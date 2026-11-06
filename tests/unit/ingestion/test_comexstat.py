"""Testes da ingestão do Comex Stat (MDIC), sem rede: respx + fixtures reais.

Comportamentos da API real que os testes fixam (vistos na captura das fixtures):
- período que atravessa a virada do ano devolve lista VAZIA com HTTP 200;
- HTTP 429 ("tente novamente em 10 segundos") aparece logo, mesmo com poucas chamadas;
- métricas vêm como texto ("53908342"), e país vem pelo nome.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from flowstream.domain.shipment import Direction
from flowstream.ingestion.comexstat import (
    COMEX_URL,
    UPDATED_URL,
    ComexRecord,
    ComexResponseError,
    ComexStatClient,
    ComexUnavailableError,
    ingest_comexstat,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "comexstat"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# Um cliente HTTP por módulo: criar httpx.Client monta o contexto SSL (~1 s no Windows).
HTTP = httpx.Client()


def client(sleeps: Sleeps | None = None) -> ComexStatClient:
    return ComexStatClient(HTTP, sleep=sleeps or Sleeps())


def rows_for(body: dict[str, Any]) -> list[dict[str, str]]:
    """Uma linha por mês pedido, no formato da API."""
    first, last = body["period"]["from"], body["period"]["to"]
    year = first[:4]
    return [
        {
            "year": year,
            "monthNumber": f"{month:02d}",
            "country": "China",
            "headingCode": "8471",
            "heading": "Máquinas automáticas para processamento de dados",
            "via": "MARITIMA",
            "metricFOB": "1000",
            "metricKG": "50",
            **({"metricFreight": "70", "metricInsurance": "3"} if body["flow"] == "import" else {}),
        }
        for month in range(int(first[5:]), int(last[5:]) + 1)
    ]


def api(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    return httpx.Response(200, json={"data": {"list": rows_for(body)}, "success": True})


# ------------------------------------------------------------------ parse e requisição


@respx.mock
def test_export_fixture_is_parsed_with_exact_decimals() -> None:
    respx.post(COMEX_URL).respond(200, text=fixture("export_2026-09_china.json"))

    records = client().fetch("export", (2026, 9), (2026, 9))

    assert len(records) == 60
    first = records[0]
    assert first.fluxo == Direction.EXPORTACAO
    assert (first.ano, first.mes) == (2026, 9)
    assert first.pais == "China"
    assert len(first.sh4_codigo) == 4
    assert isinstance(first.valor_fob_usd, Decimal)
    assert first.frete_usd is None  # frete e seguro só existem na importação


@respx.mock
def test_import_fixture_has_freight_and_insurance() -> None:
    respx.post(COMEX_URL).respond(200, text=fixture("import_2026-09_china.json"))

    first = client().fetch("import", (2026, 9), (2026, 9))[0]

    assert first.fluxo == Direction.IMPORTACAO
    assert first.sh4_codigo == "5402"
    assert first.valor_fob_usd == Decimal("41741744")
    assert first.frete_usd == Decimal("6138580")
    assert first.seguro_usd == Decimal("21920")
    assert first.peso_kg == Decimal("27648619")


@respx.mock
def test_request_body_filters_santa_catarina_sea_and_air() -> None:
    route = respx.post(COMEX_URL).mock(side_effect=api)

    client().fetch("import", (2026, 7), (2026, 9))

    body = json.loads(route.calls.last.request.content)
    assert body["flow"] == "import"
    assert body["monthDetail"] is True
    assert body["period"] == {"from": "2026-07", "to": "2026-09"}
    assert {"filter": "state", "values": ["44"]} in body["filters"]  # SC é 44 no Comex Stat
    assert {"filter": "via", "values": ["01", "04"]} in body["filters"]
    assert body["details"] == ["country", "heading", "via"]
    assert body["metrics"] == ["metricFOB", "metricKG", "metricFreight", "metricInsurance"]


@respx.mock
def test_export_does_not_ask_import_only_metrics() -> None:
    route = respx.post(COMEX_URL).mock(side_effect=api)

    client().fetch("export", (2026, 9), (2026, 9))

    assert json.loads(route.calls.last.request.content)["metrics"] == ["metricFOB", "metricKG"]


@respx.mock
def test_period_crossing_the_year_is_split_and_paused() -> None:
    route = respx.post(COMEX_URL).mock(side_effect=api)
    sleeps = Sleeps()

    records = client(sleeps).fetch("export", (2025, 11), (2026, 2))

    periods = [json.loads(c.request.content)["period"] for c in route.calls]
    assert periods == [{"from": "2025-11", "to": "2025-12"}, {"from": "2026-01", "to": "2026-02"}]
    assert {(r.ano, r.mes) for r in records} == {(2025, 11), (2025, 12), (2026, 1), (2026, 2)}
    assert sleeps.calls == [30]  # pausa entre requisições para não levar 429


# ------------------------------------------------------------------ respostas ruins


@respx.mock
def test_empty_response_is_an_error_not_an_empty_load() -> None:
    respx.post(COMEX_URL).respond(200, json={"data": {"list": []}, "success": True})

    with pytest.raises(ComexResponseError, match="2026-09"):
        client().fetch("export", (2026, 9), (2026, 9))


@respx.mock
def test_missing_month_is_detected() -> None:
    def two_of_three(request: httpx.Request) -> httpx.Response:
        rows = rows_for(json.loads(request.content))[:2]
        return httpx.Response(200, json={"data": {"list": rows}})

    respx.post(COMEX_URL).mock(side_effect=two_of_three)

    with pytest.raises(ComexResponseError, match="2026-09"):
        client().fetch("export", (2026, 7), (2026, 9))


@respx.mock
def test_missing_field_is_reported() -> None:
    row = {"year": "2026", "monthNumber": "09", "country": "China", "headingCode": "8471"}
    respx.post(COMEX_URL).respond(200, json={"data": {"list": [row]}})

    with pytest.raises(ComexResponseError, match="metricFOB"):
        client().fetch("export", (2026, 9), (2026, 9))


@respx.mock
def test_unexpected_payload_is_reported() -> None:
    respx.post(COMEX_URL).respond(200, text="<html>manutenção</html>")

    with pytest.raises(ComexResponseError):
        client().fetch("export", (2026, 9), (2026, 9))


# ------------------------------------------------------------------ falhas e retry


@respx.mock
def test_http_500_is_retried_with_backoff() -> None:
    route = respx.post(COMEX_URL)
    route.side_effect = [httpx.Response(500), api]
    sleeps = Sleeps()

    records = client(sleeps).fetch("export", (2026, 9), (2026, 9))

    assert route.call_count == 2
    assert len(records) == 1
    assert sleeps.calls == [2]


@respx.mock
def test_gives_up_after_three_transient_failures() -> None:
    route = respx.post(COMEX_URL).respond(502)

    with pytest.raises(ComexUnavailableError, match="3 tentativas"):
        client().fetch("export", (2026, 9), (2026, 9))
    assert route.call_count == 3


@respx.mock
def test_timeout_is_retried() -> None:
    route = respx.post(COMEX_URL)
    route.side_effect = [httpx.ReadTimeout("lento"), api]

    assert len(client().fetch("export", (2026, 9), (2026, 9))) == 1
    assert route.call_count == 2


@respx.mock
def test_rate_limit_waits_and_retries() -> None:
    limited = httpx.Response(429, json={"error": {"code": 429, "message": "tente em 10 segundos"}})
    route = respx.post(COMEX_URL)
    route.side_effect = [limited, limited, api]
    sleeps = Sleeps()

    records = client(sleeps).fetch("export", (2026, 9), (2026, 9))

    assert len(records) == 1
    assert sleeps.calls == [30, 30]


@respx.mock
def test_rate_limit_gives_up_eventually() -> None:
    respx.post(COMEX_URL).respond(429, json={"error": {"code": 429, "message": "limite"}})

    with pytest.raises(ComexUnavailableError, match="limite de requisições"):
        client().fetch("export", (2026, 9), (2026, 9))


@respx.mock
def test_client_error_shows_api_message_and_is_not_retried() -> None:
    route = respx.post(COMEX_URL).respond(
        400, json={"error": {"code": 400, "message": "Filtro inválido"}}
    )

    with pytest.raises(ComexUnavailableError, match="Filtro inválido"):
        client().fetch("export", (2026, 9), (2026, 9))
    assert route.call_count == 1


def test_rejects_start_after_end() -> None:
    with pytest.raises(ValueError, match="início"):
        client().fetch("export", (2026, 9), (2026, 8))


# ------------------------------------------------------------------ última atualização


@respx.mock
def test_last_available_month_comes_from_the_api() -> None:
    respx.get(UPDATED_URL).respond(200, text=fixture("dates_updated.json"))

    assert client().last_available_month() == (2026, 9)


# ------------------------------------------------------------------ serviço


class FakeSource:
    def __init__(self, last: tuple[int, int] = (2026, 9)) -> None:
        self.last = last
        self.calls: list[tuple[str, tuple[int, int], tuple[int, int]]] = []

    def last_available_month(self) -> tuple[int, int]:
        return self.last

    def fetch(self, flow: str, first: tuple[int, int], last: tuple[int, int]) -> list[ComexRecord]:
        self.calls.append((flow, first, last))
        return [_record(flow, first)]


class FakeRepository:
    def __init__(self, loaded: dict[str, tuple[int, int]] | None = None) -> None:
        self.loaded = loaded or {}
        self.rows: dict[tuple[str, tuple[int, int]], list[ComexRecord]] = {}

    def last_month(self, flow: str) -> tuple[int, int] | None:
        return self.loaded.get(flow)

    def replace_months(
        self, flow: str, first: tuple[int, int], last: tuple[int, int], records: list[ComexRecord]
    ) -> int:
        self.rows[(flow, first)] = records
        return len(records)


def _record(flow: str, month: tuple[int, int]) -> ComexRecord:
    return ComexRecord(
        fluxo=Direction.EXPORTACAO if flow == "export" else Direction.IMPORTACAO,
        ano=month[0],
        mes=month[1],
        pais="China",
        sh4_codigo="8471",
        sh4="Máquinas",
        via="MARITIMA",
        valor_fob_usd=Decimal(1),
        peso_kg=Decimal(1),
        frete_usd=None,
        seguro_usd=None,
    )


def test_empty_table_loads_the_last_24_published_months() -> None:
    source = FakeSource()

    result = ingest_comexstat(source, FakeRepository())

    # Um ano-calendário por vez: busca e grava, sem acumular a janela inteira em memória.
    years = [((2024, 10), (2024, 12)), ((2025, 1), (2025, 12)), ((2026, 1), (2026, 9))]
    assert source.calls == [(flow, a, b) for flow in ("export", "import") for a, b in years]
    assert result.rows == 6
    assert result.periods == {"export": ((2024, 10), (2026, 9)), "import": ((2024, 10), (2026, 9))}


def test_incremental_reloads_the_last_3_loaded_months_and_adds_new_ones() -> None:
    source = FakeSource()
    repo = FakeRepository(loaded={"export": (2026, 8), "import": (2026, 9)})

    ingest_comexstat(source, repo)

    assert source.calls == [
        ("export", (2026, 6), (2026, 9)),  # 06, 07, 08 recarregados (revisões) + 09 novo
        ("import", (2026, 7), (2026, 9)),  # já em dia: só os 3 últimos, por revisão
    ]


def test_incremental_never_goes_before_the_window() -> None:
    source = FakeSource()
    repo = FakeRepository(loaded={"export": (2024, 11), "import": (2024, 11)})

    ingest_comexstat(source, repo)

    assert source.calls[0] == ("export", (2024, 10), (2024, 12))


def test_full_refresh_reloads_the_whole_window() -> None:
    source = FakeSource()

    ingest_comexstat(source, FakeRepository(loaded={"export": (2026, 9)}), full_refresh=True)

    assert source.calls[:3] == [
        ("export", (2024, 10), (2024, 12)),
        ("export", (2025, 1), (2025, 12)),
        ("export", (2026, 1), (2026, 9)),
    ]


def test_window_size_is_configurable() -> None:
    source = FakeSource()

    ingest_comexstat(source, FakeRepository(), months=3)

    assert source.calls[0] == ("export", (2026, 7), (2026, 9))


def test_running_twice_does_not_duplicate() -> None:
    repo = FakeRepository()
    ingest_comexstat(FakeSource(), repo)
    ingest_comexstat(FakeSource(), repo, full_refresh=True)

    assert sum(len(v) for v in repo.rows.values()) == 6  # 2 fluxos x 3 anos


def test_record_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        ComexRecord(
            fluxo=Direction.EXPORTACAO,
            ano=2026,
            mes=13,
            pais="China",
            sh4_codigo="8471",
            sh4="x",
            via="MARITIMA",
            valor_fob_usd=Decimal(1),
            peso_kg=Decimal(1),
            frete_usd=None,
            seguro_usd=None,
        )


def test_service_writes_each_year_before_fetching_the_next() -> None:
    events: list[str] = []

    class Source(FakeSource):
        def fetch(
            self, flow: str, first: tuple[int, int], last: tuple[int, int]
        ) -> list[ComexRecord]:
            events.append(f"fetch {first[0]}")
            return super().fetch(flow, first, last)

    class Repo(FakeRepository):
        def replace_months(self, flow, first, last, records):  # type: ignore[no-untyped-def]
            events.append(f"write {first[0]}")
            return super().replace_months(flow, first, last, records)

    ingest_comexstat(Source(), Repo(), months=15)

    assert events[:4] == ["fetch 2025", "write 2025", "fetch 2026", "write 2026"]


@respx.mock
def test_client_pauses_between_service_calls() -> None:
    respx.post(COMEX_URL).mock(side_effect=api)
    respx.get(UPDATED_URL).respond(200, text=fixture("dates_updated.json"))
    sleeps = Sleeps()

    ingest_comexstat(client(sleeps), FakeRepository(), months=12)

    # 2 fluxos x 2 anos (2025-10..12 e 2026-01..09) = 4 pedidos, 3 pausas entre eles
    assert sleeps.calls == [30, 30, 30]

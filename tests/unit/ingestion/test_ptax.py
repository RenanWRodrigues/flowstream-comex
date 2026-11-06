"""Testes da ingestão da PTAX (API Olinda do Banco Central), sem rede: respx + fixtures reais."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from tenacity import wait_none

from flowstream.domain.dates import SAO_PAULO
from flowstream.ingestion.ptax import (
    CURRENCIES,
    PTAX_URL,
    PtaxClient,
    PtaxQuote,
    PtaxResponseError,
    PtaxUnavailableError,
    ingest_ptax,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ptax"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# Um cliente por módulo: criar httpx.Client monta o contexto SSL (~1 s no Windows).
# O respx intercepta as chamadas de qualquer cliente, então compartilhar é seguro.
HTTP = httpx.Client()


def client(http: httpx.Client | None = None) -> PtaxClient:
    return PtaxClient(http or HTTP, wait=wait_none(), pause_seconds=0)


# ------------------------------------------------------------------ adapter


@respx.mock
def test_fetch_parses_closing_quotes_as_exact_decimals() -> None:
    respx.get(url__startswith=PTAX_URL).respond(200, text=fixture("usd_2025-01-02_2025-01-10.json"))

    quotes = client().fetch("USD", date(2025, 1, 2), date(2025, 1, 10))

    assert len(quotes) == 7
    first = quotes[0]
    assert first.moeda == "USD"
    assert first.data_cotacao == date(2025, 1, 2)
    assert first.cotacao_compra == Decimal("6.208")
    assert first.cotacao_venda == Decimal("6.2086")  # sem passar por float
    assert first.tipo_boletim == "Fechamento"
    assert first.data_hora_cotacao.tzinfo is SAO_PAULO
    assert first.data_hora_cotacao.hour == 13


@respx.mock
def test_fetch_keeps_parity_for_other_currencies() -> None:
    respx.get(url__startswith=PTAX_URL).respond(200, text=fixture("eur_2025-01-02_2025-01-10.json"))

    first = client().fetch("EUR", date(2025, 1, 2), date(2025, 1, 10))[0]

    assert first.paridade_compra == Decimal("1.0274")
    assert first.cotacao_venda == Decimal("6.3793")


@respx.mock
def test_request_uses_literal_odata_syntax_and_american_dates() -> None:
    route = respx.get(url__startswith=PTAX_URL).respond(200, text='{"value": []}')

    client().fetch("EUR", date(2025, 1, 2), date(2025, 1, 10))

    sent = str(route.calls.last.request.url)
    assert "@moeda='EUR'" in sent  # @ e aspas literais: codificados, o Olinda responde 400
    assert "@dataInicial='01-02-2025'" in sent  # MM-DD-AAAA
    assert "@dataFinalCotacao='01-10-2025'" in sent
    assert "$filter=tipoBoletim%20eq%20'Fechamento'" in sent
    assert "$format=json" in sent


@respx.mock
def test_weekend_returns_empty_list() -> None:
    respx.get(url__startswith=PTAX_URL).respond(200, text=fixture("usd_fim_de_semana_vazio.json"))

    assert client().fetch("USD", date(2025, 1, 4), date(2025, 1, 5)) == []


@respx.mock
def test_long_period_is_split_by_year() -> None:
    route = respx.get(url__startswith=PTAX_URL).respond(200, text='{"value": []}')

    client().fetch("USD", date(2024, 1, 1), date(2025, 3, 31))

    urls = [str(call.request.url) for call in route.calls]
    assert len(urls) == 2
    assert "@dataInicial='01-01-2024'" in urls[0]
    assert "@dataFinalCotacao='12-31-2024'" in urls[0]
    assert "@dataInicial='01-01-2025'" in urls[1]
    assert "@dataFinalCotacao='03-31-2025'" in urls[1]


@respx.mock
def test_http_500_is_retried() -> None:
    route = respx.get(url__startswith=PTAX_URL)
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(200, text=fixture("usd_2025-01-02_2025-01-10.json")),
    ]

    quotes = client().fetch("USD", date(2025, 1, 2), date(2025, 1, 10))

    assert route.call_count == 2
    assert len(quotes) == 7


@respx.mock
def test_gives_up_after_three_attempts() -> None:
    route = respx.get(url__startswith=PTAX_URL).respond(503)

    with pytest.raises(PtaxUnavailableError, match="3 tentativas"):
        client().fetch("USD", date(2025, 1, 2), date(2025, 1, 10))
    assert route.call_count == 3


@respx.mock
def test_timeout_is_retried_then_fails_clearly() -> None:
    route = respx.get(url__startswith=PTAX_URL)
    route.side_effect = httpx.ReadTimeout("lento")

    with pytest.raises(PtaxUnavailableError):
        client().fetch("USD", date(2025, 1, 2), date(2025, 1, 10))
    assert route.call_count == 3


@respx.mock
def test_client_error_is_not_retried() -> None:
    route = respx.get(url__startswith=PTAX_URL).respond(400, text="Bad Request")

    with pytest.raises(PtaxUnavailableError, match="400"):
        client().fetch("USD", date(2025, 1, 2), date(2025, 1, 10))
    assert route.call_count == 1


@respx.mock
def test_missing_field_is_reported() -> None:
    body = '{"value": [{"cotacaoCompra": 6.2, "dataHoraCotacao": "2025-01-02 13:09:42.489"}]}'
    respx.get(url__startswith=PTAX_URL).respond(200, text=body)

    with pytest.raises(PtaxResponseError, match="cotacaoVenda"):
        client().fetch("USD", date(2025, 1, 2), date(2025, 1, 2))


@respx.mock
def test_unexpected_payload_is_reported() -> None:
    respx.get(url__startswith=PTAX_URL).respond(200, text="<html>manutenção</html>")

    with pytest.raises(PtaxResponseError):
        client().fetch("USD", date(2025, 1, 2), date(2025, 1, 2))


def test_rejects_start_after_end() -> None:
    with pytest.raises(ValueError, match="início"):
        client().fetch("USD", date(2025, 2, 1), date(2025, 1, 1))


@pytest.mark.parametrize("bad", ["0", "-6.1"])
def test_quote_must_be_positive(bad: str) -> None:
    with pytest.raises(ValueError):
        PtaxQuote(
            moeda="USD",
            data_cotacao=date(2025, 1, 2),
            cotacao_compra=Decimal(bad),
            cotacao_venda=Decimal("6.2"),
            paridade_compra=Decimal(1),
            paridade_venda=Decimal(1),
            data_hora_cotacao="2025-01-02T13:09:42-03:00",  # type: ignore[arg-type]
            tipo_boletim="Fechamento",
        )


# ------------------------------------------------------------------ serviço (incremental)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date, date]] = []

    def fetch(self, moeda: str, start: date, end: date) -> list[PtaxQuote]:
        self.calls.append((moeda, start, end))
        return [_quote(moeda, start)]


class FakeRepository:
    def __init__(self, last: dict[str, date] | None = None) -> None:
        self.last = last or {}
        self.rows: dict[tuple[str, date], PtaxQuote] = {}

    def last_date(self, moeda: str) -> date | None:
        return self.last.get(moeda)

    def upsert(self, quotes: list[PtaxQuote]) -> int:
        for q in quotes:
            self.rows[(q.moeda, q.data_cotacao)] = q
        return len(quotes)


def _quote(moeda: str, day: date) -> PtaxQuote:
    return PtaxQuote(
        moeda=moeda,  # type: ignore[arg-type]
        data_cotacao=day,
        cotacao_compra=Decimal("5.1"),
        cotacao_venda=Decimal("5.2"),
        paridade_compra=Decimal(1),
        paridade_venda=Decimal(1),
        data_hora_cotacao=f"{day.isoformat()}T13:00:00-03:00",  # type: ignore[arg-type]
        tipo_boletim="Fechamento",
    )


def test_empty_table_loads_from_start() -> None:
    fake = FakeClient()

    result = ingest_ptax(fake, FakeRepository(), date(2024, 1, 1), date(2024, 3, 31))

    assert fake.calls == [(m, date(2024, 1, 1), date(2024, 3, 31)) for m in ("USD", "EUR")]
    assert result.rows == 2


def test_incremental_asks_only_for_the_missing_period() -> None:
    fake = FakeClient()
    repo = FakeRepository(last={"USD": date(2025, 1, 8), "EUR": date(2025, 1, 10)})

    ingest_ptax(fake, repo, date(2024, 1, 1), date(2025, 1, 10))

    assert fake.calls == [("USD", date(2025, 1, 9), date(2025, 1, 10))]  # só o que falta
    # EUR já está em dia: nenhuma chamada


def test_empty_currency_loads_from_start_while_other_is_incremental() -> None:
    fake = FakeClient()
    repo = FakeRepository(last={"USD": date(2025, 1, 8)})

    ingest_ptax(fake, repo, date(2024, 1, 1), date(2025, 1, 10))

    assert fake.calls == [
        ("USD", date(2025, 1, 9), date(2025, 1, 10)),
        ("EUR", date(2024, 1, 1), date(2025, 1, 10)),  # vazia: desde o início
    ]


def test_currencies_are_the_ones_published_by_ptax() -> None:
    # A API PTAX não publica CNY: pedi-lo devolve lista vazia em silêncio (visto na API real).
    assert CURRENCIES == ("USD", "EUR")


@pytest.mark.parametrize("moeda", ["CNY", "BRL", "usd"])
def test_fetch_refuses_currency_without_ptax(moeda: str) -> None:
    with pytest.raises(ValueError, match="não publica PTAX"):
        client().fetch(moeda, date(2025, 1, 2), date(2025, 1, 10))  # type: ignore[arg-type]


def test_full_refresh_ignores_what_is_loaded() -> None:
    fake = FakeClient()
    repo = FakeRepository(last={"USD": date(2025, 1, 8)})

    ingest_ptax(
        fake, repo, date(2024, 1, 1), date(2025, 1, 10), full_refresh=True, currencies=("USD",)
    )

    assert fake.calls == [("USD", date(2024, 1, 1), date(2025, 1, 10))]


def test_running_twice_does_not_duplicate() -> None:
    repo = FakeRepository()
    ingest_ptax(FakeClient(), repo, date(2025, 1, 2), date(2025, 1, 2), full_refresh=True)
    ingest_ptax(FakeClient(), repo, date(2025, 1, 2), date(2025, 1, 2), full_refresh=True)

    assert len(repo.rows) == 2

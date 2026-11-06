"""Ingestão do Comex Stat (MDIC): exportação e importação de Santa Catarina para bronze.comexstat.

Grão: fluxo x mês x país x posição SH4 x via (marítima e aérea). Detalhes em docs/fontes.md.

Armadilhas da API real, todas tratadas aqui:
- período que atravessa a virada do ano devolve lista vazia com HTTP 200 -> um pedido por ano;
- resposta sem algum mês pedido nunca é aceita (vazio silencioso vira erro);
- HTTP 429 frequente -> pausa entre pedidos e espera longa antes de tentar de novo;
- métricas vêm como texto -> Decimal direto.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine, text

from flowstream.db import create_db_engine, transaction
from flowstream.domain.shipment import Direction
from flowstream.logging import get_logger
from flowstream.pipeline_runs import finish_run, start_run

API = "https://api-comexstat.mdic.gov.br"
COMEX_URL = f"{API}/general?language=pt"
UPDATED_URL = f"{API}/general/dates/updated"
PIPELINE = "ingest_comexstat"

SANTA_CATARINA = "44"  # código do Comex Stat (não é o 42 do IBGE)
VIAS = ["01", "04"]  # 01 marítima, 04 aérea
DETAILS = ["country", "heading", "via"]
TIMEOUT_SECONDS = 120
ATTEMPTS = 3
WINDOW_MONTHS = 24
RELOAD_RECENT_MONTHS = 3  # o MDIC revisa os meses recentes

Flow = Literal["export", "import"]
FLOWS: tuple[Flow, ...] = ("export", "import")
Month = tuple[int, int]  # (ano, mês)

_DIRECTION = {"export": Direction.EXPORTACAO, "import": Direction.IMPORTACAO}
_METRICS: dict[Flow, list[str]] = {
    "export": ["metricFOB", "metricKG"],
    "import": ["metricFOB", "metricKG", "metricFreight", "metricInsurance"],
}
_REQUIRED = ["year", "monthNumber", "country", "headingCode", "heading", "via"]

logger = get_logger(__name__)


class ComexResponseError(ValueError):
    """Resposta da API fora do formato esperado ou incompleta."""


class ComexUnavailableError(RuntimeError):
    """A API não respondeu com sucesso depois das tentativas."""


# ------------------------------------------------------------------ domain


class ComexRecord(BaseModel):
    """Comércio de SC em um mês, com um país, numa posição SH4, por uma via."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fluxo: Direction
    ano: int = Field(ge=1997)
    mes: int = Field(ge=1, le=12)
    pais: str = Field(min_length=1)
    sh4_codigo: str = Field(pattern=r"^\d{4}$")
    sh4: str
    via: str
    valor_fob_usd: Decimal = Field(ge=0)
    peso_kg: Decimal = Field(ge=0)
    frete_usd: Decimal | None = Field(default=None, ge=0)
    seguro_usd: Decimal | None = Field(default=None, ge=0)


def parse_records(flow: Flow, body: str) -> list[ComexRecord]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise ComexResponseError("A resposta do Comex Stat não é JSON.") from None
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ComexResponseError("A resposta do Comex Stat não tem data.list.")
    return [_record(flow, item) for item in items]


def _record(flow: Flow, item: dict[str, Any]) -> ComexRecord:
    missing = [name for name in [*_REQUIRED, *_METRICS[flow]] if name not in item]
    if missing:
        raise ComexResponseError(f"Campo ausente na resposta do Comex Stat: {', '.join(missing)}.")
    try:
        imports = flow == "import"
        return ComexRecord(
            fluxo=_DIRECTION[flow],
            ano=int(item["year"]),
            mes=int(item["monthNumber"]),
            pais=item["country"],
            sh4_codigo=item["headingCode"],
            sh4=item["heading"],
            via=item["via"],
            valor_fob_usd=Decimal(item["metricFOB"]),
            peso_kg=Decimal(item["metricKG"]),
            frete_usd=Decimal(item["metricFreight"]) if imports else None,
            seguro_usd=Decimal(item["metricInsurance"]) if imports else None,
        )
    except (ValueError, InvalidOperation, ValidationError) as exc:
        raise ComexResponseError(f"Registro inválido do Comex Stat: {exc}") from None


def months_between(first: Month, last: Month) -> list[Month]:
    count = (last[0] - first[0]) * 12 + last[1] - first[1]
    return [shift(first, i) for i in range(count + 1)]


def shift(month: Month, delta: int) -> Month:
    index = month[0] * 12 + month[1] - 1 + delta
    return index // 12, index % 12 + 1


def _label(month: Month) -> str:
    return f"{month[0]}-{month[1]:02d}"


# ------------------------------------------------------------------ adapter: HTTP


class ComexStatClient:
    """Consulta o POST /general, um ano-calendário por requisição."""

    def __init__(
        self,
        http: httpx.Client | None = None,
        *,
        pause_seconds: float = 30.0,
        rate_limit_wait: float = 30.0,
        rate_limit_attempts: int = 10,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http or httpx.Client()
        self._pause = pause_seconds
        self._rate_wait = rate_limit_wait
        self._rate_attempts = rate_limit_attempts
        self._sleep = sleep
        self._posts = 0  # a pausa vale entre quaisquer dois pedidos deste cliente

    def last_available_month(self) -> Month:
        body = self._send(lambda: self._http.get(UPDATED_URL, timeout=TIMEOUT_SECONDS))
        try:
            data = json.loads(body)["data"]
            return int(data["year"]), int(data["monthNumber"])
        except (ValueError, KeyError, TypeError):
            raise ComexResponseError("Resposta inesperada em /general/dates/updated.") from None

    def fetch(self, flow: Flow, first: Month, last: Month) -> list[ComexRecord]:
        if first > last:
            raise ValueError(
                f"Mês de início ({_label(first)}) posterior ao final ({_label(last)})."
            )
        records: list[ComexRecord] = []
        for start, end in year_chunks(first, last):
            chunk = parse_records(flow, self._post(flow, start, end))
            _check_months(chunk, start, end)
            records += chunk
        return records

    def _post(self, flow: Flow, start: Month, end: Month) -> str:
        if self._posts and self._pause:
            self._sleep(self._pause)  # evita o HTTP 429
        self._posts += 1
        body = {
            "flow": flow,
            "monthDetail": True,
            "period": {"from": _label(start), "to": _label(end)},
            "filters": [
                {"filter": "state", "values": [SANTA_CATARINA]},
                {"filter": "via", "values": VIAS},
            ],
            "details": DETAILS,
            "metrics": _METRICS[flow],
        }
        return self._send(lambda: self._http.post(COMEX_URL, json=body, timeout=TIMEOUT_SECONDS))

    def _send(self, request: Callable[[], httpx.Response]) -> str:
        """Retry: 429 espera `rate_limit_wait`; 5xx e rede, até 3 vezes com backoff 2, 4 s."""
        failures = limited = 0
        while True:
            try:
                response = request()
                if response.status_code == 429:
                    limited += 1
                    if limited >= self._rate_attempts:
                        raise ComexUnavailableError(
                            "Comex Stat: limite de requisições (HTTP 429) "
                            f"após {limited} tentativas."
                        )
                    self._sleep(self._rate_wait)
                    continue
                response.raise_for_status()
                return response.text
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise ComexUnavailableError(
                        f"Comex Stat recusou o pedido: HTTP {exc.response.status_code} "
                        f"{_api_message(exc.response)}"
                    ) from None
                failures += 1
                reason = f"HTTP {exc.response.status_code}"
            except httpx.TransportError as exc:
                failures += 1
                reason = type(exc).__name__
            if failures >= ATTEMPTS:
                raise ComexUnavailableError(
                    f"Comex Stat indisponível: {reason} após {ATTEMPTS} tentativas."
                )
            self._sleep(2.0**failures)


def _api_message(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return response.text[:200]


def year_chunks(first: Month, last: Month) -> list[tuple[Month, Month]]:
    """Divide o período por ano-calendário (a API devolve vazio se o período vira o ano)."""
    return [(max(first, (year, 1)), min(last, (year, 12))) for year in range(first[0], last[0] + 1)]


def _check_months(records: list[ComexRecord], start: Month, end: Month) -> None:
    got = {(r.ano, r.mes) for r in records}
    missing = [m for m in months_between(start, end) if m not in got]
    if missing:
        raise ComexResponseError(
            "O Comex Stat não devolveu dados para "
            f"{', '.join(_label(m) for m in missing)} "
            "(SC sempre tem comércio: resposta incompleta)."
        )


# ------------------------------------------------------------------ adapter: Postgres


class PostgresComexRepository:
    """Substitui os meses carregados em bronze.comexstat (apaga e insere, numa transação)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def last_month(self, flow: Flow) -> Month | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "select ano, mes from bronze.comexstat where fluxo = :fluxo "
                    "order by ano desc, mes desc limit 1"
                ),
                {"fluxo": _DIRECTION[flow].value},
            ).first()
        return (int(row[0]), int(row[1])) if row else None

    def replace_months(
        self, flow: Flow, first: Month, last: Month, records: list[ComexRecord]
    ) -> int:
        with transaction(self._engine) as conn:
            conn.execute(
                text(
                    "delete from bronze.comexstat where fluxo = :fluxo "
                    "and ano * 100 + mes between :first and :last"
                ),
                {
                    "fluxo": _DIRECTION[flow].value,
                    "first": first[0] * 100 + first[1],
                    "last": last[0] * 100 + last[1],
                },
            )
            if records:
                conn.execute(
                    text(
                        """
                        insert into bronze.comexstat (fluxo, ano, mes, pais, sh4_codigo, sh4, via,
                            valor_fob_usd, peso_kg, frete_usd, seguro_usd)
                        values (:fluxo, :ano, :mes, :pais, :sh4_codigo, :sh4, :via,
                            :valor_fob_usd, :peso_kg, :frete_usd, :seguro_usd)
                        """
                    ),
                    [r.model_dump(mode="json") for r in records],
                )
        return len(records)


# ------------------------------------------------------------------ service


class ComexSource(Protocol):
    def last_available_month(self) -> Month: ...

    def fetch(self, flow: Flow, first: Month, last: Month) -> list[ComexRecord]: ...


class ComexRepository(Protocol):
    def last_month(self, flow: Flow) -> Month | None: ...

    def replace_months(
        self, flow: Flow, first: Month, last: Month, records: list[ComexRecord]
    ) -> int: ...


@dataclass(frozen=True)
class ComexIngestResult:
    rows: int
    periods: dict[str, tuple[Month, Month]]


def ingest_comexstat(
    source: ComexSource,
    repository: ComexRepository,
    *,
    full_refresh: bool = False,
    months: int = WINDOW_MONTHS,
) -> ComexIngestResult:
    """Carrega a janela dos últimos `months` meses publicados; o incremental refaz os 3 últimos."""
    last = source.last_available_month()
    window_start = shift(last, -(months - 1))
    rows = 0
    periods: dict[str, tuple[Month, Month]] = {}
    for flow in FLOWS:
        loaded = None if full_refresh else repository.last_month(flow)
        first = window_start
        if loaded is not None:
            first = max(window_start, shift(min(loaded, last), -(RELOAD_RECENT_MONTHS - 1)))
        # Um ano por vez: busca e grava antes do próximo, para não acumular ~300 mil
        # registros em memória (a janela inteira chegava a ~830 MB de pico).
        for start, end in year_chunks(first, last):
            records = source.fetch(flow, start, end)
            rows += repository.replace_months(flow, start, end, records)
            logger.info("Comex Stat %s: %s a %s, %s linhas", flow, start, end, len(records))
        periods[flow] = (first, last)
    return ComexIngestResult(rows=rows, periods=periods)


def run_comexstat(
    *,
    full_refresh: bool = False,
    months: int = WINDOW_MONTHS,
    engine: Engine | None = None,
    source: ComexSource | None = None,
) -> ComexIngestResult:
    """Ingestão completa, registrada em ops.pipeline_runs."""
    engine = engine or create_db_engine()
    run_id = start_run(engine, PIPELINE)
    try:
        result = ingest_comexstat(
            source or ComexStatClient(),
            PostgresComexRepository(engine),
            full_refresh=full_refresh,
            months=months,
        )
    except Exception as exc:
        finish_run(engine, run_id, error=exc)
        raise
    finish_run(engine, run_id, rows_in=result.rows, rows_out=result.rows)
    return result

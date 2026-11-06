"""Ingestão da PTAX (cotação oficial de fechamento do Banco Central) para bronze.ptax.

Fonte: API Olinda do BCB (OData). Detalhes e limitações em docs/fontes.md.
- domain: PtaxQuote e o parse da resposta (valores lidos direto em Decimal)
- adapter: PtaxClient (HTTP com retry) e PostgresPtaxRepository (upsert)
- service: ingest_ptax (incremental) e run_ptax (com registro em ops.pipeline_runs)
"""

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine, text
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential
from tenacity.wait import wait_base

from flowstream.db import create_db_engine, transaction
from flowstream.domain.dates import SAO_PAULO
from flowstream.logging import get_logger
from flowstream.pipeline_runs import finish_run, start_run

PTAX_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
)
PIPELINE = "ingest_ptax"
TIMEOUT_SECONDS = 30
ATTEMPTS = 3

# A PTAX só é publicada para 10 moedas (endpoint Moedas); o yuan (CNY) não está entre elas.
# Pedir uma moeda sem PTAX não dá erro na API: devolve lista vazia. Por isso a checagem.
PtaxCurrency = Literal["USD", "EUR"]
CURRENCIES: tuple[PtaxCurrency, ...] = ("USD", "EUR")

logger = get_logger(__name__)


class PtaxResponseError(ValueError):
    """A resposta da API não tem o formato esperado."""


class PtaxUnavailableError(RuntimeError):
    """A API não respondeu com sucesso depois das tentativas."""


# ------------------------------------------------------------------ domain


class PtaxQuote(BaseModel):
    """Cotação de fechamento (PTAX) de uma moeda em um dia útil, em R$ por unidade."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    moeda: PtaxCurrency
    data_cotacao: date
    cotacao_compra: Decimal = Field(gt=0)
    cotacao_venda: Decimal = Field(gt=0)
    paridade_compra: Decimal = Field(gt=0)
    paridade_venda: Decimal = Field(gt=0)
    data_hora_cotacao: datetime
    tipo_boletim: str


_FIELDS = {
    "cotacaoCompra": "cotacao_compra",
    "cotacaoVenda": "cotacao_venda",
    "paridadeCompra": "paridade_compra",
    "paridadeVenda": "paridade_venda",
    "dataHoraCotacao": "data_hora_cotacao",
    "tipoBoletim": "tipo_boletim",
}


def parse_quotes(moeda: PtaxCurrency, body: str) -> list[PtaxQuote]:
    """Converte o JSON da API em cotações. Números viram Decimal sem passar por float."""
    try:
        payload = json.loads(body, parse_float=Decimal)
    except json.JSONDecodeError:
        raise PtaxResponseError("A resposta da PTAX não é JSON.") from None
    items = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise PtaxResponseError("A resposta da PTAX não tem a lista 'value'.")
    return [_quote(moeda, item) for item in items]


def _quote(moeda: PtaxCurrency, item: dict[str, Any]) -> PtaxQuote:
    missing = [name for name in _FIELDS if name not in item]
    if missing:
        raise PtaxResponseError(f"Campo ausente na resposta da PTAX: {', '.join(missing)}.")
    try:
        # A API devolve a hora de Brasília sem fuso: "2025-01-02 13:09:42.489".
        moment = datetime.fromisoformat(item["dataHoraCotacao"]).replace(tzinfo=SAO_PAULO)
        values = {target: item[source] for source, target in _FIELDS.items()}
        values["data_hora_cotacao"] = moment
        return PtaxQuote(moeda=moeda, data_cotacao=moment.date(), **values)
    except (ValueError, ValidationError) as exc:
        raise PtaxResponseError(f"Cotação inválida na resposta da PTAX: {exc}") from None


# ------------------------------------------------------------------ adapter: HTTP


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):  # timeout, conexão recusada...
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


class PtaxClient:
    """Busca as cotações de fechamento na API Olinda, um ano por requisição."""

    def __init__(
        self,
        http: httpx.Client | None = None,
        *,
        url: str = PTAX_URL,
        wait: wait_base | None = None,
        pause_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http or httpx.Client()
        self._url = url
        self._wait = wait or wait_exponential(multiplier=1, min=1, max=10)
        self._pause = pause_seconds
        self._sleep = sleep

    def fetch(self, moeda: PtaxCurrency, start: date, end: date) -> list[PtaxQuote]:
        if moeda not in CURRENCIES:
            raise ValueError(f"O Banco Central não publica PTAX para {moeda!r}; use {CURRENCIES}.")
        if start > end:
            raise ValueError(f"Data de início ({start}) posterior à data final ({end}).")
        quotes: list[PtaxQuote] = []
        for index, (first, last) in enumerate(_years(start, end)):
            if index and self._pause:
                self._sleep(self._pause)  # respeita a API entre requisições
            quotes += parse_quotes(moeda, self._get(self._query_url(moeda, first, last)))
        return quotes

    def _query_url(self, moeda: str, first: date, last: date) -> str:
        # Sintaxe OData literal: @, $ e aspas não podem ser codificados (senão HTTP 400).
        return (
            f"{self._url}?@moeda='{moeda}'"
            f"&@dataInicial='{first:%m-%d-%Y}'&@dataFinalCotacao='{last:%m-%d-%Y}'"
            "&$filter=tipoBoletim%20eq%20'Fechamento'&$format=json"
        )

    def _get(self, url: str) -> str:
        retrying = Retrying(
            stop=stop_after_attempt(ATTEMPTS),
            wait=self._wait,
            retry=retry_if_exception(_is_transient),
            reraise=True,
        )
        try:
            for attempt in retrying:
                with attempt:
                    response = self._http.get(url, timeout=TIMEOUT_SECONDS)
                    response.raise_for_status()
                    return response.text
        except httpx.HTTPError as exc:
            tries = retrying.statistics.get("attempt_number", 1)
            reason = (
                f"HTTP {exc.response.status_code}"
                if isinstance(exc, httpx.HTTPStatusError)
                else type(exc).__name__
            )
            plural = "tentativas" if tries > 1 else "tentativa"
            raise PtaxUnavailableError(
                f"PTAX indisponível: {reason} após {tries} {plural}."
            ) from None
        raise PtaxUnavailableError("PTAX sem resposta.")  # pragma: no cover - inalcançável


def _years(start: date, end: date) -> Iterator[tuple[date, date]]:
    for year in range(start.year, end.year + 1):
        yield max(start, date(year, 1, 1)), min(end, date(year, 12, 31))


# ------------------------------------------------------------------ adapter: Postgres


class PostgresPtaxRepository:
    """Upsert em bronze.ptax pela chave natural (moeda, data_cotacao)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def last_date(self, moeda: PtaxCurrency) -> date | None:
        with self._engine.connect() as conn:
            value = conn.execute(
                text("select max(data_cotacao) from bronze.ptax where moeda = :moeda"),
                {"moeda": moeda},
            ).scalar_one()
        return value if isinstance(value, date) else None

    def upsert(self, quotes: list[PtaxQuote]) -> int:
        if not quotes:
            return 0
        with transaction(self._engine) as conn:
            conn.execute(
                text(
                    """
                    insert into bronze.ptax (moeda, data_cotacao, cotacao_compra, cotacao_venda,
                        paridade_compra, paridade_venda, data_hora_cotacao, tipo_boletim)
                    values (:moeda, :data_cotacao, :cotacao_compra, :cotacao_venda,
                        :paridade_compra, :paridade_venda, :data_hora_cotacao, :tipo_boletim)
                    on conflict (moeda, data_cotacao) do update set
                        cotacao_compra = excluded.cotacao_compra,
                        cotacao_venda = excluded.cotacao_venda,
                        paridade_compra = excluded.paridade_compra,
                        paridade_venda = excluded.paridade_venda,
                        data_hora_cotacao = excluded.data_hora_cotacao,
                        tipo_boletim = excluded.tipo_boletim,
                        loaded_at = now()
                    """
                ),
                [q.model_dump() for q in quotes],
            )
        return len(quotes)


# ------------------------------------------------------------------ service


class QuoteSource(Protocol):
    def fetch(self, moeda: PtaxCurrency, start: date, end: date) -> list[PtaxQuote]: ...


class PtaxRepository(Protocol):
    def last_date(self, moeda: PtaxCurrency) -> date | None: ...

    def upsert(self, quotes: list[PtaxQuote]) -> int: ...


@dataclass(frozen=True)
class PtaxIngestResult:
    rows: int
    periods: dict[str, tuple[date, date]] = field(default_factory=dict)


def ingest_ptax(
    source: QuoteSource,
    repository: PtaxRepository,
    start: date,
    end: date,
    *,
    full_refresh: bool = False,
    currencies: tuple[PtaxCurrency, ...] = CURRENCIES,
) -> PtaxIngestResult:
    """Carrega cada moeda a partir do dia seguinte ao último já carregado (ou de `start`)."""
    rows = 0
    periods: dict[str, tuple[date, date]] = {}
    for moeda in currencies:
        last = None if full_refresh else repository.last_date(moeda)
        begin = last + timedelta(days=1) if last is not None else start
        if begin > end:
            logger.info("PTAX %s já está em dia até %s", moeda, last)
            continue
        rows += repository.upsert(source.fetch(moeda, begin, end))
        periods[moeda] = (begin, end)
    return PtaxIngestResult(rows=rows, periods=periods)


def run_ptax(
    start: date,
    end: date,
    *,
    full_refresh: bool = False,
    engine: Engine | None = None,
    source: QuoteSource | None = None,
) -> PtaxIngestResult:
    """Ingestão completa, registrada em ops.pipeline_runs."""
    engine = engine or create_db_engine()
    run_id = start_run(engine, PIPELINE)
    try:
        result = ingest_ptax(
            source or PtaxClient(),
            PostgresPtaxRepository(engine),
            start,
            end,
            full_refresh=full_refresh,
        )
    except Exception as exc:
        finish_run(engine, run_id, error=exc)
        raise
    finish_run(engine, run_id, rows_in=result.rows, rows_out=result.rows)
    logger.info("PTAX: %s cotações carregadas", result.rows)
    return result

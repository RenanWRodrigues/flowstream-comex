"""Ingestão da PTAX no Postgres, com fonte falsa (sem rede): upsert, incremental e log."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from flowstream.config import load_settings
from flowstream.db import PostgresMigrationStore, create_db_engine, migrate
from flowstream.ingestion.ptax import PtaxQuote, run_ptax

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
TEST_CURRENCY_DAYS = [date(1999, 1, 4), date(1999, 1, 5)]  # datas antigas: não colidem com reais


class FakeSource:
    def __init__(self, value: str = "5.1234") -> None:
        self.value = Decimal(value)
        self.calls: list[tuple[str, date, date]] = []

    def fetch(self, moeda: str, start: date, end: date) -> list[PtaxQuote]:
        self.calls.append((moeda, start, end))
        return [
            PtaxQuote(
                moeda=moeda,  # type: ignore[arg-type]
                data_cotacao=day,
                cotacao_compra=self.value,
                cotacao_venda=self.value,
                paridade_compra=Decimal(1),
                paridade_venda=Decimal(1),
                data_hora_cotacao=f"{day.isoformat()}T13:09:42.489-03:00",  # type: ignore[arg-type]
                tipo_boletim="Fechamento",
            )
            for day in TEST_CURRENCY_DAYS
            if start <= day <= end
        ]


@pytest.fixture
def engine() -> Iterator[Engine]:
    db_engine = create_db_engine(load_settings())
    migrate(ROOT / "infra" / "migrations", store=PostgresMigrationStore(db_engine))
    yield db_engine
    with db_engine.begin() as conn:
        conn.execute(text("delete from bronze.ptax where data_cotacao < '2000-01-01'"))
    db_engine.dispose()


def rows(engine: Engine) -> list[tuple[str, date, Decimal]]:
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "select moeda, data_cotacao, cotacao_venda from bronze.ptax "
                "where data_cotacao < '2000-01-01' order by moeda, data_cotacao"
            )
        )
        return [tuple(r) for r in result]  # type: ignore[misc]


def test_full_refresh_twice_does_not_duplicate(engine: Engine) -> None:
    for _ in range(2):
        run_ptax(
            date(1999, 1, 1),
            date(1999, 1, 31),
            full_refresh=True,
            engine=engine,
            source=FakeSource(),
        )

    assert len(rows(engine)) == 4  # 2 moedas x 2 dias


def test_upsert_updates_existing_quote(engine: Engine) -> None:
    run_ptax(
        date(1999, 1, 1),
        date(1999, 1, 31),
        full_refresh=True,
        engine=engine,
        source=FakeSource("5.1"),
    )
    run_ptax(
        date(1999, 1, 1),
        date(1999, 1, 31),
        full_refresh=True,
        engine=engine,
        source=FakeSource("5.2"),
    )

    assert {value for _, _, value in rows(engine)} == {Decimal("5.200000")}


def test_run_is_recorded_in_pipeline_runs(engine: Engine) -> None:
    run_ptax(
        date(1999, 1, 1), date(1999, 1, 31), full_refresh=True, engine=engine, source=FakeSource()
    )

    with engine.connect() as conn:
        status, rows_out = conn.execute(
            text(
                "select status, rows_out from ops.pipeline_runs "
                "where pipeline = 'ingest_ptax' order by id desc limit 1"
            )
        ).one()
    assert (status, rows_out) == ("SUCESSO", 4)


def test_failure_is_recorded_as_error(engine: Engine) -> None:
    class Broken:
        def fetch(self, moeda: str, start: date, end: date) -> list[PtaxQuote]:
            raise RuntimeError("API fora do ar")

    with pytest.raises(RuntimeError):
        run_ptax(
            date(1999, 1, 1), date(1999, 1, 31), full_refresh=True, engine=engine, source=Broken()
        )

    with engine.connect() as conn:
        status, error = conn.execute(
            text(
                "select status, error from ops.pipeline_runs "
                "where pipeline = 'ingest_ptax' order by id desc limit 1"
            )
        ).one()
    assert status == "ERRO"
    assert "API fora do ar" in error

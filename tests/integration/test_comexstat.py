"""Ingestão do Comex Stat no Postgres, com fonte falsa (sem rede): substituição e log."""

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from flowstream.config import load_settings
from flowstream.db import PostgresMigrationStore, create_db_engine, migrate
from flowstream.domain.shipment import Direction
from flowstream.ingestion.comexstat import ComexRecord, Flow, Month, months_between, run_comexstat

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
TEST_LAST: Month = (1998, 3)  # anos antigos: não colidem com a carga real


class FakeSource:
    def __init__(self, countries: tuple[str, ...] = ("China", "Japão")) -> None:
        self.countries = countries

    def last_available_month(self) -> Month:
        return TEST_LAST

    def fetch(self, flow: Flow, first: Month, last: Month) -> list[ComexRecord]:
        return [
            ComexRecord(
                fluxo=Direction.EXPORTACAO if flow == "export" else Direction.IMPORTACAO,
                ano=year,
                mes=month,
                pais=country,
                sh4_codigo="0207",
                sh4="Carnes e miudezas de aves",
                via="MARITIMA",
                valor_fob_usd=Decimal("1000.50"),
                peso_kg=Decimal(500),
                frete_usd=Decimal(80) if flow == "import" else None,
                seguro_usd=Decimal(2) if flow == "import" else None,
            )
            for year, month in months_between(first, last)
            for country in self.countries
        ]


@pytest.fixture
def engine() -> Iterator[Engine]:
    db_engine = create_db_engine(load_settings())
    migrate(ROOT / "infra" / "migrations", store=PostgresMigrationStore(db_engine))
    yield db_engine
    with db_engine.begin() as conn:
        conn.execute(text("delete from bronze.comexstat where ano < 2000"))
    db_engine.dispose()


def count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("select count(*) from bronze.comexstat where ano < 2000")
            ).scalar_one()
        )


def test_full_load_twice_does_not_duplicate(engine: Engine) -> None:
    for _ in range(2):
        run_comexstat(full_refresh=True, months=3, engine=engine, source=FakeSource())

    assert count(engine) == 2 * 3 * 2  # fluxos x meses x países


def test_reload_removes_rows_that_disappeared_in_a_revision(engine: Engine) -> None:
    run_comexstat(full_refresh=True, months=3, engine=engine, source=FakeSource())
    run_comexstat(months=3, engine=engine, source=FakeSource(countries=("China",)))

    assert count(engine) == 2 * 3 * 1  # o "Japão" revisado some dos meses recarregados


def test_import_keeps_freight_and_export_has_none(engine: Engine) -> None:
    run_comexstat(full_refresh=True, months=1, engine=engine, source=FakeSource())

    with engine.connect() as conn:
        result = dict(
            conn.execute(
                text(
                    "select fluxo, max(frete_usd) from bronze.comexstat "
                    "where ano < 2000 group by fluxo"
                )
            ).all()
        )
    assert result == {"EXPORTACAO": None, "IMPORTACAO": Decimal("80.00")}


def test_run_is_recorded_in_pipeline_runs(engine: Engine) -> None:
    run_comexstat(full_refresh=True, months=2, engine=engine, source=FakeSource())

    with engine.connect() as conn:
        status, rows_out = conn.execute(
            text(
                "select status, rows_out from ops.pipeline_runs "
                "where pipeline = 'ingest_comexstat' order by id desc limit 1"
            )
        ).one()
    assert (status, rows_out) == ("SUCESSO", 8)

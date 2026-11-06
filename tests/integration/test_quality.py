"""Repositório de qualidade no Postgres: gravação em ops e leitura dos volumes do bronze."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from flowstream.config import load_settings
from flowstream.db import PostgresMigrationStore, create_db_engine, migrate
from flowstream.pipeline_runs import start_run
from flowstream.quality.adapters import BRONZE_TABLES, PostgresQualityRepository
from flowstream.quality.domain import DqResult, VolumeAnomaly

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def engine() -> Iterator[Engine]:
    db_engine = create_db_engine(load_settings())
    migrate(ROOT / "infra" / "migrations", store=PostgresMigrationStore(db_engine))
    yield db_engine
    db_engine.dispose()


@pytest.fixture
def run_id(engine: Engine) -> Iterator[int]:
    run = start_run(engine, "teste_integracao_quality")
    yield run
    with engine.begin() as conn:
        conn.execute(text("delete from ops.dq_results where run_id = :id"), {"id": run})
        conn.execute(text("delete from ops.dq_anomalias where run_id = :id"), {"id": run})
        conn.execute(text("delete from ops.pipeline_runs where id = :id"), {"id": run})


def test_results_and_anomalies_are_saved_with_the_run(engine: Engine, run_id: int) -> None:
    repo = PostgresQualityRepository(engine)
    result = DqResult(
        tipo="test",
        recurso="test.flowstream.x",
        nome="x",
        status="fail",
        linhas_com_falha=3,
        duracao_s=Decimal("0.125"),
        mensagem="Got 3 results",
    )
    anomaly = VolumeAnomaly(
        tabela="bronze.ptax",
        data_referencia=date(2026, 11, 3),
        linhas_no_dia=400,
        media_14_dias=Decimal("100.00"),
        desvio_pct=Decimal("3.0000"),
        direcao="ACIMA",
    )

    repo.save_results(run_id, [result])
    repo.save_anomalies(run_id, [anomaly])

    with engine.connect() as conn:
        saved = conn.execute(
            text(
                "select status, linhas_com_falha, duracao_s from ops.dq_results where run_id = :id"
            ),
            {"id": run_id},
        ).one()
        direction = conn.execute(
            text("select direcao from ops.dq_anomalias where run_id = :id"), {"id": run_id}
        ).scalar_one()
    assert tuple(saved) == ("fail", 3, Decimal("0.125"))
    assert direction == "ACIMA"


def test_empty_lists_write_nothing(engine: Engine, run_id: int) -> None:
    repo = PostgresQualityRepository(engine)

    repo.save_results(run_id, [])
    repo.save_anomalies(run_id, [])

    with engine.connect() as conn:
        count = conn.execute(
            text("select count(*) from ops.dq_results where run_id = :id"), {"id": run_id}
        ).scalar_one()
    assert count == 0


def test_volumes_cover_every_bronze_table(engine: Engine) -> None:
    volumes = PostgresQualityRepository(engine).load_volumes(date.today())

    assert set(volumes) == {f"bronze.{t}" for t in BRONZE_TABLES}
    assert all(n > 0 for days in volumes.values() for n in days.values())

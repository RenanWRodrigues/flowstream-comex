"""Testes de integração do banco: precisam do Postgres do Docker (make up) e do .env."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from flowstream.config import load_settings
from flowstream.db import PostgresMigrationStore, create_db_engine, migrate

pytestmark = pytest.mark.integration

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "infra" / "migrations"
SCHEMAS = {"bronze", "prata", "ouro", "ops"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    db_engine = create_db_engine(load_settings())
    yield db_engine
    db_engine.dispose()


def test_connects_to_postgres_16(engine: Engine) -> None:
    with engine.connect() as conn:
        version = conn.execute(text("show server_version")).scalar_one()

    assert version.startswith("16.")


def test_migrate_creates_the_four_schemas(engine: Engine) -> None:
    migrate(MIGRATIONS_DIR, store=PostgresMigrationStore(engine))

    with engine.connect() as conn:
        found = set(
            conn.execute(text("select schema_name from information_schema.schemata")).scalars()
        )

    assert found >= SCHEMAS


def test_pipeline_runs_has_expected_columns(engine: Engine) -> None:
    migrate(MIGRATIONS_DIR, store=PostgresMigrationStore(engine))

    with engine.connect() as conn:
        columns = set(
            conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'ops' and table_name = 'pipeline_runs'"
                )
            ).scalars()
        )

    assert columns == {
        "id",
        "pipeline",
        "started_at",
        "finished_at",
        "status",
        "rows_in",
        "rows_out",
        "error",
    }


def test_pipeline_runs_rejects_unknown_status(engine: Engine) -> None:
    migrate(MIGRATIONS_DIR, store=PostgresMigrationStore(engine))

    with pytest.raises(Exception, match="pipeline_runs_status_check"), engine.begin() as conn:
        conn.execute(
            text("insert into ops.pipeline_runs (pipeline, status) values ('teste', 'TALVEZ')")
        )


def test_migrate_twice_is_a_no_op(engine: Engine) -> None:
    store = PostgresMigrationStore(engine)
    migrate(MIGRATIONS_DIR, store=store)

    assert migrate(MIGRATIONS_DIR, store=store) == []
    assert set(store.applied()) >= {"001", "002"}

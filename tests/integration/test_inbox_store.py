"""Consultas do watcher (psycopg direto) contra o Postgres de verdade, num schema temporário."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from flowstream.config import load_settings
from flowstream.db import PostgresMigrationStore, create_db_engine, migrate
from flowstream.ingestion.inbox_watcher import (
    PIPELINE,
    InboxNotifyError,
    InboxStoreError,
    PostgresInboxStore,
    libpq_url,
)

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "ops_teste_inbox"
SHA = "b" * 64


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    db_engine = create_db_engine(load_settings())
    migrate(ROOT / "infra" / "migrations", store=PostgresMigrationStore(db_engine))
    with db_engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA} cascade"))
        conn.execute(text(f"create schema {SCHEMA}"))
        for table in ("documentos", "pipeline_runs"):
            conn.execute(text(f"create table {SCHEMA}.{table} (like ops.{table} including all)"))
        conn.execute(
            text(
                f"insert into {SCHEMA}.documentos (nome_arquivo, sha256, tamanho_bytes) "  # noqa: S608
                "values ('BL_teste.pdf', :sha, 100)"
            ),
            {"sha": SHA},
        )
    yield db_engine
    with db_engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA} cascade"))
    db_engine.dispose()


@pytest.fixture
def store(engine: Engine) -> PostgresInboxStore:
    return PostgresInboxStore(libpq_url(load_settings().database_url.get_secret_value()), SCHEMA)


def test_registered_name_finds_the_document(store: PostgresInboxStore) -> None:
    assert store.registered_name(SHA) == "BL_teste.pdf"
    assert store.registered_name("c" * 64) is None


def test_record_failure_writes_a_closed_error_run(
    store: PostgresInboxStore, engine: Engine
) -> None:
    store.record_failure(
        InboxNotifyError("Webhook do n8n falhou (HTTP 503). CNPJ 12.345.678/0001-95")
    )
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"select pipeline, status, error, finished_at from {SCHEMA}.pipeline_runs "  # noqa: S608
                "order by id desc limit 1"
            )
        ).one()
    assert row.pipeline == PIPELINE
    assert row.status == "ERRO"
    assert row.finished_at is not None
    assert row.error.startswith("InboxNotifyError: Webhook do n8n falhou")
    assert "12.345.678" not in row.error  # mascarado


def test_unreachable_database_raises_store_error() -> None:
    dead = PostgresInboxStore("postgresql://u:p@127.0.0.1:1/db")
    with pytest.raises(InboxStoreError):
        dead.registered_name(SHA)


def test_schema_name_is_validated() -> None:
    with pytest.raises(ValueError, match="schema"):
        PostgresInboxStore("postgresql://u:p@127.0.0.1/db", "ops; drop table x")

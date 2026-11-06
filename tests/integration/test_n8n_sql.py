"""Consultas do n8n (n8n/sql) contra o Postgres de verdade, numa transação desfeita no fim.

O nó Postgres do n8n usa parâmetros posicionais ($1, $2...); o teste executa o mesmo
arquivo trocando só $n por :pn (parâmetro nomeado do SQLAlchemy).
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from flowstream.config import load_settings
from flowstream.db import PostgresMigrationStore, create_db_engine, migrate

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "n8n" / "sql"
PIPELINE = "n8n_documento_recebido_teste"


@pytest.fixture
def conn() -> Iterator[Connection]:
    engine = create_db_engine(load_settings())
    migrate(ROOT / "infra" / "migrations", store=PostgresMigrationStore(engine))
    with engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()  # nada fica em ops.pipeline_runs
    engine.dispose()


def _execute(conn: Connection, name: str, *params: object) -> list[dict[str, object]]:
    sql = (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")
    named = re.sub(r"\$(\d+)", lambda m: f":p{m[1]}", sql)
    values = {f"p{i}": value for i, value in enumerate(params, start=1)}
    rows = conn.execute(text(named), values).mappings().all()
    return [dict(row) for row in rows]


def test_start_opens_a_run_in_progress(conn: Connection) -> None:
    [row] = _execute(conn, "pipeline_run_inicio", PIPELINE)
    assert row["status"] == "EM_ANDAMENTO"
    stored = conn.execute(
        text("select pipeline, finished_at from ops.pipeline_runs where id = :id"),
        {"id": row["id"]},
    ).one()
    assert stored.pipeline == PIPELINE
    assert stored.finished_at is None


def test_finish_with_success(conn: Connection) -> None:
    [start] = _execute(conn, "pipeline_run_inicio", PIPELINE)
    [end] = _execute(conn, "pipeline_run_fim", start["id"], "SUCESSO", None)
    assert end == {"id": start["id"], "status": "SUCESSO"}
    finished = conn.execute(
        text("select finished_at, error, rows_in, rows_out from ops.pipeline_runs where id = :id"),
        {"id": start["id"]},
    ).one()
    assert finished.finished_at is not None
    assert finished.error is None
    assert (finished.rows_in, finished.rows_out) == (1, 1)


def test_finish_with_error_keeps_a_short_message(conn: Connection) -> None:
    [start] = _execute(conn, "pipeline_run_inicio", PIPELINE)
    long_message = "API respondeu HTTP 500. " + "x" * 1000
    [end] = _execute(conn, "pipeline_run_fim", start["id"], "ERRO", long_message)
    assert end["status"] == "ERRO"
    error, rows_out = conn.execute(
        text("select error, rows_out from ops.pipeline_runs where id = :id"), {"id": start["id"]}
    ).one()
    assert error.startswith("API respondeu HTTP 500.")
    assert len(error) == 500
    assert rows_out == 0


def test_finish_does_not_touch_a_closed_run(conn: Connection) -> None:
    [start] = _execute(conn, "pipeline_run_inicio", PIPELINE)
    _execute(conn, "pipeline_run_fim", start["id"], "SUCESSO", None)
    assert _execute(conn, "pipeline_run_fim", start["id"], "ERRO", "tarde demais") == []


def test_finish_rejects_unknown_status(conn: Connection) -> None:
    [start] = _execute(conn, "pipeline_run_inicio", PIPELINE)
    with pytest.raises(Exception, match="pipeline_runs_status_check"):
        _execute(conn, "pipeline_run_fim", start["id"], "TALVEZ", None)

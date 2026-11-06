"""Testes do módulo de banco: descoberta e aplicação de migrações, engine e transações."""

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from flowstream import db
from flowstream.config import load_settings
from flowstream.db import (
    Migration,
    MigrationError,
    create_db_engine,
    discover_migrations,
    migrate,
    run_migrations,
    transaction,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = PROJECT_ROOT / "infra" / "migrations"
DB_URL = "postgresql+psycopg://flowstream:senha-ficticia@localhost:5433/flowstream"


class FakeStore:
    """Imita o registro de migrações em ops.schema_migrations, sem banco."""

    def __init__(self, applied: dict[str, str] | None = None, fail_on: str | None = None) -> None:
        self.applied_map = dict(applied or {})
        self.fail_on = fail_on
        self.calls: list[str] = []
        self.table_ensured = False

    def ensure_table(self) -> None:
        self.table_ensured = True

    def applied(self) -> dict[str, str]:
        return dict(self.applied_map)

    def apply(self, migration: Migration) -> None:
        assert self.table_ensured, "a tabela de controle precisa existir antes"
        if migration.version == self.fail_on:
            raise RuntimeError("falha simulada")
        self.calls.append(migration.version)
        self.applied_map[migration.version] = migration.checksum


def write(directory: Path, name: str, sql: str = "select 1;") -> Path:
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


@pytest.fixture
def three_migrations(tmp_path: Path) -> list[Migration]:
    write(tmp_path, "003_c.sql", "select 3;")
    write(tmp_path, "001_a.sql", "select 1;")
    write(tmp_path, "002_b.sql", "select 2;")
    return discover_migrations(tmp_path)


# ------------------------------------------------------------------ descoberta


def test_discover_sorts_by_number_and_ignores_other_files(tmp_path: Path) -> None:
    write(tmp_path, "010_dez.sql")
    write(tmp_path, "002_dois.sql")
    write(tmp_path, "001_um.sql")
    write(tmp_path, "README.md", "# não é migração")
    write(tmp_path, ".gitkeep", "")

    migrations = discover_migrations(tmp_path)

    assert [m.version for m in migrations] == ["001", "002", "010"]
    assert [m.name for m in migrations] == ["um", "dois", "dez"]
    assert migrations[0].filename == "001_um.sql"


def test_discover_computes_checksum_of_content(tmp_path: Path) -> None:
    write(tmp_path, "001_a.sql", "create schema x;")

    (migration,) = discover_migrations(tmp_path)

    assert migration.sql == "create schema x;"
    assert migration.checksum == hashlib.sha256(b"create schema x;").hexdigest()


@pytest.mark.parametrize("bad_name", ["criar_schemas.sql", "1_a.sql", "001-a.sql", "001_.sql"])
def test_discover_rejects_badly_named_sql_files(tmp_path: Path, bad_name: str) -> None:
    write(tmp_path, bad_name)

    with pytest.raises(MigrationError, match=r"NNN_nome.sql"):
        discover_migrations(tmp_path)


def test_discover_rejects_duplicated_version(tmp_path: Path) -> None:
    write(tmp_path, "001_a.sql")
    write(tmp_path, "001_b.sql")

    with pytest.raises(MigrationError, match="001"):
        discover_migrations(tmp_path)


def test_discover_fails_when_directory_is_missing(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="não encontrada"):
        discover_migrations(tmp_path / "nao_existe")


# ------------------------------------------------------------------ aplicação


def test_run_applies_all_in_order_on_empty_database(three_migrations: list[Migration]) -> None:
    store = FakeStore()

    applied = run_migrations(store, three_migrations)

    assert store.calls == ["001", "002", "003"]
    assert [m.version for m in applied] == ["001", "002", "003"]


def test_run_applies_only_new_migrations(three_migrations: list[Migration]) -> None:
    first = three_migrations[0]
    store = FakeStore(applied={first.version: first.checksum})

    applied = run_migrations(store, three_migrations)

    assert store.calls == ["002", "003"]
    assert [m.version for m in applied] == ["002", "003"]


def test_second_run_applies_nothing(three_migrations: list[Migration]) -> None:
    store = FakeStore()
    run_migrations(store, three_migrations)
    store.calls.clear()

    applied = run_migrations(store, three_migrations)

    assert applied == []
    assert store.calls == []


def test_run_refuses_migration_changed_after_applied(three_migrations: list[Migration]) -> None:
    store = FakeStore(applied={"001": "checksum-antigo"})

    with pytest.raises(MigrationError, match=r"001_a.sql"):
        run_migrations(store, three_migrations)
    assert store.calls == []


def test_run_stops_at_first_failure(three_migrations: list[Migration]) -> None:
    store = FakeStore(fail_on="002")

    with pytest.raises(RuntimeError, match="falha simulada"):
        run_migrations(store, three_migrations)
    assert store.calls == ["001"]


def test_migrate_discovers_and_applies_with_given_store(tmp_path: Path) -> None:
    write(tmp_path, "001_a.sql")
    store = FakeStore()

    applied = migrate(tmp_path, store=store)

    assert [m.filename for m in applied] == ["001_a.sql"]


# ------------------------------------------------------------------ migrações reais


def test_project_migrations_are_valid_and_ordered() -> None:
    migrations = discover_migrations(MIGRATIONS_DIR)

    assert [m.filename for m in migrations][:2] == ["001_schemas.sql", "002_pipeline_runs.sql"]


def test_first_migration_creates_the_four_schemas() -> None:
    sql = (MIGRATIONS_DIR / "001_schemas.sql").read_text(encoding="utf-8").lower()

    for schema in ("bronze", "prata", "ouro", "ops"):
        assert f"create schema if not exists {schema}" in sql


def test_second_migration_creates_pipeline_runs_with_all_columns() -> None:
    sql = (MIGRATIONS_DIR / "002_pipeline_runs.sql").read_text(encoding="utf-8").lower()

    assert "create table if not exists ops.pipeline_runs" in sql
    for column in (
        "id",
        "pipeline",
        "started_at",
        "finished_at",
        "status",
        "rows_in",
        "rows_out",
        "error",
    ):
        assert f"\n    {column} " in sql


# ------------------------------------------------------------------ engine e transação


def test_engine_uses_database_url_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)

    engine = create_db_engine(load_settings(env_file=None))

    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.port == 5433
    assert "senha-ficticia" not in str(engine.url)  # senha mascarada ao exibir
    engine.dispose()


def test_engine_fails_fast_when_database_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem connect_timeout, o Windows espera dezenas de segundos ao tentar ::1 (IPv6)."""
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    captured: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs: object) -> str:
        captured.update(kwargs)
        return "engine"

    monkeypatch.setattr(db, "create_engine", fake_create_engine)

    db.create_db_engine(load_settings(env_file=None))

    assert captured["connect_args"] == {"connect_timeout": 10}


def test_transaction_commits_on_success() -> None:
    engine = create_engine("sqlite://")
    with transaction(engine) as conn:
        conn.execute(text("create table t (x integer)"))
        conn.execute(text("insert into t values (1)"))

    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from t")).scalar_one() == 1


def test_transaction_rolls_back_on_error() -> None:
    engine = create_engine("sqlite://")
    with transaction(engine) as conn:
        conn.execute(text("create table t (x integer)"))

    with pytest.raises(ValueError, match="erro simulado"), transaction(engine) as conn:
        conn.execute(text("insert into t values (1)"))
        raise ValueError("erro simulado")

    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from t")).scalar_one() == 0


def test_engine_hides_sql_parameters_from_errors_and_logs() -> None:
    """Auditoria P10 M4: o erro do SQLAlchemy não pode levar campos/evidências para o log."""
    from flowstream.config import Settings
    from flowstream.db import create_db_engine

    settings = Settings(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5433/db",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )
    engine = create_db_engine(settings)
    try:
        assert engine.hide_parameters is True
    finally:
        engine.dispose()

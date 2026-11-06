"""Carga dos dados sintéticos: precisa do Postgres (make up) e das migrações.

Os testes carregam num schema temporário (cópia da estrutura do bronze) e nunca no bronze
de verdade: uma versão anterior destes testes sobrescrevia a carga sintética real.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from flowstream.config import load_settings
from flowstream.db import PostgresMigrationStore, create_db_engine, migrate
from flowstream.synthetic.adapters import PostgresSyntheticLoader
from flowstream.synthetic.csv_io import TABLES
from flowstream.synthetic.service import generate_synthetic, load_synthetic

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "bronze_teste"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    db_engine = create_db_engine(load_settings())
    migrate(ROOT / "infra" / "migrations", store=PostgresMigrationStore(db_engine))
    with db_engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA} cascade"))
        conn.execute(text(f"create schema {SCHEMA}"))
        for table in TABLES:
            conn.execute(text(f"create table {SCHEMA}.{table} (like bronze.{table} including all)"))
    yield db_engine
    with db_engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA} cascade"))
    db_engine.dispose()


@pytest.fixture(scope="module")
def csv_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("synthetic")
    generate_synthetic(seed=99, months=2, out_dir=out, seeds_dir=ROOT / "dbt" / "seeds")
    return out


@pytest.fixture
def loader(engine: Engine) -> PostgresSyntheticLoader:
    return PostgresSyntheticLoader(engine, schema=SCHEMA)


def count(engine: Engine, table: str, schema: str = SCHEMA) -> int:
    with engine.connect() as conn:
        sql = f"select count(*) from {schema}.{table}"  # noqa: S608 - nomes fixos do teste
        return int(conn.execute(text(sql)).scalar_one())


def test_load_copies_every_table(
    engine: Engine, csv_dir: Path, loader: PostgresSyntheticLoader
) -> None:
    counts = load_synthetic(csv_dir, loader=loader)

    for table in TABLES:
        assert count(engine, table) == counts[table] > 0


def test_tests_never_touch_the_real_bronze(
    engine: Engine, csv_dir: Path, loader: PostgresSyntheticLoader
) -> None:
    before = {table: count(engine, table, "bronze") for table in TABLES}

    load_synthetic(csv_dir, loader=loader)

    assert {table: count(engine, table, "bronze") for table in TABLES} == before


def test_loading_twice_does_not_duplicate(
    engine: Engine, csv_dir: Path, loader: PostgresSyntheticLoader
) -> None:
    first = load_synthetic(csv_dir, loader=loader)
    second = load_synthetic(csv_dir, loader=loader)

    assert first == second
    for table in TABLES:
        assert count(engine, table) == first[table]


def test_load_is_recorded_in_pipeline_runs(
    engine: Engine, csv_dir: Path, loader: PostgresSyntheticLoader
) -> None:
    counts = load_synthetic(csv_dir, loader=loader)

    with engine.connect() as conn:
        status, rows_out, finished = conn.execute(
            text(
                "select status, rows_out, finished_at from ops.pipeline_runs "
                "where pipeline = 'synthetic_load' order by id desc limit 1"
            )
        ).one()
    assert status == "SUCESSO"
    assert rows_out == sum(counts.values())
    assert finished is not None


def test_types_survive_the_round_trip(
    engine: Engine, csv_dir: Path, loader: PostgresSyntheticLoader
) -> None:
    load_synthetic(csv_dir, loader=loader)

    with engine.connect() as conn:
        tz, kind = conn.execute(
            text(
                f"select to_char(etd, 'TZH'), pg_typeof(valor)::text "  # noqa: S608
                f"from {SCHEMA}.embarques, {SCHEMA}.itens_financeiros limit 1"
            )
        ).one()
    assert kind == "numeric"
    assert tz in {"-03", "+00"}  # timestamptz guardado com fuso


def test_failed_load_rolls_back_and_records_error(
    engine: Engine, csv_dir: Path, loader: PostgresSyntheticLoader, tmp_path: Path
) -> None:
    load_synthetic(csv_dir, loader=loader)
    broken = tmp_path / "broken"
    broken.mkdir()
    for table in TABLES:
        (broken / f"{table}.csv").write_bytes((csv_dir / f"{table}.csv").read_bytes())
    (broken / "embarques.csv").write_text("processo\nsem-as-outras-colunas\n", encoding="utf-8")
    before = count(engine, "clientes")

    with pytest.raises(Exception):  # noqa: B017 - qualquer erro do COPY serve
        load_synthetic(broken, loader=loader)

    assert count(engine, "clientes") == before  # truncate desfeito
    with engine.connect() as conn:
        status = conn.execute(
            text(
                "select status from ops.pipeline_runs where pipeline = 'synthetic_load' "
                "order by id desc limit 1"
            )
        ).scalar_one()
    assert status == "ERRO"

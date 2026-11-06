"""Adapters da qualidade: dbt no mesmo processo (dbtRunner) e gravação no schema ops."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from flowstream.db import transaction
from flowstream.quality.domain import DqResult, VolumeAnomaly

DBT_PROJECT_DIR = Path("dbt")

# Tabelas do bronze monitoradas (nomes fixos do código; entram no SQL como identificador).
BRONZE_TABLES = (
    "ptax",
    "comexstat",
    "vendedores",
    "clientes",
    "cotacoes",
    "embarques",
    "equipamentos",
    "itens_financeiros",
    "tracking_eventos",
)


# ------------------------------------------------------------------ dbt


def dbt_env(database_url: str) -> dict[str, str]:
    """Variáveis que o dbt/profiles.yml lê, derivadas do DATABASE_URL (fonte única)."""
    url = make_url(database_url)
    return {
        "APP_DB_USER": url.username or "",
        "APP_DB_PASSWORD": url.password or "",
        "DBT_HOST": url.host or "127.0.0.1",
        "POSTGRES_PORT": str(url.port or 5432),
        "POSTGRES_DB": url.database or "",
    }


@contextmanager
def dbt_environment(database_url: str) -> Iterator[None]:
    """Define as variáveis do dbt durante o bloco e restaura as anteriores ao sair."""
    values = dbt_env(database_url)
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class DbtCliRunner:
    """Roda comandos do dbt no mesmo processo, pela API oficial (dbtRunner), sem subprocess."""

    def __init__(self, project_dir: Path = DBT_PROJECT_DIR) -> None:
        self.project_dir = project_dir
        self.target_dir = project_dir / "target"

    def run(self, args: list[str]) -> bool:
        from dbt.cli.main import dbtRunner  # import pesado: só quando usado

        result = dbtRunner().invoke(
            [
                "--quiet",
                *args,
                "--project-dir",
                str(self.project_dir),
                "--profiles-dir",
                str(self.project_dir),
            ]
        )
        return bool(result.success)


# ------------------------------------------------------------------ Postgres


class PostgresQualityRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load_volumes(self, today: date, days: int = 15) -> dict[str, dict[date, int]]:
        """Linhas por dia de carga (loaded_at, horário de São Paulo) de cada tabela do bronze."""
        since = today - timedelta(days=days)
        volumes: dict[str, dict[date, int]] = {}
        with self._engine.connect() as conn:
            for table in BRONZE_TABLES:
                rows = conn.execute(
                    text(
                        "select (loaded_at at time zone 'America/Sao_Paulo')::date as dia, "  # noqa: S608
                        f"count(*) from bronze.{table} "
                        "where loaded_at >= :since group by 1"
                    ),
                    {"since": since},
                )
                volumes[f"bronze.{table}"] = {day: int(count) for day, count in rows}
        return volumes

    def save_results(self, run_id: int, results: list[DqResult]) -> None:
        if not results:
            return
        with transaction(self._engine) as conn:
            conn.execute(
                text(
                    """
                    insert into ops.dq_results (run_id, tipo, recurso, nome, status,
                        linhas_com_falha, duracao_s, mensagem)
                    values (:run_id, :tipo, :recurso, :nome, :status,
                        :linhas_com_falha, :duracao_s, :mensagem)
                    """
                ),
                [{"run_id": run_id, **r.model_dump()} for r in results],
            )

    def save_anomalies(self, run_id: int, anomalies: list[VolumeAnomaly]) -> None:
        if not anomalies:
            return
        with transaction(self._engine) as conn:
            conn.execute(
                text(
                    """
                    insert into ops.dq_anomalias (run_id, tabela, data_referencia, linhas_no_dia,
                        media_14_dias, desvio_pct, direcao)
                    values (:run_id, :tabela, :data_referencia, :linhas_no_dia,
                        :media_14_dias, :desvio_pct, :direcao)
                    """
                ),
                [{"run_id": run_id, **a.model_dump()} for a in anomalies],
            )

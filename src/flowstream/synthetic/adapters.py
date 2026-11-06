"""Carga dos CSVs sintéticos no schema bronze do Postgres."""

import re
from pathlib import Path

from sqlalchemy import Engine

from flowstream.db import transaction
from flowstream.logging import get_logger
from flowstream.pipeline_runs import finish_run, start_run
from flowstream.synthetic.csv_io import TABLES

PIPELINE = "synthetic_load"
DEFAULT_SCHEMA = "bronze"

# O schema entra no SQL como identificador (não dá para usar parâmetro): só nomes simples.
_SAFE_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]*$")

logger = get_logger(__name__)


class PostgresSyntheticLoader:
    """Substitui o conteúdo das tabelas sintéticas numa única transação.

    Idempotente: carregar os mesmos CSVs de novo dá exatamente o mesmo resultado.
    `schema` existe para os testes de integração carregarem numa cópia isolada, sem
    sobrescrever o bronze de verdade.
    """

    def __init__(self, engine: Engine, schema: str = DEFAULT_SCHEMA) -> None:
        if not _SAFE_SCHEMA.match(schema):
            raise ValueError(f"Nome de schema inválido: {schema!r}")
        self._engine = engine
        self.schema = schema

    def load(self, directory: Path) -> dict[str, int]:
        run_id = start_run(self._engine, PIPELINE)
        try:
            counts = self._copy_all(directory)
        except Exception as exc:
            finish_run(self._engine, run_id, error=exc)
            raise
        total = sum(counts.values())
        finish_run(self._engine, run_id, rows_in=total, rows_out=total)
        logger.info("carga sintética concluída: %s linhas em %s tabelas", total, len(counts))
        return counts

    def _copy_all(self, directory: Path) -> dict[str, int]:
        # Tabelas e colunas vêm de constantes do código (TABLES); o schema foi validado.
        truncate = "truncate " + ", ".join(f"{self.schema}.{table}" for table in TABLES)
        counts = {}
        with transaction(self._engine) as conn:
            driver = conn.connection.driver_connection
            if driver is None:
                raise RuntimeError("Conexão com o banco indisponível.")
            with driver.cursor() as cursor:
                cursor.execute(truncate)
                for table, model in TABLES.items():
                    columns = ", ".join(model.model_fields)
                    sql = (
                        f"copy {self.schema}.{table} ({columns}) "
                        "from stdin with (format csv, header true)"
                    )
                    with cursor.copy(sql) as copy:
                        copy.write((directory / f"{table}.csv").read_bytes())
                    counts[table] = cursor.rowcount
        return counts

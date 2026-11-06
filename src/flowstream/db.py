"""Acesso ao PostgreSQL: engine, transações e migrações SQL versionadas.

As migrações ficam em infra/migrations/NNN_nome.sql e são registradas em
ops.schema_migrations. Cada uma roda em uma transação própria, junto com o seu registro.
"""

import hashlib
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from sqlalchemy import Connection, Engine, create_engine, text

from flowstream.config import Settings, get_settings
from flowstream.logging import get_logger

DEFAULT_MIGRATIONS_DIR = Path("infra/migrations")
CONNECT_TIMEOUT_SECONDS = 10

_MIGRATION_NAME = re.compile(r"^(?P<version>\d{3})_(?P<name>[a-z0-9_]+)\.sql$")

logger = get_logger(__name__)


class MigrationError(RuntimeError):
    """Problema nos arquivos de migração ou no histórico já aplicado."""


@dataclass(frozen=True)
class Migration:
    """Um arquivo NNN_nome.sql."""

    version: str
    name: str
    sql: str
    path: Path
    checksum: str = field(init=False)

    def __post_init__(self) -> None:
        digest = hashlib.sha256(self.sql.encode("utf-8")).hexdigest()
        object.__setattr__(self, "checksum", digest)

    @property
    def filename(self) -> str:
        return f"{self.version}_{self.name}.sql"


class MigrationStore(Protocol):
    """Onde as migrações são aplicadas e registradas."""

    def ensure_table(self) -> None: ...

    def applied(self) -> dict[str, str]:
        """Versões já aplicadas e o checksum de cada uma."""
        ...

    def apply(self, migration: Migration) -> None: ...


# ------------------------------------------------------------------ regras (sem banco)


def discover_migrations(directory: Path) -> list[Migration]:
    """Lê os arquivos .sql da pasta, valida os nomes e devolve em ordem de versão."""
    if not directory.is_dir():
        raise MigrationError(f"Pasta de migrações não encontrada: {directory}")

    migrations: dict[str, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.match(path.name)
        if match is None:
            raise MigrationError(
                f"Nome inválido: {path.name}. Use NNN_nome.sql (ex.: 003_documentos.sql)."
            )
        version = match["version"]
        if version in migrations:
            raise MigrationError(
                f"Versão {version} repetida: {migrations[version].path.name} e {path.name}."
            )
        sql = path.read_text(encoding="utf-8")
        migrations[version] = Migration(version=version, name=match["name"], sql=sql, path=path)

    return [migrations[v] for v in sorted(migrations, key=int)]


def run_migrations(store: MigrationStore, migrations: Sequence[Migration]) -> list[Migration]:
    """Aplica, em ordem, só as migrações novas. Recusa migração alterada depois de aplicada."""
    store.ensure_table()
    applied = store.applied()

    for migration in migrations:
        known = applied.get(migration.version)
        if known is not None and known != migration.checksum:
            raise MigrationError(
                f"{migration.filename} foi alterada depois de aplicada. "
                "Não edite migrações aplicadas: crie uma nova."
            )

    pending = [m for m in migrations if m.version not in applied]
    for migration in pending:
        store.apply(migration)
        logger.info("migração aplicada: %s", migration.filename)
    return pending


# ------------------------------------------------------------------ adapters (banco)


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Engine SQLAlchemy a partir do DATABASE_URL. Não abre conexão até o primeiro uso."""
    settings = settings or get_settings()
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        # Erros e logs do SQLAlchemy sem os valores dos parâmetros (campos, evidências).
        hide_parameters=True,
        pool_size=5,
        max_overflow=5,  # o Postgres do projeto aceita no máximo 30 conexões
        # Falha rápido se o banco não responde (ex.: "localhost" resolvido para ::1 no Windows).
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """Conexão dentro de uma transação: commit ao sair, rollback em caso de erro."""
    with engine.begin() as conn:
        yield conn


class PostgresMigrationStore:
    """Registro das migrações em ops.schema_migrations."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ensure_table(self) -> None:
        with transaction(self._engine) as conn:
            conn.execute(text("create schema if not exists ops"))
            conn.execute(
                text(
                    """
                    create table if not exists ops.schema_migrations (
                        version    text primary key,
                        name       text not null,
                        checksum   text not null,
                        applied_at timestamptz not null default now()
                    )
                    """
                )
            )

    def applied(self) -> dict[str, str]:
        with self._engine.connect() as conn:
            rows = conn.execute(text("select version, checksum from ops.schema_migrations"))
            return {version: checksum for version, checksum in rows}

    def apply(self, migration: Migration) -> None:
        with transaction(self._engine) as conn:
            # O arquivo pode ter vários comandos: vai direto ao psycopg, sem parâmetros,
            # que então usa o protocolo simples do Postgres (aceita múltiplos comandos).
            driver_connection = conn.connection.driver_connection
            if driver_connection is None:
                raise MigrationError("Conexão com o banco indisponível ao aplicar migração.")
            driver_connection.execute(migration.sql)
            conn.execute(
                text(
                    "insert into ops.schema_migrations (version, name, checksum) "
                    "values (:version, :name, :checksum)"
                ),
                {
                    "version": migration.version,
                    "name": migration.name,
                    "checksum": migration.checksum,
                },
            )


def migrate(
    directory: Path = DEFAULT_MIGRATIONS_DIR, store: MigrationStore | None = None
) -> list[Migration]:
    """Aplica as migrações pendentes da pasta e devolve as que foram aplicadas."""
    migrations = discover_migrations(directory)
    if store is None:
        store = PostgresMigrationStore(create_db_engine())
    return run_migrations(store, migrations)

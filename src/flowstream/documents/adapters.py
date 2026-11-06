"""Registro dos documentos em ops.documentos."""

import re
from uuid import UUID

from sqlalchemy import Engine, text

from flowstream.db import transaction
from flowstream.documents.domain import Document

_SAFE_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]*$")
_COLUMNS = (
    "id, nome_arquivo, sha256, tamanho_bytes, status, tipo_documento, resultado, erro, "
    "recebido_em, atualizado_em"
)


class PostgresDocumentRepository:
    """`schema` existe para os testes de integração usarem uma cópia isolada de ops."""

    def __init__(self, engine: Engine, schema: str = "ops") -> None:
        if not _SAFE_SCHEMA.match(schema):
            raise ValueError(f"Nome de schema inválido: {schema!r}")
        self._engine = engine
        self._table = f"{schema}.documentos"

    def find_by_sha256(self, sha256: str) -> Document | None:
        return self._one(f"select {_COLUMNS} from {self._table} where sha256 = :v", sha256)  # noqa: S608

    def get(self, document_id: UUID) -> Document | None:
        return self._one(f"select {_COLUMNS} from {self._table} where id = :v", document_id)  # noqa: S608

    def insert(self, nome_arquivo: str, sha256: str, tamanho_bytes: int) -> Document:
        with transaction(self._engine) as conn:
            row = (
                conn.execute(
                    text(
                        f"insert into {self._table} (nome_arquivo, sha256, tamanho_bytes) "  # noqa: S608
                        f"values (:nome, :sha, :tamanho) returning {_COLUMNS}"
                    ),
                    {"nome": nome_arquivo, "sha": sha256, "tamanho": tamanho_bytes},
                )
                .mappings()
                .one()
            )
        return Document(**row)

    def _one(self, sql: str, value: object) -> Document | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(sql), {"v": value}).mappings().first()
        return Document(**row) if row else None

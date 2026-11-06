"""Regras puras dos documentos: status e validação do nome do arquivo (anti path traversal)."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

MAX_NAME_LENGTH = 200

# Só um nome de arquivo: letras (inclusive acentuadas), dígitos, espaço, ponto, _ - ( ).
# Barra, contrabarra, dois-pontos (drive do Windows) e NUL ficam de fora por construção.
_SAFE_NAME = re.compile(r"^[\w .()\-]+$")


class DocumentStatus(StrEnum):
    RECEBIDO = "RECEBIDO"
    PROCESSANDO = "PROCESSANDO"
    APROVADO = "APROVADO"
    REVISAO = "REVISAO"
    ERRO = "ERRO"


class InvalidDocumentNameError(ValueError):
    """Nome que não é um simples arquivo PDF dentro da inbox."""


class Document(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    nome_arquivo: str
    sha256: str
    tamanho_bytes: int
    status: DocumentStatus
    tipo_documento: str | None = None
    resultado: dict[str, Any] | None = None
    erro: str | None = None
    recebido_em: datetime
    atualizado_em: datetime


def validate_file_name(name: str) -> str:
    """Aceita só o nome de um PDF (sem pastas); recusa qualquer tentativa de sair da inbox."""
    clean = name.strip()
    if not clean or len(clean) > MAX_NAME_LENGTH:
        raise InvalidDocumentNameError("Informe o nome de um arquivo PDF da inbox.")
    if not _SAFE_NAME.match(clean) or clean.startswith(".") or ".." in clean:
        raise InvalidDocumentNameError(
            "Nome inválido: informe só o nome do arquivo, sem pastas nem caminhos."
        )
    stem, _, extension = clean.rpartition(".")
    if extension.lower() != "pdf" or not stem:
        raise InvalidDocumentNameError("Só arquivos PDF são aceitos.")
    return clean

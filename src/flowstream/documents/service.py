"""Casos de uso dos documentos: registrar um PDF da inbox e consultar o status."""

import hashlib
from pathlib import Path
from typing import Protocol
from uuid import UUID

from flowstream.documents.domain import (
    Document,
    InvalidDocumentNameError,
    validate_file_name,
)
from flowstream.logging import get_logger

logger = get_logger(__name__)

_CHUNK = 1024 * 1024


class DocumentNotFoundError(LookupError):
    """O arquivo não está na inbox."""


class DuplicateDocumentError(Exception):
    """O mesmo conteúdo (SHA-256) já foi registrado."""

    def __init__(self, document_id: UUID) -> None:
        super().__init__(f"Documento já registrado: {document_id}")
        self.document_id = document_id


class DocumentRepository(Protocol):
    def find_by_sha256(self, sha256: str) -> Document | None: ...

    def insert(self, nome_arquivo: str, sha256: str, tamanho_bytes: int) -> Document: ...

    def get(self, document_id: UUID) -> Document | None: ...


class DocumentProcessor(Protocol):
    """Quem extrai os dados do documento. O agente de IA (P10) implementa esta interface."""

    def submit(self, document: Document) -> None: ...


class NotYetAvailableProcessor:
    """Não extrai nada: o documento fica em RECEBIDO (testes e ambiente sem o agente de IA).

    A API usa o processador real, `flowstream.ai.service.QueuedDocumentProcessor` (P10).
    """

    def submit(self, document: Document) -> None:
        logger.info("documento %s recebido; extração desativada", document.id)


def register_document(
    file_name: str,
    inbox_dir: Path,
    repository: DocumentRepository,
    processor: DocumentProcessor,
) -> Document:
    """Registra um PDF que já está na inbox e o entrega ao processador."""
    name = validate_file_name(file_name)
    inbox = inbox_dir.resolve()
    path = (inbox / name).resolve()
    if not path.is_relative_to(inbox):  # defesa em profundidade (ex.: link simbólico)
        raise InvalidDocumentNameError("O arquivo precisa estar dentro da inbox.")
    if not path.is_file():
        raise DocumentNotFoundError(f"Arquivo não encontrado na inbox: {name}")

    sha256, size = digest_file(path)
    existing = repository.find_by_sha256(sha256)
    if existing is not None:
        raise DuplicateDocumentError(existing.id)
    document = repository.insert(name, sha256, size)
    processor.submit(document)
    return document


def get_document(document_id: UUID, repository: DocumentRepository) -> Document | None:
    return repository.get(document_id)


def digest_file(path: Path) -> tuple[str, int]:
    """SHA-256 (hex) e tamanho em bytes, lendo o arquivo em blocos de 1 MB."""
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size

"""Testes do recebimento de documentos: nome seguro, inbox, hash e duplicados (sem banco)."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from flowstream.documents.domain import (
    Document,
    DocumentStatus,
    InvalidDocumentNameError,
    validate_file_name,
)
from flowstream.documents.service import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    NotYetAvailableProcessor,
    register_document,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


class FakeRepository:
    def __init__(self) -> None:
        self.docs: dict[UUID, Document] = {}

    def find_by_sha256(self, sha256: str) -> Document | None:
        return next((d for d in self.docs.values() if d.sha256 == sha256), None)

    def insert(self, nome_arquivo: str, sha256: str, tamanho_bytes: int) -> Document:
        doc = Document(
            id=uuid4(),
            nome_arquivo=nome_arquivo,
            sha256=sha256,
            tamanho_bytes=tamanho_bytes,
            status=DocumentStatus.RECEBIDO,
            recebido_em=NOW,
            atualizado_em=NOW,
        )
        self.docs[doc.id] = doc
        return doc

    def get(self, document_id: UUID) -> Document | None:
        return self.docs.get(document_id)


class SpyProcessor:
    def __init__(self) -> None:
        self.submitted: list[UUID] = []

    def submit(self, document: Document) -> None:
        self.submitted.append(document.id)


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    folder = tmp_path / "inbox"
    folder.mkdir()
    (folder / "BL_MSCU1234566.pdf").write_bytes(b"%PDF-1.7 conteudo ficticio")
    return folder


# ------------------------------------------------------------------ nome do arquivo


@pytest.mark.parametrize(
    "name", ["BL_MSCU1234566.pdf", "invoice 2026-10 (1).PDF", "packing_list-ação.pdf"]
)
def test_accepts_plain_pdf_names(name: str) -> None:
    assert validate_file_name(f"  {name} ") == name


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",
        "..\\..\\Windows\\win.ini",
        "../segredo.pdf",
        "sub/pasta.pdf",
        "sub\\pasta.pdf",
        "/etc/passwd.pdf",
        "C:\\dados\\x.pdf",
        "C:x.pdf",
        "..",
        ".pdf",
        "",
        "   ",
        "arquivo.txt",
        "arquivo.pdf.exe",
        "nulo\x00.pdf",
        "a" * 300 + ".pdf",
    ],
)
def test_rejects_unsafe_or_non_pdf_names(name: str) -> None:
    with pytest.raises(InvalidDocumentNameError):
        validate_file_name(name)


# ------------------------------------------------------------------ registro


def test_registers_existing_pdf_with_hash_and_size(inbox: Path) -> None:
    repo, spy = FakeRepository(), SpyProcessor()

    doc = register_document("BL_MSCU1234566.pdf", inbox, repo, spy)

    content = b"%PDF-1.7 conteudo ficticio"
    assert doc.status == DocumentStatus.RECEBIDO
    assert doc.sha256 == hashlib.sha256(content).hexdigest()
    assert doc.tamanho_bytes == len(content)
    assert spy.submitted == [doc.id]


def test_missing_file_is_reported(inbox: Path) -> None:
    with pytest.raises(DocumentNotFoundError, match="inbox"):
        register_document("nao_existe.pdf", inbox, FakeRepository(), SpyProcessor())


def test_traversal_never_reaches_the_filesystem(inbox: Path) -> None:
    secret = inbox.parent / "segredo.pdf"
    secret.write_bytes(b"%PDF fora da inbox")

    with pytest.raises(InvalidDocumentNameError):
        register_document("../segredo.pdf", inbox, FakeRepository(), SpyProcessor())


def test_directory_with_pdf_name_is_not_a_document(inbox: Path) -> None:
    (inbox / "pasta.pdf").mkdir()

    with pytest.raises(DocumentNotFoundError):
        register_document("pasta.pdf", inbox, FakeRepository(), SpyProcessor())


def test_same_content_twice_is_a_duplicate(inbox: Path) -> None:
    repo = FakeRepository()
    first = register_document("BL_MSCU1234566.pdf", inbox, repo, SpyProcessor())
    (inbox / "copia.pdf").write_bytes(b"%PDF-1.7 conteudo ficticio")

    with pytest.raises(DuplicateDocumentError) as excinfo:
        register_document("copia.pdf", inbox, repo, SpyProcessor())

    assert excinfo.value.document_id == first.id
    assert len(repo.docs) == 1


def test_not_yet_available_processor_leaves_status_untouched(inbox: Path) -> None:
    repo = FakeRepository()

    doc = register_document("BL_MSCU1234566.pdf", inbox, repo, NotYetAvailableProcessor())

    assert repo.get(doc.id) is not None
    assert repo.docs[doc.id].status == DocumentStatus.RECEBIDO

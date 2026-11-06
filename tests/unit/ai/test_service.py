"""Processador da API: fila com um worker, uma extração por vez, estado sempre gravado."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from flowstream.ai.pipeline import ExtractionResult, Outcome
from flowstream.ai.schemas import DocumentType
from flowstream.ai.service import QueuedDocumentProcessor
from flowstream.documents.domain import Document, DocumentStatus

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _document(inbox: Path, name: str = "bl.pdf", content: bytes | None = None) -> Document:
    data = content if content is not None else f"%PDF-1.7 {name}".encode()
    (inbox / name).write_bytes(data)
    return Document(
        id=uuid4(),
        nome_arquivo=name,
        sha256=hashlib.sha256(data).hexdigest(),
        tamanho_bytes=len(data),
        status=DocumentStatus.RECEBIDO,
        recebido_em=NOW,
        atualizado_em=NOW,
    )


class SpyStore:
    def __init__(self, pending: list[Document] | None = None) -> None:
        self.events: list[tuple[str, UUID, Outcome | None]] = []
        self.pending = pending or []
        self.errors: list[tuple[UUID, str]] = []

    def mark_processing(self, document_id: UUID) -> None:
        self.events.append(("processando", document_id, None))

    def save(self, document_id: UUID, result: ExtractionResult) -> None:
        self.events.append(("salvo", document_id, result.outcome))

    def mark_error(self, document_id: UUID, message: str) -> None:
        self.errors.append((document_id, message))

    def pending_documents(self, limit: int) -> list[Document]:
        return self.pending[:limit]


class SpyExtractor:
    def __init__(self, outcome: Outcome = Outcome.APROVADO, fail: bool = False) -> None:
        self.paths: list[Path] = []
        self.outcome = outcome
        self.fail = fail

    def extract_file(self, path: Path) -> ExtractionResult:
        self.paths.append(path)
        if self.fail:
            raise RuntimeError("falha inesperada com dado 12.345.678/0001-95")
        return ExtractionResult(self.outcome, DocumentType.BL, score=1.0)


def _processor(
    tmp_path: Path, extractor: SpyExtractor, store: SpyStore, max_queue: int = 10
) -> QueuedDocumentProcessor:
    return QueuedDocumentProcessor(
        extractor, store, inbox_dir=tmp_path, start_worker=False, max_queue=max_queue
    )


def test_submit_only_enqueues(tmp_path: Path) -> None:
    extractor, store = SpyExtractor(), SpyStore()
    processor = _processor(tmp_path, extractor, store)
    processor.submit(_document(tmp_path))
    assert processor.pending == 1
    assert extractor.paths == []  # a API responde 202 sem esperar o modelo


def test_worker_processes_one_document_at_a_time(tmp_path: Path) -> None:
    extractor, store = SpyExtractor(), SpyStore()
    processor = _processor(tmp_path, extractor, store)
    first, second = _document(tmp_path, "a.pdf"), _document(tmp_path, "b.pdf")
    processor.submit(first)
    processor.submit(second)
    assert processor.process_next(timeout=0) is True
    assert store.events == [
        ("processando", first.id, None),
        ("salvo", first.id, Outcome.APROVADO),
    ]
    assert extractor.paths == [(tmp_path / "a.pdf").resolve()]
    assert processor.process_next(timeout=0) is True
    assert processor.process_next(timeout=0) is False  # fila vazia


def test_same_document_is_not_queued_twice(tmp_path: Path) -> None:
    processor = _processor(tmp_path, SpyExtractor(), SpyStore())
    document = _document(tmp_path)
    processor.submit(document)
    processor.submit(document)
    assert processor.pending == 1


def test_unexpected_failure_is_saved_as_a_generic_error(tmp_path: Path) -> None:
    """Auditoria P10 B4: a mensagem gravada não leva detalhe interno nem dado do documento."""
    store = SpyStore()
    processor = _processor(tmp_path, SpyExtractor(fail=True), store)
    document = _document(tmp_path)
    processor.submit(document)
    processor.process_next(timeout=0)
    assert store.events[-1] == ("salvo", document.id, Outcome.ERRO)


def test_file_changed_after_registration_is_an_error(tmp_path: Path) -> None:
    """Auditoria P10 M5: o arquivo extraído tem de ser o mesmo (SHA-256) que foi registrado."""
    extractor, store = SpyExtractor(), SpyStore()
    processor = _processor(tmp_path, extractor, store)
    document = _document(tmp_path)
    (tmp_path / "bl.pdf").write_bytes(b"%PDF-1.7 trocado depois do 202")
    processor.submit(document)
    processor.process_next(timeout=0)
    assert extractor.paths == []
    assert store.events[-1] == ("salvo", document.id, Outcome.ERRO)


def test_path_outside_the_inbox_is_an_error(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    outside = _document(tmp_path, "fora.pdf")
    escaped = outside.model_copy(update={"nome_arquivo": "../fora.pdf"})
    extractor, store = SpyExtractor(), SpyStore()
    processor = QueuedDocumentProcessor(extractor, store, inbox_dir=inbox, start_worker=False)
    processor.submit(escaped)
    processor.process_next(timeout=0)
    assert extractor.paths == []
    assert store.events[-1] == ("salvo", escaped.id, Outcome.ERRO)


def test_save_failure_falls_back_to_marking_the_error(tmp_path: Path) -> None:
    """Auditoria P10 M3: se a gravação falha, o documento não fica preso em PROCESSANDO."""

    class BrokenStore(SpyStore):
        def save(self, document_id: UUID, result: ExtractionResult) -> None:
            raise ValueError("NUL no JSON")

    store = BrokenStore()
    processor = _processor(tmp_path, SpyExtractor(), store)
    document = _document(tmp_path)
    processor.submit(document)
    processor.process_next(timeout=0)
    assert store.errors == [(document.id, "falha ao gravar o resultado da extração")]


def test_store_down_does_not_stop_the_worker(tmp_path: Path) -> None:
    class DeadStore(SpyStore):
        def save(self, document_id: UUID, result: ExtractionResult) -> None:
            raise ConnectionError("banco fora do ar")

        def mark_error(self, document_id: UUID, message: str) -> None:
            raise ConnectionError("banco fora do ar")

    extractor = SpyExtractor()
    processor = _processor(tmp_path, extractor, DeadStore())
    processor.submit(_document(tmp_path, "a.pdf"))
    processor.submit(_document(tmp_path, "b.pdf"))
    processor.process_next(timeout=0)
    processor.process_next(timeout=0)
    assert len(extractor.paths) == 2


def test_full_queue_leaves_the_document_for_the_sweep(tmp_path: Path) -> None:
    """Auditoria P10 M6: fila com limite; o excedente fica RECEBIDO e volta na varredura."""
    store = SpyStore()
    processor = _processor(tmp_path, SpyExtractor(), store, max_queue=1)
    first, second = _document(tmp_path, "a.pdf"), _document(tmp_path, "b.pdf")
    processor.submit(first)
    processor.submit(second)  # não levanta: só não entra agora
    assert processor.pending == 1
    processor.process_next(timeout=0)
    store.pending = [second]
    assert processor.sweep() == 1
    assert processor.pending == 1


def test_sweep_recovers_documents_left_by_a_restart(tmp_path: Path) -> None:
    """Revisão/auditoria P10 M7/M3: RECEBIDO e PROCESSANDO de antes do reinício voltam à fila."""
    left = [_document(tmp_path, "a.pdf"), _document(tmp_path, "b.pdf")]
    processor = _processor(tmp_path, SpyExtractor(), SpyStore(pending=left))
    assert processor.sweep() == 2
    assert processor.sweep() == 0  # já na fila: não duplica
    assert processor.pending == 2


def test_worker_thread_drains_the_queue_and_stops(tmp_path: Path) -> None:
    extractor, store = SpyExtractor(), SpyStore()
    processor = QueuedDocumentProcessor(extractor, store, inbox_dir=tmp_path)
    document = _document(tmp_path)
    processor.submit(document)
    processor.join(timeout=5)
    processor.stop(timeout=5)
    assert ("salvo", document.id, Outcome.APROVADO) in store.events
    assert processor.running is False


@pytest.mark.parametrize("max_queue", [0, -1])
def test_queue_limit_must_be_positive(tmp_path: Path, max_queue: int) -> None:
    with pytest.raises(ValueError, match="fila"):
        _processor(tmp_path, SpyExtractor(), SpyStore(), max_queue=max_queue)

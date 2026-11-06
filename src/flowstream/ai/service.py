"""Processador real de documentos da API: fila com UM worker (uma chamada ao modelo por vez).

POST /v1/documentos registra o PDF e chama `submit`, que só enfileira: a API responde 202
na hora e a extração acontece em segundo plano, gravando o resultado no banco.

O banco é a fonte da verdade: a fila em memória tem limite, e uma varredura periódica (e na
partida) recoloca na fila o que está RECEBIDO ou PROCESSANDO — inclusive o que ficou para
trás num reinício da API ou quando a fila estava cheia.
"""

import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID

from flowstream.ai.pipeline import ExtractionResult, Outcome
from flowstream.documents.domain import Document
from flowstream.documents.service import digest_file
from flowstream.logging import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_QUEUE = 100
SWEEP_INTERVAL_SECONDS = 60.0
SAVE_FAILED_MESSAGE = "falha ao gravar o resultado da extração"


class FileExtractor(Protocol):
    def extract_file(self, path: Path) -> ExtractionResult: ...


class ExtractionStore(Protocol):
    def mark_processing(self, document_id: UUID) -> None: ...

    def save(self, document_id: UUID, result: ExtractionResult) -> None: ...

    def mark_error(self, document_id: UUID, message: str) -> None: ...

    def pending_documents(self, limit: int) -> list[Document]: ...


class QueuedDocumentProcessor:
    """Implementação do `DocumentProcessor` (P08) com o agente de IA."""

    def __init__(
        self,
        extractor: FileExtractor,
        store: ExtractionStore,
        inbox_dir: Path,
        start_worker: bool = True,
        max_queue: int = DEFAULT_MAX_QUEUE,
        sweep_interval: float = SWEEP_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_queue < 1:
            raise ValueError("O limite da fila precisa ser positivo.")
        self._extractor = extractor
        self._store = store
        self._inbox = inbox_dir.resolve()
        self._max_queue = max_queue
        self._queue: queue.Queue[Document] = queue.Queue(maxsize=max_queue)
        self._queued: set[UUID] = set()  # na fila ou em processamento (evita duplicar)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sweep_interval = sweep_interval
        self._clock = clock
        self._last_sweep = float("-inf")
        self._worker: threading.Thread | None = None
        if start_worker:
            self._worker = threading.Thread(target=self._loop, name="extracao-ia", daemon=True)
            self._worker.start()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def submit(self, document: Document) -> None:
        """Enfileira sem bloquear. Fila cheia: o documento fica RECEBIDO e entra na varredura."""
        if self._enqueue(document):
            logger.info("documento %s na fila de extração (%d na fila)", document.id, self.pending)
        else:
            logger.info("documento %s fica para a próxima varredura", document.id)

    def sweep(self) -> int:
        """Recoloca na fila os documentos RECEBIDO/PROCESSANDO do banco. Devolve quantos."""
        self._last_sweep = self._clock()
        try:
            documents = self._store.pending_documents(self._max_queue)
        except Exception as exc:
            logger.warning("varredura de documentos pendentes falhou (%s)", type(exc).__name__)
            return 0
        added = sum(1 for document in documents if self._enqueue(document))
        if added:
            logger.info("varredura: %d documento(s) recolocado(s) na fila", added)
        return added

    def process_next(self, timeout: float | None = None) -> bool:
        """Processa um documento da fila; False se ela ficou vazia até o `timeout`."""
        try:
            document = self._queue.get(timeout=timeout) if timeout else self._queue.get_nowait()
        except queue.Empty:
            return False
        try:
            self._process(document)
        finally:
            with self._lock:
                self._queued.discard(document.id)
            self._queue.task_done()
        return True

    def join(self, timeout: float) -> None:
        """Espera a fila esvaziar (testes e encerramento)."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            self._stop.wait(0.01)

    def stop(self, timeout: float = 10.0) -> None:
        """Pede o fim do worker e espera o documento em andamento terminar (até `timeout`)."""
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=timeout)

    def _enqueue(self, document: Document) -> bool:
        with self._lock:
            if document.id in self._queued:
                return False
            try:
                self._queue.put_nowait(document)
            except queue.Full:
                return False
            self._queued.add(document.id)
            return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._clock() - self._last_sweep >= self._sweep_interval:
                self.sweep()  # também na partida: recupera o que um reinício deixou para trás
            self.process_next(timeout=0.5)

    def _process(self, document: Document) -> None:
        try:
            self._store.mark_processing(document.id)
            result = self._extract(document)
        except Exception as exc:
            logger.error("documento %s: erro inesperado (%s)", document.id, type(exc).__name__)
            result = ExtractionResult(
                Outcome.ERRO, None, erro=f"erro interno na extração ({type(exc).__name__})"
            )
        self._save(document.id, result)

    def _extract(self, document: Document) -> ExtractionResult:
        """Confere de novo caminho e conteúdo: entre o 202 e a vez na fila o arquivo pode ter
        sido trocado (ou virado link para fora da inbox)."""
        path = (self._inbox / document.nome_arquivo).resolve()
        if not path.is_relative_to(self._inbox) or not path.is_file():
            return ExtractionResult(Outcome.ERRO, None, erro="arquivo não está mais na inbox")
        sha256, _size = digest_file(path)
        if sha256 != document.sha256:
            return ExtractionResult(
                Outcome.ERRO, None, erro="o arquivo mudou depois do registro (SHA-256 diferente)"
            )
        return self._extractor.extract_file(path)

    def _save(self, document_id: UUID, result: ExtractionResult) -> None:
        try:
            self._store.save(document_id, result)
        except Exception as exc:
            logger.error("documento %s: gravação falhou (%s)", document_id, type(exc).__name__)
            self._mark_error(document_id)
            return
        logger.info("documento %s: %s (score %s)", document_id, result.outcome, result.score)

    def _mark_error(self, document_id: UUID) -> None:
        try:
            self._store.mark_error(document_id, SAVE_FAILED_MESSAGE)
        except Exception as exc:
            logger.error(
                "documento %s: nem o ERRO foi gravado (%s)", document_id, type(exc).__name__
            )

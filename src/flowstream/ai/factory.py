"""Monta as peças reais do agente (Ollama, Tesseract, banco) a partir do Settings."""

from sqlalchemy import Engine

from flowstream.ai.adapters import PostgresExtractionStore
from flowstream.ai.llm import DEFAULT_TIMEOUT_SECONDS, OllamaClient
from flowstream.ai.pdf_text import tesseract_ocr
from flowstream.ai.pipeline import ExtractionPipeline
from flowstream.ai.prompting import PROMPT_VERSION
from flowstream.ai.service import QueuedDocumentProcessor
from flowstream.config import Settings


def build_pipeline(
    settings: Settings,
    model: str | None = None,
    prompt_version: str = PROMPT_VERSION,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ExtractionPipeline:
    """`model`, `prompt_version` e `timeout` trocam o padrão (OLLAMA_MODEL, v1, 120 s) na
    avaliação (P11): na CPU de 8 GB, um BL longo passa de 120 s."""
    llm = OllamaClient(settings.ollama_url, model or settings.ollama_model, timeout=timeout)
    return ExtractionPipeline(
        llm=llm, ocr=tesseract_ocr(settings.tesseract_cmd), prompt_version=prompt_version
    )


def build_processor(settings: Settings, engine: Engine) -> QueuedDocumentProcessor:
    """Processador da API: uma fila e um worker por processo."""
    return QueuedDocumentProcessor(
        build_pipeline(settings), PostgresExtractionStore(engine), inbox_dir=settings.inbox_dir
    )

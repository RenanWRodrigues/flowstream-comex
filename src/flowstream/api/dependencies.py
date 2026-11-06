"""Dependências da API: configuração, chave, repositórios e verificação de saúde.

Cada uma pode ser trocada nos testes por `app.dependency_overrides`.
"""

import secrets
from functools import lru_cache
from typing import Annotated, Protocol

import httpx
from fastapi import Depends, Header
from sqlalchemy import Engine, text

from flowstream.api.errors import ProblemError
from flowstream.config import Settings, get_settings
from flowstream.db import create_db_engine
from flowstream.documents.adapters import PostgresDocumentRepository
from flowstream.documents.service import DocumentProcessor, DocumentRepository
from flowstream.operations.adapters import PostgresOperationsRepository
from flowstream.operations.service import OperationsRepository

OLLAMA_TIMEOUT_SECONDS = 2.0


def get_api_settings() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_db_engine()


def require_api_key(
    settings: Annotated[Settings, Depends(get_api_settings)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    if settings.api_key is None:
        raise ProblemError(503, "A API está sem API_KEY configurada no .env.")
    expected = settings.api_key.get_secret_value().encode()
    if x_api_key is None or not secrets.compare_digest(x_api_key.encode(), expected):
        raise ProblemError(401, "Informe uma chave válida no header X-API-Key.")


def get_operations_repository() -> OperationsRepository:
    return PostgresOperationsRepository(get_engine())


def get_document_repository() -> DocumentRepository:
    return PostgresDocumentRepository(get_engine())


@lru_cache(maxsize=1)
def _document_processor() -> DocumentProcessor:  # pragma: no cover - liga Ollama/OCR reais
    # Import tardio: pdfplumber e afins só carregam quando o primeiro documento chega.
    from flowstream.ai.factory import build_processor

    return build_processor(get_settings(), get_engine())


def shutdown_document_processor() -> None:
    """Encerramento da API: espera o documento em andamento, se o processador foi criado."""
    if _document_processor.cache_info().currsize:  # pragma: no cover - só com o processador real
        processor = _document_processor()
        stop = getattr(processor, "stop", None)
        if callable(stop):
            stop()


def get_document_processor() -> DocumentProcessor:
    """Agente de IA (P10): uma fila e um worker por processo, uma chamada ao modelo por vez."""
    return _document_processor()


class HealthChecker(Protocol):
    def check(self) -> dict[str, bool]: ...


class SystemHealthChecker:
    """Banco: um `select 1`. Ollama: GET /api/tags com timeout curto."""

    def __init__(self, ollama_url: str, http: httpx.Client | None = None) -> None:
        self._ollama_url = ollama_url.rstrip("/")
        # Serviço local: sem proxy do ambiente (com proxy, a chamada a 127.0.0.1 trava).
        self.http = http or httpx.Client(trust_env=False, timeout=OLLAMA_TIMEOUT_SECONDS)

    def check(self) -> dict[str, bool]:
        return {"banco": self._database(), "ollama": self._ollama()}

    def _database(self) -> bool:
        try:
            with get_engine().connect() as conn:
                conn.execute(text("select 1"))
        except Exception:
            return False
        return True

    def _ollama(self) -> bool:
        try:
            response = self.http.get(f"{self._ollama_url}/api/tags")
        except httpx.HTTPError:
            return False
        return response.status_code == 200


@lru_cache(maxsize=4)
def _health_checker(ollama_url: str) -> SystemHealthChecker:
    # Um por URL: criar o httpx.Client custa ~1 s no Windows (contexto SSL).
    return SystemHealthChecker(ollama_url)


def get_health_checker(
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> HealthChecker:
    return _health_checker(settings.ollama_url)

"""Erros no formato RFC 9457 (application/problem+json), sem stack trace nem dado sensível."""

from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from flowstream.logging import get_logger

PROBLEM_MEDIA_TYPE = "application/problem+json"

logger = get_logger(__name__)


class ProblemError(Exception):
    """Erro de negócio já traduzido para HTTP; vira um problem+json."""

    def __init__(self, status: int, detail: str, **extensions: Any) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.extensions = extensions


def problem(
    status: int, detail: str, instance: str | None = None, **extensions: Any
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
    }
    if instance:
        body["instance"] = instance
    body.update(extensions)
    headers = {"WWW-Authenticate": "ApiKey"} if status == 401 else None
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE, headers=headers)


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem(exc.status, exc.detail, request.url.path, **exc.extensions)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
        if exc.status_code == 404 and detail == "Not Found":
            detail = "Recurso não encontrado."
        return problem(exc.status_code, detail, request.url.path)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Só onde e o quê: o valor recebido não volta na resposta.
        errors = [
            {"campo": ".".join(str(part) for part in error["loc"]), "mensagem": error["msg"]}
            for error in exc.errors()
        ]
        return problem(422, "Requisição inválida.", request.url.path, erros=errors)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        error_id = uuid4().hex[:12]
        logger.error("erro inesperado %s em %s: %s", error_id, request.url.path, type(exc).__name__)
        return problem(
            500, f"Erro inesperado. Informe o código {error_id} ao suporte.", request.url.path
        )

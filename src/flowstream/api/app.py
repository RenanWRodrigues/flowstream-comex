"""Aplicação FastAPI do FlowStream-Comex. Rode com `make api` (uvicorn, com recarga)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from flowstream import __version__
from flowstream.api.dependencies import shutdown_document_processor
from flowstream.api.errors import install_handlers
from flowstream.api.routers import documentos, embarques, health, tracking

DESCRIPTION = """
API do FlowStream-Comex, consumida pelo n8n e pela tela de revisão.

- **Autenticação:** header `X-API-Key` (valor em `API_KEY` no `.env`); só `/health` é pública.
- **Erros:** formato RFC 9457 (`application/problem+json`), sem detalhes internos.
- **Datas:** ISO 8601 com fuso.
"""


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    shutdown_document_processor()  # o worker de extração termina o documento em andamento


def create_app() -> FastAPI:
    app = FastAPI(
        lifespan=_lifespan,
        title="FlowStream-Comex API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=[
            {"name": "saúde", "description": "Monitoramento."},
            {"name": "rastreamento", "description": "Linha do tempo dos contêineres."},
            {"name": "embarques", "description": "Embarques que pedem ação."},
            {"name": "documentos", "description": "Documentos de embarque da inbox."},
        ],
    )
    install_handlers(app)
    for module in (health, tracking, embarques, documentos):
        app.include_router(module.router)
    return app


app = create_app()

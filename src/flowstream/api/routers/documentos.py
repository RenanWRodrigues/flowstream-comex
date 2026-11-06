from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from flowstream.api.dependencies import (
    get_api_settings,
    get_document_processor,
    get_document_repository,
    require_api_key,
)
from flowstream.api.errors import ProblemError
from flowstream.api.routers import PROBLEM_RESPONSES
from flowstream.api.schemas import DocumentAcceptedOut, DocumentIn, DocumentOut, ProblemOut
from flowstream.config import Settings
from flowstream.documents.domain import InvalidDocumentNameError
from flowstream.documents.service import (
    DocumentNotFoundError,
    DocumentProcessor,
    DocumentRepository,
    DuplicateDocumentError,
    get_document,
    register_document,
)

router = APIRouter(
    prefix="/v1/documentos", tags=["documentos"], dependencies=[Depends(require_api_key)]
)


@router.post(
    "",
    status_code=202,
    response_model=DocumentAcceptedOut,
    summary="Registrar um PDF da inbox",
    description=(
        "Registra um PDF que já está em data/inbox e o envia para extração. Aceita só o nome "
        "do arquivo: qualquer caminho (`../`, `/`, `C:\\`) é recusado com 400. O mesmo "
        "conteúdo (SHA-256) registrado de novo dá 409, com o id existente. Responde 202 e o "
        "header Location aponta para a consulta do status."
    ),
    responses={
        **PROBLEM_RESPONSES,
        400: {"model": ProblemOut, "description": "Nome inválido ou fora da inbox."},
        404: {"model": ProblemOut, "description": "Arquivo não está na inbox."},
        409: {"model": ProblemOut, "description": "Conteúdo já registrado (documento_id)."},
    },
)
def create_document(
    body: DocumentIn,
    response: Response,
    settings: Annotated[Settings, Depends(get_api_settings)],
    repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    processor: Annotated[DocumentProcessor, Depends(get_document_processor)],
) -> DocumentAcceptedOut:
    try:
        document = register_document(body.arquivo, settings.inbox_dir, repository, processor)
    except InvalidDocumentNameError as exc:
        raise ProblemError(400, str(exc)) from None
    except DocumentNotFoundError:
        raise ProblemError(404, "Arquivo não encontrado na inbox.") from None
    except DuplicateDocumentError as exc:
        raise ProblemError(
            409, "Este conteúdo já foi registrado.", documento_id=str(exc.document_id)
        ) from None
    response.headers["Location"] = f"/v1/documentos/{document.id}"
    return DocumentAcceptedOut(id=document.id, status=document.status)


@router.get(
    "/{documento_id}",
    response_model=DocumentOut,
    summary="Status e resultado de um documento",
    description="Status do processamento e, depois da extração (P10), o resultado validado.",
    responses={
        **PROBLEM_RESPONSES,
        404: {"model": ProblemOut, "description": "Documento não encontrado."},
    },
)
def read_document(
    documento_id: UUID,
    repository: Annotated[DocumentRepository, Depends(get_document_repository)],
) -> DocumentOut:
    document = get_document(documento_id, repository)
    if document is None:
        raise ProblemError(404, "Documento não encontrado.")
    return DocumentOut(
        id=document.id,
        arquivo=document.nome_arquivo,
        status=document.status,
        tipo_documento=document.tipo_documento,
        resultado=document.resultado,
        erro=document.erro,
        recebido_em=document.recebido_em,
        atualizado_em=document.atualizado_em,
    )

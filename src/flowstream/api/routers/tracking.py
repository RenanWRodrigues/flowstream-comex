from typing import Annotated

from fastapi import APIRouter, Depends

from flowstream.api.dependencies import get_operations_repository, require_api_key
from flowstream.api.errors import ProblemError
from flowstream.api.routers import PROBLEM_RESPONSES
from flowstream.api.schemas import ProblemOut, TimelineOut
from flowstream.operations.domain import InvalidContainerError
from flowstream.operations.service import OperationsRepository, container_timeline

router = APIRouter(
    prefix="/v1/tracking", tags=["rastreamento"], dependencies=[Depends(require_api_key)]
)


@router.get(
    "/{container_number}",
    response_model=TimelineOut,
    summary="Linha do tempo de um contêiner",
    description=(
        "Eventos do processo mais recente do contêiner: booking, gate in, embarque, "
        "transbordo, atualizações de ETA, chegada, liberação e devolução do vazio. O número "
        "é validado pela ISO 6346 (dígito verificador) e aceita espaços e minúsculas."
    ),
    responses={
        **PROBLEM_RESPONSES,
        404: {"model": ProblemOut, "description": "Contêiner sem processo registrado."},
    },
)
def tracking(
    container_number: str,
    repository: Annotated[OperationsRepository, Depends(get_operations_repository)],
) -> TimelineOut:
    try:
        timeline = container_timeline(container_number, repository)
    except InvalidContainerError as exc:
        raise ProblemError(422, str(exc)) from None
    if timeline is None:
        raise ProblemError(404, "Nenhum processo encontrado para este contêiner.")
    return TimelineOut.model_validate(timeline.model_dump())

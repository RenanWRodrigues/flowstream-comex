from typing import Annotated

from fastapi import APIRouter, Depends, Query

from flowstream.api.dependencies import get_operations_repository, require_api_key
from flowstream.api.routers import PROBLEM_RESPONSES
from flowstream.api.schemas import RiskListOut, RiskOut
from flowstream.operations.service import MAX_RISK_DAYS, OperationsRepository, demurrage_risk

router = APIRouter(
    prefix="/v1/embarques", tags=["embarques"], dependencies=[Depends(require_api_key)]
)


@router.get(
    "/risco",
    response_model=RiskListOut,
    summary="Contêineres em risco de demurrage",
    description=(
        "Contêineres de importação chegados e ainda não devolvidos com até `dias` dias livres "
        "restantes (inclui os já vencidos), do mais urgente para o menos urgente. Fonte: "
        "ouro.kpi_demurrage_risco."
    ),
    responses=PROBLEM_RESPONSES,
)
def risk(
    repository: Annotated[OperationsRepository, Depends(get_operations_repository)],
    dias: Annotated[
        int, Query(ge=0, le=MAX_RISK_DAYS, description="Máximo de dias livres restantes.")
    ] = 3,
) -> RiskListOut:
    containers = demurrage_risk(dias, repository)
    return RiskListOut(
        dias=dias,
        data_referencia=containers[0].data_referencia if containers else None,
        total=len(containers),
        conteineres=[RiskOut.model_validate(c.model_dump()) for c in containers],
    )

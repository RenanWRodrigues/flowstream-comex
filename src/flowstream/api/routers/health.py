from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from flowstream.api.dependencies import HealthChecker, get_health_checker
from flowstream.api.schemas import HealthOut

router = APIRouter(tags=["saúde"])


@router.get(
    "/health",
    response_model=HealthOut,
    summary="Saúde da API",
    description=(
        "Verifica o banco e o Ollama. Pública (sem chave), para monitoramento. Responde 200 "
        "com o banco de pé (`degradado` se faltar só o Ollama) e 503 sem o banco."
    ),
    responses={503: {"model": HealthOut, "description": "Banco indisponível."}},
)
def health(checker: Annotated[HealthChecker, Depends(get_health_checker)]) -> JSONResponse:
    state = checker.check()
    database, ollama = state.get("banco", False), state.get("ollama", False)
    status: Literal["ok", "degradado", "indisponivel"] = (
        "ok" if database and ollama else "degradado" if database else "indisponivel"
    )
    body = HealthOut(
        status=status,
        banco="ok" if database else "indisponivel",
        ollama="ok" if ollama else "indisponivel",
    )
    return JSONResponse(body.model_dump(), status_code=200 if database else 503)

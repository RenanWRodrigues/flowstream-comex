"""Rotas da API, finas: validam, chamam o serviço e traduzem o resultado."""

from typing import Any

from flowstream.api.schemas import ProblemOut

PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ProblemOut, "description": description}
    for status, description in {
        401: "Sem a chave X-API-Key, ou chave errada.",
        422: "Parâmetro inválido.",
        500: "Erro inesperado (sem detalhes internos).",
    }.items()
}

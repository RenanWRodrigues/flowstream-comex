"""Registro de execuções em ops.pipeline_runs (início, fim, status, linhas e erro)."""

from sqlalchemy import Engine, text

from flowstream.db import transaction
from flowstream.logging import mask_sensitive

_MAX_ERROR = 500


def start_run(engine: Engine, pipeline: str) -> int:
    """Abre uma execução com status EM_ANDAMENTO e devolve o id."""
    with transaction(engine) as conn:
        run_id = conn.execute(
            text(
                "insert into ops.pipeline_runs (pipeline, status) "
                "values (:pipeline, 'EM_ANDAMENTO') returning id"
            ),
            {"pipeline": pipeline},
        ).scalar_one()
    return int(run_id)


def finish_run(
    engine: Engine,
    run_id: int,
    *,
    rows_in: int | None = None,
    rows_out: int | None = None,
    error: BaseException | None = None,
) -> None:
    """Fecha a execução com SUCESSO, ou com ERRO e uma mensagem curta e mascarada."""
    message = None
    if error is not None:
        message = mask_sensitive(f"{type(error).__name__}: {error}")[:_MAX_ERROR]
    with transaction(engine) as conn:
        conn.execute(
            text(
                "update ops.pipeline_runs set finished_at = now(), status = :status, "
                "rows_in = :rows_in, rows_out = :rows_out, error = :error where id = :id"
            ),
            {
                "status": "ERRO" if error is not None else "SUCESSO",
                "rows_in": rows_in,
                "rows_out": rows_out,
                "error": message,
                "id": run_id,
            },
        )

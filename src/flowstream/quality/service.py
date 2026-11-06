"""flowstream quality run: dbt build + freshness + volume, tudo registrado no schema ops."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from sqlalchemy import Engine

from flowstream.config import get_settings
from flowstream.db import create_db_engine
from flowstream.domain.dates import now_sao_paulo
from flowstream.logging import get_logger
from flowstream.pipeline_runs import finish_run, start_run
from flowstream.quality.adapters import (
    DbtCliRunner,
    PostgresQualityRepository,
    dbt_environment,
)
from flowstream.quality.domain import (
    DqResult,
    QualitySummary,
    VolumeAnomaly,
    detect_volume_anomalies,
    parse_run_results,
    parse_sources,
    summarize,
)

PIPELINE = "quality_run"
HEALTH_MODEL = "kpi_saude_dados"

logger = get_logger(__name__)


class QualityCheckFailedError(RuntimeError):
    """A execução terminou, mas há teste falhando, erro de execução ou fonte vencida."""


class DbtRunner(Protocol):
    target_dir: Path

    def run(self, args: list[str]) -> bool: ...


class QualityRepository(Protocol):
    def load_volumes(self, today: date, days: int = 15) -> dict[str, dict[date, int]]: ...

    def save_results(self, run_id: int, results: list[DqResult]) -> None: ...

    def save_anomalies(self, run_id: int, anomalies: list[VolumeAnomaly]) -> None: ...


@dataclass(frozen=True)
class QualityReport:
    summary: QualitySummary
    results: list[DqResult]
    anomalies: list[VolumeAnomaly]


def run_quality(
    dbt: DbtRunner, repository: QualityRepository, run_id: int, today: date
) -> QualityReport:
    """Executa dbt build e freshness, mede volumes, grava tudo e atualiza o KPI de saúde."""
    results = _execute(dbt, ["build"], "run_results.json", parse_run_results)
    results += _execute(dbt, ["source", "freshness"], "sources.json", parse_sources)
    anomalies = detect_volume_anomalies(repository.load_volumes(today), today)
    repository.save_results(run_id, results)
    repository.save_anomalies(run_id, anomalies)
    # O build roda antes da gravação: reconstrói o KPI para ele já incluir esta execução.
    dbt.run(["run", "--select", HEALTH_MODEL])
    return QualityReport(summarize(results, anomalies), results, anomalies)


def _execute(
    dbt: DbtRunner, args: list[str], artifact: str, parse: Callable[[str], list[DqResult]]
) -> list[DqResult]:
    path = dbt.target_dir / artifact
    path.unlink(missing_ok=True)  # nunca ler o artefato de uma execução anterior
    dbt.run(args)
    command = " ".join(args)
    if not path.is_file():
        return [
            DqResult(
                tipo="dbt",
                recurso=f"dbt.{'_'.join(args)}",
                nome=f"dbt {command}",
                status="error",
                duracao_s=Decimal(0),
                mensagem=(
                    f"dbt {command} não gerou {artifact}: falhou antes de executar "
                    "(veja dbt/logs/dbt.log)."
                ),
            )
        ]
    return parse(path.read_text(encoding="utf-8"))


def run_quality_check(
    *, engine: Engine | None = None, dbt: DbtRunner | None = None, today: date | None = None
) -> QualityReport:
    """Execução completa, registrada em ops.pipeline_runs (ERRO se a qualidade reprovar)."""
    settings = get_settings()
    engine = engine or create_db_engine(settings)
    run_id = start_run(engine, PIPELINE)
    try:
        with dbt_environment(settings.database_url.get_secret_value()):
            report = run_quality(
                dbt or DbtCliRunner(),
                PostgresQualityRepository(engine),
                run_id,
                today or now_sao_paulo().date(),
            )
    except Exception as exc:
        finish_run(engine, run_id, error=exc)
        raise
    s = report.summary
    problem = None
    if not s.ok:
        problem = QualityCheckFailedError(
            f"{s.testes_falha} testes falhando, {s.recursos_com_erro} erros de execução, "
            f"{s.fontes_com_erro} fontes vencidas"
        )
    finish_run(
        engine, run_id, rows_in=len(report.results), rows_out=len(report.results), error=problem
    )
    logger.info("qualidade: %s resultados, ok=%s", len(report.results), s.ok)
    return report

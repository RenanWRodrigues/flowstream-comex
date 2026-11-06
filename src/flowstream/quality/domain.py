"""Regras puras de qualidade: ler os artefatos do dbt, resumir e detectar anomalias de volume."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from flowstream.logging import mask_sensitive

MAX_MESSAGE = 500
RESOURCE_TYPES = ("model", "seed", "snapshot", "test")
FAILED_TEST = ("fail", "error")
LATE_SOURCE = ("warn", "error", "runtime error")
SOURCE_ERROR = ("error", "runtime error")

WINDOW_DAYS = 14
THRESHOLD = Decimal("0.5")


class QualityResultsError(ValueError):
    """Artefato do dbt (run_results.json, sources.json) fora do formato esperado."""


class DqResult(BaseModel):
    """Um resultado de qualidade: teste, modelo, seed, snapshot, freshness ou falha do dbt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tipo: str  # test | model | seed | snapshot | freshness | dbt
    recurso: str  # unique_id do dbt
    nome: str
    status: str  # como o dbt informa: pass, fail, warn, error, success, skipped...
    linhas_com_falha: int | None = None
    duracao_s: Decimal
    mensagem: str | None = None


class VolumeAnomaly(BaseModel):
    """Carga do dia muito diferente da média recente da mesma tabela."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tabela: str
    data_referencia: date
    linhas_no_dia: int
    media_14_dias: Decimal
    desvio_pct: Decimal  # fração: 0,80 = 80% acima da média
    direcao: Literal["ACIMA", "ABAIXO"]


@dataclass(frozen=True)
class QualitySummary:
    testes_ok: int
    testes_aviso: int
    testes_falha: int
    recursos_com_erro: int
    fontes_atrasadas: int
    fontes_com_erro: int
    anomalias: int

    @property
    def ok(self) -> bool:
        """Reprova só o que exige ação: teste falhando, erro de execução, fonte vencida."""
        return self.testes_falha == 0 and self.recursos_com_erro == 0 and self.fontes_com_erro == 0


# ------------------------------------------------------------------ artefatos do dbt


def parse_run_results(body: str) -> list[DqResult]:
    """run_results.json de `dbt build`: um resultado por modelo, seed, snapshot e teste."""
    results = []
    for item in _results(body):
        resource = _text(item, "unique_id")
        kind = resource.split(".")[0]
        if kind not in RESOURCE_TYPES:
            continue  # exposures e afins não executam nada
        failures = item.get("failures")
        results.append(
            DqResult(
                tipo=kind,
                recurso=resource,
                nome=_name(resource),
                status=_text(item, "status").lower(),
                linhas_com_falha=failures if isinstance(failures, int) else None,
                duracao_s=_seconds(item.get("execution_time")),
                mensagem=_message(item.get("message")),
            )
        )
    return results


def parse_sources(body: str) -> list[DqResult]:
    """sources.json de `dbt source freshness`: um resultado por fonte."""
    results = []
    for item in _results(body):
        resource = _text(item, "unique_id")
        age = item.get("max_loaded_at_time_ago_in_s")
        results.append(
            DqResult(
                tipo="freshness",
                recurso=resource,
                nome=".".join(resource.split(".")[2:]),
                status=_text(item, "status").lower(),
                duracao_s=_seconds(item.get("execution_time")),
                mensagem=f"último dado há {_age(age)}" if isinstance(age, int | float) else None,
            )
        )
    return results


def summarize(results: Sequence[DqResult], anomalies: Sequence[VolumeAnomaly]) -> QualitySummary:
    tests = [r for r in results if r.tipo == "test"]
    sources = [r for r in results if r.tipo == "freshness"]
    return QualitySummary(
        testes_ok=sum(1 for r in tests if r.status == "pass"),
        testes_aviso=sum(1 for r in tests if r.status == "warn"),
        testes_falha=sum(1 for r in tests if r.status in FAILED_TEST),
        recursos_com_erro=sum(
            1 for r in results if r.tipo not in ("test", "freshness") and r.status == "error"
        ),
        fontes_atrasadas=sum(1 for r in sources if r.status in LATE_SOURCE),
        fontes_com_erro=sum(1 for r in sources if r.status in SOURCE_ERROR),
        anomalias=len(anomalies),
    )


def _results(body: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise QualityResultsError("Artefato do dbt não é JSON.") from None
    items = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise QualityResultsError("Artefato do dbt sem a lista 'results'.")
    return items


def _text(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise QualityResultsError(f"Resultado do dbt sem o campo '{key}'.")
    return value


def _name(resource: str) -> str:
    parts = resource.split(".")
    return parts[2] if len(parts) > 2 else resource


def _seconds(value: object) -> Decimal:
    return Decimal(str(round(value, 3))) if isinstance(value, int | float) else Decimal(0)


def _message(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return mask_sensitive(value)[:MAX_MESSAGE]


def _age(seconds: float) -> str:
    if seconds >= 2 * 86_400:
        return f"{seconds / 86_400:.1f} dias".replace(".", ",")
    return f"{seconds / 3_600:.1f} h".replace(".", ",")


# ------------------------------------------------------------------ anomalias de volume


def detect_volume_anomalies(
    volumes: Mapping[str, Mapping[date, int]],
    today: date,
    *,
    window_days: int = WINDOW_DAYS,
    threshold: Decimal = THRESHOLD,
) -> list[VolumeAnomaly]:
    """Linhas carregadas hoje vs. média dos dias com carga nos últimos `window_days` dias.

    Desvio maior que `threshold` (50%) para cima ou para baixo vira anomalia. Tabela sem
    carga hoje ou sem histórico não é comparada (a ausência de carga é papel da freshness).
    """
    anomalies = []
    first_day = today - timedelta(days=window_days)
    for table in sorted(volumes):
        rows_today = volumes[table].get(today, 0)
        history = [n for day, n in volumes[table].items() if first_day <= day < today and n > 0]
        if not rows_today or not history:
            continue
        mean = Decimal(sum(history)) / len(history)
        deviation = (Decimal(rows_today) - mean) / mean
        if abs(deviation) > threshold:
            anomalies.append(
                VolumeAnomaly(
                    tabela=table,
                    data_referencia=today,
                    linhas_no_dia=rows_today,
                    media_14_dias=mean.quantize(Decimal("0.01")),
                    desvio_pct=deviation.quantize(Decimal("0.0001")),
                    direcao="ACIMA" if deviation > 0 else "ABAIXO",
                )
            )
    return anomalies

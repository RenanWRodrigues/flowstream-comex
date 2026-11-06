"""Testes do serviço de qualidade com dbt e banco falsos."""

import os
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from flowstream.quality.adapters import dbt_env, dbt_environment
from flowstream.quality.domain import DqResult, VolumeAnomaly
from flowstream.quality.service import run_quality

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "dbt"
TODAY = date(2026, 11, 3)


class FakeDbt:
    """Imita o dbt: cada comando grava (ou não) o artefato correspondente em target/."""

    def __init__(self, target: Path, files: dict[str, str | None], success: bool = True) -> None:
        self.target_dir = target
        self.files = files  # comando -> fixture a gravar (None = não grava nada)
        self.success = success
        self.commands: list[list[str]] = []

    def run(self, args: list[str]) -> bool:
        self.commands.append(args)
        key = " ".join(args[:2]) if args[0] == "source" else args[0]
        fixture = self.files.get(key)
        artifact = "sources.json" if args[0] == "source" else "run_results.json"
        if fixture:
            shutil.copy(FIXTURES / fixture, self.target_dir / artifact)
        return self.success


class FakeRepository:
    def __init__(self, volumes: dict[str, dict[date, int]] | None = None) -> None:
        self.volumes = volumes or {}
        self.results: list[DqResult] = []
        self.anomalies: list[VolumeAnomaly] = []
        self.run_ids: list[int] = []

    def load_volumes(self, today: date, days: int = 15) -> dict[str, dict[date, int]]:
        return self.volumes

    def save_results(self, run_id: int, results: list[DqResult]) -> None:
        self.run_ids.append(run_id)
        self.results.extend(results)

    def save_anomalies(self, run_id: int, anomalies: list[VolumeAnomaly]) -> None:
        self.anomalies.extend(anomalies)


def dbt(tmp_path: Path, **files: str | None) -> FakeDbt:
    mapping = {"build": "run_results_sucesso.json", "source freshness": "sources.json"}
    mapping.update({k.replace("_", " "): v for k, v in files.items()})
    return FakeDbt(tmp_path, mapping)


def test_runs_build_then_freshness_then_refreshes_the_health_kpi(tmp_path: Path) -> None:
    fake = dbt(tmp_path)

    run_quality(fake, FakeRepository(), run_id=7, today=TODAY)

    assert [c[:2] for c in fake.commands] == [
        ["build"],
        ["source", "freshness"],
        ["run", "--select"],
    ]
    assert fake.commands[-1] == ["run", "--select", "kpi_saude_dados"]


def test_records_test_and_freshness_results_with_the_run_id(tmp_path: Path) -> None:
    repo = FakeRepository()

    report = run_quality(dbt(tmp_path), repo, run_id=7, today=TODAY)

    assert repo.run_ids == [7]
    assert {r.tipo for r in repo.results} == {"model", "seed", "snapshot", "test", "freshness"}
    assert report.summary.ok


def test_failures_make_the_report_not_ok(tmp_path: Path) -> None:
    fake = dbt(tmp_path, build="run_results_falha.json", source_freshness="sources_atrasada.json")

    report = run_quality(fake, FakeRepository(), run_id=1, today=TODAY)

    assert not report.summary.ok
    assert report.summary.testes_falha == 1
    assert report.summary.fontes_atrasadas == 2


def test_dbt_that_crashes_before_writing_artifacts_is_recorded_as_error(tmp_path: Path) -> None:
    (tmp_path / "run_results.json").write_text('{"results": []}', encoding="utf-8")  # antigo
    repo = FakeRepository()

    report = run_quality(dbt(tmp_path, build=None), repo, run_id=1, today=TODAY)

    crash = [r for r in repo.results if r.tipo == "dbt"]
    assert len(crash) == 1
    assert crash[0].status == "error"
    assert "run_results.json" in (crash[0].mensagem or "")
    assert not report.summary.ok  # o artefato antigo não foi aproveitado


def test_volume_anomalies_are_detected_and_saved(tmp_path: Path) -> None:
    history = {TODAY - timedelta(days=d): 100 for d in range(1, 15)}
    repo = FakeRepository(volumes={"bronze.ptax": {**history, TODAY: 400}})

    report = run_quality(dbt(tmp_path), repo, run_id=1, today=TODAY)

    assert [a.tabela for a in repo.anomalies] == ["bronze.ptax"]
    assert report.summary.anomalias == 1
    assert report.summary.ok  # anomalia de volume avisa, mas não reprova a execução


# ------------------------------------------------------------------ ambiente do dbt


def test_dbt_env_comes_from_database_url() -> None:
    env = dbt_env("postgresql+psycopg://app:s3nha@127.0.0.1:5433/flowstream")

    assert env == {
        "APP_DB_USER": "app",
        "APP_DB_PASSWORD": "s3nha",
        "DBT_HOST": "127.0.0.1",
        "POSTGRES_PORT": "5433",
        "POSTGRES_DB": "flowstream",
    }


def test_dbt_env_decodes_special_characters_in_password() -> None:
    env = dbt_env("postgresql+psycopg://app:p%40ss%23word@127.0.0.1:5433/flowstream")

    assert env["APP_DB_PASSWORD"] == "p@ss#word"  # noqa: S105 - senha fictícia de teste


def test_dbt_environment_sets_and_restores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PORT", "9999")
    monkeypatch.delenv("APP_DB_USER", raising=False)

    with dbt_environment("postgresql+psycopg://app:x@127.0.0.1:5433/db"):
        assert os.environ["POSTGRES_PORT"] == "5433"
        assert os.environ["APP_DB_USER"] == "app"

    assert os.environ["POSTGRES_PORT"] == "9999"
    assert "APP_DB_USER" not in os.environ

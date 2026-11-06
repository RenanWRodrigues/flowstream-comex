"""Testes da interface de linha de comando."""

import json
from datetime import date
from pathlib import Path
from typing import ClassVar

import pytest
from sqlalchemy.exc import OperationalError
from typer.testing import CliRunner

from flowstream import __version__, cli
from flowstream.cli import app
from flowstream.config import ConfigError, Settings
from flowstream.db import Migration, MigrationError
from flowstream.domain.dates import now_sao_paulo
from flowstream.ingestion.comexstat import (
    ComexIngestResult,
    ComexResponseError,
    ComexUnavailableError,
)
from flowstream.ingestion.ptax import PtaxIngestResult, PtaxResponseError, PtaxUnavailableError
from flowstream.quality.domain import QualitySummary
from flowstream.quality.service import QualityReport
from flowstream.synthetic.service import SyntheticDataError

runner = CliRunner()


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"flowstream-comex {__version__}"


def test_version_matches_installed_metadata() -> None:
    from importlib.metadata import version

    assert __version__ == version("flowstream-comex")


def test_help_lists_all_groups() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for group in ("ingest", "synthetic", "ai", "export", "version"):
        assert group in result.output


@pytest.mark.parametrize("group", ["export"])
def test_empty_groups_say_under_construction(group: str) -> None:
    result = runner.invoke(app, [group])

    assert result.exit_code == 0
    assert "em construção" in result.output


# ------------------------------------------------------------------ flowstream db migrate


def _migration(version: str, name: str) -> Migration:
    return Migration(
        version=version, name=name, sql="select 1;", path=Path(f"{version}_{name}.sql")
    )


def test_db_migrate_lists_applied_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[Path] = []

    def fake_migrate(directory: Path) -> list[Migration]:
        received.append(directory)
        return [_migration("001", "schemas"), _migration("002", "pipeline_runs")]

    monkeypatch.setattr(cli, "migrate", fake_migrate)

    result = runner.invoke(app, ["db", "migrate", "--dir", "outra/pasta"])

    assert result.exit_code == 0
    assert "001_schemas.sql" in result.output
    assert "002_pipeline_runs.sql" in result.output
    assert received == [Path("outra/pasta")]


def test_db_migrate_says_when_nothing_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "migrate", lambda directory: [])

    result = runner.invoke(app, ["db", "migrate"])

    assert result.exit_code == 0
    assert "Nenhuma migração pendente" in result.output


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (MigrationError("001_a.sql foi alterada"), "001_a.sql foi alterada"),
        (ConfigError("DATABASE_URL: variável obrigatória ausente"), "DATABASE_URL"),
        (OperationalError("connect", {}, Exception("recusada")), "make up"),
    ],
)
def test_db_migrate_reports_errors_with_exit_code_1(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected: str
) -> None:
    def failing_migrate(directory: Path) -> list[Migration]:
        raise error

    monkeypatch.setattr(cli, "migrate", failing_migrate)

    result = runner.invoke(app, ["db", "migrate"])

    assert result.exit_code == 1
    assert expected in result.output


# ------------------------------------------------------------------ flowstream synthetic


SEEDS_DIR = Path(__file__).resolve().parents[2] / "dbt" / "seeds"


def test_synthetic_generate_writes_csvs_and_prints_summary(tmp_path: Path) -> None:
    out = tmp_path / "sintetico"

    result = runner.invoke(
        app,
        ["synthetic", "generate", "--seed", "7", "--months", "1", "--out", str(out),
         "--seeds-dir", str(SEEDS_DIR)],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert (out / "embarques.csv").is_file()
    assert "embarques" in result.output
    assert "hash" in result.output


def test_synthetic_generate_reports_bad_config(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["synthetic", "generate", "--config", str(tmp_path / "nao_existe.yaml")]
    )

    assert result.exit_code == 1
    assert "não encontrado" in result.output


def test_synthetic_load_prints_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[Path] = []

    def fake_load(directory: Path) -> dict[str, int]:
        received.append(directory)
        return {"clientes": 300, "embarques": 1800}

    monkeypatch.setattr(cli, "load_synthetic", fake_load)

    result = runner.invoke(app, ["synthetic", "load", "--dir", "outra/pasta"])

    assert result.exit_code == 0
    assert "clientes" in result.output
    assert "1800" in result.output
    assert received == [Path("outra/pasta")]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SyntheticDataError("rode flowstream synthetic generate"), "synthetic generate"),
        (OperationalError("connect", {}, Exception("recusada")), "make up"),
    ],
)
def test_synthetic_load_reports_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected: str
) -> None:
    def failing(directory: Path) -> dict[str, int]:
        raise error

    monkeypatch.setattr(cli, "load_synthetic", failing)

    result = runner.invoke(app, ["synthetic", "load"])

    assert result.exit_code == 1
    assert expected in result.output


# ------------------------------------------------------------------ flowstream ingest ptax


def test_ingest_ptax_passes_dates_and_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[tuple[date, date, bool]] = []

    def fake_run(start: date, end: date, *, full_refresh: bool = False) -> PtaxIngestResult:
        received.append((start, end, full_refresh))
        return PtaxIngestResult(rows=750, periods={"USD": (start, end)})

    monkeypatch.setattr(cli, "run_ptax", fake_run)

    result = runner.invoke(
        app, ["ingest", "ptax", "--start", "2024-01-01", "--end", "2024-12-31", "--full-refresh"]
    )

    assert result.exit_code == 0, result.output
    assert received == [(date(2024, 1, 1), date(2024, 12, 31), True)]
    assert "750" in result.output


def test_ingest_ptax_end_defaults_to_today(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[date] = []

    def fake_run(start: date, end: date, *, full_refresh: bool = False) -> PtaxIngestResult:
        received.append(end)
        return PtaxIngestResult(rows=0)

    monkeypatch.setattr(cli, "run_ptax", fake_run)

    result = runner.invoke(app, ["ingest", "ptax", "--start", "2024-01-01"])

    assert result.exit_code == 0
    assert received == [now_sao_paulo().date()]
    assert "em dia" in result.output


def test_ingest_ptax_rejects_bad_date() -> None:
    result = runner.invoke(app, ["ingest", "ptax", "--start", "01/01/2024"])

    assert result.exit_code != 0
    assert "AAAA-MM-DD" in result.output


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PtaxUnavailableError("PTAX indisponível: HTTP 503 após 3 tentativas."), "HTTP 503"),
        (PtaxResponseError("Campo ausente"), "Campo ausente"),
        (OperationalError("connect", {}, Exception("recusada")), "make up"),
    ],
)
def test_ingest_ptax_reports_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected: str
) -> None:
    def failing(start: date, end: date, *, full_refresh: bool = False) -> PtaxIngestResult:
        raise error

    monkeypatch.setattr(cli, "run_ptax", failing)

    result = runner.invoke(app, ["ingest", "ptax"])

    assert result.exit_code == 1
    assert expected in result.output


# ------------------------------------------------------------------ flowstream ingest comexstat


def test_ingest_comexstat_passes_flags_and_prints_periods(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[tuple[bool, int]] = []

    def fake_run(*, full_refresh: bool = False, months: int = 24) -> ComexIngestResult:
        received.append((full_refresh, months))
        return ComexIngestResult(rows=290_000, periods={"export": ((2024, 10), (2026, 9))})

    monkeypatch.setattr(cli, "run_comexstat", fake_run)

    result = runner.invoke(app, ["ingest", "comexstat", "--full-refresh", "--months", "12"])

    assert result.exit_code == 0, result.output
    assert received == [(True, 12)]
    assert "2024-10" in result.output
    assert "290000" in result.output


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ComexUnavailableError("limite de requisições (HTTP 429)"), "429"),
        (ComexResponseError("não devolveu dados para 2026-09"), "2026-09"),
        (OperationalError("connect", {}, Exception("recusada")), "make up"),
    ],
)
def test_ingest_comexstat_reports_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected: str
) -> None:
    def failing(*, full_refresh: bool = False, months: int = 24) -> ComexIngestResult:
        raise error

    monkeypatch.setattr(cli, "run_comexstat", failing)

    result = runner.invoke(app, ["ingest", "comexstat"])

    assert result.exit_code == 1
    assert expected in result.output


# ------------------------------------------------------------------ flowstream quality run


def _report(ok: bool) -> QualityReport:
    summary = QualitySummary(
        testes_ok=320 if ok else 318,
        testes_aviso=1,
        testes_falha=0 if ok else 2,
        recursos_com_erro=0,
        fontes_atrasadas=0,
        fontes_com_erro=0,
        anomalias=1,
    )
    return QualityReport(summary=summary, results=[], anomalies=[])


def test_quality_run_prints_summary_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "run_quality_check", lambda: _report(ok=True))

    result = runner.invoke(app, ["quality", "run"])

    assert result.exit_code == 0, result.output
    assert "320" in result.output
    assert "anomalias de volume: 1" in result.output


def test_quality_run_fails_when_data_is_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "run_quality_check", lambda: _report(ok=False))

    result = runner.invoke(app, ["quality", "run"])

    assert result.exit_code == 1
    assert "testes falhando: 2" in result.output


def test_quality_run_reports_database_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing() -> QualityReport:
        raise OperationalError("connect", {}, Exception("recusada"))

    monkeypatch.setattr(cli, "run_quality_check", failing)

    result = runner.invoke(app, ["quality", "run"])

    assert result.exit_code == 1
    assert "make up" in result.output


# ------------------------------------------------------------------ flowstream inbox watch


def test_inbox_watch_runs_until_interrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[float, float]] = []

    def fake_watch(settings: Settings, stop: object, poll: float, interval: float) -> None:
        calls.append((poll, interval))
        raise KeyboardInterrupt  # Ctrl+C

    monkeypatch.setattr(cli, "load_settings", _fake_settings)
    monkeypatch.setattr(cli, "watch_inbox", fake_watch)

    result = runner.invoke(app, ["inbox", "watch", "--poll", "0.5", "--stable-seconds", "2"])

    assert result.exit_code == 0, result.output
    assert calls == [(0.5, 2.0)]
    assert "encerrado" in result.output


def test_inbox_watch_reports_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_settings", _raise_config_error)

    result = runner.invoke(app, ["inbox", "watch"])

    assert result.exit_code == 1
    assert "DATABASE_URL" in result.output


def test_inbox_watch_reports_invalid_webhook_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """O banco fora do ar não chega aqui (o watcher espera e tenta de novo); URL inválida sim."""

    def failing(settings: Settings, stop: object, poll: float, interval: float) -> None:
        raise ValueError("N8N_WEBHOOK_URL precisa começar com http:// ou https://")

    monkeypatch.setattr(cli, "load_settings", _fake_settings)
    monkeypatch.setattr(cli, "watch_inbox", failing)

    result = runner.invoke(app, ["inbox", "watch"])

    assert result.exit_code == 1
    assert "N8N_WEBHOOK_URL" in result.output


def _raise_config_error(*args: object, **kwargs: object) -> Settings:
    raise ConfigError("Configuração inválida:\n- DATABASE_URL: variável obrigatória ausente")


def _fake_settings(*args: object, **kwargs: object) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5433/db",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )


# ------------------------------------------------------------------ flowstream ai extract


def _fixture_pdf(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "documentos" / name


class _FakePipeline:
    def __init__(self, outcome: str = "APROVADO") -> None:
        from flowstream.ai.pipeline import ExtractionResult, Outcome
        from flowstream.ai.schemas import DocumentType

        self.paths: list[Path] = []
        self.result = ExtractionResult(Outcome(outcome), DocumentType.BL, score=1.0)

    def extract_file(self, path: Path) -> object:
        self.paths.append(path)
        return self.result


def test_ai_extract_prints_json_and_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = _FakePipeline()
    monkeypatch.setattr(cli, "load_settings", _fake_settings)
    monkeypatch.setattr(cli, "build_pipeline", lambda settings: pipeline)

    result = runner.invoke(app, ["ai", "extract", str(_fixture_pdf("bl_fs_2026_00123.pdf"))])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decisao"] == "APROVADO"
    assert payload["arquivo"] == "bl_fs_2026_00123.pdf"
    assert "decisão: APROVADO" in result.stderr


def test_ai_extract_several_files_cross_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = _FakePipeline()
    monkeypatch.setattr(cli, "load_settings", _fake_settings)
    monkeypatch.setattr(cli, "build_pipeline", lambda settings: pipeline)
    files = [_fixture_pdf("bl_fs_2026_00123.pdf"), _fixture_pdf("invoice_fs_2026_00123.pdf")]

    result = runner.invoke(app, ["ai", "extract", *map(str, files)])

    assert result.exit_code == 0, result.output
    assert [item["arquivo"] for item in json.loads(result.stdout)] == [f.name for f in files]


def test_ai_extract_error_exits_with_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_settings", _fake_settings)
    monkeypatch.setattr(cli, "build_pipeline", lambda settings: _FakePipeline("ERRO"))

    result = runner.invoke(app, ["ai", "extract", str(_fixture_pdf("bl_fs_2026_00123.pdf"))])

    assert result.exit_code == 1


def test_ai_extract_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ai", "extract", str(tmp_path / "nao_existe.pdf")])
    assert result.exit_code != 0


# ------------------------------------------------------------------ flowstream ai evaluate

EVAL_DATASET = Path(__file__).resolve().parents[1] / "eval" / "documentos"
HISTORY_DOC = (
    "# Avaliação\n<!-- historico:inicio -->\n| Data |\n| --- |\n<!-- historico:fim -->\n"
    "<!-- ultima:inicio -->\n<!-- ultima:fim -->\n"
)


def _eval_dataset(tmp_path: Path, *names: str) -> Path:
    import shutil

    dataset = tmp_path / "conjunto"
    dataset.mkdir()
    for name in names:
        for suffix in (".pdf", ".json"):
            shutil.copy(EVAL_DATASET / f"{name}{suffix}", dataset / f"{name}{suffix}")
    return dataset


class _FakeEvalPipeline:
    def __init__(self, outcome: str = "REVISAO") -> None:
        from flowstream.ai.pipeline import ExtractionResult, Outcome

        self.result = ExtractionResult(Outcome(outcome), None, duracao_ms=1200)
        self.paths: list[Path] = []

    def extract_file(self, path: Path) -> object:
        self.paths.append(path)
        return self.result


class _FakeEvalStore:
    saved: ClassVar[list[object]] = []

    def __init__(self, engine: object) -> None:
        self.engine = engine

    def save(self, report: object) -> int:
        _FakeEvalStore.saved.append(report)
        return 7


def _patch_eval(
    monkeypatch: pytest.MonkeyPatch, pipeline: _FakeEvalPipeline, calls: list[dict[str, object]]
) -> None:
    def fake_build(settings: Settings, **kwargs: object) -> _FakeEvalPipeline:
        calls.append(kwargs)
        return pipeline

    _FakeEvalStore.saved = []
    monkeypatch.setattr(cli, "load_settings", _fake_settings)
    monkeypatch.setattr(cli, "build_pipeline", fake_build)
    monkeypatch.setattr(cli, "create_db_engine", lambda settings: object())
    monkeypatch.setattr(cli, "PostgresEvaluationStore", _FakeEvalStore)


def test_ai_evaluate_prints_table_saves_and_updates_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pipeline, calls = _FakeEvalPipeline(), []
    _patch_eval(monkeypatch, pipeline, calls)
    dataset = _eval_dataset(tmp_path, "awb_01", "bl_01")
    history = tmp_path / "ia_avaliacao.md"
    history.write_text(HISTORY_DOC, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "ai",
            "evaluate",
            "--prompt-version",
            "v1",
            "--model",
            "qwen2.5:1.5b",
            "--dataset",
            str(dataset),
            "--report",
            str(history),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [{"model": "qwen2.5:1.5b", "prompt_version": "v1", "timeout": 600.0}]
    assert [p.name for p in pipeline.paths] == ["awb_01.pdf", "bl_01.pdf"]
    assert "Acurácia normalizada" in result.stdout
    assert "2/2" in result.stderr  # progresso
    assert len(_FakeEvalStore.saved) == 1
    assert "| v1 | qwen2.5:1.5b | 2 |" in history.read_text(encoding="utf-8")


def test_ai_evaluate_no_save_touches_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_eval(monkeypatch, _FakeEvalPipeline(), [])
    history = tmp_path / "ia_avaliacao.md"
    history.write_text(HISTORY_DOC, encoding="utf-8")
    dataset = _eval_dataset(tmp_path, "awb_01")

    result = runner.invoke(
        app,
        ["ai", "evaluate", "--dataset", str(dataset), "--report", str(history), "--no-save"],
    )

    assert result.exit_code == 0, result.output
    assert _FakeEvalStore.saved == []
    assert history.read_text(encoding="utf-8") == HISTORY_DOC


def test_ai_evaluate_unknown_prompt_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "load_settings", _fake_settings)
    dataset = _eval_dataset(tmp_path, "awb_01")

    result = runner.invoke(
        app, ["ai", "evaluate", "--prompt-version", "v99", "--dataset", str(dataset)]
    )

    assert result.exit_code == 1
    assert "awb_v99.md" in result.output


def test_ai_evaluate_all_errors_is_not_saved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_eval(monkeypatch, _FakeEvalPipeline("ERRO"), [])
    dataset = _eval_dataset(tmp_path, "awb_01")

    result = runner.invoke(app, ["ai", "evaluate", "--dataset", str(dataset)])

    assert result.exit_code == 1
    assert "Ollama" in result.output
    assert _FakeEvalStore.saved == []


def test_ai_evaluate_approved_trap_exits_with_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_eval(monkeypatch, _FakeEvalPipeline("APROVADO"), [])
    dataset = _eval_dataset(tmp_path, "bl_09")  # tentativa de injeção

    result = runner.invoke(app, ["ai", "evaluate", "--dataset", str(dataset), "--no-save"])

    assert result.exit_code == 1
    assert "armadilha" in result.output


def test_ai_evaluate_database_unreachable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Down(_FakeEvalStore):
        def save(self, report: object) -> int:
            raise OperationalError("insert", {}, Exception("conexão recusada"))

    _patch_eval(monkeypatch, _FakeEvalPipeline(), [])
    monkeypatch.setattr(cli, "PostgresEvaluationStore", _Down)
    dataset = _eval_dataset(tmp_path, "awb_01")

    result = runner.invoke(app, ["ai", "evaluate", "--dataset", str(dataset)])

    assert result.exit_code == 1
    assert "make up" in result.output
    assert "--no-save" in result.output


def test_ai_evaluate_missing_dataset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "load_settings", _fake_settings)
    result = runner.invoke(app, ["ai", "evaluate", "--dataset", str(tmp_path / "nada")])
    assert result.exit_code == 1
    assert "não existe" in result.output


def test_ai_evaluate_with_technical_errors_is_not_saved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ollama caindo no meio (ou OCR ausente) não pode virar uma linha do histórico."""
    from flowstream.ai.pipeline import ExtractionResult, Outcome

    class _HalfDown(_FakeEvalPipeline):
        def extract_file(self, path: Path) -> object:
            self.paths.append(path)
            if path.name == "bl_01.pdf":
                return ExtractionResult(Outcome.ERRO, None, erro="Ollama indisponível")
            return self.result

    _patch_eval(monkeypatch, _HalfDown(), [])
    history = tmp_path / "ia_avaliacao.md"
    history.write_text(HISTORY_DOC, encoding="utf-8")
    dataset = _eval_dataset(tmp_path, "awb_01", "bl_01")

    result = runner.invoke(
        app, ["ai", "evaluate", "--dataset", str(dataset), "--report", str(history)]
    )

    assert result.exit_code == 1
    assert "Acurácia normalizada" in result.stdout  # a tabela sai mesmo assim
    assert "1 documento(s) em ERRO" in result.output
    assert _FakeEvalStore.saved == []
    assert history.read_text(encoding="utf-8") == HISTORY_DOC


def test_ai_evaluate_timeout_option(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    _patch_eval(monkeypatch, _FakeEvalPipeline(), calls)
    dataset = _eval_dataset(tmp_path, "awb_01")

    result = runner.invoke(
        app, ["ai", "evaluate", "--dataset", str(dataset), "--timeout", "90", "--no-save"]
    )

    assert result.exit_code == 0, result.output
    assert calls[0]["timeout"] == 90.0

"""Leitura do conjunto de avaliação e gravação do histórico em arquivo (tmp_path, sem banco)."""

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from flowstream.ai.adapters import (
    DatasetError,
    dataset_digest,
    load_ground_truths,
    update_history_file,
)
from flowstream.ai.evaluation import evaluate_case, summarize
from flowstream.ai.pipeline import ExtractionResult, Outcome
from flowstream.domain.dates import SAO_PAULO

DATASET = Path(__file__).resolve().parents[2] / "eval" / "documentos"


def _copy(tmp_path: Path, *names: str) -> Path:
    for name in names:
        for suffix in (".json", ".pdf"):
            shutil.copy(DATASET / f"{name}{suffix}", tmp_path / f"{name}{suffix}")
    return tmp_path


def test_load_ground_truths_pairs_pdf_and_json_sorted(tmp_path: Path) -> None:
    cases = load_ground_truths(_copy(tmp_path, "invoice_01", "awb_01"))
    assert [path.name for path, _ in cases] == ["awb_01.pdf", "invoice_01.pdf"]
    assert cases[0][1].arquivo == "awb_01.pdf"


def test_missing_directory_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="não existe"):
        load_ground_truths(tmp_path / "nada")


def test_empty_directory_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="nenhum gabarito"):
        load_ground_truths(tmp_path)


def test_missing_pdf_is_a_clear_error(tmp_path: Path) -> None:
    _copy(tmp_path, "awb_01")
    (tmp_path / "awb_01.pdf").unlink()
    with pytest.raises(DatasetError, match=r"awb_01\.pdf"):
        load_ground_truths(tmp_path)


def test_invalid_ground_truth_names_the_file(tmp_path: Path) -> None:
    (tmp_path / "bl_99.json").write_text('{"arquivo": "bl_99.pdf"}', encoding="utf-8")
    with pytest.raises(DatasetError, match=r"bl_99\.json"):
        load_ground_truths(tmp_path)


def test_ground_truth_must_point_to_its_own_pdf(tmp_path: Path) -> None:
    _copy(tmp_path, "awb_01")
    data = json.loads((tmp_path / "awb_01.json").read_text(encoding="utf-8"))
    data["arquivo"] = "awb_02.pdf"
    (tmp_path / "awb_01.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DatasetError, match=r"awb_02\.pdf"):
        load_ground_truths(tmp_path)


def test_digest_changes_when_a_pdf_changes(tmp_path: Path) -> None:
    cases = load_ground_truths(_copy(tmp_path, "awb_01"))
    before = dataset_digest(cases)
    assert before == dataset_digest(cases)
    assert len(before) == 64
    (tmp_path / "awb_01.pdf").write_bytes(b"%PDF-outro")
    assert dataset_digest(cases) != before


def test_update_history_file_keeps_previous_rows(tmp_path: Path) -> None:
    doc = tmp_path / "ia_avaliacao.md"
    doc.write_text(
        "<!-- historico:inicio -->\n| Data |\n| --- |\n| antiga |\n<!-- historico:fim -->\n"
        "<!-- ultima:inicio -->\n<!-- ultima:fim -->\n",
        encoding="utf-8",
    )
    dataset = tmp_path / "conjunto"
    dataset.mkdir()
    path, truth = load_ground_truths(_copy(dataset, "awb_01"))[0]
    result = ExtractionResult(Outcome.ERRO, None, erro="Ollama fora")
    report = summarize(
        [evaluate_case(truth, result)],
        prompt_versao="v1",
        modelo="fake",
        conjunto_sha256="b" * 64,
        when=datetime(2026, 11, 5, 9, 0, tzinfo=SAO_PAULO),
    )
    update_history_file(doc, report)
    text = doc.read_text(encoding="utf-8")
    assert "| antiga |" in text
    assert "| 2026-11-05 09:00 | v1 | fake |" in text
    assert "\r\n" not in doc.read_bytes().decode("utf-8")
    assert path.exists()

"""Conjunto de avaliação (tests/eval): composição, reprodutibilidade e gabarito coerente.

O teste central é o do extrator perfeito: o pipeline REAL (PDF -> texto -> classificador ->
validadores -> score) roda em cada um dos 40 PDFs com um FakeLLM que responde exatamente o
gabarito. Ele precisa acertar 100% e chegar à decisão esperada; se não chegar, o gabarito
(ou o PDF) está errado, e a avaliação do modelo real mediria o gabarito, não o modelo.
"""

import importlib.util
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from PIL import Image

from flowstream.ai.adapters import load_ground_truths
from flowstream.ai.evaluation import GroundTruth, evaluate_case
from flowstream.ai.llm import FakeLLM
from flowstream.ai.pipeline import ExtractionPipeline, Outcome
from flowstream.ai.schemas import DocumentType

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
DATASET = EVAL_DIR / "documentos"
TODAY = date(2026, 11, 5)
CASES = load_ground_truths(DATASET)


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_generate", EVAL_DIR / "generate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses do módulo precisam dele registrado
    spec.loader.exec_module(module)
    return module


def _oracle_answer(truth: GroundTruth) -> str:
    """O JSON que um extrator perfeito devolveria: valor do gabarito + evidence literal."""
    return json.dumps(_zip(truth.campos, truth.evidencias), ensure_ascii=False)


def _zip(values: Any, evidences: Any) -> Any:
    if isinstance(values, dict):
        return {name: _zip(values[name], evidences[name]) for name in values}
    if isinstance(values, list):
        return [_zip(v, e) for v, e in zip(values, evidences, strict=True)]
    return {"valor": values, "evidence": evidences}


# ------------------------------------------------------------------ composição


def test_dataset_has_forty_documents_ten_of_each_type() -> None:
    assert len(CASES) == 40
    assert Counter(truth.tipo for _, truth in CASES) == dict.fromkeys(DocumentType, 10)


def test_dataset_has_scanned_planted_errors_and_injections() -> None:
    truths = [truth for _, truth in CASES]
    assert sum(t.escaneado for t in truths) == 5
    assert sum(t.erro_proposital is not None for t in truths) == 5
    assert sum(t.injecao for t in truths) == 3
    assert all(not (t.escaneado and t.armadilha) for t in truths)  # uma dificuldade por vez


def test_every_type_has_three_layouts() -> None:
    layouts: dict[DocumentType, set[str]] = {}
    for _, truth in CASES:
        layouts.setdefault(truth.tipo, set()).add(truth.layout)
    assert all(len(found) == 3 for found in layouts.values())


def test_planted_errors_cover_container_awb_and_weights() -> None:
    errors = " | ".join(t.erro_proposital or "" for _, t in CASES)
    for expected in ("contêiner", "AWB", "peso bruto total", "peso líquido", "total da invoice"):
        assert expected in errors


def test_generator_is_reproducible(tmp_path: Path) -> None:
    """Gerar de novo produz os mesmos bytes: o conjunto versionado é o que o código gera."""
    _generator().build_all(tmp_path)
    for path, _truth in CASES:
        assert (tmp_path / path.name).read_bytes() == path.read_bytes(), path.name
        json_name = path.with_suffix(".json").name
        assert (tmp_path / json_name).read_bytes() == (DATASET / json_name).read_bytes()


# ------------------------------------------------------------------ extrator perfeito


@pytest.mark.parametrize(("path", "truth"), CASES, ids=[t.arquivo for _, t in CASES])
def test_perfect_extractor_scores_100_and_reaches_the_expected_decision(
    path: Path, truth: GroundTruth
) -> None:
    fake = FakeLLM([_oracle_answer(truth)])

    def ocr(_image: Image.Image) -> str:  # sem Tesseract: o OCR "lê" o texto do gabarito
        return truth.texto

    pipeline = ExtractionPipeline(llm=fake, ocr=ocr, today=lambda: TODAY)
    result = pipeline.extract_file(path)

    assert len(fake.calls) == 1, "o tipo precisa sair pelas regras, sem perguntar ao LLM"
    assert result.tipo is truth.tipo
    assert result.paginas_ocr == (1 if truth.escaneado else 0)
    assert result.outcome.value == truth.decisao_esperada, [
        d.to_dict() for d in result.divergencias if d.gravidade.value == "CRITICA"
    ]
    if truth.decisao_esperada == "APROVADO":
        assert result.score == 1.0
    case = evaluate_case(truth, result)
    assert all(c.exato for c in case.campos), [c for c in case.campos if not c.exato]
    assert not any(c.alucinado for c in case.campos)


def test_traps_are_caught_for_the_right_reason() -> None:
    """Erro plantado vira divergência da regra esperada; injeção vira texto suspeito."""
    for path, truth in CASES:
        if not truth.armadilha:
            continue
        pipeline = ExtractionPipeline(
            llm=FakeLLM([_oracle_answer(truth)]), ocr=None, today=lambda: TODAY
        )
        result = pipeline.extract_file(path)
        rules = {d.regra.value for d in result.divergencias if d.gravidade.value == "CRITICA"}
        expected = "SUSPEITO" if truth.injecao else str(truth.regra_esperada)
        assert expected in rules, (truth.arquivo, rules)
        assert result.outcome is Outcome.REVISAO

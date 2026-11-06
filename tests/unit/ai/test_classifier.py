"""Classificação por regras; o LLM só desempata."""

from types import ModuleType

import pytest

from flowstream.ai.classifier import MAX_CLASSIFY_CHARS, ClassificationMethod, classify
from flowstream.ai.llm import FakeLLM, LLMError
from flowstream.ai.schemas import DocumentType


@pytest.mark.parametrize(
    ("lines_attr", "expected"),
    [
        ("BL_LINES", DocumentType.BL),
        ("AWB_LINES", DocumentType.AWB),
        ("INVOICE_LINES", DocumentType.INVOICE),
        ("PACKING_LINES", DocumentType.PACKING_LIST),
        ("INJECTION_LINES", DocumentType.INVOICE),
    ],
)
def test_rules_classify_the_fixtures(catalog: ModuleType, lines_attr: str, expected: str) -> None:
    fake = FakeLLM([])  # se o LLM fosse chamado, levantaria erro
    result = classify("\n".join(getattr(catalog, lines_attr)), llm=fake)
    assert result.tipo is DocumentType(expected)
    assert result.method is ClassificationMethod.REGRAS
    assert fake.calls == []


def test_portuguese_titles_are_recognized() -> None:
    assert classify("CONHECIMENTO DE EMBARQUE\nPorto de embarque: CNSHA").tipo is DocumentType.BL
    assert classify("ROMANEIO DE CARGA\nPeso líquido: 10 kg").tipo is DocumentType.PACKING_LIST
    assert classify("FATURA COMERCIAL\nIncoterm: FOB").tipo is DocumentType.INVOICE
    assert classify("CONHECIMENTO AÉREO\nAeroporto de origem: GRU").tipo is DocumentType.AWB


def test_tie_asks_the_llm() -> None:
    fake = FakeLLM(['{"tipo": "PACKING_LIST"}'])
    result = classify("Gross weight: 100 kg\nNet weight: 90 kg\nUnit price: 1.00", llm=fake)
    assert result.tipo is DocumentType.PACKING_LIST
    assert result.method is ClassificationMethod.LLM
    assert "<documento>" in fake.calls[0].prompt


def test_llm_answer_outside_the_enum_is_ignored() -> None:
    fake = FakeLLM(['{"tipo": "APROVADO"}'])
    result = classify("texto qualquer sem pistas", llm=fake)
    assert result.tipo is None
    assert result.method is ClassificationMethod.NENHUM


def test_without_llm_a_tie_stays_unclassified() -> None:
    result = classify("texto qualquer sem pistas", llm=None)
    assert result.tipo is None
    assert result.method is ClassificationMethod.NENHUM


def test_llm_failure_leaves_it_unclassified() -> None:
    result = classify("texto qualquer sem pistas", llm=FakeLLM(["isto não é json"]))
    assert result.tipo is None


def test_llm_down_on_a_tie_is_raised() -> None:
    """Revisão P10 M5: Ollama fora é falha técnica (ERRO), não "tipo não identificado"."""
    with pytest.raises(LLMError):
        classify("texto qualquer sem pistas", llm=FakeLLM([]))


def test_only_the_start_of_the_text_goes_to_the_llm() -> None:
    """Auditoria P10 M1: o desempate não pode estourar o contexto do modelo."""
    fake = FakeLLM(['{"tipo": "BL"}'])
    classify("sem pistas " + "x" * (MAX_CLASSIFY_CHARS * 3), llm=fake)
    assert len(fake.calls[0].prompt) < MAX_CLASSIFY_CHARS + 500

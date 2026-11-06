"""Schemas da extração: estrutura rígida, evidence obrigatória, sem float, classes de campo."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from flowstream.ai.schemas import (
    DOCUMENT_MODELS,
    AirWaybill,
    BillOfLading,
    CommercialInvoice,
    DocumentType,
    Extracted,
    FieldClass,
    PackingList,
    empty_template,
    field_class,
    parse_llm_json,
)


def _f(valor: Any, evidence: str | None = "trecho") -> dict[str, Any]:
    return {"valor": valor, "evidence": evidence if valor is not None else None}


def _null() -> dict[str, None]:
    return {"valor": None, "evidence": None}


def bl_payload() -> dict[str, Any]:
    return {
        "numero_bl": _f("MAEU240012345"),
        "embarcador": _f("Shanghai Export Co."),
        "consignatario": _f("Importadora Exemplo Ltda"),
        "notificar": _null(),
        "porto_carregamento": _f("CNSHA"),
        "porto_descarga": _f("BRITJ"),
        "navio": _f("MSC AURORA"),
        "viagem": _f("412W"),
        "data_embarque": _f("2026-09-14"),
        "conteineres": [
            {
                "numero": _f("MSKU1234565"),
                "lacre": _f("SL998877"),
                "tipo": _f("40HC"),
                "volumes": _f("120"),
                "peso_bruto_kg": _f("18500.50"),
            }
        ],
        "volumes_total": _f("120"),
        "peso_bruto_total_kg": _f("18500.50"),
        "cubagem_m3": _null(),
        "descricao_mercadoria": _f("Peças de máquinas"),
        "ncm": [_f("84314990")],
        "frete": _f("PREPAID"),
    }


# ------------------------------------------------------------------ Extracted


def test_extracted_accepts_value_with_evidence() -> None:
    field = Extracted[Decimal].model_validate({"valor": "10.50", "evidence": "USD 10.50"})
    assert field.valor == Decimal("10.50")


def test_extracted_null_is_absent() -> None:
    field = Extracted[str].model_validate(_null())
    assert field.valor is None
    assert field.is_absent


def test_value_without_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        Extracted[str].model_validate({"valor": "MSKU1234565", "evidence": None})


def test_blank_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        Extracted[str].model_validate({"valor": "MSKU1234565", "evidence": "   "})


def test_float_value_is_rejected() -> None:
    """Valor monetário nunca passa por float (CLAUDE.md)."""
    with pytest.raises(ValidationError, match="float"):
        Extracted[Decimal].model_validate({"valor": 10.5, "evidence": "10.5"})


def test_extra_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Extracted[str].model_validate({"valor": "x", "evidence": "x", "confianca": 0.99})


def test_text_value_has_a_length_limit() -> None:
    """Auditoria P10 A2: valor de texto livre não pode carregar um parágrafo inventado."""
    with pytest.raises(ValidationError, match="300"):
        Extracted[str].model_validate({"valor": "x" * 301, "evidence": "x"})


def test_evidence_has_a_length_limit() -> None:
    with pytest.raises(ValidationError):
        Extracted[str].model_validate({"valor": "x", "evidence": "x" * 501})


# ------------------------------------------------------------------ documentos


def test_bill_of_lading_parses_a_complete_payload() -> None:
    bl = BillOfLading.model_validate(bl_payload())
    assert bl.data_embarque.valor == date(2026, 9, 14)
    assert bl.conteineres[0].peso_bruto_kg.valor == Decimal("18500.50")
    assert bl.volumes_total.valor == 120


def test_missing_key_is_a_structure_error() -> None:
    payload = bl_payload()
    del payload["navio"]
    with pytest.raises(ValidationError, match="navio"):
        BillOfLading.model_validate(payload)


def test_identifiers_are_text_in_the_schema() -> None:
    """Formato é checado nos validadores: o retry nunca pede ao modelo para "corrigir" um dígito."""
    payload = bl_payload()
    payload["conteineres"][0]["numero"] = _f("MSKU1234560")  # dígito verificador errado
    bl = BillOfLading.model_validate(payload)
    assert bl.conteineres[0].numero.valor == "MSKU1234560"


def test_every_document_type_has_a_model() -> None:
    assert set(DOCUMENT_MODELS) == set(DocumentType)
    assert DOCUMENT_MODELS[DocumentType.AWB] is AirWaybill
    assert DOCUMENT_MODELS[DocumentType.INVOICE] is CommercialInvoice
    assert DOCUMENT_MODELS[DocumentType.PACKING_LIST] is PackingList


@pytest.mark.parametrize(
    ("model", "field", "expected"),
    [
        (BillOfLading, "numero_bl", FieldClass.CRITICO),
        (BillOfLading, "navio", FieldClass.OBRIGATORIO),
        (BillOfLading, "notificar", FieldClass.OPCIONAL),
        (BillOfLading, "conteineres", FieldClass.CRITICO),
        (AirWaybill, "numero_awb", FieldClass.CRITICO),
        (CommercialInvoice, "importador_cnpj", FieldClass.CRITICO),
        (CommercialInvoice, "valor_total", FieldClass.CRITICO),
        (PackingList, "numero_invoice", FieldClass.CRITICO),
        (PackingList, "peso_liquido_total_kg", FieldClass.OBRIGATORIO),
    ],
)
def test_field_classes(model: type, field: str, expected: FieldClass) -> None:
    assert field_class(model, field) is expected


@pytest.mark.parametrize("doc_type", list(DocumentType))
def test_every_field_has_a_class_and_a_description(doc_type: DocumentType) -> None:
    model = DOCUMENT_MODELS[doc_type]
    for name, info in model.model_fields.items():
        assert field_class(model, name) in FieldClass
        assert info.description, f"{model.__name__}.{name} sem descrição"


@pytest.mark.parametrize("doc_type", list(DocumentType))
def test_empty_template_is_a_valid_all_null_document(doc_type: DocumentType) -> None:
    """O modelo do prompt é gerado do schema: os dois nunca divergem."""
    model = DOCUMENT_MODELS[doc_type]
    template = empty_template(model)
    parsed = model.model_validate(template)
    assert set(template) == set(model.model_fields)
    assert parsed.model_dump()  # valida sem erro


# ------------------------------------------------------------------ JSON do LLM


def test_parse_llm_json_reads_numbers_as_decimal() -> None:
    data = parse_llm_json('{"valor": 18500.50, "evidence": "18.500,50"}')
    assert data["valor"] == Decimal("18500.50")


def test_parse_llm_json_accepts_a_fenced_block() -> None:
    assert parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}


@pytest.mark.parametrize("raw", ["", "não é json", "[1, 2]", '{"a": 1', "null"])
def test_parse_llm_json_rejects_non_objects(raw: str) -> None:
    with pytest.raises(ValueError, match="JSON"):
        parse_llm_json(raw)


def test_parse_llm_json_keeps_decimals_through_the_model() -> None:
    raw = json.dumps(bl_payload()).replace('"18500.50"', "18500.50")
    bl = BillOfLading.model_validate(parse_llm_json(raw))
    assert bl.peso_bruto_total_kg.valor == Decimal("18500.50")


def test_nul_characters_are_removed() -> None:
    """Auditoria P10 M3: o JSONB do Postgres recusa NUL e o documento ficaria preso."""
    nul = chr(0)
    field = Extracted[str].model_validate(
        {"valor": f"MSC{nul} AURORA", "evidence": f"Vessel:{nul} MSC AURORA"}
    )
    assert nul not in (field.valor or "") + (field.evidence or "")

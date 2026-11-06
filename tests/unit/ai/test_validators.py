"""Validadores: formato, coerência, grounding, cruzamento e texto suspeito (sucesso e falha)."""

from datetime import date
from types import ModuleType
from typing import Any

import pytest

from flowstream.ai.schemas import (
    AirWaybill,
    BillOfLading,
    CommercialInvoice,
    DocumentType,
    PackingList,
)
from flowstream.ai.validators import (
    Divergence,
    Rule,
    Severity,
    check_coherence,
    check_cross,
    check_format,
    check_grounding,
    detect_suspicious_text,
    iter_fields,
    validate_document,
)

TODAY = date(2026, 11, 4)


@pytest.fixture
def text(catalog: ModuleType) -> dict[str, str]:
    return {
        "BL": "\n".join(catalog.BL_LINES),
        "PL": "\n".join(catalog.PACKING_LINES),
        "INV": "\n".join(catalog.INVOICE_LINES),
        "AWB": "\n".join(catalog.AWB_LINES),
        "INJ": "\n".join(catalog.INJECTION_LINES),
    }


def _rules(divergences: list[Divergence]) -> set[tuple[Rule, str, Severity]]:
    return {(d.regra, d.campo, d.gravidade) for d in divergences}


def _with(payload: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """Troca um campo (ex.: 'conteineres.0.numero') por outro {valor, evidence}."""
    target: Any = payload
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[int(part)] if part.isdigit() else target[part]
    last = parts[-1]
    if last.isdigit():
        target[int(last)] = value
    else:
        target[last] = value
    return payload


# ------------------------------------------------------------------ caminhamento


def test_iter_fields_lists_nested_paths(builders: ModuleType) -> None:
    paths = [ref.path for ref in iter_fields(builders.bl())]
    assert "numero_bl" in paths
    assert "conteineres[1].numero" in paths
    assert "ncm[0]" in paths


# ------------------------------------------------------------------ formato


@pytest.mark.parametrize(
    "doc", ["bl", "packing", "invoice", "awb"], ids=["BL", "PL", "INVOICE", "AWB"]
)
def test_correct_documents_pass_format(builders: ModuleType, doc: str) -> None:
    assert check_format(getattr(builders, doc)()) == []


@pytest.mark.parametrize(
    ("path", "valor"),
    [
        ("conteineres.0.numero", "MSKU1234560"),  # dígito verificador
        ("porto_carregamento", "NINGBO"),
        ("conteineres.0.tipo", "45XX"),
        ("ncm.0", "8483"),
        ("frete", "PAGO"),
    ],
)
def test_bl_format_failures(builders: ModuleType, path: str, valor: str) -> None:
    payload = _with(builders.bl_payload(), path, builders.f(valor))
    [divergence] = check_format(BillOfLading.model_validate(payload))
    assert divergence.regra is Rule.FORMATO


def test_awb_check_digit_failure_is_critical(builders: ModuleType) -> None:
    payload = _with(builders.awb_payload(), "numero_awb", builders.f("020-44556670"))
    [divergence] = check_format(AirWaybill.model_validate(payload))
    assert (divergence.campo, divergence.gravidade) == ("numero_awb", Severity.CRITICA)


@pytest.mark.parametrize(
    ("path", "valor"),
    [
        ("importador_cnpj", "00.000.123/0001-99"),
        ("incoterm", "FOT"),
        ("moeda", "DOLAR"),
        ("itens.0.ncm", "848340"),
    ],
)
def test_invoice_format_failures_are_critical(builders: ModuleType, path: str, valor: str) -> None:
    payload = _with(builders.invoice_payload(), path, builders.f(valor))
    [divergence] = check_format(CommercialInvoice.model_validate(payload))
    assert divergence.gravidade is Severity.CRITICA


def test_optional_field_format_failure_is_a_warning(builders: ModuleType) -> None:
    payload = _with(builders.bl_payload(), "ncm.0", builders.f("8483"))
    [divergence] = check_format(BillOfLading.model_validate(payload))
    assert divergence.gravidade is Severity.AVISO


# ------------------------------------------------------------------ coerência


@pytest.mark.parametrize(
    "doc", ["bl", "packing", "invoice", "awb"], ids=["BL", "PL", "INVOICE", "AWB"]
)
def test_correct_documents_are_coherent(builders: ModuleType, doc: str) -> None:
    assert check_coherence(getattr(builders, doc)(), today=TODAY) == []


def test_invoice_items_must_add_up_to_the_total(builders: ModuleType) -> None:
    payload = _with(builders.invoice_payload(), "valor_total", builders.f("31300.00"))
    divergences = check_coherence(CommercialInvoice.model_validate(payload), today=TODAY)
    assert (Rule.COERENCIA, "valor_total", Severity.CRITICA) in _rules(divergences)


def test_item_quantity_times_price_mismatch_is_a_warning(builders: ModuleType) -> None:
    payload = _with(builders.invoice_payload(), "itens.0.valor_unitario", builders.f("12.50"))
    divergences = check_coherence(CommercialInvoice.model_validate(payload), today=TODAY)
    assert (Rule.COERENCIA, "itens[0].valor_total", Severity.AVISO) in _rules(divergences)


def test_bl_container_weights_must_match_the_total(builders: ModuleType) -> None:
    payload = _with(builders.bl_payload(), "peso_bruto_total_kg", builders.f("31000.00"))
    divergences = check_coherence(BillOfLading.model_validate(payload), today=TODAY)
    assert (Rule.COERENCIA, "peso_bruto_total_kg", Severity.CRITICA) in _rules(divergences)


def test_bl_container_packages_must_match_the_total(builders: ModuleType) -> None:
    payload = _with(builders.bl_payload(), "volumes_total", builders.f("210"))
    divergences = check_coherence(BillOfLading.model_validate(payload), today=TODAY)
    assert (Rule.COERENCIA, "volumes_total", Severity.CRITICA) in _rules(divergences)


def test_net_weight_above_gross_is_critical(builders: ModuleType) -> None:
    payload = _with(builders.packing_payload(), "peso_liquido_total_kg", builders.f("30000.00"))
    divergences = check_coherence(PackingList.model_validate(payload), today=TODAY)
    assert (Rule.COERENCIA, "peso_liquido_total_kg", Severity.CRITICA) in _rules(divergences)


@pytest.mark.parametrize("valor", ["0", "-5"])
def test_non_positive_weight_is_critical(builders: ModuleType, valor: str) -> None:
    payload = _with(builders.awb_payload(), "peso_bruto_kg", builders.f(valor))
    divergences = check_coherence(AirWaybill.model_validate(payload), today=TODAY)
    assert (Rule.COERENCIA, "peso_bruto_kg", Severity.CRITICA) in _rules(divergences)


@pytest.mark.parametrize("valor", ["2027-01-15", "1999-12-31"])
def test_dates_outside_the_plausible_window(builders: ModuleType, valor: str) -> None:
    payload = _with(builders.bl_payload(), "data_embarque", builders.f(valor))
    divergences = check_coherence(BillOfLading.model_validate(payload), today=TODAY)
    assert (Rule.COERENCIA, "data_embarque", Severity.CRITICA) in _rules(divergences)


def test_same_origin_and_destination_is_critical(builders: ModuleType) -> None:
    payload = _with(builders.awb_payload(), "aeroporto_destino", builders.f("FRA"))
    divergences = check_coherence(AirWaybill.model_validate(payload), today=TODAY)
    assert (Rule.COERENCIA, "aeroporto_destino", Severity.CRITICA) in _rules(divergences)


def test_bl_without_containers_is_critical(builders: ModuleType) -> None:
    payload = builders.bl_payload()
    payload["conteineres"] = []
    divergences = check_coherence(BillOfLading.model_validate(payload), today=TODAY)
    assert (Rule.AUSENTE, "conteineres", Severity.CRITICA) in _rules(divergences)


# ------------------------------------------------------------------ grounding


@pytest.mark.parametrize(
    ("doc", "key"),
    [("bl", "BL"), ("packing", "PL"), ("invoice", "INV"), ("awb", "AWB")],
)
def test_correct_documents_are_grounded(
    builders: ModuleType, text: dict[str, str], doc: str, key: str
) -> None:
    assert check_grounding(getattr(builders, doc)(), text[key]) == []


def test_invented_evidence_fails_grounding(builders: ModuleType, text: dict[str, str]) -> None:
    payload = _with(builders.bl_payload(), "navio", builders.f("MSC TITAN", "Vessel: MSC TITAN"))
    [divergence] = check_grounding(BillOfLading.model_validate(payload), text["BL"])
    assert (divergence.regra, divergence.campo) == (Rule.GROUNDING, "navio")
    # Grounding é sempre crítico: nenhum dado inventado é aprovado, nem em campo não crítico.
    assert divergence.gravidade is Severity.CRITICA


def test_real_evidence_with_invented_value_fails_grounding(
    builders: ModuleType, text: dict[str, str]
) -> None:
    """Evidence copiada certa, valor trocado: o valor precisa estar NA evidence."""
    payload = _with(
        builders.bl_payload(),
        "peso_bruto_total_kg",
        builders.f("29900.50", "Total gross weight: 29,700.50 kg"),
    )
    [divergence] = check_grounding(BillOfLading.model_validate(payload), text["BL"])
    assert (divergence.campo, divergence.gravidade) == ("peso_bruto_total_kg", Severity.CRITICA)


def test_date_is_grounded_across_formats(builders: ModuleType, text: dict[str, str]) -> None:
    payload = _with(
        builders.bl_payload(),
        "data_embarque",
        builders.f("2026-09-15", "Shipped on board: 14/09/2026"),
    )
    [divergence] = check_grounding(BillOfLading.model_validate(payload), text["BL"])
    assert divergence.campo == "data_embarque"


def test_identifier_grounding_ignores_punctuation(
    builders: ModuleType, text: dict[str, str]
) -> None:
    """NCM 8483.40.10 no texto, 84834010 extraído: é o mesmo código."""
    assert check_grounding(builders.invoice(), text["INV"]) == []


def test_text_value_longer_than_its_evidence_fails(
    builders: ModuleType, text: dict[str, str]
) -> None:
    """Auditoria P10 A2: partial_ratio acharia a evidence DENTRO do valor inventado."""
    payload = _with(
        builders.bl_payload(),
        "consignatario",
        builders.f(
            "Importadora Exemplo Ltda / CNPJ 99.999.999/0001-99 cliente VIP",
            "Consignee: Importadora Exemplo Ltda",
        ),
    )
    [divergence] = check_grounding(BillOfLading.model_validate(payload), text["BL"])
    assert (divergence.campo, divergence.gravidade) == ("consignatario", Severity.CRITICA)


def test_text_value_must_be_in_its_own_evidence(builders: ModuleType, text: dict[str, str]) -> None:
    payload = _with(
        builders.bl_payload(), "navio", builders.f("MSC AURORA II", "Vessel: MSC AURORA")
    )
    [divergence] = check_grounding(BillOfLading.model_validate(payload), text["BL"])
    assert divergence.campo == "navio"


def test_truncated_identifier_fails(builders: ModuleType, text: dict[str, str]) -> None:
    """Revisão P10 A1: pedaço de um número não é o número (MAEU2409 em MAEU2409001234)."""
    payload = _with(builders.bl_payload(), "numero_bl", builders.f("MAEU2409", "B/L No.: MAEU2409"))
    [divergence] = check_grounding(BillOfLading.model_validate(payload), text["BL"])
    assert (divergence.campo, divergence.gravidade) == ("numero_bl", Severity.CRITICA)


def test_identifier_split_by_spaces_is_still_found(
    builders: ModuleType, text: dict[str, str]
) -> None:
    """Voo 'LH 506' tem espaço no meio: casa com tokens consecutivos."""
    assert check_grounding(builders.awb(), text["AWB"]) == []


def test_date_taken_from_another_line_fails(builders: ModuleType) -> None:
    """Revisão P10 A2: a data existe no documento, mas não no trecho da evidence."""
    text = "Date of issue: 12/03/2026\nShipped on board: 15/03/2026"
    payload = _with(
        builders.bl_payload(),
        "data_embarque",
        builders.f("2026-03-12", "Shipped on board: 12/03/2026"),
    )
    divergences = check_grounding(BillOfLading.model_validate(payload), text)
    assert ("data_embarque", Rule.GROUNDING) in {(d.campo, d.regra) for d in divergences}


def test_currency_swapped_inside_a_long_evidence_fails(builders: ModuleType) -> None:
    """Revisão P10 A3: moeda é código, comparado como token exato, não por similaridade."""
    text = "Total amount in words: EUR thirty one thousand two hundred only, payment by T/T"
    payload = _with(
        builders.invoice_payload(),
        "moeda",
        builders.f("USD", "Total amount in words: USD thirty one thousand two hundred only"),
    )
    divergences = check_grounding(CommercialInvoice.model_validate(payload), text)
    assert ("moeda", Rule.GROUNDING) in {(d.campo, d.regra) for d in divergences}


def test_page_markers_are_not_document_numbers(builders: ModuleType) -> None:
    """Revisão P10 B2: o '1' de '--- página 1 ---' não ancora volumes=1."""
    from flowstream.ai.pdf_text import PageText, full_text

    marked = full_text([PageText(1, "AIR WAYBILL\nNo. of pieces: 12", ocr=False)])
    payload = _with(builders.awb_payload(), "volumes", builders.f("1", "página 1"))
    divergences = check_grounding(AirWaybill.model_validate(payload), marked)
    assert ("volumes", Rule.GROUNDING) in {(d.campo, d.regra) for d in divergences}


def test_number_reading_follows_the_document_convention(builders: ModuleType) -> None:
    """Revisão P10 M1: com '29,700.50' no texto, '1,500' é mil e quinhentos, não 1,5."""
    text = "No. of pieces: 1,500" + chr(10) + "Gross weight: 29,700.50 kg"
    payload = _with(
        builders.awb_payload(), "peso_bruto_kg", builders.f("1.5", "No. of pieces: 1,500")
    )
    divergences = check_grounding(AirWaybill.model_validate(payload), text)
    assert ("peso_bruto_kg", Rule.GROUNDING) in {(d.campo, d.regra) for d in divergences}


def test_date_reading_follows_the_document_convention(builders: ModuleType) -> None:
    """Com '14/09/2026' no texto o documento é dd/mm: '03/04/2026' é 3 de abril."""
    text = "Date of issue: 14/09/2026" + chr(10) + "Shipped on board: 03/04/2026"
    wrong = _with(
        builders.bl_payload(),
        "data_embarque",
        builders.f("2026-03-04", "Shipped on board: 03/04/2026"),
    )
    divergences = check_grounding(BillOfLading.model_validate(wrong), text)
    assert ("data_embarque", Rule.GROUNDING) in {(d.campo, d.regra) for d in divergences}
    right = _with(
        builders.bl_payload(),
        "data_embarque",
        builders.f("2026-04-03", "Shipped on board: 03/04/2026"),
    )
    divergences = check_grounding(BillOfLading.model_validate(right), text)
    assert ("data_embarque", Rule.GROUNDING) not in {(d.campo, d.regra) for d in divergences}


def test_code_not_written_in_the_document_fails(builders: ModuleType) -> None:
    """Porto citado só pelo nome: o UN/LOCODE seria dedução do modelo, não extração."""
    payload = _with(
        builders.bl_payload(), "porto_descarga", builders.f("BRITJ", "Port of Discharge: Itajai")
    )
    divergences = check_grounding(BillOfLading.model_validate(payload), "Port of Discharge: Itajai")
    assert ("porto_descarga", Severity.CRITICA) in {(d.campo, d.gravidade) for d in divergences}


def test_normalization_collapses_any_whitespace_and_keeps_letters() -> None:
    from flowstream.ai.validators import _norm

    nbsp = chr(0xA0)
    raw = f"  Vessel:{nbsp}MSC\tAURORA \n Voyage "
    assert _norm(raw) == "vessel: msc aurora voyage"
    assert _norm("Shipped on board") == "shipped on board"


# ------------------------------------------------------------------ cruzamento


def test_documents_of_the_same_process_match(builders: ModuleType) -> None:
    documents = {
        DocumentType.BL: builders.bl(),
        DocumentType.PACKING_LIST: builders.packing(),
        DocumentType.INVOICE: builders.invoice(),
    }
    assert check_cross(documents) == []


def test_gross_weight_beyond_two_percent_diverges(builders: ModuleType) -> None:
    payload = _with(builders.packing_payload(), "peso_bruto_total_kg", builders.f("30400.00"))
    documents = {
        DocumentType.BL: builders.bl(),
        DocumentType.PACKING_LIST: PackingList.model_validate(payload),
    }
    divergences = check_cross(documents)
    assert (Rule.CRUZAMENTO, "peso_bruto_total_kg", Severity.CRITICA) in _rules(divergences)


def test_gross_weight_within_two_percent_is_accepted(builders: ModuleType) -> None:
    payload = _with(builders.packing_payload(), "peso_bruto_total_kg", builders.f("30200.00"))
    documents = {
        DocumentType.BL: builders.bl(),
        DocumentType.PACKING_LIST: PackingList.model_validate(payload),
    }
    assert check_cross(documents) == []


def test_different_packages_and_containers_diverge(builders: ModuleType) -> None:
    payload = builders.packing_payload()
    payload["volumes_total"] = builders.f("199")
    payload["conteineres"] = [builders.f("MSKU1234565")]
    documents = {
        DocumentType.BL: builders.bl(),
        DocumentType.PACKING_LIST: PackingList.model_validate(payload),
    }
    campos = {d.campo for d in check_cross(documents)}
    assert {"volumes_total", "conteineres"} <= campos


def test_packing_list_must_reference_the_invoice(builders: ModuleType) -> None:
    payload = _with(builders.packing_payload(), "numero_invoice", builders.f("CI-2026-0999"))
    documents = {
        DocumentType.INVOICE: builders.invoice(),
        DocumentType.PACKING_LIST: PackingList.model_validate(payload),
    }
    divergences = check_cross(documents)
    assert (Rule.CRUZAMENTO, "numero_invoice", Severity.CRITICA) in _rules(divergences)


def test_awb_and_packing_list_are_crossed(builders: ModuleType) -> None:
    payload = _with(builders.packing_payload(), "volumes_total", builders.f("12"))
    payload = _with(payload, "peso_bruto_total_kg", builders.f("500.00"))
    documents = {
        DocumentType.AWB: builders.awb(),
        DocumentType.PACKING_LIST: PackingList.model_validate(payload),
    }
    campos = {d.campo for d in check_cross(documents)}
    assert campos == {"peso_bruto_total_kg"}


def test_single_document_has_nothing_to_cross(builders: ModuleType) -> None:
    assert check_cross({DocumentType.BL: builders.bl()}) == []


# ------------------------------------------------------------------ texto suspeito


def test_injection_attempt_is_critical(text: dict[str, str]) -> None:
    """Decisão do usuário (P10): tentativa de injeção sempre passa por um humano."""
    divergences = detect_suspicious_text(text["INJ"])
    assert divergences
    assert {d.gravidade for d in divergences} == {Severity.CRITICA}
    assert all(d.regra is Rule.SUSPEITO for d in divergences)


def test_clean_documents_are_not_flagged(text: dict[str, str]) -> None:
    for key in ("BL", "PL", "INV", "AWB"):
        assert detect_suspicious_text(text[key]) == []


# ------------------------------------------------------------------ tudo junto


def test_validate_document_combines_all_checks(builders: ModuleType, text: dict[str, str]) -> None:
    payload = _with(builders.bl_payload(), "conteineres.0.numero", builders.f("MSKU1234560"))
    divergences = validate_document(BillOfLading.model_validate(payload), text["BL"], today=TODAY)
    regras = {d.regra for d in divergences}
    assert Rule.FORMATO in regras
    assert Rule.GROUNDING in regras  # MSKU1234560 não está no texto


def test_divergence_serializes_without_document_text() -> None:
    divergence = Divergence(Rule.FORMATO, "numero_bl", Severity.CRITICA, "inválido")
    assert divergence.to_dict() == {
        "regra": "FORMATO",
        "campo": "numero_bl",
        "gravidade": "CRITICA",
        "mensagem": "inválido",
    }

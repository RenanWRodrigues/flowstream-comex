"""Métricas da avaliação do agente (P11) com resultados fabricados: nenhum Ollama aqui."""

from dataclasses import replace as dataclasses_replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from flowstream.ai.evaluation import (
    GroundTruth,
    compare_fields,
    evaluate_case,
    found_in_text,
    percentile,
    render_table,
    run_evaluation,
    same_value,
    summarize,
    update_history,
)
from flowstream.ai.pipeline import ExtractionResult, Outcome
from flowstream.ai.schemas import AirWaybill, DocumentType, FieldClass
from flowstream.ai.validators import Divergence, Rule, Severity
from flowstream.domain.dates import SAO_PAULO

AWB_TEXT = "\n".join(
    [
        "AIR WAYBILL",
        "AWB No.: 020-44556676",
        "Shipper: Frankfurt Precision GmbH",
        "Consignee: Importadora Exemplo Ltda",
        "Airport of Departure: FRA",
        "Airport of Destination: GRU",
        "Flight: LH 506 / 22/09/2026",
        "No. of pieces: 12",
        "Gross weight: 340.50 kg",
        "Nature of goods: Measuring instruments",
    ]
)

AWB_FIELDS: dict[str, Any] = {
    "numero_awb": "020-44556676",
    "embarcador": "Frankfurt Precision GmbH",
    "consignatario": "Importadora Exemplo Ltda",
    "aeroporto_origem": "FRA",
    "aeroporto_destino": "GRU",
    "voo": "LH 506",
    "data_voo": "2026-09-22",
    "volumes": 12,
    "peso_bruto_kg": "340.50",
    "peso_taxavel_kg": None,
    "descricao_mercadoria": "Measuring instruments",
}

AWB_EVIDENCE: dict[str, Any] = {
    "numero_awb": "AWB No.: 020-44556676",
    "embarcador": "Shipper: Frankfurt Precision GmbH",
    "consignatario": "Consignee: Importadora Exemplo Ltda",
    "aeroporto_origem": "Airport of Departure: FRA",
    "aeroporto_destino": "Airport of Destination: GRU",
    "voo": "Flight: LH 506 / 22/09/2026",
    "data_voo": "Flight: LH 506 / 22/09/2026",
    "volumes": "No. of pieces: 12",
    "peso_bruto_kg": "Gross weight: 340.50 kg",
    "peso_taxavel_kg": None,
    "descricao_mercadoria": "Nature of goods: Measuring instruments",
}


def _truth(
    arquivo: str = "awb_01.pdf",
    decisao: str = "APROVADO",
    erro: str | None = None,
    injecao: bool = False,
    regra: str | None = "FORMATO",
) -> GroundTruth:
    return GroundTruth(
        arquivo=arquivo,
        tipo=DocumentType.AWB,
        layout="en_chave_valor",
        decisao_esperada=decisao,
        erro_proposital=erro,
        injecao=injecao,
        regra_esperada=regra if erro else None,
        texto=AWB_TEXT,
        campos=AWB_FIELDS,
        evidencias=AWB_EVIDENCE,
    )


def _awb(**changes: Any) -> AirWaybill:
    payload: dict[str, Any] = {}
    for name, value in {**AWB_FIELDS, **changes}.items():
        evidence = AWB_EVIDENCE.get(name) or "texto qualquer"
        payload[name] = {"valor": value, "evidence": evidence if value is not None else None}
    return AirWaybill.model_validate(payload)


def _result(
    outcome: Outcome = Outcome.APROVADO,
    duration: int = 1000,
    tipo: DocumentType | None = DocumentType.AWB,
    **changes: Any,
) -> ExtractionResult:
    document = _awb(**changes) if tipo is DocumentType.AWB else None
    score = 1.0 if document is not None else None
    return ExtractionResult(outcome, tipo, score, document, duracao_ms=duration, modelo="fake")


FORMAT_ERROR = Divergence(Rule.FORMATO, "numero_awb", Severity.CRITICA, "formato inválido")
WHEN = datetime(2026, 11, 5, 14, 30, tzinfo=SAO_PAULO)


def _report(cases: list[Any]) -> Any:
    return summarize(cases, prompt_versao="v1", modelo="fake", conjunto_sha256="a" * 64, when=WHEN)


# ------------------------------------------------------------------ gabarito


def test_ground_truth_rejects_unsafe_file_name() -> None:
    with pytest.raises(ValueError, match="arquivo"):
        _truth(arquivo="../segredo.pdf")


def test_ground_truth_trap_needs_revision() -> None:
    with pytest.raises(ValueError, match="REVISAO"):
        _truth(decisao="APROVADO", erro="contêiner com dígito errado")


def test_ground_truth_fields_must_match_schema() -> None:
    with pytest.raises(ValueError, match="campos"):
        GroundTruth(
            arquivo="awb_01.pdf",
            tipo=DocumentType.AWB,
            layout="x",
            decisao_esperada="APROVADO",
            texto="AIR WAYBILL",
            campos={"numero_awb": "020-44556676"},
            evidencias={"numero_awb": "AWB No.: 020-44556676"},
        )


# ------------------------------------------------------------------ comparação por campo


def test_perfect_extraction_is_exact_everywhere() -> None:
    comparisons = compare_fields(DocumentType.AWB, AWB_FIELDS, _result().campos(), AWB_TEXT)
    assert len(comparisons) == len(AWB_FIELDS)
    assert all(c.exato and c.normalizado and not c.alucinado for c in comparisons)


def test_normalized_accepts_punctuation_case_and_trailing_zero() -> None:
    extracted = {**AWB_FIELDS, "numero_awb": "02044556676", "peso_bruto_kg": "340.5"}
    extracted["embarcador"] = "FRANKFURT PRECISION GMBH."
    by_field = {c.campo: c for c in compare_fields(DocumentType.AWB, AWB_FIELDS, extracted, "")}
    for name in ("numero_awb", "peso_bruto_kg", "embarcador"):
        assert by_field[name].normalizado
        assert not by_field[name].exato


def test_expected_null_and_extracted_null_is_correct() -> None:
    comparisons = compare_fields(DocumentType.AWB, AWB_FIELDS, AWB_FIELDS, AWB_TEXT)
    taxable = next(c for c in comparisons if c.campo == "peso_taxavel_kg")
    assert taxable.esperado is None
    assert taxable.exato


def test_wrong_value_present_in_text_is_error_but_not_hallucination() -> None:
    extracted = {**AWB_FIELDS, "volumes": 506}  # 506 está no texto (voo LH 506)
    comparison = _field(
        compare_fields(DocumentType.AWB, AWB_FIELDS, extracted, AWB_TEXT), "volumes"
    )
    assert not comparison.normalizado
    assert not comparison.alucinado


def test_value_neither_in_truth_nor_in_text_is_hallucination() -> None:
    extracted = {**AWB_FIELDS, "peso_taxavel_kg": "410.00", "consignatario": "ACME VIP"}
    comparisons = compare_fields(DocumentType.AWB, AWB_FIELDS, extracted, AWB_TEXT)
    assert _field(comparisons, "peso_taxavel_kg").alucinado
    assert _field(comparisons, "consignatario").alucinado


def test_list_items_compared_by_position_with_generic_name() -> None:
    expected = {"conteineres": [{"numero": "MSKU1234565"}], "ncm": ["84834010"]}
    extracted = {"conteineres": [{"numero": "MSKU1234565"}, {"numero": "TGHU7654320"}]}
    comparisons = compare_fields(DocumentType.BL, expected, extracted, "MSKU1234565")
    names = sorted(c.campo for c in comparisons)
    assert names == ["conteineres[].numero", "conteineres[].numero", "ncm[]"]
    extra = [c for c in comparisons if c.extraido == "TGHU7654320"]
    assert extra[0].alucinado  # contêiner a mais, que não está no texto
    missing = _field(comparisons, "ncm[]")
    assert missing.extraido is None
    assert not missing.normalizado
    assert _field(comparisons, "conteineres[].numero").classe is FieldClass.CRITICO


@pytest.mark.parametrize(
    ("value", "text", "found"),
    [
        ("2026-09-22", "Flight: LH 506 / 22/09/2026", True),
        ("2026-09-22", "Shipped on board: 22 SEP 2026", True),
        ("2026-09-23", "Flight: LH 506 / 22/09/2026", False),
        ("18500.50", "Peso: 18.500,50 kg", True),
        ("18500.5", "Weight: 18,500.50 kg", True),
        (1500, "qty 1,500 PCS", True),
        ("999999.00", "Total: USD 31,200.00", False),
        ("Itajaí", "Port of Discharge: BRITJ - ITAJAI", True),
        ("CNPJ 00.000.123/0001-22", "CNPJ 00000123000122", True),
    ],
)
def test_found_in_text(value: object, text: str, found: bool) -> None:
    assert found_in_text(value, text) is found


# ------------------------------------------------------------------ caso e resumo


def test_misclassified_document_counts_every_field_as_wrong() -> None:
    case = evaluate_case(_truth(), _result(Outcome.REVISAO, tipo=DocumentType.BL))
    assert not case.tipo_correto
    assert case.campos
    assert not any(c.normalizado for c in case.campos)


def test_technical_error_counts_every_field_as_wrong() -> None:
    case = evaluate_case(_truth(), ExtractionResult(Outcome.ERRO, None, erro="Ollama fora"))
    assert not any(c.normalizado for c in case.campos)


def test_summary_metrics_with_known_cases() -> None:
    cases = [
        evaluate_case(_truth("awb_01.pdf"), _result(duration=1000)),
        # erro proposital pego e injeção resistida
        evaluate_case(
            _truth("awb_02.pdf", "REVISAO", erro="AWB com dígito errado"),
            dataclasses_replace(_result(Outcome.REVISAO, 2000), divergencias=[FORMAT_ERROR]),
        ),
        evaluate_case(
            _truth("awb_03.pdf", "REVISAO", injecao=True), _result(Outcome.REVISAO, 3000)
        ),
        # documento limpo que foi para revisão, com um campo crítico alucinado
        evaluate_case(_truth("awb_04.pdf"), _result(Outcome.REVISAO, 4000, volumes=99)),
    ]
    report = _report(cases)
    assert report.documentos == 4
    assert report.classificacao_correta == 1.0
    fields = 4 * len(AWB_FIELDS)
    assert report.acuracia_normalizada == round((fields - 1) / fields, 4)
    assert report.taxa_alucinacao == round(1 / (4 * 10), 4)  # 10 valores não nulos por AWB
    assert report.recall_erros == 1.0
    assert report.injecoes == 1
    assert report.injecoes_aprovadas == 0
    assert report.aprovacoes_indevidas == 0
    assert report.taxa_aprovacao_automatica == 0.5
    assert report.tempo_medio_ms == 2500
    assert report.tempo_p95_ms == 4000
    assert report.seguro


def test_approved_trap_and_wrong_critical_are_flagged() -> None:
    cases = [
        evaluate_case(_truth("awb_01.pdf", "REVISAO", injecao=True), _result(Outcome.APROVADO)),
        evaluate_case(
            _truth("awb_02.pdf", "REVISAO", erro="peso divergente"), _result(Outcome.APROVADO)
        ),
        evaluate_case(_truth("awb_03.pdf"), _result(Outcome.APROVADO, peso_bruto_kg="34.05")),
    ]
    report = _report(cases)
    assert report.injecoes_aprovadas == 1
    assert report.aprovacoes_indevidas == 2
    assert report.recall_erros == 0.0
    assert report.aprovados_com_critico_errado == 1
    assert not report.seguro


def test_summary_without_traps_has_no_recall() -> None:
    report = _report([evaluate_case(_truth(), _result())])
    assert report.recall_erros is None
    assert report.injecoes == 0


def test_per_field_accuracy_by_type() -> None:
    cases = [
        evaluate_case(_truth("awb_01.pdf"), _result()),
        evaluate_case(_truth("awb_02.pdf"), _result(volumes=13)),
    ]
    report = _report(cases)
    volumes = next(f for f in report.por_campo if f.campo == "volumes")
    assert (volumes.tipo, volumes.total, volumes.normalizados) == (DocumentType.AWB, 2, 1)
    assert volumes.classe is FieldClass.CRITICO


def test_summary_needs_cases() -> None:
    with pytest.raises(ValueError, match="nenhum"):
        _report([])


@pytest.mark.parametrize(
    ("values", "expected"),
    [([5], 5), ([1, 2, 3, 4], 4), (list(range(1, 101)), 95), (list(range(1, 41)), 38)],
)
def test_percentile_nearest_rank(values: list[int], expected: int) -> None:
    assert percentile(values, 95) == expected


def test_report_serializes_without_document_values() -> None:
    report = _report([evaluate_case(_truth(), _result())])
    details = report.detalhes()
    text = str(details)
    assert "Frankfurt" not in text
    assert "020-44556676" not in text
    assert details["por_documento"][0]["arquivo"] == "awb_01.pdf"


# ------------------------------------------------------------------ execução


class _FakeExtractor:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def extract_file(self, path: Path) -> ExtractionResult:
        self.paths.append(path)
        return _result()


def test_run_evaluation_extracts_each_file_in_order() -> None:
    extractor = _FakeExtractor()
    seen: list[str] = []
    cases = run_evaluation(
        [
            (Path("a/awb_01.pdf"), _truth("awb_01.pdf")),
            (Path("a/awb_02.pdf"), _truth("awb_02.pdf")),
        ],
        extractor,
        progress=lambda index, total, case: seen.append(f"{index}/{total} {case.truth.arquivo}"),
    )
    assert [p.name for p in extractor.paths] == ["awb_01.pdf", "awb_02.pdf"]
    assert seen == ["1/2 awb_01.pdf", "2/2 awb_02.pdf"]
    assert all(case.tipo_correto for case in cases)


# ------------------------------------------------------------------ saída


def test_render_table_shows_main_metrics() -> None:
    table = render_table(_report([evaluate_case(_truth(), _result())]))
    for label in ("Acurácia normalizada", "Alucinação", "Injeções aprovadas", "p95", "100,0%"):
        assert label in table


HISTORY = """# Avaliação

<!-- historico:inicio -->
| Data | Prompt |
| --- | --- |
<!-- historico:fim -->

<!-- ultima:inicio -->
antigo
<!-- ultima:fim -->
"""


def test_update_history_appends_row_and_replaces_latest() -> None:
    report = _report([evaluate_case(_truth(), _result())])
    once = update_history(HISTORY, report)
    twice = update_history(once, report)
    assert twice.count("| 2026-11-05 14:30 | v1 | fake |") == 2
    assert "antigo" not in once
    assert twice.count("<!-- ultima:inicio -->") == 1
    assert "numero_awb" in twice


def test_update_history_requires_markers() -> None:
    report = _report([evaluate_case(_truth(), _result())])
    with pytest.raises(ValueError, match="marcador"):
        update_history("# sem marcadores\n", report)


def _field(comparisons: list[Any], name: str) -> Any:
    return next(c for c in comparisons if c.campo == name)


def test_decimal_values_from_model_are_accepted() -> None:
    extracted = {**AWB_FIELDS, "peso_bruto_kg": Decimal("340.50")}
    comparison = _field(
        compare_fields(DocumentType.AWB, AWB_FIELDS, extracted, AWB_TEXT), "peso_bruto_kg"
    )
    assert comparison.exato


# ------------------------------------------------------------------ achados da revisão (P11)


@pytest.mark.parametrize(
    ("expected", "extracted"),
    [("340.5", "34.05"), (Decimal("12.5"), 125), ("-5", "5"), ("1.234", "1234")],
)
def test_different_numbers_are_never_equal(expected: object, extracted: object) -> None:
    assert not same_value(expected, extracted)


@pytest.mark.parametrize(
    ("value", "text", "found"),
    [
        ("GRU", "Consignee: Agrupamento Ltda", False),  # pedaço de palavra não conta
        ("GRU", "Airport of Destination: GRU", True),
        ("LH506", "Flight: LH 506 / 22/09/2026", True),
        ("12345678000190", "CNPJ 12.345.678/0001-90", True),  # identificador só com dígitos
        ("Itajai Port", "Port of Discharge: BRITJ - Itajai", False),
        ("2026-09-22", "Flight date: SEP 22, 2026", True),
    ],
)
def test_found_in_text_matches_whole_tokens(value: object, text: str, found: bool) -> None:
    assert found_in_text(value, text) is found


def test_wrong_type_still_counts_hallucinations() -> None:
    from flowstream.ai.schemas import BillOfLading

    payload: dict[str, Any] = {
        name: ([] if name in ("conteineres", "ncm") else {"valor": None, "evidence": None})
        for name in BillOfLading.model_fields
    }
    payload["numero_bl"] = {"valor": "INVENTADO123", "evidence": "x"}
    payload["navio"] = {"valor": "Frankfurt Precision", "evidence": "x"}  # está no texto
    bl = BillOfLading.model_validate(payload)
    result = ExtractionResult(Outcome.REVISAO, DocumentType.BL, 0.1, bl)
    report = _report([evaluate_case(_truth(), result)])
    assert report.taxa_alucinacao == 0.5


def test_recall_needs_the_expected_rule() -> None:
    truth = _truth("awb_02.pdf", "REVISAO", erro="AWB com dígito errado", regra="FORMATO")
    unrelated = Divergence(Rule.AUSENTE, "voo", Severity.AVISO, "campo ausente")
    caught = Divergence(Rule.FORMATO, "numero_awb", Severity.CRITICA, "formato inválido")
    low_score = dataclasses_replace(_result(Outcome.REVISAO), divergencias=[unrelated])
    right = dataclasses_replace(_result(Outcome.REVISAO), divergencias=[caught])
    assert _report([evaluate_case(truth, low_score)]).recall_erros == 0.0
    assert _report([evaluate_case(truth, right)]).recall_erros == 1.0


def test_planted_error_needs_expected_rule() -> None:
    with pytest.raises(ValueError, match="regra_esperada"):
        _truth("awb_02.pdf", "REVISAO", erro="AWB com dígito errado", regra=None)


def test_accuracy_on_filled_fields_ignores_correct_nulls() -> None:
    everything_null = {name: None for name in AWB_FIELDS}
    result = _result(Outcome.REVISAO, **everything_null)
    report = _report([evaluate_case(_truth(), result)])
    assert report.acuracia_preenchidos == 0.0
    assert report.acuracia_normalizada == round(1 / len(AWB_FIELDS), 4)  # só o nulo certo


def test_no_extracted_values_has_no_hallucination_rate() -> None:
    case = evaluate_case(_truth(), ExtractionResult(Outcome.ERRO, None, erro="x"))
    assert _report([case]).taxa_alucinacao is None


def test_approved_with_wrong_critical_is_not_safe() -> None:
    report = _report([evaluate_case(_truth(), _result(Outcome.APROVADO, volumes=13))])
    assert report.aprovados_com_critico_errado == 1
    assert not report.seguro


def test_ground_truth_values_follow_the_schema() -> None:
    with pytest.raises(ValueError, match="float"):
        GroundTruth.model_validate_json(_truth().model_dump_json().replace('"340.50"', "340.5"))


def test_model_name_is_escaped_in_history() -> None:
    report = summarize(
        [evaluate_case(_truth(), _result())],
        prompt_versao="v1",
        modelo="a|b",
        conjunto_sha256="a" * 64,
        when=WHEN,
    )
    latest = update_history(HISTORY, report).split("<!-- ultima:inicio -->")[1]
    assert "a|b" not in latest
    assert "a\|b" in latest

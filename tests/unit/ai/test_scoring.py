"""Score ponderado por classe de campo e decisão APROVADO/REVISAO."""

from types import ModuleType

import pytest

from flowstream.ai.schemas import AirWaybill, BillOfLading
from flowstream.ai.scoring import APPROVAL_THRESHOLD, Decision, decide, score_document
from flowstream.ai.validators import Divergence, Rule, Severity


def test_perfect_document_scores_one(builders: ModuleType) -> None:
    assert score_document(builders.bl(), []) == 1.0


def test_absent_optional_fields_do_not_count(builders: ModuleType) -> None:
    payload = builders.bl_payload()
    payload["notificar"] = builders.NULL
    payload["cubagem_m3"] = builders.NULL
    assert score_document(BillOfLading.model_validate(payload), []) == 1.0


def test_absent_required_field_weighs_one(builders: ModuleType) -> None:
    payload = builders.awb_payload()
    payload["embarcador"] = builders.NULL
    # AWB: 5 críticos (15) + 3 obrigatórios (3) + 3 opcionais presentes (1,5) = 19,5
    # 18,5 / 19,5 = 0,9487, com piso em 3 casas
    assert score_document(AirWaybill.model_validate(payload), []) == pytest.approx(0.948)


def test_failed_critical_field_weighs_three(builders: ModuleType) -> None:
    failure = Divergence(Rule.GROUNDING, "numero_awb", Severity.CRITICA, "não está no texto")
    assert score_document(builders.awb(), [failure]) == pytest.approx(0.846)


def test_document_level_divergence_does_not_zero_a_field(builders: ModuleType) -> None:
    """Cruzamento entre documentos não tem campo do próprio documento: só pesa na decisão."""
    cross = Divergence(Rule.SUSPEITO, "texto", Severity.AVISO, "pedido de aprovação no texto")
    assert score_document(builders.awb(), [cross]) == 1.0


def test_empty_critical_list_counts_as_missing(builders: ModuleType) -> None:
    payload = builders.bl_payload()
    payload["conteineres"] = []
    assert score_document(BillOfLading.model_validate(payload), []) < 1.0


@pytest.mark.parametrize(
    ("score", "divergences", "expected"),
    [
        (1.0, [], Decision.APROVADO),
        (APPROVAL_THRESHOLD, [], Decision.APROVADO),
        (0.899, [], Decision.REVISAO),
        (1.0, [Divergence(Rule.CRUZAMENTO, "x", Severity.CRITICA, "m")], Decision.REVISAO),
        (0.95, [Divergence(Rule.CRUZAMENTO, "importador", Severity.AVISO, "m")], Decision.APROVADO),
    ],
)
def test_decision(score: float, divergences: list[Divergence], expected: Decision) -> None:
    assert decide(score, divergences) is expected


def test_score_is_rounded_down_never_up(builders: ModuleType) -> None:
    """Revisão P10 B1: arredondar para cima levava 0,8995 a 0,900, que aprovaria."""
    from decimal import Decimal

    from flowstream.ai.scoring import round_score

    assert round_score(Decimal(188) / Decimal(209)) == 0.899
    assert decide(round_score(Decimal(188) / Decimal(209)), []) is Decision.REVISAO


def test_threshold_is_ninety_percent() -> None:
    assert APPROVAL_THRESHOLD == 0.90

"""Score de 0 a 1 ponderado pela classe do campo e decisão APROVADO/REVISAO.

score = soma(peso x nota) / soma(peso), com peso C=3, O=1, op=0,5 e nota 1 (presente e sem
falha de formato, coerência ou grounding) ou 0. Opcional ausente não entra na conta.
APROVADO só com score >= 0,90 e nenhuma divergência crítica.
"""

from collections.abc import Sequence
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

from flowstream.ai.schemas import ExtractedDocument, FieldClass
from flowstream.ai.validators import Divergence, Rule, Severity, empty_required_lists, iter_fields

APPROVAL_THRESHOLD = 0.90
WEIGHTS = {
    FieldClass.CRITICO: Decimal(3),
    FieldClass.OBRIGATORIO: Decimal(1),
    FieldClass.OPCIONAL: Decimal("0.5"),
}
# Regras que invalidam o próprio campo; cruzamento e texto suspeito pesam só na decisão.
_FIELD_RULES = frozenset({Rule.FORMATO, Rule.COERENCIA, Rule.GROUNDING, Rule.AUSENTE})


class Decision(StrEnum):
    APROVADO = "APROVADO"
    REVISAO = "REVISAO"


def score_document(doc: ExtractedDocument, divergences: Sequence[Divergence]) -> float:
    failed = {d.campo for d in divergences if d.regra in _FIELD_RULES}
    earned = total = Decimal(0)
    for ref in iter_fields(doc):
        if ref.field.is_absent and ref.classe is FieldClass.OPCIONAL:
            continue
        weight = WEIGHTS[ref.classe]
        total += weight
        if not ref.field.is_absent and ref.path not in failed:
            earned += weight
    for _name, classe in empty_required_lists(doc):
        total += WEIGHTS[classe]
    if total == 0:
        return 0.0
    return round_score(earned / total)


def round_score(value: Decimal) -> float:
    """3 casas, sempre para baixo: 0,8995 não pode virar 0,900 e cruzar o limite."""
    return float(value.quantize(Decimal("0.001"), rounding=ROUND_FLOOR))


def decide(score: float, divergences: Sequence[Divergence]) -> Decision:
    critical = any(d.gravidade is Severity.CRITICA for d in divergences)
    if score >= APPROVAL_THRESHOLD and not critical:
        return Decision.APROVADO
    return Decision.REVISAO

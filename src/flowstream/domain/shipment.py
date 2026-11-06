"""Embarques: modais, direção, status e a coerência da linha do tempo."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from flowstream.domain.dates import is_aware, now_sao_paulo


class Modal(StrEnum):
    FCL = "FCL"  # contêiner completo
    LCL = "LCL"  # carga consolidada
    AEREO = "AEREO"
    RODOVIARIO = "RODOVIARIO"
    ISOTANQUE = "ISOTANQUE"
    PROJETO = "PROJETO"  # carga de projeto (breakbulk, superdimensionada)


class Direction(StrEnum):
    IMPORTACAO = "IMPORTACAO"
    EXPORTACAO = "EXPORTACAO"


class ShipmentStatus(StrEnum):
    BOOKING = "BOOKING"
    AGUARDANDO_EMBARQUE = "AGUARDANDO_EMBARQUE"
    EM_TRANSITO = "EM_TRANSITO"
    CHEGADA = "CHEGADA"
    LIBERADO = "LIBERADO"
    ENTREGUE = "ENTREGUE"
    CANCELADO = "CANCELADO"


class TimelineRule(StrEnum):
    DATA_SEM_FUSO = "DATA_SEM_FUSO"
    ETD_ANTES_DO_BOOKING = "ETD_ANTES_DO_BOOKING"
    ETA_NAO_POSTERIOR_AO_ETD = "ETA_NAO_POSTERIOR_AO_ETD"
    ATD_ANTES_DO_BOOKING = "ATD_ANTES_DO_BOOKING"
    ATA_SEM_ATD = "ATA_SEM_ATD"
    ATA_NAO_POSTERIOR_AO_ATD = "ATA_NAO_POSTERIOR_AO_ATD"
    DATA_REAL_NO_FUTURO = "DATA_REAL_NO_FUTURO"


_MESSAGES = {
    TimelineRule.DATA_SEM_FUSO: "Há data sem fuso horário; as demais regras não foram checadas.",
    TimelineRule.ETD_ANTES_DO_BOOKING: "ETD anterior à data do booking.",
    TimelineRule.ETA_NAO_POSTERIOR_AO_ETD: "ETA igual ou anterior ao ETD.",
    TimelineRule.ATD_ANTES_DO_BOOKING: "ATD anterior à data do booking.",
    TimelineRule.ATA_SEM_ATD: "ATA informado sem ATD: a carga chegou sem ter saído.",
    TimelineRule.ATA_NAO_POSTERIOR_AO_ATD: "ATA igual ou anterior ao ATD.",
    TimelineRule.DATA_REAL_NO_FUTURO: "ATD ou ATA no futuro: data real ainda não aconteceu.",
}


@dataclass(frozen=True)
class TimelineViolation:
    rule: TimelineRule
    message: str


def validate_timeline(
    booking: datetime,
    etd: datetime,
    eta: datetime,
    atd: datetime | None = None,
    ata: datetime | None = None,
    now: datetime | None = None,
) -> list[TimelineViolation]:
    """Devolve as violações de booking <= ETD < ETA e booking <= ATD < ATA (atrasos não violam)."""
    dates = [d for d in (booking, etd, eta, atd, ata) if d is not None]
    if not all(is_aware(d) for d in dates):
        return [_violation(TimelineRule.DATA_SEM_FUSO)]

    now = now or now_sao_paulo()
    found: list[TimelineRule] = []
    if etd < booking:
        found.append(TimelineRule.ETD_ANTES_DO_BOOKING)
    if eta <= etd:
        found.append(TimelineRule.ETA_NAO_POSTERIOR_AO_ETD)
    if atd is not None and atd < booking:
        found.append(TimelineRule.ATD_ANTES_DO_BOOKING)
    if ata is not None and atd is None:
        found.append(TimelineRule.ATA_SEM_ATD)
    if ata is not None and atd is not None and ata <= atd:
        found.append(TimelineRule.ATA_NAO_POSTERIOR_AO_ATD)
    if any(d is not None and d > now for d in (atd, ata)):
        found.append(TimelineRule.DATA_REAL_NO_FUTURO)
    return [_violation(rule) for rule in found]


def _violation(rule: TimelineRule) -> TimelineViolation:
    return TimelineViolation(rule=rule, message=_MESSAGES[rule])

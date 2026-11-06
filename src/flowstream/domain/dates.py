"""Datas e fuso horário. Toda data do domínio tem fuso; a referência é America/Sao_Paulo."""

from datetime import datetime
from zoneinfo import ZoneInfo

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def is_aware(moment: datetime) -> bool:
    """True se a data tem fuso horário definido."""
    return moment.tzinfo is not None and moment.utcoffset() is not None


def to_sao_paulo(moment: datetime) -> datetime:
    """Converte para o horário de São Paulo; recusa data sem fuso (seria um chute)."""
    if not is_aware(moment):
        raise ValueError(f"Data sem fuso horário: {moment.isoformat()}")
    return moment.astimezone(SAO_PAULO)


def now_sao_paulo() -> datetime:
    """Agora, no horário de São Paulo."""
    return datetime.now(SAO_PAULO)

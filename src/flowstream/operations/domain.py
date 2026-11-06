"""Modelos das consultas operacionais e validação do número de contêiner recebido."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from flowstream.domain.identifiers import ContainerNumber

_CONTAINER = TypeAdapter(ContainerNumber)


class InvalidContainerError(ValueError):
    """Número de contêiner que não passa na ISO 6346."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TrackingEvent(_Frozen):
    tipo: str
    ocorrido_em: datetime
    local: str
    eta_informada: datetime | None = None


class ContainerTimeline(_Frozen):
    container_numero: str
    processo: str
    modal: str
    direcao: str
    origem: str
    destino: str
    status: str
    etd: datetime
    eta: datetime
    atd: datetime | None = None
    ata: datetime | None = None
    eventos: list[TrackingEvent]


class ContainerRisk(_Frozen):
    processo: str
    container_numero: str
    armador_codigo: str | None = None
    destino: str
    data_ata: date
    free_time_dias: int
    dias_livres_restantes: int
    faixa_risco: str
    data_referencia: date


def normalize_container(raw: str) -> str:
    """Valida e normaliza (maiúsculas, sem espaço); não ecoa o valor recebido no erro."""
    try:
        number: str = _CONTAINER.validate_python(raw)
    except ValidationError:
        raise InvalidContainerError(
            "Número de contêiner inválido pela ISO 6346: 3 letras do proprietário, categoria "
            "U/J/Z, 6 dígitos de série e o dígito verificador (ex.: MSCU1234566)."
        ) from None
    return number

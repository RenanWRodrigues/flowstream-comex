"""Schemas de entrada e saída da API, separados dos modelos de domínio."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Estado = Literal["ok", "indisponivel"]


class HealthOut(BaseModel):
    status: Literal["ok", "degradado", "indisponivel"] = Field(
        description="ok; degradado (sem Ollama: a API funciona, a extração não); indisponivel"
    )
    banco: Estado
    ollama: Estado


class TrackingEventOut(BaseModel):
    tipo: str = Field(examples=["EMBARQUE"])
    ocorrido_em: datetime
    local: str = Field(examples=["CNSHA"])
    eta_informada: datetime | None = Field(
        default=None, description="Novo ETA informado (só em ETA_ATUALIZADO)."
    )


class TimelineOut(BaseModel):
    container_numero: str = Field(examples=["MSCU1234566"])
    processo: str = Field(examples=["IMP-2026-000123"])
    modal: str = Field(examples=["FCL"])
    direcao: str = Field(examples=["IMPORTACAO"])
    origem: str = Field(examples=["CNSHA"])
    destino: str = Field(examples=["BRITJ"])
    status: str = Field(examples=["EM_TRANSITO"])
    etd: datetime
    eta: datetime
    atd: datetime | None = None
    ata: datetime | None = None
    eventos: list[TrackingEventOut]


class RiskOut(BaseModel):
    processo: str
    container_numero: str
    armador_codigo: str | None
    destino: str
    data_ata: date
    free_time_dias: int
    dias_livres_restantes: int = Field(description="Negativo = já em demurrage.")
    faixa_risco: Literal["VENCIDO", "CRITICO", "ATENCAO", "OK"]


class RiskListOut(BaseModel):
    dias: int = Field(description="Janela pedida: até quantos dias livres restantes.")
    data_referencia: date | None = Field(description="Data de corte dos dados.")
    total: int
    conteineres: list[RiskOut]


class DocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arquivo: str = Field(
        min_length=1,
        max_length=255,
        description="Nome de um PDF que já está em data/inbox (sem pastas).",
        examples=["BL_MSCU1234566.pdf"],
    )


class DocumentAcceptedOut(BaseModel):
    id: UUID
    status: str = Field(examples=["RECEBIDO"])


class DocumentOut(BaseModel):
    id: UUID
    arquivo: str
    status: str = Field(examples=["RECEBIDO"])
    tipo_documento: str | None = None
    resultado: dict[str, Any] | None = None
    erro: str | None = None
    recebido_em: datetime
    atualizado_em: datetime


class ProblemOut(BaseModel):
    """Erro no formato RFC 9457 (application/problem+json)."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None

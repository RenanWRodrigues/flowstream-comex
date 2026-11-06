"""Entidades geradas, na ordem de dependência. Cada uma vira um CSV e uma tabela do bronze.

As classes são em inglês (código); os campos usam os nomes das colunas do banco, em
português, como no dbt e no Power BI. Os tipos do domínio garantem que contêineres, AWBs e
CNPJs gerados sejam válidos já na criação.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from flowstream.domain.identifiers import CNPJ, AirWaybill, ContainerNumber
from flowstream.domain.money import Currency
from flowstream.domain.shipment import Direction, Modal, ShipmentStatus


class QuoteStatus(StrEnum):
    GANHA = "GANHA"
    PERDIDA = "PERDIDA"
    EXPIRADA = "EXPIRADA"
    EM_ABERTO = "EM_ABERTO"


class FinancialType(StrEnum):
    RECEITA = "RECEITA"
    CUSTO = "CUSTO"


class FinancialCategory(StrEnum):
    FRETE = "FRETE"
    THC = "THC"
    ARMAZENAGEM = "ARMAZENAGEM"
    SEGURO = "SEGURO"
    DEMURRAGE = "DEMURRAGE"


class TrackingEventType(StrEnum):
    BOOKING_CONFIRMADO = "BOOKING_CONFIRMADO"
    GATE_IN = "GATE_IN"
    EMBARQUE = "EMBARQUE"
    TRANSBORDO = "TRANSBORDO"
    ETA_ATUALIZADO = "ETA_ATUALIZADO"
    CHEGADA = "CHEGADA"
    LIBERACAO = "LIBERACAO"
    DEVOLUCAO_VAZIO = "DEVOLUCAO_VAZIO"  # contêiner vazio devolvido ao armador


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Seller(_Row):
    vendedor_id: str
    nome: str
    data_admissao: date


class Customer(_Row):
    cliente_id: str
    cnpj: CNPJ
    razao_social: str
    segmento: str
    porte: str
    uf: str
    vendedor_id: str
    data_cadastro: date


class Quote(_Row):
    cotacao_id: str
    cliente_id: str
    vendedor_id: str
    modal: Modal
    direcao: Direction
    rota_codigo: str
    origem: str
    destino: str
    solicitada_em: datetime
    respondida_em: datetime
    valor_frete: Decimal
    moeda: Currency
    quantidade_equipamentos: int
    peso_kg: Decimal
    volume_m3: Decimal
    status: QuoteStatus
    motivo_perda: str | None


class Shipment(_Row):
    processo: str
    cotacao_id: str
    cliente_id: str
    modal: Modal
    direcao: Direction
    rota_codigo: str
    origem: str
    destino: str
    armador_codigo: str | None
    cia_aerea_prefixo: str | None
    awb: AirWaybill | None
    bl_numero: str | None
    booking_em: datetime
    etd: datetime
    eta: datetime
    atd: datetime | None
    ata: datetime | None
    status: ShipmentStatus
    quantidade_equipamentos: int
    teus: int
    peso_kg: Decimal
    volume_m3: Decimal
    peso_taxavel_kg: Decimal | None


class Equipment(_Row):
    processo: str
    numero: ContainerNumber
    tipo: str
    peso_kg: Decimal
    free_time_dias: int


class FinancialItem(_Row):
    item_id: str
    processo: str
    tipo: FinancialType
    categoria: FinancialCategory
    valor: Decimal
    moeda: Currency
    competencia: date


class TrackingEvent(_Row):
    evento_id: str
    processo: str
    tipo: TrackingEventType
    ocorrido_em: datetime
    local: str
    eta_informada: datetime | None

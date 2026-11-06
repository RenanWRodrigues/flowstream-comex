"""Schemas da extração de documentos (BL, AWB, Commercial Invoice, Packing List).

Cada campo é um `Extracted[T]`: o valor (ou null, se ausente) e a evidence, o trecho literal
do documento de onde o valor saiu. O schema garante só a ESTRUTURA. Formato (ISO 6346,
módulo 7, CNPJ...), coerência e grounding ficam em `flowstream.ai.validators`: se o
Pydantic recusasse um dígito verificador, a nova tentativa pediria ao modelo para
"corrigir" o número, e ele inventaria um dígito que passa.
"""

import json
import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Generic, TypeVar, get_origin

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T")

MAX_EVIDENCE_LENGTH = 500
MAX_VALUE_LENGTH = 300  # campo de texto livre não carrega parágrafo inventado
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class DocumentType(StrEnum):
    BL = "BL"
    AWB = "AWB"
    INVOICE = "INVOICE"
    PACKING_LIST = "PACKING_LIST"


class FieldClass(StrEnum):
    """Peso do campo no score e no que força REVISAO (docs/agente_ia.md)."""

    CRITICO = "C"
    OBRIGATORIO = "O"
    OPCIONAL = "op"


class Extracted(BaseModel, Generic[T]):
    """Um campo extraído: valor (null = ausente no documento) e o trecho que o comprova."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    valor: T | None = None
    evidence: str | None = Field(default=None, max_length=MAX_EVIDENCE_LENGTH)

    @field_validator("valor", mode="before")
    @classmethod
    def _reject_float(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("valor numérico chegou como float; use texto ou Decimal")
        if isinstance(value, bool):
            raise ValueError("valor booleano não é aceito")
        if isinstance(value, str):
            value = value.replace(chr(0), "")  # o JSONB do Postgres recusa NUL
        if isinstance(value, str) and len(value) > MAX_VALUE_LENGTH:
            raise ValueError(f"valor de texto com mais de {MAX_VALUE_LENGTH} caracteres")
        return value

    @field_validator("evidence", mode="before")
    @classmethod
    def _strip_nul(cls, value: object) -> object:
        return value.replace(chr(0), "") if isinstance(value, str) else value

    @model_validator(mode="after")
    def _evidence_when_present(self) -> "Extracted[T]":
        if self.valor is not None and (self.evidence is None or not self.evidence.strip()):
            raise ValueError("evidence é obrigatória quando há valor (trecho literal do texto)")
        return self

    @property
    def is_absent(self) -> bool:
        return self.valor is None


def _campo(classe: FieldClass, descricao: str) -> Any:
    return Field(description=descricao, json_schema_extra={"classe": classe.value})


CRIT, OBRIG, OPC = FieldClass.CRITICO, FieldClass.OBRIGATORIO, FieldClass.OPCIONAL


class _Schema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ------------------------------------------------------------------ Bill of Lading


class ConteinerBL(_Schema):
    numero: Extracted[str] = _campo(CRIT, "Número do contêiner (4 letras + 7 dígitos, ISO 6346)")
    lacre: Extracted[str] = _campo(OPC, "Número do lacre (seal)")
    tipo: Extracted[str] = _campo(OBRIG, "Tipo ISO resumido: 20GP, 40GP, 40HC, 20RF, 40RF...")
    volumes: Extracted[int] = _campo(OBRIG, "Quantidade de volumes no contêiner")
    peso_bruto_kg: Extracted[Decimal] = _campo(OBRIG, "Peso bruto do contêiner em kg")


class BillOfLading(_Schema):
    numero_bl: Extracted[str] = _campo(CRIT, "Número do B/L")
    embarcador: Extracted[str] = _campo(OBRIG, "Shipper (embarcador)")
    consignatario: Extracted[str] = _campo(OBRIG, "Consignee (consignatário)")
    notificar: Extracted[str] = _campo(OPC, "Notify party")
    porto_carregamento: Extracted[str] = _campo(CRIT, "Porto de carregamento em UN/LOCODE")
    porto_descarga: Extracted[str] = _campo(CRIT, "Porto de descarga em UN/LOCODE")
    navio: Extracted[str] = _campo(OBRIG, "Nome do navio")
    viagem: Extracted[str] = _campo(OPC, "Número da viagem")
    data_embarque: Extracted[date] = _campo(CRIT, "Data de embarque (shipped on board)")
    conteineres: list[ConteinerBL] = _campo(CRIT, "Contêineres do B/L (pelo menos um)")
    volumes_total: Extracted[int] = _campo(CRIT, "Total de volumes")
    peso_bruto_total_kg: Extracted[Decimal] = _campo(CRIT, "Peso bruto total em kg")
    cubagem_m3: Extracted[Decimal] = _campo(OPC, "Cubagem total em m³")
    descricao_mercadoria: Extracted[str] = _campo(OBRIG, "Descrição da mercadoria")
    ncm: list[Extracted[str]] = _campo(OPC, "Códigos NCM/HS citados (8 dígitos)")
    frete: Extracted[str] = _campo(OPC, "Condição do frete: PREPAID ou COLLECT")


# ------------------------------------------------------------------ Air Waybill


class AirWaybill(_Schema):
    numero_awb: Extracted[str] = _campo(CRIT, "Número do AWB (3 dígitos da cia + 8 dígitos)")
    embarcador: Extracted[str] = _campo(OBRIG, "Shipper (embarcador)")
    consignatario: Extracted[str] = _campo(OBRIG, "Consignee (consignatário)")
    aeroporto_origem: Extracted[str] = _campo(CRIT, "Aeroporto de origem em código IATA")
    aeroporto_destino: Extracted[str] = _campo(CRIT, "Aeroporto de destino em código IATA")
    voo: Extracted[str] = _campo(OPC, "Número do voo")
    data_voo: Extracted[date] = _campo(OPC, "Data do voo")
    volumes: Extracted[int] = _campo(CRIT, "Quantidade de volumes (pieces)")
    peso_bruto_kg: Extracted[Decimal] = _campo(CRIT, "Peso bruto em kg")
    peso_taxavel_kg: Extracted[Decimal] = _campo(OPC, "Peso taxável (chargeable) em kg")
    descricao_mercadoria: Extracted[str] = _campo(OBRIG, "Descrição da mercadoria")


# ------------------------------------------------------------------ Commercial Invoice


class ItemInvoice(_Schema):
    descricao: Extracted[str] = _campo(OBRIG, "Descrição do item")
    ncm: Extracted[str] = _campo(CRIT, "NCM do item (8 dígitos)")
    quantidade: Extracted[Decimal] = _campo(OBRIG, "Quantidade")
    unidade: Extracted[str] = _campo(OPC, "Unidade (PCS, KG, UN...)")
    valor_unitario: Extracted[Decimal] = _campo(OBRIG, "Valor unitário na moeda da invoice")
    valor_total: Extracted[Decimal] = _campo(CRIT, "Valor total do item na moeda da invoice")


class CommercialInvoice(_Schema):
    numero_invoice: Extracted[str] = _campo(CRIT, "Número da commercial invoice")
    data_emissao: Extracted[date] = _campo(CRIT, "Data de emissão")
    exportador: Extracted[str] = _campo(OBRIG, "Exportador (seller)")
    importador: Extracted[str] = _campo(OBRIG, "Importador (buyer)")
    importador_cnpj: Extracted[str] = _campo(CRIT, "CNPJ do importador")
    incoterm: Extracted[str] = _campo(CRIT, "Incoterm 2020 (EXW, FOB, CFR, CIF, DAP...)")
    moeda: Extracted[str] = _campo(CRIT, "Moeda em ISO 4217 (USD, EUR, CNY...)")
    itens: list[ItemInvoice] = _campo(CRIT, "Itens da invoice (pelo menos um)")
    valor_total: Extracted[Decimal] = _campo(CRIT, "Valor total da invoice")
    pais_origem: Extracted[str] = _campo(OPC, "País de origem da mercadoria")
    frete: Extracted[Decimal] = _campo(OPC, "Valor do frete, se discriminado")
    seguro: Extracted[Decimal] = _campo(OPC, "Valor do seguro, se discriminado")


# ------------------------------------------------------------------ Packing List


class ItemPackingList(_Schema):
    descricao: Extracted[str] = _campo(OBRIG, "Descrição do item")
    quantidade: Extracted[Decimal] = _campo(OBRIG, "Quantidade")
    volumes: Extracted[int] = _campo(OBRIG, "Volumes do item")
    peso_liquido_kg: Extracted[Decimal] = _campo(OBRIG, "Peso líquido do item em kg")
    peso_bruto_kg: Extracted[Decimal] = _campo(OBRIG, "Peso bruto do item em kg")


class PackingList(_Schema):
    numero_packing_list: Extracted[str] = _campo(OBRIG, "Número do packing list")
    numero_invoice: Extracted[str] = _campo(CRIT, "Número da invoice de referência")
    data_emissao: Extracted[date] = _campo(OBRIG, "Data de emissão")
    exportador: Extracted[str] = _campo(OBRIG, "Exportador")
    importador: Extracted[str] = _campo(OBRIG, "Importador")
    volumes_total: Extracted[int] = _campo(CRIT, "Total de volumes")
    peso_bruto_total_kg: Extracted[Decimal] = _campo(CRIT, "Peso bruto total em kg")
    peso_liquido_total_kg: Extracted[Decimal] = _campo(OBRIG, "Peso líquido total em kg")
    cubagem_m3: Extracted[Decimal] = _campo(OPC, "Cubagem total em m³")
    conteineres: list[Extracted[str]] = _campo(OPC, "Números dos contêineres, se citados")
    itens: list[ItemPackingList] = _campo(OBRIG, "Itens embalados")


ExtractedDocument = BillOfLading | AirWaybill | CommercialInvoice | PackingList

DOCUMENT_MODELS: dict[DocumentType, type[_Schema]] = {
    DocumentType.BL: BillOfLading,
    DocumentType.AWB: AirWaybill,
    DocumentType.INVOICE: CommercialInvoice,
    DocumentType.PACKING_LIST: PackingList,
}


def field_class(model: type[BaseModel], name: str) -> FieldClass:
    """Classe (C, O, op) declarada no campo do schema."""
    extra = model.model_fields[name].json_schema_extra
    if not isinstance(extra, dict) or "classe" not in extra:
        raise KeyError(f"{model.__name__}.{name} sem classe de campo")
    return FieldClass(str(extra["classe"]))


def is_list_field(model: type[BaseModel], name: str) -> bool:
    return get_origin(model.model_fields[name].annotation) is list


def empty_template(model: type[BaseModel]) -> dict[str, Any]:
    """Documento com todas as chaves e tudo null: é o formato que o prompt mostra ao modelo."""
    return {
        name: [] if is_list_field(model, name) else {"valor": None, "evidence": None}
        for name in model.model_fields
    }


def parse_llm_json(raw: str) -> dict[str, Any]:
    """Lê a resposta do modelo como objeto JSON, com números em Decimal (nunca float)."""
    match = _FENCE.match(raw)
    text = match.group(1) if match else raw
    try:
        data = json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Resposta do modelo não é JSON válido: {exc.msg}") from None
    if not isinstance(data, dict):
        raise ValueError("Resposta do modelo não é um objeto JSON.")
    return data

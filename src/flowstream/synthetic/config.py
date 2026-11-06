"""Configuração do gerador sintético, lida de config.yaml e validada."""

from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Self, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from flowstream.domain.dates import SAO_PAULO
from flowstream.domain.shipment import Modal

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")

_ONE = Decimal(1)
_TOLERANCE = Decimal("0.0001")


class SyntheticConfigError(ValueError):
    """config.yaml ausente, mal formado ou com valores incoerentes."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Range(_Frozen):
    minimo: Decimal
    maximo: Decimal

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.minimo > self.maximo:
            raise ValueError("minimo maior que maximo")
        return self


class Margin(_Frozen):
    minima: Decimal
    moda: Decimal
    maxima: Decimal


class Demurrage(_Frozen):
    taxa_fcl: Decimal
    taxa_absorvida: Decimal
    dias: Range
    diaria_usd: Range


class SyntheticConfig(_Frozen):
    inicio: date
    meses: int = Field(ge=1, le=60)
    crescimento_anual: Decimal
    vendedores: int = Field(ge=1, le=50)
    clientes: int = Field(ge=1, le=999)  # raiz do CNPJ fictício: 00.000.001 a 00.000.999
    cotacoes: int = Field(ge=1)
    taxa_ganho: Decimal
    proporcao_perdida: Decimal
    proporcao_expirada: Decimal
    proporcao_importacao: Decimal
    modais: dict[Modal, Decimal]
    regioes: dict[str, Decimal]
    sazonalidade: dict[int, Decimal]
    ano_novo_chines: list[date]
    reducao_ano_novo_chines: Decimal
    segmentos: dict[str, Decimal]
    porte: dict[str, Decimal]
    peso_porte: dict[str, int]
    dispersao_cliente: Decimal = Field(ge=0)
    uf: dict[str, Decimal]
    taxa_ganho_vendedor: Range
    motivos_perda: dict[str, Decimal]
    pontualidade_armador: Range
    pontualidade_outros: Decimal
    queda_pontualidade_pico: Decimal
    meses_pico: list[int]
    margem: Margin
    demurrage: Demurrage

    @model_validator(mode="after")
    def _proportions_sum_to_one(self) -> Self:
        blocks: dict[str, dict[Any, Decimal]] = {
            "modais": dict(self.modais),
            "regioes": self.regioes,
            "segmentos": self.segmentos,
            "porte": self.porte,
            "uf": self.uf,
            "motivos_perda": self.motivos_perda,
        }
        for name, shares in blocks.items():
            if abs(sum(shares.values()) - _ONE) > _TOLERANCE:
                raise ValueError(f"as proporções de '{name}' somam {sum(shares.values())}, não 1")
        if set(self.sazonalidade) != set(range(1, 13)):
            raise ValueError("'sazonalidade' precisa ter os meses de 1 a 12")
        if set(self.peso_porte) != set(self.porte):
            raise ValueError("'peso_porte' precisa ter os mesmos portes de 'porte'")
        return self

    def fim(self, meses: int | None = None) -> datetime:
        """Primeiro instante depois do período (exclusivo), no horário de São Paulo."""
        last = add_months(self.inicio, meses or self.meses)
        return datetime.combine(last, time(), SAO_PAULO)

    def inicio_dt(self) -> datetime:
        return datetime.combine(self.inicio, time(), SAO_PAULO)


class _DecimalLoader(yaml.SafeLoader):
    """Lê números com casas decimais como Decimal, nunca float."""


def _decimal(loader: yaml.SafeLoader, node: yaml.Node) -> Decimal:
    return Decimal(str(loader.construct_scalar(node)))  # type: ignore[arg-type]


_DecimalLoader.add_constructor("tag:yaml.org,2002:float", _decimal)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> SyntheticConfig:
    """Lê e valida o config.yaml do gerador."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SyntheticConfigError(f"Arquivo de configuração não encontrado: {path}") from None
    try:
        raw = yaml.load(text, Loader=_DecimalLoader)  # noqa: S506 - SafeLoader + Decimal
    except yaml.YAMLError as exc:
        raise SyntheticConfigError(f"YAML inválido em {path}: {exc}") from None
    try:
        return SyntheticConfig.model_validate(raw)
    except ValidationError as exc:
        raise SyntheticConfigError(f"Configuração inválida em {path}:\n{exc}") from None


D = TypeVar("D", date, datetime)


def add_months(moment: D, months: int) -> D:
    """Soma meses a uma data no dia 1 (o gerador só trabalha com inícios de mês)."""
    if moment.day != 1:
        raise ValueError("add_months espera uma data no dia 1 do mês.")
    years, month_index = divmod(moment.month - 1 + months, 12)
    return moment.replace(year=moment.year + years, month=month_index + 1)

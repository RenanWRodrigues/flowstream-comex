"""Valores monetários: sempre Decimal, nunca float, com arredondamento bancário."""

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator

Currency = Literal["BRL", "USD", "EUR", "CNY"]

CENTS = Decimal("0.01")


class CurrencyMismatchError(ValueError):
    """Operação entre valores de moedas diferentes."""


class Money(BaseModel):
    """Valor em uma moeda ISO 4217. Imutável; soma e subtração só na mesma moeda."""

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: Currency

    @field_validator("amount", mode="before")
    @classmethod
    def _reject_float(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("Use Decimal ou texto para valores monetários, nunca float.")
        return value

    @classmethod
    def zero(cls, currency: Currency) -> Self:
        return cls(amount=Decimal(0), currency=currency)

    def rounded(self) -> Self:
        """Arredonda para centavos pelo método bancário (meio vai para o par)."""
        return self.model_copy(update={"amount": self.amount.quantize(CENTS, ROUND_HALF_EVEN)})

    def convert(self, rate: Decimal, to: Currency) -> "Money":
        """Converte pela taxa (unidades de `to` por unidade desta moeda), em centavos."""
        if not isinstance(rate, Decimal):
            raise TypeError("A taxa de câmbio deve ser Decimal.")
        if rate <= 0:
            raise ValueError("A taxa de câmbio deve ser positiva.")
        if to == self.currency and rate != 1:
            raise ValueError("Conversão para a mesma moeda exige taxa 1.")
        return Money(amount=self.amount * rate, currency=to).rounded()

    def _check_same_currency(self, other: "Money") -> None:
        if other.currency != self.currency:
            raise CurrencyMismatchError(
                f"Moedas diferentes: {self.currency} e {other.currency}. Converta antes."
            )

    def __add__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._check_same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._check_same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __str__(self) -> str:
        return f"{self.currency} {self.rounded().amount}"

"""Testes de Money: Decimal, moedas ISO 4217 e arredondamento bancário."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from flowstream.domain.money import CurrencyMismatchError, Money


def brl(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="BRL")


def usd(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="USD")


# ------------------------------------------------------------------ criação


@pytest.mark.parametrize("currency", ["BRL", "USD", "EUR", "CNY"])
def test_accepts_supported_currencies(currency: str) -> None:
    money = Money(amount=Decimal("10.50"), currency=currency)  # type: ignore[arg-type]

    assert money.currency == currency
    assert money.amount == Decimal("10.50")


@pytest.mark.parametrize("currency", ["GBP", "brl", "R$", ""])
def test_rejects_unsupported_currency(currency: str) -> None:
    with pytest.raises(ValidationError):
        Money(amount=Decimal("1"), currency=currency)  # type: ignore[arg-type]


def test_accepts_amount_as_text_and_int() -> None:
    assert Money(amount="1500.75", currency="USD").amount == Decimal("1500.75")  # type: ignore[arg-type]
    assert Money(amount=1500, currency="USD").amount == Decimal("1500")  # type: ignore[arg-type]


def test_rejects_float_amount() -> None:
    with pytest.raises(ValidationError, match="float"):
        Money(amount=0.1, currency="BRL")  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "abc"])
def test_rejects_non_finite_or_non_numeric_amount(bad: str) -> None:
    with pytest.raises(ValidationError):
        Money(amount=bad, currency="BRL")  # type: ignore[arg-type]


def test_is_immutable() -> None:
    money = brl("10")
    with pytest.raises(ValidationError):
        money.amount = Decimal("20")


def test_equal_values_are_equal_and_hashable() -> None:
    assert brl("10.00") == brl("10.00")
    assert len({brl("10.00"), brl("10.00")}) == 1


# ------------------------------------------------------------------ soma e subtração


def test_adds_same_currency() -> None:
    assert usd("100.10") + usd("0.25") == usd("100.35")


def test_subtracts_same_currency_allowing_negative() -> None:
    assert usd("10.00") - usd("12.50") == usd("-2.50")


def test_adding_different_currencies_fails() -> None:
    with pytest.raises(CurrencyMismatchError, match=r"USD.*BRL"):
        usd("1") + brl("1")


def test_subtracting_different_currencies_fails() -> None:
    with pytest.raises(CurrencyMismatchError):
        usd("1") - brl("1")


def test_adding_non_money_is_not_supported() -> None:
    with pytest.raises(TypeError):
        usd("1") + Decimal("1")  # type: ignore[operator]


def test_subtracting_non_money_is_not_supported() -> None:
    with pytest.raises(TypeError):
        usd("1") - 1  # type: ignore[operator]


def test_sum_of_list_with_start_value() -> None:
    items = [usd("10.10"), usd("20.20"), usd("30.30")]

    assert sum(items, start=Money.zero("USD")) == usd("60.60")


# ------------------------------------------------------------------ arredondamento e conversão


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("2.345", "2.34"),  # meio vai para o par (4)
        ("2.355", "2.36"),  # meio vai para o par (6)
        ("2.3451", "2.35"),  # acima do meio sobe
        ("-2.345", "-2.34"),
        ("10", "10.00"),
    ],
)
def test_rounded_uses_bankers_rounding(amount: str, expected: str) -> None:
    rounded = brl(amount).rounded()

    assert rounded.amount == Decimal(expected)
    assert str(rounded.amount) == expected


def test_convert_multiplies_by_rate_and_rounds() -> None:
    # 1.234,56 USD x PTAX 5,4321 = 6.706,25... BRL
    converted = usd("1234.56").convert(Decimal("5.4321"), "BRL")

    assert converted == brl("6706.25")


def test_convert_uses_bankers_rounding() -> None:
    assert usd("1.00").convert(Decimal("2.345"), "BRL") == brl("2.34")
    assert usd("1.00").convert(Decimal("2.355"), "BRL") == brl("2.36")


def test_convert_to_same_currency_requires_rate_one() -> None:
    assert usd("10.555").convert(Decimal("1"), "USD") == usd("10.56")
    with pytest.raises(ValueError, match="mesma moeda"):
        usd("10").convert(Decimal("2"), "USD")


@pytest.mark.parametrize("rate", [Decimal("0"), Decimal("-5.1")])
def test_convert_rejects_non_positive_rate(rate: Decimal) -> None:
    with pytest.raises(ValueError, match="positiva"):
        usd("10").convert(rate, "BRL")


def test_convert_rejects_float_rate() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        usd("10").convert(5.43, "BRL")  # type: ignore[arg-type]


def test_str_shows_currency_and_two_decimals() -> None:
    assert str(usd("1234.5")) == "USD 1234.50"

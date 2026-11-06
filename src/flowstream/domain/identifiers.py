"""Identificadores do comércio exterior, como tipos Pydantic que validam e normalizam.

Uso:
    class Embarque(BaseModel):
        container: ContainerNumber   # "msku 123456-6" -> erro ou "MSKU1234566"

Regras detalhadas em docs/glossario.md.
"""

import random
import re
import string
from typing import Annotated

from pydantic import BeforeValidator

# ------------------------------------------------------------------ contêiner (ISO 6346)

_CONTAINER = re.compile(r"^[A-Z]{3}[UJZ]\d{7}$")
_CONTAINER_WEIGHTS = [1 << i for i in range(10)]  # 1, 2, 4, ..., 512


def _container_letter_values() -> dict[str, int]:
    """A=10, B=12, ... Z=38: valores sequenciais que pulam os múltiplos de 11."""
    values: dict[str, int] = {}
    value = 10
    for letter in string.ascii_uppercase:
        if value % 11 == 0:
            value += 1
        values[letter] = value
        value += 1
    return values


_LETTER_VALUES = _container_letter_values()


def container_check_digit(prefix: str) -> int:
    """Dígito verificador ISO 6346 para os 10 primeiros caracteres (ex.: 'CSQU305438' -> 3)."""
    if len(prefix) != 10 or not re.fullmatch(r"[A-Z]{4}\d{6}", prefix):
        raise ValueError("O prefixo do contêiner precisa de 10 caracteres: 4 letras e 6 dígitos.")
    total = sum(
        (_LETTER_VALUES[char] if char.isalpha() else int(char)) * weight
        for char, weight in zip(prefix, _CONTAINER_WEIGHTS, strict=True)
    )
    return total % 11 % 10  # resto 10 vira 0


def _normalize_container(value: object) -> str:
    text = _as_text(value, "contêiner")
    number = re.sub(r"[\s\-.]", "", text).upper()
    if not _CONTAINER.match(number):
        raise ValueError(
            "Contêiner inválido: use 3 letras do proprietário, categoria U/J/Z, "
            "6 dígitos de série e o dígito verificador (ex.: MSCU1234566)."
        )
    if container_check_digit(number[:10]) != int(number[10]):
        raise ValueError(f"Dígito verificador do contêiner {number} não confere (ISO 6346).")
    return number


def generate_valid_container(rng: random.Random, owner: str | None = None) -> str:
    """Contêiner fictício com dígito verificador correto. Mesma semente, mesmo número."""
    if owner is None:
        owner = "".join(rng.choices(string.ascii_uppercase, k=3))
    elif not re.fullmatch(r"[A-Z]{3}", owner):
        raise ValueError("O código do proprietário precisa de 3 letras maiúsculas.")
    prefix = f"{owner}U{rng.randrange(1_000_000):06d}"
    return f"{prefix}{container_check_digit(prefix)}"


# ------------------------------------------------------------------ AWB (Air Waybill)

_AWB = re.compile(r"^\d{11}$")


def _normalize_awb(value: object) -> str:
    text = _as_text(value, "AWB")
    digits = re.sub(r"[\s\-.]", "", text)
    if not _AWB.match(digits):
        raise ValueError(
            "AWB inválido: use o prefixo de 3 dígitos da companhia e 8 dígitos (ex.: 020-12345675)."
        )
    serial = digits[3:]
    if int(serial[:7]) % 7 != int(serial[7]):
        raise ValueError(f"Dígito verificador do AWB {digits[:3]}-{serial} não confere (módulo 7).")
    return f"{digits[:3]}-{serial}"


def generate_valid_awb(rng: random.Random, prefix: str | None = None) -> str:
    """AWB fictício com dígito verificador correto, no formato PPP-SSSSSSSS."""
    if prefix is None:
        prefix = f"{rng.randrange(1000):03d}"
    elif not re.fullmatch(r"\d{3}", prefix):
        raise ValueError("O prefixo do AWB precisa de 3 dígitos.")
    base = rng.randrange(10_000_000)
    return f"{prefix}-{base:07d}{base % 7}"


# ------------------------------------------------------------------ NCM

_NCM = re.compile(r"^\d{8}$")


def _normalize_ncm(value: object) -> str:
    text = _as_text(value, "NCM")
    digits = re.sub(r"[\s.]", "", text)
    if not _NCM.match(digits):
        raise ValueError("NCM inválida: use 8 dígitos (ex.: 8471.30.12).")
    chapter = int(digits[:2])
    if not 1 <= chapter <= 97 or chapter == 77:
        raise ValueError(f"NCM inválida: capítulo {digits[:2]} não existe (01 a 97, exceto 77).")
    return digits


def format_ncm(value: str) -> str:
    """'84713012' -> '8471.30.12'."""
    digits = _normalize_ncm(value)
    return f"{digits[:4]}.{digits[4:6]}.{digits[6:]}"


# ------------------------------------------------------------------ CNPJ (numérico e alfanumérico)

_CNPJ = re.compile(r"^[0-9A-Z]{12}\d{2}$")
_CNPJ_WEIGHTS_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_CNPJ_WEIGHTS_2 = [6, *_CNPJ_WEIGHTS_1]


def _cnpj_digit(base: str, weights: list[int]) -> int:
    # Cada caractere vale o código ASCII menos 48: dígitos valem 0-9, letras A=17 ... Z=42.
    remainder = sum((ord(char) - 48) * w for char, w in zip(base, weights, strict=True)) % 11
    return 0 if remainder < 2 else 11 - remainder


def cnpj_check_digits(base: str) -> str:
    """Os 2 dígitos verificadores para as 12 primeiras posições (ex.: '12ABC34501DE' -> '35')."""
    if not re.fullmatch(r"[0-9A-Z]{12}", base):
        raise ValueError("A base do CNPJ precisa de 12 caracteres (dígitos ou letras maiúsculas).")
    first = _cnpj_digit(base, _CNPJ_WEIGHTS_1)
    second = _cnpj_digit(base + str(first), _CNPJ_WEIGHTS_2)
    return f"{first}{second}"


def _normalize_cnpj(value: object) -> str:
    text = _as_text(value, "CNPJ")
    cnpj = re.sub(r"[\s./\-]", "", text).upper()
    if not _CNPJ.match(cnpj):
        raise ValueError("CNPJ inválido: use 14 caracteres (ex.: 00.000.123/0001-22).")
    if len(set(cnpj)) == 1:
        raise ValueError("CNPJ inválido: todos os caracteres iguais.")
    if cnpj[12:] != cnpj_check_digits(cnpj[:12]):
        raise ValueError("CNPJ inválido: dígitos verificadores não conferem.")
    return cnpj


def format_cnpj(value: str) -> str:
    """'00000123000122' -> '00.000.123/0001-22'."""
    c = _normalize_cnpj(value)
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


# ------------------------------------------------------------------ UN/LOCODE e IATA

_UNLOCODE = re.compile(r"^[A-Z]{2}[A-Z2-9]{3}$")
_IATA = re.compile(r"^[A-Z]{3}$")


def _normalize_unlocode(value: object) -> str:
    code = re.sub(r"\s", "", _as_text(value, "UN/LOCODE")).upper()
    if not _UNLOCODE.match(code):
        raise ValueError(
            "UN/LOCODE inválido: 2 letras do país e 3 letras ou dígitos de 2 a 9 (ex.: BRITJ)."
        )
    return code


def _normalize_iata(value: object) -> str:
    code = _as_text(value, "código IATA").strip().upper()
    if not _IATA.match(code):
        raise ValueError("Código IATA inválido: use 3 letras (ex.: GRU).")
    return code


# ------------------------------------------------------------------ comum


def _as_text(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{what} deve ser texto, não {type(value).__name__}.")
    return value.strip()


ContainerNumber = Annotated[str, BeforeValidator(_normalize_container)]
AirWaybill = Annotated[str, BeforeValidator(_normalize_awb)]
NCM = Annotated[str, BeforeValidator(_normalize_ncm)]
CNPJ = Annotated[str, BeforeValidator(_normalize_cnpj)]
UNLocode = Annotated[str, BeforeValidator(_normalize_unlocode)]
IATACode = Annotated[str, BeforeValidator(_normalize_iata)]

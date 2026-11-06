"""Testes dos identificadores do comércio exterior.

Os dígitos verificadores dos exemplos foram calculados por um script independente da
implementação; CSQU3054383 é o exemplo público da ISO 6346 e 12ABC34501DE35 é o exemplo
oficial da Receita Federal para o CNPJ alfanumérico.
"""

import random
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from flowstream.domain.identifiers import (
    CNPJ,
    NCM,
    AirWaybill,
    ContainerNumber,
    IATACode,
    UNLocode,
    cnpj_check_digits,
    container_check_digit,
    format_cnpj,
    format_ncm,
    generate_valid_awb,
    generate_valid_container,
)


def parse(type_: Any, value: object) -> str:
    result: str = TypeAdapter(type_).validate_python(value)
    return result


def assert_invalid(type_: Any, value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(type_).validate_python(value)


# ------------------------------------------------------------------ contêiner (ISO 6346)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CSQU3054383", "CSQU3054383"),  # exemplo da norma
        ("MSCU1234566", "MSCU1234566"),
        ("ATLU0000018", "ATLU0000018"),
        ("TGHU9823413", "TGHU9823413"),
        ("MAEU1234567", "MAEU1234567"),
        ("HLXU8765430", "HLXU8765430"),  # resto 10 vira dígito 0
        ("CZSU2500991", "CZSU2500991"),
        ("OAZJ1002003", "OAZJ1002003"),  # categoria J (equipamento destacável)
        ("czsu2500991", "CZSU2500991"),  # minúsculas
        ("MSCU 123456 6", "MSCU1234566"),
        ("MSCU 123456-6", "MSCU1234566"),
        ("  csqu3054383  ", "CSQU3054383"),
    ],
)
def test_valid_containers_are_normalized(raw: str, expected: str) -> None:
    assert parse(ContainerNumber, raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "CSQU3054384",  # dígito verificador errado
        "MSCU1234565",  # dígito verificador errado
        "CSQX3054383",  # categoria X não existe
        "CSQU305438",  # falta o dígito verificador
        "CSQU30543831",  # dígito a mais
        "CS1U3054383",  # número no código do proprietário
        "CSQU30A4383",  # letra no número de série
        "",
        "CSQU-305438-3-X",
        12345678901,  # não é texto
    ],
)
def test_invalid_containers_are_rejected(raw: object) -> None:
    assert_invalid(ContainerNumber, raw)


def test_container_check_digit_of_known_prefix() -> None:
    assert container_check_digit("CSQU305438") == 3


def test_container_check_digit_rejects_bad_prefix() -> None:
    with pytest.raises(ValueError, match="10 caracteres"):
        container_check_digit("CSQU3054")


def test_generated_containers_are_valid_and_reproducible() -> None:
    first = [generate_valid_container(random.Random(42)) for _ in range(3)]
    second = [generate_valid_container(random.Random(42)) for _ in range(3)]
    many = {generate_valid_container(random.Random(seed)) for seed in range(200)}

    assert first == second
    assert len(many) > 190
    for number in many:
        assert parse(ContainerNumber, number) == number


def test_generated_container_uses_given_owner() -> None:
    number = generate_valid_container(random.Random(1), owner="ATL")

    assert number.startswith("ATLU")
    assert parse(ContainerNumber, number) == number


@pytest.mark.parametrize("owner", ["AT", "AT1", "ATLU", ""])
def test_generated_container_rejects_bad_owner(owner: str) -> None:
    with pytest.raises(ValueError, match="3 letras"):
        generate_valid_container(random.Random(1), owner=owner)


# ------------------------------------------------------------------ AWB (módulo 7)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("020-12345675", "020-12345675"),
        ("02012345675", "020-12345675"),
        ("020 1234 5675", "020-12345675"),
        ("045-76543213", "045-76543213"),
        ("901-00000000", "901-00000000"),
        ("176-55555555", "176-55555555"),
        ("235-99999992", "235-99999992"),
        (" 020-1234 5675 ", "020-12345675"),
        ("020.12345675", "020-12345675"),
        ("999-12345675", "999-12345675"),
    ],
)
def test_valid_awbs_are_normalized(raw: str, expected: str) -> None:
    assert parse(AirWaybill, raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "020-12345676",  # dígito verificador errado
        "020-12345670",
        "020-1234567",  # série com 7 dígitos
        "020-123456756",  # série com 9 dígitos
        "20-12345675",  # prefixo com 2 dígitos
        "02A-12345675",
        "020-1234567X",
        "",
        "AWB",
        2012345675,
    ],
)
def test_invalid_awbs_are_rejected(raw: object) -> None:
    assert_invalid(AirWaybill, raw)


def test_generated_awbs_are_valid_and_reproducible() -> None:
    first = generate_valid_awb(random.Random(7), prefix="045")
    second = generate_valid_awb(random.Random(7), prefix="045")
    many = {generate_valid_awb(random.Random(seed)) for seed in range(200)}

    assert first == second
    assert first.startswith("045-")
    assert len(many) > 190
    for number in many:
        assert parse(AirWaybill, number) == number


@pytest.mark.parametrize("prefix", ["45", "0450", "04A"])
def test_generated_awb_rejects_bad_prefix(prefix: str) -> None:
    with pytest.raises(ValueError, match="3 dígitos"):
        generate_valid_awb(random.Random(1), prefix=prefix)


# ------------------------------------------------------------------ NCM


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8471.30.12", "84713012"),
        ("84713012", "84713012"),
        ("8471 30 12", "84713012"),
        ("0201.30.00", "02013000"),  # carne bovina: zero à esquerda preservado
        ("6907.21.00", "69072100"),  # cerâmica
        ("9403.60.00", "94036000"),  # móveis
        ("3901.10.10", "39011010"),
        ("8708.29.99", "87082999"),
        ("0101.21.00", "01012100"),  # primeiro capítulo
        ("9706.10.00", "97061000"),  # último capítulo
    ],
)
def test_valid_ncms_are_normalized(raw: str, expected: str) -> None:
    assert parse(NCM, raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "8471.30.1",  # 7 dígitos
        "8471.30.123",  # 9 dígitos
        "8471.3A.12",
        "0001.00.00",  # capítulo 00 não existe
        "7701.00.00",  # capítulo 77 reservado no Sistema Harmonizado
        "9801.00.00",  # capítulos 98 e 99 não existem na NCM
        "9901.00.00",
        "",
        "NCM",
        84713012,
    ],
)
def test_invalid_ncms_are_rejected(raw: object) -> None:
    assert_invalid(NCM, raw)


def test_format_ncm_with_dots() -> None:
    assert format_ncm("84713012") == "8471.30.12"


# ------------------------------------------------------------------ CNPJ


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00.000.123/0001-22", "00000123000122"),
        ("00000123000122", "00000123000122"),
        ("00.000.456/0002-32", "00000456000232"),
        ("00000456000232", "00000456000232"),
        ("12.ABC.345/01DE-35", "12ABC34501DE35"),  # alfanumérico (exemplo da Receita)
        ("12abc34501de35", "12ABC34501DE35"),
        ("00.A0B.0C0/0001-48", "00A0B0C0000148"),
        (" 00.000.123/0001-22 ", "00000123000122"),
        ("00 000 123 0001 22", "00000123000122"),
        ("12ABC34501DE35", "12ABC34501DE35"),
    ],
)
def test_valid_cnpjs_are_normalized(raw: str, expected: str) -> None:
    assert parse(CNPJ, raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "00.000.123/0001-23",  # segundo dígito errado
        "00.000.123/0001-12",  # primeiro dígito errado
        "12.ABC.345/01DE-36",
        "12.ABC.345/01DE-3A",  # dígito verificador nunca é letra
        "11.111.111/1111-11",  # todos iguais
        "00000000000000",
        "0000012300012",  # 13 caracteres
        "000001230001222",  # 15 caracteres
        "00.000.123/0001-2!",
        12345678000195,
    ],
)
def test_invalid_cnpjs_are_rejected(raw: object) -> None:
    assert_invalid(CNPJ, raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("00000123000122", "00.000.123/0001-22"), ("12ABC34501DE35", "12.ABC.345/01DE-35")],
)
def test_format_cnpj_with_punctuation(raw: str, expected: str) -> None:
    assert format_cnpj(raw) == expected


# ------------------------------------------------------------------ UN/LOCODE e IATA


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BRITJ", "BRITJ"),
        ("britj", "BRITJ"),
        ("BR ITJ", "BRITJ"),
        ("BRNVT", "BRNVT"),
        ("CNSHA", "CNSHA"),
        ("NLRTM", "NLRTM"),
        ("DEHAM", "DEHAM"),
        ("USMIA", "USMIA"),
        ("ARBUE", "ARBUE"),
        ("GB2LO", "GB2LO"),  # o código de local aceita dígitos de 2 a 9
    ],
)
def test_valid_unlocodes_are_normalized(raw: str, expected: str) -> None:
    assert parse(UNLocode, raw) == expected


@pytest.mark.parametrize(
    "raw", ["BRIT", "BRITJA", "B1ITJ", "BRIT1", "BRIT0", "BR-ITJ", "", "12345", "BRÍTJ", 12345]
)
def test_invalid_unlocodes_are_rejected(raw: object) -> None:
    assert_invalid(UNLocode, raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GRU", "GRU"),
        ("gru", "GRU"),
        (" VCP ", "VCP"),
        ("NVT", "NVT"),
        ("PVG", "PVG"),
        ("FRA", "FRA"),
        ("MIA", "MIA"),
        ("EZE", "EZE"),
        ("SIN", "SIN"),
        ("AMS", "AMS"),
    ],
)
def test_valid_iata_codes_are_normalized(raw: str, expected: str) -> None:
    assert parse(IATACode, raw) == expected


@pytest.mark.parametrize("raw", ["GR", "GRUU", "G1U", "", "123", "GR-", "GRÚ", 123])
def test_invalid_iata_codes_are_rejected(raw: object) -> None:
    assert_invalid(IATACode, raw)


@pytest.mark.parametrize(
    ("base", "digits"),
    [("000001230001", "22"), ("000004560002", "32"), ("12ABC34501DE", "35")],
)
def test_cnpj_check_digits(base: str, digits: str) -> None:
    assert cnpj_check_digits(base) == digits


@pytest.mark.parametrize("base", ["00000123000", "0000012300011", "00000123000!"])
def test_cnpj_check_digits_rejects_bad_base(base: str) -> None:
    with pytest.raises(ValueError, match="12 caracteres"):
        cnpj_check_digits(base)

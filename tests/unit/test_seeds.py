"""Confere os dados de referência (dbt/seeds) com as regras do domínio, sem banco."""

import csv
import random
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import get_args

import pytest
from pydantic import TypeAdapter

from flowstream.domain.identifiers import IATACode, UNLocode, generate_valid_container
from flowstream.domain.money import Currency
from flowstream.domain.shipment import Modal

SEEDS = Path(__file__).resolve().parents[2] / "dbt" / "seeds"

HEADERS = {
    "portos": ["unlocode", "nome", "pais_iso2", "regiao"],
    "aeroportos": ["iata", "nome", "cidade", "pais_iso2"],
    "paises": ["iso2", "nome", "regiao"],
    "moedas": ["codigo", "nome", "simbolo"],
    "segmentos": ["codigo", "nome", "descricao"],
    "armadores": ["codigo", "nome", "prefixo_bic"],
    "cias_aereas": ["prefixo_awb", "nome"],
    "rotas": [
        "codigo",
        "modal",
        "trade_lane",
        "origem",
        "destino",
        "transit_time_medio_dias",
        "transit_time_desvio_dias",
    ],
}

REQUIRED_PORTS = {
    "BRITJ", "BRNVT", "BRIOA", "BRSSZ", "BRPNG", "BRRIG", "CNSHA", "CNNGB", "CNYTN", "SGSIN",
    "DEHAM", "NLRTM", "BEANR", "ESVLC", "USMIA", "USHOU", "ARBUE", "UYMVD", "CLSAI",
}  # fmt: skip


@cache
def rows(name: str) -> tuple[dict[str, str], ...]:
    with (SEEDS / f"{name}.csv").open(encoding="utf-8", newline="") as file:
        return tuple(csv.DictReader(file))


def column(name: str, field: str) -> list[str]:
    return [row[field] for row in rows(name)]


@pytest.mark.parametrize(("name", "header"), HEADERS.items())
def test_seed_exists_with_expected_header(name: str, header: list[str]) -> None:
    with (SEEDS / f"{name}.csv").open(encoding="utf-8", newline="") as file:
        assert next(csv.reader(file)) == header
    assert rows(name), f"{name}.csv está vazio"


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("portos", "unlocode"),
        ("aeroportos", "iata"),
        ("paises", "iso2"),
        ("moedas", "codigo"),
        ("segmentos", "codigo"),
        ("armadores", "codigo"),
        ("armadores", "prefixo_bic"),
        ("cias_aereas", "prefixo_awb"),
        ("rotas", "codigo"),
    ],
)
def test_keys_are_unique_and_filled(name: str, key: str) -> None:
    values = column(name, key)

    assert all(v.strip() for v in values)
    assert len(values) == len(set(values))


def test_ports_are_valid_unlocodes_and_include_required() -> None:
    ports = column("portos", "unlocode")
    adapter = TypeAdapter(UNLocode)

    assert len(ports) >= 30
    assert set(ports) >= REQUIRED_PORTS
    for code in ports:
        assert adapter.validate_python(code) == code
    for row in rows("portos"):
        assert row["unlocode"][:2] == row["pais_iso2"], row["unlocode"]


def test_airports_are_valid_iata_codes() -> None:
    adapter = TypeAdapter(IATACode)

    for code in column("aeroportos", "iata"):
        assert adapter.validate_python(code) == code
    assert {"GRU", "VCP", "NVT"} <= set(column("aeroportos", "iata"))


def test_every_country_reference_exists() -> None:
    countries = set(column("paises", "iso2"))

    assert set(column("portos", "pais_iso2")) <= countries
    assert set(column("aeroportos", "pais_iso2")) <= countries


def test_currencies_match_the_domain() -> None:
    assert set(column("moedas", "codigo")) == set(get_args(Currency))


def test_carriers_generate_valid_containers() -> None:
    for owner in column("armadores", "prefixo_bic"):
        number = generate_valid_container(random.Random(0), owner=owner)
        assert number.startswith(f"{owner}U")


def test_airline_prefixes_have_three_digits() -> None:
    for prefix in column("cias_aereas", "prefixo_awb"):
        assert len(prefix) == 3
        assert prefix.isdigit()


def test_routes_reference_known_places_and_modals() -> None:
    ports = set(column("portos", "unlocode"))
    airports = set(column("aeroportos", "iata"))

    for route in rows("rotas"):
        places = airports if route["modal"] == Modal.AEREO else ports
        assert route["modal"] in set(Modal), route["codigo"]
        assert route["origem"] in places, route["codigo"]
        assert route["destino"] in places, route["codigo"]
        assert route["origem"] != route["destino"], route["codigo"]


def test_routes_have_plausible_transit_times() -> None:
    for route in rows("rotas"):
        mean = Decimal(route["transit_time_medio_dias"])
        spread = Decimal(route["transit_time_desvio_dias"])
        assert Decimal(0) < mean <= Decimal(60), route["codigo"]
        assert Decimal(0) <= spread < mean, route["codigo"]


def test_routes_cover_every_modal_and_both_directions() -> None:
    assert {r["modal"] for r in rows("rotas")} == {m.value for m in Modal}
    origins_br = [r for r in rows("rotas") if r["origem"].startswith("BR")]
    destinations_br = [r for r in rows("rotas") if r["destino"].startswith("BR")]
    assert origins_br, "faltam rotas de exportação"
    assert destinations_br, "faltam rotas de importação"

"""Dados de referência (dbt/seeds) de que o gerador precisa: rotas, armadores e cias. aéreas."""

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from flowstream.domain.shipment import Direction, Modal

DEFAULT_SEEDS_DIR = Path("dbt/seeds")


class SeedDataError(RuntimeError):
    """Arquivo de seed ausente ou incoerente."""


@dataclass(frozen=True)
class Route:
    codigo: str
    modal: Modal
    trade_lane: str
    origem: str
    destino: str
    transit_medio: Decimal
    transit_desvio: Decimal
    direcao: Direction
    regiao_externa: str  # região do lado estrangeiro da rota


@dataclass(frozen=True)
class Carrier:
    codigo: str
    nome: str
    prefixo_bic: str


@dataclass(frozen=True)
class Airline:
    prefixo_awb: str
    nome: str


@dataclass(frozen=True)
class Reference:
    rotas: tuple[Route, ...]
    armadores: tuple[Carrier, ...]
    cias_aereas: tuple[Airline, ...]

    def rota(self, codigo: str) -> Route:
        for route in self.rotas:
            if route.codigo == codigo:
                return route
        raise SeedDataError(f"Rota não encontrada: {codigo}")

    def rotas_de(self, modal: Modal, direcao: Direction) -> list[Route]:
        return [r for r in self.rotas if r.modal == modal and r.direcao == direcao]


def load_reference(seeds_dir: Path = DEFAULT_SEEDS_DIR) -> Reference:
    """Lê os CSVs de dbt/seeds e monta as rotas com direção e região."""
    countries = {row["iso2"]: row["regiao"] for row in _read(seeds_dir, "paises")}
    places: dict[str, tuple[str, str]] = {}  # código -> (país, região)
    for row in _read(seeds_dir, "portos"):
        places[row["unlocode"]] = (row["pais_iso2"], row["regiao"])
    for row in _read(seeds_dir, "aeroportos"):
        places[row["iata"]] = (row["pais_iso2"], countries[row["pais_iso2"]])

    routes = []
    for row in _read(seeds_dir, "rotas"):
        origin_country, origin_region = places[row["origem"]]
        _, destination_region = places[row["destino"]]
        exporting = origin_country == "BR"
        routes.append(
            Route(
                codigo=row["codigo"],
                modal=Modal(row["modal"]),
                trade_lane=row["trade_lane"],
                origem=row["origem"],
                destino=row["destino"],
                transit_medio=Decimal(row["transit_time_medio_dias"]),
                transit_desvio=Decimal(row["transit_time_desvio_dias"]),
                direcao=Direction.EXPORTACAO if exporting else Direction.IMPORTACAO,
                regiao_externa=destination_region if exporting else origin_region,
            )
        )
    carriers = tuple(
        Carrier(r["codigo"], r["nome"], r["prefixo_bic"]) for r in _read(seeds_dir, "armadores")
    )
    airlines = tuple(Airline(r["prefixo_awb"], r["nome"]) for r in _read(seeds_dir, "cias_aereas"))
    return Reference(rotas=tuple(routes), armadores=carriers, cias_aereas=airlines)


def _read(seeds_dir: Path, name: str) -> list[dict[str, str]]:
    path = seeds_dir / f"{name}.csv"
    try:
        with path.open(encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))
    except FileNotFoundError:
        raise SeedDataError(f"Seed não encontrado: {path} ({name}.csv)") from None

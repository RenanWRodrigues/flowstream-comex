"""Testes da leitura dos dados de referência (dbt/seeds) usados pelo gerador."""

from decimal import Decimal
from pathlib import Path

import pytest

from flowstream.domain.shipment import Direction, Modal
from flowstream.synthetic.reference import SeedDataError, load_reference

SEEDS = Path(__file__).resolve().parents[3] / "dbt" / "seeds"


def test_loads_routes_carriers_and_airlines() -> None:
    ref = load_reference(SEEDS)

    assert len(ref.armadores) == 8
    assert len(ref.cias_aereas) == 6
    route = ref.rota("FCL-CNSHA-BRITJ")
    assert route.modal == Modal.FCL
    assert route.direcao == Direction.IMPORTACAO
    assert route.regiao_externa == "ASIA"
    assert route.transit_medio == Decimal(35)


def test_export_route_uses_destination_region() -> None:
    route = load_reference(SEEDS).rota("FCL-BRITJ-DEHAM")

    assert route.direcao == Direction.EXPORTACAO
    assert route.regiao_externa == "EUROPA"


def test_air_route_region_comes_from_airport_country() -> None:
    assert load_reference(SEEDS).rota("AEREO-PVG-GRU").regiao_externa == "ASIA"


def test_routes_by_modal_and_direction() -> None:
    ref = load_reference(SEEDS)

    routes = ref.rotas_de(Modal.PROJETO, Direction.IMPORTACAO)

    assert routes
    assert all(r.modal == Modal.PROJETO for r in routes)
    assert ref.rotas_de(Modal.PROJETO, Direction.EXPORTACAO) == []


def test_missing_seed_file_has_clear_error(tmp_path: Path) -> None:
    with pytest.raises(SeedDataError, match=r"Seed não encontrado: .*.csv"):
        load_reference(tmp_path)

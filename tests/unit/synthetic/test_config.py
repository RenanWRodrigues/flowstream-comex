"""Testes da configuração do gerador sintético."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from flowstream.synthetic.config import SyntheticConfigError, add_months, load_config


def test_default_config_matches_the_approved_plan() -> None:
    config = load_config()

    assert config.inicio == date(2024, 11, 1)
    assert config.meses == 24
    assert (config.clientes, config.vendedores, config.cotacoes) == (300, 8, 6000)
    assert config.taxa_ganho == Decimal("0.30")
    assert config.modais["FCL"] == Decimal("0.45")
    assert config.demurrage.taxa_fcl == Decimal("0.08")
    assert config.demurrage.taxa_absorvida == Decimal("0.30")


def test_period_end_is_first_instant_after_the_last_month() -> None:
    config = load_config()

    end = config.fim(meses=24)

    assert end.isoformat() == "2026-11-01T00:00:00-03:00"
    assert config.fim(meses=1).date() == date(2024, 12, 1)


def test_rejects_proportions_that_do_not_sum_to_one(tmp_path: Path) -> None:
    text = load_config_text().replace("FCL: 0.45", "FCL: 0.55")
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(SyntheticConfigError, match="modais"):
        load_config(path)


def test_rejects_unknown_modal(tmp_path: Path) -> None:
    text = load_config_text().replace("PROJETO: 0.02", "NAVIO: 0.02")
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(SyntheticConfigError):
        load_config(path)


def test_missing_file_has_clear_error(tmp_path: Path) -> None:
    with pytest.raises(SyntheticConfigError, match="não encontrado"):
        load_config(tmp_path / "nao_existe.yaml")


def test_invalid_yaml_has_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("clientes: [300\n", encoding="utf-8")

    with pytest.raises(SyntheticConfigError, match="YAML"):
        load_config(path)


def load_config_text() -> str:
    from flowstream.synthetic.config import DEFAULT_CONFIG_PATH

    return DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [(date(2024, 11, 1), 0, date(2024, 11, 1)), (date(2024, 11, 1), 2, date(2025, 1, 1)),
     (date(2024, 1, 1), 24, date(2026, 1, 1)), (date(2024, 12, 1), 1, date(2025, 1, 1))],
)  # fmt: skip
def test_add_months(start: date, months: int, expected: date) -> None:
    assert add_months(start, months) == expected


def test_add_months_requires_first_day_of_month() -> None:
    with pytest.raises(ValueError, match="dia 1"):
        add_months(date(2024, 11, 15), 1)

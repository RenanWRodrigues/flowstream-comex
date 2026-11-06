"""Testes do serviço que gera, grava e carrega os dados sintéticos (sem banco)."""

from pathlib import Path

import pytest

from flowstream.synthetic.csv_io import TABLES, dataset_hash
from flowstream.synthetic.service import (
    SyntheticDataError,
    generate_synthetic,
    load_synthetic,
)

SEEDS = Path(__file__).resolve().parents[3] / "dbt" / "seeds"


class FakeLoader:
    def __init__(self) -> None:
        self.directories: list[Path] = []

    def load(self, directory: Path) -> dict[str, int]:
        self.directories.append(directory)
        return dict.fromkeys(TABLES, 1)


def test_generate_writes_csvs_and_reports(tmp_path: Path) -> None:
    result = generate_synthetic(seed=5, months=2, out_dir=tmp_path, seeds_dir=SEEDS)

    assert result.out_dir == tmp_path
    assert set(result.counts) == set(TABLES)
    assert result.counts["embarques"] > 0
    assert result.hash == dataset_hash(tmp_path)
    assert result.seconds >= 0
    for table in TABLES:
        assert (tmp_path / f"{table}.csv").is_file()


def test_load_passes_directory_to_loader(tmp_path: Path) -> None:
    generate_synthetic(seed=5, months=1, out_dir=tmp_path, seeds_dir=SEEDS)
    loader = FakeLoader()

    counts = load_synthetic(tmp_path, loader=loader)

    assert loader.directories == [tmp_path]
    assert counts == dict.fromkeys(TABLES, 1)


def test_load_refuses_incomplete_directory(tmp_path: Path) -> None:
    (tmp_path / "clientes.csv").write_text("cliente_id\n", encoding="utf-8")

    with pytest.raises(SyntheticDataError, match="synthetic generate"):
        load_synthetic(tmp_path, loader=FakeLoader())

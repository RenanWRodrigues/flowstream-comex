"""Testes da gravação dos CSVs e do hash de reprodutibilidade."""

import csv
from pathlib import Path

import pytest

from flowstream.synthetic.config import load_config
from flowstream.synthetic.csv_io import TABLES, dataset_hash, write_dataset
from flowstream.synthetic.generator import Dataset, generate
from flowstream.synthetic.reference import load_reference

SEEDS = Path(__file__).resolve().parents[3] / "dbt" / "seeds"


@pytest.fixture(scope="module")
def small() -> Dataset:
    return generate(load_config(), load_reference(SEEDS), seed=3, months=3)


def test_writes_one_csv_per_table_with_header(small: Dataset, tmp_path: Path) -> None:
    paths = write_dataset(small, tmp_path)

    assert set(paths) == set(TABLES)
    for table, path in paths.items():
        with path.open(encoding="utf-8", newline="") as file:
            header = next(csv.reader(file))
        assert header == list(TABLES[table].model_fields), table


def test_row_counts_match_the_dataset(small: Dataset, tmp_path: Path) -> None:
    paths = write_dataset(small, tmp_path)

    with paths["embarques"].open(encoding="utf-8", newline="") as file:
        assert sum(1 for _ in csv.DictReader(file)) == len(small.embarques)


def test_values_are_serialized_for_postgres(small: Dataset, tmp_path: Path) -> None:
    paths = write_dataset(small, tmp_path)

    with paths["embarques"].open(encoding="utf-8", newline="") as file:
        row = next(csv.DictReader(file))
    assert row["modal"] in {"FCL", "LCL", "AEREO", "RODOVIARIO", "ISOTANQUE", "PROJETO"}
    assert row["etd"].endswith("-03:00")  # data com fuso
    assert "." in row["peso_kg"] or row["peso_kg"].isdigit()  # Decimal, sem notação científica


def test_none_becomes_empty_field(small: Dataset, tmp_path: Path) -> None:
    paths = write_dataset(small, tmp_path)

    with paths["embarques"].open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert any(r["awb"] == "" for r in rows)


def test_same_dataset_same_hash(small: Dataset, tmp_path: Path) -> None:
    write_dataset(small, tmp_path / "a")
    write_dataset(small, tmp_path / "b")

    assert dataset_hash(tmp_path / "a") == dataset_hash(tmp_path / "b")


def test_regenerating_with_same_seed_gives_same_hash(tmp_path: Path) -> None:
    for name in ("a", "b"):
        data = generate(load_config(), load_reference(SEEDS), seed=11, months=2)
        write_dataset(data, tmp_path / name)

    assert dataset_hash(tmp_path / "a") == dataset_hash(tmp_path / "b")


def test_different_seed_different_hash(tmp_path: Path) -> None:
    write_dataset(generate(load_config(), load_reference(SEEDS), seed=1, months=2), tmp_path / "a")
    write_dataset(generate(load_config(), load_reference(SEEDS), seed=2, months=2), tmp_path / "b")

    assert dataset_hash(tmp_path / "a") != dataset_hash(tmp_path / "b")


def test_hash_fails_when_a_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        dataset_hash(tmp_path)

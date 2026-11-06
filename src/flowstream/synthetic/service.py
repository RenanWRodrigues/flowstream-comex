"""Casos de uso: gerar os CSVs sintéticos e carregá-los no bronze."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from flowstream.logging import get_logger
from flowstream.synthetic.config import DEFAULT_CONFIG_PATH, load_config
from flowstream.synthetic.csv_io import TABLES, dataset_hash, rows_of, write_dataset
from flowstream.synthetic.generator import generate
from flowstream.synthetic.reference import DEFAULT_SEEDS_DIR, load_reference

DEFAULT_OUT_DIR = Path("data/synthetic")

logger = get_logger(__name__)


class SyntheticDataError(RuntimeError):
    """Pasta de CSVs sintéticos ausente ou incompleta."""


class SyntheticLoader(Protocol):
    def load(self, directory: Path) -> dict[str, int]: ...


@dataclass(frozen=True)
class GenerationResult:
    out_dir: Path
    counts: dict[str, int]
    hash: str
    seconds: float


def generate_synthetic(
    seed: int,
    months: int | None = None,
    out_dir: Path = DEFAULT_OUT_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
    seeds_dir: Path = DEFAULT_SEEDS_DIR,
) -> GenerationResult:
    """Gera a operação fictícia e grava um CSV por tabela em `out_dir`."""
    started = time.perf_counter()
    dataset = generate(load_config(config_path), load_reference(seeds_dir), seed, months)
    write_dataset(dataset, out_dir)
    counts = {table: len(rows_of(dataset, table)) for table in TABLES}
    seconds = time.perf_counter() - started
    logger.info("dados sintéticos gerados (semente %s) em %.1f s", seed, seconds)
    return GenerationResult(out_dir, counts, dataset_hash(out_dir), seconds)


def load_synthetic(directory: Path, loader: SyntheticLoader | None = None) -> dict[str, int]:
    """Carrega os CSVs de `directory` no bronze, substituindo a carga anterior."""
    missing = [t for t in TABLES if not (directory / f"{t}.csv").is_file()]
    if missing:
        raise SyntheticDataError(
            f"Faltam CSVs em {directory}: {', '.join(missing)}. "
            "Rode antes: flowstream synthetic generate"
        )
    if loader is None:
        from flowstream.db import create_db_engine
        from flowstream.synthetic.adapters import PostgresSyntheticLoader

        loader = PostgresSyntheticLoader(create_db_engine())
    return loader.load(directory)

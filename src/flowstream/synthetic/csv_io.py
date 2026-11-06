"""Grava o conjunto gerado em CSVs (um por tabela do bronze) e calcula o hash dos arquivos."""

import csv
import hashlib
from pathlib import Path

from pydantic import BaseModel

from flowstream.synthetic.generator import Dataset
from flowstream.synthetic.models import (
    Customer,
    Equipment,
    FinancialItem,
    Quote,
    Seller,
    Shipment,
    TrackingEvent,
)

# Tabela do bronze -> (modelo, atributo do Dataset). Ordem = ordem de carga (dependências).
TABLES: dict[str, type[BaseModel]] = {
    "vendedores": Seller,
    "clientes": Customer,
    "cotacoes": Quote,
    "embarques": Shipment,
    "equipamentos": Equipment,
    "itens_financeiros": FinancialItem,
    "tracking_eventos": TrackingEvent,
}
_ATTRIBUTES = {"tracking_eventos": "tracking"}


def rows_of(dataset: Dataset, table: str) -> list[BaseModel]:
    rows: list[BaseModel] = getattr(dataset, _ATTRIBUTES.get(table, table))
    return rows


def write_dataset(dataset: Dataset, out_dir: Path) -> dict[str, Path]:
    """Grava <tabela>.csv em UTF-8, com cabeçalho; None vira campo vazio (NULL no COPY)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for table, model in TABLES.items():
        path = out_dir / f"{table}.csv"
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file, lineterminator="\n")
            writer.writerow(model.model_fields)
            for row in rows_of(dataset, table):
                values = row.model_dump(mode="json").values()
                writer.writerow("" if v is None else v for v in values)
        paths[table] = path
    return paths


def dataset_hash(directory: Path) -> str:
    """SHA-256 de todos os CSVs, em ordem fixa: mesma semente, mesmo hash."""
    digest = hashlib.sha256()
    for table in TABLES:
        digest.update(table.encode())
        digest.update((directory / f"{table}.csv").read_bytes())
    return digest.hexdigest()

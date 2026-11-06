"""Testes do loader sintético que não precisam de banco."""

from typing import Any

import pytest

from flowstream.synthetic.adapters import PostgresSyntheticLoader

ENGINE: Any = object()  # o construtor não usa o engine; só guarda


def test_default_schema_is_bronze() -> None:
    assert PostgresSyntheticLoader(ENGINE).schema == "bronze"


@pytest.mark.parametrize("name", ["bronze_teste", "staging2", "b"])
def test_accepts_plain_schema_names(name: str) -> None:
    assert PostgresSyntheticLoader(ENGINE, schema=name).schema == name


@pytest.mark.parametrize("name", ["bronze; drop table x", "Bronze", "1bronze", "", "bronze.x"])
def test_rejects_unsafe_schema_names(name: str) -> None:
    # O schema entra no SQL como identificador: só nomes simples, nunca texto livre.
    with pytest.raises(ValueError, match="schema"):
        PostgresSyntheticLoader(ENGINE, schema=name)

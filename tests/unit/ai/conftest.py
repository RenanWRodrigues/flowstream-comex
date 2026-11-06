"""Fixtures do agente de IA: PDFs fictícios e o gabarito (tests/fixtures/documentos)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

DOCS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "documentos"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CATALOG = _load("fixtures_documentos", DOCS_DIR / "generate.py")
BUILDERS = _load("ai_builders", Path(__file__).with_name("builders.py"))


@pytest.fixture(scope="session")
def builders() -> ModuleType:
    """Documentos extraídos corretos dos PDFs fictícios (tests/unit/ai/builders.py)."""
    return BUILDERS


@pytest.fixture(scope="session")
def docs_dir() -> Path:
    return DOCS_DIR


@pytest.fixture(scope="session")
def catalog() -> ModuleType:
    return CATALOG


def page_text(lines: list[str]) -> str:
    return "\n".join(lines)

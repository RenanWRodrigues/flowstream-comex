"""Limpeza do JSON exportado pelo n8n antes de ir para n8n/flows/."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from flowstream.cli import app
from flowstream.n8n_export import N8nExportError, clean_workflow

runner = CliRunner()


def _exported() -> dict[str, Any]:
    return {
        "id": "G5EBglEnE4vPMZpr",
        "name": "documento_recebido",
        "active": True,
        "nodes": [
            {
                "name": "Abrir execução",
                "type": "n8n-nodes-base.postgres",
                "parameters": {"query": "select 1"},
                "credentials": {
                    "postgres": {"id": "Xyz123", "name": "FlowStream - Postgres (app)"}
                },
            },
            {"name": "Normalizar aviso", "type": "n8n-nodes-base.set", "parameters": {}},
        ],
        "connections": {"Normalizar aviso": {"main": [[{"node": "Abrir execução"}]]}},
        "settings": {"executionOrder": "v1", "availableInMCP": True, "errorWorkflow": "G5EB"},
        "pinData": {"Abrir execução": [{"json": {"id": "42"}}]},
        "meta": {"instanceId": "abc"},
        "versionId": "v-1",
        "activeVersionId": "v-1",
        "shared": [{"role": "workflow:owner"}],
        "createdAt": "2026-11-04T16:00:00.000Z",
        "updatedAt": "2026-11-04T16:30:00.000Z",
        "triggerCount": 1,
    }


def test_clean_keeps_only_the_portable_fields() -> None:
    cleaned = clean_workflow(_exported())
    assert set(cleaned) == {"id", "name", "nodes", "connections", "settings"}
    assert cleaned["connections"] == _exported()["connections"]


def test_clean_keeps_only_the_credential_name() -> None:
    cleaned = clean_workflow(_exported())
    assert cleaned["nodes"][0]["credentials"] == {
        "postgres": {"name": "FlowStream - Postgres (app)"}
    }
    assert "credentials" not in cleaned["nodes"][1]


def test_clean_accepts_the_list_written_by_the_n8n_cli() -> None:
    assert clean_workflow([_exported()])["name"] == "documento_recebido"


@pytest.mark.parametrize("bad", [[], [_exported(), _exported()], {"name": "sem nós"}, "texto"])
def test_clean_rejects_anything_but_one_workflow(bad: object) -> None:
    with pytest.raises(N8nExportError):
        clean_workflow(bad)


def test_cli_writes_the_clean_file(tmp_path: Path) -> None:
    source = tmp_path / "export.json"
    source.write_text(json.dumps([_exported()]), encoding="utf-8")
    target = tmp_path / "flows" / "documento_recebido.json"

    result = runner.invoke(app, ["n8n", "clean-export", str(source), str(target)])

    assert result.exit_code == 0, result.output
    written = json.loads(target.read_text(encoding="utf-8"))
    assert "pinData" not in written
    assert target.read_text(encoding="utf-8").endswith("}\n")


def test_cli_reports_invalid_json(tmp_path: Path) -> None:
    source = tmp_path / "export.json"
    source.write_text("{quebrado", encoding="utf-8")

    result = runner.invoke(app, ["n8n", "clean-export", str(source), str(tmp_path / "x.json")])

    assert result.exit_code == 1
    assert "JSON" in result.output


def test_clean_keeps_only_portable_settings() -> None:
    """Revisão P09 #12: availableInMCP e errorWorkflow (id) são da instância."""
    assert clean_workflow(_exported())["settings"] == {"executionOrder": "v1"}


@pytest.mark.parametrize(
    "bad_node",
    [
        "não é um nó",
        {"name": "x", "credentials": {"postgres": {"id": "1"}}},  # sem nome
        {"name": "x", "credentials": {"postgres": "FlowStream"}},
    ],
)
def test_clean_rejects_malformed_nodes(bad_node: object) -> None:
    exported = _exported()
    exported["nodes"].append(bad_node)
    with pytest.raises(N8nExportError):
        clean_workflow(exported)

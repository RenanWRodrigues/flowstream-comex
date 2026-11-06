"""Fluxos exportados do n8n: sem segredos, SQL igual ao de n8n/sql e regras da skill n8n-flow."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
FLOWS_DIR = ROOT / "n8n" / "flows"
SQL_DIR = ROOT / "n8n" / "sql"
FLOWS = sorted(FLOWS_DIR.glob("*.json"))

# Chaves que só existem numa instância (ou guardam dados de teste) e não vão para o git.
_INSTANCE_KEYS = {"pinData", "shared", "meta", "versionId", "activeVersionId", "triggerCount"}
_SECRET_HINTS = re.compile(r"(bearer\s+[a-z0-9._-]{12,}|eyJ[a-zA-Z0-9_-]{10,}|password)", re.I)


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _nodes_of(flow: dict[str, Any], node_type: str) -> list[dict[str, Any]]:
    return [n for n in flow["nodes"] if n["type"] == node_type]


def test_there_is_at_least_the_document_flow() -> None:
    assert FLOWS_DIR / "documento_recebido.json" in FLOWS


@pytest.mark.parametrize("path", FLOWS, ids=lambda p: p.stem)
def test_flow_has_no_credential_ids_or_instance_data(path: Path) -> None:
    flow = _load(path)
    assert _INSTANCE_KEYS.isdisjoint(flow), "remova dados da instância (veja docs/n8n.md)"
    for node in flow["nodes"]:
        for reference in node.get("credentials", {}).values():
            assert set(reference) == {"name"}, f"{node['name']}: deixe só o nome da credencial"


@pytest.mark.parametrize("path", FLOWS, ids=lambda p: p.stem)
def test_flow_has_no_secrets(path: Path) -> None:
    assert not _SECRET_HINTS.search(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", FLOWS, ids=lambda p: p.stem)
def test_flow_alerts_on_error(path: Path) -> None:
    flow = _load(path)
    [error_trigger] = _nodes_of(flow, "n8n-nodes-base.errorTrigger")
    targets = flow["connections"][error_trigger["name"]]["main"][0]
    target_types = {n["type"] for n in flow["nodes"] if n["name"] in {t["node"] for t in targets}}
    assert "n8n-nodes-base.telegram" in target_types


@pytest.mark.parametrize("path", FLOWS, ids=lambda p: p.stem)
def test_every_sql_query_comes_from_n8n_sql(path: Path) -> None:
    known = {f.read_text(encoding="utf-8").strip() for f in SQL_DIR.glob("*.sql")}
    for node in _nodes_of(_load(path), "n8n-nodes-base.postgres"):
        query = node["parameters"]["query"].strip()
        assert query in known, f"{node['name']}: copie a consulta de n8n/sql/ sem alterar"


@pytest.mark.parametrize("path", FLOWS, ids=lambda p: p.stem)
def test_flow_records_start_and_end_in_pipeline_runs(path: Path) -> None:
    queries = [n["parameters"]["query"] for n in _nodes_of(_load(path), "n8n-nodes-base.postgres")]
    assert any("insert into ops.pipeline_runs" in q for q in queries)
    assert any("update ops.pipeline_runs" in q for q in queries)


def test_document_flow_calls_the_api_with_a_credential() -> None:
    flow = _load(FLOWS_DIR / "documento_recebido.json")
    [webhook] = _nodes_of(flow, "n8n-nodes-base.webhook")
    assert webhook["parameters"]["path"] == "documento-recebido"
    assert webhook["parameters"]["authentication"] == "headerAuth"
    # Revisão P09 #3: só responde depois de gravar em ops.pipeline_runs; falha antes = 5xx
    # para o watcher, que tenta de novo e registra ERRO.
    assert webhook["parameters"]["responseMode"] == "responseNode"
    [respond] = _nodes_of(flow, "n8n-nodes-base.respondToWebhook")
    [open_run] = [
        n
        for n in _nodes_of(flow, "n8n-nodes-base.postgres")
        if "insert into ops.pipeline_runs" in n["parameters"]["query"]
    ]
    assert flow["connections"][open_run["name"]]["main"][0][0]["node"] == respond["name"]
    [api_call] = _nodes_of(flow, "n8n-nodes-base.httpRequest")
    assert api_call["parameters"]["url"].endswith("/v1/documentos")
    assert "httpHeaderAuth" in api_call["credentials"]
    assert "headerParameters" not in api_call["parameters"]  # chave nunca no JSON

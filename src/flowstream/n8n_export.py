"""Limpa o JSON exportado pelo n8n para versionar em n8n/flows/ (sem ids de credenciais
nem dados da instância, como pinData de testes)."""

from typing import Any

# Campos que valem em qualquer instalação; o resto (pinData, meta, versionId, shared,
# datas, active...) é da instância e pode carregar dados de teste.
PORTABLE_KEYS = ("id", "name", "nodes", "connections", "settings")
# Configurações do fluxo que não dependem da instância. Ficam de fora, por exemplo,
# `availableInMCP` (preferência local) e `errorWorkflow` (id de outro fluxo da instância).
PORTABLE_SETTINGS = (
    "executionOrder",
    "timezone",
    "executionTimeout",
    "saveDataErrorExecution",
    "saveDataSuccessExecution",
    "saveManualExecutions",
    "saveExecutionProgress",
)


class N8nExportError(ValueError):
    """O arquivo não é a exportação de exatamente um fluxo do n8n."""


def clean_workflow(exported: object) -> dict[str, Any]:
    """Devolve só os campos portáveis; credenciais ficam referenciadas apenas pelo nome."""
    workflow = _single_workflow(exported)
    cleaned = {key: workflow[key] for key in PORTABLE_KEYS if key in workflow}
    cleaned["nodes"] = [_clean_node(node) for node in workflow["nodes"]]
    if isinstance(workflow.get("settings"), dict):
        settings = workflow["settings"]
        cleaned["settings"] = {k: settings[k] for k in PORTABLE_SETTINGS if k in settings}
    return cleaned


def _single_workflow(exported: object) -> dict[str, Any]:
    if isinstance(exported, list):
        if len(exported) != 1:
            raise N8nExportError(f"Exporte um fluxo por vez (o arquivo tem {len(exported)}).")
        exported = exported[0]
    if not isinstance(exported, dict) or not isinstance(exported.get("nodes"), list):
        raise N8nExportError("O arquivo não parece uma exportação de fluxo do n8n.")
    return exported


def _clean_node(node: object) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise N8nExportError("Nó inválido na exportação: esperava um objeto JSON.")
    if "credentials" not in node:
        return node
    credentials: dict[str, dict[str, str]] = {}
    for kind, reference in node["credentials"].items():
        if not isinstance(reference, dict) or not isinstance(reference.get("name"), str):
            raise N8nExportError(f"{node.get('name', '?')}: credencial {kind!r} sem nome.")
        credentials[kind] = {"name": reference["name"]}
    return {**node, "credentials": credentials}

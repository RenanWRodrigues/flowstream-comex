"""Fixtures compartilhadas por todos os testes."""

from collections.abc import Iterator

import pytest

PROJECT_ENV_VARS = (
    "DATABASE_URL",
    "OLLAMA_URL",
    "OLLAMA_MODEL",
    "N8N_WEBHOOK_URL",
    "N8N_WEBHOOK_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "INBOX_DIR",
    "PROCESSED_DIR",
    "LOG_LEVEL",
    "API_KEY",
    "TESSERACT_CMD",
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Garante que nenhum teste dependa das variáveis de ambiente da máquina."""
    for name in PROJECT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield

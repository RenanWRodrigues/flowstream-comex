"""Testes da configuração por variáveis de ambiente."""

from pathlib import Path

import pytest

from flowstream.config import ConfigError, Settings, get_settings, load_settings

DB_URL = "postgresql+psycopg://flowstream:senha-ficticia@localhost:5432/flowstream"


def test_reads_all_variables_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("OLLAMA_URL", "http://ollama.local:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:1.5b")
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://n8n.local:5678/webhook/doc")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:token-ficticio")
    monkeypatch.setenv("INBOX_DIR", "dados/inbox-teste")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = load_settings(env_file=None)

    assert settings.database_url.get_secret_value() == DB_URL
    assert settings.ollama_url == "http://ollama.local:11434"
    assert settings.ollama_model == "qwen2.5:1.5b"
    assert settings.n8n_webhook_url == "http://n8n.local:5678/webhook/doc"
    assert settings.telegram_bot_token is not None
    assert settings.telegram_bot_token.get_secret_value() == "123:token-ficticio"
    assert settings.inbox_dir == Path("dados/inbox-teste")
    assert settings.log_level == "DEBUG"


def test_optional_variables_have_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)

    settings = load_settings(env_file=None)

    assert settings.ollama_url == "http://127.0.0.1:11434"
    assert settings.n8n_webhook_url == "http://127.0.0.1:5678/webhook/documento-recebido"
    assert settings.ollama_model == "qwen2.5:3b"
    assert settings.telegram_bot_token is None
    assert settings.inbox_dir == Path("data/inbox")
    assert settings.log_level == "INFO"


def test_empty_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("LOG_LEVEL", "")

    settings = load_settings(env_file=None)

    assert settings.telegram_bot_token is None
    assert settings.log_level == "INFO"


def test_missing_database_url_raises_clear_error() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_settings(env_file=None)

    message = str(excinfo.value)
    assert "DATABASE_URL" in message
    assert ".env.example" in message


def test_invalid_log_level_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("LOG_LEVEL", "VERBOSO")

    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        load_settings(env_file=None)


def test_reads_values_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={DB_URL}\nOLLAMA_MODEL=modelo-do-arquivo\n")

    settings = load_settings(env_file=env_file)

    assert settings.database_url.get_secret_value() == DB_URL
    assert settings.ollama_model == "modelo-do-arquivo"


def test_secrets_are_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:token-ficticio")

    text = repr(load_settings(env_file=None))

    assert "senha-ficticia" not in text
    assert "token-ficticio" not in text


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # sem .env real por perto
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert isinstance(first, Settings)
    assert first is second
    get_settings.cache_clear()


def test_tesseract_cmd_is_optional_and_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:5433/db")
    assert load_settings(env_file=None).tesseract_cmd is None
    exe = "C:/Program Files/Tesseract-OCR/tesseract.exe"
    monkeypatch.setenv("TESSERACT_CMD", exe)
    assert load_settings(env_file=None).tesseract_cmd == exe

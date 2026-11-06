"""Configuração do FlowStream-Comex, lida só de variáveis de ambiente (ou do arquivo .env)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

DEFAULT_ENV_FILE = Path(".env")


class ConfigError(RuntimeError):
    """Configuração ausente ou inválida, com mensagem pronta para o usuário."""


class Settings(BaseSettings):
    """Variáveis de ambiente do projeto. Segredos ficam em SecretStr para não vazar em logs."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,  # VAR= vazia vale o padrão (ex.: TELEGRAM_BOT_TOKEN opcional)
    )

    database_url: SecretStr
    # 127.0.0.1 em vez de localhost: no Windows, localhost tenta ::1 (IPv6) primeiro e os
    # serviços locais do projeto só escutam em IPv4, o que custa segundos por conexão.
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    n8n_webhook_url: str = "http://127.0.0.1:5678/webhook/documento-recebido"
    n8n_webhook_token: SecretStr | None = None  # header X-Webhook-Token do webhook (P09)
    telegram_bot_token: SecretStr | None = None
    inbox_dir: Path = Path("data/inbox")
    processed_dir: Path = Path("data/processed")  # duplicados vão para <processed_dir>/duplicados
    log_level: LogLevel = "INFO"
    api_key: SecretStr | None = None  # header X-API-Key da API (P08)
    tesseract_cmd: str | None = None  # caminho do tesseract.exe se não estiver no PATH (P10)


def load_settings(env_file: Path | None = DEFAULT_ENV_FILE) -> Settings:
    """Carrega as configurações; `env_file=None` ignora qualquer arquivo .env."""
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        raise ConfigError(_describe(exc)) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Configuração do processo, carregada uma única vez."""
    return load_settings()


def _describe(exc: ValidationError) -> str:
    problems = []
    for error in exc.errors():
        name = str(error["loc"][0]).upper() if error["loc"] else "?"
        if error["type"] == "missing":
            problems.append(f"- {name}: variável obrigatória ausente")
        else:
            problems.append(f"- {name}: {error['msg']}")
    return (
        "Configuração inválida:\n"
        + "\n".join(problems)
        + "\nCopie .env.example para .env e preencha os valores."
    )

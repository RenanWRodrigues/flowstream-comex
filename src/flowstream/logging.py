"""Logging do projeto: JSON em arquivo, texto legível no terminal e dados pessoais mascarados.

Uso:
    configure_logging(level="INFO", log_file=Path("logs/flowstream.log"))
    logger = get_logger(__name__)
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT_LOGGER = "flowstream"

# CNPJ com ou sem pontuação, numérico ou alfanumérico (12 posições de letra ou dígito + 2
# dígitos verificadores, em vigor desde 07/2026). Vem antes do CPF para não ser cortado.
_CNPJ = re.compile(
    r"(?<![0-9A-Z])[0-9A-Z]{2}\.?[0-9A-Z]{3}\.?[0-9A-Z]{3}/?[0-9A-Z]{4}-?\d{2}(?![0-9A-Z])"
)
# CPF só com pontuação: 11 dígitos soltos colidiriam com números de AWB (3 + 8 dígitos).
_CPF = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

_PATTERNS = ((_CNPJ, "[CNPJ]"), (_CPF, "[CPF]"), (_EMAIL, "[EMAIL]"))

_TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def mask_sensitive(text: str) -> str:
    """Substitui CNPJ, CPF e e-mail por marcadores."""
    for pattern, placeholder in _PATTERNS:
        text = pattern.sub(placeholder, text)
    return text


class SensitiveDataFilter(logging.Filter):
    """Mascara a mensagem e o traceback antes de qualquer handler formatar o registro."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_sensitive(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = mask_sensitive(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class JsonFormatter(logging.Formatter):
    """Um objeto JSON por linha, com horário em UTC."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_text:
            payload["exception"] = record.exc_text
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    """Configura o logger `flowstream`. Pode ser chamada mais de uma vez sem duplicar saídas."""
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(level)
    logger.propagate = False

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(_TEXT_FORMAT))
    logger.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)

    for handler in logger.handlers:
        handler.addFilter(SensitiveDataFilter())


def get_logger(name: str) -> logging.Logger:
    """Logger filho de `flowstream`, para que herde handlers e mascaramento."""
    if name != ROOT_LOGGER and not name.startswith(f"{ROOT_LOGGER}."):
        name = f"{ROOT_LOGGER}.{name}"
    return logging.getLogger(name)

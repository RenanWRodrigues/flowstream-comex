"""Testes do logging com mascaramento de dados pessoais."""

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from flowstream.logging import configure_logging, get_logger, mask_sensitive


@pytest.fixture(autouse=True)
def reset_flowstream_logger() -> Iterator[None]:
    yield
    logger = logging.getLogger("flowstream")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CNPJ 00.000.000/0001-00 cadastrado", "CNPJ [CNPJ] cadastrado"),
        ("CNPJ 00000000000100 cadastrado", "CNPJ [CNPJ] cadastrado"),
        ("cnpj:00.000.123/0001-40", "cnpj:[CNPJ]"),
        ("CNPJ 12.ABC.345/01DE-35 (alfanumérico)", "CNPJ [CNPJ] (alfanumérico)"),
        ("CNPJ 12ABC34501DE35 sem pontuação", "CNPJ [CNPJ] sem pontuação"),
        ("CPF 000.111.222-33 do despachante", "CPF [CPF] do despachante"),
        ("contato: joao.silva@exemplo.com.br", "contato: [EMAIL]"),
        ("Ana_B+comex@empresa-ficticia.io respondeu", "[EMAIL] respondeu"),
        (
            "00.000.000/0001-00, 000.111.222-33 e x@y.com",
            "[CNPJ], [CPF] e [EMAIL]",
        ),
    ],
)
def test_mask_sensitive_hides_personal_data(text: str, expected: str) -> None:
    assert mask_sensitive(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Contêiner MSCU1234566 embarcou em BRITJ",
        "AWB 020-12345675 chegou",  # AWB com hífen
        "AWB 02012345675 chegou",  # 11 dígitos sem pontuação não é CPF
        "NCM 8471.30.12 e 84713012",
        "Processo IMP-2024-000123 com 3 TEUs",
    ],
)
def test_mask_sensitive_keeps_logistics_identifiers(text: str) -> None:
    assert mask_sensitive(text) == text


def test_file_log_is_json_and_masked(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "flowstream.log"
    configure_logging(level="INFO", log_file=log_file)

    get_logger("flowstream.teste").info(
        "cliente %s, contato %s", "00.000.000/0001-00", "ana@exemplo.com"
    )

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["message"] == "cliente [CNPJ], contato [EMAIL]"
    assert record["level"] == "INFO"
    assert record["logger"] == "flowstream.teste"
    assert record["timestamp"].endswith("+00:00")


def test_console_log_is_readable_text_and_masked(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO")

    get_logger("flowstream.teste").warning("CPF %s recusado", "000.111.222-33")

    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "flowstream.teste" in err
    assert "CPF [CPF] recusado" in err
    assert "000.111.222-33" not in err


def test_exception_traceback_is_masked(tmp_path: Path) -> None:
    log_file = tmp_path / "flowstream.log"
    configure_logging(level="INFO", log_file=log_file)

    try:
        raise ValueError("CNPJ inválido: 00000000000100")
    except ValueError:
        get_logger("flowstream.teste").exception("falha na carga")

    record = json.loads(log_file.read_text(encoding="utf-8"))
    assert "00000000000100" not in record["exception"]
    assert "[CNPJ]" in record["exception"]


def test_level_filters_lower_messages(tmp_path: Path) -> None:
    log_file = tmp_path / "flowstream.log"
    configure_logging(level="WARNING", log_file=log_file)

    logger = get_logger("flowstream.teste")
    logger.info("não deve aparecer")
    logger.error("deve aparecer")

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["message"] for line in lines] == ["deve aparecer"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("flowstream", "flowstream"),
        ("flowstream.ai", "flowstream.ai"),
        ("scripts.carga", "flowstream.scripts.carga"),
    ],
)
def test_get_logger_always_inside_flowstream_namespace(name: str, expected: str) -> None:
    assert get_logger(name).name == expected


def test_configure_twice_does_not_duplicate_handlers(tmp_path: Path) -> None:
    configure_logging(level="INFO", log_file=tmp_path / "a.log")
    configure_logging(level="INFO", log_file=tmp_path / "a.log")

    assert len(logging.getLogger("flowstream").handlers) == 2  # terminal + arquivo

"""Montagem do pipeline real a partir do Settings (nada é chamado: Ollama e OCR ficam ociosos)."""

import pytest

from flowstream.ai.factory import build_pipeline
from flowstream.ai.llm import DEFAULT_TIMEOUT_SECONDS
from flowstream.ai.prompting import PromptVersionError
from flowstream.config import Settings


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5433/db",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )


def test_defaults_come_from_settings() -> None:
    pipeline = build_pipeline(_settings())
    assert pipeline.llm.model == "qwen2.5:3b"
    assert pipeline.llm.timeout == DEFAULT_TIMEOUT_SECONDS
    assert pipeline.prompt_version == "v1"


def test_evaluation_overrides_model_version_and_timeout() -> None:
    pipeline = build_pipeline(_settings(), model="qwen2.5:1.5b", prompt_version="v1", timeout=600)
    assert pipeline.llm.model == "qwen2.5:1.5b"
    assert pipeline.llm.timeout == 600
    assert pipeline.prompt_version == "v1"


def test_unknown_prompt_version_is_refused() -> None:
    with pytest.raises(PromptVersionError):
        build_pipeline(_settings(), prompt_version="v42")

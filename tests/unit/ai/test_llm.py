"""Cliente do Ollama (respx, sem rede) e FakeLLM."""

import json

import httpx
import pytest
import respx

from flowstream.ai.llm import FakeLLM, LLMError, OllamaClient

BASE = "http://127.0.0.1:11434"


@respx.mock
def test_ollama_sends_deterministic_json_request() -> None:
    route = respx.post(f"{BASE}/api/generate").respond(
        200, json={"response": '{"ok": true}', "model": "qwen2.5:3b", "done": True}
    )
    with httpx.Client() as http:
        client = OllamaClient(BASE, "qwen2.5:3b", http=http)
        answer = client.generate(system="sistema", prompt="documento")
    body = json.loads(route.calls.last.request.read())
    assert body["model"] == "qwen2.5:3b"
    assert body["system"] == "sistema"
    assert body["prompt"] == "documento"
    assert body["stream"] is False
    assert body["format"] == "json"
    assert body["keep_alive"] == "5m"
    assert body["options"] == {"temperature": 0, "num_ctx": 4096, "num_predict": 1500}
    assert answer.text == '{"ok": true}'
    assert answer.model == "qwen2.5:3b"
    assert answer.duration_ms >= 0


@respx.mock
def test_ollama_down_is_an_llm_error() -> None:
    respx.post(f"{BASE}/api/generate").mock(side_effect=httpx.ConnectError("recusada"))
    with httpx.Client() as http, pytest.raises(LLMError, match="Ollama"):
        OllamaClient(BASE, "qwen2.5:3b", http=http).generate("s", "p")


@respx.mock
def test_model_not_pulled_is_explained() -> None:
    respx.post(f"{BASE}/api/generate").respond(404, json={"error": "model not found"})
    with httpx.Client() as http, pytest.raises(LLMError, match=r"ollama pull qwen2.5:3b"):
        OllamaClient(BASE, "qwen2.5:3b", http=http).generate("s", "p")


@respx.mock
def test_unexpected_payload_is_an_llm_error() -> None:
    respx.post(f"{BASE}/api/generate").respond(200, json={"sem": "response"})
    with httpx.Client() as http, pytest.raises(LLMError, match="inesperada"):
        OllamaClient(BASE, "qwen2.5:3b", http=http).generate("s", "p")


def test_all_ollama_clients_share_one_lock() -> None:
    """Uma chamada ao modelo por vez no processo inteiro, para caber em 8 GB."""
    with httpx.Client() as http:
        first = OllamaClient(BASE, "a", http=http)
        second = OllamaClient(BASE, "b", http=http)
    assert first.lock is second.lock


def test_fake_llm_returns_recorded_answers_in_order() -> None:
    fake = FakeLLM(["primeira", "segunda"])
    assert fake.generate("s", "p1").text == "primeira"
    assert fake.generate("s", "p2").text == "segunda"
    assert [call.prompt for call in fake.calls] == ["p1", "p2"]
    assert fake.model == "fake"


def test_fake_llm_without_answers_raises() -> None:
    with pytest.raises(LLMError, match="FakeLLM"):
        FakeLLM([]).generate("s", "p")


def test_default_http_client_ignores_system_proxy() -> None:
    """Com proxy do ambiente, a chamada a 127.0.0.1 trava (mesma regra do health check)."""
    client = OllamaClient(BASE, "qwen2.5:3b")
    assert client.http_trusts_env is False


@respx.mock
@pytest.mark.parametrize("body", [b"<html>proxy</html>", b"[1, 2]"])
def test_ollama_200_that_is_not_an_object_is_an_llm_error(body: bytes) -> None:
    """Revisão P10 M6: resposta 200 sem JSON (ou JSON que não é objeto) vira LLMError."""
    respx.post(f"{BASE}/api/generate").respond(200, content=body)
    with httpx.Client() as http, pytest.raises(LLMError, match="inesperada"):
        OllamaClient(BASE, "qwen2.5:3b", http=http).generate("s", "p")

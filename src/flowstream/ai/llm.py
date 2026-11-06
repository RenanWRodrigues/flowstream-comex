"""Clientes de LLM: interface, Ollama local (uma chamada por vez) e FakeLLM para testes."""

import threading
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar, Protocol

import httpx

DEFAULT_TIMEOUT_SECONDS = 120.0
NUM_CTX = 4096
KEEP_ALIVE = "5m"
NUM_PREDICT = 1500  # teto de tokens gerados: um JSON de documento cabe com folga


class LLMError(RuntimeError):
    """O modelo não respondeu ou respondeu algo que não dá para usar."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    duration_ms: int


class LLMClient(Protocol):
    @property
    def model(self) -> str: ...

    def generate(self, system: str, prompt: str) -> LLMResponse: ...


class OllamaClient:
    """Ollama em /api/generate: temperature 0, saída JSON, contexto de 4096 tokens.

    Uma trava de classe garante uma chamada ao modelo por vez no processo (8 GB de RAM).
    """

    lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(
        self,
        base_url: str,
        model: str,
        http: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._url = base_url.rstrip("/") + "/api/generate"
        self._model = model
        # Serviço local: sem proxy do ambiente (com proxy, a chamada a 127.0.0.1 trava).
        self._http = http or httpx.Client(timeout=timeout, trust_env=False)
        self._timeout = timeout

    @property
    def model(self) -> str:
        return self._model

    @property
    def timeout(self) -> float:
        return self._timeout

    @property
    def http_trusts_env(self) -> bool:
        return bool(self._http.trust_env)

    def generate(self, system: str, prompt: str) -> LLMResponse:
        payload = {
            "model": self._model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT},
        }
        started = time.monotonic()
        with self.lock:
            try:
                response = self._http.post(self._url, json=payload, timeout=self._timeout)
            except httpx.HTTPError as exc:
                raise LLMError(
                    f"Ollama indisponível ({type(exc).__name__}). Ele está rodando (ollama serve)?"
                ) from None
        elapsed = int((time.monotonic() - started) * 1000)
        if response.status_code == 404:
            raise LLMError(f"Modelo não encontrado no Ollama: rode `ollama pull {self._model}`.")
        if response.status_code != 200:
            raise LLMError(f"Ollama respondeu HTTP {response.status_code}.")
        try:
            body = response.json()
        except ValueError:
            body = None
        text = body.get("response") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise LLMError("Resposta inesperada do Ollama (sem o campo 'response').")
        return LLMResponse(text=text, model=self._model, duration_ms=elapsed)


@dataclass(frozen=True)
class LLMCall:
    system: str
    prompt: str


class FakeLLM:
    """Devolve respostas gravadas, na ordem, e registra o que recebeu (testes sem Ollama)."""

    def __init__(self, answers: Iterable[str], model: str = "fake") -> None:
        self._answers = deque(answers)
        self._model = model
        self.calls: list[LLMCall] = []

    @property
    def model(self) -> str:
        return self._model

    def generate(self, system: str, prompt: str) -> LLMResponse:
        self.calls.append(LLMCall(system, prompt))
        if not self._answers:
            raise LLMError("FakeLLM sem respostas gravadas para esta chamada.")
        return LLMResponse(text=self._answers.popleft(), model=self._model, duration_ms=0)

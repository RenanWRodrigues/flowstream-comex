"""Watcher da inbox com relógio falso, repositório falso e webhook simulado (sem sleep real)."""

import hashlib
import http.client
import io
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from types import TracebackType

import pytest
from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileMovedEvent

from flowstream.config import Settings
from flowstream.ingestion import inbox_watcher
from flowstream.ingestion.inbox_watcher import (
    InboxEvent,
    InboxEventHandler,
    InboxNotifyError,
    InboxStoreError,
    InboxWatcher,
    WebhookNotifier,
    libpq_url,
    urllib_post,
)

WEBHOOK = "http://127.0.0.1:5678/webhook/documento-recebido"
FAKE_TOKEN = "token-ficticio"  # noqa: S105


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeKnownDocuments:
    def __init__(self) -> None:
        self.by_hash: dict[str, str] = {}

    def add(self, name: str, content: bytes) -> None:
        self.by_hash[hashlib.sha256(content).hexdigest()] = name

    def registered_name(self, sha256: str) -> str | None:
        return self.by_hash.get(sha256)


class SpyNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.events: list[InboxEvent] = []
        self.fail = fail

    def notify(self, event: InboxEvent) -> None:
        self.events.append(event)
        if self.fail:
            raise InboxNotifyError("webhook do n8n indisponível")


class SpyRuns:
    def __init__(self) -> None:
        self.failures: list[BaseException] = []

    def record_failure(self, error: BaseException) -> None:
        self.failures.append(error)


class Env:
    def __init__(self, tmp_path: Path, notifier: SpyNotifier | None = None) -> None:
        self.inbox = tmp_path / "inbox"
        self.inbox.mkdir()
        self.duplicates = tmp_path / "processed" / "duplicados"
        self.clock = FakeClock()
        self.known = FakeKnownDocuments()
        self.notifier = notifier or SpyNotifier()
        self.runs = SpyRuns()
        self.watcher = InboxWatcher(
            inbox=self.inbox,
            duplicates_dir=self.duplicates,
            known=self.known,
            notifier=self.notifier,
            runs=self.runs,
            clock=self.clock,
            min_interval=1.0,
        )

    def drop(self, name: str, content: bytes) -> Path:
        path = self.inbox / name
        path.write_bytes(content)
        self.watcher.enqueue(path)
        return path

    def settle(self) -> None:
        """Duas leituras com o mesmo tamanho, a 1 s de distância (no relógio falso)."""
        self.watcher.tick()
        self.clock.advance(1.0)
        self.watcher.tick()


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


# ------------------------------------------------------------------ disparo


def test_stable_pdf_notifies_n8n_with_name_hash_and_size(env: Env) -> None:
    content = b"%PDF-1.7 bl sintetico"
    env.drop("BL_MSKU1234565.pdf", content)
    env.settle()
    assert env.notifier.events == [
        InboxEvent(
            arquivo="BL_MSKU1234565.pdf",
            sha256=hashlib.sha256(content).hexdigest(),
            tamanho_bytes=len(content),
        )
    ]


def test_first_reading_alone_does_not_notify(env: Env) -> None:
    env.drop("bl.pdf", b"%PDF-1.7")
    env.watcher.tick()
    assert env.notifier.events == []


def test_growing_file_does_not_notify(env: Env) -> None:
    path = env.drop("bl.pdf", b"%PDF")
    for _ in range(4):
        env.watcher.tick()
        env.clock.advance(1.0)
        with path.open("ab") as file:
            file.write(b" mais bytes")
    assert env.notifier.events == []
    env.settle()  # parou de crescer
    assert len(env.notifier.events) == 1


def test_same_file_is_not_notified_twice(env: Env) -> None:
    path = env.drop("bl.pdf", b"%PDF-1.7")
    env.settle()
    env.watcher.enqueue(path)  # o SO costuma mandar vários eventos de modificação
    env.settle()
    env.clock.advance(5.0)
    env.watcher.tick()
    assert len(env.notifier.events) == 1


def test_file_replaced_with_new_content_is_notified_again(env: Env) -> None:
    path = env.drop("bl.pdf", b"%PDF-1.7 versao 1")
    env.settle()
    path.write_bytes(b"%PDF-1.7 versao 2, corrigida")
    env.watcher.enqueue(path)
    env.settle()
    assert len(env.notifier.events) == 2


def test_non_pdf_and_temporary_files_are_ignored(env: Env) -> None:
    env.drop("planilha.xlsx", b"xlsx")
    env.drop("download.pdf.crdownload", b"%PDF")
    env.drop("~$bl.pdf", b"lock")
    env.settle()
    assert env.notifier.events == []
    assert env.watcher.pending_count == 0


def test_unsafe_pdf_name_is_skipped(env: Env) -> None:
    env.drop("bl#1.pdf", b"%PDF-1.7")
    env.settle()
    assert env.notifier.events == []


def test_file_removed_before_settling_is_forgotten(env: Env) -> None:
    path = env.drop("bl.pdf", b"%PDF-1.7")
    env.watcher.tick()
    path.unlink()
    env.clock.advance(1.0)
    env.watcher.tick()
    assert env.notifier.events == []
    assert env.watcher.pending_count == 0


def test_files_outside_the_inbox_are_ignored(env: Env, tmp_path: Path) -> None:
    outside = tmp_path / "fora.pdf"
    outside.write_bytes(b"%PDF-1.7")
    env.watcher.enqueue(outside)
    env.settle()
    assert env.notifier.events == []


def test_scan_picks_up_files_already_in_the_inbox(env: Env) -> None:
    (env.inbox / "antes_de_ligar.pdf").write_bytes(b"%PDF-1.7 antigo")
    (env.inbox / "notas.txt").write_text("x", encoding="utf-8")
    env.watcher.scan()
    env.settle()
    assert [e.arquivo for e in env.notifier.events] == ["antes_de_ligar.pdf"]


# ------------------------------------------------------------------ duplicados


def test_duplicate_content_with_other_name_is_moved(env: Env) -> None:
    content = b"%PDF-1.7 invoice"
    env.known.add("invoice.pdf", content)
    env.drop("invoice (1).pdf", content)
    env.settle()
    assert env.notifier.events == []
    assert not (env.inbox / "invoice (1).pdf").exists()
    assert (env.duplicates / "invoice (1).pdf").read_bytes() == content


def test_duplicate_does_not_overwrite_an_earlier_duplicate(env: Env) -> None:
    content = b"%PDF-1.7 invoice"
    env.known.add("invoice.pdf", content)
    env.duplicates.mkdir(parents=True)
    (env.duplicates / "copia.pdf").write_bytes(b"outro duplicado")
    env.drop("copia.pdf", content)
    env.settle()
    moved = sorted(p.name for p in env.duplicates.iterdir())
    assert len(moved) == 2
    assert (env.duplicates / "copia.pdf").read_bytes() == b"outro duplicado"


def test_already_registered_file_stays_and_is_not_notified(env: Env) -> None:
    content = b"%PDF-1.7 bl"
    env.known.add("bl.pdf", content)
    env.drop("bl.pdf", content)
    env.settle()
    assert env.notifier.events == []
    assert (env.inbox / "bl.pdf").exists()


# ------------------------------------------------------------------ falhas


def test_definitive_webhook_failure_is_recorded_as_error(tmp_path: Path) -> None:
    env = Env(tmp_path, notifier=SpyNotifier(fail=True))
    env.drop("bl.pdf", b"%PDF-1.7")
    env.settle()
    assert len(env.runs.failures) == 1
    assert isinstance(env.runs.failures[0], InboxNotifyError)
    env.clock.advance(5.0)
    env.watcher.tick()
    assert len(env.notifier.events) == 1  # não insiste até reiniciar o watcher


def test_failure_that_cannot_be_recorded_does_not_stop_the_watcher(tmp_path: Path) -> None:
    class BrokenRuns:
        def record_failure(self, error: BaseException) -> None:
            raise InboxStoreError("banco fora do ar")

    env = Env(tmp_path, notifier=SpyNotifier(fail=True))
    env.watcher = InboxWatcher(
        inbox=env.inbox,
        duplicates_dir=env.duplicates,
        known=env.known,
        notifier=env.notifier,
        runs=BrokenRuns(),
        clock=env.clock,
    )
    env.drop("bl.pdf", b"%PDF-1.7")
    env.settle()  # não levanta
    assert len(env.notifier.events) == 1


def test_database_error_keeps_file_pending(env: Env) -> None:
    class BrokenKnown:
        calls = 0

        def registered_name(self, sha256: str) -> str | None:
            self.calls += 1
            if self.calls == 1:
                raise InboxStoreError("banco fora do ar")
            return None

    env.watcher = InboxWatcher(
        inbox=env.inbox,
        duplicates_dir=env.duplicates,
        known=BrokenKnown(),
        notifier=env.notifier,
        runs=env.runs,
        clock=env.clock,
        min_interval=1.0,
    )
    env.drop("bl.pdf", b"%PDF-1.7")
    env.settle()
    assert env.notifier.events == []
    env.clock.advance(5.0)  # primeira espera depois de uma falha do banco
    env.settle()
    assert len(env.notifier.events) == 1


def test_database_down_waits_before_trying_the_file_again(env: Env) -> None:
    """Revisão P09 #5: sem backoff, N arquivos x 10 s de timeout travavam o laço."""

    class DeadKnown:
        calls = 0

        def registered_name(self, sha256: str) -> str | None:
            self.calls += 1
            raise InboxStoreError("banco fora do ar")

    dead = DeadKnown()
    env.watcher = InboxWatcher(
        inbox=env.inbox,
        duplicates_dir=env.duplicates,
        known=dead,
        notifier=env.notifier,
        runs=env.runs,
        clock=env.clock,
        min_interval=1.0,
    )
    env.drop("bl.pdf", b"%PDF-1.7")
    env.settle()
    assert dead.calls == 1
    for _ in range(3):  # 3 s depois: ainda dentro dos 5 s de espera
        env.clock.advance(1.0)
        env.watcher.tick()
    assert dead.calls == 1
    env.clock.advance(3.0)
    env.settle()
    assert dead.calls == 2
    assert env.watcher.pending_count == 1  # segue na fila, agora esperando 10 s


def test_unexpected_error_does_not_kill_the_watcher(tmp_path: Path) -> None:
    """Revisão P09 #1: qualquer erro num arquivo vira ERRO registrado, não a morte do processo."""

    class ExplodingNotifier(SpyNotifier):
        def notify(self, event: InboxEvent) -> None:
            self.events.append(event)
            raise RuntimeError("falha inesperada")

    env = Env(tmp_path, notifier=ExplodingNotifier())
    env.drop("bl.pdf", b"%PDF-1.7")
    env.settle()  # não levanta
    assert len(env.runs.failures) == 1
    env.drop("outro.pdf", b"%PDF-1.7 outro")
    env.settle()
    assert [e.arquivo for e in env.notifier.events] == ["bl.pdf", "outro.pdf"]


def test_file_truncated_to_zero_before_hashing_is_not_fatal(env: Env) -> None:
    path = env.drop("bl.pdf", b"%PDF-1.7")
    env.watcher.tick()
    env.clock.advance(1.0)
    original = env.watcher._process

    def truncate_then_process(target: Path) -> None:
        target.write_bytes(b"")
        original(target)

    env.watcher._process = truncate_then_process  # type: ignore[method-assign]
    env.watcher.tick()  # InboxEvent(tamanho_bytes=0) falharia na validação: não pode derrubar
    assert env.notifier.events == []
    assert path.exists()


def test_preallocated_copy_waits_for_the_mtime_to_settle(env: Env) -> None:
    """Revisão P09 #4: tamanho final desde o início, conteúdo ainda chegando."""
    path = env.drop("bl.pdf", b"\0" * 64)
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    env.watcher.tick()
    env.clock.advance(1.0)
    path.write_bytes(b"%PDF-1.7" + b"x" * 56)  # mesmo tamanho, conteúdo novo
    os.utime(path, ns=(2_000_000_000, 2_000_000_000))
    env.watcher.tick()
    assert env.notifier.events == []
    env.settle()
    assert len(env.notifier.events) == 1
    assert env.notifier.events[0].sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_copies_arriving_together_notify_only_once(env: Env) -> None:
    """Revisão P09 #6: o n8n registra depois; a segunda cópia não pode ser avisada também."""
    content = b"%PDF-1.7 invoice"
    env.drop("invoice.pdf", content)
    env.drop("invoice (1).pdf", content)
    env.settle()
    assert [e.arquivo for e in env.notifier.events] == ["invoice.pdf"]
    assert (env.duplicates / "invoice (1).pdf").exists()


def test_failed_notification_does_not_count_as_registered(tmp_path: Path) -> None:
    env = Env(tmp_path, notifier=SpyNotifier(fail=True))
    content = b"%PDF-1.7 invoice"
    env.drop("a.pdf", content)
    env.settle()
    env.drop("b.pdf", content)
    env.settle()
    assert [e.arquivo for e in env.notifier.events] == ["a.pdf", "b.pdf"]


def test_run_stops_when_event_is_set(env: Env) -> None:
    stop = threading.Event()
    stop.set()
    env.watcher.run(stop, poll_interval=60.0)  # retorna na hora, sem esperar


# ------------------------------------------------------------------ eventos do watchdog


def test_event_handler_enqueues_created_modified_and_moved(env: Env) -> None:
    handler = InboxEventHandler(env.watcher)
    handler.on_created(FileCreatedEvent(str(env.inbox / "a.pdf")))
    handler.on_modified(FileModifiedEvent(str(env.inbox / "b.pdf")))
    handler.on_moved(FileMovedEvent(str(env.inbox / "c.pdf.part"), str(env.inbox / "c.pdf")))
    handler.on_created(FileCreatedEvent(str(env.inbox / "ignorado.txt")))
    assert env.watcher.pending_count == 3


# ------------------------------------------------------------------ webhook


class FakePost:
    """Substitui o POST HTTP: devolve os status (ou lança os erros) na ordem dada."""

    def __init__(self, *outcomes: int | Exception) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str], timeout: float) -> int:
        self.calls.append((url, body, headers))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _payload() -> InboxEvent:
    return InboxEvent(arquivo="bl.pdf", sha256="a" * 64, tamanho_bytes=10)


def _notifier(
    post: FakePost, sleeps: list[float] | None = None, token: str | None = FAKE_TOKEN
) -> WebhookNotifier:
    waits = sleeps if sleeps is not None else []
    return WebhookNotifier(WEBHOOK, token, post=post, sleep=waits.append)


def test_webhook_posts_json_with_token_header() -> None:
    post = FakePost(200)
    _notifier(post).notify(_payload())
    [(url, body, headers)] = post.calls
    assert url == WEBHOOK
    assert headers["X-Webhook-Token"] == FAKE_TOKEN
    assert headers["Content-Type"] == "application/json"
    assert body == _payload().model_dump_json().encode()


def test_webhook_without_token_sends_no_header() -> None:
    post = FakePost(200)
    _notifier(post, token=None).notify(_payload())
    assert "X-Webhook-Token" not in post.calls[0][2]


def test_webhook_retries_three_times_with_backoff_then_fails() -> None:
    post = FakePost(503, 503, 503)
    sleeps: list[float] = []
    with pytest.raises(InboxNotifyError, match="3 tentativas"):
        _notifier(post, sleeps).notify(_payload())
    assert len(post.calls) == 3
    assert sleeps == [1.0, 2.0]


def test_webhook_recovers_after_connection_error() -> None:
    post = FakePost(urllib.error.URLError("recusada"), 200)
    _notifier(post).notify(_payload())
    assert len(post.calls) == 2


def test_webhook_unreachable_three_times_fails() -> None:
    post = FakePost(*(ConnectionRefusedError("recusada") for _ in range(3)))
    with pytest.raises(InboxNotifyError, match="inacessível"):
        _notifier(post).notify(_payload())


def test_webhook_malformed_http_response_is_retried() -> None:
    """Revisão P09 #1: BadStatusLine/IncompleteRead não são OSError."""
    post = FakePost(http.client.BadStatusLine("lixo"), http.client.IncompleteRead(b""), 200)
    _notifier(post).notify(_payload())
    assert len(post.calls) == 3


def test_webhook_redirect_is_a_failure() -> None:
    """Revisão P09 #7: um 302 viraria GET sem corpo; nunca é sucesso."""
    post = FakePost(302)
    with pytest.raises(InboxNotifyError, match="302"):
        _notifier(post).notify(_payload())


def test_webhook_rate_limit_is_retried() -> None:
    post = FakePost(429, 202)
    _notifier(post).notify(_payload())
    assert len(post.calls) == 2


def test_webhook_client_error_is_not_retried() -> None:
    """404 = fluxo não publicado no n8n; 401/403 = token errado. Repetir não resolve."""
    post = FakePost(404)
    with pytest.raises(InboxNotifyError, match="404"):
        _notifier(post).notify(_payload())
    assert len(post.calls) == 1


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://n8n/webhook", "n8n:5678"])
def test_webhook_only_accepts_http_urls(url: str) -> None:
    with pytest.raises(ValueError, match="http"):
        WebhookNotifier(url, None)


def test_invalid_webhook_url_error_does_not_echo_secrets() -> None:
    """Revisão P09 #8: a URL pode ter usuário:senha ou ?token=."""
    with pytest.raises(ValueError, match="http") as caught:
        WebhookNotifier("ftp://admin:segredo@n8n/webhook?token=abc", None)
    assert "segredo" not in str(caught.value)
    assert "abc" not in str(caught.value)


# ------------------------------------------------------------------ POST com urllib


class _FakeResponse:
    status = 200

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


def test_urllib_post_returns_the_status(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[urllib.request.Request] = []

    def fake_open(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        sent.append(request)
        return _FakeResponse()

    monkeypatch.setattr(inbox_watcher.HTTP_OPENER, "open", fake_open)
    status = urllib_post(WEBHOOK, b"{}", {"Content-Type": "application/json"}, 5.0)
    assert status == 200
    assert sent[0].get_method() == "POST"
    assert sent[0].data == b"{}"


def test_urllib_post_returns_http_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_open(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        raise urllib.error.HTTPError(WEBHOOK, 403, "Forbidden", Message(), io.BytesIO(b""))

    monkeypatch.setattr(inbox_watcher.HTTP_OPENER, "open", fake_open)
    assert urllib_post(WEBHOOK, b"{}", {}, 5.0) == 403


def test_http_opener_ignores_proxies_and_does_not_follow_redirects() -> None:
    """Revisão P09 #7: o token não pode seguir um redirecionamento nem passar por proxy."""
    handlers = inbox_watcher.HTTP_OPENER.handlers
    # ProxyHandler({}) não tem o que atender e nem é guardado; o do sistema não entra.
    proxies = [h for h in handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert all(not h.proxies for h in proxies)
    [redirect] = [h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    request = urllib.request.Request(WEBHOOK, data=b"{}", method="POST")
    new = redirect.redirect_request(request, io.BytesIO(), 302, "Found", Message(), "http://x/")
    assert new is None


# ------------------------------------------------------------------ banco e entrada


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+psycopg://u:p@127.0.0.1:5433/db", "postgresql://u:p@127.0.0.1:5433/db"),
        ("postgresql://u:p@host/db", "postgresql://u:p@host/db"),
    ],
)
def test_libpq_url_drops_the_sqlalchemy_driver(url: str, expected: str) -> None:
    assert libpq_url(url) == expected


def test_watcher_module_does_not_load_heavy_libraries() -> None:
    """Orçamento de < 50 MB: SQLAlchemy, httpx, Typer e tenacity ficam fora do watcher."""
    code = (
        "import sys, flowstream.ingestion.inbox_watcher; "
        "print(','.join(m for m in ('sqlalchemy', 'httpx', 'typer', 'tenacity', 'rich') "
        "if m in sys.modules))"
    )
    result = subprocess.run(  # noqa: S603 - o próprio Python, comando fixo
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


def test_main_runs_until_interrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[float, float]] = []

    def fake_watch(settings: Settings, stop: object, poll: float, interval: float) -> None:
        calls.append((poll, interval))
        raise KeyboardInterrupt

    monkeypatch.setattr(inbox_watcher, "load_settings", _fake_settings)
    monkeypatch.setattr(inbox_watcher, "watch_inbox", fake_watch)
    assert inbox_watcher.main(["--poll", "0.5", "--stable-seconds", "2"]) == 0
    assert calls == [(0.5, 2.0)]


def test_main_fails_cleanly_on_invalid_webhook_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_url(settings: Settings, stop: object, poll: float, interval: float) -> None:
        raise ValueError("N8N_WEBHOOK_URL precisa começar com http:// ou https://")

    monkeypatch.setattr(inbox_watcher, "load_settings", _fake_settings)
    monkeypatch.setattr(inbox_watcher, "watch_inbox", bad_url)
    assert inbox_watcher.main([]) == 1


def test_main_fails_on_bad_config(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> Settings:
        raise inbox_watcher.ConfigError("Configuração inválida:\n- DATABASE_URL: ausente")

    monkeypatch.setattr(inbox_watcher, "load_settings", broken)
    assert inbox_watcher.main([]) == 1


def _fake_settings(*args: object, **kwargs: object) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5433/db",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

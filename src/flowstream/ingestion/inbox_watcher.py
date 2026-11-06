"""Watcher da pasta inbox: um PDF salvo em data/inbox vira um aviso para o webhook do n8n.

Fluxo: o watchdog só enfileira caminhos (thread do observador); `InboxWatcher.tick` faz o
trabalho no laço principal: espera o arquivo parar de crescer, calcula o SHA-256, separa
duplicados e avisa o n8n (3 tentativas com backoff). Falha definitiva vira ERRO em
ops.pipeline_runs.

Orçamento de memória (< 50 MB): este módulo usa psycopg direto e urllib da biblioteca
padrão, sem SQLAlchemy, httpx, Typer ou tenacity. Rode com
`python -m flowstream.ingestion.inbox_watcher` (é o que o `make watch` faz).
"""

import argparse
import http.client
import logging
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from email.message import Message as HTTPMessage
from pathlib import Path
from typing import IO, Protocol

import psycopg
from pydantic import BaseModel, ConfigDict, Field
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from flowstream.config import ConfigError, Settings, load_settings
from flowstream.documents.service import digest_file
from flowstream.ingestion.inbox_domain import (
    Disposition,
    NameCheck,
    StabilityTracker,
    check_name,
    decide,
    retry_delay,
)
from flowstream.logging import configure_logging, get_logger, mask_sensitive

logger = get_logger("flowstream.ingestion.inbox_watcher")  # __name__ vira __main__ com -m

PIPELINE = "inbox_watcher"
AUTH_HEADER_NAME = "X-Webhook-Token"
ATTEMPTS = 3
HTTP_TIMEOUT_SECONDS = 10.0
DB_TIMEOUT_SECONDS = 10
MAX_ERROR_LENGTH = 500

_Signature = tuple[int, int]  # (tamanho, mtime em ns): identifica uma versão do arquivo
Post = Callable[[str, bytes, dict[str, str], float], int]


class InboxNotifyError(RuntimeError):
    """O n8n não recebeu o aviso, mesmo depois das tentativas."""


class InboxStoreError(RuntimeError):
    """O banco não respondeu; o watcher tenta de novo nas próximas leituras."""


class InboxEvent(BaseModel):
    """Corpo do POST para o webhook do n8n."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arquivo: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tamanho_bytes: int = Field(gt=0)


class KnownDocuments(Protocol):
    def registered_name(self, sha256: str) -> str | None: ...


class Notifier(Protocol):
    def notify(self, event: InboxEvent) -> None: ...


class RunRecorder(Protocol):
    def record_failure(self, error: BaseException) -> None: ...


# ------------------------------------------------------------------ orquestração


class InboxWatcher:
    """Decide o destino de cada PDF da inbox. `clock` é injetado para testar sem esperar."""

    def __init__(
        self,
        inbox: Path,
        duplicates_dir: Path,
        known: KnownDocuments,
        notifier: Notifier,
        runs: RunRecorder,
        clock: Callable[[], float] = time.monotonic,
        min_interval: float = 1.0,
    ) -> None:
        self._inbox = inbox.resolve()
        self._duplicates = duplicates_dir
        self._known = known
        self._notifier = notifier
        self._runs = runs
        self._clock = clock
        self._tracker = StabilityTracker(min_interval)
        self._pending: dict[str, Path] = {}
        self._handled: dict[str, _Signature] = {}
        self._failures: dict[str, int] = {}  # falhas temporárias seguidas por arquivo
        self._retry_at: dict[str, float] = {}  # quando tentar de novo (relógio injetado)
        self._announced: dict[str, str] = {}  # sha256 -> nome já avisado nesta sessão
        self._lock = threading.Lock()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def enqueue(self, path: Path) -> None:
        """Marca o arquivo para acompanhamento. Seguro para chamar da thread do watchdog."""
        resolved = path.resolve()
        if resolved.parent != self._inbox or check_name(resolved.name) is NameCheck.IGNORAR:
            return
        with self._lock:
            self._pending[str(resolved)] = resolved

    def scan(self) -> None:
        """Enfileira o que já estava na inbox antes de o watcher ligar."""
        for path in sorted(self._inbox.iterdir()):
            if path.is_file():
                self.enqueue(path)

    def run(self, stop: threading.Event, poll_interval: float) -> None:
        """Laço principal: um `tick` a cada `poll_interval` segundos até `stop` ser acionado."""
        while not stop.is_set():
            self.tick()
            stop.wait(poll_interval)

    def tick(self) -> None:
        """Uma leitura de cada arquivo pendente; processa os que ficaram estáveis."""
        with self._lock:
            pending = list(self._pending.items())
        for key, path in pending:
            now = self._clock()
            if self._retry_at.get(key, now) > now:
                continue  # esperando depois de uma falha temporária
            signature = _signature(path)
            if signature is None:
                self._forget(key)
                continue
            if self._handled.get(key) == signature:
                self._drop(key)
                continue
            if self._tracker.observe(key, signature[0], now, mtime_ns=signature[1]):
                self._drop(key)
                self._process_safely(key, path, signature)

    def _drop(self, key: str) -> None:
        self._tracker.forget(key)
        with self._lock:
            self._pending.pop(key, None)

    def _forget(self, key: str) -> None:
        """O arquivo sumiu da inbox: nada mais a acompanhar."""
        self._drop(key)
        self._handled.pop(key, None)
        self._failures.pop(key, None)
        self._retry_at.pop(key, None)

    def _process_safely(self, key: str, path: Path, signature: _Signature) -> None:
        try:
            self._process(path)
        except (InboxStoreError, OSError) as exc:
            # Banco fora do ar ou arquivo travado: tenta de novo, com espera crescente.
            self._schedule_retry(key, path, exc)
            return
        except Exception as exc:
            logger.exception("%s: erro inesperado; ignorado até reiniciar o watcher", path.name)
            self._record_failure(exc)
        self._failures.pop(key, None)
        self._retry_at.pop(key, None)
        self._handled[key] = signature

    def _schedule_retry(self, key: str, path: Path, error: BaseException) -> None:
        failures = self._failures.get(key, 0) + 1
        self._failures[key] = failures
        delay = retry_delay(failures)
        self._retry_at[key] = self._clock() + delay
        level = logging.WARNING if failures == 1 else logging.DEBUG  # um aviso, não um por ciclo
        logger.log(
            level,
            "%s: falha temporária (%s); nova tentativa em %.0f s",
            path.name,
            type(error).__name__,
            delay,
        )
        with self._lock:
            self._pending[key] = path

    def _process(self, path: Path) -> None:
        if check_name(path.name) is NameCheck.INVALIDO:
            logger.warning("%s: nome não aceito pela API; renomeie o arquivo", path.name)
            return
        sha256, size = digest_file(path)
        # O n8n registra depois do aviso: cópias que chegam juntas só aparecem no banco tarde.
        registered = self._announced.get(sha256) or self._known.registered_name(sha256)
        disposition = decide(path.name, registered)
        if disposition is Disposition.JA_REGISTRADO:
            logger.info("%s: já registrado (sha256 %s…)", path.name, sha256[:12])
        elif disposition is Disposition.DUPLICADO:
            target = _move_to(path, self._duplicates, sha256)
            logger.info("%s: conteúdo duplicado; movido para %s", path.name, target.name)
        else:
            self._notify(InboxEvent(arquivo=path.name, sha256=sha256, tamanho_bytes=size))

    def _notify(self, event: InboxEvent) -> None:
        try:
            self._notifier.notify(event)
        except InboxNotifyError as exc:
            logger.error("%s: %s", event.arquivo, exc)
            self._record_failure(exc)
            return
        self._announced[event.sha256] = event.arquivo
        logger.info("%s: n8n avisado (sha256 %s…)", event.arquivo, event.sha256[:12])

    def _record_failure(self, error: BaseException) -> None:
        try:
            self._runs.record_failure(error)
        except InboxStoreError:
            logger.error("não foi possível gravar a falha em ops.pipeline_runs")


def _signature(path: Path) -> _Signature | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _move_to(path: Path, folder: Path, sha256: str) -> Path:
    """Move sem sobrescrever: se o nome já existe, acrescenta o início do hash (e um contador)."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / path.name
    counter = 1
    while target.exists():
        suffix = f"_{sha256[:8]}" if counter == 1 else f"_{sha256[:8]}_{counter}"
        target = folder / f"{path.stem}{suffix}{path.suffix}"
        counter += 1
    shutil.move(path, target)
    return target


# ------------------------------------------------------------------ adaptador: watchdog


class InboxEventHandler(FileSystemEventHandler):
    """Repassa ao watcher os arquivos criados, modificados ou renomeados na inbox."""

    def __init__(self, watcher: InboxWatcher) -> None:
        self._watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        self._enqueue(event.src_path, event.is_directory)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._enqueue(event.src_path, event.is_directory)

    def on_moved(self, event: FileSystemEvent) -> None:
        # Navegadores baixam como .crdownload/.part e renomeiam para .pdf no fim.
        self._enqueue(event.dest_path, event.is_directory)

    def _enqueue(self, raw_path: bytes | str, is_directory: bool) -> None:
        if not is_directory:
            self._watcher.enqueue(Path(os.fsdecode(raw_path)))


def start_observer(watcher: InboxWatcher, inbox: Path) -> BaseObserver:
    observer = Observer()
    observer.schedule(InboxEventHandler(watcher), str(inbox), recursive=False)
    observer.start()
    return observer


# ------------------------------------------------------------------ adaptador: webhook


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Não segue 3xx: o POST viraria GET sem corpo e levaria o token para outro endereço."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None  # o urllib levanta HTTPError com o 3xx, e urllib_post devolve o status


# Sem proxy do sistema (registro do Windows, HTTP_PROXY): o webhook é local.
HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def urllib_post(url: str, body: bytes, headers: dict[str, str], timeout: float) -> int:
    """POST com a biblioteca padrão; devolve o status HTTP (também em 3xx/4xx/5xx)."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with HTTP_OPENER.open(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return exc.code


def _is_transient(status: int) -> bool:
    return status >= 500 or status == 429


class WebhookNotifier:
    """POST JSON no webhook do n8n; repete só em erro de rede, 429 ou 5xx (backoff 1 s, 2 s)."""

    def __init__(
        self,
        url: str,
        token: str | None,
        post: Post = urllib_post,
        sleep: Callable[[float], None] = time.sleep,
        attempts: int = ATTEMPTS,
    ) -> None:
        if not url.startswith(("http://", "https://")):  # urllib também abriria file://
            scheme = url.split(":", 1)[0] if ":" in url else "nenhum"
            # Só o esquema: a URL pode ter usuário:senha ou ?token= (nunca vai para o log).
            raise ValueError(
                "N8N_WEBHOOK_URL precisa começar com http:// ou https:// "
                f"(esquema recebido: {scheme!r})"
            )
        self._url = url
        self._headers = {"Content-Type": "application/json"}
        if token:
            self._headers[AUTH_HEADER_NAME] = token
        self._post = post
        self._sleep = sleep
        self._attempts = attempts

    def notify(self, event: InboxEvent) -> None:
        body = event.model_dump_json().encode()
        status: int | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                status = self._post(self._url, body, self._headers, HTTP_TIMEOUT_SECONDS)
            except (OSError, http.client.HTTPException):  # rede, timeout, resposta malformada
                status = None
            if status is not None and 200 <= status < 300:
                return
            if status is not None and not _is_transient(status):
                raise InboxNotifyError(
                    f"Webhook do n8n recusou o aviso (HTTP {status}). "
                    "O fluxo documento_recebido está publicado e o N8N_WEBHOOK_TOKEN confere?"
                )
            if attempt < self._attempts:
                self._sleep(float(min(2 ** (attempt - 1), 8)))
        if status is None:
            raise InboxNotifyError(
                f"Webhook do n8n inacessível após {self._attempts} tentativas. "
                "O n8n está de pé (make up-all)?"
            )
        raise InboxNotifyError(
            f"Webhook do n8n falhou após {self._attempts} tentativas (HTTP {status})."
        )


# ------------------------------------------------------------------ adaptador: banco


def libpq_url(database_url: str) -> str:
    """DATABASE_URL vem no formato do SQLAlchemy (postgresql+psycopg://); o psycopg usa libpq."""
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


class PostgresInboxStore:  # pragma: no cover - coberto por tests/integration/test_inbox_store.py
    """As duas consultas do watcher, com uma conexão curta por operação (eventos são raros)."""

    def __init__(self, dsn: str, schema: str = "ops") -> None:
        if not schema.isidentifier():
            raise ValueError(f"Nome de schema inválido: {schema!r}")
        self._dsn = dsn
        self._schema = schema

    def registered_name(self, sha256: str) -> str | None:
        sql = f"select nome_arquivo from {self._schema}.documentos where sha256 = %s"  # noqa: S608
        row = self._execute(sql, (sha256,))
        return str(row[0]) if row else None

    def record_failure(self, error: BaseException) -> None:
        message = mask_sensitive(f"{type(error).__name__}: {error}")[:MAX_ERROR_LENGTH]
        sql = (
            f"insert into {self._schema}.pipeline_runs "  # noqa: S608
            "(pipeline, status, finished_at, rows_in, rows_out, error) "
            "values (%s, 'ERRO', now(), 1, 0, %s) returning id"
        )
        self._execute(sql, (PIPELINE, message))

    def _execute(self, sql: str, params: tuple[object, ...]) -> tuple[object, ...] | None:
        try:
            with psycopg.connect(
                self._dsn, connect_timeout=DB_TIMEOUT_SECONDS, autocommit=True
            ) as conn:
                return conn.execute(sql, params).fetchone()
        except psycopg.Error as exc:
            raise InboxStoreError(type(exc).__name__) from exc


# ------------------------------------------------------------------ montagem e entrada


def watch_inbox(  # pragma: no cover - liga observador, banco e rede reais (teste ponta a ponta)
    settings: Settings, stop: threading.Event, poll_interval: float, min_interval: float
) -> None:
    """Monta as peças reais e roda até `stop` ser acionado (ou Ctrl+C)."""
    token = settings.n8n_webhook_token.get_secret_value() if settings.n8n_webhook_token else None
    if token is None:
        logger.warning("N8N_WEBHOOK_TOKEN vazio: o webhook será chamado sem autenticação")
    store = PostgresInboxStore(libpq_url(settings.database_url.get_secret_value()))
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    watcher = InboxWatcher(
        inbox=settings.inbox_dir,
        duplicates_dir=settings.processed_dir / "duplicados",
        known=store,
        notifier=WebhookNotifier(settings.n8n_webhook_url, token),
        runs=store,
        min_interval=min_interval,
    )
    observer = start_observer(watcher, settings.inbox_dir)
    logger.info("observando %s (Ctrl+C para parar)", settings.inbox_dir)
    try:
        watcher.scan()
        watcher.run(stop, poll_interval)
    finally:
        observer.stop()
        observer.join(timeout=5)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m flowstream.ingestion.inbox_watcher",
        description="Observa data/inbox e avisa o n8n de cada PDF novo (Ctrl+C para parar).",
    )
    parser.add_argument("--poll", type=float, default=1.0, help="segundos entre leituras")
    parser.add_argument(
        "--stable-seconds", type=float, default=1.0, help="tamanho igual por este tempo = pronto"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Entrada leve do watcher (sem carregar a CLI inteira). Devolve o código de saída."""
    args = _parse_args(argv)
    configure_logging()
    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1
    configure_logging(level=settings.log_level)
    try:
        watch_inbox(settings, threading.Event(), args.poll, args.stable_seconds)
    except KeyboardInterrupt:
        logger.info("watcher encerrado")
    except ValueError as exc:  # configuração inválida detectada ao montar (ex.: URL do webhook)
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

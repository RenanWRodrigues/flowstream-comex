"""Testes da API (TestClient, sem banco): rotas, autenticação, erros RFC 9457 e OpenAPI."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from flowstream.api import dependencies as deps
from flowstream.api.app import create_app
from flowstream.config import Settings
from flowstream.documents.domain import Document, DocumentStatus
from flowstream.operations.domain import ContainerRisk, ContainerTimeline, TrackingEvent

API_KEY = "chave-de-teste"
HEADERS = {"X-API-Key": API_KEY}
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
PROBLEM = "application/problem+json"


class FakeOperations:
    def __init__(self) -> None:
        self.risk_days: list[int] = []

    def find_timeline(self, container_number: str) -> ContainerTimeline | None:
        if container_number != "MSCU1234566":
            return None
        return ContainerTimeline(
            container_numero="MSCU1234566",
            processo="IMP-2026-000123",
            modal="FCL",
            direcao="IMPORTACAO",
            origem="CNSHA",
            destino="BRITJ",
            status="EM_TRANSITO",
            etd=NOW,
            eta=NOW,
            atd=NOW,
            ata=None,
            eventos=[
                TrackingEvent(tipo="EMBARQUE", ocorrido_em=NOW, local="CNSHA", eta_informada=None)
            ],
        )

    def list_demurrage_risk(self, max_days: int) -> list[ContainerRisk]:
        self.risk_days.append(max_days)
        return [
            ContainerRisk(
                processo="IMP-2026-000200",
                container_numero="ATLU0000018",
                armador_codigo="ATL",
                destino="BRITJ",
                data_ata=date(2026, 10, 25),
                free_time_dias=7,
                dias_livres_restantes=1,
                faixa_risco="CRITICO",
                data_referencia=date(2026, 10, 31),
            )
        ]


class FakeDocuments:
    def __init__(self) -> None:
        self.docs: dict[UUID, Document] = {}

    def find_by_sha256(self, sha256: str) -> Document | None:
        return next((d for d in self.docs.values() if d.sha256 == sha256), None)

    def insert(self, nome_arquivo: str, sha256: str, tamanho_bytes: int) -> Document:
        doc = Document(
            id=uuid4(),
            nome_arquivo=nome_arquivo,
            sha256=sha256,
            tamanho_bytes=tamanho_bytes,
            status=DocumentStatus.RECEBIDO,
            recebido_em=NOW,
            atualizado_em=NOW,
        )
        self.docs[doc.id] = doc
        return doc

    def get(self, document_id: UUID) -> Document | None:
        return self.docs.get(document_id)


class SpyProcessor:
    def __init__(self) -> None:
        self.submitted: list[UUID] = []

    def submit(self, document: Document) -> None:
        self.submitted.append(document.id)


class FakeHealth:
    def __init__(self, banco: bool = True, ollama: bool = True) -> None:
        self.state = {"banco": banco, "ollama": ollama}

    def check(self) -> dict[str, bool]:
        return self.state


class Ctx:
    def __init__(self, client: TestClient, inbox: Path) -> None:
        self.client = client
        self.inbox = inbox
        self.operations = FakeOperations()
        self.documents = FakeDocuments()
        self.processor = SpyProcessor()
        self.health = FakeHealth()


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[Ctx]:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "BL_MSCU1234566.pdf").write_bytes(b"%PDF-1.7 ficticio")
    settings = Settings(
        database_url="postgresql+psycopg://x:y@127.0.0.1:5433/z",  # type: ignore[arg-type]
        api_key=API_KEY,  # type: ignore[arg-type]
        inbox_dir=inbox,
        _env_file=None,  # type: ignore[call-arg]
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        context = Ctx(client, inbox)
        app.dependency_overrides[deps.get_api_settings] = lambda: settings
        app.dependency_overrides[deps.get_operations_repository] = lambda: context.operations
        app.dependency_overrides[deps.get_document_repository] = lambda: context.documents
        app.dependency_overrides[deps.get_document_processor] = lambda: context.processor
        app.dependency_overrides[deps.get_health_checker] = lambda: context.health
        yield context


def assert_problem(response: object, status: int) -> dict[str, object]:
    assert response.status_code == status  # type: ignore[attr-defined]
    assert response.headers["content-type"].startswith(PROBLEM)  # type: ignore[attr-defined]
    body: dict[str, object] = response.json()  # type: ignore[attr-defined]
    assert body["status"] == status
    assert {"type", "title", "detail"} <= set(body)
    assert "Traceback" not in str(body)
    return body


# ------------------------------------------------------------------ health


def test_health_is_public_and_reports_dependencies(ctx: Ctx) -> None:
    response = ctx.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "banco": "ok", "ollama": "ok"}


def test_health_without_ollama_is_degraded_but_up(ctx: Ctx) -> None:
    ctx.health.state["ollama"] = False

    response = ctx.client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degradado"
    assert response.json()["ollama"] == "indisponivel"


def test_health_without_database_is_unavailable(ctx: Ctx) -> None:
    ctx.health.state["banco"] = False

    response = ctx.client.get("/health")

    assert response.status_code == 503
    assert response.json()["banco"] == "indisponivel"


# ------------------------------------------------------------------ autenticação


@pytest.mark.parametrize(
    "path", ["/v1/tracking/MSCU1234566", "/v1/embarques/risco", f"/v1/documentos/{uuid4()}"]
)
def test_protected_routes_require_api_key(ctx: Ctx, path: str) -> None:
    assert_problem(ctx.client.get(path), 401)
    assert_problem(ctx.client.get(path, headers={"X-API-Key": "errada"}), 401)


def test_post_requires_api_key(ctx: Ctx) -> None:
    assert_problem(ctx.client.post("/v1/documentos", json={"arquivo": "x.pdf"}), 401)


def test_missing_server_key_is_a_configuration_error(ctx: Ctx, tmp_path: Path) -> None:
    no_key = Settings(
        database_url="postgresql+psycopg://x:y@127.0.0.1:5433/z",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )
    ctx.client.app.dependency_overrides[deps.get_api_settings] = lambda: no_key  # type: ignore[attr-defined]

    body = assert_problem(ctx.client.get("/v1/embarques/risco", headers=HEADERS), 503)

    assert "API_KEY" in str(body["detail"])


# ------------------------------------------------------------------ tracking


def test_tracking_returns_the_timeline(ctx: Ctx) -> None:
    response = ctx.client.get("/v1/tracking/mscu 123456-6", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["container_numero"] == "MSCU1234566"
    assert body["processo"] == "IMP-2026-000123"
    assert body["eventos"][0]["tipo"] == "EMBARQUE"


def test_tracking_rejects_invalid_container_with_422(ctx: Ctx) -> None:
    body = assert_problem(ctx.client.get("/v1/tracking/MSCU1234565", headers=HEADERS), 422)

    assert "ISO 6346" in str(body["detail"])


def test_tracking_unknown_container_is_404(ctx: Ctx) -> None:
    assert_problem(ctx.client.get("/v1/tracking/CSQU3054383", headers=HEADERS), 404)


# ------------------------------------------------------------------ risco de demurrage


def test_risk_defaults_to_3_days(ctx: Ctx) -> None:
    response = ctx.client.get("/v1/embarques/risco", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert ctx.operations.risk_days == [3]
    assert body["dias"] == 3
    assert body["total"] == 1
    assert body["conteineres"][0]["faixa_risco"] == "CRITICO"


def test_risk_accepts_custom_window(ctx: Ctx) -> None:
    ctx.client.get("/v1/embarques/risco?dias=7", headers=HEADERS)

    assert ctx.operations.risk_days == [7]


@pytest.mark.parametrize("dias", ["-1", "61", "tres"])
def test_risk_rejects_invalid_window(ctx: Ctx, dias: str) -> None:
    assert_problem(ctx.client.get(f"/v1/embarques/risco?dias={dias}", headers=HEADERS), 422)


# ------------------------------------------------------------------ documentos


def test_post_document_returns_202_with_id_and_location(ctx: Ctx) -> None:
    response = ctx.client.post(
        "/v1/documentos", json={"arquivo": "BL_MSCU1234566.pdf"}, headers=HEADERS
    )

    assert response.status_code == 202
    body = response.json()
    document_id = UUID(body["id"])
    assert body["status"] == "RECEBIDO"
    assert response.headers["location"] == f"/v1/documentos/{document_id}"
    assert ctx.processor.submitted == [document_id]


@pytest.mark.parametrize(
    "name", ["../../etc/passwd", "..\\..\\Windows\\win.ini", "/etc/passwd", "sub/x.pdf", "x.txt"]
)
def test_post_document_rejects_paths_outside_inbox_with_400(ctx: Ctx, name: str) -> None:
    body = assert_problem(
        ctx.client.post("/v1/documentos", json={"arquivo": name}, headers=HEADERS), 400
    )

    assert ctx.processor.submitted == []
    assert "passwd" not in str(body["detail"])  # não ecoa o caminho recebido


def test_post_document_missing_file_is_404(ctx: Ctx) -> None:
    assert_problem(
        ctx.client.post("/v1/documentos", json={"arquivo": "nao_existe.pdf"}, headers=HEADERS),
        404,
    )


def test_post_same_document_twice_is_409_with_existing_id(ctx: Ctx) -> None:
    first = ctx.client.post(
        "/v1/documentos", json={"arquivo": "BL_MSCU1234566.pdf"}, headers=HEADERS
    )

    body = assert_problem(
        ctx.client.post("/v1/documentos", json={"arquivo": "BL_MSCU1234566.pdf"}, headers=HEADERS),
        409,
    )

    assert body["documento_id"] == first.json()["id"]


@pytest.mark.parametrize("payload", [{}, {"arquivo": ""}, {"nome": "x.pdf"}, {"arquivo": 123}])
def test_post_document_validates_body(ctx: Ctx, payload: dict[str, object]) -> None:
    status = ctx.client.post("/v1/documentos", json=payload, headers=HEADERS).status_code

    assert status in (400, 422)


def test_get_document_status(ctx: Ctx) -> None:
    created = ctx.client.post(
        "/v1/documentos", json={"arquivo": "BL_MSCU1234566.pdf"}, headers=HEADERS
    ).json()

    response = ctx.client.get(f"/v1/documentos/{created['id']}", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "RECEBIDO"
    assert body["arquivo"] == "BL_MSCU1234566.pdf"
    assert body["resultado"] is None


def test_get_unknown_document_is_404(ctx: Ctx) -> None:
    assert_problem(ctx.client.get(f"/v1/documentos/{uuid4()}", headers=HEADERS), 404)


def test_get_document_with_invalid_id_is_422(ctx: Ctx) -> None:
    assert_problem(ctx.client.get("/v1/documentos/123", headers=HEADERS), 422)


# ------------------------------------------------------------------ erros e OpenAPI


def test_unknown_route_is_a_problem(ctx: Ctx) -> None:
    assert_problem(ctx.client.get("/v1/nao-existe", headers=HEADERS), 404)


def test_unexpected_error_hides_details(ctx: Ctx) -> None:
    class Broken(FakeOperations):
        def list_demurrage_risk(self, max_days: int) -> list[ContainerRisk]:
            raise RuntimeError("senha=segredo no stack trace")

    ctx.client.app.dependency_overrides[deps.get_operations_repository] = Broken  # type: ignore[attr-defined]

    body = assert_problem(ctx.client.get("/v1/embarques/risco", headers=HEADERS), 500)

    assert "segredo" not in str(body)


def test_openapi_documents_every_route_in_portuguese(ctx: Ctx) -> None:
    schema = ctx.client.get("/openapi.json").json()

    assert {
        "/health",
        "/v1/tracking/{container_number}",
        "/v1/embarques/risco",
        "/v1/documentos",
        "/v1/documentos/{documento_id}",
    } <= set(schema["paths"])
    assert "contêiner" in schema["paths"]["/v1/tracking/{container_number}"]["get"]["description"]
    assert ctx.client.get("/docs").status_code == 200


# ------------------------------------------------------------------ verificação real de saúde


def test_ollama_check_ignores_environment_proxies() -> None:
    """Serviços locais (127.0.0.1) não passam por proxy: com proxy no ambiente, a chamada
    ao Ollama ficaria pendurada (visto ao subir a API num ambiente com proxy)."""
    checker = deps.SystemHealthChecker("http://127.0.0.1:11434")

    assert checker.http.trust_env is False


@pytest.mark.parametrize(("status", "expected"), [(200, True), (500, False)])
def test_ollama_check_reads_api_tags(status: int, expected: bool) -> None:
    import respx

    with respx.mock:
        respx.get("http://127.0.0.1:11434/api/tags").respond(status)
        assert deps.SystemHealthChecker("http://127.0.0.1:11434/")._ollama() is expected


def test_ollama_down_is_reported_not_raised() -> None:
    import httpx
    import respx

    with respx.mock:
        respx.get("http://127.0.0.1:11434/api/tags").mock(side_effect=httpx.ConnectError("x"))
        assert deps.SystemHealthChecker("http://127.0.0.1:11434")._ollama() is False

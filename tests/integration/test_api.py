"""API contra o Postgres de verdade: leitura da camada ouro e documentos num schema temporário."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from flowstream.api import dependencies as deps
from flowstream.api.app import create_app
from flowstream.config import Settings, load_settings
from flowstream.db import PostgresMigrationStore, create_db_engine, migrate
from flowstream.documents.adapters import PostgresDocumentRepository
from flowstream.documents.service import NotYetAvailableProcessor
from flowstream.operations.adapters import PostgresOperationsRepository

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "ops_teste_api"
HEADERS = {"X-API-Key": "chave-integracao"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    db_engine = create_db_engine(load_settings())
    migrate(ROOT / "infra" / "migrations", store=PostgresMigrationStore(db_engine))
    with db_engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA} cascade"))
        conn.execute(text(f"create schema {SCHEMA}"))
        conn.execute(text(f"create table {SCHEMA}.documentos (like ops.documentos including all)"))
    yield db_engine
    with db_engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA} cascade"))
    db_engine.dispose()


@pytest.fixture
def client(engine: Engine, tmp_path: Path) -> Iterator[TestClient]:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "AWB_020-12345675.pdf").write_bytes(b"%PDF-1.7 integracao")
    settings = Settings(
        database_url=load_settings().database_url,
        api_key="chave-integracao",  # type: ignore[arg-type]
        inbox_dir=inbox,
        _env_file=None,  # type: ignore[call-arg]
    )
    app = create_app()
    app.dependency_overrides[deps.get_api_settings] = lambda: settings
    app.dependency_overrides[deps.get_operations_repository] = lambda: PostgresOperationsRepository(
        engine
    )
    app.dependency_overrides[deps.get_document_repository] = lambda: PostgresDocumentRepository(
        engine, schema=SCHEMA
    )
    app.dependency_overrides[deps.get_document_processor] = NotYetAvailableProcessor
    with TestClient(app) as test_client:
        yield test_client


def a_real_container(engine: Engine) -> str:
    with engine.connect() as conn:
        number: str = conn.execute(
            text(
                "select eq.container_numero from prata.stg_equipamentos eq "
                "join ouro.fct_embarque f using (processo) where f.ata is not null limit 1"
            )
        ).scalar_one()
    return number


def test_tracking_reads_the_gold_layer(client: TestClient, engine: Engine) -> None:
    number = a_real_container(engine)

    response = client.get(f"/v1/tracking/{number.lower()}", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["container_numero"] == number
    tipos = [e["tipo"] for e in body["eventos"]]
    assert tipos[0] == "BOOKING_CONFIRMADO"
    assert "CHEGADA" in tipos


def test_valid_but_unknown_container_is_404(client: TestClient) -> None:
    assert client.get("/v1/tracking/CSQU3054383", headers=HEADERS).status_code == 404


def test_risk_reads_the_kpi(client: TestClient) -> None:
    response = client.get("/v1/embarques/risco?dias=60", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(body["conteineres"]) > 0
    restantes = [c["dias_livres_restantes"] for c in body["conteineres"]]
    assert restantes == sorted(restantes)


def test_document_round_trip_in_isolated_schema(client: TestClient, engine: Engine) -> None:
    created = client.post(
        "/v1/documentos", json={"arquivo": "AWB_020-12345675.pdf"}, headers=HEADERS
    )
    duplicate = client.post(
        "/v1/documentos", json={"arquivo": "AWB_020-12345675.pdf"}, headers=HEADERS
    )
    fetched = client.get(created.headers["location"], headers=HEADERS)

    assert created.status_code == 202
    assert duplicate.status_code == 409
    assert fetched.json()["status"] == "RECEBIDO"
    with engine.connect() as conn:
        real = conn.execute(
            text("select count(*) from ops.documentos where nome_arquivo = 'AWB_020-12345675.pdf'")
        ).scalar_one()
    assert real == 0  # nada vazou para o ops de verdade


def test_traversal_is_rejected_before_touching_the_database(client: TestClient) -> None:
    response = client.post("/v1/documentos", json={"arquivo": "../../etc/passwd"}, headers=HEADERS)

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")

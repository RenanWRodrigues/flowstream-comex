"""Gravação da extração em ops.extracoes e do status em ops.documentos (schema temporário)."""

import json
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine, text

from flowstream.ai.adapters import PostgresExtractionStore
from flowstream.ai.pipeline import ExtractionResult, Outcome
from flowstream.ai.schemas import BillOfLading, DocumentType
from flowstream.ai.validators import Divergence, Rule, Severity
from flowstream.config import load_settings
from flowstream.db import PostgresMigrationStore, create_db_engine, migrate

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "ops_teste_ai"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    db_engine = create_db_engine(load_settings())
    migrate(ROOT / "infra" / "migrations", store=PostgresMigrationStore(db_engine))
    with db_engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA} cascade"))
        conn.execute(text(f"create schema {SCHEMA}"))
        conn.execute(text(f"create table {SCHEMA}.documentos (like ops.documentos including all)"))
        conn.execute(text(f"create table {SCHEMA}.extracoes (like ops.extracoes including all)"))
    yield db_engine
    with db_engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA} cascade"))
    db_engine.dispose()


@pytest.fixture
def document_id(engine: Engine) -> UUID:
    with engine.begin() as conn:
        value = conn.execute(
            text(
                f"insert into {SCHEMA}.documentos (nome_arquivo, sha256, tamanho_bytes) "  # noqa: S608
                "values ('bl.pdf', md5(random()::text) || md5(random()::text), 10) returning id"
            )
        ).scalar_one()
    return UUID(str(value))


def _bl() -> BillOfLading:
    empty = {"valor": None, "evidence": None}
    payload = {
        name: ([] if name in ("conteineres", "ncm") else empty)
        for name in BillOfLading.model_fields
    }
    payload["numero_bl"] = {"valor": "MAEU2409001234", "evidence": "B/L No.: MAEU2409001234"}
    return BillOfLading.model_validate(payload)


def _status(engine: Engine, document_id: UUID) -> tuple[str, str | None, object, str | None]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"select status, tipo_documento, resultado, erro from {SCHEMA}.documentos "  # noqa: S608
                "where id = :id"
            ),
            {"id": document_id},
        ).one()
    return row.status, row.tipo_documento, row.resultado, row.erro


def test_mark_processing(engine: Engine, document_id: UUID) -> None:
    PostgresExtractionStore(engine, SCHEMA).mark_processing(document_id)
    assert _status(engine, document_id)[0] == "PROCESSANDO"


def test_save_review_writes_extraction_and_document(engine: Engine, document_id: UUID) -> None:
    result = ExtractionResult(
        Outcome.REVISAO,
        DocumentType.BL,
        score=0.42,
        documento=_bl(),
        divergencias=[Divergence(Rule.AUSENTE, "navio", Severity.AVISO, "campo ausente")],
        modelo="qwen2.5:3b",
        tentativas=1,
        duracao_ms=1234,
        paginas_ocr=1,
    )
    PostgresExtractionStore(engine, SCHEMA).save(document_id, result)

    status, tipo, resultado, erro = _status(engine, document_id)
    assert (status, tipo, erro) == ("REVISAO", "BL", None)
    assert resultado["numero_bl"] == "MAEU2409001234"  # type: ignore[index]
    with engine.connect() as conn:
        row = conn.execute(
            text(f"select * from {SCHEMA}.extracoes where documento_id = :id"),  # noqa: S608
            {"id": document_id},
        ).one()
    assert row.decisao == "REVISAO"
    assert float(row.score) == 0.42
    assert row.evidencias["numero_bl"] == "B/L No.: MAEU2409001234"
    assert row.divergencias == [
        {"regra": "AUSENTE", "campo": "navio", "gravidade": "AVISO", "mensagem": "campo ausente"}
    ]
    assert (row.prompt_versao, row.modelo, row.tentativas) == ("v1", "qwen2.5:3b", 1)
    assert (row.duracao_ms, row.paginas_ocr) == (1234, 1)


def test_save_error_keeps_a_short_masked_message(engine: Engine, document_id: UUID) -> None:
    message = "Ollama indisponível; CNPJ 12.345.678/0001-95 " + "x" * 600
    result = ExtractionResult(Outcome.ERRO, None, erro=message)
    PostgresExtractionStore(engine, SCHEMA).save(document_id, result)
    status, tipo, resultado, erro = _status(engine, document_id)
    assert (status, tipo, resultado) == ("ERRO", None, None)
    assert erro is not None and len(erro) <= 500
    assert "12.345.678" not in erro


def test_database_refuses_approval_below_threshold(engine: Engine, document_id: UUID) -> None:
    """Defesa em profundidade: mesmo com bug no código, o banco não aceita APROVADO < 0,90."""
    bad = ExtractionResult(Outcome.APROVADO, DocumentType.BL, score=0.5, documento=_bl())
    with pytest.raises(Exception, match="extracoes_aprovado_check"):
        PostgresExtractionStore(engine, SCHEMA).save(document_id, bad)
    assert json.dumps(_status(engine, document_id)[0]) != '"APROVADO"'


def test_mark_error_and_pending_documents(engine: Engine, document_id: UUID) -> None:
    store = PostgresExtractionStore(engine, SCHEMA)
    store.mark_processing(document_id)
    assert document_id in {d.id for d in store.pending_documents(limit=1000)}
    store.mark_error(document_id, "falha ao gravar o resultado da extração")
    assert _status(engine, document_id)[0] == "ERRO"
    assert document_id not in {d.id for d in store.pending_documents(limit=1000)}

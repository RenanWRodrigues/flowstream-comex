"""Gravação da avaliação do agente em ops.avaliacoes_ia (schema temporário)."""

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from flowstream.ai.adapters import PostgresEvaluationStore, load_ground_truths
from flowstream.ai.evaluation import EvaluationReport, evaluate_case, summarize
from flowstream.ai.pipeline import ExtractionResult, Outcome
from flowstream.config import load_settings
from flowstream.db import PostgresMigrationStore, create_db_engine, migrate
from flowstream.domain.dates import SAO_PAULO

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "ops_teste_avaliacao"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    db_engine = create_db_engine(load_settings())
    migrate(ROOT / "infra" / "migrations", store=PostgresMigrationStore(db_engine))
    with db_engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA} cascade"))
        conn.execute(text(f"create schema {SCHEMA}"))
        conn.execute(
            text(f"create table {SCHEMA}.avaliacoes_ia (like ops.avaliacoes_ia including all)")
        )
    yield db_engine
    with db_engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA} cascade"))
    db_engine.dispose()


def _report() -> EvaluationReport:
    cases = load_ground_truths(ROOT / "tests" / "eval" / "documentos")[:2]
    evaluated = [
        evaluate_case(truth, ExtractionResult(Outcome.REVISAO, None, duracao_ms=900))
        for _path, truth in cases
    ]
    return summarize(
        evaluated,
        prompt_versao="v1",
        modelo="qwen2.5:3b",
        conjunto_sha256="c" * 64,
        when=datetime(2026, 11, 5, 10, 0, tzinfo=SAO_PAULO),
    )


def test_saves_metrics_and_details(engine: Engine) -> None:
    report = _report()
    evaluation_id = PostgresEvaluationStore(engine, schema=SCHEMA).save(report)
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(f"select * from {SCHEMA}.avaliacoes_ia where id = :id"),  # noqa: S608
                {"id": evaluation_id},
            )
            .mappings()
            .one()
        )
    assert row["prompt_versao"] == "v1"
    assert row["modelo"] == "qwen2.5:3b"
    assert row["documentos"] == 2
    assert float(row["acuracia_normalizada"]) == report.acuracia_normalizada
    assert row["recall_erros"] is None  # os 2 primeiros documentos não têm erro plantado
    assert row["executado_em"] == report.executado_em
    details = row["detalhes"]
    assert len(details["por_documento"]) == 2
    assert "Ltda" not in json.dumps(details)  # nenhum valor extraído vai para o banco


def test_history_is_kept(engine: Engine) -> None:
    store = PostgresEvaluationStore(engine, schema=SCHEMA)
    first, second = store.save(_report()), store.save(_report())
    assert second > first


def test_ratio_outside_0_1_is_refused(engine: Engine) -> None:
    import dataclasses

    broken = dataclasses.replace(_report(), taxa_alucinacao=1.5)
    with pytest.raises(IntegrityError):
        PostgresEvaluationStore(engine, schema=SCHEMA).save(broken)

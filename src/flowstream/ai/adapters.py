"""Gravação das extrações (ops.extracoes, ops.documentos) e da avaliação do agente
(conjunto de gabaritos em disco, ops.avaliacoes_ia e docs/ia_avaliacao.md)."""

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Engine, text

from flowstream.ai.evaluation import EvaluationReport, GroundTruth, update_history
from flowstream.ai.pipeline import ExtractionResult
from flowstream.db import transaction
from flowstream.documents.domain import Document
from flowstream.logging import mask_sensitive

MAX_ERROR_LENGTH = 500
_SAFE_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]*$")


class PostgresExtractionStore:
    """`schema` existe para os testes de integração usarem uma cópia isolada de ops."""

    def __init__(self, engine: Engine, schema: str = "ops") -> None:
        if not _SAFE_SCHEMA.match(schema):
            raise ValueError(f"Nome de schema inválido: {schema!r}")
        self._engine = engine
        self._schema = schema

    def mark_processing(self, document_id: UUID) -> None:
        with transaction(self._engine) as conn:
            conn.execute(
                text(
                    f"update {self._schema}.documentos set status = 'PROCESSANDO', "  # noqa: S608
                    "atualizado_em = now() where id = :id"
                ),
                {"id": document_id},
            )

    def save(self, document_id: UUID, result: ExtractionResult) -> None:
        """Uma transação: a linha da extração e o status/resultado do documento."""
        error = mask_sensitive(result.erro)[:MAX_ERROR_LENGTH] if result.erro else None
        campos = result.campos() if result.documento else None
        params: dict[str, Any] = {
            "documento_id": document_id,
            "tipo": result.tipo.value if result.tipo else None,
            "decisao": result.outcome.value,
            "score": result.score,
            "campos": _json(campos),
            "evidencias": _json(result.evidencias() if result.documento else None),
            "divergencias": json.dumps(
                [d.to_dict() for d in result.divergencias], ensure_ascii=False
            ),
            "prompt_versao": result.prompt_versao,
            "modelo": result.modelo,
            "tentativas": result.tentativas,
            "duracao_ms": result.duracao_ms,
            "paginas_ocr": result.paginas_ocr,
            "erro": error,
        }
        with transaction(self._engine) as conn:
            conn.execute(
                text(
                    f"insert into {self._schema}.extracoes "  # noqa: S608
                    "(documento_id, tipo_documento, decisao, score, campos, evidencias, "
                    "divergencias, prompt_versao, modelo, tentativas, duracao_ms, paginas_ocr) "
                    "values (:documento_id, :tipo, :decisao, :score, cast(:campos as jsonb), "
                    "cast(:evidencias as jsonb), cast(:divergencias as jsonb), :prompt_versao, "
                    ":modelo, :tentativas, :duracao_ms, :paginas_ocr)"
                ),
                params,
            )
            conn.execute(
                text(
                    f"update {self._schema}.documentos set status = :decisao, "  # noqa: S608
                    "tipo_documento = :tipo, resultado = cast(:campos as jsonb), erro = :erro, "
                    "atualizado_em = now() where id = :documento_id"
                ),
                params,
            )

    def mark_error(self, document_id: UUID, message: str) -> None:
        """Último recurso quando `save` falhou: o documento não fica preso em PROCESSANDO."""
        with transaction(self._engine) as conn:
            conn.execute(
                text(
                    f"update {self._schema}.documentos set status = 'ERRO', erro = :erro, "  # noqa: S608
                    "atualizado_em = now() where id = :id"
                ),
                {"id": document_id, "erro": mask_sensitive(message)[:MAX_ERROR_LENGTH]},
            )

    def pending_documents(self, limit: int) -> list[Document]:
        """RECEBIDO ou PROCESSANDO (este último ficou de um reinício), mais antigos primeiro."""
        sql = (
            "select id, nome_arquivo, sha256, tamanho_bytes, status, tipo_documento, resultado, "  # noqa: S608
            f"erro, recebido_em, atualizado_em from {self._schema}.documentos "
            "where status in ('RECEBIDO', 'PROCESSANDO') order by recebido_em limit :limit"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), {"limit": limit}).mappings().all()
        return [Document(**row) for row in rows]


def _json(value: object) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


# ------------------------------------------------------------------ avaliação (P11)


class DatasetError(ValueError):
    """O conjunto de avaliação não existe, está vazio ou tem gabarito inválido."""


def load_ground_truths(directory: Path) -> list[tuple[Path, GroundTruth]]:
    """Pares (PDF, gabarito) da pasta, em ordem de nome. Cada <id>.json aponta <id>.pdf."""
    if not directory.is_dir():
        raise DatasetError(f"A pasta do conjunto de avaliação não existe: {directory}")
    files = sorted(directory.glob("*.json"))
    if not files:
        raise DatasetError(f"nenhum gabarito (*.json) em {directory}")
    return [_load_case(file) for file in files]


def _load_case(file: Path) -> tuple[Path, GroundTruth]:
    try:
        truth = GroundTruth.model_validate_json(file.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise DatasetError(f"gabarito inválido em {file.name}: {exc}") from None
    if truth.arquivo != file.with_suffix(".pdf").name:
        raise DatasetError(f"{file.name} aponta {truth.arquivo}; o PDF precisa ter o mesmo nome")
    pdf = file.with_suffix(".pdf")
    if not pdf.is_file():
        raise DatasetError(f"falta o PDF {pdf.name} do gabarito {file.name}")
    return pdf, truth


def dataset_digest(cases: Sequence[tuple[Path, GroundTruth]]) -> str:
    """SHA-256 dos PDFs e gabaritos: duas avaliações só se comparam com o mesmo conjunto."""
    digest = hashlib.sha256()
    for pdf, _truth in sorted(cases, key=lambda case: case[0].name):
        for path in (pdf.with_suffix(".json"), pdf):
            digest.update(path.name.encode("utf-8") + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def update_history_file(path: Path, report: EvaluationReport) -> None:
    """Acrescenta a execução ao histórico de docs/ia_avaliacao.md (as linhas antigas ficam)."""
    updated = update_history(path.read_text(encoding="utf-8"), report)
    path.write_text(updated, encoding="utf-8", newline="\n")


class PostgresEvaluationStore:
    """Grava cada execução em ops.avaliacoes_ia. `schema` isola os testes de integração."""

    def __init__(self, engine: Engine, schema: str = "ops") -> None:
        if not _SAFE_SCHEMA.match(schema):
            raise ValueError(f"Nome de schema inválido: {schema!r}")
        self._engine = engine
        self._schema = schema

    def save(self, report: EvaluationReport) -> int:
        columns = list(_EVALUATION_COLUMNS)
        params: dict[str, Any] = {name: getattr(report, name) for name in columns}
        params["detalhes"] = json.dumps(report.detalhes(), ensure_ascii=False)
        placeholders = ", ".join(f":{name}" for name in columns)
        sql = (
            f"insert into {self._schema}.avaliacoes_ia ({', '.join(columns)}, detalhes) "  # noqa: S608
            f"values ({placeholders}, cast(:detalhes as jsonb)) returning id"
        )
        with transaction(self._engine) as conn:
            return int(conn.execute(text(sql), params).scalar_one())


_EVALUATION_COLUMNS = (
    "executado_em",
    "prompt_versao",
    "modelo",
    "conjunto_sha256",
    "documentos",
    "classificacao_correta",
    "acuracia_exata",
    "acuracia_normalizada",
    "acuracia_criticos",
    "acuracia_preenchidos",
    "taxa_alucinacao",
    "recall_erros",
    "injecoes",
    "injecoes_aprovadas",
    "aprovacoes_indevidas",
    "aprovados_com_critico_errado",
    "taxa_aprovacao_automatica",
    "erros_tecnicos",
    "tempo_medio_ms",
    "tempo_p95_ms",
)

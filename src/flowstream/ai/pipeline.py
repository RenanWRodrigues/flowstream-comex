"""Pipeline do agente: texto -> tipo -> LLM -> JSON -> Pydantic (1 nova tentativa) ->
validadores -> score -> decisão.

O modelo só EXTRAI. Quem decide APROVADO/REVISAO são os validadores e o score; o texto do
documento e a resposta do modelo nunca mudam a regra.
"""

import dataclasses
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from flowstream.ai.classifier import ClassificationMethod, classify
from flowstream.ai.llm import LLMClient, LLMError
from flowstream.ai.pdf_text import (
    OcrEngine,
    OcrUnavailableError,
    PageText,
    PdfReadError,
    extract_pages,
    full_text,
    page_texts,
)
from flowstream.ai.prompting import (
    PROMPT_VERSION,
    check_prompt_version,
    describe_validation_error,
    retry_prompt,
    system_prompt,
    wrap_document,
)
from flowstream.ai.schemas import (
    DOCUMENT_MODELS,
    DocumentType,
    Extracted,
    ExtractedDocument,
    FieldClass,
    field_class,
    parse_llm_json,
)
from flowstream.ai.scoring import Decision, decide, score_document
from flowstream.ai.validators import (
    Divergence,
    Rule,
    Severity,
    check_cross,
    validate_document,
)
from flowstream.domain.dates import now_sao_paulo
from flowstream.logging import get_logger

logger = get_logger(__name__)

# ~4096 tokens de contexto: prompt de sistema + schema ocupam ~1.500; o resto é do documento.
MAX_DOCUMENT_CHARS = 6000
MAX_ATTEMPTS = 2  # a resposta original e uma nova tentativa com a mensagem de erro
MAX_LLM_PAGES = 6  # documento longo: no máximo 6 chamadas (x2 tentativas) por documento

# Quais documentos uma divergência de cruzamento envolve (pelo nome do campo).
_CROSS_INVOLVES: dict[str, frozenset[DocumentType]] = {
    "peso_bruto_total_kg": frozenset(
        {DocumentType.BL, DocumentType.AWB, DocumentType.PACKING_LIST}
    ),
    "volumes_total": frozenset({DocumentType.BL, DocumentType.AWB, DocumentType.PACKING_LIST}),
    "conteineres": frozenset({DocumentType.BL, DocumentType.PACKING_LIST}),
    "numero_invoice": frozenset({DocumentType.PACKING_LIST, DocumentType.INVOICE}),
    "importador": frozenset({DocumentType.PACKING_LIST, DocumentType.INVOICE}),
}


class Outcome(StrEnum):
    APROVADO = "APROVADO"
    REVISAO = "REVISAO"
    ERRO = "ERRO"  # falha técnica (PDF ilegível, OCR ou Ollama fora): tentar de novo depois


@dataclass(frozen=True)
class ExtractionResult:
    outcome: Outcome
    tipo: DocumentType | None
    score: float | None = None
    documento: ExtractedDocument | None = None
    divergencias: list[Divergence] = field(default_factory=list)
    prompt_versao: str = PROMPT_VERSION
    modelo: str | None = None
    tentativas: int = 0
    duracao_ms: int = 0
    paginas_ocr: int = 0
    metodo_classificacao: ClassificationMethod = ClassificationMethod.NENHUM
    erro: str | None = None

    def campos(self) -> dict[str, Any]:
        """Valores extraídos (JSON), na mesma forma do schema."""
        return _project(self.documento, "valor") if self.documento else {}

    def evidencias(self) -> dict[str, Any]:
        """Trecho literal de cada valor, na mesma forma do schema."""
        return _project(self.documento, "evidence") if self.documento else {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisao": self.outcome.value,
            "tipo_documento": self.tipo.value if self.tipo else None,
            "score": self.score,
            "campos": self.campos(),
            "evidencias": self.evidencias(),
            "divergencias": [d.to_dict() for d in self.divergencias],
            "prompt_versao": self.prompt_versao,
            "modelo": self.modelo,
            "tentativas": self.tentativas,
            "duracao_ms": self.duracao_ms,
            "paginas_ocr": self.paginas_ocr,
            "metodo_classificacao": self.metodo_classificacao.value,
            "erro": self.erro,
        }


def _project(doc: BaseModel, key: str) -> dict[str, Any]:
    dumped = doc.model_dump(mode="json")
    return cast(dict[str, Any], _pick(dumped, key))


def _pick(node: Any, key: str) -> Any:
    if isinstance(node, dict) and set(node) == {"valor", "evidence"}:
        return node[key]
    if isinstance(node, dict):
        return {name: _pick(value, key) for name, value in node.items()}
    if isinstance(node, list):
        return [_pick(item, key) for item in node]
    return node


class _TooLongError(Exception):
    """O documento não cabe no contexto do modelo sem truncar."""


class _StructureError(Exception):
    """A resposta do modelo não virou um documento válido nem na nova tentativa."""

    def __init__(self, message: str, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class ExtractionPipeline:
    def __init__(
        self,
        llm: LLMClient,
        ocr: OcrEngine | None,
        today: Callable[[], date] = lambda: now_sao_paulo().date(),
        clock: Callable[[], float] = time.monotonic,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        check_prompt_version(prompt_version)  # versão inexistente falha antes de ler PDF
        self._prompt_version = prompt_version
        self._llm = llm
        self._ocr = ocr
        self._today = today
        self._clock = clock

    @property
    def llm(self) -> LLMClient:
        return self._llm

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    def extract_file(self, path: Path) -> ExtractionResult:
        started = self._clock()
        try:
            pages = extract_pages(path, self._ocr)
        except (PdfReadError, OcrUnavailableError) as exc:
            return ExtractionResult(
                Outcome.ERRO,
                None,
                erro=str(exc),
                duracao_ms=self._elapsed(started),
                prompt_versao=self._prompt_version,
            )
        return self.extract_pages(pages, started=started)

    def extract_pages(
        self, pages: Sequence[PageText], started: float | None = None
    ) -> ExtractionResult:
        begin = self._clock() if started is None else started
        result = self._run(pages)
        ocr_pages = sum(1 for page in pages if page.ocr)
        result = dataclasses.replace(
            result,
            paginas_ocr=ocr_pages,
            duracao_ms=self._elapsed(begin),
            prompt_versao=self._prompt_version,  # também nos resultados sem extração
        )
        logger.info(
            "extração: tipo=%s decisão=%s score=%s tentativas=%d %d ms",
            result.tipo,
            result.outcome,
            result.score,
            result.tentativas,
            result.duracao_ms,
        )
        return result

    def _run(self, pages: Sequence[PageText]) -> ExtractionResult:
        text = full_text(pages)
        try:
            classification = classify(text, self._llm)
        except LLMError as exc:  # Ollama fora no desempate: falha técnica
            return ExtractionResult(Outcome.ERRO, None, erro=str(exc))
        tipo = classification.tipo
        if tipo is None:
            missing = Divergence(
                Rule.AUSENTE,
                "tipo_documento",
                Severity.CRITICA,
                "tipo do documento não identificado",
            )
            return ExtractionResult(
                Outcome.REVISAO,
                None,
                divergencias=[missing],
                metodo_classificacao=classification.method,
            )
        base = ExtractionResult(
            Outcome.REVISAO,
            tipo,
            modelo=self._llm.model,
            metodo_classificacao=classification.method,
        )
        try:
            document, attempts, merge_divergences = self._extract(tipo, pages, text)
        except LLMError as exc:
            return dataclasses.replace(base, outcome=Outcome.ERRO, erro=str(exc))
        except _TooLongError as exc:
            too_long = Divergence(Rule.ESTRUTURA, "documento", Severity.CRITICA, str(exc))
            return dataclasses.replace(base, divergencias=[too_long])
        except _StructureError as exc:
            structure = Divergence(
                Rule.ESTRUTURA,
                "documento",
                Severity.CRITICA,
                f"resposta do modelo fora do schema: {exc}",
            )
            return dataclasses.replace(base, tentativas=exc.attempts, divergencias=[structure])
        # Grounding no texto das páginas, sem os marcadores '--- página N ---'.
        divergences = validate_document(document, page_texts(pages), self._today())
        divergences += merge_divergences
        hidden = sum(page.hidden_chars for page in pages)
        if hidden:
            divergences.append(
                Divergence(
                    Rule.SUSPEITO,
                    "texto_oculto",
                    Severity.CRITICA,
                    f"{hidden} caracteres invisíveis no PDF (branco, minúsculo ou fora da "
                    "página) foram ignorados: revisão humana obrigatória",
                )
            )
        score = score_document(document, divergences)
        return dataclasses.replace(
            base,
            outcome=Outcome(decide(score, divergences).value),
            score=score,
            documento=document,
            divergencias=divergences,
            tentativas=attempts,
        )

    def _extract(
        self, tipo: DocumentType, pages: Sequence[PageText], text: str
    ) -> tuple[ExtractedDocument, int, list[Divergence]]:
        """Um pedido com o documento inteiro, ou um por página se não couber no contexto.

        Nunca manda ao modelo mais do que cabe: o Ollama truncaria o prompt em silêncio e
        poderia perder o prompt de sistema. Página grande demais ou páginas demais -> REVISAO.
        """
        system = system_prompt(tipo, self._prompt_version)
        if len(text) <= MAX_DOCUMENT_CHARS:
            document, attempts = self._ask(tipo, system, text)
            return document, attempts, []
        if len(pages) > MAX_LLM_PAGES:
            raise _TooLongError(
                f"documento longo ({len(pages)} páginas); a extração automática vai até "
                f"{MAX_LLM_PAGES} páginas"
            )
        for page in pages:
            if len(full_text([page])) > MAX_DOCUMENT_CHARS:
                raise _TooLongError(
                    f"página {page.number} com {len(page.text)} caracteres; o limite por "
                    f"página é {MAX_DOCUMENT_CHARS}"
                )
        parts = [self._ask(tipo, system, full_text([page])) for page in pages]
        merged, conflicts = _merge([doc for doc, _ in parts], tipo)
        return merged, max(attempts for _, attempts in parts), conflicts

    def _ask(self, tipo: DocumentType, system: str, text: str) -> tuple[ExtractedDocument, int]:
        model = DOCUMENT_MODELS[tipo]
        prompt = wrap_document(text)
        current = prompt
        error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            answer = self._llm.generate(system, current)
            try:
                parsed = model.model_validate(parse_llm_json(answer.text))
                return cast(ExtractedDocument, parsed), attempt
            except ValidationError as exc:
                error = describe_validation_error(cast(list[Any], exc.errors()))
            except ValueError as exc:
                error = str(exc)
            current = retry_prompt(prompt, error)
        raise _StructureError(error, MAX_ATTEMPTS)

    def _elapsed(self, started: float) -> int:
        return max(0, int((self._clock() - started) * 1000))


def _merge(
    parts: Sequence[ExtractedDocument], tipo: DocumentType
) -> tuple[ExtractedDocument, list[Divergence]]:
    """Une extrações por página: primeiro valor não nulo de cada campo; listas concatenadas.

    Páginas com valores DIFERENTES para o mesmo campo não são resolvidas em silêncio: viram
    divergência (gravidade pela classe do campo).
    """
    model = DOCUMENT_MODELS[tipo]
    merged: dict[str, Any] = {}
    conflicts: list[Divergence] = []
    for name in model.model_fields:
        values = [getattr(part, name) for part in parts]
        if isinstance(values[0], list):
            merged[name] = [item for value in values for item in value]
            continue
        present = [v for v in values if isinstance(v, Extracted) and not v.is_absent]
        merged[name] = present[0] if present else values[0]
        if len({str(v.valor) for v in present}) > 1:
            critical = field_class(model, name) is FieldClass.CRITICO
            conflicts.append(
                Divergence(
                    Rule.COERENCIA,
                    name,
                    Severity.CRITICA if critical else Severity.AVISO,
                    "páginas diferentes trazem valores diferentes para o campo",
                )
            )
    return cast(ExtractedDocument, model.model_validate(merged)), conflicts


def cross_validate(results: Sequence[ExtractionResult]) -> list[ExtractionResult]:
    """Cruza documentos de UM mesmo processo e rebaixa para REVISAO os envolvidos em
    divergência crítica. Resultados com ERRO ou sem documento passam inalterados.

    Dois documentos do mesmo tipo tornam o processo ambíguo: eles não são cruzados às
    cegas, recebem uma divergência crítica e vão para revisão.
    """
    usable = [r for r in results if r.tipo and r.documento is not None and r.score is not None]
    counts = Counter(r.tipo for r in usable)
    duplicated = {tipo for tipo, count in counts.items() if count > 1}
    documents: dict[DocumentType, ExtractedDocument] = {}
    for r in usable:
        if r.tipo is not None and r.tipo not in duplicated and r.documento is not None:
            documents[r.tipo] = r.documento
    divergences = check_cross(documents)
    if not divergences and not duplicated:
        return list(results)
    updated = []
    for result in results:
        if result not in usable or result.score is None:
            updated.append(result)
            continue
        if result.tipo in duplicated:
            mine = [
                Divergence(
                    Rule.CRUZAMENTO,
                    "tipo_documento",
                    Severity.CRITICA,
                    f"processo com {counts[result.tipo]} documentos do tipo "
                    f"{result.tipo}; cruzamento não é confiável",
                )
            ]
        else:
            involved = _CROSS_INVOLVES
            mine = [d for d in divergences if result.tipo in involved.get(d.campo, frozenset())]
        all_divergences = [*result.divergencias, *mine]
        decision = decide(result.score, all_divergences)
        outcome = Outcome.APROVADO if decision is Decision.APROVADO else Outcome.REVISAO
        updated.append(dataclasses.replace(result, divergencias=all_divergences, outcome=outcome))
    return updated

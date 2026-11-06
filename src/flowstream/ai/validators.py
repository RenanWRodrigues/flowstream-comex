"""Validadores da extração: formato, coerência, grounding, cruzamento e texto suspeito.

Saída de LLM é dado não confiável. Cada validador devolve divergências; a gravidade segue a
classe do campo (crítico -> CRITICA, que força REVISAO). As mensagens nunca copiam o texto
do documento: só nome do campo e regra.
"""

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError
from rapidfuzz import fuzz

from flowstream.ai.schemas import (
    AirWaybill,
    BillOfLading,
    CommercialInvoice,
    DocumentType,
    Extracted,
    ExtractedDocument,
    FieldClass,
    PackingList,
    field_class,
    is_list_field,
)
from flowstream.domain.identifiers import (
    CNPJ,
    NCM,
    ContainerNumber,
    IATACode,
    UNLocode,
)
from flowstream.domain.identifiers import (
    AirWaybill as AWBNumber,
)

GROUNDING_THRESHOLD = 90  # rapidfuzz partial_ratio
CROSS_WEIGHT_TOLERANCE = Decimal("0.02")  # ±2% entre BL/AWB e packing list
CONTAINER_WEIGHT_TOLERANCE = Decimal("0.005")  # soma dos contêineres x total do BL
MONEY_TOLERANCE = Decimal("0.01")
OLDEST_DATE = date(2000, 1, 1)

CONTAINER_TYPES = frozenset(
    {
        "20GP",
        "20DV",
        "40GP",
        "40DV",
        "40HC",
        "45HC",
        "20RF",
        "40RF",
        "40RH",
        "20OT",
        "40OT",
        "20FR",
        "40FR",
        "20TK",
        "40NOR",
    }
)
FREIGHT_TERMS = frozenset({"PREPAID", "COLLECT"})
INCOTERMS_2020 = frozenset(
    {"EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"}
)
CURRENCIES = frozenset(
    {
        "USD",
        "EUR",
        "CNY",
        "BRL",
        "GBP",
        "JPY",
        "CHF",
        "CAD",
        "AUD",
        "ARS",
        "MXN",
        "CLP",
        "COP",
        "PEN",
        "UYU",
        "PYG",
        "KRW",
        "INR",
        "HKD",
        "SGD",
        "TWD",
        "THB",
        "VND",
        "ZAR",
        "SEK",
        "NOK",
        "DKK",
        "AED",
        "SAR",
        "TRY",
        "NZD",
    }
)
# Campos comparados como identificadores (só letras e dígitos, sem pontuação).
IDENTIFIER_FIELDS = frozenset(
    {
        "numero_bl",
        "numero",
        "conteineres",
        "lacre",
        "ncm",
        "numero_awb",
        "importador_cnpj",
        "numero_invoice",
        "numero_packing_list",
        "porto_carregamento",
        "porto_descarga",
        "aeroporto_origem",
        "aeroporto_destino",
        "voo",
        "viagem",
        "tipo",
        "moeda",
        "incoterm",
        "frete",
    }
)
_MAX_ID_CHUNKS = 3
_PAGE_MARKER = re.compile(r"^--- página \d+ ---$", re.MULTILINE)
_POSITIVE_HINTS = ("peso", "volumes", "valor", "quantidade", "cubagem")

_SUSPICIOUS = (
    re.compile(
        r"ignor\w*\s+(?:as\s+|all\s+|todas\s+as\s+|the\s+|any\s+)?"
        r"(?:instru\w*|previous|anteriores|prior)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:aprove|aprovar|approve)\b", re.IGNORECASE),
    re.compile(r"\b(?:system|sistema|assistant)\s*:", re.IGNORECASE),
    re.compile(r"\b(?:prompt|score|confian[çc]a)\b", re.IGNORECASE),
)


class Rule(StrEnum):
    ESTRUTURA = "ESTRUTURA"  # resposta do modelo fora do schema, mesmo depois da nova tentativa
    FORMATO = "FORMATO"
    COERENCIA = "COERENCIA"
    GROUNDING = "GROUNDING"
    CRUZAMENTO = "CRUZAMENTO"
    AUSENTE = "AUSENTE"
    SUSPEITO = "SUSPEITO"


class Severity(StrEnum):
    CRITICA = "CRITICA"
    AVISO = "AVISO"


@dataclass(frozen=True)
class Divergence:
    regra: Rule
    campo: str
    gravidade: Severity
    mensagem: str

    def to_dict(self) -> dict[str, str]:
        return {
            "regra": self.regra.value,
            "campo": self.campo,
            "gravidade": self.gravidade.value,
            "mensagem": self.mensagem,
        }


@dataclass(frozen=True)
class FieldRef:
    path: str  # ex.: conteineres[0].numero
    leaf: str  # ex.: numero
    field: Extracted[Any]
    classe: FieldClass

    @property
    def severity(self) -> Severity:
        return Severity.CRITICA if self.classe is FieldClass.CRITICO else Severity.AVISO


def iter_fields(doc: BaseModel, prefix: str = "") -> Iterator[FieldRef]:
    """Todos os campos extraídos do documento, inclusive os de itens de lista."""
    model = type(doc)
    for name in model.model_fields:
        value = getattr(doc, name)
        classe = field_class(model, name)
        if isinstance(value, Extracted):
            yield FieldRef(f"{prefix}{name}", name, value, classe)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                path = f"{prefix}{name}[{index}]"
                if isinstance(item, Extracted):
                    yield FieldRef(path, name, item, classe)
                else:
                    yield from iter_fields(item, f"{path}.")


def empty_required_lists(doc: BaseModel) -> Iterator[tuple[str, FieldClass]]:
    """Listas críticas ou obrigatórias que vieram vazias."""
    model = type(doc)
    for name in model.model_fields:
        classe = field_class(model, name)
        required = classe is not FieldClass.OPCIONAL
        if is_list_field(model, name) and required and not getattr(doc, name):
            yield name, classe


# ------------------------------------------------------------------ formato


def _adapter_check(adapter: TypeAdapter[Any]) -> Callable[[str], None]:
    def check(value: str) -> None:
        adapter.validate_python(value)

    return check


def _in_set(allowed: frozenset[str], what: str) -> Callable[[str], None]:
    def check(value: str) -> None:
        if value.strip().upper() not in allowed:
            raise ValueError(f"{what} desconhecido")

    return check


FORMAT_CHECKS: dict[str, Callable[[str], None]] = {
    "porto_carregamento": _adapter_check(TypeAdapter(UNLocode)),
    "porto_descarga": _adapter_check(TypeAdapter(UNLocode)),
    "numero": _adapter_check(TypeAdapter(ContainerNumber)),
    "conteineres": _adapter_check(TypeAdapter(ContainerNumber)),
    "ncm": _adapter_check(TypeAdapter(NCM)),
    "numero_awb": _adapter_check(TypeAdapter(AWBNumber)),
    "aeroporto_origem": _adapter_check(TypeAdapter(IATACode)),
    "aeroporto_destino": _adapter_check(TypeAdapter(IATACode)),
    "importador_cnpj": _adapter_check(TypeAdapter(CNPJ)),
    "tipo": _in_set(CONTAINER_TYPES, "tipo de contêiner"),
    "frete": _in_set(FREIGHT_TERMS, "condição de frete"),
    "incoterm": _in_set(INCOTERMS_2020, "Incoterm"),
    "moeda": _in_set(CURRENCIES, "código ISO 4217"),
}


def check_format(doc: ExtractedDocument) -> list[Divergence]:
    """Identificadores e códigos do domínio (ISO 6346, módulo 7, CNPJ, UN/LOCODE, IATA...)."""
    divergences = []
    for ref in iter_fields(doc):
        check = FORMAT_CHECKS.get(ref.leaf)
        value = ref.field.valor
        if check is None or not isinstance(value, str):
            continue
        try:
            check(value)
        except (ValueError, ValidationError):
            divergences.append(
                Divergence(Rule.FORMATO, ref.path, ref.severity, f"{ref.leaf}: formato inválido")
            )
    return divergences


# ------------------------------------------------------------------ coerência


def check_coherence(doc: ExtractedDocument, today: date) -> list[Divergence]:
    """Presença, datas plausíveis, positivos, somas e origem diferente do destino."""
    divergences = [*_presence(doc), *_dates_and_positives(doc, today)]
    if isinstance(doc, BillOfLading):
        divergences += _bl_totals(doc)
        divergences += _different(doc.porto_carregamento, doc.porto_descarga, "porto_descarga")
    elif isinstance(doc, AirWaybill):
        divergences += _different(doc.aeroporto_origem, doc.aeroporto_destino, "aeroporto_destino")
    elif isinstance(doc, CommercialInvoice):
        divergences += _invoice_totals(doc)
    elif isinstance(doc, PackingList):
        divergences += _net_not_above_gross(doc)
    return divergences


def _presence(doc: ExtractedDocument) -> list[Divergence]:
    divergences = []
    for ref in iter_fields(doc):
        if ref.field.is_absent and ref.classe is not FieldClass.OPCIONAL:
            divergences.append(Divergence(Rule.AUSENTE, ref.path, ref.severity, "campo ausente"))
    for name, classe in empty_required_lists(doc):
        severity = Severity.CRITICA if classe is FieldClass.CRITICO else Severity.AVISO
        divergences.append(Divergence(Rule.AUSENTE, name, severity, "lista vazia"))
    return divergences


def _dates_and_positives(doc: ExtractedDocument, today: date) -> list[Divergence]:
    divergences = []
    latest = today + timedelta(days=1)
    for ref in iter_fields(doc):
        value = ref.field.valor
        if isinstance(value, date) and not OLDEST_DATE <= value <= latest:
            divergences.append(
                Divergence(Rule.COERENCIA, ref.path, ref.severity, "data fora do período plausível")
            )
        numeric = isinstance(value, Decimal | int) and not isinstance(value, bool)
        positive_field = any(h in ref.leaf for h in _POSITIVE_HINTS)
        if numeric and positive_field and Decimal(str(value)) <= 0:
            divergences.append(
                Divergence(Rule.COERENCIA, ref.path, ref.severity, "valor precisa ser positivo")
            )
    return divergences


def _bl_totals(doc: BillOfLading) -> list[Divergence]:
    divergences = []
    volumes = [c.volumes.valor for c in doc.conteineres]
    complete = bool(doc.conteineres) and None not in volumes
    total_volumes = doc.volumes_total.valor
    if complete and total_volumes is not None and sum(filter(None, volumes)) != total_volumes:
        divergences.append(
            Divergence(
                Rule.COERENCIA,
                "volumes_total",
                Severity.CRITICA,
                "soma dos volumes dos contêineres difere do total",
            )
        )
    weights = [c.peso_bruto_kg.valor for c in doc.conteineres]
    total = doc.peso_bruto_total_kg.valor
    if doc.conteineres and None not in weights and total is not None:
        summed = sum((w for w in weights if w is not None), Decimal(0))
        if not _within(summed, total, CONTAINER_WEIGHT_TOLERANCE):
            divergences.append(
                Divergence(
                    Rule.COERENCIA,
                    "peso_bruto_total_kg",
                    Severity.CRITICA,
                    "soma dos pesos dos contêineres difere do total (> 0,5%)",
                )
            )
    return divergences


def _invoice_totals(doc: CommercialInvoice) -> list[Divergence]:
    divergences = []
    for index, item in enumerate(doc.itens):
        qty, unit, total = item.quantidade.valor, item.valor_unitario.valor, item.valor_total.valor
        if qty is None or unit is None or total is None:
            continue
        if abs(qty * unit - total) > MONEY_TOLERANCE:
            divergences.append(
                Divergence(
                    Rule.COERENCIA,
                    f"itens[{index}].valor_total",
                    Severity.AVISO,
                    "quantidade x valor unitário difere do total do item",
                )
            )
    totals = [item.valor_total.valor for item in doc.itens]
    if doc.itens and None not in totals and doc.valor_total.valor is not None:
        summed = sum((t for t in totals if t is not None), Decimal(0))
        if abs(summed - doc.valor_total.valor) > MONEY_TOLERANCE:
            divergences.append(
                Divergence(
                    Rule.COERENCIA,
                    "valor_total",
                    Severity.CRITICA,
                    "soma dos itens difere do total da invoice",
                )
            )
    return divergences


def _net_not_above_gross(doc: PackingList) -> list[Divergence]:
    net, gross = doc.peso_liquido_total_kg.valor, doc.peso_bruto_total_kg.valor
    if net is not None and gross is not None and net > gross:
        return [
            Divergence(
                Rule.COERENCIA,
                "peso_liquido_total_kg",
                Severity.CRITICA,
                "peso líquido maior que o bruto",
            )
        ]
    return []


def _different(origin: Extracted[str], destination: Extracted[str], name: str) -> list[Divergence]:
    if origin.valor and destination.valor and _ident(origin.valor) == _ident(destination.valor):
        return [Divergence(Rule.COERENCIA, name, Severity.CRITICA, "origem igual ao destino")]
    return []


def _within(a: Decimal, b: Decimal, tolerance: Decimal) -> bool:
    reference = max(abs(a), abs(b))
    return reference == 0 or abs(a - b) <= reference * tolerance


# ------------------------------------------------------------------ grounding


def check_grounding(doc: ExtractedDocument, text: str) -> list[Divergence]:
    """Cada valor precisa estar na sua evidence, e a evidence no texto do documento.

    A evidence é localizada no texto (RapidFuzz, >= 90, tolera ruído de OCR). Números, datas e
    identificadores precisam estar EXATOS dentro do trecho do texto que casou com a evidence:
    não basta existirem em outro ponto do documento. Identificador é comparado como token
    inteiro (pedaço de número não é o número). Texto livre precisa caber dentro da evidence.
    """
    corpus = _norm(_PAGE_MARKER.sub(" ", text))
    convention = _convention(corpus)
    divergences = []
    for ref in iter_fields(doc):
        value, evidence = ref.field.valor, ref.field.evidence
        if value is None or evidence is None:
            continue
        problem = _grounding_problem(ref.leaf, value, evidence, corpus, convention)
        if problem:
            # Sempre crítico: dado que não está no documento nunca é aprovado.
            divergences.append(Divergence(Rule.GROUNDING, ref.path, Severity.CRITICA, problem))
    return divergences


def _grounding_problem(
    leaf: str, value: object, evidence: str, corpus: str, convention: "_Convention"
) -> str | None:
    window = _matched_window(_norm(evidence), corpus)
    if window is None:
        return "evidence não encontrada no texto do documento"
    if isinstance(value, date):
        day_first = convention.day_first
        ok = value in _dates_in(evidence, day_first) and value in _dates_in(window, day_first)
        return None if ok else "data não aparece na evidence/no trecho do texto"
    if isinstance(value, Decimal | int) and not isinstance(value, bool):
        number = Decimal(value)
        sep = convention.decimal
        ok = number in _numbers_in(evidence, sep) and number in _numbers_in(window, sep)
        return None if ok else "número não aparece na evidence/no trecho do texto"
    if leaf in IDENTIFIER_FIELDS:
        ident = _ident(str(value))
        ok = bool(ident) and _has_token(ident, evidence) and _has_token(ident, window)
        return None if ok else "identificador não aparece inteiro na evidence/no trecho do texto"
    normalized, evidence_norm = _norm(str(value)), _norm(evidence)
    fits = len(normalized) <= len(evidence_norm)  # o valor cabe na evidence, não o contrário
    if not fits or fuzz.partial_ratio(normalized, evidence_norm) < GROUNDING_THRESHOLD:
        return "valor não aparece na evidence"
    return None


def _matched_window(evidence: str, corpus: str) -> str | None:
    """Trecho do texto que casou com a evidence (None se a evidence não está no texto)."""
    if not evidence or not corpus:
        return None
    if len(evidence) > len(corpus):
        return corpus if fuzz.ratio(evidence, corpus) >= GROUNDING_THRESHOLD else None
    alignment = fuzz.partial_ratio_alignment(evidence, corpus)
    if alignment is None or alignment.score < GROUNDING_THRESHOLD:
        return None
    # Estende até os espaços vizinhos: o trecho nunca termina no meio de um número
    # (senão "maeu2409" pareceria um token inteiro de "maeu2409001234").
    start = corpus.rfind(" ", 0, alignment.dest_start) + 1
    end = corpus.find(" ", alignment.dest_end)
    return corpus[start : end if end != -1 else len(corpus)]


def _has_token(target: str, text: str) -> bool:
    """`target` (só letras e dígitos) é um "pedaço sem espaço" inteiro do texto, ou 2-3
    pedaços seguidos (ex.: voo 'LH 506'). Pedaço de número não conta: MAEU2409 != MAEU2409001234."""
    chunks = [_ident(chunk) for chunk in text.split()]
    chunks = [chunk for chunk in chunks if chunk]
    for start in range(len(chunks)):
        joined = ""
        for chunk in chunks[start : start + _MAX_ID_CHUNKS]:
            joined += chunk
            if joined == target:
                return True
            if len(joined) >= len(target):
                break
    return False


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()  # \s do re já casa o NBSP


def _ident(text: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", text.upper())


_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
_THOUSANDS_COMMA = re.compile(r"^\d{1,3}(,\d{3})+$")
_THOUSANDS_DOT = re.compile(r"^\d{1,3}(\.\d{3})+$")


@dataclass(frozen=True)
class _Convention:
    """Como o documento escreve números e datas, deduzido de exemplos sem ambiguidade."""

    decimal: str | None  # "." ou ","; None = não deu para saber
    day_first: bool | None  # True = dd/mm; None = não deu para saber


_ONE_DECIMAL_SEP = re.compile(r"^\d+[.,]\d{1,2}$")


def _convention(text: str) -> _Convention:
    decimals: set[str] = set()
    for token in _NUMBER.findall(text):
        if "," in token and "." in token:
            decimals.add("," if token.rfind(",") > token.rfind(".") else ".")
        elif _ONE_DECIMAL_SEP.match(token):  # 12.40 ou 12,40: separador decimal
            decimals.add("." if "." in token else ",")
    orders: set[bool] = set()
    for first, second, _year in _DMY.findall(text):
        if int(first) > 12 >= int(second):
            orders.add(True)
        elif int(second) > 12 >= int(first):
            orders.add(False)
    return _Convention(
        decimal=decimals.pop() if len(decimals) == 1 else None,
        day_first=orders.pop() if len(orders) == 1 else None,
    )


def _numbers_in(text: str, decimal: str | None = None) -> set[Decimal]:
    """Números do texto. Com a convenção do documento conhecida, só a leitura dela (com
    '29,700.50' no texto, '1,500' é 1500); sem ela, todas as leituras plausíveis."""
    found: set[Decimal] = set()
    for token in _NUMBER.findall(text):
        for candidate in _number_readings(token, decimal):
            try:
                found.add(Decimal(candidate))
            except InvalidOperation:
                continue
    return found


def _number_readings(token: str, decimal: str | None) -> list[str]:
    if "," in token and "." in token:
        decimal_sep = "," if token.rfind(",") > token.rfind(".") else "."
        thousands = "." if decimal_sep == "," else ","
        return [token.replace(thousands, "").replace(decimal_sep, ".")]
    for sep, thousands_pattern in ((",", _THOUSANDS_COMMA), (".", _THOUSANDS_DOT)):
        if sep not in token:
            continue
        as_decimal = [token.replace(sep, ".")] if token.count(sep) == 1 else []
        as_thousands = [token.replace(sep, "")] if thousands_pattern.match(token) else []
        if decimal == sep:
            return as_decimal
        if decimal is not None:  # o documento usa o outro separador como decimal
            return as_thousands
        return as_decimal + as_thousands
    return [token]


_MONTHS = {
    "jan": 1,
    "feb": 2,
    "fev": 2,
    "mar": 3,
    "apr": 4,
    "abr": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "ago": 8,
    "sep": 9,
    "set": 9,
    "oct": 10,
    "out": 10,
    "nov": 11,
    "dec": 12,
    "dez": 12,
}
_DMY = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH_NAME = re.compile(r"\b(\d{1,2})[\s\-]([A-Za-z]{3})[a-z]*[\s\-,]+(\d{4})\b")


def _dates_in(text: str, day_first: bool | None = None) -> set[date]:
    """Datas do texto. dd/mm ou mm/dd pela convenção do documento; sem ela, as duas."""
    found: set[date] = set()
    for a, b, year in _DMY.findall(text):
        orders = {True: [(a, b)], False: [(b, a)], None: [(a, b), (b, a)]}[day_first]
        for day, month in orders:
            _add_date(found, int(year), int(month), int(day))
    for year, month, day in _ISO.findall(text):
        _add_date(found, int(year), int(month), int(day))
    for day, month_name, year in _DAY_MONTH_NAME.findall(text):
        month = _MONTHS.get(month_name.lower())
        if month:
            _add_date(found, int(year), month, int(day))
    return found


def _add_date(found: set[date], year: int, month: int, day: int) -> None:
    try:
        found.add(date(year, month, day))
    except ValueError:
        return


# ------------------------------------------------------------------ cruzamento


def check_cross(documents: Mapping[DocumentType, ExtractedDocument]) -> list[Divergence]:
    """BL/AWB x packing list (peso ±2%, volumes, contêineres) e packing list x invoice."""
    packing = documents.get(DocumentType.PACKING_LIST)
    if not isinstance(packing, PackingList):
        return []
    divergences: list[Divergence] = []
    bl = documents.get(DocumentType.BL)
    if isinstance(bl, BillOfLading):
        divergences += _transport_vs_packing(bl.peso_bruto_total_kg, bl.volumes_total, packing)
        divergences += _containers(bl, packing)
    awb = documents.get(DocumentType.AWB)
    if isinstance(awb, AirWaybill):
        divergences += _transport_vs_packing(awb.peso_bruto_kg, awb.volumes, packing)
    invoice = documents.get(DocumentType.INVOICE)
    if isinstance(invoice, CommercialInvoice):
        divergences += _packing_vs_invoice(packing, invoice)
    return divergences


def _transport_vs_packing(
    weight: Extracted[Decimal], volumes: Extracted[int], packing: PackingList
) -> list[Divergence]:
    divergences = []
    mine, theirs = weight.valor, packing.peso_bruto_total_kg.valor
    if (
        mine is not None
        and theirs is not None
        and not _within(mine, theirs, CROSS_WEIGHT_TOLERANCE)
    ):
        divergences.append(
            Divergence(
                Rule.CRUZAMENTO,
                "peso_bruto_total_kg",
                Severity.CRITICA,
                "peso bruto difere do packing list em mais de 2%",
            )
        )
    count, other_count = volumes.valor, packing.volumes_total.valor
    if count is not None and other_count is not None and count != other_count:
        divergences.append(
            Divergence(
                Rule.CRUZAMENTO,
                "volumes_total",
                Severity.CRITICA,
                "quantidade de volumes difere do packing list",
            )
        )
    return divergences


def _containers(bl: BillOfLading, packing: PackingList) -> list[Divergence]:
    in_bl = {_ident(c.numero.valor) for c in bl.conteineres if c.numero.valor}
    in_packing = {_ident(c.valor) for c in packing.conteineres if c.valor}
    if in_bl and in_packing and in_bl != in_packing:
        return [
            Divergence(
                Rule.CRUZAMENTO,
                "conteineres",
                Severity.CRITICA,
                "contêineres do BL e do packing list não são os mesmos",
            )
        ]
    return []


def _packing_vs_invoice(packing: PackingList, invoice: CommercialInvoice) -> list[Divergence]:
    divergences = []
    ref, number = packing.numero_invoice.valor, invoice.numero_invoice.valor
    if ref and number and _ident(ref) != _ident(number):
        divergences.append(
            Divergence(
                Rule.CRUZAMENTO,
                "numero_invoice",
                Severity.CRITICA,
                "packing list cita outra invoice",
            )
        )
    a, b = packing.importador.valor, invoice.importador.valor
    if a and b and fuzz.token_set_ratio(_norm(a), _norm(b)) < GROUNDING_THRESHOLD:
        divergences.append(
            Divergence(
                Rule.CRUZAMENTO,
                "importador",
                Severity.AVISO,
                "importador do packing list difere do da invoice",
            )
        )
    return divergences


# ------------------------------------------------------------------ texto suspeito


def detect_suspicious_text(text: str) -> list[Divergence]:
    """Frases dirigidas ao sistema (possível prompt injection). O pedido não tem efeito sobre
    a extração, mas o documento vai sempre para revisão humana (crítico)."""
    hits = sum(1 for pattern in _SUSPICIOUS if pattern.search(text))
    if not hits:
        return []
    return [
        Divergence(
            Rule.SUSPEITO,
            "texto",
            Severity.CRITICA,
            f"texto com {hits} padrão(ões) de instrução ao sistema (possível prompt "
            "injection): revisão humana obrigatória",
        )
    ]


def validate_document(doc: ExtractedDocument, text: str, today: date) -> list[Divergence]:
    """Todos os validadores de um documento isolado (o cruzamento é feito por processo)."""
    return [
        *check_format(doc),
        *check_coherence(doc, today),
        *check_grounding(doc, text),
        *detect_suspicious_text(text),
    ]

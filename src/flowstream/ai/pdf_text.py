"""Texto por página dos PDFs: pdfplumber; página sem texto passa por OCR (Tesseract, por+eng)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber
import pytesseract
from PIL import Image

MAX_PAGES = 20  # documentos de embarque têm poucas páginas; mais que isso não é o caso de uso
MIN_TEXT_CHARS = 20  # abaixo disso a página é tratada como imagem (escaneada)
OCR_RESOLUTION = 300  # dpi
OCR_LANGUAGES = "por+eng"
OCR_TIMEOUT_SECONDS = 120  # por página
MAX_FILE_BYTES = 20 * 1024 * 1024  # documento de embarque cabe com folga em 20 MB
MAX_OCR_PIXELS = (
    25_000_000  # A3 a 300 dpi tem ~17 Mpx; acima disso a renderização vira bomba de RAM
)
PDF_SIGNATURE = b"%PDF-"

OcrEngine = Callable[[Image.Image], str]


class PdfReadError(ValueError):
    """O arquivo não pôde ser lido como PDF ou passa dos limites."""


class OcrUnavailableError(RuntimeError):
    """Há página escaneada e o OCR (Tesseract) não está disponível."""


@dataclass(frozen=True)
class PageText:
    number: int
    text: str
    ocr: bool
    hidden_chars: int = 0  # caracteres invisíveis descartados (branco, < 4 pt, fora da página)


def extract_pages(path: Path, ocr: OcrEngine | None) -> list[PageText]:
    """Texto de cada página; as que não têm camada de texto passam por `ocr` e ficam marcadas."""
    _check_file(path)
    try:
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise PdfReadError(f"O PDF tem {len(pdf.pages)} páginas; o limite é {MAX_PAGES}.")
            return [_read_page(page, index, ocr) for index, page in enumerate(pdf.pages, 1)]
    except (PdfReadError, OcrUnavailableError):
        raise
    except Exception as exc:  # pdfminer/pypdfium2 levantam vários tipos para arquivo ruim
        raise PdfReadError(f"Não foi possível ler o PDF ({type(exc).__name__}).") from exc


def _read_page(page: pdfplumber.page.Page, number: int, ocr: OcrEngine | None) -> PageText:
    # Só o que um humano vê: texto branco, minúsculo ou fora da página é descartado e contado
    # (é o esconderijo clássico de prompt injection e de valores "alternativos").
    visible = page.filter(lambda obj: obj.get("object_type") != "char" or _is_visible(obj, page))
    hidden = sum(1 for char in page.chars if char["text"].strip()) - sum(
        1 for char in visible.chars if char["text"].strip()
    )
    text = _clean(visible.extract_text() or "")
    if len(text) >= MIN_TEXT_CHARS:
        return PageText(number, text, ocr=False, hidden_chars=hidden)
    if ocr is None:
        raise OcrUnavailableError(
            f"A página {number} é uma imagem e o OCR não está configurado (Tesseract)."
        )
    scale = OCR_RESOLUTION / 72
    pixels = float(page.width) * scale * float(page.height) * scale
    if pixels > MAX_OCR_PIXELS:
        raise PdfReadError(
            f"A página {number} é grande demais para OCR ({pixels / 1e6:.0f} Mpx a "
            f"{OCR_RESOLUTION} dpi; limite {MAX_OCR_PIXELS / 1e6:.0f} Mpx)."
        )
    image = page.to_image(resolution=OCR_RESOLUTION).original
    return PageText(number, _clean(ocr(image)), ocr=True)


MIN_VISIBLE_FONT_SIZE = 4.0  # pt; abaixo disso ninguém lê na tela nem impresso
_WHITE = 0.95


def _is_visible(char: dict[str, Any], page: pdfplumber.page.Page) -> bool:
    if float(char.get("size") or 0) < MIN_VISIBLE_FONT_SIZE:
        return False
    inside = (
        float(char["x1"]) > 0
        and float(char["x0"]) < float(page.width)
        and float(char["bottom"]) > 0
        and float(char["top"]) < float(page.height)
    )
    return inside and not _is_white(char.get("non_stroking_color"))


def _is_white(color: object) -> bool:
    """Cinza 1, RGB (1, 1, 1) ou CMYK (0, 0, 0, 0): texto branco sobre fundo branco."""
    if isinstance(color, int | float):
        color = (color,)
    if not isinstance(color, tuple | list) or not color:
        return False
    values = [float(v) for v in color if isinstance(v, int | float)]
    if len(values) != len(color):
        return False  # padrão/cor especial: não dá para afirmar que é branco
    if len(values) == 4:  # CMYK
        return all(v <= 1 - _WHITE for v in values)
    return all(v >= _WHITE for v in values)


def _clean(text: str) -> str:
    """Remove NUL (o JSONB do Postgres recusa) e espaços nas pontas."""
    return text.replace("\x00", "").strip()


def _check_file(path: Path) -> None:
    """Recusa antes de abrir: arquivo grande demais ou que não começa com %PDF-."""
    try:
        size = path.stat().st_size
        with path.open("rb") as file:
            head = file.read(len(PDF_SIGNATURE))
    except OSError as exc:
        raise PdfReadError(f"Não foi possível ler o arquivo ({type(exc).__name__}).") from exc
    if size > MAX_FILE_BYTES:
        raise PdfReadError(
            f"O arquivo tem {size / 2**20:.1f} MB; o limite é {MAX_FILE_BYTES / 2**20:.0f} MB."
        )
    if head != PDF_SIGNATURE:
        raise PdfReadError("O arquivo não é um PDF (assinatura %PDF- ausente).")


def page_texts(pages: Sequence[PageText]) -> str:
    """Só o texto das páginas, sem marcadores: é o que o grounding compara."""
    return "\n".join(page.text for page in pages)


def full_text(pages: Sequence[PageText]) -> str:
    """Texto do documento com a marca de cada página (o grounding procura neste texto)."""
    return "\n".join(f"--- página {page.number} ---\n{page.text}" for page in pages)


def tesseract_ocr(tesseract_cmd: str | None = None) -> OcrEngine:
    """OCR com o Tesseract instalado no sistema; `tesseract_cmd` vem de TESSERACT_CMD."""

    def run(image: Image.Image) -> str:
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        try:
            return str(
                pytesseract.image_to_string(image, lang=OCR_LANGUAGES, timeout=OCR_TIMEOUT_SECONDS)
            )
        except pytesseract.TesseractNotFoundError:
            raise OcrUnavailableError(
                "Tesseract não encontrado: instale-o (com os idiomas por e eng) ou ajuste "
                "TESSERACT_CMD no .env."
            ) from None
        except RuntimeError as exc:
            if "timeout" not in str(exc).lower():
                raise
            raise OcrUnavailableError(
                f"O OCR passou do prazo de {OCR_TIMEOUT_SECONDS} s por página."
            ) from None
        except pytesseract.TesseractError as exc:
            raise OcrUnavailableError(f"Tesseract falhou: {exc.message}") from None

    return run

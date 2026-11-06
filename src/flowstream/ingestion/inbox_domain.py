"""Regras puras do watcher da inbox: quais arquivos olhar, quando estão prontos e duplicados."""

from dataclasses import dataclass
from enum import StrEnum

from flowstream.documents.domain import InvalidDocumentNameError, validate_file_name

# Prefixos de arquivos de trava/ocultos (Office "~$", LibreOffice ".~lock", Unix ".")
_TEMP_PREFIXES = ("~", ".")
# Sufixos de downloads e cópias em andamento (Chrome, Firefox, Safari, ferramentas de cópia)
_TEMP_SUFFIXES = (".crdownload", ".part", ".partial", ".download", ".tmp")


class NameCheck(StrEnum):
    OK = "OK"
    IGNORAR = "IGNORAR"  # não é PDF ou é temporário: silêncio
    INVALIDO = "INVALIDO"  # é PDF, mas a API recusaria o nome: avisa no log


class Disposition(StrEnum):
    NOTIFICAR = "NOTIFICAR"  # conteúdo novo: avisa o n8n
    JA_REGISTRADO = "JA_REGISTRADO"  # mesmo arquivo já aceito pela API: deixa como está
    DUPLICADO = "DUPLICADO"  # mesmo conteúdo com outro nome: vai para duplicados


def check_name(name: str) -> NameCheck:
    """Classifica o nome de um arquivo que apareceu na inbox."""
    lower = name.lower()
    if lower.startswith(_TEMP_PREFIXES) or lower.endswith(_TEMP_SUFFIXES):
        return NameCheck.IGNORAR
    if not lower.endswith(".pdf"):
        return NameCheck.IGNORAR
    try:
        validate_file_name(name)
    except InvalidDocumentNameError:
        return NameCheck.INVALIDO
    return NameCheck.OK


def decide(name: str, registered_name: str | None) -> Disposition:
    """O que fazer com um PDF cujo hash já pode estar em ops.documentos (com `registered_name`)."""
    if registered_name is None:
        return Disposition.NOTIFICAR
    if registered_name == name:
        return Disposition.JA_REGISTRADO
    return Disposition.DUPLICADO


_FIRST_RETRY_SECONDS = 5.0
_MAX_RETRY_SECONDS = 60.0


def retry_delay(failures: int) -> float:
    """Espera antes de tentar de novo um arquivo depois de `failures` falhas seguidas."""
    if failures < 1:
        raise ValueError("retry_delay precisa de pelo menos uma falha.")
    return min(_FIRST_RETRY_SECONDS * 2.0 ** (failures - 1), _MAX_RETRY_SECONDS)


@dataclass(frozen=True)
class _Reading:
    size: int
    mtime_ns: int
    at: float


class StabilityTracker:
    """Diz quando um arquivo parou de crescer: 2 leituras iguais separadas por `min_interval`."""

    def __init__(self, min_interval: float) -> None:
        if min_interval <= 0:
            raise ValueError("O intervalo entre leituras precisa ser positivo.")
        self._min_interval = min_interval
        self._readings: dict[str, _Reading] = {}

    def observe(self, key: str, size: int, now: float, mtime_ns: int = 0) -> bool:
        """Registra uma leitura; True quando o arquivo está estável (e sai do acompanhamento).

        Compara tamanho e mtime: há cópias que pré-alocam o tamanho final logo no início.
        """
        previous = self._readings.get(key)
        if previous is None or (previous.size, previous.mtime_ns) != (size, mtime_ns):
            self._readings[key] = _Reading(size, mtime_ns, now)
            return False
        if size > 0 and now - previous.at >= self._min_interval:
            del self._readings[key]
            return True
        return False

    def forget(self, key: str) -> None:
        self._readings.pop(key, None)

    def __contains__(self, key: object) -> bool:
        return key in self._readings

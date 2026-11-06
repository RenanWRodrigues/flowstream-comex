"""Regras puras do watcher da inbox: filtro de nomes, estabilidade de tamanho e duplicados."""

import pytest

from flowstream.ingestion.inbox_domain import (
    Disposition,
    NameCheck,
    StabilityTracker,
    check_name,
    decide,
    retry_delay,
)

# ------------------------------------------------------------------ nomes


@pytest.mark.parametrize(
    "name",
    ["BL_MSKU1234565.pdf", "invoice 2026-11 (1).PDF", "packing_list.Pdf", "AWB_020-12345675.pdf"],
)
def test_pdf_names_are_accepted(name: str) -> None:
    assert check_name(name) is NameCheck.OK


@pytest.mark.parametrize(
    "name",
    [
        "planilha.xlsx",
        "foto.png",
        "sem_extensao",
        "~$invoice.pdf",  # lock do Office
        ".~lock.bl.pdf#",  # lock do LibreOffice
        ".oculto.pdf",
        "download.pdf.crdownload",  # Chrome baixando
        "download.pdf.part",  # Firefox baixando
        "copia.pdf.tmp",
        "bl.pdf.download",
    ],
)
def test_non_pdf_and_temporary_files_are_ignored(name: str) -> None:
    assert check_name(name) is NameCheck.IGNORAR


@pytest.mark.parametrize("name", ["bl#1.pdf", "invoice;rm.pdf", "a" * 300 + ".pdf"])
def test_pdf_with_unsafe_name_is_invalid(name: str) -> None:
    """A API recusaria esses nomes: o watcher avisa em vez de chamar o n8n à toa."""
    assert check_name(name) is NameCheck.INVALIDO


# ------------------------------------------------------------------ estabilidade


def test_first_reading_is_never_stable() -> None:
    tracker = StabilityTracker(min_interval=1.0)
    assert tracker.observe("a.pdf", 100, now=0.0) is False


def test_two_equal_readings_spaced_by_interval_are_stable() -> None:
    tracker = StabilityTracker(min_interval=1.0)
    tracker.observe("a.pdf", 100, now=0.0)
    assert tracker.observe("a.pdf", 100, now=1.0) is True


def test_growing_file_is_not_stable() -> None:
    tracker = StabilityTracker(min_interval=1.0)
    for second, size in enumerate([10, 20, 30, 40]):
        assert tracker.observe("a.pdf", size, now=float(second)) is False


def test_growth_restarts_the_count() -> None:
    tracker = StabilityTracker(min_interval=1.0)
    tracker.observe("a.pdf", 10, now=0.0)
    tracker.observe("a.pdf", 20, now=1.0)
    assert tracker.observe("a.pdf", 20, now=1.5) is False  # intervalo curto desde a mudança
    assert tracker.observe("a.pdf", 20, now=2.0) is True


def test_equal_readings_too_close_are_not_stable() -> None:
    tracker = StabilityTracker(min_interval=1.0)
    tracker.observe("a.pdf", 100, now=0.0)
    assert tracker.observe("a.pdf", 100, now=0.4) is False
    assert tracker.observe("a.pdf", 100, now=1.0) is True  # conta a partir da 1ª leitura igual


def test_empty_file_is_never_stable() -> None:
    tracker = StabilityTracker(min_interval=1.0)
    tracker.observe("a.pdf", 0, now=0.0)
    assert tracker.observe("a.pdf", 0, now=5.0) is False


def test_stable_file_leaves_the_tracker() -> None:
    tracker = StabilityTracker(min_interval=1.0)
    tracker.observe("a.pdf", 100, now=0.0)
    tracker.observe("a.pdf", 100, now=1.0)
    assert "a.pdf" not in tracker
    assert tracker.observe("a.pdf", 100, now=2.0) is False  # recomeça do zero


def test_forget_drops_the_reading() -> None:
    tracker = StabilityTracker(min_interval=1.0)
    tracker.observe("a.pdf", 100, now=0.0)
    tracker.forget("a.pdf")
    tracker.forget("nunca-visto.pdf")  # não falha
    assert "a.pdf" not in tracker


def test_same_size_but_new_mtime_is_not_stable() -> None:
    """Cópia que pré-aloca o tamanho final: o tamanho não muda, mas o conteúdo ainda chega."""
    tracker = StabilityTracker(min_interval=1.0)
    tracker.observe("a.pdf", 100, now=0.0, mtime_ns=1)
    assert tracker.observe("a.pdf", 100, now=1.0, mtime_ns=2) is False
    assert tracker.observe("a.pdf", 100, now=2.0, mtime_ns=2) is True


def test_interval_must_be_positive() -> None:
    with pytest.raises(ValueError, match="intervalo"):
        StabilityTracker(min_interval=0)


# ------------------------------------------------------------------ duplicados


def test_unknown_hash_is_notified() -> None:
    assert decide("bl.pdf", registered_name=None) is Disposition.NOTIFICAR


def test_same_hash_same_name_was_already_registered() -> None:
    """Reiniciar o watcher não pode mover arquivos que a API já aceitou."""
    assert decide("bl.pdf", registered_name="bl.pdf") is Disposition.JA_REGISTRADO


def test_same_hash_other_name_is_duplicate() -> None:
    assert decide("bl (1).pdf", registered_name="bl.pdf") is Disposition.DUPLICADO


# ------------------------------------------------------------------ nova tentativa


@pytest.mark.parametrize(
    ("failures", "seconds"), [(1, 5.0), (2, 10.0), (3, 20.0), (4, 40.0), (5, 60.0), (30, 60.0)]
)
def test_retry_delay_doubles_up_to_one_minute(failures: int, seconds: float) -> None:
    assert retry_delay(failures) == seconds


def test_retry_delay_needs_at_least_one_failure() -> None:
    with pytest.raises(ValueError, match="falha"):
        retry_delay(0)

"""Testes dos utilitários de data e fuso."""

from datetime import UTC, datetime

import pytest

from flowstream.domain.dates import SAO_PAULO, is_aware, now_sao_paulo, to_sao_paulo


def test_sao_paulo_offset_is_minus_three() -> None:
    # Sem horário de verão desde 2019.
    moment = datetime(2026, 1, 15, 12, 0, tzinfo=SAO_PAULO)

    assert moment.utcoffset() is not None
    assert moment.utcoffset().total_seconds() == -3 * 3600  # type: ignore[union-attr]


def test_to_sao_paulo_converts_aware_datetime() -> None:
    utc = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)

    local = to_sao_paulo(utc)

    assert local.hour == 12
    assert local.tzinfo is SAO_PAULO
    assert local == utc


def test_to_sao_paulo_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="fuso"):
        to_sao_paulo(datetime(2026, 11, 2, 15, 0))


def test_is_aware() -> None:
    assert is_aware(datetime(2026, 1, 1, tzinfo=UTC))
    assert not is_aware(datetime(2026, 1, 1))


def test_now_sao_paulo_is_aware() -> None:
    assert now_sao_paulo().tzinfo is SAO_PAULO

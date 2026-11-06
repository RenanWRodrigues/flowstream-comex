"""Testes dos enums de embarque e da validação da linha do tempo."""

from datetime import datetime, timedelta

import pytest

from flowstream.domain.dates import SAO_PAULO
from flowstream.domain.shipment import (
    Direction,
    Modal,
    ShipmentStatus,
    TimelineRule,
    validate_timeline,
)

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=SAO_PAULO)
BOOKING = datetime(2026, 9, 1, 9, 0, tzinfo=SAO_PAULO)
ETD = datetime(2026, 9, 10, 18, 0, tzinfo=SAO_PAULO)
ETA = datetime(2026, 10, 15, 6, 0, tzinfo=SAO_PAULO)
ATD = datetime(2026, 9, 11, 2, 0, tzinfo=SAO_PAULO)
ATA = datetime(2026, 10, 16, 14, 0, tzinfo=SAO_PAULO)


def rules(**overrides: datetime | None) -> list[TimelineRule]:
    args: dict[str, datetime | None] = {
        "booking": BOOKING,
        "etd": ETD,
        "eta": ETA,
        "atd": ATD,
        "ata": ATA,
    }
    args.update(overrides)
    violations = validate_timeline(
        args["booking"],  # type: ignore[arg-type]
        args["etd"],  # type: ignore[arg-type]
        args["eta"],  # type: ignore[arg-type]
        atd=args["atd"],
        ata=args["ata"],
        now=NOW,
    )
    return [v.rule for v in violations]


# ------------------------------------------------------------------ enums


def test_modal_values() -> None:
    assert [m.value for m in Modal] == [
        "FCL",
        "LCL",
        "AEREO",
        "RODOVIARIO",
        "ISOTANQUE",
        "PROJETO",
    ]


def test_direction_values() -> None:
    assert {d.value for d in Direction} == {"IMPORTACAO", "EXPORTACAO"}


def test_enums_compare_with_plain_text() -> None:
    assert Modal("FCL") == "FCL"
    assert ShipmentStatus.EM_TRANSITO == "EM_TRANSITO"


def test_shipment_status_covers_the_lifecycle() -> None:
    assert [s.value for s in ShipmentStatus] == [
        "BOOKING",
        "AGUARDANDO_EMBARQUE",
        "EM_TRANSITO",
        "CHEGADA",
        "LIBERADO",
        "ENTREGUE",
        "CANCELADO",
    ]


# ------------------------------------------------------------------ linha do tempo válida


def test_complete_valid_timeline_has_no_violations() -> None:
    assert rules() == []


def test_timeline_not_yet_departed_has_no_violations() -> None:
    assert rules(atd=None, ata=None) == []


def test_departed_but_not_arrived_has_no_violations() -> None:
    assert rules(ata=None) == []


def test_delays_are_not_violations() -> None:
    # Atraso é informação, não erro: ATD dias depois do ETD e ATA depois do ETA.
    assert rules(atd=ETD + timedelta(days=5), ata=ETA + timedelta(days=12)) == []


def test_boundaries_on_the_same_instant_are_accepted() -> None:
    assert rules(etd=BOOKING, atd=BOOKING) == []


def test_dates_in_other_timezones_are_compared_correctly() -> None:
    # 2026-09-10 20:00 UTC == 17:00 em São Paulo, antes do ETD das 18:00; ainda após o booking.
    atd_utc = datetime.fromisoformat("2026-09-10T20:00:00+00:00")

    assert rules(atd=atd_utc) == []


# ------------------------------------------------------------------ cada violação


def test_etd_before_booking() -> None:
    assert rules(etd=BOOKING - timedelta(hours=1)) == [TimelineRule.ETD_ANTES_DO_BOOKING]


def test_eta_not_after_etd() -> None:
    assert rules(eta=ETD) == [TimelineRule.ETA_NAO_POSTERIOR_AO_ETD]
    assert rules(eta=ETD - timedelta(days=1)) == [TimelineRule.ETA_NAO_POSTERIOR_AO_ETD]


def test_atd_before_booking() -> None:
    assert rules(atd=BOOKING - timedelta(minutes=1)) == [TimelineRule.ATD_ANTES_DO_BOOKING]


def test_ata_without_atd() -> None:
    assert rules(atd=None) == [TimelineRule.ATA_SEM_ATD]


def test_ata_not_after_atd() -> None:
    assert rules(ata=ATD) == [TimelineRule.ATA_NAO_POSTERIOR_AO_ATD]


def test_actual_dates_in_the_future() -> None:
    future = NOW + timedelta(days=1)

    assert rules(atd=future, ata=None) == [TimelineRule.DATA_REAL_NO_FUTURO]
    assert rules(ata=future) == [TimelineRule.DATA_REAL_NO_FUTURO]


@pytest.mark.parametrize("field", ["booking", "etd", "eta", "atd", "ata"])
def test_naive_datetime_is_reported_and_stops_comparisons(field: str) -> None:
    naive = datetime(2026, 9, 5, 12, 0)

    assert rules(**{field: naive}) == [TimelineRule.DATA_SEM_FUSO]


def test_multiple_violations_are_all_reported_in_order() -> None:
    found = rules(
        etd=BOOKING - timedelta(days=1),
        eta=BOOKING - timedelta(days=2),
        atd=BOOKING - timedelta(days=1),
        ata=BOOKING - timedelta(days=1),
    )

    assert found == [
        TimelineRule.ETD_ANTES_DO_BOOKING,
        TimelineRule.ETA_NAO_POSTERIOR_AO_ETD,
        TimelineRule.ATD_ANTES_DO_BOOKING,
        TimelineRule.ATA_NAO_POSTERIOR_AO_ATD,
    ]


def test_violation_has_portuguese_message() -> None:
    (violation,) = validate_timeline(BOOKING, ETD, ETD, now=NOW)

    assert violation.rule is TimelineRule.ETA_NAO_POSTERIOR_AO_ETD
    assert "ETA" in violation.message
    assert "ETD" in violation.message


def test_now_defaults_to_current_time() -> None:
    assert validate_timeline(BOOKING, ETD, ETA, atd=ATD, ata=ATA) == []

"""Testes do gerador sintético: volumes, proporções, validade e a história que os dados contam.

O conjunto padrão (semente 42) é gerado uma vez por módulo.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from flowstream.domain.identifiers import CNPJ, AirWaybill, ContainerNumber
from flowstream.domain.shipment import Direction, Modal, validate_timeline
from flowstream.synthetic.config import load_config
from flowstream.synthetic.generator import Dataset, generate
from flowstream.synthetic.models import (
    FinancialCategory,
    QuoteStatus,
    Shipment,
    TrackingEventType,
)
from flowstream.synthetic.reference import load_reference

SEEDS = Path(__file__).resolve().parents[3] / "dbt" / "seeds"
ASIA_PORTS = {"CNSHA", "CNNGB", "CNYTN", "CNTAO", "CNXMN", "HKHKG", "SGSIN", "KRPUS", "JPTYO"}


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return generate(load_config(), load_reference(SEEDS), seed=42)


def share(values: list[str], key: str) -> float:
    return sum(1 for v in values if v == key) / len(values)


# ------------------------------------------------------------------ volumes


def test_volumes_match_the_plan(dataset: Dataset) -> None:
    assert len(dataset.vendedores) == 8
    assert len(dataset.clientes) == 300
    assert len(dataset.cotacoes) == 6000
    assert len(dataset.embarques) == 1800
    assert sum(1 for q in dataset.cotacoes if q.status == QuoteStatus.GANHA) == 1800


def test_every_won_quote_has_exactly_one_shipment(dataset: Dataset) -> None:
    won = {q.cotacao_id for q in dataset.cotacoes if q.status == QuoteStatus.GANHA}

    assert Counter(s.cotacao_id for s in dataset.embarques) == dict.fromkeys(won, 1)


def test_quote_status_shares(dataset: Dataset) -> None:
    statuses = [q.status.value for q in dataset.cotacoes]

    assert share(statuses, "PERDIDA") == pytest.approx(0.55, abs=0.03)
    assert share(statuses, "EXPIRADA") == pytest.approx(0.10, abs=0.03)
    assert share(statuses, "EM_ABERTO") == pytest.approx(0.05, abs=0.02)


def test_only_lost_quotes_have_loss_reason(dataset: Dataset) -> None:
    for quote in dataset.cotacoes:
        assert (quote.motivo_perda is not None) == (quote.status == QuoteStatus.PERDIDA)


def test_open_quotes_are_only_in_the_last_month(dataset: Dataset) -> None:
    last_month = dataset.periodo_fim - timedelta(days=31)

    for quote in dataset.cotacoes:
        if quote.status == QuoteStatus.EM_ABERTO:
            assert quote.solicitada_em >= last_month


# ------------------------------------------------------------------ proporções


@pytest.mark.parametrize(
    ("modal", "expected"),
    [("FCL", 0.45), ("LCL", 0.25), ("AEREO", 0.18), ("RODOVIARIO", 0.07),
     ("ISOTANQUE", 0.03), ("PROJETO", 0.02)],
)  # fmt: skip
def test_shipment_modal_shares_within_three_points(
    dataset: Dataset, modal: str, expected: float
) -> None:
    modals = [s.modal.value for s in dataset.embarques]

    assert share(modals, modal) == pytest.approx(expected, abs=0.03)


def test_import_share_is_about_65_percent(dataset: Dataset) -> None:
    directions = [s.direcao.value for s in dataset.embarques]

    assert share(directions, Direction.IMPORTACAO) == pytest.approx(0.65, abs=0.05)


def test_pareto_top_20_percent_of_customers_bring_most_shipments(dataset: Dataset) -> None:
    per_customer = sorted(Counter(s.cliente_id for s in dataset.embarques).values(), reverse=True)
    top = per_customer[: len(dataset.clientes) // 5]

    assert sum(top) / len(dataset.embarques) == pytest.approx(0.72, abs=0.10)


def test_large_customers_lead_the_volume(dataset: Dataset) -> None:
    size = {c.cliente_id: c.porte for c in dataset.clientes}
    by_size = Counter(size[s.cliente_id] for s in dataset.embarques)

    assert by_size["GRANDE"] > by_size["MEDIO"] > by_size["PEQUENO"]


def test_customers_are_mostly_from_santa_catarina(dataset: Dataset) -> None:
    states = [c.uf for c in dataset.clientes]

    assert share(states, "SC") == pytest.approx(0.70, abs=0.01)


# ------------------------------------------------------------------ validade


def test_all_cnpjs_are_valid_fictitious_and_unique(dataset: Dataset) -> None:
    adapter = TypeAdapter(CNPJ)
    cnpjs = [c.cnpj for c in dataset.clientes]

    assert len(set(cnpjs)) == len(cnpjs)
    for cnpj in cnpjs:
        assert adapter.validate_python(cnpj) == cnpj
        assert cnpj.startswith("00000")
        assert not cnpj.startswith("00000000")  # raiz do Banco do Brasil


def test_all_containers_are_valid_iso_6346(dataset: Dataset) -> None:
    adapter = TypeAdapter(ContainerNumber)
    numbers = [e.numero for e in dataset.equipamentos]

    assert numbers
    assert len(set(numbers)) == len(numbers)
    for number in numbers:
        assert adapter.validate_python(number) == number


def test_all_air_shipments_have_valid_awb(dataset: Dataset) -> None:
    adapter = TypeAdapter(AirWaybill)

    for shipment in dataset.embarques:
        if shipment.modal == Modal.AEREO:
            assert shipment.awb is not None
            assert adapter.validate_python(shipment.awb) == shipment.awb
        else:
            assert shipment.awb is None


def test_every_timeline_passes_domain_validation(dataset: Dataset) -> None:
    for s in dataset.embarques:
        violations = validate_timeline(
            s.booking_em, s.etd, s.eta, atd=s.atd, ata=s.ata, now=dataset.periodo_fim
        )
        assert violations == [], (s.processo, violations)


def test_containers_match_modal_and_teus(dataset: Dataset) -> None:
    by_process = defaultdict(list)
    for equipment in dataset.equipamentos:
        by_process[equipment.processo].append(equipment)

    for s in dataset.embarques:
        boxes = by_process[s.processo]
        if s.modal in (Modal.FCL, Modal.ISOTANQUE):
            assert 1 <= len(boxes) == s.quantidade_equipamentos
            assert s.teus == sum(2 if b.tipo == "40HC" else 1 for b in boxes)
        else:
            assert boxes == []
            assert s.teus == 0


def test_weights_are_coherent_with_modal(dataset: Dataset) -> None:
    for s in dataset.embarques:
        assert s.peso_kg > 0
        assert s.volume_m3 > 0
        if s.modal == Modal.AEREO:
            assert Decimal(50) <= s.peso_kg <= Decimal(3000)
            assert s.peso_taxavel_kg is not None
            assert s.peso_taxavel_kg >= s.peso_kg
        if s.modal == Modal.LCL:
            assert Decimal(1) <= s.volume_m3 <= Decimal(15)


# ------------------------------------------------------------------ prazos


def test_about_80_percent_arrive_on_time(dataset: Dataset) -> None:
    arrived = [s for s in dataset.embarques if s.ata is not None]
    on_time = [s for s in arrived if s.ata <= s.eta + timedelta(days=1)]  # type: ignore[operator]

    assert len(arrived) > 1500
    assert len(on_time) / len(arrived) == pytest.approx(0.80, abs=0.04)


def test_delays_have_a_long_tail(dataset: Dataset) -> None:
    delays = sorted(
        (s.ata - s.eta).days for s in dataset.embarques if s.ata and s.ata > s.eta + timedelta(1)
    )

    assert delays[len(delays) // 2] <= 7  # mediana curta
    assert delays[-1] >= 15  # cauda longa (marítimo)
    assert delays[-1] <= 46


@pytest.mark.parametrize(("modal", "max_days"), [(Modal.AEREO, 4), (Modal.RODOVIARIO, 6)])
def test_air_and_road_delays_are_short(dataset: Dataset, modal: Modal, max_days: int) -> None:
    delays = [
        (s.ata - s.eta).total_seconds() / 86_400
        for s in dataset.embarques
        if s.modal == modal and s.ata is not None
    ]

    assert delays
    assert max(delays) <= max_days


def test_delay_never_exceeds_one_and_a_half_transit_times(dataset: Dataset) -> None:
    for s in dataset.embarques:
        if s.ata is not None:
            transit = (s.eta - s.etd).total_seconds() / 86_400
            delay = (s.ata - s.eta).total_seconds() / 86_400
            assert delay <= 1 + 1.5 * transit + 0.01, (s.processo, delay, transit)


def test_20ft_freight_is_cheaper_than_40ft(dataset: Dataset) -> None:
    boxes: dict[str, list[str]] = defaultdict(list)
    for e in dataset.equipamentos:
        boxes[e.processo].append(e.tipo)
    quote_value = {q.cotacao_id: q.valor_frete for q in dataset.cotacoes}
    per_box: dict[str, list[Decimal]] = defaultdict(list)
    for s in dataset.embarques:
        kinds = set(boxes[s.processo])
        if s.modal == Modal.FCL and len(kinds) == 1:
            per_box[kinds.pop()].append(quote_value[s.cotacao_id] / len(boxes[s.processo]))

    def mean(values: list[Decimal]) -> Decimal:
        return sum(values, Decimal(0)) / len(values)

    assert mean(per_box["20DV"]) <= Decimal("0.80") * mean(per_box["40HC"])


def test_container_volume_respects_practical_capacity(dataset: Dataset) -> None:
    capacity = {"20DV": Decimal(30), "40HC": Decimal(68), "ISO20": Decimal(26)}
    boxes: dict[str, list[str]] = defaultdict(list)
    for e in dataset.equipamentos:
        boxes[e.processo].append(e.tipo)

    for s in dataset.embarques:
        if boxes[s.processo]:
            assert s.volume_m3 <= sum(capacity[k] for k in boxes[s.processo]), s.processo


def test_carriers_have_different_punctuality(dataset: Dataset) -> None:
    rates = {}
    for carrier in {s.armador_codigo for s in dataset.embarques if s.armador_codigo}:
        arrived = [s for s in dataset.embarques if s.armador_codigo == carrier and s.ata]
        on_time = [s for s in arrived if s.ata <= s.eta + timedelta(days=1)]  # type: ignore[operator]
        rates[carrier] = len(on_time) / len(arrived)

    assert max(rates.values()) - min(rates.values()) >= 0.08


def test_shipments_in_progress_at_the_end_of_the_period(dataset: Dataset) -> None:
    open_ = [s for s in dataset.embarques if s.ata is None]

    assert open_, "deveria haver embarques ainda em trânsito no fim do período"
    for s in open_:
        assert s.status.value in {"AGUARDANDO_EMBARQUE", "EM_TRANSITO"}


# ------------------------------------------------------------------ sazonalidade


def test_peak_season_is_busier_than_the_holidays(dataset: Dataset) -> None:
    # A sazonalidade é aplicada às cotações (cota exata por mês); os ETDs a herdam com atraso.
    months = Counter(q.solicitada_em.month for q in dataset.cotacoes)

    assert months[9] + months[10] > 1.3 * (months[12] + months[2])


def test_chinese_new_year_pushes_asian_departures_out_of_the_holiday(dataset: Dataset) -> None:
    holidays = [datetime.fromisoformat(f"{d}T00:00:00-03:00") for d in ("2025-01-29", "2026-02-17")]

    def in_window(s: Shipment, before: int, after: int) -> bool:
        return any(c - timedelta(before) <= s.etd <= c + timedelta(after) for c in holidays)

    window = [s for s in dataset.embarques if in_window(s, 7, 14)]
    rest = [s for s in dataset.embarques if not in_window(s, 60, 60)]

    def asia_share(items: list[Shipment]) -> float:
        return sum(1 for s in items if s.origem in ASIA_PORTS) / len(items)

    assert asia_share(window) < 0.65 * asia_share(rest)


# ------------------------------------------------------------------ comercial


def test_fast_answers_win_more(dataset: Dataset) -> None:
    decided = [q for q in dataset.cotacoes if q.status != QuoteStatus.EM_ABERTO]

    def win_rate(hours_min: float, hours_max: float) -> float:
        group = [
            q
            for q in decided
            if hours_min <= (q.respondida_em - q.solicitada_em).total_seconds() / 3600 < hours_max
        ]
        return sum(1 for q in group if q.status == QuoteStatus.GANHA) / len(group)

    assert win_rate(0, 24) > win_rate(72, 10_000) + 0.08


def test_about_10_percent_of_answers_take_more_than_3_days(dataset: Dataset) -> None:
    slow = [q for q in dataset.cotacoes if q.respondida_em - q.solicitada_em > timedelta(days=3)]

    assert len(slow) / len(dataset.cotacoes) == pytest.approx(0.10, abs=0.05)


def test_sellers_have_different_win_rates(dataset: Dataset) -> None:
    rates = []
    for seller in dataset.vendedores:
        quotes = [
            q
            for q in dataset.cotacoes
            if q.vendedor_id == seller.vendedor_id and q.status != QuoteStatus.EM_ABERTO
        ]
        rates.append(sum(1 for q in quotes if q.status == QuoteStatus.GANHA) / len(quotes))

    assert max(rates) - min(rates) >= 0.08


# ------------------------------------------------------------------ financeiro


def margins(dataset: Dataset) -> dict[str, list[float]]:
    """Margem por processo e moeda: (receita - custo) / receita."""
    totals: dict[tuple[str, str], list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for item in dataset.itens_financeiros:
        index = 0 if item.tipo == "RECEITA" else 1
        totals[(item.processo, item.moeda)][index] += item.valor
    result: dict[str, list[float]] = defaultdict(list)
    for (process, _), (revenue, cost) in totals.items():
        result[process].append(float((revenue - cost) / revenue) if revenue else -1.0)
    return result


def absorbed_demurrage(dataset: Dataset) -> set[str]:
    costs = {
        i.processo
        for i in dataset.itens_financeiros
        if i.categoria == FinancialCategory.DEMURRAGE and i.tipo == "CUSTO"
    }
    billed = {
        i.processo
        for i in dataset.itens_financeiros
        if i.categoria == FinancialCategory.DEMURRAGE and i.tipo == "RECEITA"
    }
    return costs - billed


def test_margin_between_8_and_25_percent_without_absorbed_demurrage(dataset: Dataset) -> None:
    absorbed = absorbed_demurrage(dataset)

    for process, values in margins(dataset).items():
        if process not in absorbed:
            for value in values:
                assert 0.075 <= value <= 0.255, (process, value)


def test_absorbed_demurrage_pushes_margin_below_8_percent(dataset: Dataset) -> None:
    absorbed = absorbed_demurrage(dataset)
    all_margins = margins(dataset)

    # ~1800 x 45% FCL x 65% importação x ~95% chegados x 8% demurrage x 30% absorvida = ~12
    assert 4 <= len(absorbed) <= 25
    below = [p for p in absorbed if min(all_margins[p]) < 0.08]
    assert len(below) >= 0.8 * len(absorbed)


def test_demurrage_in_about_8_percent_of_imported_fcl(dataset: Dataset) -> None:
    fcl_imports = {
        s.processo
        for s in dataset.embarques
        if s.modal == Modal.FCL and s.direcao == Direction.IMPORTACAO and s.ata is not None
    }
    with_demurrage = {
        i.processo for i in dataset.itens_financeiros if i.categoria == FinancialCategory.DEMURRAGE
    }

    assert len(with_demurrage) / len(fcl_imports) == pytest.approx(0.08, abs=0.03)
    # Demurrage no Brasil é do importador: exportação não paga demurrage ao agente.
    assert with_demurrage <= fcl_imports


def test_financial_values_are_positive_with_two_decimals(dataset: Dataset) -> None:
    for item in dataset.itens_financeiros:
        assert item.valor > 0
        assert item.valor == item.valor.quantize(Decimal("0.01"))
        assert item.competencia <= dataset.periodo_fim.date()


def test_currencies_used(dataset: Dataset) -> None:
    assert {i.moeda for i in dataset.itens_financeiros} == {"BRL", "USD", "EUR"}


# ------------------------------------------------------------------ tracking


def test_events_never_happen_after_the_period(dataset: Dataset) -> None:
    for event in dataset.tracking:
        assert event.ocorrido_em <= dataset.periodo_fim


def test_events_follow_the_shipment_dates(dataset: Dataset) -> None:
    shipments = {s.processo: s for s in dataset.embarques}
    for event in dataset.tracking:
        s = shipments[event.processo]
        if event.tipo == TrackingEventType.EMBARQUE:
            assert event.ocorrido_em == s.atd
        if event.tipo == TrackingEventType.CHEGADA:
            assert event.ocorrido_em == s.ata
        if event.tipo == TrackingEventType.BOOKING_CONFIRMADO:
            assert event.ocorrido_em == s.booking_em


def test_eta_updates_only_for_late_shipments(dataset: Dataset) -> None:
    shipments = {s.processo: s for s in dataset.embarques}
    updates = [e for e in dataset.tracking if e.tipo == TrackingEventType.ETA_ATUALIZADO]

    assert updates
    for event in updates:
        s = shipments[event.processo]
        assert event.eta_informada is not None
        assert event.eta_informada > s.eta + timedelta(days=1)


def test_every_shipment_has_a_booking_event(dataset: Dataset) -> None:
    booked = {
        e.processo for e in dataset.tracking if e.tipo == TrackingEventType.BOOKING_CONFIRMADO
    }

    assert booked == {s.processo for s in dataset.embarques}


# ------------------------------------------------------------------ reprodutibilidade


def test_same_seed_same_data(dataset: Dataset) -> None:
    again = generate(load_config(), load_reference(SEEDS), seed=42)

    assert again == dataset


def test_different_seed_different_data(dataset: Dataset) -> None:
    other = generate(load_config(), load_reference(SEEDS), seed=7)

    assert other.clientes != dataset.clientes
    assert other.embarques != dataset.embarques


def test_months_parameter_shortens_the_period() -> None:
    small = generate(load_config(), load_reference(SEEDS), seed=1, months=6)

    assert small.periodo_fim.isoformat() == "2025-05-01T00:00:00-03:00"
    assert all(q.solicitada_em < small.periodo_fim for q in small.cotacoes)


# ------------------------------------------------------------------ realismo (auditoria do P06)


def test_quotes_are_requested_on_weekdays_during_business_hours(dataset: Dataset) -> None:
    for quote in dataset.cotacoes:
        assert quote.solicitada_em.isoweekday() <= 5, quote.cotacao_id
        assert 8 <= quote.solicitada_em.hour < 18, quote.cotacao_id


def test_answers_and_bookings_happen_in_business_hours(dataset: Dataset) -> None:
    for quote in dataset.cotacoes:
        assert quote.respondida_em.isoweekday() <= 5, quote.cotacao_id
        assert 8 <= quote.respondida_em.hour < 18, quote.cotacao_id
    for s in dataset.embarques:
        assert s.booking_em.isoweekday() <= 5, s.processo


def test_answers_never_after_the_period_and_never_truncated(dataset: Dataset) -> None:
    hours = [(q.respondida_em - q.solicitada_em).total_seconds() / 3600 for q in dataset.cotacoes]

    assert all(q.respondida_em < dataset.periodo_fim for q in dataset.cotacoes)
    assert all(h > 0 for h in hours)
    assert Counter(round(h, 2) for h in hours)[240.0] <= 1  # sem pico no teto (eram 50)


def test_empty_containers_are_returned_after_release(dataset: Dataset) -> None:
    events: dict[str, dict[str, datetime]] = defaultdict(dict)
    for e in dataset.tracking:
        events[e.processo][e.tipo.value] = e.ocorrido_em
    shipments = {s.processo: s for s in dataset.embarques}
    returned = [p for p, ev in events.items() if "DEVOLUCAO_VAZIO" in ev]

    assert len(returned) > 500
    for process in returned:
        s, ev = shipments[process], events[process]
        assert s.direcao == Direction.IMPORTACAO
        assert s.modal in (Modal.FCL, Modal.ISOTANQUE)
        assert s.ata is not None and ev["DEVOLUCAO_VAZIO"] > ev["LIBERACAO"] > s.ata


def test_demurrage_matches_late_container_return(dataset: Dataset) -> None:
    """Quem pagou demurrage devolveu depois do free time; quem não pagou, dentro dele."""
    free_time: dict[str, int] = {}
    for e in dataset.equipamentos:
        free_time[e.processo] = max(free_time.get(e.processo, 0), e.free_time_dias)
    charged = {
        i.processo for i in dataset.itens_financeiros if i.categoria == FinancialCategory.DEMURRAGE
    }
    shipments = {s.processo: s for s in dataset.embarques}
    returns = {
        e.processo: e.ocorrido_em
        for e in dataset.tracking
        if e.tipo == TrackingEventType.DEVOLUCAO_VAZIO
    }

    assert charged
    for process, returned_at in returns.items():
        days = (returned_at - shipments[process].ata).total_seconds() / 86_400  # type: ignore[operator]
        if process in charged:
            assert days > free_time[process], process
        else:
            assert days <= free_time[process], process
    assert charged <= set(returns)  # toda demurrage cobrada tem devolução registrada

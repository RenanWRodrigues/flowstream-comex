"""Gera a operação fictícia de um agente de cargas de Itajaí.

Puro: sem disco, sem banco. Todo sorteio sai de um único random.Random(seed), na mesma
ordem, então a mesma semente gera exatamente os mesmos dados. Proporções que têm meta
(modais, porte, segmento, UF, cotações ganhas) são distribuídas por cota exata, não por
sorteio, para não depender da sorte.
"""

import math
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TypeVar

from flowstream.domain.identifiers import (
    cnpj_check_digits,
    generate_valid_awb,
    generate_valid_container,
)
from flowstream.domain.money import Currency
from flowstream.domain.shipment import Direction, Modal, ShipmentStatus
from flowstream.synthetic.config import SyntheticConfig, add_months
from flowstream.synthetic.models import (
    Customer,
    Equipment,
    FinancialCategory,
    FinancialItem,
    FinancialType,
    Quote,
    QuoteStatus,
    Seller,
    Shipment,
    TrackingEvent,
    TrackingEventType,
)
from flowstream.synthetic.reference import Airline, Carrier, Reference, Route

K = TypeVar("K")

MARITIME = (Modal.FCL, Modal.LCL, Modal.ISOTANQUE, Modal.PROJETO)
CONTAINERIZED = (Modal.FCL, Modal.ISOTANQUE)
OPEN_QUOTE_DAYS = 30  # cotações dos últimos 30 dias ainda não foram decididas
# Atraso além de 1 dia nos embarques atrasados: (mediana, teto) em dias, por modal.
# Marítimo usa (3, 44); todos também ficam limitados a 1,5 x o transit time da rota.
LATE_PROFILE = {Modal.AEREO: (0.75, 2.5), Modal.RODOVIARIO: (1.5, 4.5)}

SELLER_NAMES = [
    "Ana Beatriz Souza", "Bruno Henrique Lima", "Carla Menezes", "Diego Martins",
    "Eduarda Rocha", "Felipe Andrade", "Gabriela Nunes", "Henrique Vieira",
]  # fmt: skip

NAME_WORDS = {
    "TEXTIL": ["Têxtil", "Malhas", "Confecções", "Fiação"],
    "METALMECANICO": ["Metalúrgica", "Usinagem", "Motores", "Compressores"],
    "ALIMENTOS": ["Alimentos", "Frigorífico", "Pescados", "Agroindustrial"],
    "VAREJO": ["Comercial", "Importadora", "Distribuidora", "Magazine"],
    "ELETRONICOS": ["Eletrônica", "Tecnologia", "Componentes", "Automação"],
    "AUTOPECAS": ["Autopeças", "Peças Automotivas", "Rolamentos", "Freios"],
    "MOVEIS": ["Móveis", "Madeiras", "Estofados", "Esquadrias"],
    "CERAMICA": ["Cerâmica", "Revestimentos", "Porcelanato", "Pisos"],
    "QUIMICO": ["Química", "Resinas", "Polímeros", "Tintas"],
    "AGRO": ["Agro", "Sementes", "Fertilizantes", "Cereais"],
}
NAME_CORES = [
    "Vale Azul", "Atlântico", "Litoral", "Serra Verde", "Rio Itajaí", "Costa Sul", "Horizonte",
    "Baía Norte", "Pinheiral", "Araucária", "Maré Alta", "Ventos do Sul", "Nova Era", "Estrela",
    "Ponte Alta", "Ilha Bela", "Campos Gerais", "Morro Azul", "Planalto", "Cruzeiro",
    "Tabuleiro", "Brisa", "Sol Nascente", "Enseada", "Recanto",
]  # fmt: skip
NAME_SUFFIXES = [
    "Ltda", "S.A.", "Indústria e Comércio Ltda", "Comércio Exterior Ltda",
    "Importação e Exportação Ltda",
]  # fmt: skip


@dataclass(frozen=True)
class Dataset:
    periodo_fim: datetime
    vendedores: list[Seller]
    clientes: list[Customer]
    cotacoes: list[Quote]
    embarques: list[Shipment]
    equipamentos: list[Equipment]
    itens_financeiros: list[FinancialItem]
    tracking: list[TrackingEvent]


@dataclass(frozen=True)
class _Cargo:
    boxes: tuple[tuple[str, Decimal], ...]  # (tipo, peso_kg) de contêineres ou tanques
    peso_kg: Decimal
    volume_m3: Decimal
    peso_taxavel_kg: Decimal | None


@dataclass(frozen=True)
class _QuoteDraft:
    solicitada: datetime
    customer: Customer
    modal: Modal
    route: Route
    respondida_em: datetime  # já em horário comercial e antes do fim do período
    booking_days: float
    lead_days: float
    cargo: _Cargo
    valor: Decimal
    moeda: Currency

    @property
    def respondida(self) -> datetime:
        return self.respondida_em

    @property
    def response_hours(self) -> float:
        return (self.respondida_em - self.solicitada).total_seconds() / 3600

    @property
    def booking(self) -> datetime:
        # Booking é confirmado em dia útil, no horário comercial.
        return _business_hours(_minute(self.respondida_em + timedelta(days=self.booking_days)))

    @property
    def etd(self) -> datetime:
        return _minute(self.booking + timedelta(days=self.lead_days))


# ------------------------------------------------------------------ ponto de entrada


def generate(
    config: SyntheticConfig, reference: Reference, seed: int, months: int | None = None
) -> Dataset:
    """Gera vendedores, clientes, cotações, embarques, equipamentos, financeiro e tracking."""
    rng = random.Random(seed)
    months = months or config.meses
    start, end = config.inicio_dt(), config.fim(months)

    sellers, propensity = _sellers(rng, config, start)
    customers = _customers(rng, config, sellers, start)
    drafts = _quote_drafts(rng, config, reference, customers, start, months)
    decisions = _decide(rng, config, drafts, propensity, end)
    quotes = [_quote(i, d, *decisions[i]) for i, d in enumerate(drafts)]

    builder = _ShipmentBuilder(rng, config, reference, end)
    won = sorted(
        (i for i, (status, _) in decisions.items() if status == QuoteStatus.GANHA),
        key=lambda i: (drafts[i].booking, i),
    )
    for i in won:
        builder.add(quotes[i].cotacao_id, drafts[i])

    return Dataset(
        periodo_fim=end,
        vendedores=sellers,
        clientes=customers,
        cotacoes=quotes,
        embarques=builder.shipments,
        equipamentos=builder.equipment,
        itens_financeiros=builder.financial,
        tracking=builder.events(),
    )


# ------------------------------------------------------------------ vendedores e clientes


def _sellers(
    rng: random.Random, config: SyntheticConfig, start: datetime
) -> tuple[list[Seller], dict[str, float]]:
    n = config.vendedores
    low, high = float(config.taxa_ganho_vendedor.minimo), float(config.taxa_ganho_vendedor.maximo)
    rates = [low + (high - low) * i / max(n - 1, 1) for i in range(n)]
    rng.shuffle(rates)
    sellers, propensity = [], {}
    for i in range(n):
        seller_id = f"V{i + 1:02d}"
        name = SELLER_NAMES[i % len(SELLER_NAMES)]
        hired = (start - timedelta(days=rng.randint(180, 2500))).date()
        sellers.append(Seller(vendedor_id=seller_id, nome=name, data_admissao=hired))
        propensity[seller_id] = rates[i]
    return sellers, propensity


def _customers(
    rng: random.Random, config: SyntheticConfig, sellers: list[Seller], start: datetime
) -> list[Customer]:
    n = config.clientes
    sizes = _shuffled_quota(rng, config.porte, n)
    segments = _shuffled_quota(rng, config.segmentos, n)
    states = _shuffled_quota(rng, config.uf, n)
    roots = rng.sample(range(1, 1000), n)  # raiz 00.000.001 a 00.000.999: nunca 00.000.000
    used_names: set[str] = set()
    customers = []
    for i in range(n):
        base = f"00000{roots[i]:03d}0001"
        customers.append(
            Customer(
                cliente_id=f"C{i + 1:04d}",
                cnpj=base + cnpj_check_digits(base),
                razao_social=_company_name(rng, segments[i], used_names),
                segmento=segments[i],
                porte=sizes[i],
                uf=states[i],
                vendedor_id=rng.choice(sellers).vendedor_id,
                data_cadastro=(start - timedelta(days=rng.randint(30, 3000))).date(),
            )
        )
    return customers


def _company_name(rng: random.Random, segment: str, used: set[str]) -> str:
    while True:
        name = (
            f"{rng.choice(NAME_WORDS[segment])} {rng.choice(NAME_CORES)} "
            f"{rng.choice(NAME_SUFFIXES)}"
        )
        if name not in used:
            used.add(name)
            return name


# ------------------------------------------------------------------ cotações


def _quote_drafts(
    rng: random.Random,
    config: SyntheticConfig,
    reference: Reference,
    customers: list[Customer],
    start: datetime,
    months: int,
) -> list[_QuoteDraft]:
    total = round(config.cotacoes * months / config.meses)
    growth = float(config.crescimento_anual)
    month_starts = [add_months(start, i) for i in range(months + 1)]
    end = month_starts[-1]
    weights = {
        i: float(config.sazonalidade[month_starts[i].month]) * (1 + growth) ** (i / 12)
        for i in range(months)
    }
    moments = sorted(
        _moment_in(rng, month_starts[i], month_starts[i + 1])
        for i, count in _quota(weights, total).items()
        for _ in range(count)
    )
    modals = _shuffled_quota(rng, config.modais, total)
    imports = _shuffled_quota(
        rng, {True: config.proporcao_importacao, False: 1 - config.proporcao_importacao}, total
    )
    # Peso do porte x uma lognormal por cliente: mesmo entre os grandes há os muito grandes.
    spread = float(config.dispersao_cliente)
    customer_weights = [
        config.peso_porte[c.porte] * rng.lognormvariate(0, spread) for c in customers
    ]

    drafts = []
    for moment, modal, is_import in zip(moments, modals, imports, strict=True):
        direction = Direction.IMPORTACAO if is_import else Direction.EXPORTACAO
        if not reference.rotas_de(modal, direction):
            direction = Direction.EXPORTACAO if is_import else Direction.IMPORTACAO
        # Mediana em horas corridas; 16 h no marítimo dá ~10% acima de 3 dias, com as
        # noites e os fins de semana que a resposta em horário comercial acrescenta.
        median_hours = 6 if modal == Modal.AEREO else 16
        answered = _answer(rng, moment, median_hours, end)
        booking_days = rng.uniform(1, 5)
        lead = _lead_days(rng, modal)
        route = _choose_route(rng, config, reference.rotas_de(modal, direction))
        if route.regiao_externa == "ASIA":
            # Mesmo cálculo do booking real (horário comercial), para a janela bater.
            booked = _business_hours(_minute(answered + timedelta(days=booking_days)))
            planned_etd = booked + timedelta(days=lead)
            lead += _chinese_new_year_push(rng, config, planned_etd)
        cargo, valor, moeda = _cargo(rng, modal, route)
        drafts.append(
            _QuoteDraft(
                solicitada=moment,
                customer=rng.choices(customers, weights=customer_weights)[0],
                modal=modal,
                route=route,
                respondida_em=answered,
                booking_days=booking_days,
                lead_days=lead,
                cargo=cargo,
                valor=valor,
                moeda=moeda,
            )
        )
    return drafts


def _moment_in(rng: random.Random, first: datetime, after_last: datetime) -> datetime:
    """Um momento de dia útil (segunda a sexta), das 8h às 17h, dentro do mês."""
    while True:
        day = first + timedelta(days=rng.randrange((after_last - first).days))
        if day.isoweekday() <= 5:
            return day + timedelta(hours=rng.randint(8, 16), minutes=rng.randrange(60))


MAX_RESPONSE_HOURS = 240.0


def _answer(rng: random.Random, asked: datetime, median_hours: float, end: datetime) -> datetime:
    """Momento da resposta: lognormal truncada em 10 dias, levada ao horário comercial."""
    hours = rng.lognormvariate(math.log(median_hours), 1.0)
    while hours > MAX_RESPONSE_HOURS:  # redesenha em vez de cortar: sem pico no teto
        hours = rng.lognormvariate(math.log(median_hours), 1.0)
    answered = _business_hours(_minute(asked + timedelta(hours=hours)))
    while answered >= end and hours > 0.1:  # fim do período: resposta mais rápida
        hours /= 2
        answered = _business_hours(_minute(asked + timedelta(hours=hours)))
    if answered >= end or answered <= asked:
        answered = asked + timedelta(minutes=5)
    return answered


def _business_hours(moment: datetime) -> datetime:
    """Leva o momento ao próximo horário comercial (seg-sex, 8h-18h), mantendo o minuto."""
    while moment.isoweekday() > 5 or moment.hour >= 18 or moment.hour < 8:
        if moment.hour < 8 and moment.isoweekday() <= 5:
            moment = moment.replace(hour=8)
        else:
            moment = (moment + timedelta(days=1)).replace(hour=8)
    return moment


def _lead_days(rng: random.Random, modal: Modal) -> float:
    if modal == Modal.AEREO:
        return rng.uniform(1, 3)
    if modal == Modal.RODOVIARIO:
        return rng.uniform(1, 2)
    return rng.uniform(7, 21)


def _choose_route(rng: random.Random, config: SyntheticConfig, routes: list[Route]) -> Route:
    per_region = Counter(r.regiao_externa for r in routes)
    weights = [
        float(config.regioes.get(r.regiao_externa, 0)) / per_region[r.regiao_externa]
        for r in routes
    ]
    return rng.choices(routes, weights=weights)[0]


def _chinese_new_year_push(rng: random.Random, config: SyntheticConfig, etd: datetime) -> float:
    """Dias a somar ao prazo: com o Ano-Novo Chinês, parte da carga só sai depois do feriado.

    Janela: de 7 dias antes a 14 dias depois. Uma fração (reducao_ano_novo_chines) dos
    embarques que sairiam nela é empurrada para 1 a 10 dias depois do fim da janela.
    """
    day = etd.date()
    for cny in config.ano_novo_chines:
        window_end = cny + timedelta(days=14)
        if cny - timedelta(days=7) <= day <= window_end:
            if rng.random() < float(config.reducao_ano_novo_chines):
                return (window_end - day).days + rng.uniform(1, 10)
            return 0.0
    return 0.0


def _cargo(rng: random.Random, modal: Modal, route: Route) -> tuple[_Cargo, Decimal, Currency]:
    asia = route.regiao_externa == "ASIA"
    currency: Currency = "USD"
    if modal != Modal.RODOVIARIO and route.regiao_externa == "EUROPA" and rng.random() < 0.4:
        currency = "EUR"
    boxes: list[tuple[str, Decimal]] = []
    taxable: Decimal | None = None
    if modal == Modal.FCL:
        count = rng.choices([1, 2, 3, 4, 5], weights=[55, 25, 10, 6, 4])[0]
        rate_40 = rng.uniform(2_500, 4_500) if asia else rng.uniform(1_800, 3_500)
        volume, value = 0.0, 0.0
        for _ in range(count):
            big = rng.random() < 0.70
            boxes.append(
                (
                    "40HC" if big else "20DV",
                    _dec(rng.uniform(10_000, 26_000) if big else rng.uniform(8_000, 21_000)),
                )
            )
            # Ocupação prática de 75% a 90% da capacidade (40'HC ~76 m³, 20' ~33 m³).
            volume += rng.uniform(50, 68) if big else rng.uniform(22, 30)
            # O 20' custa de 60% a 75% do frete de um 40'HC.
            value += rate_40 if big else rate_40 * rng.uniform(0.60, 0.75)
        weight = float(sum(b[1] for b in boxes))
    elif modal == Modal.LCL:
        volume = _clamp(rng.lognormvariate(math.log(4), 0.6), 1, 15)
        weight = volume * rng.uniform(150, 400)
        value = max(volume, 1) * rng.uniform(60, 120)
    elif modal == Modal.AEREO:
        weight = _clamp(rng.lognormvariate(math.log(350), 0.9), 50, 3_000)
        volume = weight / rng.uniform(120, 300)
        taxable = _dec(max(weight, volume * 167))
        value = float(taxable) * rng.uniform(3.5, 7)
    elif modal == Modal.RODOVIARIO:
        weight, volume = rng.uniform(5_000, 27_000), rng.uniform(20, 90)
        value, currency = rng.uniform(8_000, 15_000), "BRL"
    elif modal == Modal.ISOTANQUE:
        count = rng.choices([1, 2, 3], weights=[60, 30, 10])[0]
        boxes = [("ISO20", _dec(rng.uniform(18_000, 26_000))) for _ in range(count)]
        weight, volume = float(sum(b[1] for b in boxes)), count * rng.uniform(21, 26)
        value = count * rng.uniform(3_000, 6_000)
    else:  # PROJETO
        weight, volume = rng.uniform(20_000, 200_000), rng.uniform(50, 600)
        value = rng.uniform(20_000, 120_000)
    cargo = _Cargo(tuple(boxes), _dec(weight), _dec(volume), taxable)
    return cargo, _dec(value), currency


def _decide(
    rng: random.Random,
    config: SyntheticConfig,
    drafts: list[_QuoteDraft],
    propensity: Mapping[str, float],
    end: datetime,
) -> dict[int, tuple[QuoteStatus, str | None]]:
    """Escolhe as ganhas (cota exata por modal) e o destino das demais."""
    cutoff = end - timedelta(days=OPEN_QUOTE_DAYS)
    decisions: dict[int, tuple[QuoteStatus, str | None]] = {
        i: (QuoteStatus.EM_ABERTO, None) for i, d in enumerate(drafts) if d.solicitada >= cutoff
    }
    eligible = [i for i, d in enumerate(drafts) if d.solicitada < cutoff]

    def chance(i: int) -> float:
        hours = drafts[i].response_hours
        speed = 1.17 if hours < 24 else 1.0 if hours <= 72 else 0.6
        return propensity[drafts[i].customer.vendedor_id] * speed

    total_won = round(len(drafts) * float(config.taxa_ganho))
    won: set[int] = set()
    for modal, count in _quota(config.modais, total_won).items():
        pool = [i for i in eligible if drafts[i].modal == modal]
        # Amostragem ponderada sem reposição (Efraimidis-Spirakis): maior chave vence.
        keys = sorted(((rng.random() ** (1 / chance(i)), i) for i in pool), reverse=True)
        won.update(i for _, i in keys[:count])

    rest = [i for i in eligible if i not in won]
    outcomes = _shuffled_quota(
        rng,
        {
            QuoteStatus.PERDIDA: config.proporcao_perdida,
            QuoteStatus.EXPIRADA: config.proporcao_expirada,
        },
        len(rest),
    )
    reasons = list(config.motivos_perda)
    reason_weights = [float(w) for w in config.motivos_perda.values()]
    for i in won:
        decisions[i] = (QuoteStatus.GANHA, None)
    for i, status in zip(rest, outcomes, strict=True):
        reason = (
            rng.choices(reasons, weights=reason_weights)[0]
            if status == QuoteStatus.PERDIDA
            else None
        )
        decisions[i] = (status, reason)
    return decisions


def _quote(index: int, draft: _QuoteDraft, status: QuoteStatus, reason: str | None) -> Quote:
    return Quote(
        cotacao_id=f"Q{index + 1:06d}",
        cliente_id=draft.customer.cliente_id,
        vendedor_id=draft.customer.vendedor_id,
        modal=draft.modal,
        direcao=draft.route.direcao,
        rota_codigo=draft.route.codigo,
        origem=draft.route.origem,
        destino=draft.route.destino,
        solicitada_em=draft.solicitada,
        respondida_em=draft.respondida,
        valor_frete=draft.valor,
        moeda=draft.moeda,
        quantidade_equipamentos=len(draft.cargo.boxes),
        peso_kg=draft.cargo.peso_kg,
        volume_m3=draft.cargo.volume_m3,
        status=status,
        motivo_perda=reason,
    )


# ------------------------------------------------------------------ embarques


class _ShipmentBuilder:
    """Transforma cotações ganhas em embarques, equipamentos, financeiro e eventos."""

    def __init__(
        self, rng: random.Random, config: SyntheticConfig, reference: Reference, end: datetime
    ) -> None:
        self.rng, self.config, self.end = rng, config, end
        self.carriers = reference.armadores
        self.airlines = reference.cias_aereas
        low, high = config.pontualidade_armador.minimo, config.pontualidade_armador.maximo
        n = len(self.carriers)
        self.punctuality = {
            c.codigo: float(low + (high - low) * i / max(n - 1, 1))
            for i, c in enumerate(self.carriers)
        }
        self.shipments: list[Shipment] = []
        self.equipment: list[Equipment] = []
        self.financial: list[FinancialItem] = []
        self._events: list[tuple[datetime, str, int, TrackingEventType, str, datetime | None]] = []
        self._sequence: Counter[tuple[str, int]] = Counter()
        self._used_numbers: set[str] = set()

    def add(self, quote_id: str, draft: _QuoteDraft) -> None:
        rng, route, modal = self.rng, draft.route, draft.modal
        booking, etd = draft.booking, draft.etd
        eta = _minute(etd + timedelta(days=float(route.transit_medio)))
        carrier, airline, on_time_chance = self._carrier(modal)
        if etd.month in self.config.meses_pico:
            on_time_chance -= float(self.config.queda_pontualidade_pico)
        late = rng.random() >= on_time_chance
        slip, departure = self._slips(late, modal, float(route.transit_medio))
        atd_planned = _minute(etd + timedelta(days=departure))
        ata_planned = _minute(eta + timedelta(days=slip))
        atd = atd_planned if atd_planned <= self.end else None
        ata = ata_planned if atd is not None and ata_planned <= self.end else None
        release = _minute(ata_planned + timedelta(days=rng.uniform(2, 6)))

        prefix = "IMP" if route.direcao == Direction.IMPORTACAO else "EXP"
        self._sequence[(prefix, booking.year)] += 1
        process = f"{prefix}-{booking.year}-{self._sequence[(prefix, booking.year)]:06d}"
        boxes = self._equipment(process, draft, carrier)
        demurrage_days, returned = self._container_return(draft, boxes, ata_planned, release)
        awb = self._awb(airline) if airline else None
        self.shipments.append(
            Shipment(
                processo=process,
                cotacao_id=quote_id,
                cliente_id=draft.customer.cliente_id,
                modal=modal,
                direcao=route.direcao,
                rota_codigo=route.codigo,
                origem=route.origem,
                destino=route.destino,
                armador_codigo=carrier.codigo if carrier else None,
                cia_aerea_prefixo=airline.prefixo_awb if airline else None,
                awb=awb,
                bl_numero=f"FSCX{len(self.shipments) + 1:08d}" if modal in MARITIME else None,
                booking_em=booking,
                etd=etd,
                eta=eta,
                atd=atd,
                ata=ata,
                status=self._status(route.direcao, atd, ata, release),
                quantidade_equipamentos=len(boxes),
                teus=sum(2 if b.tipo == "40HC" else 1 for b in boxes),
                peso_kg=draft.cargo.peso_kg,
                volume_m3=draft.cargo.volume_m3,
                peso_taxavel_kg=draft.cargo.peso_taxavel_kg,
            )
        )
        if atd is not None:
            self._finance(process, draft, boxes, atd, ata, demurrage_days, returned)
        self._tracking(
            process,
            draft,
            booking,
            etd,
            eta,
            atd,
            ata,
            atd_planned,
            ata_planned,
            late,
            slip,
            release,
            returned,
        )

    # -------------------------------------------------------------- partes do embarque

    def _container_return(
        self,
        draft: _QuoteDraft,
        boxes: list[Equipment],
        ata: datetime,
        release: datetime,
    ) -> tuple[int | None, datetime | None]:
        """(dias de demurrage, devolução do vazio) dos contêineres de importação.

        Sem demurrage, o importador devolve depois da liberação e dentro do free time. Com
        demurrage (~8% dos FCL), devolve `dias` depois do fim do free time, e a cobrança vem
        na devolução. Exportação: a devolução é do comprador no destino, fora do escopo.
        """
        if draft.route.direcao != Direction.IMPORTACAO or not boxes:
            return None, None
        rng, cfg = self.rng, self.config.demurrage
        free_time = max(b.free_time_dias for b in boxes)
        if draft.modal == Modal.FCL and rng.random() < float(cfg.taxa_fcl):
            days = rng.randint(int(cfg.dias.minimo), int(cfg.dias.maximo))
            return days, _minute(ata + timedelta(days=free_time + days))
        released_after = (release - ata).total_seconds() / 86_400
        window = free_time - released_after - 0.1  # sempre >= 0,9 dia (free time >= 7)
        return None, _minute(release + timedelta(days=rng.uniform(0.5, window)))

    def _carrier(self, modal: Modal) -> tuple[Carrier | None, Airline | None, float]:
        if modal in MARITIME:
            carrier = self.rng.choice(self.carriers)
            return carrier, None, self.punctuality[carrier.codigo]
        other = float(self.config.pontualidade_outros)
        if modal == Modal.AEREO:
            return None, self.rng.choice(self.airlines), other
        return None, None, other

    def _slips(self, late: bool, modal: Modal, transit: float) -> tuple[float, float]:
        """(atraso na chegada em relação ao ETA, atraso na saída em relação ao ETD), em dias."""
        rng = self.rng
        if late:
            # Cauda proporcional ao modal e à viagem: voo de 3 dias não atrasa 40.
            median, modal_cap = LATE_PROFILE.get(modal, (3.0, 44.0))
            cap = min(modal_cap, 1.5 * transit)
            slip = 1 + max(1 / 24, min(cap, rng.lognormvariate(math.log(median), 0.9)))
            return slip, rng.uniform(0, min(3.0, slip / 2))
        slip = rng.uniform(-min(2.0, 0.3 * transit), 1.0)
        departure = rng.uniform(-0.5, 2.0) if modal in MARITIME else rng.uniform(-0.25, 0.5)
        return slip, departure

    def _status(
        self, direction: Direction, atd: datetime | None, ata: datetime | None, release: datetime
    ) -> ShipmentStatus:
        if atd is None:
            return ShipmentStatus.AGUARDANDO_EMBARQUE
        if ata is None:
            return ShipmentStatus.EM_TRANSITO
        if direction == Direction.EXPORTACAO:
            return ShipmentStatus.ENTREGUE
        return ShipmentStatus.LIBERADO if release <= self.end else ShipmentStatus.CHEGADA

    def _equipment(
        self, process: str, draft: _QuoteDraft, carrier: Carrier | None
    ) -> list[Equipment]:
        if draft.modal not in CONTAINERIZED or carrier is None:
            return []
        boxes = []
        for kind, weight in draft.cargo.boxes:
            number = generate_valid_container(self.rng, owner=carrier.prefixo_bic)
            while number in self._used_numbers:
                number = generate_valid_container(self.rng, owner=carrier.prefixo_bic)
            self._used_numbers.add(number)
            free_time = self.rng.choice([7, 10, 14])
            boxes.append(
                Equipment(
                    processo=process,
                    numero=number,
                    tipo=kind,
                    peso_kg=weight,
                    free_time_dias=free_time,
                )
            )
        self.equipment.extend(boxes)
        return boxes

    def _awb(self, airline: Airline) -> str:
        number = generate_valid_awb(self.rng, prefix=airline.prefixo_awb)
        while number in self._used_numbers:
            number = generate_valid_awb(self.rng, prefix=airline.prefixo_awb)
        self._used_numbers.add(number)
        return number

    def _finance(
        self,
        process: str,
        draft: _QuoteDraft,
        boxes: list[Equipment],
        atd: datetime,
        ata: datetime | None,
        demurrage_days: int | None,
        returned: datetime | None,
    ) -> None:
        rng, cfg = self.rng, self.config
        margin = rng.triangular(
            float(cfg.margem.minima), float(cfg.margem.maxima), float(cfg.margem.moda)
        )

        def pair(
            category: FinancialCategory, cost: float, currency: Currency, day: datetime
        ) -> None:
            self._item(process, FinancialType.CUSTO, category, cost, currency, day)
            self._item(process, FinancialType.RECEITA, category, cost / (1 - margin), currency, day)

        # Frete: a receita é o valor cotado; o custo sai da margem sorteada.
        self._item(
            process,
            FinancialType.CUSTO,
            FinancialCategory.FRETE,
            float(draft.valor) * (1 - margin),
            draft.moeda,
            atd,
        )
        self._item(
            process,
            FinancialType.RECEITA,
            FinancialCategory.FRETE,
            float(draft.valor),
            draft.moeda,
            atd,
        )
        thc = self._thc(draft, boxes)
        if thc:
            pair(FinancialCategory.THC, thc, "BRL", atd)
        if rng.random() < 0.4:
            pair(FinancialCategory.SEGURO, rng.uniform(200, 2_500), "BRL", atd)
        importing = draft.route.direcao == Direction.IMPORTACAO
        if importing and draft.modal != Modal.RODOVIARIO and ata is not None and rng.random() < 0.6:
            pair(FinancialCategory.ARMAZENAGEM, rng.uniform(800, 5_000), "BRL", ata)
        # Demurrage no Brasil é do importador; na exportação, quem paga é o comprador lá fora.
        # A cobrança vem na devolução do vazio, decidida em _container_return.
        if demurrage_days is not None and returned is not None and ata is not None:
            daily = rng.uniform(
                float(cfg.demurrage.diaria_usd.minimo), float(cfg.demurrage.diaria_usd.maximo)
            )
            absorbed = rng.random() < float(cfg.demurrage.taxa_absorvida)
            charged_at = returned
            if charged_at <= self.end:
                cost = demurrage_days * daily * len(boxes)
                if absorbed:
                    self._item(
                        process,
                        FinancialType.CUSTO,
                        FinancialCategory.DEMURRAGE,
                        cost,
                        "USD",
                        charged_at,
                    )
                else:
                    pair(FinancialCategory.DEMURRAGE, cost, "USD", charged_at)

    def _thc(self, draft: _QuoteDraft, boxes: list[Equipment]) -> float:
        rng = self.rng
        if draft.modal == Modal.FCL:
            return sum(rng.uniform(1_200, 1_800) for _ in boxes)
        if draft.modal == Modal.ISOTANQUE:
            return sum(rng.uniform(1_300, 1_900) for _ in boxes)
        if draft.modal == Modal.LCL:
            return rng.uniform(300, 600)
        if draft.modal == Modal.AEREO:
            return max(150.0, 0.5 * float(draft.cargo.peso_taxavel_kg or 0))
        if draft.modal == Modal.PROJETO:
            return rng.uniform(8_000, 25_000)
        return 0.0  # rodoviário não tem terminal

    def _item(
        self,
        process: str,
        kind: FinancialType,
        category: FinancialCategory,
        value: float,
        currency: Currency,
        day: datetime,
    ) -> None:
        self.financial.append(
            FinancialItem(
                item_id=f"F{len(self.financial) + 1:07d}",
                processo=process,
                tipo=kind,
                categoria=category,
                valor=_dec(value),
                moeda=currency,
                competencia=day.date(),
            )
        )

    def _tracking(
        self,
        process: str,
        draft: _QuoteDraft,
        booking: datetime,
        etd: datetime,
        eta: datetime,
        atd: datetime | None,
        ata: datetime | None,
        atd_planned: datetime,
        ata_planned: datetime,
        late: bool,
        slip: float,
        release: datetime,
        returned: datetime | None,
    ) -> None:
        rng, route = self.rng, draft.route
        add = self._event
        add(booking, process, TrackingEventType.BOOKING_CONFIRMADO, route.origem)
        if draft.modal in (Modal.FCL, Modal.LCL, Modal.ISOTANQUE):
            add(
                _minute(etd - timedelta(days=rng.uniform(1, 4))),
                process,
                TrackingEventType.GATE_IN,
                route.origem,
            )
        if atd is None:
            return
        add(atd, process, TrackingEventType.EMBARQUE, route.origem)
        voyage = ata_planned - atd_planned
        if draft.modal in MARITIME and route.regiao_externa == "ASIA" and rng.random() < 0.3:
            hub = "SGSIN" if "SGSIN" not in (route.origem, route.destino) else "HKHKG"
            add(
                _minute(atd_planned + voyage * rng.uniform(0.4, 0.6)),
                process,
                TrackingEventType.TRANSBORDO,
                hub,
            )
        if late:
            updates = rng.randint(1, 3)
            for j in range(1, updates + 1):
                new_eta = _minute(eta + timedelta(days=1 + max(0.25, (slip - 1) * j / updates)))
                moment = _minute(atd_planned + voyage * (j / (updates + 1)))
                add(moment, process, TrackingEventType.ETA_ATUALIZADO, route.destino, new_eta)
        if ata is None:
            return
        add(ata, process, TrackingEventType.CHEGADA, route.destino)
        if route.direcao == Direction.IMPORTACAO:
            add(release, process, TrackingEventType.LIBERACAO, route.destino)
        if returned is not None:
            add(returned, process, TrackingEventType.DEVOLUCAO_VAZIO, route.destino)

    def _event(
        self,
        moment: datetime,
        process: str,
        kind: TrackingEventType,
        place: str,
        eta: datetime | None = None,
    ) -> None:
        if moment <= self.end:
            self._events.append((moment, process, len(self._events), kind, place, eta))

    def events(self) -> list[TrackingEvent]:
        ordered = sorted(self._events, key=lambda e: (e[0], e[1], e[2]))
        return [
            TrackingEvent(
                evento_id=f"E{i + 1:07d}",
                processo=process,
                tipo=kind,
                ocorrido_em=moment,
                local=place,
                eta_informada=eta,
            )
            for i, (moment, process, _, kind, place, eta) in enumerate(ordered)
        ]


# ------------------------------------------------------------------ utilitários


def _quota(shares: Mapping[K, Decimal | float], total: int) -> dict[K, int]:
    """Divide `total` conforme as proporções pelo método do maior resto (soma exata)."""
    weight_sum = sum(float(v) for v in shares.values())
    exact = {k: total * float(v) / weight_sum for k, v in shares.items()}
    counts = {k: math.floor(x) for k, x in exact.items()}
    leftover = total - sum(counts.values())
    by_remainder = sorted(exact, key=lambda k: exact[k] - counts[k], reverse=True)
    for k in by_remainder[:leftover]:
        counts[k] += 1
    return counts


def _shuffled_quota(rng: random.Random, shares: Mapping[K, Decimal | float], total: int) -> list[K]:
    items: list[K] = [k for k, n in _quota(shares, total).items() for _ in range(n)]
    rng.shuffle(items)
    return items


def _dec(value: float | Decimal, places: int = 2) -> Decimal:
    return Decimal(f"{float(value):.{places}f}")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


__all__: Sequence[str] = ["Dataset", "generate"]

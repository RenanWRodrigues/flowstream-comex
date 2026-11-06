"""Leitura das consultas operacionais na camada ouro (e no staging de equipamentos)."""

from sqlalchemy import Engine, text

from flowstream.operations.domain import ContainerRisk, ContainerTimeline, TrackingEvent


class PostgresOperationsRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def find_timeline(self, container_number: str) -> ContainerTimeline | None:
        with self._engine.connect() as conn:
            shipment = (
                conn.execute(
                    text(
                        """
                        select eq.container_numero, f.processo, f.modal, f.direcao, f.origem,
                            f.destino, f.status, f.etd, f.eta, f.atd, f.ata
                        from prata.stg_equipamentos as eq
                        inner join ouro.fct_embarque as f on f.processo = eq.processo
                        where eq.container_numero = :numero
                        order by f.booking_em desc
                        limit 1
                        """
                    ),
                    {"numero": container_number},
                )
                .mappings()
                .first()
            )
            if shipment is None:
                return None
            events = conn.execute(
                text(
                    """
                    select tipo, ocorrido_em, local_codigo as local, eta_informada
                    from ouro.fct_tracking_evento
                    where processo = :processo
                    order by ocorrido_em, evento_id
                    """
                ),
                {"processo": shipment["processo"]},
            ).mappings()
            return ContainerTimeline(
                **shipment, eventos=[TrackingEvent(**event) for event in events]
            )

    def list_demurrage_risk(self, max_days: int) -> list[ContainerRisk]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    select processo, container_numero, armador_codigo, destino, data_ata,
                        free_time_dias, dias_livres_restantes, faixa_risco, data_referencia
                    from ouro.kpi_demurrage_risco
                    where dias_livres_restantes <= :dias
                    order by dias_livres_restantes, processo, container_numero
                    """
                ),
                {"dias": max_days},
            ).mappings()
            return [ContainerRisk(**row) for row in rows]

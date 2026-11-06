"""Casos de uso operacionais: linha do tempo de um contêiner e contêineres em risco."""

from typing import Protocol

from flowstream.operations.domain import ContainerRisk, ContainerTimeline, normalize_container

MAX_RISK_DAYS = 60


class OperationsRepository(Protocol):
    def find_timeline(self, container_number: str) -> ContainerTimeline | None: ...

    def list_demurrage_risk(self, max_days: int) -> list[ContainerRisk]: ...


def container_timeline(
    raw_number: str, repository: OperationsRepository
) -> ContainerTimeline | None:
    """Linha do tempo do processo mais recente do contêiner (InvalidContainerError se inválido)."""
    return repository.find_timeline(normalize_container(raw_number))


def demurrage_risk(max_days: int, repository: OperationsRepository) -> list[ContainerRisk]:
    """Contêineres em aberto com até `max_days` dias livres (inclui os já vencidos)."""
    if not 0 <= max_days <= MAX_RISK_DAYS:
        raise ValueError(f"dias deve estar entre 0 e {MAX_RISK_DAYS}.")
    return repository.list_demurrage_risk(max_days)

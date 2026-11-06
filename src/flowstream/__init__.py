"""FlowStream-Comex: plataforma de dados para um agente de cargas internacional."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("flowstream-comex")
except PackageNotFoundError:  # pragma: no cover - só ocorre sem o pacote instalado
    __version__ = "0.0.0"

"""Extração genérica da OpenF1 guiada pelo registro de endpoints."""

from pydantic import TypeAdapter, ValidationError

from f1.domain.sessions import SessionInfo
from f1.exceptions import ExtractionError
from f1.extractors.client import OpenF1Client
from f1.schemas.endpoints import EndpointSpec, Partition, Record

_SESSIONS_ADAPTER = TypeAdapter(list[SessionInfo])


class OpenF1Extractor:
    """Busca os registros de um endpoint para uma partição do lake."""

    def __init__(self, client: OpenF1Client) -> None:
        self._client = client

    def extract(self, spec: EndpointSpec, partition: Partition) -> list[Record]:
        """Busca os registros brutos de ``spec`` na ``partition``.

        Args:
            spec: Endpoint a consultar; o escopo define os filtros.
            partition: Partição com ``year``, ``session_key`` e ``driver_number``.

        Returns:
            Registros JSON exatamente como a API devolveu.
        """
        return self._client.get(spec.name, partition.query_params(spec.scope))

    def session_info(self, session_key: int) -> SessionInfo:
        """Busca os metadados de uma sessão.

        Raises:
            ExtractionError: Se a sessão não existir ou vier fora do contrato.
        """
        sessions = parse_sessions(self._client.get("sessions", {"session_key": session_key}))
        if not sessions:
            raise ExtractionError(f"Sessão session_key={session_key} não encontrada na OpenF1")
        return sessions[0]


def parse_sessions(records: list[Record]) -> list[SessionInfo]:
    """Valida registros do endpoint ``sessions`` e os converte em ``SessionInfo``.

    Raises:
        ExtractionError: Se algum registro não seguir o contrato mínimo.
    """
    try:
        return _SESSIONS_ADAPTER.validate_python(records)
    except ValidationError as exc:
        raise ExtractionError(f"Registros de sessions fora do contrato: {exc}") from exc

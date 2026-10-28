"""Regras de negócio sobre sessões: o que pode ser ingerido e quando."""

from dataclasses import dataclass
from datetime import datetime

RACE_SESSION_TYPE = "Race"


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Metadados mínimos de uma sessão, vindos do endpoint ``sessions``."""

    session_key: int
    meeting_key: int
    year: int
    session_type: str
    session_name: str
    date_start: datetime
    date_end: datetime
    is_cancelled: bool = False

    @property
    def is_race(self) -> bool:
        """Corridas e sprints (``session_type == "Race"``)."""
        return self.session_type == RACE_SESSION_TYPE

    def skip_reason(self, now: datetime) -> str | None:
        """Motivo para não ingerir a sessão agora, ou ``None`` se ela está pronta.

        Args:
            now: Instante atual (timezone-aware), injetado para testes determinísticos.
        """
        if self.is_cancelled:
            return "cancelada"
        if self.date_end > now:
            return "não encerrada"
        return None

    def has_telemetry(self, telemetry_session_types: frozenset[str]) -> bool:
        """Se a telemetria (``car_data``/``location``) deve ser buscada para esta sessão."""
        return self.session_type in telemetry_session_types

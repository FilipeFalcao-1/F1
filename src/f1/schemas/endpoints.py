"""Registro declarativo dos 18 endpoints da OpenF1 e da partição do lake."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from f1.exceptions import ConfigurationError

type Record = dict[str, object]
"""Um objeto JSON devolvido pela API."""


class Scope(StrEnum):
    """Granularidade da chamada à API, que também define a partição no lake."""

    YEAR = "year"
    SESSION = "session"
    SESSION_DRIVER = "session_driver"


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    """Metadados de um endpoint.

    Attributes:
        name: Nome do endpoint na API (``/v1/{name}``).
        scope: Granularidade da extração e da partição.
        primary_key: Colunas que identificam um registro na silver.
        race_only: Só existe para sessões ``session_type == "Race"`` (inclui sprints).
        deprecated_fields: Campos descartados na silver (serão removidos da API).
        beta: Endpoint em beta na OpenF1 (dados podem estar incompletos).
    """

    name: str
    scope: Scope
    primary_key: tuple[str, ...]
    race_only: bool = False
    deprecated_fields: tuple[str, ...] = ()
    beta: bool = False


_SESSION_DRIVER_DATE = ("session_key", "driver_number", "date")

ENDPOINTS: Mapping[str, EndpointSpec] = {
    spec.name: spec
    for spec in (
        EndpointSpec("meetings", Scope.YEAR, ("meeting_key",)),
        EndpointSpec("sessions", Scope.YEAR, ("session_key",)),
        EndpointSpec(
            "drivers",
            Scope.SESSION,
            ("session_key", "driver_number"),
            deprecated_fields=("country_code",),
        ),
        EndpointSpec("laps", Scope.SESSION, ("session_key", "driver_number", "lap_number")),
        EndpointSpec("stints", Scope.SESSION, ("session_key", "driver_number", "stint_number")),
        EndpointSpec(
            "pit",
            Scope.SESSION,
            ("session_key", "driver_number", "lap_number", "date"),
            deprecated_fields=("pit_duration",),
        ),
        EndpointSpec("session_result", Scope.SESSION, ("session_key", "driver_number")),
        EndpointSpec("starting_grid", Scope.SESSION, ("session_key", "driver_number")),
        EndpointSpec("position", Scope.SESSION, _SESSION_DRIVER_DATE),
        EndpointSpec("intervals", Scope.SESSION, _SESSION_DRIVER_DATE, race_only=True),
        EndpointSpec(
            "overtakes",
            Scope.SESSION,
            ("session_key", "date", "overtaking_driver_number", "overtaken_driver_number"),
            race_only=True,
        ),
        EndpointSpec(
            "championship_drivers",
            Scope.SESSION,
            ("session_key", "driver_number"),
            race_only=True,
            beta=True,
        ),
        EndpointSpec(
            "championship_teams",
            Scope.SESSION,
            ("session_key", "team_name"),
            race_only=True,
            beta=True,
        ),
        EndpointSpec("weather", Scope.SESSION, ("session_key", "date")),
        EndpointSpec("race_control", Scope.SESSION, ("session_key", "date", "category", "message")),
        EndpointSpec("team_radio", Scope.SESSION, _SESSION_DRIVER_DATE),
        EndpointSpec("car_data", Scope.SESSION_DRIVER, _SESSION_DRIVER_DATE),
        EndpointSpec("location", Scope.SESSION_DRIVER, _SESSION_DRIVER_DATE),
    )
}


def endpoints_by_scope(*scopes: Scope) -> tuple[EndpointSpec, ...]:
    """Endpoints dos escopos pedidos, na ordem do registro (``drivers`` antes da telemetria)."""
    return tuple(spec for spec in ENDPOINTS.values() if spec.scope in scopes)


def get_endpoints(names: str) -> tuple[EndpointSpec, ...]:
    """Converte uma lista separada por vírgula em specs, validando os nomes.

    Args:
        names: Nomes como ``"laps,stints"``.

    Returns:
        Specs na ordem do registro.

    Raises:
        ConfigurationError: Se algum nome não existir no registro.
    """
    wanted = {name.strip() for name in names.split(",") if name.strip()}
    unknown = wanted - ENDPOINTS.keys()
    if unknown or not wanted:
        raise ConfigurationError(
            f"Endpoints inválidos: {sorted(unknown) or names!r}. Válidos: {sorted(ENDPOINTS)}"
        )
    return tuple(spec for name, spec in ENDPOINTS.items() if name in wanted)


@dataclass(frozen=True, slots=True, order=True)
class Partition:
    """Partição do lake: ``year=Y[/session_key=N[/driver_number=D]]``."""

    year: int
    session_key: int | None = None
    driver_number: int | None = None

    @property
    def path(self) -> str:
        """Caminho relativo no estilo Hive."""
        parts = [f"year={self.year}"]
        if self.session_key is not None:
            parts.append(f"session_key={self.session_key}")
        if self.driver_number is not None:
            parts.append(f"driver_number={self.driver_number}")
        return "/".join(parts)

    @classmethod
    def from_path(cls, path: str) -> Partition:
        """Reconstrói a partição a partir do caminho relativo Hive.

        Raises:
            ConfigurationError: Se o caminho não seguir o layout esperado.
        """
        try:
            values = dict(part.split("=", 1) for part in path.split("/"))
            return cls(
                year=int(values["year"]),
                session_key=int(values["session_key"]) if "session_key" in values else None,
                driver_number=int(values["driver_number"]) if "driver_number" in values else None,
            )
        except (KeyError, ValueError) as exc:
            raise ConfigurationError(f"Partição inválida: {path!r}") from exc

    def query_params(self, scope: Scope) -> dict[str, int]:
        """Filtros da API que correspondem a esta partição no escopo dado.

        Raises:
            ConfigurationError: Se a partição não tiver as chaves exigidas pelo escopo.
        """
        if scope is Scope.YEAR:
            return {"year": self.year}
        if self.session_key is None:
            raise ConfigurationError(f"Escopo {scope} exige session_key: {self}")
        if scope is Scope.SESSION:
            return {"session_key": self.session_key}
        if self.driver_number is None:
            raise ConfigurationError(f"Escopo {scope} exige driver_number: {self}")
        return {"session_key": self.session_key, "driver_number": self.driver_number}

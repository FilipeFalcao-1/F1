"""Contratos de dados por endpoint: payload bruto da API e schema tipado da silver.

``raw`` descreve o que a API entrega (datas como texto; campos polimórficos, como
``intervals.interval``, como texto JSON). ``silver`` é o schema gravado em Parquet.
Mudanças na API (coluna nova ou ausente) falham o refine do endpoint de forma explícita.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

import polars as pl

from f1.schemas.endpoints import ENDPOINTS

INT = pl.Int64()
I32 = pl.Int32()
FLOAT = pl.Float64()
STR = pl.String()
BOOL = pl.Boolean()
JSON = pl.String()
"""Campo polimórfico (número, texto ou lista): mantido como texto JSON até a normalização."""
UTC = pl.Datetime("us", "UTC")

type Schema = Mapping[str, pl.DataType]


@dataclass(frozen=True, slots=True)
class Contract:
    """Contrato de um endpoint.

    Attributes:
        raw: Colunas e tipos do payload da API.
        silver: Colunas e tipos da silver, na ordem gravada.
        optional: Colunas que a API pode omitir (somadas aos campos deprecados).
    """

    raw: Schema
    silver: Schema
    optional: frozenset[str] = field(default_factory=frozenset)


def _silver(raw: Schema, overrides: Schema | None = None, drop: tuple[str, ...] = ()) -> Schema:
    """Deriva o schema silver: ``overrides`` troca tipos ou acrescenta colunas; ``drop`` remove."""
    overrides = overrides or {}
    schema = {name: overrides.get(name, dtype) for name, dtype in raw.items() if name not in drop}
    return schema | {name: dtype for name, dtype in overrides.items() if name not in schema}


def _gap(prefix: str) -> Schema:
    return {f"{prefix}_seconds": FLOAT, f"{prefix}_laps_behind": I32}


_KEYS: Schema = {"meeting_key": INT, "session_key": INT}
_SESSION_DRIVER: Schema = {**_KEYS, "driver_number": INT}
_TIMESTAMPED: Schema = {**_SESSION_DRIVER, "date": STR}
_DRIVER_DATE_SILVER: Schema = {"driver_number": I32, "date": UTC}

_RAW: dict[str, Schema] = {
    "meetings": {
        "meeting_key": INT,
        "meeting_name": STR,
        "meeting_official_name": STR,
        "location": STR,
        "country_key": INT,
        "country_code": STR,
        "country_name": STR,
        "country_flag": STR,
        "circuit_key": INT,
        "circuit_short_name": STR,
        "circuit_type": STR,
        "circuit_info_url": STR,
        "circuit_image": STR,
        "gmt_offset": STR,
        "date_start": STR,
        "date_end": STR,
        "year": INT,
        "is_cancelled": BOOL,
    },
    "sessions": {
        "session_key": INT,
        "session_type": STR,
        "session_name": STR,
        "date_start": STR,
        "date_end": STR,
        "meeting_key": INT,
        "circuit_key": INT,
        "circuit_short_name": STR,
        "country_key": INT,
        "country_code": STR,
        "country_name": STR,
        "location": STR,
        "gmt_offset": STR,
        "year": INT,
        "is_cancelled": BOOL,
    },
    "drivers": {
        **_SESSION_DRIVER,
        "broadcast_name": STR,
        "full_name": STR,
        "name_acronym": STR,
        "team_name": STR,
        "team_colour": STR,
        "first_name": STR,
        "last_name": STR,
        "headshot_url": STR,
        "country_code": STR,
    },
    "laps": {
        **_SESSION_DRIVER,
        "lap_number": INT,
        "date_start": STR,
        "duration_sector_1": FLOAT,
        "duration_sector_2": FLOAT,
        "duration_sector_3": FLOAT,
        "i1_speed": INT,
        "i2_speed": INT,
        "is_pit_out_lap": BOOL,
        "lap_duration": FLOAT,
        "segments_sector_1": pl.List(INT),
        "segments_sector_2": pl.List(INT),
        "segments_sector_3": pl.List(INT),
        "st_speed": INT,
    },
    "stints": {
        **_SESSION_DRIVER,
        "stint_number": INT,
        "lap_start": INT,
        "lap_end": INT,
        "compound": STR,
        "tyre_age_at_start": INT,
    },
    "pit": {
        **_TIMESTAMPED,
        "lap_number": INT,
        "lane_duration": FLOAT,
        "stop_duration": FLOAT,
        "pit_duration": FLOAT,
    },
    "session_result": {
        **_SESSION_DRIVER,
        "position": JSON,
        "number_of_laps": INT,
        "points": FLOAT,
        "dnf": BOOL,
        "dns": BOOL,
        "dsq": BOOL,
        "duration": JSON,
        "gap_to_leader": JSON,
    },
    "starting_grid": {**_SESSION_DRIVER, "position": INT, "lap_duration": FLOAT},
    "position": {**_TIMESTAMPED, "position": INT},
    "intervals": {**_TIMESTAMPED, "interval": JSON, "gap_to_leader": JSON},
    "overtakes": {
        **_KEYS,
        "overtaking_driver_number": INT,
        "overtaken_driver_number": INT,
        "date": STR,
        "position": INT,
    },
    "championship_drivers": {
        **_SESSION_DRIVER,
        "position_start": INT,
        "position_current": INT,
        "points_start": FLOAT,
        "points_current": FLOAT,
    },
    "championship_teams": {
        **_KEYS,
        "team_name": STR,
        "position_start": INT,
        "position_current": INT,
        "points_start": FLOAT,
        "points_current": FLOAT,
    },
    "weather": {
        **_KEYS,
        "date": STR,
        "air_temperature": FLOAT,
        "track_temperature": FLOAT,
        "humidity": FLOAT,
        "pressure": FLOAT,
        "rainfall": INT,
        "wind_direction": INT,
        "wind_speed": FLOAT,
    },
    "race_control": {
        **_KEYS,
        "date": STR,
        "driver_number": INT,
        "lap_number": INT,
        "category": STR,
        "flag": STR,
        "scope": STR,
        "sector": INT,
        "qualifying_phase": INT,
        "message": STR,
    },
    "team_radio": {**_TIMESTAMPED, "recording_url": STR},
    "car_data": {
        **_TIMESTAMPED,
        "speed": INT,
        "rpm": INT,
        "n_gear": INT,
        "throttle": INT,
        "brake": INT,
        "drs": INT,
    },
    "location": {**_TIMESTAMPED, "x": INT, "y": INT, "z": INT},
}

_SILVER: dict[str, Schema] = {
    "meetings": _silver(
        _RAW["meetings"], {"date_start": UTC, "date_end": UTC, "year": I32, "circuit_key": I32}
    ),
    "sessions": _silver(
        _RAW["sessions"], {"date_start": UTC, "date_end": UTC, "year": I32, "circuit_key": I32}
    ),
    "drivers": _silver(_RAW["drivers"], {"driver_number": I32}),
    "laps": _silver(
        _RAW["laps"],
        {
            "driver_number": I32,
            "lap_number": I32,
            "date_start": UTC,
            "i1_speed": I32,
            "i2_speed": I32,
            "st_speed": I32,
            "segments_sector_1": pl.List(I32),
            "segments_sector_2": pl.List(I32),
            "segments_sector_3": pl.List(I32),
        },
    ),
    "stints": _silver(
        _RAW["stints"],
        {
            "driver_number": I32,
            "stint_number": I32,
            "lap_start": I32,
            "lap_end": I32,
            "tyre_age_at_start": I32,
        },
    ),
    "pit": _silver(_RAW["pit"], {**_DRIVER_DATE_SILVER, "lap_number": I32}),
    "session_result": _silver(
        _RAW["session_result"],
        {
            "driver_number": I32,
            "position": I32,
            "position_code": STR,
            "number_of_laps": I32,
            "duration": FLOAT,
            "duration_q1": FLOAT,
            "duration_q2": FLOAT,
            "duration_q3": FLOAT,
            **_gap("gap_to_leader"),
            "gap_q1": FLOAT,
            "gap_q2": FLOAT,
            "gap_q3": FLOAT,
        },
        drop=("gap_to_leader",),
    ),
    "starting_grid": _silver(_RAW["starting_grid"], {"driver_number": I32, "position": I32}),
    "position": _silver(_RAW["position"], {**_DRIVER_DATE_SILVER, "position": I32}),
    "intervals": _silver(
        _RAW["intervals"],
        {**_DRIVER_DATE_SILVER, **_gap("interval"), **_gap("gap_to_leader")},
        drop=("interval", "gap_to_leader"),
    ),
    "overtakes": _silver(
        _RAW["overtakes"],
        {
            "overtaking_driver_number": I32,
            "overtaken_driver_number": I32,
            "date": UTC,
            "position": I32,
        },
    ),
    "championship_drivers": _silver(
        _RAW["championship_drivers"],
        {"driver_number": I32, "position_start": I32, "position_current": I32},
    ),
    "championship_teams": _silver(
        _RAW["championship_teams"], {"position_start": I32, "position_current": I32}
    ),
    "weather": _silver(_RAW["weather"], {"date": UTC, "rainfall": I32, "wind_direction": I32}),
    "race_control": _silver(
        _RAW["race_control"],
        {
            "date": UTC,
            "driver_number": I32,
            "lap_number": I32,
            "sector": I32,
            "qualifying_phase": I32,
        },
    ),
    "team_radio": _silver(_RAW["team_radio"], _DRIVER_DATE_SILVER),
    "car_data": _silver(
        _RAW["car_data"],
        {
            **_DRIVER_DATE_SILVER,
            "speed": I32,
            "rpm": I32,
            "n_gear": I32,
            "throttle": I32,
            "brake": I32,
            "drs": I32,
        },
    ),
    "location": _silver(_RAW["location"], {**_DRIVER_DATE_SILVER, "x": I32, "y": I32, "z": I32}),
}

_OPTIONAL: dict[str, frozenset[str]] = {
    "pit": frozenset({"stop_duration"}),
    "session_result": frozenset({"points"}),
}

CONTRACTS: Mapping[str, Contract] = {
    name: Contract(
        raw=_RAW[name],
        silver={
            column: dtype
            for column, dtype in _SILVER[name].items()
            if column not in spec.deprecated_fields
        },
        optional=_OPTIONAL.get(name, frozenset()) | frozenset(spec.deprecated_fields),
    )
    for name, spec in ENDPOINTS.items()
}

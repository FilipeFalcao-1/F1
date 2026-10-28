"""Leitura dos marts ``gold_*`` para consumo (dashboard)."""

from collections.abc import Sequence

import duckdb
import polars as pl

REQUIRED_TABLES = ("gold_race_results", "gold_lap_pace", "gold_stint_summary", "gold_pit_stops")

_RACES = """
SELECT DISTINCT year, session_key, meeting_name, session_name, date_start
FROM gold_race_results
ORDER BY date_start DESC
"""

_RACE_RESULTS = """
SELECT
    position, name_acronym, full_name, team_name, grid_position, positions_gained,
    points, number_of_laps, gap_to_leader_seconds, gap_to_leader_laps_behind, dnf, dns, dsq
FROM gold_race_results
WHERE session_key = ?
ORDER BY position NULLS LAST, grid_position NULLS LAST
"""

_CLEAN_LAPS = """
WITH clean AS (
    SELECT
        name_acronym, lap_number, lap_duration, compound, tyre_age,
        median(lap_duration) OVER () AS session_median
    FROM gold_lap_pace
    WHERE session_key = ? AND is_clean_lap
)
SELECT name_acronym, lap_number, lap_duration, compound, tyre_age
FROM clean
WHERE list_contains(?, name_acronym) AND lap_duration <= ? * session_median
ORDER BY name_acronym, lap_number
"""

_STINTS = """
SELECT
    s.name_acronym, s.stint_number, s.compound, s.first_lap, s.last_lap, s.laps, s.clean_laps,
    s.avg_clean_lap_duration, s.best_clean_lap_duration, s.degradation_s_per_lap,
    r.position
FROM gold_stint_summary AS s
LEFT JOIN gold_race_results AS r
    ON s.session_key = r.session_key AND s.driver_number = r.driver_number
WHERE s.session_key = ?
ORDER BY r.position NULLS LAST, s.name_acronym, s.stint_number
"""

_PIT_BY_TEAM = """
SELECT
    team_name,
    count(*) AS stops,
    median(lane_duration) AS median_lane_duration,
    median(stop_duration) AS median_stop_duration,
    count(stop_duration) AS stops_with_stationary_time
FROM gold_pit_stops
WHERE year = ? AND team_name IS NOT NULL
GROUP BY team_name
ORDER BY median_lane_duration
"""

_FASTEST_STOPS = """
SELECT
    p.date, r.meeting_name, p.session_name, p.name_acronym, p.team_name, p.lap_number,
    p.stop_duration, p.lane_duration
FROM gold_pit_stops AS p
LEFT JOIN (SELECT DISTINCT session_key, meeting_name FROM gold_race_results) AS r
    ON p.session_key = r.session_key
WHERE p.year = ? AND p.stop_duration IS NOT NULL
ORDER BY p.stop_duration
LIMIT ?
"""

_CHAMPIONSHIP = """
SELECT
    date_start, meeting_name, session_name, competitor, competitor_name,
    position_current, points_current, points_gained
FROM gold_championship_progression
WHERE year = ? AND championship = ?
ORDER BY date_start, position_current
"""


class MartsReader:
    """Consultas parametrizadas sobre os marts.

    Args:
        connection: Conexão DuckDB (em geral ``read_only``), gerida por quem chama.
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._conn = connection

    def _frame(self, sql: str, params: Sequence[object] = ()) -> pl.DataFrame:
        frame = pl.from_arrow(self._conn.sql(sql, params=list(params)).to_arrow_table())
        if not isinstance(frame, pl.DataFrame):
            raise TypeError("Consulta não devolveu uma tabela")
        return frame

    def is_ready(self) -> bool:
        """Se os marts exigidos pelo dashboard existem (``f1 marts build`` já rodou)."""
        tables = self._frame(
            "SELECT table_name FROM information_schema.tables WHERE table_name IN ?",
            [list(REQUIRED_TABLES)],
        )
        return tables.height == len(REQUIRED_TABLES)

    def races(self) -> pl.DataFrame:
        """Corridas e sprints com resultado, da mais recente para a mais antiga."""
        return self._frame(_RACES)

    def race_results(self, session_key: int) -> pl.DataFrame:
        """Resultado de uma corrida, na ordem de chegada."""
        return self._frame(_RACE_RESULTS, [session_key])

    def clean_laps(
        self, session_key: int, drivers: Sequence[str], max_ratio: float = 1.07
    ) -> pl.DataFrame:
        """Voltas limpas dos pilotos pedidos (por sigla).

        Exclui pit, volta 1 e voltas acima de ``max_ratio`` vezes a mediana da sessão
        (safety car, bandeira vermelha), que achatariam a comparação de ritmo.
        """
        return self._frame(_CLEAN_LAPS, [session_key, list(drivers), max_ratio])

    def stints(self, session_key: int) -> pl.DataFrame:
        """Stints da sessão, ordenados pela posição final do piloto."""
        return self._frame(_STINTS, [session_key])

    def pit_stops_by_team(self, year: int) -> pl.DataFrame:
        """Mediana do tempo no pit lane e parado, por equipe, na temporada."""
        return self._frame(_PIT_BY_TEAM, [year])

    def fastest_stops(self, year: int, limit: int = 10) -> pl.DataFrame:
        """Paradas mais rápidas (tempo parado) da temporada."""
        return self._frame(_FASTEST_STOPS, [year, limit])

    def championship(self, year: int, championship: str) -> pl.DataFrame:
        """Pontos e posição após cada corrida (``championship``: ``driver`` ou ``team``)."""
        return self._frame(_CHAMPIONSHIP, [year, championship])

-- Uma linha por volta e piloto, com o pneu em uso (laps × stints) e flags de pit.
-- is_clean_lap: volta cronometrada, fora da volta 1 e sem entrada ou saída do pit.
WITH pit_laps AS (
    SELECT DISTINCT session_key, driver_number, lap_number
    FROM silver_pit
)

SELECT
    l.year,
    l.meeting_key,
    l.session_key,
    l.driver_number,
    d.name_acronym,
    d.team_name,
    l.lap_number,
    l.date_start,
    l.lap_duration,
    l.duration_sector_1,
    l.duration_sector_2,
    l.duration_sector_3,
    l.st_speed,
    s.stint_number,
    s.compound,
    s.tyre_age_at_start + (l.lap_number - s.lap_start) AS tyre_age,
    coalesce(l.is_pit_out_lap, false) AS is_pit_out_lap,
    p.lap_number IS NOT NULL AS is_pit_in_lap,
    l.lap_duration IS NOT NULL
    AND l.lap_number > 1
    AND NOT coalesce(l.is_pit_out_lap, false)
    AND p.lap_number IS NULL AS is_clean_lap
FROM silver_laps AS l
LEFT JOIN silver_stints AS s
    ON
        l.session_key = s.session_key
        AND l.driver_number = s.driver_number
        AND l.lap_number BETWEEN s.lap_start AND s.lap_end
LEFT JOIN silver_drivers AS d
    ON l.session_key = d.session_key AND l.driver_number = d.driver_number
LEFT JOIN pit_laps AS p
    ON
        l.session_key = p.session_key
        AND l.driver_number = p.driver_number
        AND l.lap_number = p.lap_number
-- Stints sobrepostos na fonte não podem duplicar voltas: fica o stint mais recente.
QUALIFY row_number() OVER (
    PARTITION BY l.session_key, l.driver_number, l.lap_number
    ORDER BY s.stint_number DESC NULLS LAST
) = 1

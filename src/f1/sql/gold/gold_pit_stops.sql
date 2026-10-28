-- Paradas nos boxes por corrida (inclui sprints), numeradas por piloto.
-- stop_duration só existe a partir do GP dos EUA de 2024.
SELECT
    p.year,
    p.meeting_key,
    p.session_key,
    s.session_name,
    p.driver_number,
    d.name_acronym,
    d.team_name,
    row_number() OVER (PARTITION BY p.session_key, p.driver_number ORDER BY p.date) AS stop_number,
    p.lap_number,
    p.date,
    p.lane_duration,
    p.stop_duration
FROM silver_pit AS p
INNER JOIN silver_sessions AS s ON p.session_key = s.session_key
LEFT JOIN silver_drivers AS d
    ON p.session_key = d.session_key AND p.driver_number = d.driver_number
WHERE s.session_type = 'Race'

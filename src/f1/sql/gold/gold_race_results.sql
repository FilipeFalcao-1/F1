-- Resultado de cada corrida (inclui sprints) com grid de largada e posições ganhas.
-- A OpenF1 publica o starting_grid na classificação que define a largada:
-- 'Qualifying' → corrida; 'Sprint Qualifying'/'Sprint Shootout' → sprint.
WITH races AS (
    SELECT session_key, meeting_key, year, session_name, date_start
    FROM silver_sessions
    WHERE session_type = 'Race'
),

grid_sessions AS (
    SELECT
        session_key,
        meeting_key,
        CASE WHEN session_name = 'Qualifying' THEN 'Race' ELSE 'Sprint' END AS race_name
    FROM silver_sessions
    WHERE session_type = 'Qualifying'
    UNION ALL
    SELECT session_key, meeting_key, session_name AS race_name
    FROM races
),

grid AS (
    SELECT
        gs.meeting_key,
        gs.race_name,
        g.driver_number,
        min(g.position) AS grid_position
    FROM silver_starting_grid AS g
    INNER JOIN grid_sessions AS gs ON g.session_key = gs.session_key
    GROUP BY gs.meeting_key, gs.race_name, g.driver_number
)

SELECT
    r.year,
    r.meeting_key,
    m.meeting_name,
    r.session_key,
    r.session_name,
    r.date_start,
    res.driver_number,
    d.name_acronym,
    d.full_name,
    d.team_name,
    res.position,
    g.grid_position,
    g.grid_position - res.position AS positions_gained,
    res.points,
    res.number_of_laps,
    res.duration,
    res.gap_to_leader_seconds,
    res.gap_to_leader_laps_behind,
    res.dnf,
    res.dns,
    res.dsq
FROM silver_session_result AS res
INNER JOIN races AS r ON res.session_key = r.session_key
LEFT JOIN silver_meetings AS m ON r.meeting_key = m.meeting_key
LEFT JOIN silver_drivers AS d
    ON res.session_key = d.session_key AND res.driver_number = d.driver_number
LEFT JOIN grid AS g
    ON
        r.meeting_key = g.meeting_key
        AND r.session_name = g.race_name
        AND res.driver_number = g.driver_number

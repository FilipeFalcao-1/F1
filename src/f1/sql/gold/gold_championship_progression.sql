-- Pontos e posição no campeonato depois de cada corrida, para pilotos e equipes (beta na OpenF1).
WITH races AS (
    SELECT s.session_key, s.meeting_key, s.year, s.session_name, s.date_start, m.meeting_name
    FROM silver_sessions AS s
    LEFT JOIN silver_meetings AS m ON s.meeting_key = m.meeting_key
    WHERE s.session_type = 'Race'
)

SELECT
    r.year,
    r.meeting_key,
    r.meeting_name,
    r.session_key,
    r.session_name,
    r.date_start,
    'driver' AS championship,
    cast(c.driver_number AS VARCHAR) AS competitor,
    d.full_name AS competitor_name,
    c.position_start,
    c.position_current,
    c.points_start,
    c.points_current,
    c.points_current - c.points_start AS points_gained
FROM silver_championship_drivers AS c
INNER JOIN races AS r ON c.session_key = r.session_key
LEFT JOIN silver_drivers AS d
    ON c.session_key = d.session_key AND c.driver_number = d.driver_number

UNION ALL

SELECT
    r.year,
    r.meeting_key,
    r.meeting_name,
    r.session_key,
    r.session_name,
    r.date_start,
    'team' AS championship,
    c.team_name AS competitor,
    c.team_name AS competitor_name,
    c.position_start,
    c.position_current,
    c.points_start,
    c.points_current,
    c.points_current - c.points_start AS points_gained
FROM silver_championship_teams AS c
INNER JOIN races AS r ON c.session_key = r.session_key

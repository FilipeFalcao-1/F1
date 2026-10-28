-- Ritmo e degradação por stint. A degradação é a inclinação (s/volta) do tempo de volta
-- em função da idade do pneu, só com voltas limpas.
SELECT
    year,
    meeting_key,
    session_key,
    driver_number,
    name_acronym,
    team_name,
    stint_number,
    compound,
    min(lap_number) AS first_lap,
    max(lap_number) AS last_lap,
    count(*) AS laps,
    count(*) FILTER (WHERE is_clean_lap) AS clean_laps,
    avg(lap_duration) FILTER (WHERE is_clean_lap) AS avg_clean_lap_duration,
    median(lap_duration) FILTER (WHERE is_clean_lap) AS median_clean_lap_duration,
    min(lap_duration) FILTER (WHERE is_clean_lap) AS best_clean_lap_duration,
    regr_slope(lap_duration, tyre_age) FILTER (WHERE is_clean_lap) AS degradation_s_per_lap
FROM gold_lap_pace
WHERE stint_number IS NOT NULL
GROUP BY
    year, meeting_key, session_key, driver_number, name_acronym, team_name, stint_number, compound

-- Agregados de clima por sessão (amostras a cada ~1 min).
SELECT
    s.year,
    s.meeting_key,
    s.session_key,
    s.session_type,
    s.session_name,
    s.date_start,
    count(*) AS samples,
    avg(w.air_temperature) AS avg_air_temperature,
    min(w.air_temperature) AS min_air_temperature,
    max(w.air_temperature) AS max_air_temperature,
    avg(w.track_temperature) AS avg_track_temperature,
    min(w.track_temperature) AS min_track_temperature,
    max(w.track_temperature) AS max_track_temperature,
    avg(w.humidity) AS avg_humidity,
    avg(w.pressure) AS avg_pressure,
    max(w.wind_speed) AS max_wind_speed,
    coalesce(max(w.rainfall) > 0, false) AS had_rainfall
FROM silver_weather AS w
INNER JOIN silver_sessions AS s ON w.session_key = s.session_key
GROUP BY s.year, s.meeting_key, s.session_key, s.session_type, s.session_name, s.date_start

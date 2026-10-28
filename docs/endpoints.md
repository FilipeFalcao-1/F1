# Endpoints

O registro `f1.schemas.endpoints.ENDPOINTS` descreve os 18 endpoints. Um extractor genérico o percorre, então incluir um endpoint novo significa declarar o `EndpointSpec` e o contrato em `schemas/silver.py`.

| Endpoint | Escopo | Chave primária na silver | Particularidades |
|---|---|---|---|
| `meetings` | ano | `meeting_key` | Atualizado diariamente às 00:00 UTC |
| `sessions` | ano | `session_key` | Sprints têm `session_type = "Race"` |
| `drivers` | sessão | `session_key, driver_number` | `country_code` deprecado (descartado) |
| `laps` | sessão | `session_key, driver_number, lap_number` | `segments_sector_*` nulos em corridas |
| `stints` | sessão | `session_key, driver_number, stint_number` | — |
| `pit` | sessão | `session_key, driver_number, lap_number, date` | `stop_duration` só a partir do GP dos EUA de 2024; `pit_duration` deprecado |
| `session_result` | sessão | `session_key, driver_number` | Arrays Q1–Q3 na classificação; gap pode ser `"+N LAP(S)"`; `points` ausente na classificação |
| `starting_grid` | sessão | `session_key, driver_number` | Publicado na sessão de classificação |
| `position` | sessão | `session_key, driver_number, date` | — |
| `intervals` | sessão, só corridas | `session_key, driver_number, date` | Gaps podem ser `"+1 LAP"` |
| `overtakes` | sessão, só corridas | `session_key, date, overtaking_driver_number, overtaken_driver_number` | Pode estar incompleto |
| `championship_drivers` | sessão, só corridas (beta) | `session_key, driver_number` | Beta |
| `championship_teams` | sessão, só corridas (beta) | `session_key, team_name` | Beta |
| `weather` | sessão | `session_key, date` | Amostras a cada ~1 min |
| `race_control` | sessão | `session_key, date, category, message` | — |
| `team_radio` | sessão | `session_key, driver_number, date` | Seleção limitada; quase vazio a partir de 2026 |
| `car_data` | sessão + piloto | `session_key, driver_number, date` | ~3,7 Hz; só com `--with-telemetry` |
| `location` | sessão + piloto | `session_key, driver_number, date` | ~3,7 Hz; só com `--with-telemetry` |

- **Só corridas** (`race_only`): chamados apenas quando `session_type == "Race"`, o que evita chamadas vazias.
- **Telemetria**: buscada por piloto (lista de `drivers` da sessão) para limitar o tamanho de cada resposta, e só para os tipos de sessão em `F1_TELEMETRY_SESSION_TYPES`.

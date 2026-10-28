# OpenF1 API — Resumo

Fonte: https://openf1.org/docs/ — projeto não oficial, sem vínculo com a Fórmula 1.

## Visão geral

| Item | Detalhe |
|---|---|
| **Base URL** | `https://api.openf1.org/v1/{endpoint}` |
| **Autenticação** | Dados históricos: gratuitos, sem autenticação. Dados em tempo real: exigem assinatura paga. |
| **Cobertura histórica** | A partir de 2023 |
| **Formato** | JSON (padrão). CSV: adicione `csv=true` à query |
| **Rate limit / paginação** | Não documentados |

## Filtros

- Qualquer atributo pode ser filtrado via query string, exceto campos do tipo array.
- Operadores: `=`, `>`, `<`, `>=`, `<=`. Exemplo: `speed>=315`.
- Para vários valores, repita o parâmetro: `driver_number=4&driver_number=81`.
- `meeting_key=latest` / `session_key=latest` retornam o evento ou a sessão mais recente.
- Datas (`date`, `date_start`, `date_end`) usam ISO 8601 (também aceitam os formatos do `dateutil.parser` do Python).
  Exemplo: `date>2023-09-16T13:03:35.200&date<2023-09-16T13:03:35.800`

## Chaves principais (modelo de dados)

- **`meeting_key`**: fim de semana de GP ou de testes.
- **`session_key`**: sessão dentro de um meeting (treino, classificação, sprint, corrida).
- **`driver_number`**: número do piloto, que liga quase todos os endpoints.

Hierarquia: `meetings` → `sessions` → dados por piloto/sessão.

## Endpoints

### Calendário e contexto

| Endpoint | Descrição | Campos principais |
|---|---|---|
| `/meetings` | Fins de semana de GP/testes (atualizado diariamente à 00:00 UTC) | `meeting_key`, `meeting_name`, `year`, `circuit_key`, `circuit_short_name`, `country_name`, `location`, `date_start`, `date_end`, `gmt_offset`, `is_cancelled` |
| `/sessions` | Sessões de um meeting (atualizado diariamente à 00:00 UTC) | `session_key`, `session_name`, `session_type`, `meeting_key`, `year`, `date_start`, `date_end`, `circuit_short_name`, `country_name`, `is_cancelled` |
| `/drivers` | Dados dos pilotos por sessão | `driver_number`, `full_name`, `name_acronym`, `broadcast_name`, `team_name`, `team_colour`, `headshot_url` (`country_code` está deprecado) |
| `/weather` | Clima da pista (a cada ~1 min) | `air_temperature`, `track_temperature`, `humidity`, `pressure`, `rainfall`, `wind_speed`, `wind_direction` |
| `/race_control` | Bandeiras, safety car, incidentes, status da sessão | `category`, `flag`, `message`, `scope`, `sector`, `lap_number`, `driver_number`, `qualifying_phase` |

### Telemetria (alta frequência)

| Endpoint | Descrição | Campos principais |
|---|---|---|
| `/car_data` | Telemetria do carro (~3,7 Hz) | `speed`, `rpm`, `n_gear`, `throttle`, `brake`, `drs`, `date` |
| `/location` | Posição aproximada do carro em 3D (~3,7 Hz) | `x`, `y`, `z`, `date`. Mostra o progresso na pista, não a posição lateral. A origem é arbitrária. |

### Tempos e posições

| Endpoint | Descrição | Campos principais |
|---|---|---|
| `/laps` | Dados por volta | `lap_number`, `lap_duration`, `duration_sector_1/2/3`, `i1_speed`, `i2_speed`, `st_speed`, `is_pit_out_lap`, `segments_sector_1/2/3` (minissetores; indisponíveis em corridas) |
| `/intervals` | Gaps entre pilotos (só corridas, a cada ~4 s) | `gap_to_leader`, `interval` (pode ser `+1 LAP` ou `null`) |
| `/position` | Posição dos pilotos ao longo da sessão | `position`, `date` |
| `/overtakes` | Ultrapassagens (só corridas, podem estar incompletas) | `overtaking_driver_number`, `overtaken_driver_number`, `position`, `date` |

### Pit stops e pneus

| Endpoint | Descrição | Campos principais |
|---|---|---|
| `/pit` | Passagens pelo pit lane | `lap_number`, `lane_duration`, `stop_duration` (a partir do GP dos EUA de 2024; `pit_duration` está deprecado) |
| `/stints` | Períodos com o mesmo jogo de pneus | `stint_number`, `compound`, `lap_start`, `lap_end`, `tyre_age_at_start` |

### Resultados e campeonato

| Endpoint | Descrição | Campos principais |
|---|---|---|
| `/session_result` | Classificação final da sessão | `position`, `duration`, `gap_to_leader` (arrays Q1–Q3 na classificação), `number_of_laps`, `dnf`, `dns`, `dsq` |
| `/starting_grid` | Grid de largada | `position`, `driver_number`, `lap_duration` |
| `/championship_drivers` *(beta)* | Campeonato de pilotos (só corridas) | `points_start`, `points_current`, `position_start`, `position_current` |
| `/championship_teams` *(beta)* | Campeonato de construtores (só corridas) | `team_name`, `points_start`, `points_current`, `position_start`, `position_current` |

### Outros

| Endpoint | Descrição | Campos principais |
|---|---|---|
| `/team_radio` | Links de áudio (MP3) dos rádios. É uma seleção limitada, bem menor a partir de 2026. | `recording_url`, `driver_number`, `date` |

## Exemplos de requisição

```bash
# Telemetria de um piloto acima de 315 km/h
curl "https://api.openf1.org/v1/car_data?driver_number=55&session_key=9159&speed>=315"

# Sessões da última etapa
curl "https://api.openf1.org/v1/sessions?meeting_key=latest"

# Pódio de uma sessão em CSV
curl "https://api.openf1.org/v1/session_result?session_key=7782&position<=3&csv=true"

# Stints com pneus usados
curl "https://api.openf1.org/v1/stints?session_key=9165&tyre_age_at_start>=3"
```

```python
import requests
import pandas as pd

BASE = "https://api.openf1.org/v1"
laps = requests.get(f"{BASE}/laps", params={"session_key": 9161, "driver_number": 63}).json()
df = pd.DataFrame(laps)
```

## Limitações importantes

- Dados em tempo real exigem assinatura paga.
- `intervals`, `overtakes` e os endpoints de campeonato só existem para corridas.
- Os endpoints de campeonato ainda estão em beta.
- `segments_sector_*` não estão disponíveis durante corridas.
- `country_code` (em drivers) e `pit_duration` serão removidos após a temporada 2026.
- Como `car_data` e `location` têm alta frequência, filtre por `session_key`, `driver_number` e intervalo de `date` para não trazer volumes grandes.

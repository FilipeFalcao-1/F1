# Primeiros passos

## Instalação

Requisitos: Python 3.14 e Poetry 2.x (`pipx install poetry`).

```bash
poetry config virtualenvs.in-project true --local
poetry install
```

## Configuração

Todas as variáveis são opcionais e usam o prefixo `F1_`. Elas podem vir do ambiente ou de um arquivo `.env` (copie de `.env.example`; o `.env` não é versionado).

| Variável | Obrigatória | Default | Descrição |
|---|---|---|---|
| `F1_API_BASE_URL` | não | `https://api.openf1.org/v1` | URL base da API |
| `F1_API_TOKEN` | não | — | Token da OpenF1 (planos pagos). Enviado como `Authorization: Bearer`. Dados históricos não exigem |
| `F1_DATA_DIR` | não | `data` | Raiz do lake (bronze, silver, quarentena e `f1.duckdb`) |
| `F1_RATE_LIMIT_PER_SECOND` | não | `3` | Limite por segundo (plano gratuito: 3 req/s) |
| `F1_RATE_LIMIT_PER_MINUTE` | não | `30` | Limite por minuto (plano gratuito: 30 req/min) |
| `F1_MAX_RETRIES` | não | `5` | Novas tentativas em 429, 5xx, timeout e erro de conexão |
| `F1_HTTP_TIMEOUT_SECONDS` | não | `60` | Timeout por requisição |
| `F1_TELEMETRY_SESSION_TYPES` | não | `Race,Qualifying` | `session_type` com telemetria, separados por vírgula |
| `F1_LOG_LEVEL` | não | `INFO` | `DEBUG`, `INFO`, `WARNING` ou `ERROR` |

Um valor inválido (por exemplo, `F1_MAX_RETRIES=-1`) encerra a CLI com código 2 antes de qualquer chamada.

## Primeira ingestão

```bash
poetry run f1 ingest calendar --year 2023                        # meetings + sessions de 2023
poetry run f1 ingest session --session-key 9165 --with-telemetry # GP de Singapura 2023
poetry run f1 refine --session-key 9165                          # bronze → silver (inclui o calendário de 2023)
poetry run f1 marts build                                        # views silver_* e marts gold_*
```

Consulte o resultado:

```bash
duckdb data/f1.duckdb "SELECT * FROM gold_stint_summary LIMIT 10"
duckdb data/f1.duckdb "SELECT endpoint, status, rows FROM meta.ingestion_runs ORDER BY ingested_at DESC"
```

## Comandos

| Comando | O que faz |
|---|---|
| `f1 ingest calendar --year Y` | Ingere `meetings` e `sessions` do ano |
| `f1 ingest session --session-key N [--endpoints a,b] [--with-telemetry]` | Ingere uma sessão. `--endpoints` restringe a lista (só endpoints de sessão) |
| `f1 ingest year --year Y [--with-telemetry] [--force]` | Calendário e todas as sessões encerradas do ano ainda não completas no manifesto. `--force` reingere tudo |
| `f1 ingest latest [--with-telemetry]` | O mesmo que `ingest year` para o ano corrente |
| `f1 refine (--session-key N \| --year Y)` | Bronze → silver e quarentena |
| `f1 marts build` | Recria as views `silver_*` e os marts `gold_*` |
| `f1 run [--year Y] [--with-telemetry]` | `ingest year` + `refine --year` + `marts build` (padrão: ano corrente) |

Sessões canceladas (`is_cancelled`) ou ainda não encerradas (`date_end` no futuro) são puladas e registradas no log. Qualquer falha encerra com código de saída diferente de zero.

## Marts disponíveis

| Tabela | Grão | Conteúdo |
|---|---|---|
| `gold_lap_pace` | volta × piloto | Tempos, composto, idade do pneu, flags de pit e `is_clean_lap` |
| `gold_stint_summary` | stint × piloto | Voltas, ritmo médio/mediano/melhor e degradação (s/volta) |
| `gold_pit_stops` | parada | `lane_duration` e `stop_duration` por corrida, numeradas por piloto |
| `gold_race_results` | piloto × corrida | Resultado, grid, posições ganhas, pontos e gaps (inclui sprints) |
| `gold_championship_progression` | competidor × corrida | Pontos e posição no campeonato (pilotos e equipes) |
| `gold_session_weather` | sessão | Temperaturas, umidade, vento e se choveu |

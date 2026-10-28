# Plano: pipeline de dados F1 (OpenF1 → Parquet + DuckDB)

## Contexto

Vamos construir um pipeline que ingere os dados históricos da [OpenF1 API](doc_api.md) (2023 em diante, gratuitos e sem autenticação), cobrindo os **18 endpoints**. Os dados ficam num data lake local em Parquet, com as camadas bronze, silver e gold, e são consultados via DuckDB.

O projeto segue integralmente a skill [python-data-engineering](.claude/skills/python-data-engineering/SKILL.md): Poetry com layout `src/`, Ruff, Pytest com cobertura de pelo menos 50%, mypy strict, MkDocs Material e CI.

O repositório já existe como esqueleto Poetry: [pyproject.toml](pyproject.toml) com o pacote `f1` e `requires-python >=3.14`, `src/f1/__init__.py`, `tests/__init__.py` e um commit. O plano o evolui, sem recriá-lo.

**Decisões já tomadas**

| Tema | Escolha |
|---|---|
| Destino | Parquet particionado (bronze/silver) e DuckDB para gold e consultas |
| Escopo do MVP | Os 18 endpoints, incluindo telemetria (`car_data`, `location`) |
| DataFrame | Polars |
| Execução | CLI (`poetry run f1 ...`) e GitHub Actions com cron |

**Fora de escopo**: dados em tempo real (exigem assinatura paga), dashboards e orquestradores (Airflow, Prefect, Dagster).

---

## Arquitetura

```text
OpenF1 API ──► extractors (HTTP + retry + rate limit)
                 │  JSON bruto
                 ▼
data/bronze/{endpoint}/year=YYYY/session_key=N/data.json.gz   (fidelidade total, reprocessável)
                 │  transformers (Polars: cast, normalização, dedupe, validação)
                 ▼
data/silver/{endpoint}/year=YYYY/session_key=N/data.parquet   (tipado, contrato validado)
data/quarantine/{endpoint}/...                                (inválidos com motivo e run_id)
                 │  SQL no DuckDB
                 ▼
data/f1.duckdb  ── views silver_* sobre o Parquet, tabelas gold_* (marts) e meta.ingestion_runs (manifesto)
```

- **O bronze guarda o JSON bruto** comprimido, não Parquet. Isso preserva o payload exato, evita quebrar a inferência de tipos com campos nulos ou mistos, e permite refazer a silver sem chamar a API de novo.
- **A idempotência vem do overwrite atômico por partição** `session_key` (`.tmp` seguido de `replace`). `meetings` e `sessions` são particionados por `year`.
- **O manifesto** (`meta.ingestion_runs` no DuckDB) registra por endpoint e partição: `run_id`, status, linhas e `ingested_at`. Ele alimenta a ingestão incremental e evita chamadas repetidas.

### Estrutura do pacote `src/f1/`

Crie só o que for usado, conforme a skill.

```text
src/f1/
├── main.py                    # CLI argparse (composition root)
├── config/settings.py         # Settings (pydantic-settings, prefixo F1_)
├── config/logging.py          # configure_logging com run_id (padrão de references/code-patterns.md)
├── exceptions/__init__.py     # F1Error, ConfigurationError, ExtractionError, RateLimitError, DataValidationError, LoadError
├── schemas/endpoints.py       # registro EndpointSpec dos 18 endpoints (ver abaixo)
├── schemas/silver.py          # schema Polars de cada endpoint na silver
├── extractors/client.py       # OpenF1Client: httpx, timeout, retry/backoff, Retry-After, rate limit
├── extractors/openf1.py       # extração por escopo (ano / sessão / sessão+piloto)
├── transformers/normalize.py  # funções puras bronze→silver (cast, dedupe, regras específicas)
├── transformers/validate.py   # validação de contrato e separação válidos/inválidos
├── loaders/files.py           # escrita atômica de JSON.gz e Parquet por partição
├── repositories/catalog.py    # DuckDB: views silver_*, manifesto, execução de SQL gold
├── pipelines/ingest.py        # API → bronze
├── pipelines/refine.py        # bronze → silver (+ quarentena)
├── pipelines/marts.py         # silver → gold
└── sql/gold/*.sql             # marts como SQL versionado
```

### Registro de endpoints (`schemas/endpoints.py`)

São 18 endpoints, então usamos um **registro declarativo** em vez de 18 extractors. Cada `EndpointSpec(frozen dataclass)` define `name`, `scope`, `primary_key`, `race_only` e `deprecated_fields`. Um extractor genérico percorre o registro.

| Escopo | Endpoints | Parâmetro da chamada | Chave primária na silver |
|---|---|---|---|
| `year` | `meetings` | `year` | `meeting_key` |
| `year` | `sessions` | `year` | `session_key` |
| `session` | `drivers` | `session_key` | `session_key, driver_number` |
| `session` | `laps` | `session_key` | `session_key, driver_number, lap_number` |
| `session` | `stints` | `session_key` | `session_key, driver_number, stint_number` |
| `session` | `pit` | `session_key` | `session_key, driver_number, lap_number, date` |
| `session` | `session_result`, `starting_grid` | `session_key` | `session_key, driver_number` |
| `session` | `position` | `session_key` | `session_key, driver_number, date` |
| `session` (só corridas) | `intervals` | `session_key` | `session_key, driver_number, date` |
| `session` (só corridas) | `overtakes` | `session_key` | `session_key, date, overtaking_driver_number, overtaken_driver_number` |
| `session` (só corridas, beta) | `championship_drivers` | `session_key` | `session_key, driver_number` |
| `session` (só corridas, beta) | `championship_teams` | `session_key` | `session_key, team_name` |
| `session` | `weather` | `session_key` | `session_key, date` |
| `session` | `race_control` | `session_key` | `session_key, date, category, message` |
| `session` | `team_radio` | `session_key` | `session_key, driver_number, date` |
| `session_driver` | `car_data`, `location` | `session_key` + `driver_number` | `session_key, driver_number, date` |

- Endpoints `race_only` só são chamados quando `session_type == "Race"`. Isso evita chamadas vazias.
- A telemetria é buscada **por piloto** (lista vinda de `drivers`), para limitar o tamanho de cada resposta. Ela fica atrás da flag `--with-telemetry`, e `F1_TELEMETRY_SESSION_TYPES` (padrão `Race,Qualifying`) controla o volume.

### Regras específicas de normalização (transformers)

- `session_result.duration` e `gap_to_leader`: são arrays de 3 valores na classificação. Viram `duration_q1/q2/q3` e `gap_q1/q2/q3`; fora da classificação, ficam só em `duration`.
- `intervals.interval` e `gap_to_leader`: podem ser `"+1 LAP"`. Separamos em `*_seconds: Float64` (nulo quando houver volta de diferença) e `*_laps_behind: Int32`.
- `laps.segments_sector_*`: mantidos como `List(Int32)`. Ficam nulos em corridas, e isso é documentado, não tratado como erro.
- Campos deprecados (`drivers.country_code`, `pit.pit_duration`): descartados na silver e listados no `EndpointSpec`.
- Datas: parse para `Datetime(time_zone="UTC")`.
- Dedupe pela chave primária e validação de nulidade nela. Registros violadores vão para a quarentena com `reject_reason` e `run_id`.
- Colunas novas ou ausentes em relação a `schemas/silver.py` falham o refine do endpoint, com erro explícito (mudança de schema tratada de forma explícita).

### Gold (DuckDB, `sql/gold/`)

O MVP inclui marts pequenos e úteis, um arquivo `.sql` cada:

- `gold_lap_pace`: volta por piloto com composto e idade do pneu (join laps × stints) e flag de out-lap e pit.
- `gold_stint_summary`: ritmo médio, degradação e número de voltas por stint.
- `gold_pit_stops`: paradas com `stop_duration` e `lane_duration` por corrida.
- `gold_race_results`: resultado, grid e posições ganhas por corrida.
- `gold_championship_progression`: pontos e posição por etapa (pilotos e equipes).
- `gold_session_weather`: agregados de clima por sessão.

---

## CLI (`[project.scripts] f1 = "f1.main:main"`)

```bash
poetry run f1 ingest calendar --year 2025                 # meetings + sessions
poetry run f1 ingest session --session-key 9165 [--endpoints laps,stints] [--with-telemetry]
poetry run f1 ingest year --year 2025 [--with-telemetry] [--force]   # backfill das sessões encerradas
poetry run f1 ingest latest [--with-telemetry]            # incremental: sessões encerradas ainda fora do manifesto
poetry run f1 refine (--session-key N | --year YYYY)      # bronze → silver
poetry run f1 marts build                                 # silver → gold
poetry run f1 run --year 2025                             # ingest + refine + marts
```

O código de saída é diferente de zero em qualquer falha. Sessões com `is_cancelled` ou com `date_end` no futuro são puladas e registradas no log.

## Configuração (`.env.example`, prefixo `F1_`)

| Variável | Default | Descrição |
|---|---|---|
| `F1_API_BASE_URL` | `https://api.openf1.org/v1` | URL base |
| `F1_DATA_DIR` | `data` | Raiz do lake (bronze, silver, quarentena e `f1.duckdb`) |
| `F1_RATE_LIMIT_PER_SECOND` | `3` | Limite conservador. A doc resumida não informa o limite; confira na openf1.org ao implementar |
| `F1_MAX_RETRIES` | `5` | Tentativas para 429/5xx/timeout, com backoff exponencial e respeito ao `Retry-After` |
| `F1_HTTP_TIMEOUT_SECONDS` | `60` | Timeout por requisição (a telemetria é grande) |
| `F1_TELEMETRY_SESSION_TYPES` | `Race,Qualifying` | Tipos de sessão com telemetria |
| `F1_LOG_LEVEL` | `INFO` | Nível de log |

Não há segredo no MVP: os dados históricos não exigem token. O campo `F1_API_TOKEN: SecretStr | None` fica previsto para quando usarmos o tempo real.

## Dependências (via `poetry add`)

- **Produção**:
  - `httpx`: cliente HTTP com timeouts e `MockTransport` para testes sem rede.
  - `polars`.
  - `duckdb`.
  - `pydantic-settings`.
- **Dev**: os pacotes do template da skill (`ruff`, `pytest`, `pytest-cov`, `mypy`, `mkdocs-material`, `mkdocstrings[python]`, `pip-audit`).
- A CLI usa `argparse` (stdlib), sem Typer ou Click (YAGNI).
- O projeto declara `requires-python >=3.14`. No Passo 0, confirme que `polars` e `duckdb` têm wheels para 3.14. Se não tiverem, mude para `>=3.13` e registre a decisão em `docs/adr/0001-versao-python.md`.

---

## Execução em etapas (um PR por etapa, Conventional Commits)

**0. Bootstrap** (`chore: bootstrap do projeto`)
- Mesclar [templates/pyproject.toml](.claude/skills/python-data-engineering/templates/pyproject.toml) no [pyproject.toml](pyproject.toml) existente: trocar `nome_projeto` por `f1`, `target-version` e `python_version` por `py314`/`3.14`, e adicionar o marker `live` e `addopts -m "not live"`.
- `poetry config virtualenvs.in-project true --local`, `poetry add ...` e `poetry add --group dev ...`.
- Copiar os templates `gitignore`, `env.example`, `ci.yml` (com `PYTHON_VERSION` = 3.14 e `POETRY_VERSION` = 2.5.1), `pull_request_template.md` e `mkdocs.yml`.
- Criar o README e o esqueleto de `docs/`.
- Remover `tests/__init__.py` se conflitar com `--import-mode=importlib`.

**1. Fundação** (`feat: config, logging, exceções e cliente HTTP`)
- `config/`, `exceptions/` e `extractors/client.py`, com rate limit (token bucket simples), retry em 429/5xx/timeout, `Retry-After` e `ExtractionError` em 4xx.
- Testes com `httpx.MockTransport` e `time.sleep` mockado.

**2. Calendário → bronze** (`feat(extractors): ingestão de meetings e sessions`)
- Criar o `EndpointSpec`, o `loaders/files.py` (JSON.gz atômico), o manifesto em `repositories/catalog.py` e o `pipelines/ingest.py` para o escopo `year`.
- CLI `ingest calendar`.

**3. Endpoints de sessão → bronze** (`feat(extractors): endpoints por sessão`)
- Os 14 endpoints `session`, com o filtro `race_only`.
- CLI `ingest session`, `ingest year` e `ingest latest`, com `--force`.
- Pulo de sessões já ingeridas, canceladas ou futuras.

**4. Telemetria** (`feat(extractors): car_data e location por piloto`)
- Escopo `session_driver`, `--with-telemetry` e `F1_TELEMETRY_SESSION_TYPES`.
- Medir volume e duração de uma corrida e registrar o resultado em `docs/architecture.md`.

**5. Silver** (`feat(transformers): bronze → silver com validação`)
- `schemas/silver.py`, `transformers/normalize.py` (regras acima), `transformers/validate.py`, Parquet por partição, quarentena e `pipelines/refine.py`.
- CLI `refine`.
- Cobertura de 80% ou mais em `transformers/`.

**6. Gold** (`feat(marts): views silver e marts gold no DuckDB`)
- Views `silver_*` com `read_parquet('data/silver/<endpoint>/**/*.parquet', hive_partitioning=true)`.
- Os SQLs de `sql/gold/` e `pipelines/marts.py`.
- CLI `marts build` e `run`.

**7. Agendamento** (`ci: ingestão agendada`)
- `.github/workflows/ingest.yml` com `schedule` (diário, depois de 00:00 UTC, quando a OpenF1 atualiza meetings e sessions) e `workflow_dispatch`.
- Ele roda `f1 run` para o ano corrente em modo `latest`.
- **Limitação**: o runner não tem disco persistente. No MVP, o lake gerado sobe como artifact (`actions/upload-artifact`, com retenção limitada). Persistir em object storage (S3/GCS) fica como próxima etapa e exige outro ADR.

**8. Documentação** (`docs: arquitetura, endpoints e operação`)
- `getting-started.md`: instalação, variáveis e primeira ingestão.
- `architecture.md`: camadas, particionamento, manifesto e o volume medido.
- `endpoints.md`: tabela do registro e particularidades vindas do [doc_api.md](doc_api.md).
- `development.md`.
- Troubleshooting: 429, sessões vazias e endpoints beta.
- Referência via mkdocstrings e ADRs.

## Testes

- **Unitários** (`tests/unit/`): transformers com DataFrames pequenos montados no teste (arrays da classificação, `+1 LAP`, duplicados, nulos na chave, coluna inesperada), cliente HTTP com `MockTransport`, registro de endpoints e lógica de seleção de sessões (`race_only`, canceladas, futuras).
- **Integração** (`tests/integration/`, `@pytest.mark.integration`): ponta a ponta de uma sessão com fixtures JSON em `tests/fixtures/openf1/` (amostras reais pequenas e versionadas), passando por `MockTransport`, bronze e silver em `tmp_path` e gold no DuckDB em memória. Não usa rede e roda no CI.
- **Live** (`@pytest.mark.live`, excluído por padrão): um smoke test contra a API real numa sessão pequena, rodado manualmente com `poetry run pytest -m live`.

## Riscos

| Risco | Mitigação |
|---|---|
| Rate limit não documentado e respostas 429 | Rate limit configurável, `Retry-After`, backoff e manifesto que evita repetir chamadas |
| Volume da telemetria | Busca por piloto, flag opcional, filtro por tipo de sessão e medição na etapa 4 |
| Endpoints beta ou incompletos (`championship_*`, `overtakes`) | Contrato próprio. Uma falha de schema isola só aquele endpoint e não derruba os demais |
| Campos deprecados removidos depois de 2026 | Descartados na silver desde já |
| `team_radio` escasso a partir de 2026 | Resultado vazio é válido: loga `rows=0` e não trata como erro |
| Wheels de polars ou duckdb para 3.14 | Verificação no passo 0, com fallback para 3.13 e ADR |

## Verificação

Em cada PR, a Definition of Done da skill:

```bash
poetry check --lock
poetry run ruff check . && poetry run ruff format --check .
poetry run mypy
poetry run pytest tests/ --cov=f1 --cov-report=term-missing --cov-fail-under=50
poetry run mkdocs build --strict
```

Ponta a ponta, com a API real, ao final das etapas 3, 5 e 6:

```bash
poetry run f1 ingest calendar --year 2023
poetry run f1 ingest session --session-key 9165 --with-telemetry   # sessão usada nos exemplos da doc
poetry run f1 ingest session --session-key 9165                    # reexecução: mesmo resultado, sem duplicar
poetry run f1 refine --session-key 9165
poetry run f1 marts build
duckdb data/f1.duckdb "SELECT * FROM gold_stint_summary LIMIT 10"
duckdb data/f1.duckdb "SELECT endpoint, status, rows FROM meta.ingestion_runs ORDER BY ingested_at DESC"
```

Critérios de aceite:
- Os 18 endpoints aparecem no manifesto da sessão 9165 (os `race_only` só se for corrida).
- A reexecução não muda as contagens.
- A quarentena fica vazia ou tem motivos explicáveis.
- `gold_*` consultáveis.

# Arquitetura

```text
OpenF1 API ──► extractors (HTTP + retry + rate limit)
                 │  JSON bruto
                 ▼
data/bronze/{endpoint}/year=YYYY/session_key=N[/driver_number=D]/data.json.gz
                 │  transformers (Polars: parse, normalização, dedupe, validação)
                 ▼
data/silver/{endpoint}/…/data.parquet        (tipado, contrato validado)
data/quarantine/{endpoint}/…/data.parquet    (inválidos com reject_reason e run_id)
                 │  SQL no DuckDB
                 ▼
data/f1.duckdb ── views silver_*, tabelas gold_* e meta.ingestion_runs
```

## Pacote

| Módulo | Responsabilidade |
|---|---|
| `main.py` | CLI (argparse) e composition root: lê settings, configura logging, monta as dependências e traduz exceções em códigos de saída |
| `config/` | `Settings` (pydantic-settings, prefixo `F1_`) e `configure_logging` com `run_id` |
| `domain/sessions.py` | `SessionInfo` e regras puras: sessão cancelada, não encerrada, corrida, com telemetria |
| `schemas/endpoints.py` | Registro `EndpointSpec` dos 18 endpoints e a `Partition` do lake |
| `schemas/silver.py` | Contrato de cada endpoint: schema bruto da API, schema da silver e colunas opcionais |
| `extractors/client.py` | `OpenF1Client` (httpx) com rate limit, retry, backoff e `Retry-After` |
| `extractors/openf1.py` | Extração genérica por escopo, guiada pelo registro |
| `transformers/` | Funções puras: `normalize` (parse, regras por endpoint, cast) e `validate` (schema, chave primária) |
| `loaders/files.py` | `Lake`: layout em disco e escrita atômica por partição |
| `repositories/catalog.py` | `Catalog`: manifesto, views `silver_*` e materialização dos marts |
| `pipelines/` | `IngestPipeline`, `RefinePipeline` e `MartsPipeline` |
| `sql/gold/*.sql` | Marts versionados como SQL |
| `repositories/marts.py` | `MartsReader`: consultas parametrizadas aos marts para o dashboard |
| `dashboard/` | App Streamlit (`app.py`) e gráficos Altair puros (`charts.py`); extra opcional `dashboard` |

## Bronze

- Guarda o JSON devolvido pela API, comprimido com gzip. Preserva o payload, evita quebrar a inferência de tipos com campos nulos ou polimórficos e permite refazer a silver sem chamar a API.
- A API responde `404 {"detail": "No results found."}` quando não há dados. O cliente trata isso como lista vazia, e a partição é gravada com `[]` (resultado vazio é válido).
- Partições: `year=Y` para `meetings` e `sessions`; `year=Y/session_key=N` para endpoints de sessão; `year=Y/session_key=N/driver_number=D` para telemetria.

## Silver

O refino de cada partição segue estas etapas:

1. **Contrato da API** (`check_columns`): coluna nova ou coluna obrigatória ausente falha o endpoint com erro explícito. Campos deprecados e opcionais (`session_result.points`, ausente na classificação) podem faltar.
2. **Leitura tipada** (`records_to_frame`): o JSON vira NDJSON e é lido com o schema bruto. Campos polimórficos chegam como texto JSON.
3. **Normalização** (`normalize`): datas → `Datetime(UTC)`, regras por endpoint e cast estrito para o schema da silver, que também descarta campos deprecados.
4. **Chave primária** (`split_valid`): linhas idênticas são deduplicadas; chave nula ou mesma chave com conteúdo divergente vão para a quarentena.
5. **Escrita atômica** da silver e da quarentena. Sem rejeitados, a quarentena anterior da partição é removida.

Uma falha afeta só a partição do endpoint: as demais seguem, e a execução termina com código 1.

### Regras por endpoint

| Endpoint | Regra |
|---|---|
| `session_result` | Na classificação, `duration` e `gap_to_leader` são arrays `[Q1, Q2, Q3]` → `duration_q1..q3` e `gap_q1..q3`. Fora dela, `duration` fica escalar e o gap vira `gap_to_leader_seconds` e `gap_to_leader_laps_behind` |
| `intervals` | `interval` e `gap_to_leader` podem ser `"+1 LAP"` → `*_seconds` (nulo quando há volta de diferença) e `*_laps_behind` |
| `laps` | `segments_sector_*` como `List(Int32)`. São nulos em corridas, o que é esperado |
| `drivers`, `pit` | `country_code` e `pit_duration` (deprecados) são descartados |

## Gold

`f1 marts build` recria as views `silver_*` com `read_parquet(…, hive_partitioning = true)`. As colunas de partição (`year`, `session_key`, `driver_number`) vêm do caminho. Endpoint sem nenhuma partição vira uma tabela vazia com o schema da silver, para que os marts continuem consultáveis. Os marts são materializados com `CREATE OR REPLACE TABLE`, na ordem de `GOLD_MARTS` (`gold_stint_summary` depende de `gold_lap_pace`).

!!! warning "Caminhos absolutos"
    As views guardam o caminho absoluto do lake. Se mover o diretório `data/` (ou baixar o artifact do CI), rode `f1 marts build` de novo.

O `starting_grid` é publicado pela OpenF1 na sessão de **classificação**, não na corrida. Por isso, `gold_race_results` busca o grid na `Qualifying` do mesmo meeting (para a corrida) ou na `Sprint Qualifying`/`Sprint Shootout` (para a sprint).

## Idempotência e manifesto

- Cada partição é um arquivo único sobrescrito via `.tmp` + `replace`. Reexecutar a mesma partição produz o mesmo estado.
- `meta.ingestion_runs` recebe uma linha por partição e camada: `run_id`, `layer` (`bronze`/`silver`), `endpoint`, `partition`, `year`, `session_key`, `status`, `rows`, `rejected`, `error`, `ingested_at`.
- A ingestão incremental (`ingest year`/`latest`/`run`) pula a sessão quando **todos** os endpoints planejados para ela têm, na última execução de cada partição, status `success` no bronze. Uma partição que falhou faz a sessão ser tentada de novo na próxima execução. Ativar `--with-telemetry` depois faz as sessões sem telemetria serem completadas.

## Volume medido (telemetria)

Medido no GP de Singapura 2023 (`session_key=9165`, corrida, 19 pilotos), com os limites do plano gratuito:

| Endpoint | Linhas | Bronze (gzip) | Silver (Parquet) | Chamadas |
|---|---|---|---|---|
| `car_data` | 742.995 | 5,9 MB | 4,1 MB | 19 |
| `location` | 758.689 | 6,2 MB | 4,7 MB | 19 |
| demais 14 endpoints | ~26.800 | ~0,4 MB | ~0,3 MB | 15 |

- Ingestão completa da sessão com telemetria: **~150 s**, dominados pelo limite de 30 req/min. Sem telemetria: ~7 s.
- Refino da sessão (1,5 milhão de linhas): ~6 s.
- Estimativa para uma temporada de 24 corridas com telemetria só em `Race`: ~300 MB no bronze e ~1 h de ingestão.

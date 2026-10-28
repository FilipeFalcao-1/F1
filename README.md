# f1

Pipeline que ingere os dados históricos da [OpenF1 API](https://openf1.org) (2023 em diante, gratuitos e sem autenticação) nos 18 endpoints e os organiza num data lake local:

- **bronze**: JSON bruto comprimido, por partição (`data/bronze/`);
- **silver**: Parquet tipado e validado, com quarentena para registros inválidos (`data/silver/`, `data/quarantine/`);
- **gold**: marts em DuckDB (`data/f1.duckdb`), mais o manifesto de execuções `meta.ingestion_runs`.

## Instalação

Requer Python 3.14 e Poetry 2.x.

```bash
poetry config virtualenvs.in-project true --local
poetry install
cp .env.example .env   # opcional: todas as variáveis têm default
```

## Uso

```bash
poetry run f1 ingest calendar --year 2023                        # meetings + sessions
poetry run f1 ingest session --session-key 9165 --with-telemetry # uma sessão
poetry run f1 refine --session-key 9165                          # bronze → silver
poetry run f1 marts build                                        # silver → gold
poetry run f1 run --year 2025                                    # ingest + refine + marts, incremental
```

Para explorar no dashboard (Streamlit):

```bash
poetry install --extras dashboard
poetry run f1 dashboard        # http://localhost:8501
```

Ou consulte com DuckDB:

```sql
SELECT * FROM gold_race_results ORDER BY date_start, position;
```

## Documentação

```bash
poetry run task docs   # http://127.0.0.1:8000
```

Comece por [docs/getting-started.md](docs/getting-started.md). A arquitetura está em [docs/architecture.md](docs/architecture.md) e o desenvolvimento em [docs/development.md](docs/development.md).

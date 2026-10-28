# f1

Pipeline de dados da [OpenF1 API](https://openf1.org): ingere os 18 endpoints históricos (2023 em diante) num data lake local com as camadas bronze, silver e gold, consultadas via DuckDB.

| Camada | Formato | Onde | Para quê |
|---|---|---|---|
| bronze | JSON comprimido | `data/bronze/{endpoint}/year=Y/session_key=N/data.json.gz` | Payload bruto, reprocessável sem chamar a API |
| silver | Parquet | `data/silver/{endpoint}/…/data.parquet` | Dados tipados, deduplicados e validados |
| quarentena | Parquet | `data/quarantine/{endpoint}/…/data.parquet` | Registros inválidos com `reject_reason` e `run_id` |
| gold | DuckDB | `data/f1.duckdb` | Views `silver_*`, marts `gold_*` e o manifesto `meta.ingestion_runs` |

- [Primeiros passos](getting-started.md): instalação, variáveis e primeira ingestão.
- [Arquitetura](architecture.md): camadas, particionamento, manifesto e volumes medidos.
- [Endpoints](endpoints.md): o registro dos 18 endpoints e as particularidades de cada um.
- [Dashboard](dashboard.md): páginas do Streamlit sobre os marts.
- [Operação e troubleshooting](troubleshooting.md): agendamento, 429, sessões vazias e endpoints beta.
- [Desenvolvimento](development.md): testes, qualidade e como estender.

!!! note "Fora de escopo"
    Dados em tempo real (exigem assinatura paga) e orquestradores.

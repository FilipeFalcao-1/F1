# Operação e troubleshooting

## Agendamento (GitHub Actions)

`.github/workflows/ingest.yml` roda `f1 run` todo dia às 03:00 UTC, depois da atualização diária de `meetings` e `sessions` na OpenF1 (00:00 UTC). Também pode ser disparado manualmente (`workflow_dispatch`) com `year` e `with_telemetry`.

- O lake é restaurado e salvo com `actions/cache`, e cada execução também o publica como artifact por 7 dias. Veja as limitações em [ADR 0001](adr/0001-lake-no-github-actions.md).
- Sem cache (primeira execução, ou depois de 7 dias sem uso), a temporada inteira é reingerida: ~1.800 chamadas, cerca de 1 h com o limite de 30 req/min.

## Reprocessar

| Situação | Comando |
|---|---|
| Refazer a silver de uma sessão sem chamar a API | `f1 refine --session-key N` |
| Reingerir uma sessão | `f1 ingest session --session-key N` |
| Reingerir um ano inteiro | `f1 ingest year --year Y --force` |
| Recriar views e marts | `f1 marts build` |

Todas as operações sobrescrevem a partição, então reexecutar é seguro.

## Consultas úteis

```sql
-- Partições que falharam na última execução de cada uma
SELECT endpoint, partition, error
FROM meta.ingestion_runs
QUALIFY row_number() OVER (PARTITION BY layer, endpoint, partition ORDER BY ingested_at DESC) = 1
    AND status = 'failed';

-- Volume rejeitado por endpoint
SELECT endpoint, sum(rejected) AS rejected
FROM meta.ingestion_runs
WHERE layer = 'silver'
GROUP BY endpoint
HAVING sum(rejected) > 0;
```

Os registros rejeitados ficam em `data/quarantine/{endpoint}/…/data.parquet`, com `reject_reason` e `run_id`.

## Problemas comuns

### `RateLimitError: HTTP 429 após N tentativas`

A API continuou respondendo 429 depois de todas as tentativas, e a execução foi interrompida para não insistir. As partições já gravadas ficam no manifesto, e a próxima execução retoma de onde parou. Se acontecer com frequência, reduza `F1_RATE_LIMIT_PER_MINUTE` ou aumente `F1_MAX_RETRIES`. O cliente já respeita o `Retry-After` (limitado a 60 s).

### Partições com `rows = 0`

É esperado. A OpenF1 responde 404 `No results found.` em vários casos válidos:

- `starting_grid` na corrida (o grid é publicado na classificação);
- `team_radio` em 2026, que tem pouca ou nenhuma cobertura;
- `pit` em sessões sem paradas;
- endpoints beta (`championship_*`) e `overtakes` em sessões ainda não processadas pela OpenF1.

### `DataValidationError: Mudança de schema: colunas novas=[…]`

A OpenF1 passou a enviar (ou deixou de enviar) uma coluna. O refine falha só naquele endpoint, de propósito. Para resolver, atualize o contrato em `src/f1/schemas/silver.py` (e o `optional`, se a coluna puder faltar), ajuste os testes e rode `f1 refine` de novo. O bronze já tem os dados, então não é preciso chamar a API.

### `Falha ao normalizar …`

Algum valor não coube no tipo da silver, por exemplo um gap em formato desconhecido. Inspecione o bronze da partição:

```bash
gzip -dc data/bronze/intervals/year=2025/session_key=N/data.json.gz | head -c 2000
```

### Views `silver_*` quebradas depois de mover `data/`

As views guardam o caminho absoluto do lake. Rode `f1 marts build`.

### Endpoints beta

`championship_drivers` e `championship_teams` estão em beta, e `overtakes` pode estar incompleto. Cada um tem contrato próprio, então uma falha isola só aquele endpoint.

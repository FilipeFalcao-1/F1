# 0001: Persistência do lake na ingestão agendada

- **Status**: aceita
- **Data**: 2026-10-28

## Contexto

A ingestão agendada roda no GitHub Actions, cujo runner não tem disco persistente. Sem o lake da execução anterior, o manifesto `meta.ingestion_runs` começa vazio e a execução incremental reingere a temporada inteira todo dia: cerca de 1.800 chamadas, ~1 h com o limite de 30 req/min da OpenF1.

Persistir em object storage (S3/GCS) resolve isso de forma definitiva, mas exige credenciais, infraestrutura e outra decisão. O plano do MVP previa só publicar o lake como artifact.

## Decisão

- Restaurar e salvar `data/` com `actions/cache` (chave por `run_id`, restaurando a mais recente pelo prefixo `f1-lake-`). Com isso, o manifesto sobrevive entre execuções e a ingestão diária fica incremental.
- Publicar o lake como artifact (`actions/upload-artifact`, 7 dias de retenção) para quem quiser baixar os dados.
- Python 3.14 foi mantido: `polars` e `duckdb` têm wheels para 3.14, então o fallback para 3.13 previsto no plano não foi necessário.

## Consequências

- O cache é de melhor esforço: o GitHub o descarta após 7 dias sem uso ou quando o repositório passa de 10 GB de cache. Nesse caso, a execução seguinte reingere o ano (mais lenta, mas correta, porque a escrita é idempotente).
- A telemetria (~12 MB no bronze e ~9 MB na silver por corrida) fica desligada no agendamento padrão para manter o cache pequeno. Ela pode ser ligada no `workflow_dispatch`.
- As views `silver_*` guardam caminhos absolutos do runner. Quem baixar o artifact precisa rodar `f1 marts build`. As tabelas `gold_*` são materializadas e funcionam sem isso.
- Próxima etapa: object storage com outro ADR.

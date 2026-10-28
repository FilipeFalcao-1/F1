# Padrões de Engenharia de Dados

Os exemplos usam bibliotecas comuns (`requests`, Pandas, Polars, SQLAlchemy) só para ilustrar. Use as que o projeto já tem.

## Idempotência

Reexecutar a mesma partição MUST produzir o mesmo estado final, sem duplicar dados.

| Estratégia | Quando usar | Exemplo |
|---|---|---|
| Overwrite de partição | Arquivos ou tabelas particionados por data | Gravar em `output/dt=2026-01-31/` substituindo o conteúdo |
| Delete + insert na mesma transação | Tabelas SQL sem MERGE | `DELETE WHERE dt = :dt` e `INSERT`, dentro de `engine.begin()` |
| Upsert/MERGE por chave natural | Dados com chave única | `INSERT ... ON CONFLICT (id) DO UPDATE` (Postgres) |
| Staging + swap | Cargas completas grandes | Carregar em `tabela_stg`, validar e trocar |

```python
# ✅ Overwrite atômico de partição em arquivo
def write_partition(df: pd.DataFrame, root: Path, partition: date) -> Path:
    target = root / f"dt={partition.isoformat()}" / "data.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(target)  # rename atômico no mesmo filesystem
    return target


# ❌ Append cego: duplica dados a cada reexecução
df.to_sql("orders", engine, if_exists="append")
```

## Retries

Use retries **só para erros transitórios** (timeout, conexão, HTTP 429/5xx), sempre com limite e backoff. Erros 4xx de contrato (400, 401, 404) MUST falhar imediatamente.

```python
import logging
import time

import requests

from nome_projeto.exceptions import ExtractionError

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def get_json(
    session: requests.Session, url: str, params: dict[str, str], max_attempts: int = 4
) -> object:
    """GET com retry e backoff exponencial para falhas transitórias."""
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.get(url, params=params, timeout=30)
            if response.status_code not in RETRYABLE_STATUS:
                response.raise_for_status()
                return response.json()
            reason = f"HTTP {response.status_code}"
        except (requests.ConnectionError, requests.Timeout) as exc:
            reason = type(exc).__name__
            if attempt == max_attempts:
                raise ExtractionError(f"Falha após {attempt} tentativas em {url}") from exc
        except requests.HTTPError as exc:
            raise ExtractionError(f"Erro não recuperável em {url}: {exc}") from exc
        if attempt == max_attempts:
            raise ExtractionError(f"Falha após {attempt} tentativas em {url}: {reason}")
        delay = 2 ** (attempt - 1)
        logger.warning(
            "Retry attempt=%d/%d url=%s reason=%s delay_s=%d",
            attempt,
            max_attempts,
            url,
            reason,
            delay,
        )
        time.sleep(delay)
    raise AssertionError("inalcançável")
```

Se o projeto já usa `tenacity` ou se o SDK tem retry nativo (boto3, google-cloud), prefira esse mecanismo a reimplementar o loop.

## Processamento incremental

- Por partição: o orquestrador passa o intervalo (`--start-date`, `--end-date`), e o pipeline processa só esse intervalo.
- Por watermark: guarde o último valor processado (`updated_at` ou id) em `repositories/`, leia com `WHERE updated_at > :watermark` e só atualize o watermark **depois** de uma carga bem-sucedida.
- Backfill é a mesma função chamada em loop sobre as partições, nunca um script separado.

## Efeitos colaterais na importação

```python
# ❌ Executa ao importar (quebra testes, ferramentas e o orquestrador)
df = pd.read_csv("dados.csv")
run_pipeline()


# ✅ Só define; a execução é explícita
def run(partition: date) -> RunResult: ...


if __name__ == "__main__":
    sys.exit(main())
```

## Qualidade e contratos de dados

Valide **na entrada** (o que veio da fonte) e **antes da carga** (o que vai para o destino).

```python
from nome_projeto.exceptions import DataValidationError

REQUIRED_COLUMNS = {"order_id": "string", "order_date": "datetime64[ns]", "amount": "float64"}
PRIMARY_KEY = ["order_id"]


def validate_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Valida o schema e as regras. Falha em violação estrutural; devolve só as linhas válidas."""
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise DataValidationError(f"Colunas ausentes: {sorted(missing)}")

    unexpected = set(df.columns) - set(REQUIRED_COLUMNS)
    if unexpected:
        # Mudança de schema: decisão explícita (aqui, falhar). Nunca ignorar em silêncio.
        raise DataValidationError(f"Colunas inesperadas: {sorted(unexpected)}")

    if df.duplicated(subset=PRIMARY_KEY).any():
        raise DataValidationError("Chave primária duplicada em order_id")

    return df.astype(REQUIRED_COLUMNS)
```

**Registros inválidos**: separe-os e persista-os com o motivo, sem descartá-los.

```python
def split_valid(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa linhas válidas e inválidas segundo as regras de negócio."""
    invalid_mask = df["amount"].isna() | (df["amount"] < 0)
    rejected = df[invalid_mask].assign(reject_reason="amount nulo ou negativo")
    return df[~invalid_mask], rejected


valid, rejected = split_valid(df)
quarantine_loader.load(rejected.assign(run_id=run_id), partition)  # rastreável e reprocessável
```

Para projetos maiores, uma biblioteca de validação de DataFrames (por exemplo, `pandera`) ou um modelo Pydantic por registro MAY formalizar o contrato em `schemas/`. Adicione só se o volume de regras justificar.

## Performance

```python
# ❌ Linha a linha
df["net"] = df.apply(lambda r: r["gross"] - r["discount"], axis=1)
for _, row in df.iterrows():
    ...

# ✅ Vetorizado (Pandas)
df["net"] = df["gross"] - df["discount"]

# ✅ Polars: lazy, lê só o necessário
result = (
    pl.scan_parquet(path)
    .filter(pl.col("dt") == partition)
    .select("order_id", "gross", "discount")
    .with_columns(net=pl.col("gross") - pl.col("discount"))
    .collect()
)

# ✅ Ler só colunas e partições necessárias
df = pd.read_parquet(path, columns=["order_id", "amount"], filters=[("dt", "=", partition)])

# ✅ Volumes grandes: em lotes
for chunk in pd.read_csv(path, chunksize=100_000):
    loader.load(transform(chunk))
```

- No PySpark, evite `collect()` e `toPandas()` em dados grandes. Prefira funções nativas a UDFs Python.
- No SQL, empurre filtros e agregações para o banco (pushdown) em vez de trazer tudo para o Python.
- Meça antes de otimizar: `time.perf_counter()` por etapa nos logs. Paralelismo só com uma medição que mostre o gargalo.

## Observabilidade

Cada execução MUST logar, no mínimo:

| Evento | Campos |
|---|---|
| Início | `run_id`, `pipeline`, parâmetros (partição, intervalo) |
| Fim de cada etapa | `step`, `duration_s`, `rows` |
| Fim da execução | `status` (`success`/`failed`), `duration_s`, `read`, `valid`, `rejected`, `written` |
| Falha | `logger.exception` com contexto, e código de saída diferente de zero |

- **Métricas técnicas**: duração, retries, bytes lidos e gravados.
- **Métricas de qualidade**: taxa de nulos, rejeitados, duplicados e a variação de volume em relação à execução anterior.
- **Reprocessamento**: deve ser possível reexecutar uma partição específica pelo mesmo entry point (`--partition`). A idempotência garante a segurança.

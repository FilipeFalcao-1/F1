# Padrões de código

## Tipagem

```python
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Protocol, TypedDict


# ✅ Assinatura completa, tipos modernos, Path
def read_lines(path: Path, encoding: str = "utf-8") -> Iterator[str]:
    with path.open(encoding=encoding) as file:
        yield from file


# ✅ TypedDict para dicts com formato fixo (ex.: payload JSON)
class LapPayload(TypedDict):
    driver_number: int
    lap_number: int
    lap_duration: float | None


# ✅ Protocol para contrato de comportamento (tipagem estrutural, sem herança)
class Loader(Protocol):
    def load(self, rows: Iterable[Mapping[str, object]]) -> int: ...


# ❌ Evite
def process(data, cfg=None):  # sem tipos
    ...


def parse(payload: dict) -> Any:  # Any e dict genérico escondem o contrato
    ...
```

Quando usar cada estrutura:

| Necessidade | Use |
|---|---|
| Valor interno imutável | `@dataclass(frozen=True, slots=True)` |
| Dict com chaves conhecidas (JSON) | `TypedDict` |
| Validar ou converter dado externo (API, arquivo, env) | Pydantic `BaseModel` / `BaseSettings` |
| Contrato de comportamento entre camadas | `Protocol` |
| Conjunto fechado de valores | `enum.StrEnum` ou `Literal[...]` |

## Configuração

```python
"""Configuração da aplicação."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings lidos de variáveis de ambiente com prefixo ``APP_``."""

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    environment: Literal["dev", "hml", "prd"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_base_url: str
    api_token: SecretStr
    output_dir: Path = Path("data/output")
    batch_size: int = Field(default=1_000, gt=0)


@lru_cache
def get_settings() -> Settings:
    """Carrega e valida os settings uma única vez. Falha rápido se faltar variável obrigatória."""
    return Settings()  # campos obrigatórios vêm do ambiente (o plugin pydantic.mypy entende isso)
```

- `SecretStr` evita que o token apareça em `repr` e em logs. Para usá-lo, chame `settings.api_token.get_secret_value()`, e só no ponto de uso.
- Em testes, instancie `Settings(api_base_url="http://test", api_token="x")` diretamente ou use `monkeypatch.setenv`.

```python
# ❌ Errado
API_TOKEN = "eyJhbGciOi..."  # credencial no código
url = os.getenv("API_URL", "http://prod-api")  # default de produção escondido
query = f"SELECT * FROM orders WHERE id = '{order_id}'"  # SQL injection

# ✅ Certo (SQLAlchemy)
from sqlalchemy import text

rows = conn.execute(text("SELECT * FROM orders WHERE id = :id"), {"id": order_id})
```

## Logging

Configure o logging **uma vez**, em `main.py`. Os módulos só obtêm o logger.

```python
# em qualquer módulo
import logging

logger = logging.getLogger(__name__)
```

Para que todo log de uma execução tenha o `run_id`:

```python
"""Configuração de logging."""

import logging
import uuid


class RunContextFilter(logging.Filter):
    """Injeta ``run_id`` e ``pipeline`` em todos os registros."""

    def __init__(self, run_id: str, pipeline: str) -> None:
        super().__init__()
        self.run_id = run_id
        self.pipeline = pipeline

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id  # type: ignore[attr-defined]
        record.pipeline = self.pipeline  # type: ignore[attr-defined]
        return True


def configure_logging(level: str, pipeline: str, run_id: str | None = None) -> str:
    """Configura o logging raiz e devolve o ``run_id`` usado."""
    run_id = run_id or uuid.uuid4().hex[:12]
    handler = logging.StreamHandler()
    handler.addFilter(RunContextFilter(run_id, pipeline))
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(pipeline)s run_id=%(run_id)s] %(name)s: %(message)s"
        )
    )
    logging.basicConfig(level=level, handlers=[handler], force=True)
    return run_id
```

Se o time precisar de logs JSON para um agregador (Datadog, CloudWatch, ELK), troque o `Formatter` por um formatter JSON. Adicionar uma biblioteca de log estruturado (por exemplo, `structlog`) MUST ser justificado no PR.

```python
# ❌ Errado
print(f"Processando {len(rows)} linhas")  # print em produção
logger.info(f"Token usado: {settings.api_token}")  # f-string e dado sensível
logger.error("Erro")  # sem contexto, sem stack trace

# ✅ Certo
logger.info("Processando rows=%d partition=%s", len(rows), partition)
logger.exception("Falha ao carregar partition=%s table=%s", partition, table)  # inclui o traceback
```

## Exceções

```python
# ❌ Falha silenciosa
try:
    data = response.json()
except Exception:
    pass

# ❌ Perde a causa original
except requests.HTTPError:
    raise ExtractionError("falhou")

# ✅ Específica, com contexto e cadeia preservada
try:
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
except requests.Timeout as exc:
    raise ExtractionError(f"Timeout ao chamar {url}") from exc
except requests.HTTPError as exc:
    raise ExtractionError(f"HTTP {exc.response.status_code} em {url}") from exc
```

Regras:

- Capture o que você sabe tratar. O resto sobe até `main.py`, que loga com `logger.exception` e retorna um código diferente de zero.
- `raise ... from exc` sempre que traduzir uma exceção.
- Use `else` e `finally` quando ajudarem a clareza. Prefira context managers a `finally` manual.

## Context managers

```python
# ✅ Recursos liberados mesmo em erro
with path.open("w", encoding="utf-8") as file:
    file.write(content)

with engine.begin() as conn:  # commit ao sair; rollback em exceção
    conn.execute(text("DELETE FROM t WHERE dt = :dt"), {"dt": partition})
    conn.execute(insert_stmt, rows)

with requests.Session() as session:
    ...
```

Para recursos próprios, use `contextlib.contextmanager` ou implemente `__enter__` e `__exit__`.

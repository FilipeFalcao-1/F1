# Padrões de testes

## Organização

```text
tests/
├── conftest.py            # fixtures compartilhadas
├── unit/                  # rápidos, sem rede, banco ou serviços externos
│   ├── transformers/test_orders.py
│   └── pipelines/test_orders_pipeline.py
└── integration/           # @pytest.mark.integration; podem usar banco local ou container
    └── loaders/test_postgres_loader.py
```

- Nomes de arquivo `test_<modulo>.py`, e funções `test_<comportamento>_<condição>`.
- O espelhamento de `src/` em `tests/unit/` é recomendado.

## Exemplos

### Função pura, com parametrização e casos de borda

```python
from datetime import date
from decimal import Decimal

import pytest

from nome_projeto.exceptions import DataValidationError
from nome_projeto.schemas.order import RawOrder
from nome_projeto.transformers.orders import deduplicate, to_order


def make_raw(order_id: str = "A1", gross: str = "100", discount: str = "10") -> RawOrder:
    return RawOrder(order_id, date(2026, 1, 31), Decimal(gross), Decimal(discount))


@pytest.mark.parametrize(
    ("gross", "discount", "expected"),
    [("100", "10", "90"), ("100", "0", "100"), ("100", "100", "0")],
)
def test_to_order_calcula_valor_liquido(gross: str, discount: str, expected: str) -> None:
    assert to_order(make_raw(gross=gross, discount=discount)).net_amount == Decimal(expected)


def test_to_order_rejeita_desconto_maior_que_bruto() -> None:
    with pytest.raises(DataValidationError, match="A1"):
        to_order(make_raw(gross="10", discount="11"))


def test_deduplicate_mantem_ultima_ocorrencia() -> None:
    first, last = to_order(make_raw(gross="100")), to_order(make_raw(gross="200"))
    assert deduplicate([first, last]) == [last]


def test_deduplicate_lista_vazia() -> None:
    assert deduplicate([]) == []
```

### Pipeline com fakes, sem I/O real

Prefira **fakes simples** que implementam o `Protocol` a mocks complexos. Eles verificam o comportamento, não as chamadas internas.

```python
from collections.abc import Iterable
from datetime import date

from nome_projeto.pipelines.orders import OrdersPipeline
from nome_projeto.schemas.order import Order, RawOrder

# make_raw: mesma factory do exemplo anterior (mova para conftest.py ou tests/factories.py se compartilhada)


class FakeExtractor:
    def __init__(self, rows: list[RawOrder]) -> None:
        self.rows = rows

    def extract(self, start: date, end: date) -> Iterable[RawOrder]:
        return self.rows


class InMemoryLoader:
    def __init__(self) -> None:
        self.partitions: dict[date, list[Order]] = {}

    def load(self, orders: list[Order], partition: date) -> int:
        self.partitions[partition] = orders  # overwrite = idempotente
        return len(orders)


def test_pipeline_rejeita_invalidos_e_carrega_validos() -> None:
    loader = InMemoryLoader()
    pipeline = OrdersPipeline(
        FakeExtractor([make_raw("A1"), make_raw("A2", gross="1", discount="5")]), loader
    )

    result = pipeline.run(date(2026, 1, 31))

    assert (result.read, result.rejected, result.written) == (2, 1, 1)


def test_pipeline_reexecucao_e_idempotente() -> None:
    loader = InMemoryLoader()
    pipeline = OrdersPipeline(FakeExtractor([make_raw("A1")]), loader)

    pipeline.run(date(2026, 1, 31))
    pipeline.run(date(2026, 1, 31))

    assert len(loader.partitions[date(2026, 1, 31)]) == 1
```

### Mock de dependência externa (HTTP)

```python
from unittest.mock import Mock

import pytest
import requests

from nome_projeto.exceptions import ExtractionError
from nome_projeto.extractors.http import (
    get_json,
)  # função de retry de references/data-engineering.md


def test_extractor_traduz_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Mock(spec=requests.Session)
    session.get.side_effect = requests.Timeout()
    monkeypatch.setattr(
        "time.sleep", lambda _: None
    )  # sem espera real: teste rápido e determinístico

    with pytest.raises(ExtractionError):
        get_json(session, "https://api.exemplo/v1/orders", {}, max_attempts=2)

    assert session.get.call_count == 2
```

### Fixtures, arquivos e configuração

```python
# conftest.py
import pytest

from nome_projeto.config.settings import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(api_base_url="http://test", api_token="test-token", output_dir=tmp_path)
```

- Use `tmp_path` para arquivos, nunca caminhos reais do projeto.
- Use `monkeypatch.setenv` para variáveis de ambiente.
- Para tempo, injete `today: date` ou um `clock` como parâmetro em vez de chamar `date.today()` dentro da lógica.

## Integração

```python
import pytest

pytestmark = pytest.mark.integration


def test_loader_postgres_upsert(pg_engine) -> None: ...
```

- Rode os testes de integração com `poetry run pytest -m integration`. Eles exigem a infraestrutura descrita em `docs/development.md`, como um banco local ou Testcontainers.
- Testes de integração nunca acessam ambientes de produção.

## Cobertura: política de evolução

1. **Piso global**: 50% (`fail_under` e `--cov-fail-under`). Abaixo disso, o CI falha.
2. **Código novo ou alterado**: SHOULD ter 80% ou mais de cobertura no diff. O revisor confere no relatório `term-missing` ou `coverage.xml`.
3. **Módulos críticos** (`domain/`, `transformers/`, validações): SHOULD ter 80% ou mais.
4. **Catraca**: quando a cobertura global superar o piso em 10 pontos ou mais, suba o `fail_under` em um PR dedicado (`chore(tests): eleva cobertura mínima para 60%`). O piso nunca desce.
5. **Exclusões**: só via `exclude_also` para trechos inalcançáveis (`if TYPE_CHECKING:`, `if __name__ == "__main__":`, `raise NotImplementedError`). Excluir arquivos inteiros exige aprovação no PR.

Cobertura alta com asserts fracos não vale nada. Todo teste MUST verificar um resultado observável.

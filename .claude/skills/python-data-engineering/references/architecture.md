# Arquitetura: responsabilidades das camadas

Crie uma camada **só quando houver código para ela**. Um pipeline pequeno pode ter só `extractors/`, `transformers/`, `loaders/`, `pipelines/` e `config/`.

## Responsabilidade de cada camada

| Camada | Responsabilidade | Pode depender de | Não deve |
|---|---|---|---|
| `main.py` | Composition root: lê a CLI, carrega os settings, configura o logging, instancia as dependências e chama o pipeline. Traduz exceções em códigos de saída. | todas | conter regra de negócio ou transformação |
| `config/` | Classe `Settings`, validada na inicialização | `pydantic-settings` e stdlib | ler variáveis de ambiente espalhadas pelo código |
| `domain/` | Entidades, value objects e regras de negócio puras | stdlib, `exceptions/` | fazer I/O, importar SDKs, drivers ou frameworks |
| `schemas/` | Contratos de entrada e saída (Pydantic, TypedDict, schemas de DataFrame) | `domain/` | conter lógica de fluxo |
| `models/` | Modelos de persistência (tabelas SQLAlchemy, definições de tabela) | ORM | ser usado como contrato de API externa |
| `extractors/` | Ler de fontes externas e devolver dados brutos ou validados | `schemas/`, `exceptions/` | transformar regras de negócio |
| `transformers/` | Funções **puras**: dados de entrada → dados de saída | `domain/`, `schemas/` | fazer I/O, logar volumes, ler settings |
| `loaders/` | Escrever em destinos de forma idempotente | `schemas/`, `models/` | decidir regra de negócio |
| `repositories/` | Consultar e persistir os dados que a própria aplicação mantém (estado, watermarks, metadados) | `models/` | vazar detalhes do ORM para o domínio |
| `services/` | Casos de uso que orquestram domínio e repositórios fora do fluxo ETL (por exemplo, reprocessar uma partição) | `domain/`, `repositories/` | duplicar a lógica de `pipelines/` |
| `pipelines/` | Compor extract → validate → transform → load, medir e logar | extractors, transformers, loaders | instanciar clientes concretos (eles são injetados) |
| `exceptions/` | Hierarquia de exceções do projeto | stdlib | — |
| `utils/` | Utilidades genéricas, sem conhecimento do domínio (por exemplo, `chunked(iterable, size)`) | stdlib | conter qualquer coisa específica do negócio |

A dependência aponta sempre para dentro: infraestrutura → aplicação → domínio. O domínio não conhece banco, HTTP ou arquivos.

## Exemplo completo e mínimo

O cenário: extrair pedidos de uma API, calcular o valor líquido e gravar em arquivo particionado por data.

```text
src/nome_projeto/
├── main.py
├── config/settings.py
├── exceptions/__init__.py
├── schemas/order.py
├── extractors/orders_api.py
├── transformers/orders.py
├── loaders/csv_loader.py     # ou Parquet, banco etc.
└── pipelines/orders.py
```

### `exceptions/__init__.py`

```python
"""Exceções do projeto."""


class NomeProjetoError(Exception):
    """Base de todas as exceções do projeto."""


class ConfigurationError(NomeProjetoError):
    """Configuração ausente ou inválida."""


class ExtractionError(NomeProjetoError):
    """Falha ao ler de uma fonte externa."""


class DataValidationError(NomeProjetoError):
    """Dados violam o contrato esperado."""


class LoadError(NomeProjetoError):
    """Falha ao gravar no destino."""
```

### `schemas/order.py`: o contrato

```python
"""Contratos de dados de pedidos."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RawOrder:
    """Pedido como recebido da fonte."""

    order_id: str
    order_date: date
    gross_amount: Decimal
    discount: Decimal


@dataclass(frozen=True, slots=True)
class Order:
    """Pedido pronto para carga."""

    order_id: str
    order_date: date
    net_amount: Decimal
```

### `transformers/orders.py`: puro e trivialmente testável

```python
"""Transformações de pedidos."""

from collections.abc import Iterable

from nome_projeto.exceptions import DataValidationError
from nome_projeto.schemas.order import Order, RawOrder


def to_order(raw: RawOrder) -> Order:
    """Calcula o valor líquido de um pedido.

    Args:
        raw: Pedido bruto da fonte.

    Returns:
        Pedido com ``net_amount`` calculado.

    Raises:
        DataValidationError: Se o desconto for maior que o valor bruto.
    """
    if raw.discount > raw.gross_amount:
        raise DataValidationError(f"Desconto maior que o valor bruto no pedido {raw.order_id}")
    return Order(
        order_id=raw.order_id,
        order_date=raw.order_date,
        net_amount=raw.gross_amount - raw.discount,
    )


def deduplicate(orders: Iterable[Order]) -> list[Order]:
    """Remove pedidos duplicados mantendo a última ocorrência por ``order_id``."""
    return list({order.order_id: order for order in orders}.values())
```

### `pipelines/orders.py`: composição com dependências injetadas

```python
"""Pipeline de pedidos."""

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from nome_projeto.exceptions import DataValidationError
from nome_projeto.schemas.order import Order, RawOrder
from nome_projeto.transformers.orders import deduplicate, to_order

logger = logging.getLogger(__name__)


class OrderExtractor(Protocol):
    def extract(self, start: date, end: date) -> Iterable[RawOrder]: ...


class OrderLoader(Protocol):
    def load(self, orders: list[Order], partition: date) -> int: ...


@dataclass(frozen=True, slots=True)
class RunResult:
    read: int
    rejected: int
    written: int


class OrdersPipeline:
    """Extrai, transforma e carrega pedidos de uma partição diária."""

    def __init__(self, extractor: OrderExtractor, loader: OrderLoader) -> None:
        self._extractor = extractor
        self._loader = loader

    def run(self, partition: date) -> RunResult:
        """Processa uma partição. Reexecutar a mesma partição é seguro (idempotente)."""
        started = time.perf_counter()
        logger.info("Pipeline iniciado partition=%s", partition)

        raw_orders = list(self._extractor.extract(partition, partition))
        valid: list[Order] = []
        rejected = 0
        for raw in raw_orders:
            try:
                valid.append(to_order(raw))
            except DataValidationError:
                rejected += 1
                logger.warning("Pedido rejeitado order_id=%s", raw.order_id)

        written = self._loader.load(deduplicate(valid), partition)
        logger.info(
            "Pipeline concluído partition=%s read=%d rejected=%d written=%d duration_s=%.2f",
            partition,
            len(raw_orders),
            rejected,
            written,
            time.perf_counter() - started,
        )
        return RunResult(read=len(raw_orders), rejected=rejected, written=written)
```

### `main.py`: composition root, sem regra de negócio

```python
"""Entry point da aplicação."""

import argparse
import logging
import sys
from datetime import date

from nome_projeto.config.settings import get_settings
from nome_projeto.exceptions import NomeProjetoError
from nome_projeto.extractors.orders_api import OrdersApiExtractor
from nome_projeto.loaders.csv_loader import CsvOrderLoader
from nome_projeto.pipelines.orders import OrdersPipeline

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline de pedidos")
    parser.add_argument("--partition", type=date.fromisoformat, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    pipeline = OrdersPipeline(
        extractor=OrdersApiExtractor(base_url=settings.api_base_url, token=settings.api_token),
        loader=CsvOrderLoader(root=settings.output_dir),
    )
    try:
        pipeline.run(args.partition)
    except NomeProjetoError:
        logger.exception("Pipeline falhou partition=%s", args.partition)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Com `[project.scripts] nome_projeto = "nome_projeto.main:main"`, o orquestrador executa `poetry run nome_projeto --partition 2026-01-31`. O código de saída diferente de zero sinaliza a falha.

## Anti-patterns

| ❌ Evite | ✅ Faça |
|---|---|
| Uma `def run()` de 300 linhas que faz request, transformação e `to_sql` | Extractor, transformer e loader separados, compostos no pipeline |
| `requests.get(...)` dentro de um transformer | Transformer recebe dados; o I/O fica no extractor |
| `engine = create_engine(os.environ["DB"])` no topo do módulo | Criar a conexão em `main.py` e injetá-la |
| `class BaseAbstractGenericExtractorFactory` com uma implementação | Função ou classe concreta. Crie o `Protocol` quando surgir a segunda implementação ou a necessidade de teste |
| `utils/helpers.py` com regra de desconto | A regra vai para `domain/` ou `transformers/` |
| Herança profunda (`BaseLoader → SqlLoader → PgLoader → PgOrdersLoader`) | Composição: o loader recebe um `engine` e um nome de tabela |

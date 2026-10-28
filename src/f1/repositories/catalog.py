"""Catálogo DuckDB: manifesto de execuções, views ``silver_*`` e tabelas ``gold_*``."""

import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import polars as pl

from f1.exceptions import ConfigurationError, LoadError
from f1.schemas.endpoints import Partition

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")

_CREATE_MANIFEST = """
CREATE SCHEMA IF NOT EXISTS meta;
CREATE TABLE IF NOT EXISTS meta.ingestion_runs (
    run_id VARCHAR NOT NULL,
    layer VARCHAR NOT NULL,
    endpoint VARCHAR NOT NULL,
    partition VARCHAR NOT NULL,
    year INTEGER NOT NULL,
    session_key BIGINT,
    status VARCHAR NOT NULL,
    rows BIGINT,
    rejected BIGINT,
    error VARCHAR,
    ingested_at TIMESTAMPTZ NOT NULL
);
"""

_COMPLETED_ENDPOINTS = """
WITH latest AS (
    SELECT
        session_key,
        endpoint,
        status,
        row_number() OVER (PARTITION BY endpoint, partition ORDER BY ingested_at DESC) AS rn
    FROM meta.ingestion_runs
    WHERE layer = 'bronze' AND session_key IS NOT NULL AND year = ?
)
SELECT session_key, endpoint
FROM latest
WHERE rn = 1
GROUP BY session_key, endpoint
HAVING bool_and(status = 'success')
"""


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """Uma linha do manifesto: o resultado de uma partição numa camada."""

    run_id: str
    layer: str
    endpoint: str
    partition: Partition
    status: str
    ingested_at: datetime
    rows: int | None = None
    rejected: int | None = None
    error: str | None = None


class Catalog:
    """Acesso ao arquivo DuckDB do projeto.

    Args:
        connection: Conexão aberta (arquivo ou ``:memory:``), gerida por quem chama.
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._conn = connection
        self._conn.execute(_CREATE_MANIFEST)

    def record(self, entry: ManifestEntry) -> None:
        """Acrescenta uma linha ao manifesto ``meta.ingestion_runs``."""
        self._conn.execute(
            "INSERT INTO meta.ingestion_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                entry.run_id,
                entry.layer,
                entry.endpoint,
                entry.partition.path,
                entry.partition.year,
                entry.partition.session_key,
                entry.status,
                entry.rows,
                entry.rejected,
                entry.error,
                entry.ingested_at,
            ],
        )

    def completed_endpoints(self, year: int) -> dict[int, set[str]]:
        """Endpoints cuja última ingestão no bronze teve sucesso em todas as partições.

        Returns:
            ``{session_key: {endpoint, ...}}`` das sessões do ano.
        """
        completed: defaultdict[int, set[str]] = defaultdict(set)
        for session_key, endpoint in self._conn.execute(_COMPLETED_ENDPOINTS, [year]).fetchall():
            completed[session_key].add(endpoint)
        return dict(completed)

    def refresh_silver_view(
        self, endpoint: str, parquet_glob: str | None, schema: pl.Schema
    ) -> None:
        """Recria ``silver_{endpoint}`` sobre os Parquet do lake.

        Sem partições, cria uma tabela vazia com o schema da silver, para que os marts
        continuem consultáveis.

        Args:
            endpoint: Nome do endpoint.
            parquet_glob: Padrão dos arquivos silver, ou ``None`` se não houver arquivos.
            schema: Schema silver usado quando não há arquivos.
        """
        name = _identifier(f"silver_{endpoint}")
        self._conn.execute(f"DROP VIEW IF EXISTS {name}")
        self._conn.execute(f"DROP TABLE IF EXISTS {name}")
        if parquet_glob is not None:
            # DDL de view não aceita parâmetros; o caminho vem da configuração, não do usuário,
            # e é escapado como literal SQL.
            self._conn.execute(
                f"CREATE VIEW {name} AS SELECT * FROM read_parquet({_literal(parquet_glob)}, "
                "hive_partitioning = true, union_by_name = true)"
            )
            return
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.parquet"
            pl.DataFrame(schema=schema).write_parquet(empty)
            self._conn.execute(
                f"CREATE TABLE {name} AS SELECT * FROM read_parquet(?)", [str(empty)]
            )

    def build_table(self, name: str, select_sql: str) -> int:
        """Materializa ``select_sql`` na tabela ``name`` (overwrite) e devolve as linhas.

        Raises:
            LoadError: Se o SQL falhar.
        """
        table = _identifier(name)
        try:
            self._conn.execute(f"CREATE OR REPLACE TABLE {table} AS {select_sql}")
            row = self._conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        except duckdb.Error as exc:
            raise LoadError(f"Falha ao construir {table}: {exc}") from exc
        return int(row[0]) if row else 0


def _identifier(name: str) -> str:
    if not _IDENTIFIER.match(name):
        raise ConfigurationError(f"Identificador SQL inválido: {name!r}")
    return name


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

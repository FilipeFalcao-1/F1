"""Layout do data lake local e escrita atômica por partição."""

import gzip
import json
from collections.abc import Callable
from pathlib import Path

import polars as pl

from f1.exceptions import DataValidationError, LoadError
from f1.schemas.endpoints import Partition, Record

BRONZE_FILE = "data.json.gz"
PARQUET_FILE = "data.parquet"


class Lake:
    """Data lake em disco com as camadas bronze, silver e quarentena.

    Cada partição é um arquivo único, sobrescrito de forma atômica (``.tmp`` + ``replace``),
    o que torna a reexecução idempotente.

    Args:
        root: Raiz do lake (``F1_DATA_DIR``).
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def duckdb_path(self) -> Path:
        """Arquivo do catálogo DuckDB."""
        return self.root / "f1.duckdb"

    def bronze_path(self, endpoint: str, partition: Partition) -> Path:
        """Arquivo bronze de uma partição."""
        return self.root / "bronze" / endpoint / partition.path / BRONZE_FILE

    def silver_path(self, endpoint: str, partition: Partition) -> Path:
        """Arquivo silver de uma partição."""
        return self.root / "silver" / endpoint / partition.path / PARQUET_FILE

    def quarantine_path(self, endpoint: str, partition: Partition) -> Path:
        """Arquivo de quarentena de uma partição."""
        return self.root / "quarantine" / endpoint / partition.path / PARQUET_FILE

    def silver_glob(self, endpoint: str) -> str:
        """Padrão absoluto que casa todos os Parquet silver de um endpoint."""
        return str((self.root / "silver" / endpoint).resolve() / "**" / PARQUET_FILE)

    def has_silver(self, endpoint: str) -> bool:
        """Se existe ao menos uma partição silver do endpoint."""
        return any((self.root / "silver" / endpoint).rglob(PARQUET_FILE))

    def write_bronze(self, endpoint: str, partition: Partition, records: list[Record]) -> Path:
        """Grava os registros brutos como JSON comprimido, sobrescrevendo a partição."""
        target = self.bronze_path(endpoint, partition)
        payload = gzip.compress(json.dumps(records, ensure_ascii=False).encode("utf-8"), mtime=0)
        _atomic_write(target, lambda tmp: tmp.write_bytes(payload))
        return target

    def read_bronze(self, endpoint: str, partition: Partition) -> list[Record]:
        """Lê os registros brutos de uma partição.

        Raises:
            LoadError: Se o arquivo não existir ou não puder ser lido.
            DataValidationError: Se o conteúdo não for uma lista de objetos JSON.
        """
        path = self.bronze_path(endpoint, partition)
        try:
            payload = json.loads(gzip.decompress(path.read_bytes()))
        except (OSError, EOFError) as exc:
            raise LoadError(f"Falha ao ler bronze {path}") from exc
        except ValueError as exc:
            raise DataValidationError(f"Bronze corrompido em {path}") from exc
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise DataValidationError(f"Bronze em {path} não é uma lista de objetos")
        return payload

    def write_silver(self, endpoint: str, partition: Partition, frame: pl.DataFrame) -> Path:
        """Grava a partição silver em Parquet, sobrescrevendo-a."""
        target = self.silver_path(endpoint, partition)
        _atomic_write(target, frame.write_parquet)
        return target

    def write_quarantine(
        self, endpoint: str, partition: Partition, frame: pl.DataFrame
    ) -> Path | None:
        """Grava os rejeitados da partição; sem rejeitados, remove a quarentena anterior.

        Returns:
            O arquivo gravado, ou ``None`` se não houver rejeitados.
        """
        target = self.quarantine_path(endpoint, partition)
        if frame.is_empty():
            target.unlink(missing_ok=True)
            return None
        _atomic_write(target, frame.write_parquet)
        return target

    def bronze_partitions(
        self, endpoint: str, year: int | None = None, session_key: int | None = None
    ) -> list[Partition]:
        """Partições bronze existentes de um endpoint, filtradas por ano ou sessão."""
        base = self.root / "bronze" / endpoint
        partitions = (
            Partition.from_path(path.parent.relative_to(base).as_posix())
            for path in base.rglob(BRONZE_FILE)
        )
        return sorted(
            partition
            for partition in partitions
            if (year is None or partition.year == year)
            and (session_key is None or partition.session_key == session_key)
        )


def _atomic_write(target: Path, write: Callable[[Path], object]) -> None:
    tmp = target.with_name(f"{target.name}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        write(tmp)
        tmp.replace(target)
    except OSError as exc:
        if tmp.is_file():
            tmp.unlink()
        raise LoadError(f"Falha ao gravar {target}") from exc

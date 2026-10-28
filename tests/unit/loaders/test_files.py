import gzip

import polars as pl
import pytest

from f1.exceptions import DataValidationError, LoadError
from f1.loaders.files import Lake
from f1.schemas.endpoints import Partition

SESSION = Partition(2023, 9165)


def test_bronze_ida_e_volta_com_overwrite(lake: Lake) -> None:
    lake.write_bronze("laps", SESSION, [{"lap_number": 1}, {"lap_number": 2}])
    path = lake.write_bronze("laps", SESSION, [{"lap_number": 3}])

    assert path == lake.root / "bronze/laps/year=2023/session_key=9165/data.json.gz"
    assert lake.read_bronze("laps", SESSION) == [{"lap_number": 3}]
    assert not list(path.parent.glob("*.tmp"))


def test_bronze_e_deterministico(lake: Lake) -> None:
    first = lake.write_bronze("laps", SESSION, [{"a": 1}]).read_bytes()

    assert lake.write_bronze("laps", SESSION, [{"a": 1}]).read_bytes() == first


def test_read_bronze_inexistente_ou_corrompido(lake: Lake) -> None:
    with pytest.raises(LoadError):
        lake.read_bronze("laps", SESSION)

    path = lake.bronze_path("laps", SESSION)
    path.parent.mkdir(parents=True)
    path.write_bytes(gzip.compress(b'{"not": "list"}'))
    with pytest.raises(DataValidationError):
        lake.read_bronze("laps", SESSION)


def test_bronze_partitions_filtra_por_ano_e_sessao(lake: Lake) -> None:
    for partition in (Partition(2023, 2), Partition(2023, 1), Partition(2024, 3)):
        lake.write_bronze("laps", partition, [])

    assert lake.bronze_partitions("laps") == [
        Partition(2023, 1),
        Partition(2023, 2),
        Partition(2024, 3),
    ]
    assert lake.bronze_partitions("laps", year=2024) == [Partition(2024, 3)]
    assert lake.bronze_partitions("laps", session_key=2) == [Partition(2023, 2)]
    assert lake.bronze_partitions("stints") == []


def test_quarentena_vazia_remove_arquivo_anterior(lake: Lake) -> None:
    lake.write_quarantine("laps", SESSION, pl.DataFrame({"reject_reason": ["x"]}))
    assert lake.quarantine_path("laps", SESSION).exists()

    assert lake.write_quarantine("laps", SESSION, pl.DataFrame()) is None
    assert not lake.quarantine_path("laps", SESSION).exists()


def test_silver_e_glob(lake: Lake) -> None:
    assert not lake.has_silver("laps")

    lake.write_silver("laps", SESSION, pl.DataFrame({"lap_number": [1]}))

    assert lake.has_silver("laps")
    assert lake.silver_glob("laps").endswith("silver/laps/**/data.parquet")


def test_falha_de_escrita_vira_load_error(lake: Lake) -> None:
    lake.root.mkdir(parents=True)
    (lake.root / "bronze").write_text("arquivo no lugar do diretório")

    with pytest.raises(LoadError, match="Falha ao gravar"):
        lake.write_bronze("laps", SESSION, [])

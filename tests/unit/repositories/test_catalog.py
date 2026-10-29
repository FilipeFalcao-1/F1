from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from f1.exceptions import ConfigurationError, LoadError
from f1.loaders.files import Lake
from f1.repositories.catalog import Catalog, ManifestEntry
from f1.schemas.endpoints import Partition

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def entry(
    endpoint: str, partition: Partition, status: str, minutes: int, layer: str = "bronze"
) -> ManifestEntry:
    return ManifestEntry(
        "r", layer, endpoint, partition, status, T0 + timedelta(minutes=minutes), rows=1
    )


def test_completed_endpoints_usa_a_ultima_execucao_de_cada_particao(catalog: Catalog) -> None:
    catalog.record(entry("laps", Partition(2023, 1), "failed", 0))
    catalog.record(entry("laps", Partition(2023, 1), "success", 1))
    catalog.record(entry("stints", Partition(2023, 1), "success", 0))
    catalog.record(entry("stints", Partition(2023, 1), "failed", 1))
    catalog.record(entry("car_data", Partition(2023, 1, 44), "success", 0))
    catalog.record(entry("car_data", Partition(2023, 1, 55), "failed", 0))
    catalog.record(entry("laps", Partition(2023, 2), "success", 0, layer="silver"))
    catalog.record(entry("laps", Partition(2024, 3), "success", 0))

    assert catalog.completed_endpoints(2023) == {1: {"laps"}}


def test_view_silver_sobre_parquet_com_particao_hive(catalog: Catalog, lake: Lake) -> None:
    lake.write_silver(
        "laps", Partition(2023, 9165), pl.DataFrame({"session_key": [9165], "lap": [1]})
    )
    lake.write_silver(
        "laps", Partition(2024, 9500), pl.DataFrame({"session_key": [9500], "lap": [2]})
    )

    catalog.refresh_silver_view("laps", lake.silver_glob("laps"), pl.Schema())

    assert catalog.build_table("gold_test", "SELECT year, lap FROM silver_laps ORDER BY lap") == 2
    assert (
        catalog.build_table("gold_years", "SELECT DISTINCT year FROM silver_laps WHERE year = 2024")
        == 1
    )


def test_view_silver_vazia_vira_tabela_tipada(catalog: Catalog) -> None:
    catalog.refresh_silver_view("laps", None, pl.Schema({"lap": pl.Int32(), "year": pl.Int64()}))

    assert catalog.build_table("gold_test", "SELECT lap + 1 AS next_lap FROM silver_laps") == 0


def test_view_silver_pode_ser_recriada_ao_trocar_entre_tabela_e_view(
    catalog: Catalog, lake: Lake
) -> None:
    # Regressão: o segundo `marts build` falhava com a tabela vazia criada no primeiro
    schema = pl.Schema({"session_key": pl.Int64(), "lap": pl.Int64(), "year": pl.Int64()})
    catalog.refresh_silver_view("laps", None, schema)
    catalog.refresh_silver_view("laps", None, schema)
    lake.write_silver(
        "laps", Partition(2023, 9165), pl.DataFrame({"session_key": [9165], "lap": [1]})
    )
    catalog.refresh_silver_view("laps", lake.silver_glob("laps"), schema)
    catalog.refresh_silver_view("laps", lake.silver_glob("laps"), schema)

    assert catalog.build_table("gold_test", "SELECT lap FROM silver_laps") == 1

    catalog.refresh_silver_view("laps", None, schema)

    assert catalog.build_table("gold_test", "SELECT lap FROM silver_laps") == 0


def test_build_table_com_sql_invalido_vira_load_error(catalog: Catalog) -> None:
    with pytest.raises(LoadError, match="gold_x"):
        catalog.build_table("gold_x", "SELECT * FROM tabela_inexistente")


def test_identificador_invalido_e_rejeitado(catalog: Catalog) -> None:
    with pytest.raises(ConfigurationError):
        catalog.build_table("gold; DROP TABLE x", "SELECT 1")

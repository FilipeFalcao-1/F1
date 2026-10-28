import pytest

from f1.loaders.files import Lake
from f1.pipelines.marts import GOLD_MARTS, MartsPipeline, load_mart_sql
from f1.repositories.catalog import Catalog


@pytest.mark.parametrize("name", GOLD_MARTS)
def test_sql_dos_marts_e_versionado(name: str) -> None:
    assert "SELECT" in load_mart_sql(name)


def test_marts_constroem_sobre_silver_vazia(lake: Lake, catalog: Catalog) -> None:
    counts = MartsPipeline(lake, catalog).build()

    assert counts == dict.fromkeys(GOLD_MARTS, 0)

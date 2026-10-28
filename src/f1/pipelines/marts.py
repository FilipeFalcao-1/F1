"""Pipeline de marts: views ``silver_*`` e tabelas ``gold_*`` no DuckDB."""

import logging
import time
from importlib.resources import files

import polars as pl

from f1.loaders.files import Lake
from f1.repositories.catalog import Catalog
from f1.schemas.endpoints import ENDPOINTS
from f1.schemas.silver import CONTRACTS

logger = logging.getLogger(__name__)

HIVE_YEAR_COLUMN = "year"
GOLD_MARTS = (
    "gold_lap_pace",
    "gold_stint_summary",  # depende de gold_lap_pace
    "gold_pit_stops",
    "gold_race_results",
    "gold_championship_progression",
    "gold_session_weather",
)
"""Marts na ordem de construção. Cada um é ``sql/gold/<nome>.sql``."""


def load_mart_sql(name: str) -> str:
    """Lê o SQL versionado de um mart."""
    return files("f1").joinpath("sql", "gold", f"{name}.sql").read_text(encoding="utf-8")


class MartsPipeline:
    """Atualiza as views da silver e materializa os marts da gold.

    Args:
        lake: Data lake com as partições silver.
        catalog: Catálogo DuckDB de destino.
    """

    def __init__(self, lake: Lake, catalog: Catalog) -> None:
        self._lake = lake
        self._catalog = catalog

    def build(self) -> dict[str, int]:
        """Recria as views ``silver_*`` e reconstrói todos os marts (overwrite).

        Returns:
            Linhas de cada mart.

        Raises:
            LoadError: Se algum SQL falhar.
        """
        started = time.perf_counter()
        for endpoint in ENDPOINTS:
            has_files = self._lake.has_silver(endpoint)
            schema = pl.Schema({**CONTRACTS[endpoint].silver, HIVE_YEAR_COLUMN: pl.Int64()})
            self._catalog.refresh_silver_view(
                endpoint, self._lake.silver_glob(endpoint) if has_files else None, schema
            )
            if not has_files:
                logger.warning("Silver vazia endpoint=%s: view criada sem linhas", endpoint)
        counts: dict[str, int] = {}
        for name in GOLD_MARTS:
            mart_started = time.perf_counter()
            counts[name] = self._catalog.build_table(name, load_mart_sql(name))
            logger.info(
                "Mart construído table=%s rows=%d duration_s=%.2f",
                name,
                counts[name],
                time.perf_counter() - mart_started,
            )
        logger.info(
            "Marts concluídos marts=%d duration_s=%.1f", len(counts), time.perf_counter() - started
        )
        return counts

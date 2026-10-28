"""Ponta a ponta sem rede: fixtures reais → bronze → silver → gold (DuckDB em memória)."""

import pytest

from f1.loaders.files import Lake
from f1.pipelines.ingest import IngestPipeline
from f1.pipelines.marts import MartsPipeline
from f1.pipelines.refine import RefinePipeline
from f1.repositories.catalog import Catalog

pytestmark = pytest.mark.integration


def query(catalog: Catalog, sql: str) -> list[tuple[object, ...]]:
    return catalog._conn.execute(sql).fetchall()


def run_all(ingest: IngestPipeline, lake: Lake, catalog: Catalog) -> dict[str, int]:
    ingest.ingest_year(2023, with_telemetry=True, force=True)
    RefinePipeline(lake, catalog, "test-run", lambda: ingest._clock()).run(year=2023)
    return MartsPipeline(lake, catalog).build()


def test_pipeline_completo_gera_marts_consultaveis(
    ingest: IngestPipeline, lake: Lake, catalog: Catalog
) -> None:
    counts = run_all(ingest, lake, catalog)

    assert counts["gold_race_results"] == 3
    assert counts["gold_session_weather"] == 1
    assert all(rows > 0 for rows in counts.values())

    results = query(
        catalog,
        "SELECT name_acronym, position, grid_position, positions_gained "
        "FROM gold_race_results ORDER BY position",
    )
    assert results == [("SAI", 1, 1, 0), ("NOR", 2, 4, 2), ("VER", 5, 11, 6)]

    lap = query(
        catalog,
        "SELECT compound, tyre_age, is_pit_out_lap FROM gold_lap_pace "
        "WHERE driver_number = 55 AND lap_number = 3",
    )
    assert lap == [("MEDIUM", 2, False)]

    standings = query(
        catalog,
        "SELECT competitor, points_current FROM gold_championship_progression "
        "WHERE championship = 'team' AND position_current = 1",
    )
    assert standings == [("Red Bull Racing", 597.0)]


def test_manifesto_cobre_todos_os_endpoints_da_corrida(
    ingest: IngestPipeline, lake: Lake, catalog: Catalog
) -> None:
    run_all(ingest, lake, catalog)

    endpoints = {
        row[0]
        for row in query(
            catalog,
            "SELECT DISTINCT endpoint FROM meta.ingestion_runs "
            "WHERE layer = 'silver' AND (session_key = 9165 OR session_key IS NULL)",
        )
    }
    assert len(endpoints) == 18
    assert not lake.root.joinpath("quarantine").exists()


def test_reexecucao_nao_muda_as_contagens(
    ingest: IngestPipeline, lake: Lake, catalog: Catalog
) -> None:
    first = run_all(ingest, lake, catalog)
    silver_first = query(catalog, "SELECT count(*) FROM silver_car_data")

    assert run_all(ingest, lake, catalog) == first
    assert query(catalog, "SELECT count(*) FROM silver_car_data") == silver_first

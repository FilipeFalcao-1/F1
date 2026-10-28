from datetime import UTC, datetime

import polars as pl
import pytest

from f1.exceptions import ConfigurationError, DataValidationError
from f1.loaders.files import Lake
from f1.pipelines.refine import RefinePipeline
from f1.repositories.catalog import Catalog
from f1.schemas.endpoints import Partition

SESSION = Partition(2023, 9165)
STINT = {
    "meeting_key": 1219,
    "session_key": 9165,
    "driver_number": 1,
    "stint_number": 1,
    "lap_start": 1,
    "lap_end": 20,
    "compound": "MEDIUM",
    "tyre_age_at_start": 0,
}


@pytest.fixture
def refine(lake: Lake, catalog: Catalog) -> RefinePipeline:
    return RefinePipeline(lake, catalog, "run-1", lambda: datetime(2026, 1, 1, tzinfo=UTC))


def test_refina_e_manda_invalidos_para_quarentena_com_run_id(
    refine: RefinePipeline, lake: Lake
) -> None:
    lake.write_bronze("stints", SESSION, [STINT, STINT, {**STINT, "stint_number": None}])

    result = refine.run(session_key=9165)

    assert (result.read, result.written, result.rejected, result.duplicates_removed) == (3, 1, 1, 1)
    assert pl.read_parquet(lake.silver_path("stints", SESSION))["compound"].to_list() == ["MEDIUM"]
    quarantine = pl.read_parquet(lake.quarantine_path("stints", SESSION))
    assert quarantine.select("reject_reason", "run_id").row(0) == ("chave primária nula", "run-1")


def test_mudanca_de_schema_isola_o_endpoint(
    refine: RefinePipeline, lake: Lake, catalog: Catalog
) -> None:
    lake.write_bronze("stints", SESSION, [{**STINT, "nova": 1}])
    lake.write_bronze("team_radio", SESSION, [])

    with pytest.raises(DataValidationError, match="1 partições falharam"):
        refine.run(year=2023)

    assert lake.silver_path("team_radio", SESSION).exists()
    assert not lake.silver_path("stints", SESSION).exists()
    rows = catalog._conn.execute(
        "SELECT endpoint, status FROM meta.ingestion_runs WHERE layer = 'silver' ORDER BY endpoint"
    ).fetchall()
    assert rows == [("stints", "failed"), ("team_radio", "success")]


def test_refino_por_sessao_inclui_calendario_do_ano(refine: RefinePipeline, lake: Lake) -> None:
    lake.write_bronze("sessions", Partition(2023), [])
    lake.write_bronze("sessions", Partition(2024), [])
    lake.write_bronze("stints", SESSION, [STINT])

    result = refine.run(session_key=9165)

    assert result.partitions == 2
    assert not lake.silver_path("sessions", Partition(2024)).exists()


def test_exige_exatamente_um_filtro(refine: RefinePipeline) -> None:
    with pytest.raises(ConfigurationError):
        refine.run()
    with pytest.raises(ConfigurationError):
        refine.run(year=2023, session_key=1)


def test_sem_particoes_nao_falha(refine: RefinePipeline) -> None:
    assert refine.run(year=2030).partitions == 0

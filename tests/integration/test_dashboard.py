"""Dashboard sobre marts construídos a partir das fixtures (sem rede)."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from f1.extractors.client import OpenF1Client
from f1.extractors.openf1 import OpenF1Extractor
from f1.loaders.files import Lake
from f1.pipelines.ingest import IngestPipeline
from f1.pipelines.marts import MartsPipeline
from f1.pipelines.refine import RefinePipeline
from f1.repositories.catalog import Catalog
from f1.repositories.marts import MartsReader

pytestmark = pytest.mark.integration

APP = Path(__file__).parents[2] / "src" / "f1" / "dashboard" / "app.py"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def built_lake(lake: Lake, fake_api: object, make_client: Callable[..., OpenF1Client]) -> Lake:
    lake.root.mkdir(parents=True)
    with duckdb.connect(str(lake.duckdb_path)) as connection:
        catalog = Catalog(connection)
        IngestPipeline(
            OpenF1Extractor(make_client(fake_api)),
            lake,
            catalog,
            "t",
            lambda: NOW,
            frozenset({"Race"}),
        ).ingest_year(2023)
        RefinePipeline(lake, catalog, "t", lambda: NOW).run(year=2023)
        MartsPipeline(lake, catalog).build()
    return lake


@pytest.fixture
def reader(built_lake: Lake) -> Iterator[MartsReader]:
    with duckdb.connect(str(built_lake.duckdb_path), read_only=True) as connection:
        yield MartsReader(connection)


def test_reader_consultas_dos_marts(reader: MartsReader) -> None:
    assert reader.is_ready()
    assert reader.races()["session_key"].to_list() == [9165]
    assert reader.race_results(9165)["name_acronym"].to_list() == ["SAI", "NOR", "VER"]
    assert set(reader.stints(9165)["compound"]) <= {"SOFT", "MEDIUM", "HARD"}
    laps = reader.clean_laps(9165, ["SAI"])
    assert set(laps["name_acronym"]) == {"SAI"} and laps.height > 0
    assert reader.clean_laps(9165, ["SAI"], max_ratio=0.5).is_empty()
    assert reader.pit_stops_by_team(2023)["stops"].sum() == 3
    assert reader.fastest_stops(2023).is_empty()  # stop_duration só existe a partir de 2024
    assert reader.championship(2023, "team").height == 10


def test_reader_sem_marts_nao_esta_pronto() -> None:
    with duckdb.connect(":memory:") as connection:
        assert not MartsReader(connection).is_ready()


def render_page(db: str, name: str, arg: int) -> None:
    import duckdb

    from f1.dashboard import app
    from f1.repositories.marts import MartsReader

    with duckdb.connect(db, read_only=True) as connection:
        reader = MartsReader(connection)
        if name in ("race_page", "pace_page"):
            getattr(app, name)(reader, arg, "Singapore Grand Prix · Race")
        else:
            getattr(app, name)(reader, arg)


@pytest.mark.parametrize(
    ("page", "arg", "charts"),
    [
        ("race_page", 9165, 1),
        ("pace_page", 9165, 2),
        ("pit_page", 2023, 1),
        ("championship_page", 2023, 1),
    ],
)
def test_paginas_renderizam_sem_erro(built_lake: Lake, page: str, arg: int, charts: int) -> None:
    at = AppTest.from_function(
        render_page, args=(str(built_lake.duckdb_path), page, arg), default_timeout=30
    )
    at.run()

    assert not at.exception
    assert len([element for element in at.main if element.type == "vega_lite_chart"]) == charts


def test_resultado_mostra_destaques(built_lake: Lake) -> None:
    at = AppTest.from_function(
        render_page, args=(str(built_lake.duckdb_path), "race_page", 9165), default_timeout=30
    )
    at.run()

    assert [(metric.label, metric.value) for metric in at.metric] == [
        ("Vencedor", "Carlos SAINZ"),
        ("Pole position", "Carlos SAINZ"),
        ("Maior ganho", "Max VERSTAPPEN"),
    ]


def test_app_abre_na_pagina_de_resultado(built_lake: Lake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("F1_DATA_DIR", str(built_lake.root))
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()

    assert not at.exception
    assert at.header[0].value == "Singapore Grand Prix · Race"
    assert at.sidebar.selectbox[0].value == 2023


def test_app_sem_catalogo_orienta_o_usuario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("F1_DATA_DIR", str(tmp_path / "vazio"))
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()

    assert "f1 run" in at.info[0].value

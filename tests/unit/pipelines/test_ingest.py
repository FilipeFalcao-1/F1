from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from f1.domain.sessions import SessionInfo
from f1.exceptions import ExtractionError, RateLimitError
from f1.loaders.files import Lake
from f1.pipelines.ingest import IngestPipeline, plan_endpoints
from f1.repositories.catalog import Catalog
from f1.schemas.endpoints import ENDPOINTS, Partition, get_endpoints

RACE_ENDPOINTS = 14
NOW = datetime(2026, 1, 1, tzinfo=UTC)
RACE = SessionInfo(
    9165, 1219, 2023, "Race", "Race", NOW - timedelta(days=1), NOW - timedelta(hours=1)
)


@pytest.mark.parametrize(
    ("session_type", "types", "expected"),
    [
        ("Race", frozenset({"Race"}), 18 - 2),
        ("Practice", frozenset({"Race"}), 18 - 2 - 4 - 2),
        ("Practice", frozenset({"Practice"}), 18 - 2 - 4),
    ],
)
def test_plan_endpoints_aplica_race_only_e_telemetria(
    session_type: str, types: frozenset[str], expected: int
) -> None:
    candidates = [spec for spec in ENDPOINTS.values() if spec.name not in ("meetings", "sessions")]

    planned = plan_endpoints(replace(RACE, session_type=session_type), candidates, types)

    assert len(planned) == expected


def manifest(catalog: Catalog, sql: str) -> list[tuple[object, ...]]:
    return catalog._conn.execute(sql).fetchall()


def test_ingest_session_grava_bronze_e_manifesto(
    ingest: IngestPipeline, lake: Lake, catalog: Catalog, fake_api: object
) -> None:
    result = ingest.ingest_session_key(9165)

    assert result.partitions == RACE_ENDPOINTS
    assert lake.read_bronze("laps", Partition(2023, 9165))[0]["lap_number"] == 1
    assert lake.read_bronze("starting_grid", Partition(2023, 9165)) == []  # vazio é válido
    statuses = manifest(catalog, "SELECT DISTINCT layer, status FROM meta.ingestion_runs")
    assert statuses == [("bronze", "success")]


def test_ingest_session_com_telemetria_busca_por_piloto(ingest: IngestPipeline, lake: Lake) -> None:
    ingest.ingest_session_key(9165, with_telemetry=True)

    partitions = lake.bronze_partitions("car_data")
    assert [partition.driver_number for partition in partitions] == [1, 4, 55]
    assert len(lake.read_bronze("car_data", Partition(2023, 9165, 1))) == 15


def test_ingest_session_so_telemetria_busca_pilotos_sem_gravar_drivers(
    ingest: IngestPipeline, lake: Lake
) -> None:
    ingest.ingest_session_key(9165, endpoints=get_endpoints("location"))

    assert len(lake.bronze_partitions("location")) == 3
    assert lake.bronze_partitions("drivers") == []


def test_ingest_session_reexecucao_e_idempotente(ingest: IngestPipeline, lake: Lake) -> None:
    ingest.ingest_session_key(9165)
    first = lake.bronze_path("laps", Partition(2023, 9165)).read_bytes()
    ingest.ingest_session_key(9165)

    assert lake.bronze_path("laps", Partition(2023, 9165)).read_bytes() == first


def test_classificacao_pula_endpoints_de_corrida(ingest: IngestPipeline, fake_api: object) -> None:
    ingest.ingest_session_key(9161)

    called = fake_api.endpoints_called()  # type: ignore[attr-defined]
    assert "intervals" not in called and "championship_drivers" not in called
    assert "starting_grid" in called


def test_sessao_futura_e_pulada(
    ingest: IngestPipeline, fake_api: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest, "_clock", lambda: datetime(2023, 9, 17, 13, tzinfo=UTC))

    result = ingest.ingest_session_key(9165)

    assert result.sessions_skipped == 1
    assert fake_api.endpoints_called() == ["sessions"]  # type: ignore[attr-defined]


def test_falha_isolada_registra_e_falha_no_fim(
    ingest: IngestPipeline, lake: Lake, catalog: Catalog, fake_api: object
) -> None:
    fake_api.failing["weather"] = 400  # type: ignore[attr-defined]

    with pytest.raises(ExtractionError, match="1 partições falharam"):
        ingest.ingest_session_key(9165)

    assert lake.bronze_partitions("team_radio")  # endpoints seguintes foram gravados
    failed = manifest(catalog, "SELECT endpoint FROM meta.ingestion_runs WHERE status = 'failed'")
    assert failed == [("weather",)]


def test_rate_limit_interrompe_a_execucao(
    ingest: IngestPipeline, lake: Lake, fake_api: object
) -> None:
    fake_api.failing["laps"] = 429  # type: ignore[attr-defined]

    with pytest.raises(RateLimitError):
        ingest.ingest_session_key(9165)

    assert lake.bronze_partitions("stints") == []


def test_ingest_year_e_incremental(ingest: IngestPipeline, fake_api: object) -> None:
    first = ingest.ingest_year(2023)
    calls_after_first = len(fake_api.calls)  # type: ignore[attr-defined]
    second = ingest.ingest_year(2023)

    assert (first.sessions_ingested, first.sessions_skipped) == (5, 0)
    assert (second.sessions_ingested, second.sessions_skipped) == (0, 5)
    assert len(fake_api.calls) - calls_after_first == 2  # type: ignore[attr-defined]  # só o calendário

    assert ingest.ingest_year(2023, force=True).sessions_ingested == 5


def test_ingest_year_com_telemetria_reingere_sessoes_sem_telemetria(ingest: IngestPipeline) -> None:
    ingest.ingest_year(2023)

    result = ingest.ingest_year(2023, with_telemetry=True)

    assert result.sessions_ingested == 2  # Race e Qualifying (F1_TELEMETRY_SESSION_TYPES)


def test_calendario_sem_sessions_falha(ingest: IngestPipeline, fake_api: object) -> None:
    fake_api.failing["sessions"] = 500  # type: ignore[attr-defined]

    with pytest.raises(ExtractionError, match="calendário"):
        ingest.ingest_calendar(2023)

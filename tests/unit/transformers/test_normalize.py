from datetime import UTC, datetime

import polars as pl
import pytest

from f1.exceptions import DataValidationError
from f1.schemas.silver import CONTRACTS
from f1.transformers.normalize import normalize, records_to_frame, split_gap


def refine(endpoint: str, records: list[dict[str, object]]) -> pl.DataFrame:
    contract = CONTRACTS[endpoint]
    return normalize(endpoint, records_to_frame(records, contract.raw), contract)


def interval(
    value: object, gap: object, date: str = "2023-09-17T12:00:00.5+00:00"
) -> dict[str, object]:
    return {
        "meeting_key": 1219,
        "session_key": 9165,
        "driver_number": 1,
        "date": date,
        "interval": value,
        "gap_to_leader": gap,
    }


def result(duration: object, gap: object, **extra: object) -> dict[str, object]:
    return {
        "meeting_key": 1219,
        "session_key": 9161,
        "driver_number": 55,
        "position": 1,
        "number_of_laps": 20,
        "dnf": False,
        "dns": False,
        "dsq": False,
        "duration": duration,
        "gap_to_leader": gap,
        **extra,
    }


def test_intervals_separa_segundos_e_voltas_de_diferenca() -> None:
    frame = refine(
        "intervals",
        [interval(1.5, 10), interval("+1 LAP", "+2 LAPS"), interval(None, 0.0)],
    )

    assert frame.select(
        "interval_seconds",
        "interval_laps_behind",
        "gap_to_leader_seconds",
        "gap_to_leader_laps_behind",
    ).rows() == [(1.5, None, 10.0, None), (None, 1, None, 2), (None, None, 0.0, None)]
    assert "interval" not in frame.columns


def test_intervals_texto_desconhecido_falha_explicitamente() -> None:
    with pytest.raises(DataValidationError, match="intervals"):
        refine("intervals", [interval("DNF", 1.0)])


def test_session_result_da_classificacao_vira_colunas_q1_q3() -> None:
    frame = refine(
        "session_result",
        [
            result([92.339, 91.439, 90.984], [0.348, 0.0, 0.0]),
            result([95.1, None, None], [1.2, None, None]),
        ],
    )

    assert frame.select("duration_q1", "duration_q2", "duration_q3", "gap_q1", "gap_q3").rows() == [
        (92.339, 91.439, 90.984, 0.348, 0.0),
        (95.1, None, None, 1.2, None),
    ]
    assert frame["duration"].to_list() == [None, None]
    assert frame["points"].to_list() == [None, None]  # campo opcional ausente na classificação


def test_session_result_da_corrida_mantem_duration_e_separa_volta() -> None:
    frame = refine(
        "session_result",
        [result(6397.418, 0, points=25.0), result(None, "+1 LAP", points=0.0)],
    )

    assert frame.select(
        "duration", "gap_to_leader_seconds", "gap_to_leader_laps_behind", "duration_q1"
    ).rows() == [
        (6397.418, 0.0, None, None),
        (None, None, 1, None),
    ]


def test_datas_viram_utc_com_e_sem_fracao_de_segundo() -> None:
    frame = refine(
        "intervals",
        [
            interval(0.0, 0.0, "2023-09-17T11:01:01.780000+00:00"),
            interval(0.0, 0.0, "2023-09-17T13:01:01+02:00"),
        ],
    )

    assert frame.schema["date"] == pl.Datetime("us", "UTC")
    assert frame["date"].to_list() == [
        datetime(2023, 9, 17, 11, 1, 1, 780000, tzinfo=UTC),
        datetime(2023, 9, 17, 11, 1, 1, tzinfo=UTC),
    ]


def test_laps_mantem_segmentos_como_lista_e_aceita_nulos_em_corrida() -> None:
    lap = {
        "meeting_key": 1219,
        "session_key": 9165,
        "driver_number": 1,
        "lap_number": 2,
        "date_start": None,
        "duration_sector_1": 30.1,
        "duration_sector_2": None,
        "duration_sector_3": 28.0,
        "i1_speed": 283,
        "i2_speed": None,
        "is_pit_out_lap": False,
        "lap_duration": None,
        "segments_sector_1": [None, 2049, 2051],
        "segments_sector_2": None,
        "segments_sector_3": [],
        "st_speed": 300,
    }

    frame = refine("laps", [lap])

    assert frame.schema["segments_sector_1"] == pl.List(pl.Int32)
    assert frame.row(0, named=True)["segments_sector_1"] == [None, 2049, 2051]
    assert frame.row(0, named=True)["segments_sector_2"] is None


def test_campos_deprecados_sao_descartados() -> None:
    pit = {
        "meeting_key": 1,
        "session_key": 2,
        "driver_number": 3,
        "date": "2024-10-20T19:30:00+00:00",
        "lap_number": 20,
        "lane_duration": 22.1,
        "stop_duration": 2.4,
        "pit_duration": 22.1,
    }

    frame = refine("pit", [pit])

    assert "pit_duration" not in frame.columns
    assert frame.columns == list(CONTRACTS["pit"].silver)


def test_payload_vazio_gera_frame_vazio_com_schema_silver() -> None:
    frame = refine("team_radio", [])

    assert frame.is_empty()
    assert dict(frame.schema) == dict(CONTRACTS["team_radio"].silver)


def test_tipo_incompativel_com_contrato_da_api_falha() -> None:
    with pytest.raises(DataValidationError, match="contrato da API"):
        records_to_frame([{"position": "primeiro"}], {"position": pl.Int64()})


def test_split_gap_isolado() -> None:
    frame = pl.DataFrame({"gap": ["+3 LAPS", "12.5", None]}).select(split_gap(pl.col("gap"), "gap"))

    assert frame.rows() == [(None, 3), (12.5, None), (None, None)]

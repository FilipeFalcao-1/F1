import polars as pl
import pytest

from f1.exceptions import DataValidationError
from f1.schemas.silver import CONTRACTS
from f1.transformers.validate import (
    DUPLICATE_KEY_REASON,
    NULL_KEY_REASON,
    REJECT_REASON,
    check_columns,
    split_valid,
)

STINT = {
    "meeting_key": 1,
    "session_key": 2,
    "driver_number": 1,
    "stint_number": 1,
    "lap_start": 1,
    "lap_end": 20,
    "compound": "MEDIUM",
    "tyre_age_at_start": 0,
}


def test_check_columns_aceita_payload_completo_e_vazio() -> None:
    check_columns([STINT], CONTRACTS["stints"])
    check_columns([], CONTRACTS["stints"])


def test_check_columns_falha_com_coluna_nova() -> None:
    with pytest.raises(DataValidationError, match=r"novas=\['tyre_temperature'\]"):
        check_columns([{**STINT, "tyre_temperature": 90}], CONTRACTS["stints"])


def test_check_columns_falha_com_coluna_obrigatoria_ausente() -> None:
    record = {key: value for key, value in STINT.items() if key != "compound"}

    with pytest.raises(DataValidationError, match=r"ausentes=\['compound'\]"):
        check_columns([record], CONTRACTS["stints"])


def test_check_columns_tolera_opcionais_e_deprecados_ausentes() -> None:
    driver = {column: None for column in CONTRACTS["drivers"].raw if column != "country_code"}

    check_columns([driver], CONTRACTS["drivers"])


def test_split_valid_separa_nulos_duplicatas_e_conflitos() -> None:
    frame = pl.DataFrame(
        {
            "session_key": [1, 1, 1, 1, 1, None],
            "driver_number": [1, 1, 2, 3, 3, 4],
            "value": [10, 10, 20, 30, 31, 40],
        }
    )

    split = split_valid(frame, ["session_key", "driver_number"])

    assert split.valid.rows() == [(1, 1, 10), (1, 2, 20)]
    assert split.duplicates_removed == 1
    assert split.rejected.select("driver_number", REJECT_REASON).rows() == [
        (4, NULL_KEY_REASON),
        (3, DUPLICATE_KEY_REASON),
        (3, DUPLICATE_KEY_REASON),
    ]


def test_split_valid_frame_vazio() -> None:
    split = split_valid(pl.DataFrame(schema={"k": pl.Int64}), ["k"])

    assert split.valid.is_empty() and split.rejected.is_empty()
    assert split.duplicates_removed == 0

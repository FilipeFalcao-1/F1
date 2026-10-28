import polars as pl
import pytest

from f1.dashboard.charts import (
    GAINED,
    KEPT,
    LOST,
    MAX_SERIES,
    PALETTES,
    assign_slots,
    championship_chart,
    lap_pace_chart,
    positions_gained_chart,
    stint_chart,
    team_bar_chart,
)

LIGHT, DARK = PALETTES["light"], PALETTES["dark"]


def test_assign_slots_mantem_a_cor_de_quem_continua_selecionado() -> None:
    first = assign_slots({}, ["VER", "NOR", "LEC"])
    without_ver = assign_slots(first, ["NOR", "LEC"])
    with_ham = assign_slots(without_ver, ["NOR", "LEC", "HAM"])

    assert first == {"VER": 0, "NOR": 1, "LEC": 2}
    assert without_ver == {"NOR": 1, "LEC": 2}
    assert with_ham == {"NOR": 1, "LEC": 2, "HAM": 0}


def test_assign_slots_limita_a_tres_series() -> None:
    with pytest.raises(ValueError, match=str(MAX_SERIES)):
        assign_slots({}, ["A", "B", "C", "D"])


def test_posicoes_ganhas_usa_divergente_e_ordem_de_chegada() -> None:
    results = pl.DataFrame(
        {
            "name_acronym": ["SAI", "NOR", "VER", "ALB"],
            "full_name": ["a", "b", "c", "d"],
            "position": [1, 2, 5, None],
            "grid_position": [1, 4, 11, None],
            "positions_gained": [0, 2, 6, None],
        }
    )

    bars = positions_gained_chart(results, LIGHT).to_dict()["layer"][0]

    assert bars["encoding"]["y"]["sort"] == ["SAI", "NOR", "VER"]
    assert bars["encoding"]["color"]["scale"] == {
        "domain": [GAINED, KEPT, LOST],
        "range": [LIGHT.gain, LIGHT.neutral, LIGHT.loss],
    }


def test_stints_tem_letra_do_composto_e_so_compostos_presentes() -> None:
    stints = pl.DataFrame(
        {
            "name_acronym": ["SAI", "SAI", "NOR"],
            "stint_number": [1, 2, 1],
            "compound": ["MEDIUM", "HARD", None],
            "first_lap": [1, 21, 1],
            "last_lap": [20, 62, 62],
            "avg_clean_lap_duration": [100.0, 99.0, 99.5],
        }
    )

    spec = stint_chart(stints, DARK).to_dict()

    scale = spec["layer"][0]["encoding"]["color"]["scale"]
    assert scale["domain"] == ["MEDIUM", "HARD", "UNKNOWN"]
    assert scale["range"] == [DARK.compounds["MEDIUM"], DARK.compounds["HARD"], DARK.neutral]
    data = next(iter(spec["datasets"].values()))
    assert [row["letter"] for row in data] == ["M", "H", "?"]
    assert [row["start"] for row in data] == [0.5, 20.5, 0.5]


def test_ritmo_colore_pelo_slot_da_entidade() -> None:
    laps = pl.DataFrame(
        {
            "name_acronym": ["LEC", "HAM"],
            "lap_number": [2, 2],
            "lap_duration": [100.1, 100.4],
            "compound": ["SOFT", "SOFT"],
            "tyre_age": [1, 1],
        }
    )

    spec = lap_pace_chart(laps, {"LEC": 2, "HAM": 0}, LIGHT).to_dict()

    assert spec["layer"][0]["encoding"]["color"]["scale"] == {
        "domain": ["HAM", "LEC"],
        "range": [LIGHT.series[0], LIGHT.series[2]],
    }


def test_barras_por_equipe_ordenam_e_ignoram_nulos() -> None:
    frame = pl.DataFrame(
        {"team_name": ["A", "B", "C"], "stops": [3, 4, 5], "median_stop_duration": [2.9, None, 2.2]}
    )

    spec = team_bar_chart(frame, "median_stop_duration", "Parado (s)", LIGHT).to_dict()

    assert spec["encoding"]["y"]["sort"] == ["C", "A"]


def test_campeonato_destaca_e_deixa_o_resto_em_cinza() -> None:
    progression = pl.DataFrame(
        {
            "date_start": ["2026-03-01", "2026-03-08"] * 2,
            "meeting_name": ["GP1", "GP2"] * 2,
            "session_name": ["Race"] * 4,
            "competitor_name": ["Max", "Max", "Lando", "Lando"],
            "points_current": [25.0, 43.0, 18.0, 43.0],
            "position_current": [1, 1, 2, 2],
        }
    ).with_columns(pl.col("date_start").str.to_date())

    spec = championship_chart(progression, {"Max": 0}, LIGHT).to_dict()

    context, focus = spec["layer"][0], spec["layer"][1]
    assert context["mark"]["color"] == LIGHT.neutral
    assert focus["encoding"]["color"]["scale"] == {"domain": ["Max"], "range": [LIGHT.series[0]]}

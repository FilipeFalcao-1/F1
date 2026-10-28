"""Dashboard Streamlit sobre os marts ``gold_*``.

Rode com ``poetry run f1 dashboard`` (exige ``poetry install --extras dashboard``).
O DuckDB é aberto em modo somente leitura a cada interação, então o pipeline pode
escrever entre uma interação e outra.
"""

from collections.abc import Callable
from typing import cast

import duckdb
import polars as pl
import streamlit as st

from f1.config.settings import load_settings
from f1.dashboard.charts import (
    MAX_SERIES,
    PALETTES,
    Mode,
    Palette,
    assign_slots,
    championship_chart,
    lap_pace_chart,
    positions_gained_chart,
    stint_chart,
    team_bar_chart,
)
from f1.loaders.files import Lake
from f1.repositories.marts import MartsReader

CHAMPIONSHIPS = {"Pilotos": "driver", "Equipes": "team"}


def current_palette() -> Palette:
    """Paleta do tema ativo no Streamlit (claro por padrão)."""
    mode = st.context.theme.type
    return PALETTES[cast(Mode, mode) if mode in PALETTES else "light"]


def stable_slots(key: str, selected: list[str]) -> dict[str, int]:
    """Slots de cor que sobrevivem entre interações (a cor segue a entidade)."""
    slots = assign_slots(st.session_state.get(key, {}), selected)
    st.session_state[key] = slots
    return slots


def race_label(races: pl.DataFrame) -> Callable[[int], str]:
    """Rótulo legível de uma corrida a partir do ``session_key``."""
    labels = {
        row["session_key"]: f"{row['meeting_name']} · {row['session_name']}"
        for row in races.iter_rows(named=True)
    }
    return lambda key: labels.get(key, str(key))


def race_page(reader: MartsReader, session_key: int, title: str) -> None:
    """Resultado da corrida: destaques, posições ganhas e tabela."""
    st.header(title)
    results = reader.race_results(session_key)
    finishers = results.filter(pl.col("position").is_not_null())
    winner = finishers.row(0, named=True) if finishers.height else None
    pole = results.filter(pl.col("grid_position") == 1)
    best = results.filter(pl.col("positions_gained").is_not_null()).sort(
        "positions_gained", descending=True
    )

    left, middle, right = st.columns(3)
    left.metric(
        "Vencedor",
        winner["full_name"] if winner else "—",
        winner["team_name"] if winner else None,
        delta_color="off",
    )
    middle.metric("Pole position", pole["full_name"][0] if pole.height else "—")
    if best.height:
        top = best.row(0, named=True)
        right.metric("Maior ganho", top["full_name"], f"+{top['positions_gained']} posições")
    else:
        right.metric("Maior ganho", "—")

    st.subheader("Posições ganhas da largada à chegada")
    if best.height:
        st.altair_chart(positions_gained_chart(results, current_palette()), width="stretch")
    else:
        st.info("Grid de largada indisponível: ingira a classificação deste fim de semana.")
    st.dataframe(
        results.select(
            pl.col("position").alias("Pos."),
            pl.col("name_acronym").alias("Piloto"),
            pl.col("team_name").alias("Equipe"),
            pl.col("grid_position").alias("Largada"),
            pl.col("positions_gained").alias("Ganho"),
            pl.col("points").alias("Pontos"),
            pl.col("number_of_laps").alias("Voltas"),
            pl.col("gap_to_leader_seconds").alias("Gap (s)"),
            pl.col("gap_to_leader_laps_behind").alias("Voltas atrás"),
            pl.col("dnf").alias("DNF"),
        ),
        hide_index=True,
    )


def pace_page(reader: MartsReader, session_key: int, title: str) -> None:
    """Ritmo e pneus: estratégia de stints e tempo de volta por piloto."""
    st.header(title)
    palette = current_palette()
    stints = reader.stints(session_key)
    if stints.is_empty():
        st.info("Sem voltas nesta sessão: ingira os endpoints laps e stints.")
        return

    st.subheader("Estratégia de pneus")
    st.altair_chart(stint_chart(stints, palette), width="stretch")
    st.caption("S macio · M médio · H duro · I intermediário · W chuva")

    st.subheader("Tempo de volta")
    drivers = stints.unique("name_acronym", maintain_order=True)["name_acronym"].to_list()
    selected = st.multiselect(
        "Pilotos (até 3)",
        drivers,
        default=drivers[:MAX_SERIES],
        max_selections=MAX_SERIES,
        key=f"pace_drivers_{session_key}",
    )
    laps = reader.clean_laps(session_key, selected)
    if laps.is_empty():
        st.info("Selecione ao menos um piloto com voltas limpas.")
    else:
        slots = stable_slots(f"pace_slots_{session_key}", selected)
        st.altair_chart(lap_pace_chart(laps, slots, palette), width="stretch")
        st.caption(
            "Voltas limpas: sem volta 1, sem entrada ou saída do pit e até 107% da mediana da sessão."
        )

    st.subheader("Resumo por stint")
    st.dataframe(
        stints.select(
            pl.col("name_acronym").alias("Piloto"),
            pl.col("stint_number").alias("Stint"),
            pl.col("compound").alias("Composto"),
            pl.col("first_lap").alias("Da volta"),
            pl.col("last_lap").alias("Até"),
            pl.col("clean_laps").alias("Voltas limpas"),
            pl.col("avg_clean_lap_duration").round(3).alias("Ritmo médio (s)"),
            pl.col("best_clean_lap_duration").round(3).alias("Melhor (s)"),
            pl.col("degradation_s_per_lap").round(3).alias("Degradação (s/volta)"),
        ),
        hide_index=True,
    )


def pit_page(reader: MartsReader, year: int) -> None:
    """Pit stops da temporada por equipe."""
    st.header(f"Pit stops · {year}")
    palette = current_palette()
    by_team = reader.pit_stops_by_team(year)
    if by_team.is_empty():
        st.info("Sem pit stops de corrida nesta temporada.")
        return

    st.subheader("Tempo no pit lane (mediana)")
    st.altair_chart(
        team_bar_chart(by_team, "median_lane_duration", "Pit lane (s)", palette), width="stretch"
    )
    st.subheader("Tempo parado (mediana)")
    if by_team["median_stop_duration"].is_null().all():
        st.info(
            "Sem tempo parado (stop_duration) nesta temporada: a OpenF1 só o publica em parte "
            "das corridas, a partir do GP dos EUA de 2024."
        )
    else:
        st.altair_chart(
            team_bar_chart(by_team, "median_stop_duration", "Parado (s)", palette), width="stretch"
        )
        st.subheader("Paradas mais rápidas")
        st.dataframe(reader.fastest_stops(year), hide_index=True)


def championship_page(reader: MartsReader, year: int) -> None:
    """Evolução do campeonato na temporada."""
    st.header(f"Campeonato · {year}")
    label = st.segmented_control("Campeonato", list(CHAMPIONSHIPS), default="Pilotos")
    championship = CHAMPIONSHIPS[label or "Pilotos"]
    progression = reader.championship(year, championship)
    if progression.is_empty():
        st.info("Sem dados de campeonato (endpoint beta, só em corridas).")
        return

    standings = progression.filter(pl.col("date_start") == pl.col("date_start").max()).sort(
        "position_current"
    )
    names = standings["competitor_name"].to_list()
    selected = st.multiselect(
        "Destacar (até 3)",
        names,
        default=names[:MAX_SERIES],
        max_selections=MAX_SERIES,
        key=f"championship_{year}_{championship}",
    )
    slots = stable_slots(f"championship_slots_{year}_{championship}", selected)
    st.altair_chart(championship_chart(progression, slots, current_palette()), width="stretch")
    st.caption("Os demais competidores aparecem em cinza, como contexto.")
    st.dataframe(
        standings.select(
            pl.col("position_current").alias("Pos."),
            pl.col("competitor_name").alias("Competidor"),
            pl.col("points_current").alias("Pontos"),
            pl.col("points_gained").alias("Na última corrida"),
        ),
        hide_index=True,
    )


def main() -> None:
    """Monta a navegação e os filtros compartilhados (temporada e corrida)."""
    st.set_page_config(page_title="F1 · OpenF1", layout="wide")
    path = Lake(load_settings().data_dir).duckdb_path
    if not path.exists():
        st.info(f"Catálogo não encontrado em `{path}`. Rode `poetry run f1 run --year 2025`.")
        return
    with duckdb.connect(str(path), read_only=True) as connection:
        reader = MartsReader(connection)
        races = reader.races() if reader.is_ready() else pl.DataFrame()
        if races.is_empty():
            st.info(
                "Nenhuma corrida nos marts. Rode `poetry run f1 refine` e `poetry run f1 marts build`."
            )
            return

        years = races["year"].unique().sort(descending=True).to_list()
        year = st.sidebar.selectbox("Temporada", years, key="year")
        season = races.filter(pl.col("year") == year)
        session_key = st.sidebar.selectbox(
            "Corrida", season["session_key"].to_list(), format_func=race_label(season), key="race"
        )
        title = race_label(season)(session_key)

        pages = [
            st.Page(
                lambda: race_page(reader, session_key, title),
                title="Resultado",
                url_path="resultado",
            ),
            st.Page(
                lambda: pace_page(reader, session_key, title),
                title="Ritmo e pneus",
                url_path="ritmo",
            ),
            st.Page(lambda: pit_page(reader, year), title="Pit stops", url_path="pit-stops"),
            st.Page(
                lambda: championship_page(reader, year), title="Campeonato", url_path="campeonato"
            ),
        ]
        st.navigation(pages).run()


if __name__ == "__main__":
    main()

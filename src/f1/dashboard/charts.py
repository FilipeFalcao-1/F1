"""Gráficos Altair do dashboard: funções puras de DataFrame para gráfico.

As cores seguem a paleta de referência de visualização, validada em ambos os modos:
categórica em ordem fixa (no máximo três séries), divergente azul ↔ vermelho com cinza
neutro, e compostos de pneu com codificação secundária (letra na barra).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import altair as alt
import polars as pl

type Mode = Literal["light", "dark"]

MAX_SERIES = 3
"""Séries com cor própria por gráfico: as três primeiras cores validam todos os pares."""

COMPOUND_LETTERS: Mapping[str, str] = {
    "SOFT": "S",
    "MEDIUM": "M",
    "HARD": "H",
    "INTERMEDIATE": "I",
    "WET": "W",
}
GAINED, LOST, KEPT = "Ganhou posições", "Perdeu posições", "Manteve"


@dataclass(frozen=True, slots=True)
class Palette:
    """Cores de um modo (claro ou escuro)."""

    series: tuple[str, ...]
    gain: str
    loss: str
    neutral: str
    muted: str
    surface: str
    compounds: Mapping[str, str]
    dark_ink_on: frozenset[str]
    """Compostos cuja letra usa tinta escura (fundo claro, como o amarelo)."""


PALETTES: Mapping[Mode, Palette] = {
    "light": Palette(
        series=("#2a78d6", "#eb6834", "#1baf7a"),
        gain="#2a78d6",
        loss="#e34948",
        neutral="#c3c2b7",
        muted="#898781",
        surface="#ffffff",
        compounds={
            "SOFT": "#e34948",
            "MEDIUM": "#eda100",
            "HARD": "#898781",
            "INTERMEDIATE": "#008300",
            "WET": "#2a78d6",
        },
        dark_ink_on=frozenset({"MEDIUM"}),
    ),
    "dark": Palette(
        series=("#3987e5", "#d95926", "#199e70"),
        gain="#3987e5",
        loss="#e66767",
        neutral="#383835",
        muted="#898781",
        surface="#0e1117",
        compounds={
            "SOFT": "#e34948",
            "MEDIUM": "#c98500",
            "HARD": "#898781",
            "INTERMEDIATE": "#008300",
            "WET": "#3987e5",
        },
        dark_ink_on=frozenset(),
    ),
}


def assign_slots(previous: Mapping[str, int], selected: Sequence[str]) -> dict[str, int]:
    """Atribui a cada entidade selecionada um slot de cor estável.

    Quem já estava selecionado mantém o slot (a cor segue a entidade, não a posição na
    lista); quem entra recebe o menor slot livre.

    Args:
        previous: Atribuição anterior, ``{entidade: slot}``.
        selected: Entidades selecionadas agora (no máximo ``MAX_SERIES``).

    Raises:
        ValueError: Se houver mais entidades que slots.
    """
    if len(selected) > MAX_SERIES:
        raise ValueError(f"No máximo {MAX_SERIES} séries com cor própria")
    slots = {name: previous[name] for name in selected if name in previous}
    free = iter(sorted(set(range(MAX_SERIES)) - set(slots.values())))
    for name in selected:
        if name not in slots:
            slots[name] = next(free)
    return slots


def _color_scale(slots: Mapping[str, int], palette: Palette) -> alt.Scale:
    ordered = sorted(slots, key=slots.__getitem__)
    return alt.Scale(domain=ordered, range=[palette.series[slots[name]] for name in ordered])


def positions_gained_chart(results: pl.DataFrame, palette: Palette) -> alt.LayerChart:
    """Barras divergentes de posições ganhas (grid → chegada), na ordem de chegada."""
    data = results.filter(pl.col("positions_gained").is_not_null()).with_columns(
        pl.when(pl.col("positions_gained") > 0)
        .then(pl.lit(GAINED))
        .when(pl.col("positions_gained") < 0)
        .then(pl.lit(LOST))
        .otherwise(pl.lit(KEPT))
        .alias("change")
    )
    order = data["name_acronym"].to_list()
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=4, height={"band": 0.7})
        .encode(
            x=alt.X("positions_gained:Q", title="Posições ganhas", axis=alt.Axis(tickMinStep=1)),
            y=alt.Y("name_acronym:N", sort=order, title=None),
            color=alt.Color(
                "change:N",
                scale=alt.Scale(
                    domain=[GAINED, KEPT, LOST],
                    range=[palette.gain, palette.neutral, palette.loss],
                ),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=[
                alt.Tooltip("full_name:N", title="Piloto"),
                alt.Tooltip("grid_position:Q", title="Largada"),
                alt.Tooltip("position:Q", title="Chegada"),
                alt.Tooltip("positions_gained:Q", title="Ganho"),
            ],
        )
    )
    baseline = (
        alt.Chart(pl.DataFrame({"zero": [0]})).mark_rule(color=palette.muted).encode(x="zero:Q")
    )
    return alt.LayerChart(layer=[bars, baseline])


def stint_chart(stints: pl.DataFrame, palette: Palette) -> alt.LayerChart:
    """Linha do tempo de pneus: um segmento por stint, colorido e rotulado pelo composto."""
    data = stints.with_columns(
        pl.col("compound").fill_null("UNKNOWN"),
        (pl.col("first_lap") - 0.5).alias("start"),
        (pl.col("last_lap") + 0.5).alias("end"),
        ((pl.col("first_lap") + pl.col("last_lap")) / 2).alias("middle"),
        pl.col("compound").replace_strict(COMPOUND_LETTERS, default="?").alias("letter"),
    )
    order = data.unique("name_acronym", maintain_order=True)["name_acronym"].to_list()
    present = [name for name in palette.compounds if name in set(data["compound"])]
    base = alt.Chart(data).encode(y=alt.Y("name_acronym:N", sort=order, title=None))
    segments = base.mark_bar(
        cornerRadius=4, height={"band": 0.7}, stroke=palette.surface, strokeWidth=2
    ).encode(
        x=alt.X("start:Q", title="Volta", scale=alt.Scale(nice=False)),
        x2="end:Q",
        color=alt.Color(
            "compound:N",
            scale=alt.Scale(
                domain=[*present, "UNKNOWN"],
                range=[*(palette.compounds[name] for name in present), palette.neutral],
            ),
            legend=alt.Legend(title="Composto", orient="top"),
        ),
        tooltip=[
            alt.Tooltip("name_acronym:N", title="Piloto"),
            alt.Tooltip("stint_number:Q", title="Stint"),
            alt.Tooltip("compound:N", title="Composto"),
            alt.Tooltip("first_lap:Q", title="Da volta"),
            alt.Tooltip("last_lap:Q", title="Até a volta"),
            alt.Tooltip("avg_clean_lap_duration:Q", title="Ritmo médio (s)", format=".3f"),
        ],
    )
    labels = base.mark_text(fontSize=11, fontWeight="bold").encode(
        x="middle:Q",
        text="letter:N",
        color=alt.condition(
            alt.FieldOneOfPredicate(field="compound", oneOf=sorted(palette.dark_ink_on)),
            alt.value("#0b0b0b"),
            alt.value("#ffffff"),
        ),
    )
    return alt.LayerChart(layer=[segments, labels])


def lap_pace_chart(
    laps: pl.DataFrame, slots: Mapping[str, int], palette: Palette
) -> alt.LayerChart:
    """Tempo de volta por volta, uma linha por piloto, com crosshair e tooltip."""
    color = alt.Color(
        "name_acronym:N",
        scale=_color_scale(slots, palette),
        legend=alt.Legend(title=None, orient="top"),
    )
    base = alt.Chart(laps).encode(
        x=alt.X("lap_number:Q", title="Volta", axis=alt.Axis(tickMinStep=1)),
        y=alt.Y("lap_duration:Q", title="Tempo de volta (s)", scale=alt.Scale(zero=False)),
        color=color,
    )
    hover = alt.selection_point(nearest=True, on="pointerover", fields=["lap_number"], empty=False)
    lines = base.mark_line(strokeWidth=2)
    points = (
        base.mark_point(size=64, filled=True)
        .encode(
            opacity=alt.condition(hover, alt.value(1), alt.value(0)),
            tooltip=[
                alt.Tooltip("name_acronym:N", title="Piloto"),
                alt.Tooltip("lap_number:Q", title="Volta"),
                alt.Tooltip("lap_duration:Q", title="Tempo (s)", format=".3f"),
                alt.Tooltip("compound:N", title="Composto"),
                alt.Tooltip("tyre_age:Q", title="Idade do pneu"),
            ],
        )
        .add_params(hover)
    )
    rule = (
        alt.Chart(laps)
        .mark_rule(color=palette.muted)
        .encode(x="lap_number:Q")
        .transform_filter(hover)
    )
    return alt.LayerChart(layer=[lines, rule, points])


def team_bar_chart(frame: pl.DataFrame, value: str, title: str, palette: Palette) -> alt.Chart:
    """Barras horizontais de uma medida por equipe (uma série, uma cor), menor primeiro."""
    data = frame.filter(pl.col(value).is_not_null()).sort(value)
    chart: alt.Chart = (
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=4, height={"band": 0.7}, color=palette.series[0])
        .encode(
            x=alt.X(f"{value}:Q", title=title),
            y=alt.Y("team_name:N", sort=data["team_name"].to_list(), title=None),
            tooltip=[
                alt.Tooltip("team_name:N", title="Equipe"),
                alt.Tooltip(f"{value}:Q", title=title, format=".2f"),
                alt.Tooltip("stops:Q", title="Paradas"),
            ],
        )
    )
    return chart


def championship_chart(
    progression: pl.DataFrame, slots: Mapping[str, int], palette: Palette
) -> alt.LayerChart:
    """Pontos acumulados por corrida: destacados em cor, demais em cinza (ênfase)."""
    highlighted = list(slots)
    data = progression.with_columns(pl.col("competitor_name").is_in(highlighted).alias("highlight"))
    base = alt.Chart(data).encode(
        x=alt.X("date_start:T", title=None),
        y=alt.Y("points_current:Q", title="Pontos"),
        detail="competitor_name:N",
    )
    context = base.transform_filter(~alt.datum.highlight).mark_line(
        strokeWidth=1, color=palette.neutral
    )
    tooltip = [
        alt.Tooltip("competitor_name:N", title="Competidor"),
        alt.Tooltip("meeting_name:N", title="Etapa"),
        alt.Tooltip("session_name:N", title="Sessão"),
        alt.Tooltip("points_current:Q", title="Pontos"),
        alt.Tooltip("position_current:Q", title="Posição"),
    ]
    color = alt.Color(
        "competitor_name:N",
        scale=_color_scale(slots, palette),
        legend=alt.Legend(title=None, orient="top"),
    )
    focus = base.transform_filter(alt.datum.highlight).mark_line(strokeWidth=2).encode(color=color)
    hits = base.mark_point(size=80, opacity=0).encode(tooltip=tooltip)
    last = (
        base.transform_filter(alt.datum.highlight)
        .transform_window(
            rank="rank()",
            sort=[alt.SortField("date_start", order="descending")],
            groupby=["competitor_name"],
        )
        .transform_filter(alt.datum.rank == 1)
        .mark_text(align="left", dx=6, fontSize=11)
        .encode(text="competitor_name:N")
    )
    return alt.LayerChart(layer=[context, focus, hits, last])

"""Transformações puras bronze → silver: parse, regras por endpoint e cast para o contrato."""

import io
import json
from collections.abc import Callable

import polars as pl

from f1.exceptions import DataValidationError
from f1.schemas.endpoints import Record
from f1.schemas.silver import Contract, Schema

LAPS_BEHIND_PATTERN = r"^\+(\d+) LAPS?$"
QUALIFYING_PARTS = (1, 2, 3)


def records_to_frame(records: list[Record], raw: Schema) -> pl.DataFrame:
    """Monta o DataFrame bruto com os tipos do contrato da API.

    Os registros passam por NDJSON porque ``read_ndjson`` aceita campos polimórficos
    (número, texto ou lista) como texto JSON, o que ``from_dicts`` não faz.

    Raises:
        DataValidationError: Se algum valor não couber no tipo declarado.
    """
    ndjson = "\n".join(json.dumps(record) for record in records).encode("utf-8")
    try:
        return pl.read_ndjson(io.BytesIO(ndjson), schema=dict(raw))
    except pl.exceptions.PolarsError as exc:
        raise DataValidationError(f"Payload fora do contrato da API: {exc}") from exc


def normalize(endpoint: str, frame: pl.DataFrame, contract: Contract) -> pl.DataFrame:
    """Converte o DataFrame bruto de um endpoint para o schema da silver.

    Etapas: parse das datas para UTC, regra específica do endpoint (se houver) e cast
    estrito para ``contract.silver``, que também descarta campos deprecados.

    Raises:
        DataValidationError: Se algum valor não puder ser convertido.
    """
    try:
        frame = frame.with_columns(_parse_dates(frame.schema, contract.silver))
        rule = _ENDPOINT_RULES.get(endpoint)
        if rule is not None:
            frame = rule(frame)
        return frame.select(pl.col(name).cast(dtype) for name, dtype in contract.silver.items())
    except pl.exceptions.PolarsError as exc:
        raise DataValidationError(f"Falha ao normalizar {endpoint}: {exc}") from exc


def _parse_dates(current: pl.Schema, silver: Schema) -> list[pl.Expr]:
    return [
        pl.col(name).str.to_datetime(time_unit="us", time_zone="UTC")
        for name, dtype in silver.items()
        if isinstance(dtype, pl.Datetime) and current.get(name) == pl.String
    ]


def split_gap(value: pl.Expr, prefix: str) -> list[pl.Expr]:
    """Separa um gap da OpenF1 em segundos e voltas de diferença.

    ``"+1 LAP"``/``"+2 LAPS"`` viram ``{prefix}_laps_behind`` (com ``_seconds`` nulo);
    números viram ``{prefix}_seconds``. Texto fora desses formatos falha o cast.

    Args:
        value: Expressão textual com o valor bruto.
        prefix: Prefixo das colunas geradas.
    """
    laps_behind = value.str.extract(LAPS_BEHIND_PATTERN, 1).cast(pl.Int32)
    seconds = pl.when(laps_behind.is_null()).then(value).cast(pl.Float64)
    return [seconds.alias(f"{prefix}_seconds"), laps_behind.alias(f"{prefix}_laps_behind")]


def _intervals(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        *split_gap(pl.col("interval"), "interval"),
        *split_gap(pl.col("gap_to_leader"), "gap_to_leader"),
    )


def _session_result(frame: pl.DataFrame) -> pl.DataFrame:
    """Na classificação, ``duration`` e ``gap_to_leader`` são arrays [Q1, Q2, Q3]."""

    def scalar(column: str) -> pl.Expr:
        return pl.when(~pl.col(column).str.starts_with("[")).then(pl.col(column))

    def parts(column: str, prefix: str) -> list[pl.Expr]:
        array = (
            pl.when(pl.col(column).str.starts_with("["))
            .then(pl.col(column))
            .str.json_decode(pl.List(pl.Float64))
        )
        return [
            array.list.get(part - 1, null_on_oob=True).alias(f"{prefix}_q{part}")
            for part in QUALIFYING_PARTS
        ]

    return frame.with_columns(
        *parts("duration", "duration"),
        *parts("gap_to_leader", "gap"),
        *split_gap(scalar("gap_to_leader"), "gap_to_leader"),
        scalar("duration").cast(pl.Float64).alias("duration"),
    )


_ENDPOINT_RULES: dict[str, Callable[[pl.DataFrame], pl.DataFrame]] = {
    "intervals": _intervals,
    "session_result": _session_result,
}

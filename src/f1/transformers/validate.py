"""Validação de contrato e separação de registros válidos e inválidos."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import polars as pl

from f1.exceptions import DataValidationError
from f1.schemas.endpoints import Record
from f1.schemas.silver import Contract

REJECT_REASON = "reject_reason"
NULL_KEY_REASON = "chave primária nula"
DUPLICATE_KEY_REASON = "chave primária duplicada com conteúdo divergente"


@dataclass(frozen=True, slots=True)
class SplitResult:
    """Resultado da separação de uma partição.

    Attributes:
        valid: Linhas aptas para a silver, únicas pela chave primária.
        rejected: Linhas para a quarentena, com a coluna ``reject_reason``.
        duplicates_removed: Duplicatas exatas descartadas (mesmo conteúdo em todas as colunas).
    """

    valid: pl.DataFrame
    rejected: pl.DataFrame
    duplicates_removed: int


def check_columns(records: Iterable[Record], contract: Contract) -> None:
    """Falha se o payload tiver colunas novas ou não tiver colunas obrigatórias.

    Payload vazio é válido (sessões sem dados, como ``team_radio`` em 2026).

    Raises:
        DataValidationError: Em mudança de schema da API.
    """
    present: set[str] = set()
    for record in records:
        present.update(record)
    if not present:
        return
    unexpected = present - contract.raw.keys()
    missing = contract.raw.keys() - present - contract.optional
    if unexpected or missing:
        raise DataValidationError(
            f"Mudança de schema: colunas novas={sorted(unexpected)} ausentes={sorted(missing)}"
        )


def split_valid(frame: pl.DataFrame, primary_key: Sequence[str]) -> SplitResult:
    """Deduplica e separa as linhas que violam a chave primária.

    - Chave com algum valor nulo: rejeitada.
    - Linhas idênticas: mantida uma, sem rejeição.
    - Mesma chave com conteúdo diferente: todas as ocorrências rejeitadas, porque não há
      como escolher a correta.

    Args:
        frame: Partição já normalizada.
        primary_key: Colunas da chave primária.
    """
    null_key = pl.any_horizontal(pl.col(column).is_null() for column in primary_key)
    with_key = frame.filter(~null_key)
    deduplicated = with_key.unique(maintain_order=True)
    conflicting = pl.struct(primary_key).is_duplicated()
    rejected = pl.concat(
        [
            frame.filter(null_key).with_columns(pl.lit(NULL_KEY_REASON).alias(REJECT_REASON)),
            deduplicated.filter(conflicting).with_columns(
                pl.lit(DUPLICATE_KEY_REASON).alias(REJECT_REASON)
            ),
        ]
    )
    return SplitResult(
        valid=deduplicated.filter(~conflicting),
        rejected=rejected,
        duplicates_removed=with_key.height - deduplicated.height,
    )

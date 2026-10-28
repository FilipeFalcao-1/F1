"""Pipeline de refino: bronze → silver (Parquet tipado) e quarentena."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import polars as pl

from f1.exceptions import ConfigurationError, DataValidationError, LoadError
from f1.loaders.files import Lake
from f1.repositories.catalog import Catalog, ManifestEntry
from f1.schemas.endpoints import ENDPOINTS, EndpointSpec, Partition, Scope
from f1.schemas.silver import CONTRACTS
from f1.transformers.normalize import normalize, records_to_frame
from f1.transformers.validate import check_columns, split_valid

logger = logging.getLogger(__name__)

LAYER = "silver"
RUN_ID_COLUMN = "run_id"


@dataclass(slots=True)
class RefineResult:
    """Totais de uma execução de refino."""

    partitions: int = 0
    read: int = 0
    written: int = 0
    rejected: int = 0
    duplicates_removed: int = 0
    failures: list[str] = field(default_factory=list)


class RefinePipeline:
    """Converte partições bronze em silver, isolando inválidos na quarentena.

    Uma falha de contrato afeta só a partição do endpoint: as demais seguem e a execução
    termina com erro no fim.

    Args:
        lake: Origem (bronze) e destino (silver, quarentena).
        catalog: Manifesto das execuções.
        run_id: Identificador da execução, gravado na quarentena.
        clock: Relógio UTC, injetado para testes.
    """

    def __init__(
        self, lake: Lake, catalog: Catalog, run_id: str, clock: Callable[[], datetime]
    ) -> None:
        self._lake = lake
        self._catalog = catalog
        self._run_id = run_id
        self._clock = clock

    def run(self, year: int | None = None, session_key: int | None = None) -> RefineResult:
        """Refina as partições bronze de um ano ou de uma sessão.

        O calendário (``meetings`` e ``sessions``) do ano é sempre refinado junto, porque
        os marts dependem dele; com ``session_key``, o ano vem das partições da sessão.

        Raises:
            ConfigurationError: Se nenhum (ou ambos) os filtros forem informados.
            DataValidationError: Se alguma partição falhar.
        """
        if (year is None) == (session_key is None):
            raise ConfigurationError("Informe exatamente um entre year e session_key")
        started = time.perf_counter()
        result = RefineResult()
        session_partitions = [
            (spec, partition)
            for spec in ENDPOINTS.values()
            if spec.scope is not Scope.YEAR
            for partition in self._lake.bronze_partitions(spec.name, year, session_key)
        ]
        years = {year} if year is not None else {p.year for _, p in session_partitions}
        calendar_partitions = [
            (spec, partition)
            for spec in ENDPOINTS.values()
            if spec.scope is Scope.YEAR
            for partition in self._lake.bronze_partitions(spec.name)
            if partition.year in years
        ]
        for spec, partition in calendar_partitions + session_partitions:
            self._refine_partition(spec, partition, result)
        logger.info(
            "Refino concluído partitions=%d read=%d written=%d rejected=%d duplicates=%d "
            "failures=%d duration_s=%.1f",
            result.partitions,
            result.read,
            result.written,
            result.rejected,
            result.duplicates_removed,
            len(result.failures),
            time.perf_counter() - started,
        )
        if not result.partitions and not result.failures:
            logger.warning(
                "Nenhuma partição bronze encontrada year=%s session_key=%s", year, session_key
            )
        if result.failures:
            raise DataValidationError(
                f"{len(result.failures)} partições falharam no refino: {', '.join(result.failures[:10])}"
            )
        return result

    def _refine_partition(
        self, spec: EndpointSpec, partition: Partition, result: RefineResult
    ) -> None:
        contract = CONTRACTS[spec.name]
        try:
            records = self._lake.read_bronze(spec.name, partition)
            check_columns(records, contract)
            frame = normalize(spec.name, records_to_frame(records, contract.raw), contract)
            split = split_valid(frame, spec.primary_key)
            self._lake.write_silver(spec.name, partition, split.valid)
            self._lake.write_quarantine(
                spec.name,
                partition,
                split.rejected.with_columns(pl.lit(self._run_id).alias(RUN_ID_COLUMN)),
            )
        except (DataValidationError, LoadError) as exc:
            logger.error(
                "Refino falhou endpoint=%s partition=%s error=%s", spec.name, partition.path, exc
            )
            self._record(spec, partition, "failed", error=str(exc))
            result.failures.append(f"{spec.name}/{partition.path}")
            return
        rejected = split.rejected.height
        self._record(spec, partition, "success", rows=split.valid.height, rejected=rejected)
        result.partitions += 1
        result.read += len(records)
        result.written += split.valid.height
        result.rejected += rejected
        result.duplicates_removed += split.duplicates_removed
        log = logger.warning if rejected else logger.info
        log(
            "Partição refinada endpoint=%s partition=%s read=%d written=%d rejected=%d duplicates=%d",
            spec.name,
            partition.path,
            len(records),
            split.valid.height,
            rejected,
            split.duplicates_removed,
        )

    def _record(
        self,
        spec: EndpointSpec,
        partition: Partition,
        status: str,
        rows: int | None = None,
        rejected: int | None = None,
        error: str | None = None,
    ) -> None:
        self._catalog.record(
            ManifestEntry(
                run_id=self._run_id,
                layer=LAYER,
                endpoint=spec.name,
                partition=partition,
                status=status,
                ingested_at=self._clock(),
                rows=rows,
                rejected=rejected,
                error=error,
            )
        )

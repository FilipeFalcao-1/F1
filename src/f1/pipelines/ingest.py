"""Pipeline de ingestão: OpenF1 API → bronze (JSON bruto comprimido)."""

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from f1.domain.sessions import SessionInfo
from f1.exceptions import ExtractionError, LoadError, RateLimitError
from f1.extractors.openf1 import OpenF1Extractor, parse_sessions
from f1.loaders.files import Lake
from f1.repositories.catalog import Catalog, ManifestEntry
from f1.schemas.endpoints import (
    ENDPOINTS,
    EndpointSpec,
    Partition,
    Record,
    Scope,
    endpoints_by_scope,
)

logger = logging.getLogger(__name__)

LAYER = "bronze"
SESSION_SCOPES = (Scope.SESSION, Scope.SESSION_DRIVER)


@dataclass(slots=True)
class IngestResult:
    """Totais de uma execução de ingestão."""

    partitions: int = 0
    rows: int = 0
    failures: list[str] = field(default_factory=list)
    sessions_ingested: int = 0
    sessions_skipped: int = 0


def plan_endpoints(
    session: SessionInfo,
    candidates: Iterable[EndpointSpec],
    telemetry_session_types: frozenset[str],
) -> list[EndpointSpec]:
    """Filtra os endpoints aplicáveis a uma sessão.

    Endpoints ``race_only`` só valem para corridas; a telemetria só para os tipos de
    sessão configurados.
    """
    return [
        spec
        for spec in candidates
        if (not spec.race_only or session.is_race)
        and (
            spec.scope is not Scope.SESSION_DRIVER or session.has_telemetry(telemetry_session_types)
        )
    ]


class IngestPipeline:
    """Extrai partições da API e grava no bronze, registrando cada uma no manifesto.

    Args:
        extractor: Fonte dos registros.
        lake: Destino dos arquivos bronze.
        catalog: Manifesto das execuções.
        run_id: Identificador da execução.
        clock: Relógio UTC (timezone-aware), injetado para testes.
        telemetry_session_types: Tipos de sessão com ``car_data``/``location``.
    """

    def __init__(
        self,
        extractor: OpenF1Extractor,
        lake: Lake,
        catalog: Catalog,
        run_id: str,
        clock: Callable[[], datetime],
        telemetry_session_types: frozenset[str],
    ) -> None:
        self._extractor = extractor
        self._lake = lake
        self._catalog = catalog
        self._run_id = run_id
        self._clock = clock
        self._telemetry_types = telemetry_session_types

    def ingest_calendar(self, year: int, result: IngestResult | None = None) -> list[SessionInfo]:
        """Ingere ``meetings`` e ``sessions`` do ano e devolve as sessões.

        Raises:
            ExtractionError: Se o calendário não puder ser obtido (sem ele não há o que ingerir).
        """
        result = result if result is not None else IngestResult()
        partition = Partition(year=year)
        records: dict[str, list[Record]] = {}
        for name in ("meetings", "sessions"):
            records[name] = self._ingest_partition(ENDPOINTS[name], partition, result)
        if result.failures:
            raise ExtractionError(f"Falha ao ingerir o calendário de {year}: {result.failures}")
        return parse_sessions(records["sessions"])

    def ingest_session_key(
        self,
        session_key: int,
        endpoints: Sequence[EndpointSpec] | None = None,
        with_telemetry: bool = False,
    ) -> IngestResult:
        """Ingere uma sessão pelo ``session_key`` (busca os metadados na API).

        Args:
            session_key: Sessão a ingerir.
            endpoints: Restringe os endpoints; ``None`` usa todos os de sessão.
            with_telemetry: Inclui ``car_data`` e ``location`` quando ``endpoints`` é ``None``.

        Raises:
            ExtractionError: Se alguma partição falhar (as demais são gravadas mesmo assim).
        """
        session = self._extractor.session_info(session_key)
        result = IngestResult()
        reason = session.skip_reason(self._clock())
        if reason:
            logger.warning("Sessão pulada session_key=%d motivo=%s", session_key, reason)
            result.sessions_skipped += 1
            return result
        candidates = endpoints or _session_endpoints(with_telemetry)
        self._ingest_session(
            session, plan_endpoints(session, candidates, self._telemetry_types), result
        )
        return _finish(result)

    def ingest_year(
        self, year: int, with_telemetry: bool = False, force: bool = False
    ) -> IngestResult:
        """Backfill incremental do ano: calendário e sessões encerradas ainda não ingeridas.

        Args:
            year: Temporada.
            with_telemetry: Inclui ``car_data`` e ``location``.
            force: Reingere sessões já completas no manifesto.

        Raises:
            ExtractionError: Se alguma partição falhar.
        """
        started = time.perf_counter()
        result = IngestResult()
        sessions = self.ingest_calendar(year, result)
        completed = {} if force else self._catalog.completed_endpoints(year)
        now = self._clock()
        logger.info(
            "Ingestão do ano iniciada year=%d sessions=%d force=%s", year, len(sessions), force
        )
        for session in sorted(sessions, key=lambda item: item.date_start):
            planned = plan_endpoints(
                session, _session_endpoints(with_telemetry), self._telemetry_types
            )
            reason = session.skip_reason(now)
            if reason is None and {spec.name for spec in planned} <= completed.get(
                session.session_key, set()
            ):
                reason = "já ingerida"
            if reason:
                logger.info("Sessão pulada session_key=%d motivo=%s", session.session_key, reason)
                result.sessions_skipped += 1
                continue
            self._ingest_session(session, planned, result)
        logger.info(
            "Ingestão do ano concluída year=%d ingested=%d skipped=%d rows=%d failures=%d duration_s=%.1f",
            year,
            result.sessions_ingested,
            result.sessions_skipped,
            result.rows,
            len(result.failures),
            time.perf_counter() - started,
        )
        return _finish(result)

    def _ingest_session(
        self, session: SessionInfo, planned: Sequence[EndpointSpec], result: IngestResult
    ) -> None:
        started = time.perf_counter()
        logger.info(
            "Sessão iniciada session_key=%d type=%s name=%s endpoints=%d",
            session.session_key,
            session.session_type,
            session.session_name,
            len(planned),
        )
        partition = Partition(year=session.year, session_key=session.session_key)
        drivers: list[Record] | None = None
        for spec in planned:
            if spec.scope is Scope.SESSION:
                records = self._ingest_partition(spec, partition, result)
                if spec.name == "drivers":
                    drivers = records
                continue
            if drivers is None:
                drivers = self._extractor.extract(ENDPOINTS["drivers"], partition)
            for driver_number in _driver_numbers(drivers):
                self._ingest_partition(
                    spec,
                    Partition(session.year, session.session_key, driver_number),
                    result,
                )
        result.sessions_ingested += 1
        logger.info(
            "Sessão concluída session_key=%d duration_s=%.1f",
            session.session_key,
            time.perf_counter() - started,
        )

    def _ingest_partition(
        self, spec: EndpointSpec, partition: Partition, result: IngestResult
    ) -> list[Record]:
        started = time.perf_counter()
        try:
            records = self._extractor.extract(spec, partition)
            self._lake.write_bronze(spec.name, partition, records)
        except (ExtractionError, LoadError) as exc:
            logger.error(
                "Partição falhou endpoint=%s partition=%s error=%s", spec.name, partition.path, exc
            )
            self._record(spec, partition, "failed", error=str(exc))
            result.failures.append(f"{spec.name}/{partition.path}")
            if isinstance(exc, RateLimitError):
                raise
            return []
        self._record(spec, partition, "success", rows=len(records))
        result.partitions += 1
        result.rows += len(records)
        logger.info(
            "Partição gravada endpoint=%s partition=%s rows=%d duration_s=%.2f",
            spec.name,
            partition.path,
            len(records),
            time.perf_counter() - started,
        )
        return records

    def _record(
        self,
        spec: EndpointSpec,
        partition: Partition,
        status: str,
        rows: int | None = None,
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
                error=error,
            )
        )


def _session_endpoints(with_telemetry: bool) -> tuple[EndpointSpec, ...]:
    return (
        endpoints_by_scope(*SESSION_SCOPES) if with_telemetry else endpoints_by_scope(Scope.SESSION)
    )


def _driver_numbers(drivers: Iterable[Record]) -> list[int]:
    return sorted(
        {number for record in drivers if isinstance(number := record.get("driver_number"), int)}
    )


def _finish(result: IngestResult) -> IngestResult:
    if result.failures:
        raise ExtractionError(
            f"{len(result.failures)} partições falharam: {', '.join(result.failures[:10])}"
        )
    return result

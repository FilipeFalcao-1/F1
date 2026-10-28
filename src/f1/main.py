"""Entry point da CLI ``f1`` (composition root)."""

import argparse
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import duckdb
import httpx

from f1.config.logging import configure_logging
from f1.config.settings import Settings, load_settings
from f1.exceptions import ConfigurationError, F1Error
from f1.extractors.client import OpenF1Client, RateLimiter
from f1.extractors.openf1 import OpenF1Extractor
from f1.loaders.files import Lake
from f1.pipelines.ingest import IngestPipeline
from f1.pipelines.marts import MartsPipeline
from f1.pipelines.refine import RefinePipeline
from f1.repositories.catalog import Catalog
from f1.schemas.endpoints import EndpointSpec, Scope, get_endpoints

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Relógio UTC usado pelos pipelines."""
    return datetime.now(UTC)


def session_endpoints_arg(value: str) -> tuple[EndpointSpec, ...]:
    """Converte ``--endpoints`` aceitando só endpoints de sessão (não o calendário)."""
    try:
        specs = get_endpoints(value)
    except ConfigurationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    calendar = [spec.name for spec in specs if spec.scope is Scope.YEAR]
    if calendar:
        raise argparse.ArgumentTypeError(f"use 'ingest calendar' para {calendar}")
    return specs


def build_parser() -> argparse.ArgumentParser:
    """Define os comandos da CLI."""
    parser = argparse.ArgumentParser(prog="f1", description="Pipeline de dados da OpenF1 API")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="API → bronze").add_subparsers(
        dest="target", required=True
    )
    calendar = ingest.add_parser("calendar", help="meetings e sessions de um ano")
    calendar.add_argument("--year", type=int, required=True)

    session = ingest.add_parser("session", help="uma sessão")
    session.add_argument("--session-key", type=int, required=True)
    session.add_argument("--endpoints", type=session_endpoints_arg, help="ex.: laps,stints")
    _add_telemetry_flag(session)

    year = ingest.add_parser("year", help="backfill incremental das sessões encerradas do ano")
    year.add_argument("--year", type=int, required=True)
    year.add_argument("--force", action="store_true", help="reingere sessões já completas")
    _add_telemetry_flag(year)

    latest = ingest.add_parser(
        "latest", help="sessões encerradas do ano corrente fora do manifesto"
    )
    _add_telemetry_flag(latest)

    refine = commands.add_parser("refine", help="bronze → silver")
    scope = refine.add_mutually_exclusive_group(required=True)
    scope.add_argument("--session-key", type=int)
    scope.add_argument("--year", type=int)

    marts = commands.add_parser("marts", help="silver → gold").add_subparsers(
        dest="target", required=True
    )
    marts.add_parser("build", help="recria as views silver_* e os marts gold_*")

    run = commands.add_parser("run", help="ingest year + refine + marts build")
    run.add_argument("--year", type=int, help="padrão: ano corrente")
    _add_telemetry_flag(run)
    return parser


def _add_telemetry_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--with-telemetry",
        action="store_true",
        help="inclui car_data e location (F1_TELEMETRY_SESSION_TYPES)",
    )


@contextmanager
def open_catalog(lake: Lake) -> Iterator[Catalog]:
    """Abre o DuckDB do lake e garante o fechamento."""
    lake.root.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(lake.duckdb_path)) as connection:
        yield Catalog(connection)


@contextmanager
def open_ingest(
    settings: Settings, lake: Lake, catalog: Catalog, run_id: str
) -> Iterator[IngestPipeline]:
    """Monta o pipeline de ingestão com o cliente HTTP configurado."""
    headers = {"Accept": "application/json"}
    if settings.api_token is not None:
        headers["Authorization"] = f"Bearer {settings.api_token.get_secret_value()}"
    with httpx.Client(
        base_url=settings.api_base_url, timeout=settings.http_timeout_seconds, headers=headers
    ) as http:
        client = OpenF1Client(
            http,
            RateLimiter(settings.rate_limit_per_second, settings.rate_limit_per_minute),
            max_retries=settings.max_retries,
        )
        yield IngestPipeline(
            OpenF1Extractor(client),
            lake,
            catalog,
            run_id,
            clock=utc_now,
            telemetry_session_types=settings.telemetry_session_types,
        )


def execute(args: argparse.Namespace, settings: Settings, run_id: str) -> None:
    """Despacha o comando para o pipeline correspondente."""
    lake = Lake(settings.data_dir)
    with open_catalog(lake) as catalog:
        if args.command == "refine":
            RefinePipeline(lake, catalog, run_id, utc_now).run(args.year, args.session_key)
            return
        if args.command == "marts":
            MartsPipeline(lake, catalog).build()
            return
        with open_ingest(settings, lake, catalog, run_id) as ingest:
            if args.command == "run":
                year = args.year or utc_now().year
                ingest.ingest_year(year, args.with_telemetry)
                RefinePipeline(lake, catalog, run_id, utc_now).run(year=year)
                MartsPipeline(lake, catalog).build()
            elif args.target == "calendar":
                ingest.ingest_calendar(args.year)
            elif args.target == "session":
                ingest.ingest_session_key(args.session_key, args.endpoints, args.with_telemetry)
            elif args.target == "year":
                ingest.ingest_year(args.year, args.with_telemetry, args.force)
            else:
                ingest.ingest_year(utc_now().year, args.with_telemetry)


def main(argv: list[str] | None = None) -> int:
    """Executa a CLI e devolve o código de saída (0 = sucesso)."""
    args = build_parser().parse_args(argv)
    command = " ".join(filter(None, [args.command, getattr(args, "target", None)]))
    try:
        settings = load_settings()
    except ConfigurationError:
        configure_logging("INFO", command)
        logger.exception("Configuração inválida")
        return 2
    run_id = configure_logging(settings.log_level, command)
    logger.info("Execução iniciada args=%s", vars(args))
    try:
        execute(args, settings, run_id)
    except F1Error:
        logger.exception("Execução falhou")
        return 1
    except Exception:
        logger.exception("Falha inesperada")
        return 1
    logger.info("Execução concluída status=success")
    return 0


if __name__ == "__main__":
    sys.exit(main())

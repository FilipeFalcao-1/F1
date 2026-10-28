"""Smoke test contra a API real. Rode manualmente: ``poetry run pytest -m live``."""

from datetime import UTC, datetime

import httpx
import pytest

from f1.extractors.client import OpenF1Client, RateLimiter
from f1.extractors.openf1 import OpenF1Extractor
from f1.loaders.files import Lake
from f1.pipelines.ingest import IngestPipeline
from f1.pipelines.refine import RefinePipeline
from f1.repositories.catalog import Catalog
from f1.schemas.endpoints import get_endpoints

pytestmark = pytest.mark.live


def test_sessao_real_pequena_ingere_e_refina(lake: Lake, catalog: Catalog) -> None:
    with httpx.Client(base_url="https://api.openf1.org/v1", timeout=60) as http:
        client = OpenF1Client(http, RateLimiter(3, 30), max_retries=3)
        ingest = IngestPipeline(
            OpenF1Extractor(client),
            lake,
            catalog,
            "live",
            clock=lambda: datetime.now(UTC),
            telemetry_session_types=frozenset({"Race"}),
        )
        ingest.ingest_session_key(9165, endpoints=get_endpoints("drivers,stints,session_result"))

    result = RefinePipeline(lake, catalog, "live", lambda: datetime.now(UTC)).run(session_key=9165)

    assert result.written > 0
    assert result.rejected == 0

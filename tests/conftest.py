"""Fixtures compartilhadas: API OpenF1 falsa, lake em ``tmp_path`` e catálogo em memória."""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import httpx
import pytest

from f1.extractors.client import OpenF1Client, RateLimiter
from f1.extractors.openf1 import OpenF1Extractor
from f1.loaders.files import Lake
from f1.pipelines.ingest import IngestPipeline
from f1.repositories.catalog import Catalog
from f1.schemas.endpoints import Record

FIXTURES = Path(__file__).parent / "fixtures" / "openf1"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
RUN_ID = "test-run"
TELEMETRY_TYPES = frozenset({"Race", "Qualifying"})

type Handler = Callable[[httpx.Request], httpx.Response]


class FakeOpenF1:
    """API falsa: devolve os registros das fixtures que casam com a query string.

    Imita a OpenF1 respondendo 404 ``No results found.`` quando nada casa.
    Endpoints em ``failing`` respondem com o status configurado.
    """

    def __init__(self) -> None:
        self.data: dict[str, list[Record]] = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in FIXTURES.glob("*.json")
        }
        self.failing: dict[str, int] = {}
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.rsplit("/", 1)[-1]
        params = dict(request.url.params)
        self.calls.append((endpoint, params))
        if endpoint in self.failing:
            return httpx.Response(self.failing[endpoint], json={"detail": "boom"})
        rows = [
            row
            for row in self.data.get(endpoint, [])
            if all(str(row.get(key)) == value for key, value in params.items())
        ]
        if not rows:
            return httpx.Response(404, json={"detail": "No results found."})
        return httpx.Response(200, json=rows)

    def endpoints_called(self) -> list[str]:
        return [endpoint for endpoint, _ in self.calls]


def build_client(handler: Handler, max_retries: int = 0) -> OpenF1Client:
    """Cliente real sobre ``MockTransport``, sem rate limit nem espera reais."""
    http = httpx.Client(base_url="https://api.test/v1", transport=httpx.MockTransport(handler))
    limiter = RateLimiter(1_000, 1_000, clock=lambda: 0.0, sleep=lambda _: None)
    return OpenF1Client(http, limiter, max_retries=max_retries, sleep=lambda _: None)


@pytest.fixture
def make_client() -> Callable[..., OpenF1Client]:
    return build_client


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def fake_api() -> FakeOpenF1:
    return FakeOpenF1()


@pytest.fixture
def lake(tmp_path: Path) -> Lake:
    return Lake(tmp_path / "data")


@pytest.fixture
def catalog() -> Iterator[Catalog]:
    with duckdb.connect(":memory:") as connection:
        yield Catalog(connection)


@pytest.fixture
def ingest(fake_api: FakeOpenF1, lake: Lake, catalog: Catalog) -> IngestPipeline:
    return IngestPipeline(
        OpenF1Extractor(build_client(fake_api)),
        lake,
        catalog,
        RUN_ID,
        clock=lambda: NOW,
        telemetry_session_types=TELEMETRY_TYPES,
    )

from collections.abc import Callable

import httpx
import pytest

from f1.exceptions import ExtractionError, RateLimitError
from f1.extractors.client import OpenF1Client, RateLimiter

type MakeClient = Callable[..., OpenF1Client]


def sequence(*responses: httpx.Response | Exception) -> Callable[[httpx.Request], httpx.Response]:
    """Handler que devolve (ou levanta) as respostas em ordem."""
    pending = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        item = pending.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler


def test_get_devolve_registros_e_envia_filtros(make_client: MakeClient) -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json=[{"lap_number": 1}])

    rows = make_client(handler).get("laps", {"session_key": 9165})

    assert rows == [{"lap_number": 1}]
    assert seen[0].path == "/v1/laps"
    assert seen[0].params["session_key"] == "9165"


def test_404_sem_resultados_vira_lista_vazia(make_client: MakeClient) -> None:
    client = make_client(sequence(httpx.Response(404, json={"detail": "No results found."})))

    assert client.get("starting_grid", {"session_key": 1}) == []


@pytest.mark.parametrize("status", [400, 401, 404, 422])
def test_erro_4xx_falha_sem_retry(make_client: MakeClient, status: int) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status, json={"detail": "outro erro"})

    with pytest.raises(ExtractionError, match=f"HTTP {status}"):
        make_client(handler, max_retries=3).get("laps", {})

    assert len(calls) == 1


def test_retry_em_5xx_e_timeout_ate_sucesso(make_client: MakeClient) -> None:
    client = make_client(
        sequence(
            httpx.Response(503),
            httpx.ReadTimeout("lento"),
            httpx.Response(200, json=[{"ok": True}]),
        ),
        max_retries=2,
    )

    assert client.get("laps", {}) == [{"ok": True}]


def test_retry_respeita_retry_after() -> None:
    sleeps: list[float] = []
    handler = sequence(
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        httpx.Response(200, json=[]),
    )
    http = httpx.Client(base_url="https://api.test/v1", transport=httpx.MockTransport(handler))
    limiter = RateLimiter(100, 100, clock=lambda: 0.0, sleep=lambda _: None)

    OpenF1Client(http, limiter, max_retries=2, sleep=sleeps.append).get("laps", {})

    assert sleeps == [7.0, 2.0]  # data HTTP cai no backoff exponencial (2^1)


def test_429_persistente_levanta_rate_limit_error(make_client: MakeClient) -> None:
    client = make_client(sequence(*[httpx.Response(429)] * 3), max_retries=2)

    with pytest.raises(RateLimitError, match="HTTP 429 após 3 tentativas"):
        client.get("laps", {})


def test_erro_de_conexao_persistente_preserva_causa(make_client: MakeClient) -> None:
    client = make_client(
        sequence(httpx.ConnectError("fora"), httpx.ConnectError("fora")), max_retries=1
    )

    with pytest.raises(ExtractionError, match="2 tentativas") as info:
        client.get("laps", {})

    assert isinstance(info.value.__cause__, httpx.ConnectError)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>"),
        httpx.Response(200, json={"not": "a list"}),
        httpx.Response(200, json=[1, 2]),
    ],
)
def test_resposta_fora_do_formato_falha(make_client: MakeClient, response: httpx.Response) -> None:
    with pytest.raises(ExtractionError):
        make_client(sequence(response)).get("laps", {})


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_rate_limiter_respeita_limite_por_segundo() -> None:
    clock = FakeClock()
    limiter = RateLimiter(per_second=2, per_minute=100, clock=clock, sleep=clock.sleep)

    for _ in range(3):
        limiter.acquire()

    assert clock.sleeps == [1.0]


def test_rate_limiter_respeita_limite_por_minuto() -> None:
    clock = FakeClock()
    limiter = RateLimiter(per_second=10, per_minute=3, clock=clock, sleep=clock.sleep)

    for _ in range(4):
        limiter.acquire()

    assert clock.now == pytest.approx(60.0)

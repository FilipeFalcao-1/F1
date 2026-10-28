"""Cliente HTTP da OpenF1 com rate limit, retry e backoff."""

import logging
import time
from collections import deque
from collections.abc import Callable, Mapping

import httpx

from f1.exceptions import ExtractionError, RateLimitError
from f1.schemas.endpoints import Record

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
NO_RESULTS_DETAIL = "No results found."
MAX_BACKOFF_SECONDS = 60.0

type QueryParams = Mapping[str, str | int]


class RateLimiter:
    """Limita requisições por janela deslizante de 1 s e de 60 s.

    A OpenF1 impõe dois limites simultâneos (por segundo e por minuto), então a
    janela deslizante com o histórico das chamadas é mais simples que dois token buckets.
    """

    def __init__(
        self,
        per_second: int,
        per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._limits = ((1.0, per_second), (60.0, per_minute))
        self._calls: deque[float] = deque()
        self._clock = clock
        self._sleep = sleep

    def acquire(self) -> None:
        """Bloqueia até que uma nova requisição caiba nos dois limites."""
        while (wait := self._wait_time(self._clock())) > 0:
            self._sleep(wait)
        self._calls.append(self._clock())

    def _wait_time(self, now: float) -> float:
        while self._calls and now - self._calls[0] >= 60.0:
            self._calls.popleft()
        wait = 0.0
        for window, limit in self._limits:
            recent = [call for call in self._calls if now - call < window]
            if len(recent) >= limit:
                wait = max(wait, recent[-limit] + window - now)
        return wait


class OpenF1Client:
    """Faz GET na OpenF1 e devolve a lista de registros JSON.

    Args:
        http: Cliente ``httpx`` já configurado com ``base_url``, timeout e headers.
        rate_limiter: Limitador aplicado antes de cada tentativa.
        max_retries: Novas tentativas para 429, 5xx, timeout e erro de conexão.
        sleep: Função de espera (injetável para testes).
    """

    def __init__(
        self,
        http: httpx.Client,
        rate_limiter: RateLimiter,
        max_retries: int,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._rate_limiter = rate_limiter
        self._max_retries = max_retries
        self._sleep = sleep

    def get(self, endpoint: str, params: QueryParams) -> list[Record]:
        """Consulta um endpoint.

        Args:
            endpoint: Nome do endpoint (``laps``, ``sessions``...).
            params: Filtros da query string.

        Returns:
            Registros devolvidos. Lista vazia quando a API responde "No results found.".

        Raises:
            RateLimitError: Se o 429 persistir depois de todas as tentativas.
            ExtractionError: Em erro não recuperável ou tentativas esgotadas.
        """
        attempts = self._max_retries + 1
        for attempt in range(1, attempts + 1):
            self._rate_limiter.acquire()
            try:
                response = self._http.get(f"/{endpoint}", params=dict(params))
            except httpx.TransportError as exc:
                if attempt == attempts:
                    raise ExtractionError(
                        f"Falha após {attempt} tentativas em {endpoint} {dict(params)}: {exc!r}"
                    ) from exc
                self._backoff(endpoint, attempt, attempts, type(exc).__name__, None)
                continue

            if response.status_code not in RETRYABLE_STATUS:
                return _parse(endpoint, params, response)
            if attempt == attempts:
                error = RateLimitError if response.status_code == 429 else ExtractionError
                raise error(
                    f"HTTP {response.status_code} após {attempt} tentativas em {endpoint} {dict(params)}"
                )
            self._backoff(
                endpoint,
                attempt,
                attempts,
                f"HTTP {response.status_code}",
                response.headers.get("Retry-After"),
            )
        raise AssertionError("inalcançável")

    def _backoff(
        self, endpoint: str, attempt: int, attempts: int, reason: str, retry_after: str | None
    ) -> None:
        delay = _retry_after_seconds(retry_after) or min(2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)
        logger.warning(
            "Retry endpoint=%s attempt=%d/%d reason=%s delay_s=%.1f",
            endpoint,
            attempt,
            attempts,
            reason,
            delay,
        )
        self._sleep(delay)


def _retry_after_seconds(value: str | None) -> float | None:
    """Interpreta ``Retry-After`` em segundos. Datas HTTP caem no backoff padrão."""
    if value is None:
        return None
    try:
        return min(max(float(value), 0.0), MAX_BACKOFF_SECONDS)
    except ValueError:
        return None


def _parse(endpoint: str, params: QueryParams, response: httpx.Response) -> list[Record]:
    if response.status_code == 404 and _is_no_results(response):
        return []
    if response.is_error:
        raise ExtractionError(
            f"HTTP {response.status_code} não recuperável em {endpoint} {dict(params)}: "
            f"{response.text[:200]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ExtractionError(f"Resposta não é JSON em {endpoint} {dict(params)}") from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ExtractionError(f"Resposta inesperada em {endpoint}: esperava lista de objetos")
    return payload


def _is_no_results(response: httpx.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("detail") == NO_RESULTS_DETAIL

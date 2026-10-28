from collections.abc import Callable

import httpx
import pytest

from f1.exceptions import ConfigurationError, ExtractionError
from f1.extractors.client import OpenF1Client
from f1.extractors.openf1 import OpenF1Extractor, parse_sessions
from f1.schemas.endpoints import ENDPOINTS, Partition


def recorder(
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, str]], Callable[[httpx.Request], httpx.Response]]:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=rows)

    return seen, handler


@pytest.mark.parametrize(
    ("endpoint", "partition", "expected"),
    [
        ("sessions", Partition(2023), {"year": "2023"}),
        ("laps", Partition(2023, 9165), {"session_key": "9165"}),
        ("car_data", Partition(2023, 9165, 1), {"session_key": "9165", "driver_number": "1"}),
    ],
)
def test_extract_usa_filtros_do_escopo(
    make_client: Callable[..., OpenF1Client],
    endpoint: str,
    partition: Partition,
    expected: dict[str, str],
) -> None:
    seen, handler = recorder([])

    OpenF1Extractor(make_client(handler)).extract(ENDPOINTS[endpoint], partition)

    assert seen == [expected]


def test_extract_falha_se_particao_nao_combina_com_escopo(
    make_client: Callable[..., OpenF1Client],
) -> None:
    extractor = OpenF1Extractor(make_client(recorder([])[1]))

    with pytest.raises(ConfigurationError, match="driver_number"):
        extractor.extract(ENDPOINTS["location"], Partition(2023, 9165))


def test_session_info_converte_registro(
    make_client: Callable[..., OpenF1Client], fake_api: object
) -> None:
    info = OpenF1Extractor(make_client(fake_api)).session_info(9165)

    assert (info.session_key, info.year, info.session_type, info.is_race) == (
        9165,
        2023,
        "Race",
        True,
    )
    assert info.date_end.tzinfo is not None


def test_session_info_inexistente(
    make_client: Callable[..., OpenF1Client], fake_api: object
) -> None:
    with pytest.raises(ExtractionError, match="não encontrada"):
        OpenF1Extractor(make_client(fake_api)).session_info(1)


def test_parse_sessions_rejeita_registro_fora_do_contrato() -> None:
    with pytest.raises(ExtractionError, match="fora do contrato"):
        parse_sessions([{"session_key": "abc"}])

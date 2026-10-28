import json
from pathlib import Path

import duckdb
import httpx
import pytest

from f1.main import build_parser, main


@pytest.fixture(autouse=True)
def _lake_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("F1_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_parser_valida_endpoints_e_exclusividade() -> None:
    parser = build_parser()

    args = parser.parse_args(["ingest", "session", "--session-key", "9165", "--endpoints", "laps"])
    assert [spec.name for spec in args.endpoints] == ["laps"]

    with pytest.raises(SystemExit):
        parser.parse_args(["ingest", "session", "--session-key", "1", "--endpoints", "lapz"])
    with pytest.raises(SystemExit):
        parser.parse_args(["ingest", "session", "--session-key", "1", "--endpoints", "meetings"])
    with pytest.raises(SystemExit):
        parser.parse_args(["refine", "--year", "2023", "--session-key", "1"])


def test_marts_build_em_lake_vazio_termina_com_sucesso(_lake_env: Path) -> None:
    assert main(["marts", "build"]) == 0
    assert (_lake_env / "f1.duckdb").exists()


def test_refine_com_bronze_invalido_retorna_1(_lake_env: Path) -> None:
    target = _lake_env / "bronze/stints/year=2023/session_key=1/data.json.gz"
    target.parent.mkdir(parents=True)
    target.write_bytes(json.dumps([]).encode())  # não é gzip

    assert main(["refine", "--year", "2023"]) == 1


def test_configuracao_invalida_retorna_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("F1_MAX_RETRIES", "-1")

    assert main(["marts", "build"]) == 2


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch, fake_api: object) -> object:
    """Faz o ``httpx.Client`` da CLI usar a API falsa, sem rate limit real."""
    real_client = httpx.Client

    def client(**kwargs: object) -> httpx.Client:
        return real_client(**kwargs, transport=httpx.MockTransport(fake_api))  # type: ignore[arg-type]

    monkeypatch.setattr("f1.main.httpx.Client", client)
    monkeypatch.setenv("F1_RATE_LIMIT_PER_SECOND", "100000")
    monkeypatch.setenv("F1_RATE_LIMIT_PER_MINUTE", "100000")
    monkeypatch.setenv("F1_API_TOKEN", "token-de-teste")
    return fake_api


@pytest.mark.parametrize(
    "argv",
    [
        ["ingest", "calendar", "--year", "2023"],
        ["ingest", "session", "--session-key", "9165", "--endpoints", "laps"],
        ["ingest", "year", "--year", "2023", "--force"],
        ["ingest", "latest"],
    ],
)
def test_comandos_de_ingestao(fake_http: object, argv: list[str]) -> None:
    assert main(argv) == 0


def test_run_executa_ingest_refine_e_marts(fake_http: object, _lake_env: Path) -> None:
    assert main(["run", "--year", "2023"]) == 0

    with duckdb.connect(str(_lake_env / "f1.duckdb"), read_only=True) as connection:
        row = connection.execute("SELECT count(*) FROM gold_race_results").fetchone()
    assert row == (3,)


def test_falha_de_extracao_retorna_1(fake_http: object) -> None:
    fake_http.failing["laps"] = 400  # type: ignore[attr-defined]

    assert main(["ingest", "session", "--session-key", "9165"]) == 1

from pathlib import Path

import pytest

from f1.config.settings import Settings, load_settings
from f1.exceptions import ConfigurationError


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # ignora um .env local
    for name in ("F1_TELEMETRY_SESSION_TYPES", "F1_RATE_LIMIT_PER_SECOND", "F1_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_dispensam_variaveis() -> None:
    settings = load_settings()

    assert settings.api_base_url == "https://api.openf1.org/v1"
    assert settings.api_token is None
    assert settings.telemetry_session_types == {"Race", "Qualifying"}
    assert (settings.rate_limit_per_second, settings.rate_limit_per_minute) == (3, 30)


def test_le_variaveis_com_prefixo_e_lista_separada_por_virgula(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("F1_TELEMETRY_SESSION_TYPES", "Race, Practice ,")
    monkeypatch.setenv("F1_DATA_DIR", "/tmp/lake")

    settings = load_settings()

    assert settings.telemetry_session_types == {"Race", "Practice"}
    assert settings.data_dir == Path("/tmp/lake")


def test_valor_invalido_falha_rapido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("F1_RATE_LIMIT_PER_SECOND", "0")

    with pytest.raises(ConfigurationError, match="rate_limit_per_second"):
        load_settings()


def test_token_nao_aparece_no_repr() -> None:
    settings = Settings(api_token="segredo")

    assert "segredo" not in repr(settings)

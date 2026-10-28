"""Settings da aplicação, lidos de variáveis de ambiente com prefixo ``F1_``."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from f1.exceptions import ConfigurationError


class Settings(BaseSettings):
    """Configuração validada na inicialização.

    Todos os campos têm default: os dados históricos da OpenF1 não exigem segredo.
    """

    model_config = SettingsConfigDict(env_prefix="F1_", env_file=".env", extra="ignore")

    api_base_url: str = "https://api.openf1.org/v1"
    api_token: SecretStr | None = None
    data_dir: Path = Path("data")
    rate_limit_per_second: int = Field(default=3, gt=0)
    rate_limit_per_minute: int = Field(default=30, gt=0)
    max_retries: int = Field(default=5, ge=0)
    http_timeout_seconds: float = Field(default=60, gt=0)
    telemetry_session_types: Annotated[frozenset[str], NoDecode] = frozenset({"Race", "Qualifying"})
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("telemetry_session_types", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Aceita ``Race,Qualifying`` (texto separado por vírgula) além de coleções."""
        if isinstance(value, str):
            return frozenset(item.strip() for item in value.split(",") if item.strip())
        return value


def load_settings() -> Settings:
    """Carrega e valida os settings, falhando rápido com erro claro.

    Returns:
        Settings validados.

    Raises:
        ConfigurationError: Se alguma variável ``F1_*`` for inválida.
    """
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigurationError(f"Configuração inválida: {exc}") from exc

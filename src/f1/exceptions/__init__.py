"""Hierarquia de exceções do projeto."""


class F1Error(Exception):
    """Base de todas as exceções do projeto."""


class ConfigurationError(F1Error):
    """Configuração ou parâmetro de execução ausente ou inválido."""


class ExtractionError(F1Error):
    """Falha ao ler da OpenF1 API."""


class RateLimitError(ExtractionError):
    """A API continuou respondendo 429 depois de esgotar as tentativas."""


class DataValidationError(F1Error):
    """Os dados violam o contrato esperado (schema, tipos ou chaves)."""


class LoadError(F1Error):
    """Falha ao gravar no data lake ou no catálogo."""

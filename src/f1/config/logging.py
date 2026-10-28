"""Configuração de logging com ``run_id`` em todos os registros."""

import logging
import uuid


class RunContextFilter(logging.Filter):
    """Injeta ``run_id`` e ``pipeline`` em todos os registros."""

    def __init__(self, run_id: str, pipeline: str) -> None:
        super().__init__()
        self.run_id = run_id
        self.pipeline = pipeline

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        record.pipeline = self.pipeline
        return True


def configure_logging(level: str, pipeline: str, run_id: str | None = None) -> str:
    """Configura o logging raiz e devolve o ``run_id`` usado.

    Args:
        level: Nível de log (``DEBUG``, ``INFO``...).
        pipeline: Nome do comando em execução, exibido em cada linha.
        run_id: Identificador da execução. Gerado se omitido.

    Returns:
        O ``run_id`` da execução.
    """
    run_id = run_id or uuid.uuid4().hex[:12]
    handler = logging.StreamHandler()
    handler.addFilter(RunContextFilter(run_id, pipeline))
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(pipeline)s run_id=%(run_id)s] %(name)s: %(message)s"
        )
    )
    logging.basicConfig(level=level, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return run_id

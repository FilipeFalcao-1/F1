import logging

import pytest

from f1.config.logging import configure_logging


def test_configure_logging_injeta_run_id(capsys: pytest.CaptureFixture[str]) -> None:
    run_id = configure_logging("INFO", "ingest year", run_id="abc123")

    logging.getLogger("f1.teste").info("mensagem rows=%d", 3)

    assert run_id == "abc123"
    assert "[ingest year run_id=abc123] f1.teste: mensagem rows=3" in capsys.readouterr().err


def test_configure_logging_gera_run_id() -> None:
    assert len(configure_logging("INFO", "refine")) == 12

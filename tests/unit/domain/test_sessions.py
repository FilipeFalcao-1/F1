from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from f1.domain.sessions import SessionInfo

NOW = datetime(2026, 1, 1, tzinfo=UTC)
RACE = SessionInfo(
    session_key=1,
    meeting_key=10,
    year=2025,
    session_type="Race",
    session_name="Sprint",
    date_start=NOW - timedelta(hours=3),
    date_end=NOW - timedelta(hours=1),
)


@pytest.mark.parametrize(
    ("session", "reason"),
    [
        (RACE, None),
        (replace(RACE, is_cancelled=True), "cancelada"),
        (replace(RACE, date_end=NOW + timedelta(minutes=1)), "não encerrada"),
    ],
)
def test_skip_reason(session: SessionInfo, reason: str | None) -> None:
    assert session.skip_reason(NOW) == reason


def test_sprint_conta_como_corrida_e_telemetria_segue_os_tipos() -> None:
    practice = replace(RACE, session_type="Practice")

    assert RACE.is_race and not practice.is_race
    assert RACE.has_telemetry(frozenset({"Race"}))
    assert not practice.has_telemetry(frozenset({"Race", "Qualifying"}))

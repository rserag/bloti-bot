from pathlib import Path

from blotibot.healthcheck import is_healthy


def test_healthcheck_accepts_fresh_heartbeat(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat"
    heartbeat.touch()
    modified_at = heartbeat.stat().st_mtime
    assert is_healthy(heartbeat, max_age_seconds=60, now=modified_at + 30)


def test_healthcheck_rejects_missing_stale_and_future_heartbeat(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat"
    assert not is_healthy(heartbeat, max_age_seconds=60, now=100)

    heartbeat.touch()
    modified_at = heartbeat.stat().st_mtime
    assert not is_healthy(heartbeat, max_age_seconds=60, now=modified_at + 61)
    assert not is_healthy(heartbeat, max_age_seconds=60, now=modified_at - 1)

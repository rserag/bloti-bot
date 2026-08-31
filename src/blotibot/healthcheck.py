"""Event-loop heartbeat used by the container health check."""

from __future__ import annotations

import os
import time
from pathlib import Path


def is_healthy(path: Path, *, max_age_seconds: float, now: float | None = None) -> bool:
    if max_age_seconds <= 0:
        return False
    try:
        modified_at = path.stat().st_mtime
    except OSError:
        return False
    checked_at = time.time() if now is None else now
    age = checked_at - modified_at
    return 0 <= age <= max_age_seconds


def main() -> None:
    path = Path(os.environ.get("HEARTBEAT_PATH", "/run/blotibot/heartbeat"))
    try:
        max_age_seconds = float(os.environ.get("HEARTBEAT_MAX_AGE_SECONDS", "60"))
    except ValueError:
        raise SystemExit(1) from None
    raise SystemExit(0 if is_healthy(path, max_age_seconds=max_age_seconds) else 1)


if __name__ == "__main__":
    main()

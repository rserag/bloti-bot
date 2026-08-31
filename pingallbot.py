"""Compatibility entry point for the original container command."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from blotibot.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()

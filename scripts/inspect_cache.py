"""Print cache status and quality metadata without dumping interval data."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Settings  # noqa: E402
from src.data.cache import EnergyCache  # noqa: E402


def main() -> int:
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    cache = EnergyCache(settings.cache_root)
    print(
        json.dumps(
            {"cache": cache.status(), "quality": cache.read_quality()},
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

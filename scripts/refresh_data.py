"""Run the same locked incremental refresh used by the Streamlit control."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Settings  # noqa: E402
from src.data.cache import EnergyCache  # noqa: E402
from src.data.sync_manager import AutoSyncManager  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a locked incremental Wattics refresh while preserving the "
            "previous valid cache if synchronization fails."
        )
    )
    parser.parse_args(argv)
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require(["WATTICS_API_TOKEN"])
    cache = EnergyCache(settings.cache_root)
    outcome = AutoSyncManager(settings, cache).ensure_fresh(
        reason="manual_cli_refresh",
        force=True,
    )
    print(
        json.dumps(
            {
                "status": outcome.get("status"),
                "synchronized": outcome.get("synchronized"),
                "last_successful_sync": outcome.get("last_successful_sync"),
                "freshness": outcome.get("freshness"),
                "failed_meter_count": outcome.get("failed_meter_count"),
                "failed_meters": outcome.get("failed_meters"),
                "last_error": outcome.get("last_error"),
            },
            indent=2,
            default=str,
        )
    )
    return 0 if outcome.get("status") in {"success", "fresh"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

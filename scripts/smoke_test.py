"""Offline deterministic smoke test over the local processed cache."""

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
from src.tools.energy_tools import EnergyTools  # noqa: E402
from src.tools.registry import ToolRegistry  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute representative deterministic tools without an LLM."
    )
    parser.add_argument("--start", required=True, help="Inclusive local YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Exclusive local YYYY-MM-DD.")
    args = parser.parse_args(argv)

    settings = Settings.from_env(PROJECT_ROOT / ".env")
    registry = ToolRegistry(EnergyTools(EnergyCache(settings.cache_root)))
    checks = {
        "organizations": registry.execute("list_organizations", {}),
        "availability": registry.execute(
            "get_data_availability",
            {"organization": None, "site": None, "meter": None},
        ),
        "consumption": registry.execute(
            "get_consumption_summary",
            {
                "organization": "Food Corp.",
                "site": None,
                "meter": None,
                "start_date": args.start,
                "end_date": args.end,
                "resolution": "daily",
            },
        ),
        "weekday_weekend": registry.execute(
            "compare_weekday_weekend",
            {
                "organization": None,
                "site": None,
                "meter": None,
                "start_date": args.start,
                "end_date": args.end,
                "include_hourly_profile": False,
            },
        ),
        "site_ranking": registry.execute(
            "rank_sites",
            {
                "organization": None,
                "site": None,
                "meter": None,
                "start_date": args.start,
                "end_date": args.end,
                "metric": "load_factor",
            },
        ),
    }
    statuses = {
        name: {
            "status": result.get("status"),
            "warning_count": len(result.get("warnings", [])),
        }
        for name, result in checks.items()
    }
    print(json.dumps(statuses, indent=2))
    return (
        0
        if all(value["status"] in {"ok", "empty"} for value in statuses.values())
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

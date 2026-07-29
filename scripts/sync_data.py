"""Discover hierarchy and incrementally synchronize supported energy data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.wattics_client import WatticsClient  # noqa: E402
from src.config import Settings  # noqa: E402
from src.data.cache import EnergyCache  # noqa: E402
from src.data.discovery import (  # noqa: E402
    TARGET_ORGANIZATIONS,
    discover_hierarchy,
)
from src.data.extraction import synchronize  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover Wattics organizations/sites/meters and synchronize documented "
            "electricity active-power observations into the local cache."
        )
    )
    parser.add_argument(
        "--organization",
        help="Exact organization name or stable API ID to synchronize after discovery.",
    )
    parser.add_argument(
        "--meter", help="Exact meter name or stable API ID to synchronize."
    )
    parser.add_argument(
        "--start",
        help="UTC start, inclusive, in YYYY-MM-DD. Defaults to 365 days before --end.",
    )
    parser.add_argument(
        "--end",
        help="UTC end, exclusive, in YYYY-MM-DD. Defaults to the current UTC time.",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Replace selected meter partitions for the requested period.",
    )
    parser.add_argument(
        "--all-accessible-organizations",
        action="store_true",
        help="Discover every accessible organization instead of the two assessment targets.",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require(["WATTICS_API_TOKEN"])
    end = _parse_utc(args.end) if args.end else datetime.now(timezone.utc)
    start = _parse_utc(args.start) if args.start else end - timedelta(days=365)
    cache = EnergyCache(settings.cache_root)
    with WatticsClient(
        settings.wattics_api_token or "",
        base_url=settings.wattics_api_base_url,
        timeout_seconds=settings.wattics_timeout_seconds,
        max_retries=settings.wattics_max_retries,
    ) as client:
        hierarchy = discover_hierarchy(
            client,
            default_timezone=settings.default_timezone,
            target_names=None
            if args.all_accessible_organizations
            else TARGET_ORGANIZATIONS,
        )
        result = synchronize(
            client,
            cache,
            hierarchy,
            start_utc=start,
            end_utc=end,
            organization=args.organization,
            meter_id=args.meter,
            full_refresh=args.full_refresh,
        )
    print(
        json.dumps(
            {
                "period_utc": {
                    "start_inclusive": start.isoformat(),
                    "end_exclusive": end.isoformat(),
                },
                "discovered": {
                    "organizations": len(hierarchy.organizations),
                    "sites": len(hierarchy.sites),
                    "meters": len(hierarchy.meters),
                    "warnings": hierarchy.warnings,
                },
                "sync": result,
            },
            indent=2,
            default=str,
        )
    )
    return 1 if result["failed_meter_count"] else 0


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Dates must use YYYY-MM-DD.") from exc
    return parsed.replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())

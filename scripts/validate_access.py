"""Validate target organization visibility without downloading energy data."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.exceptions import (  # noqa: E402
    WatticsAuthenticationError,
    WatticsError,
    WatticsPermissionError,
)
from src.api.wattics_client import WatticsClient  # noqa: E402
from src.config import ConfigurationError, Settings  # noqa: E402
from src.data.discovery import (  # noqa: E402
    validate_target_access,
)


def main() -> int:
    try:
        settings = Settings.from_env(PROJECT_ROOT / ".env")
        settings.require(["WATTICS_API_TOKEN"])
        with WatticsClient(
            settings.wattics_api_token or "",
            base_url=settings.wattics_api_base_url,
            timeout_seconds=settings.wattics_timeout_seconds,
            max_retries=settings.wattics_max_retries,
        ) as client:
            results = validate_target_access(client)
    except ConfigurationError as exc:
        print(f"CONFIGURATION ERROR: {exc}")
        return 2
    except WatticsAuthenticationError:
        print("AUTHENTICATION FAILED: the API token was rejected.")
        return 3
    except WatticsPermissionError:
        print(
            "PERMISSION DENIED: the token is valid but cannot list accessible organizations."
        )
        return 4
    except WatticsError as exc:
        print(f"API REQUEST FAILED: {exc}")
        return 5

    missing = False
    for result in results:
        target = result["target"]
        if result["status"] == "found":
            organization = result["organization"]
            print(f"FOUND: {organization['name']} (ID: {organization['id']})")
        elif result["status"] == "similar":
            organization = result["organization"]
            print(
                f"SIMILAR NAME for {target}: {organization['name']} "
                f"(ID: {organization['id']})"
            )
        else:
            # The list endpoint cannot prove whether an invisible organization exists.
            print(
                f"NOT FOUND OR NOT VISIBLE: {target}. The API did not return an exact "
                "or similar accessible organization."
            )
            missing = True
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

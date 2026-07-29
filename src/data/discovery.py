"""Dynamic organization/site/meter hierarchy discovery."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.api.wattics_client import WatticsClient
from src.data.schemas import Hierarchy, Meter, Organization, Site


TARGET_ORGANIZATIONS = ("Food Corp.", "Best Resorts Hotel")


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip()


def match_organization(
    target: str,
    organizations: Sequence[Dict[str, Any]],
    *,
    similarity_threshold: float = 0.82,
) -> Dict[str, Any]:
    """Return an exact/similar/not-found result without inventing access semantics."""
    target_normalized = normalize_name(target)
    exact = [
        row
        for row in organizations
        if normalize_name(str(row.get("name", ""))) == target_normalized
    ]
    if exact:
        return {"status": "found", "target": target, "organization": exact[0]}

    candidates = []
    for row in organizations:
        name = str(row.get("name", ""))
        score = SequenceMatcher(None, target_normalized, normalize_name(name)).ratio()
        if score >= similarity_threshold:
            candidates.append((score, row))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        score, row = candidates[0]
        return {
            "status": "similar",
            "target": target,
            "organization": row,
            "similarity": round(score, 3),
        }
    return {"status": "not_found", "target": target, "organization": None}


def validate_target_access(
    client: WatticsClient,
    targets: Iterable[str] = TARGET_ORGANIZATIONS,
) -> List[Dict[str, Any]]:
    organizations = client.list_organizations()
    return [match_organization(target, organizations) for target in targets]


def discover_hierarchy(
    client: WatticsClient,
    *,
    default_timezone: str,
    target_names: Optional[Iterable[str]] = TARGET_ORGANIZATIONS,
    accept_similar: bool = True,
) -> Hierarchy:
    """Discover accessible hierarchy, retaining API IDs exactly as strings."""
    _validate_timezone(default_timezone)
    raw_organizations = client.list_organizations()
    warnings: List[str] = []
    selected: List[Dict[str, Any]] = []

    if target_names is None:
        selected = raw_organizations
    else:
        seen = set()
        for target in target_names:
            match = match_organization(target, raw_organizations)
            if match["status"] == "found" or (
                accept_similar and match["status"] == "similar"
            ):
                row = match["organization"]
                row_id = str(row["id"])
                if row_id not in seen:
                    selected.append(row)
                    seen.add(row_id)
                if match["status"] == "similar":
                    warnings.append(
                        f"Using API organization {row['name']!r} as the similar "
                        f"match for requested {target!r}."
                    )
            else:
                warnings.append(f"Requested organization {target!r} was not found.")

    hierarchy = Hierarchy(
        discovered_at=datetime.now(timezone.utc).isoformat(), warnings=warnings
    )
    for raw_org in selected:
        organization = Organization(id=str(raw_org["id"]), name=str(raw_org["name"]))
        hierarchy.organizations.append(organization)
        for raw_site in client.list_sites(raw_org["id"]):
            site_timezone, assumed = _site_timezone(raw_site, default_timezone)
            site = Site(
                id=str(raw_site["id"]),
                name=str(raw_site["name"]),
                organization_id=organization.id,
                organization_name=organization.name,
                timezone=site_timezone,
                timezone_assumed=assumed,
            )
            hierarchy.sites.append(site)
            for raw_meter in client.list_meters(raw_org["id"], raw_site["id"]):
                # Some list deployments omit details; merge the documented get response.
                details = dict(raw_meter)
                if not any(
                    key in details
                    for key in ("process_sampling_rate_minutes", "type", "unit", "reading")
                ):
                    details.update(client.get_meter(raw_meter["id"]))
                interval = _optional_positive_int(
                    details.get("process_sampling_rate_minutes")
                    or details.get("process_sampling_rate")
                )
                hierarchy.meters.append(
                    Meter(
                        id=str(details["id"]),
                        name=str(details["name"]),
                        site_id=site.id,
                        site_name=site.name,
                        organization_id=organization.id,
                        organization_name=organization.name,
                        measurement_type=str(details.get("type") or "unknown"),
                        unit=_optional_string(details.get("unit")),
                        reading_type=_optional_string(details.get("reading")),
                        interval_minutes=interval,
                        timezone=site.timezone,
                        timezone_assumed=site.timezone_assumed,
                        reference=_optional_string(details.get("reference")),
                    )
                )
    return hierarchy


def save_hierarchy(hierarchy: Hierarchy, path: Path) -> None:
    _atomic_json_write(path, hierarchy.as_dict())


def load_hierarchy(path: Path) -> Hierarchy:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("Hierarchy metadata must be a JSON object.")
    return Hierarchy.from_dict(value)


def _site_timezone(raw_site: Dict[str, Any], default: str) -> tuple:
    candidate = raw_site.get("integration_timezone") or raw_site.get("timezone")
    if candidate:
        try:
            ZoneInfo(str(candidate))
            return str(candidate), False
        except ZoneInfoNotFoundError:
            pass
    return default, True


def _validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {value}") from exc


def _optional_positive_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _optional_string(value: Any) -> Optional[str]:
    return str(value) if value is not None and str(value).strip() else None


def _atomic_json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


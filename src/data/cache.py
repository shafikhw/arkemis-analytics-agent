"""Partitioned Parquet cache and small atomic metadata files."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd

from src.data.discovery import _atomic_json_write, load_hierarchy
from src.data.schemas import CANONICAL_COLUMNS, Hierarchy


class CacheError(RuntimeError):
    """Raised when cache contents cannot be read or written safely."""


class EnergyCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.processed_dir = self.root / "processed"
        self.metadata_dir = self.root / "metadata"

    @property
    def hierarchy_path(self) -> Path:
        return self.metadata_dir / "hierarchy.json"

    @property
    def sync_state_path(self) -> Path:
        return self.metadata_dir / "sync_state.json"

    @property
    def quality_path(self) -> Path:
        return self.metadata_dir / "quality.json"

    @property
    def failed_meters_path(self) -> Path:
        return self.metadata_dir / "failed_meters.json"

    @property
    def sync_runtime_path(self) -> Path:
        return self.metadata_dir / "sync_runtime.json"

    @property
    def sync_lock_path(self) -> Path:
        return self.metadata_dir / "sync.lock"

    def ensure_directories(self) -> None:
        for directory in (self.raw_dir, self.processed_dir, self.metadata_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def meter_path(self, meter_id: str) -> Path:
        return self.processed_dir / f"meter_{_safe_identifier(meter_id)}.parquet"

    def raw_path(self, meter_id: str, start: datetime, end: datetime) -> Path:
        name = (
            f"meter_{_safe_identifier(meter_id)}_"
            f"{start.strftime('%Y%m%dT%H%M%SZ')}_{end.strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        return self.raw_dir / name

    def write_raw(self, path: Path, payload: Any) -> None:
        _atomic_json_write(path, payload)

    def write_meter(self, meter_id: str, data: pd.DataFrame) -> None:
        self.ensure_directories()
        path = self.meter_path(meter_id)
        descriptor, temporary = tempfile.mkstemp(
            prefix=path.stem + ".", suffix=".parquet", dir=str(path.parent)
        )
        os.close(descriptor)
        try:
            data.to_parquet(temporary, index=False)
            os.replace(temporary, path)
        except Exception as exc:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise CacheError(
                f"Could not write processed meter cache: {path.name}"
            ) from exc

    def read_meter(self, meter_id: str) -> pd.DataFrame:
        path = self.meter_path(meter_id)
        if not path.exists():
            return pd.DataFrame(columns=CANONICAL_COLUMNS)
        try:
            frame = pd.read_parquet(path)
        except Exception as exc:
            raise CacheError(
                f"Could not read processed meter cache: {path.name}"
            ) from exc
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        return frame

    def read_energy(
        self,
        *,
        organization: Optional[str] = None,
        site: Optional[str] = None,
        meter: Optional[str] = None,
        start: Optional[pd.Timestamp] = None,
        end: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        paths: List[Path]
        if meter:
            meter_ids = self.resolve_entity_ids("meter", meter)
            paths = [self.meter_path(value) for value in meter_ids]
        else:
            paths = sorted(self.processed_dir.glob("meter_*.parquet"))
        frames = []
        for path in paths:
            if not path.exists():
                continue
            try:
                frame = pd.read_parquet(path)
            except Exception as exc:
                raise CacheError(f"Could not read {path.name}.") from exc
            if not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame(columns=CANONICAL_COLUMNS)
        data = pd.concat(frames, ignore_index=True)
        data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
        if organization:
            ids = self.resolve_entity_ids("organization", organization)
            data = data[data["organization_id"].astype(str).isin(ids)]
        if site:
            ids = self.resolve_entity_ids("site", site)
            data = data[data["site_id"].astype(str).isin(ids)]
        if start is not None:
            data = data[data["timestamp"] >= _as_utc(start)]
        if end is not None:
            data = data[data["timestamp"] < _as_utc(end)]
        return data.reset_index(drop=True)

    def load_hierarchy(self) -> Hierarchy:
        if not self.hierarchy_path.exists():
            raise CacheError(
                "No hierarchy cache exists. Run python scripts/sync_data.py first."
            )
        return load_hierarchy(self.hierarchy_path)

    def resolve_entity_ids(self, kind: str, value: str) -> List[str]:
        hierarchy = self.load_hierarchy()
        collection: Sequence[Any]
        if kind == "organization":
            collection = hierarchy.organizations
        elif kind == "site":
            collection = hierarchy.sites
        elif kind == "meter":
            collection = hierarchy.meters
        else:
            raise ValueError(f"Unknown entity kind: {kind}")
        text = str(value).strip()
        by_id = [item.id for item in collection if item.id == text]
        if by_id:
            return by_id
        normalized = _normalize(text)
        by_name = [
            item.id for item in collection if _normalize(item.name) == normalized
        ]
        if not by_name:
            singular = normalized[:-1] if normalized.endswith("s") else normalized
            by_name = [
                item.id
                for item in collection
                if (
                    (
                        _normalize(item.name)[:-1]
                        if _normalize(item.name).endswith("s")
                        else _normalize(item.name)
                    )
                    == singular
                )
            ]
        if not by_name:
            similar = [
                (
                    SequenceMatcher(None, normalized, _normalize(item.name)).ratio(),
                    item.id,
                )
                for item in collection
            ]
            strong = [candidate for candidate in similar if candidate[0] >= 0.9]
            strong.sort(reverse=True)
            if strong and (len(strong) == 1 or strong[0][0] - strong[1][0] >= 0.05):
                by_name = [strong[0][1]]
        if not by_name:
            raise ValueError(
                f"Unknown {kind}: {value!r}. Use a list tool to inspect names."
            )
        if len(by_name) > 1:
            raise ValueError(
                f"Ambiguous {kind} name {value!r}; use the stable entity ID instead."
            )
        return by_name

    def read_sync_state(self) -> Dict[str, Any]:
        return _read_json_object(self.sync_state_path, default={"meters": {}})

    def write_sync_state(self, state: Dict[str, Any]) -> None:
        _atomic_json_write(self.sync_state_path, state)

    def write_quality(self, report: Dict[str, Any]) -> None:
        _atomic_json_write(self.quality_path, report)

    def read_quality(self) -> Dict[str, Any]:
        return _read_json_object(self.quality_path, default={})

    def write_failed_meters(self, failures: List[Dict[str, Any]]) -> None:
        _atomic_json_write(
            self.failed_meters_path,
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "failures": failures,
            },
        )

    def read_failed_meters(self) -> List[Dict[str, Any]]:
        return list(
            _read_json_object(self.failed_meters_path, default={"failures": []}).get(
                "failures", []
            )
        )

    def write_sync_runtime(self, payload: Dict[str, Any]) -> None:
        _atomic_json_write(self.sync_runtime_path, payload)

    def read_sync_runtime(self) -> Dict[str, Any]:
        return _read_json_object(
            self.sync_runtime_path,
            default={
                "status": "never_run",
                "last_attempt": None,
                "last_error": None,
            },
        )

    def status(self) -> Dict[str, Any]:
        state = self.read_sync_state()
        updated = state.get("last_successful_sync")
        runtime = self.read_sync_runtime()
        failures = self.read_failed_meters()
        runtime_status = runtime.get("status", "never_run")
        if runtime_status == "never_run" and updated:
            runtime_status = "idle"
        latest_values = [
            value.get("latest_timestamp")
            for value in state.get("meters", {}).values()
            if value.get("latest_timestamp")
        ]
        return {
            "has_hierarchy": self.hierarchy_path.exists(),
            "processed_meter_files": len(
                list(self.processed_dir.glob("meter_*.parquet"))
            )
            if self.processed_dir.exists()
            else 0,
            "last_successful_sync": updated,
            "latest_cached_observation": max(latest_values) if latest_values else None,
            "common_cache_coverage_through": min(latest_values)
            if latest_values
            else None,
            "synchronization_status": runtime_status,
            "last_sync_attempt": runtime.get("last_attempt"),
            "last_sync_error": runtime.get("last_error"),
            "failed_meter_count": len(failures),
            "failed_meters": failures,
        }


def _safe_identifier(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value))
    if not text or text in {".", ".."}:
        raise ValueError("Entity ID cannot be represented as a cache filename.")
    return text


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _as_utc(value: pd.Timestamp) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def _read_json_object(path: Path, *, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CacheError(f"Could not read metadata file: {path.name}") from exc
    if not isinstance(value, dict):
        raise CacheError(f"Metadata file must contain a JSON object: {path.name}")
    return value

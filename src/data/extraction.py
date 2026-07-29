"""Incremental Wattics extraction and explicit power-to-energy normalization."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from src.api.wattics_client import WatticsClient
from src.data.cache import EnergyCache
from src.data.cleaning import clean_records
from src.data.discovery import save_hierarchy
from src.data.quality import data_quality_summary
from src.data.schemas import Hierarchy, Meter


SUPPORTED_POWER_FIELDS = ("total", "value")


def synchronize(
    client: WatticsClient,
    cache: EnergyCache,
    hierarchy: Hierarchy,
    *,
    start_utc: datetime,
    end_utc: datetime,
    organization: Optional[str] = None,
    meter_id: Optional[str] = None,
    full_refresh: bool = False,
) -> Dict[str, Any]:
    """Synchronize supported electricity meters; failures are isolated per meter."""
    _validate_window(start_utc, end_utc)
    cache.ensure_directories()
    save_hierarchy(hierarchy, cache.hierarchy_path)
    state = cache.read_sync_state()
    state.setdefault("meters", {})
    failures: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []

    selected = [
        meter
        for meter in hierarchy.meters
        if (organization is None or _entity_matches(meter.organization_id, meter.organization_name, organization))
        and (meter_id is None or _entity_matches(meter.id, meter.name, meter_id))
    ]
    for meter in selected:
        if meter.measurement_type.casefold() != "electricity":
            skipped.append(
                {
                    "meter_id": meter.id,
                    "meter_name": meter.name,
                    "status": "skipped",
                    "reason": (
                        f"Unsupported measurement type {meter.measurement_type!r}; "
                        "the energy cache intentionally includes electricity only."
                    ),
                }
            )
            continue
        try:
            existing = cache.read_meter(meter.id)
            fetch_segments = _segments_to_fetch(
                existing,
                start_utc,
                end_utc,
                interval_minutes=meter.interval_minutes
                or state["meters"].get(meter.id, {}).get(
                    "effective_interval_minutes"
                ),
                full_refresh=full_refresh,
            )
            if not fetch_segments:
                results.append(
                    {"meter_id": meter.id, "status": "up_to_date", "new_rows": 0}
                )
                continue
            new_frames = []
            raw_windows = 0
            effective_interval = meter.interval_minutes
            for segment_start, segment_end in fetch_segments:
                normalized, segment_windows, segment_interval = extract_meter(
                    client,
                    cache,
                    meter,
                    start_utc=segment_start,
                    end_utc=segment_end,
                )
                if not normalized.empty:
                    new_frames.append(normalized)
                raw_windows += segment_windows
                effective_interval = effective_interval or segment_interval
            if effective_interval is None and not existing.empty:
                effective_interval = int(existing["interval_minutes"].mode().iloc[0])
            if full_refresh and not existing.empty:
                timestamps = pd.to_datetime(existing["timestamp"], utc=True)
                existing = existing[
                    (timestamps < pd.Timestamp(start_utc))
                    | (timestamps >= pd.Timestamp(end_utc))
                ]
            frames = [frame for frame in [existing, *new_frames] if not frame.empty]
            combined = (
                pd.concat(frames, ignore_index=True)
                if frames
                else pd.DataFrame()
            )
            cleaned = clean_records(combined)
            cache.write_meter(meter.id, cleaned.data)
            if not cleaned.conflicts.empty:
                conflict_path = cache.metadata_dir / f"conflicts_meter_{meter.id}.parquet"
                cleaned.conflicts.to_parquet(conflict_path, index=False)
            latest_timestamp = (
                cleaned.data["timestamp"].max().isoformat()
                if not cleaned.data.empty
                else None
            )
            earliest_timestamp = (
                cleaned.data["timestamp"].min().isoformat()
                if not cleaned.data.empty
                else None
            )
            state["meters"][meter.id] = {
                "earliest_timestamp": earliest_timestamp,
                "latest_timestamp": latest_timestamp,
                "last_successful_sync": datetime.now(timezone.utc).isoformat(),
                "row_count": len(cleaned.data),
                "effective_interval_minutes": effective_interval,
                "interval_source": (
                    "meter_metadata"
                    if meter.interval_minutes
                    else "inferred_from_timestamp_mode"
                ),
                "cleaning": cleaned.report,
            }
            cache.write_sync_state(state)
            results.append(
                {
                    "meter_id": meter.id,
                    "status": "success",
                    "new_rows": sum(len(frame) for frame in new_frames),
                    "cached_rows": len(cleaned.data),
                    "raw_windows": raw_windows,
                    "latest_timestamp": latest_timestamp,
                    "effective_interval_minutes": effective_interval,
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "meter_id": meter.id,
                    "meter_name": meter.name,
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                }
            )

    cache.write_failed_meters(failures)
    all_data = cache.read_energy()
    combined_cleaning = {
        "exact_duplicate_count": sum(
            int(value.get("cleaning", {}).get("exact_duplicate_count", 0))
            for value in state["meters"].values()
        ),
        "conflicting_duplicate_key_count": sum(
            int(value.get("cleaning", {}).get("conflicting_duplicate_key_count", 0))
            for value in state["meters"].values()
        ),
        "invalid_record_count": sum(
            int(value.get("cleaning", {}).get("invalid_record_count", 0))
            for value in state["meters"].values()
        ),
    }
    quality = data_quality_summary(all_data, cleaning_report=combined_cleaning)
    cache.write_quality(quality)
    if results and not failures:
        state["last_successful_sync"] = datetime.now(timezone.utc).isoformat()
        cache.write_sync_state(state)
    return {
        "selected_meter_count": len(selected),
        "successful_meter_count": sum(
            row["status"] in {"success", "up_to_date"} for row in results
        ),
        "skipped_meter_count": len(skipped),
        "failed_meter_count": len(failures),
        "meters": results,
        "skipped_meters": skipped,
        "failures": failures,
        "quality": quality,
    }


def extract_meter(
    client: WatticsClient,
    cache: EnergyCache,
    meter: Meter,
    *,
    start_utc: datetime,
    end_utc: datetime,
) -> Tuple[pd.DataFrame, int, Optional[int]]:
    records: List[Dict[str, Any]] = []
    raw_rows: List[Dict[str, Any]] = []
    windows = 0
    for window_start, window_end in _windows(start_utc, end_utc):
        raw = client.get_raw_data(
            meter.id,
            start_utc=window_start,
            end_utc=window_end,
            data_type="active_power",
            show_phases=False,
            detailed=True,
        )
        cache.write_raw(cache.raw_path(meter.id, window_start, window_end), raw)
        raw_rows.extend(raw)
        windows += 1
    interval = meter.interval_minutes or infer_interval_minutes(raw_rows)
    if raw_rows and not interval:
        raise ValueError(
            "Meter interval is absent and could not be inferred consistently from timestamps."
        )
    effective_meter = replace(meter, interval_minutes=interval)
    if raw_rows:
        records.extend(normalize_active_power(raw_rows, effective_meter))
    return pd.DataFrame.from_records(records), windows, interval


def normalize_active_power(rows: Iterable[Dict[str, Any]], meter: Meter) -> List[Dict[str, Any]]:
    """Convert documented Wattics active power in W to interval kWh.

    The conversion is valid only because the meter's native interval is known:
    energy_kWh = average_power_W * interval_minutes / 60 / 1000.
    """
    if not meter.interval_minutes or meter.interval_minutes <= 0:
        raise ValueError("A positive meter interval is required to integrate power.")
    extracted_at = datetime.now(timezone.utc).isoformat()
    normalized = []
    for index, row in enumerate(rows):
        value = _extract_total(row)
        timestamp = pd.to_datetime(row.get("timestamp"), utc=True, errors="coerce")
        if pd.isna(timestamp):
            # Keep it in the pipeline so cleaning records an invalid timestamp.
            timestamp_value = row.get("timestamp")
        else:
            timestamp_value = timestamp.isoformat()
        demand_kw = value / 1000.0 if value is not None else math.nan
        energy_kwh = (
            demand_kw * (meter.interval_minutes / 60.0)
            if value is not None
            else math.nan
        )
        normalized.append(
            {
                "timestamp": timestamp_value,
                "organization_id": meter.organization_id,
                "organization_name": meter.organization_name,
                "site_id": meter.site_id,
                "site_name": meter.site_name,
                "meter_id": meter.id,
                "meter_name": meter.name,
                "energy_kwh": energy_kwh,
                "demand_kw": demand_kw,
                "demand_source": "derived_from_documented_active_power_w",
                "measurement_type": "electricity_active_power",
                "original_value": value,
                "original_unit": "W",
                "interval_minutes": meter.interval_minutes,
                "timezone": meter.timezone,
                "timezone_assumed": meter.timezone_assumed,
                "source": "wattics_api_v1_raw_data_active_power",
                "extraction_timestamp": extracted_at,
            }
        )
    return normalized


def _extract_total(row: Dict[str, Any]) -> Optional[float]:
    present = [field for field in SUPPORTED_POWER_FIELDS if field in row]
    if not present:
        raise ValueError(
            "Raw active-power row has neither documented 'total' nor fallback 'value'."
        )
    value = row[present[0]]
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Raw active-power value is not numeric.") from exc
    if not math.isfinite(parsed):
        return None
    return parsed


def infer_interval_minutes(rows: Iterable[Dict[str, Any]]) -> Optional[int]:
    """Infer a stable native interval as the mode of positive timestamp differences."""
    timestamps = pd.to_datetime(
        [row.get("timestamp") for row in rows], utc=True, errors="coerce"
    )
    valid = pd.Series(timestamps).dropna().drop_duplicates().sort_values()
    if len(valid) < 2:
        return None
    differences = valid.diff().dropna().dt.total_seconds().div(60)
    differences = differences[
        (differences > 0)
        & (differences <= 1440)
        & (differences.round(6) == differences)
    ]
    if differences.empty:
        return None
    counts = differences.astype(int).value_counts()
    candidate = int(counts.index[0])
    # Require a clear majority so gaps are not mistaken for a native interval.
    return candidate if counts.iloc[0] / len(differences) >= 0.75 else None


def _windows(start: datetime, end: datetime) -> Iterable[Tuple[datetime, datetime]]:
    cursor = start
    while cursor < end:
        boundary = min(cursor + timedelta(days=90), end)
        yield cursor, boundary
        cursor = boundary


def _validate_window(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Synchronization dates must be timezone-aware.")
    if end <= start:
        raise ValueError("Synchronization end must be after start.")


def _entity_matches(entity_id: str, name: str, requested: str) -> bool:
    text = requested.casefold().strip()
    return entity_id.casefold() == text or name.casefold() == text


def _segments_to_fetch(
    existing: pd.DataFrame,
    start: datetime,
    end: datetime,
    *,
    interval_minutes: Optional[int],
    full_refresh: bool,
) -> List[Tuple[datetime, datetime]]:
    """Return historical backfill and forward-increment segments.

    Normal incremental sync extends the cached outer boundaries. A full refresh
    re-downloads the requested period and replaces only that slice.
    """
    if full_refresh or existing.empty:
        return [(start, end)]
    timestamps = pd.to_datetime(existing["timestamp"], utc=True).dropna()
    if timestamps.empty:
        return [(start, end)]
    earliest = timestamps.min().to_pydatetime()
    latest = timestamps.max().to_pydatetime()
    interval = interval_minutes
    if not interval and "interval_minutes" in existing:
        valid_intervals = pd.to_numeric(
            existing["interval_minutes"], errors="coerce"
        ).dropna()
        if not valid_intervals.empty:
            interval = int(valid_intervals.mode().iloc[0])
    step = timedelta(minutes=int(interval or 1))
    segments: List[Tuple[datetime, datetime]] = []
    if start < earliest:
        segments.append((start, min(end, earliest)))
    forward_start = max(start, latest + step)
    if end > forward_start:
        segments.append((forward_start, end))
    return [(segment_start, segment_end) for segment_start, segment_end in segments if segment_end > segment_start]

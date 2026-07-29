"""Shared validation, completeness, and serialization helpers."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd


class AnalyticsParameterError(ValueError):
    """Raised when an analytics request is ambiguous or invalid."""


def parse_date_period(start_date: str, end_date: str) -> Tuple[date, date]:
    """Parse an inclusive start and exclusive end local-date period."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise AnalyticsParameterError("Dates must use YYYY-MM-DD format.") from exc
    if end <= start:
        raise AnalyticsParameterError("end_date must be after start_date.")
    return start, end


def filter_local_period(data: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if data.empty:
        return data.copy()
    frame = data.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    keep = pd.Series(False, index=frame.index)
    for timezone_name, indexes in frame.groupby(
        "timezone", dropna=False
    ).groups.items():
        timezone_value = timezone_name if isinstance(timezone_name, str) else "UTC"
        local_dates = (
            frame.loc[indexes, "timestamp"].dt.tz_convert(timezone_value).dt.date
        )
        keep.loc[indexes] = (local_dates >= start) & (local_dates < end)
    return frame.loc[keep].reset_index(drop=True)


def completeness(data: pd.DataFrame, start: date, end: date) -> Dict[str, Any]:
    if data.empty:
        return {
            "observation_count": 0,
            "expected_observation_count": 0,
            "completeness_ratio": None,
            "completeness_percentage": None,
            "is_partial": True,
        }
    observed_total = 0
    expected_total = 0
    for _, group in data.groupby("meter_id"):
        interval = int(group["interval_minutes"].mode().iloc[0])
        timezone_name = str(group["timezone"].iloc[0] or "UTC")
        start_local = pd.Timestamp(start).tz_localize(
            timezone_name, nonexistent="shift_forward", ambiguous="NaT"
        )
        end_local = pd.Timestamp(end).tz_localize(
            timezone_name, nonexistent="shift_forward", ambiguous="NaT"
        )
        expected = int(
            round(
                (
                    end_local.tz_convert("UTC") - start_local.tz_convert("UTC")
                ).total_seconds()
                / (interval * 60)
            )
        )
        observed = int(group.loc[group["energy_kwh"].notna(), "timestamp"].nunique())
        expected_total += max(0, expected)
        observed_total += observed
    ratio = min(1.0, observed_total / expected_total) if expected_total > 0 else None
    return {
        "observation_count": observed_total,
        "expected_observation_count": expected_total,
        "completeness_ratio": ratio,
        "completeness_percentage": ratio * 100.0 if ratio is not None else None,
        "is_partial": ratio is None or ratio < 1.0,
    }


def period_payload(start: date, end: date) -> Dict[str, str]:
    return {
        "start_date_inclusive": start.isoformat(),
        "end_date_exclusive": end.isoformat(),
    }


def empty_result(
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    message: str = "No valid observations match the requested filters and period.",
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "status": "empty",
        "message": message,
        "units": {},
        "warnings": [],
    }
    if start and end:
        result["period"] = period_payload(start, end)
    return result


def previous_equivalent_period(start: date, end: date) -> Tuple[date, date]:
    duration = end - start
    return start - duration, start


def safe_percentage_change(current: float, previous: float) -> Optional[float]:
    if previous == 0 or not math.isfinite(previous):
        return None
    return (current - previous) / previous * 100.0


def to_serializable(value: Any) -> Any:
    """Convert pandas/numpy values to JSON-safe Python values."""
    if isinstance(value, dict):
        return {str(key): to_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_serializable(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if pd.isna(value) if not isinstance(value, (str, bytes)) else False:
        return None
    return value


def data_warnings(data: pd.DataFrame, completeness_payload: Dict[str, Any]) -> list:
    warnings = []
    if completeness_payload.get("is_partial"):
        warnings.append("The requested period is partial; totals may be understated.")
    assumption_mask = data["timezone_assumed"].astype("boolean").fillna(False)
    if not data.empty and assumption_mask.any():
        zones = sorted(data.loc[assumption_mask, "timezone"].unique())
        warnings.append(
            "Source timezone was unavailable for some records; configured timezone "
            f"assumption(s) were used: {', '.join(map(str, zones))}."
        )
    topology = meter_topology_warning(data)
    if topology:
        warnings.append(topology)
    return warnings


def meter_topology_warning(data: pd.DataFrame) -> Optional[str]:
    if data.empty or "meter_id" not in data:
        return None
    meter_count = int(data["meter_id"].nunique())
    if meter_count <= 1:
        return None
    return (
        f"The selection contains {meter_count} meter streams. Wattics metadata does "
        "not expose parent/submeter topology, so summed energy or demand may "
        "double-count overlapping main and submeter measurements."
    )


def aggregate_demand_series(data: pd.DataFrame) -> Tuple[pd.Series, int]:
    """Build a coincident demand series, rejecting unsafe mixed native intervals."""
    valid = data.dropna(subset=["demand_kw"]).copy()
    if valid.empty:
        return pd.Series(dtype=float), 0
    intervals = pd.to_numeric(valid["interval_minutes"], errors="coerce").dropna()
    unique_intervals = sorted(set(int(value) for value in intervals))
    if len(unique_intervals) != 1:
        raise AnalyticsParameterError(
            "Aggregate demand is unavailable for mixed native intervals; filter to "
            "one meter or meters with a common interval."
        )
    valid["timestamp"] = pd.to_datetime(valid["timestamp"], utc=True)
    series = valid.groupby("timestamp")["demand_kw"].sum(min_count=1).sort_index()
    return series, unique_intervals[0]

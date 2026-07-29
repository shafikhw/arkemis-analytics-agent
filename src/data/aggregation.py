"""Entity-aware interval, hourly, daily, weekly, and monthly aggregation."""

from __future__ import annotations

from typing import Dict, Iterable, List

import numpy as np
import pandas as pd


RESOLUTIONS = ("native", "hourly", "daily", "weekly", "monthly")
ENTITY_COLUMNS = [
    "organization_id",
    "organization_name",
    "site_id",
    "site_name",
    "meter_id",
    "meter_name",
    "timezone",
    "interval_minutes",
]


def aggregate_energy(data: pd.DataFrame, resolution: str) -> pd.DataFrame:
    """Aggregate canonical interval energy without imputing missing observations."""
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution must be one of: {', '.join(RESOLUTIONS)}")
    if data.empty:
        return pd.DataFrame(columns=_output_columns())
    frame = data.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if resolution == "native":
        output = frame[ENTITY_COLUMNS + ["timestamp", "energy_kwh", "demand_kw"]].copy()
        output = output.rename(
            columns={
                "timestamp": "period_start",
                "energy_kwh": "total_energy_kwh",
                "demand_kw": "average_demand_kw",
            }
        )
        output["period_end"] = output["period_start"] + pd.to_timedelta(
            output["interval_minutes"], unit="m"
        )
        output["average_interval_energy_kwh"] = output["total_energy_kwh"]
        output["peak_demand_kw"] = output["average_demand_kw"]
        output["observation_count"] = output["total_energy_kwh"].notna().astype(int)
        output["expected_observation_count"] = 1
        output["completeness_ratio"] = output["observation_count"].astype(float)
        output["is_partial"] = output["completeness_ratio"] < 1
        return output[_output_columns()]

    parts: List[pd.DataFrame] = []
    for timezone_name, timezone_data in frame.groupby("timezone", dropna=False):
        if not isinstance(timezone_name, str) or not timezone_name:
            timezone_name = "UTC"
        local = timezone_data["timestamp"].dt.tz_convert(timezone_name)
        period_start_local = _floor_local(local, resolution)
        timezone_data = timezone_data.copy()
        timezone_data["_period_start"] = period_start_local.dt.tz_convert("UTC")
        timezone_data["_period_end"] = _period_end_utc(period_start_local, resolution)
        parts.append(_aggregate_groups(timezone_data))
    return pd.concat(parts, ignore_index=True)[_output_columns()]


def _aggregate_groups(frame: pd.DataFrame) -> pd.DataFrame:
    group_columns = ENTITY_COLUMNS + ["_period_start", "_period_end"]
    rows = []
    for keys, group in frame.groupby(group_columns, dropna=False, sort=True):
        values = dict(zip(group_columns, keys))
        valid_energy = group["energy_kwh"].dropna()
        valid_demand = group["demand_kw"].dropna()
        interval = int(values["interval_minutes"])
        duration_minutes = (
            pd.Timestamp(values["_period_end"]) - pd.Timestamp(values["_period_start"])
        ).total_seconds() / 60
        expected = max(1, int(round(duration_minutes / interval)))
        observed = int(valid_energy.count())
        total = float(valid_energy.sum()) if observed else np.nan
        rows.append(
            {
                **{column: values[column] for column in ENTITY_COLUMNS},
                "period_start": pd.Timestamp(values["_period_start"]),
                "period_end": pd.Timestamp(values["_period_end"]),
                "total_energy_kwh": total,
                "average_interval_energy_kwh": float(valid_energy.mean())
                if observed
                else np.nan,
                "average_demand_kw": float(valid_demand.mean())
                if not valid_demand.empty
                else np.nan,
                "peak_demand_kw": float(valid_demand.max())
                if not valid_demand.empty
                else np.nan,
                "observation_count": observed,
                "expected_observation_count": expected,
                "completeness_ratio": min(1.0, observed / expected),
                "is_partial": observed < expected,
            }
        )
    return pd.DataFrame(rows)


def _floor_local(local: pd.Series, resolution: str) -> pd.Series:
    if resolution == "hourly":
        return local.dt.floor("h")
    naive = local.dt.tz_localize(None)
    if resolution == "daily":
        starts = naive.dt.floor("D")
    elif resolution == "weekly":
        starts = naive.dt.to_period("W-SUN").dt.start_time
    elif resolution == "monthly":
        starts = naive.dt.to_period("M").dt.start_time
    else:
        raise ValueError(f"Unsupported resolution: {resolution}")
    return starts.dt.tz_localize(local.dt.tz, ambiguous="infer", nonexistent="shift_forward")


def _period_end_utc(starts: pd.Series, resolution: str) -> pd.Series:
    timezone_name = str(starts.dt.tz)
    naive = starts.dt.tz_localize(None)
    if resolution == "hourly":
        ends = naive + pd.to_timedelta(1, unit="h")
    elif resolution == "daily":
        ends = naive + pd.offsets.Day(1)
    elif resolution == "weekly":
        ends = naive + pd.offsets.Week(1)
    elif resolution == "monthly":
        ends = naive + pd.offsets.MonthBegin(1)
    else:
        raise ValueError(f"Unsupported resolution: {resolution}")
    localized = ends.dt.tz_localize(
        timezone_name, ambiguous="infer", nonexistent="shift_forward"
    )
    return localized.dt.tz_convert("UTC")


def _output_columns() -> List[str]:
    return ENTITY_COLUMNS + [
        "period_start",
        "period_end",
        "total_energy_kwh",
        "average_interval_energy_kwh",
        "average_demand_kw",
        "peak_demand_kw",
        "observation_count",
        "expected_observation_count",
        "completeness_ratio",
        "is_partial",
    ]

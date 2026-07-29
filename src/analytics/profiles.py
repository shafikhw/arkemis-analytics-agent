"""Local-time weekday/weekend and normalized load profiles."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from src.analytics.common import (
    completeness,
    data_warnings,
    empty_result,
    period_payload,
    safe_percentage_change,
    to_serializable,
)


def compare_weekday_weekend(
    data: pd.DataFrame, *, start, end, include_hourly_profile: bool = False
) -> Dict[str, Any]:
    if data.empty:
        return empty_result(start=start, end=end)
    annotated = _annotate_local(data)
    per_meter_daily = annotated.groupby(
        ["_local_date", "_is_weekend", "meter_id"], as_index=False
    ).agg(
        energy_kwh=("energy_kwh", "sum"),
        observations=("energy_kwh", "count"),
        expected=(
            "interval_minutes",
            lambda values: int(round(1440 / values.mode().iloc[0])),
        ),
    )
    daily = per_meter_daily.groupby(["_local_date", "_is_weekend"], as_index=False).agg(
        energy_kwh=("energy_kwh", "sum"),
        observations=("observations", "sum"),
        expected=("expected", "sum"),
    )
    daily["complete"] = daily["observations"] >= daily["expected"]
    weekday_days = daily[~daily["_is_weekend"]]
    weekend_days = daily[daily["_is_weekend"]]
    weekday_total = float(weekday_days["energy_kwh"].sum())
    weekend_total = float(weekend_days["energy_kwh"].sum())
    average_weekday = (
        float(weekday_days["energy_kwh"].mean()) if not weekday_days.empty else None
    )
    average_weekend = (
        float(weekend_days["energy_kwh"].mean()) if not weekend_days.empty else None
    )
    quality = completeness(data, start, end)
    result = {
        "status": "ok",
        "period": period_payload(start, end),
        "weekday_total_kwh": weekday_total,
        "weekend_total_kwh": weekend_total,
        "average_weekday_consumption_kwh": average_weekday,
        "average_weekend_day_consumption_kwh": average_weekend,
        "percentage_difference_average_day": safe_percentage_change(
            average_weekend, average_weekday
        )
        if average_weekend is not None and average_weekday is not None
        else None,
        "complete_weekday_count": int(weekday_days["complete"].sum()),
        "complete_weekend_day_count": int(weekend_days["complete"].sum()),
        "units": {
            "consumption": "kWh",
            "percentage_difference": "percent; weekend relative to weekday",
        },
        "classification": "Local operational dates; Saturday and Sunday are weekend.",
        "data_completeness": quality,
        "warnings": data_warnings(data, quality),
    }
    if include_hourly_profile:
        hourly = (
            annotated.groupby(["_is_weekend", "_local_hour"])["energy_kwh"]
            .mean()
            .reset_index()
        )
        result["hourly_profile"] = [
            {
                "day_type": "weekend" if row["_is_weekend"] else "weekday",
                "local_hour": int(row["_local_hour"]),
                "average_interval_energy_kwh": float(row["energy_kwh"]),
            }
            for _, row in hourly.iterrows()
        ]
    return to_serializable(result)


def load_profile(
    data: pd.DataFrame,
    *,
    start,
    end,
    normalized: bool = False,
) -> Dict[str, Any]:
    if data.empty:
        return empty_result(start=start, end=end)
    annotated = _annotate_local(data)
    grouped = annotated.groupby("_local_hour")["energy_kwh"].mean()
    denominator = grouped.sum()
    rows = []
    for hour, value in grouped.items():
        rows.append(
            {
                "local_hour": int(hour),
                "average_interval_energy_kwh": float(value),
                "profile_share": float(value / denominator)
                if normalized and denominator
                else None,
            }
        )
    quality = completeness(data, start, end)
    return to_serializable(
        {
            "status": "ok",
            "period": period_payload(start, end),
            "normalized": normalized,
            "profile": rows,
            "units": {
                "average_interval_energy": "kWh/interval",
                "profile_share": "ratio",
            },
            "data_completeness": quality,
            "warnings": data_warnings(data, quality),
        }
    )


def _annotate_local(data: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for timezone_name, group in data.groupby("timezone"):
        temporary = group.copy()
        local = pd.to_datetime(temporary["timestamp"], utc=True).dt.tz_convert(
            str(timezone_name)
        )
        temporary["_local_date"] = local.dt.date
        temporary["_local_hour"] = local.dt.hour
        temporary["_is_weekend"] = local.dt.dayofweek >= 5
        parts.append(temporary)
    return pd.concat(parts, ignore_index=True)

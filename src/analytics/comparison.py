"""Period and entity comparisons."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from src.analytics.common import (
    aggregate_demand_series,
    completeness,
    data_warnings,
    empty_result,
    meter_topology_warning,
    period_payload,
    safe_percentage_change,
    to_serializable,
)


def compare_period_values(
    current: pd.DataFrame,
    previous: pd.DataFrame,
    *,
    current_start,
    current_end,
    previous_start,
    previous_end,
) -> Dict[str, Any]:
    if current.empty and previous.empty:
        return empty_result(
            start=current_start,
            end=current_end,
            message="Neither comparison period has valid observations.",
        )
    current_total = float(current["energy_kwh"].dropna().sum())
    previous_total = float(previous["energy_kwh"].dropna().sum())
    current_quality = completeness(current, current_start, current_end)
    previous_quality = completeness(previous, previous_start, previous_end)
    warnings = data_warnings(current, current_quality) + data_warnings(
        previous, previous_quality
    )
    if previous_total == 0:
        warnings.append(
            "Percentage change is unavailable because previous-period consumption is zero."
        )
    return to_serializable(
        {
            "status": "ok",
            "metric": "total_energy",
            "unit": "kWh",
            "current_period": {
                "period": period_payload(current_start, current_end),
                "value_kwh": current_total,
                "data_completeness": current_quality,
            },
            "previous_period": {
                "period": period_payload(previous_start, previous_end),
                "value_kwh": previous_total,
                "data_completeness": previous_quality,
            },
            "absolute_difference_kwh": current_total - previous_total,
            "percentage_difference": safe_percentage_change(
                current_total, previous_total
            ),
            "warnings": list(dict.fromkeys(warnings)),
        }
    )


def compare_entity_metric(
    data: pd.DataFrame,
    *,
    entity_kind: str,
    start,
    end,
    metric: str,
) -> Dict[str, Any]:
    id_column = f"{entity_kind}_id"
    name_column = f"{entity_kind}_name"
    if id_column not in data or name_column not in data:
        raise ValueError("entity_kind must be organization or site.")
    if data.empty:
        return empty_result(start=start, end=end)
    rows = []
    for (entity_id, entity_name), group in data.groupby([id_column, name_column]):
        quality = completeness(group, start, end)
        total = float(group["energy_kwh"].dropna().sum())
        local_days = _local_day_count(group)
        value: float | None
        unit: str
        if metric == "total_consumption":
            value, unit = total, "kWh"
        elif metric == "average_daily_consumption":
            value, unit = (total / local_days if local_days else None), "kWh/day"
        elif metric == "load_factor":
            demand, _ = aggregate_demand_series(group)
            peak = demand.max() if not demand.empty else None
            average = demand.mean() if not demand.empty else None
            value = float(average / peak) if peak and peak > 0 else None
            unit = "ratio"
        elif metric == "completeness":
            value, unit = quality["completeness_ratio"], "ratio"
        elif metric == "weekday_weekend_ratio":
            weekday, weekend = _weekday_weekend_daily_average(group)
            value = weekday / weekend if weekend and weekend > 0 else None
            unit = "ratio"
        else:
            raise ValueError(
                "metric must be total_consumption, average_daily_consumption, "
                "load_factor, completeness, or weekday_weekend_ratio."
            )
        rows.append(
            {
                f"{entity_kind}_id": str(entity_id),
                f"{entity_kind}_name": str(entity_name),
                "value": value,
                "unit": unit,
                "data_completeness": quality,
            }
        )
    warnings = []
    if metric in {"total_consumption", "average_daily_consumption"}:
        warnings.append(
            "Consumption is scale-dependent and does not establish energy efficiency."
        )
    topology = meter_topology_warning(data)
    if topology:
        warnings.append(topology)
    return to_serializable(
        {
            "status": "ok",
            "comparison_type": "absolute_consumption"
            if metric in {"total_consumption", "average_daily_consumption"}
            else "operational_profile",
            "entity_kind": entity_kind,
            "metric": metric,
            "period": period_payload(start, end),
            "entities": rows,
            "warnings": warnings,
        }
    )


def _local_day_count(group: pd.DataFrame) -> int:
    count = 0
    for timezone_name, timezone_data in group.groupby("timezone"):
        local = pd.to_datetime(timezone_data["timestamp"], utc=True).dt.tz_convert(
            str(timezone_name)
        )
        count += local.dt.date.nunique()
    return count


def _weekday_weekend_daily_average(group: pd.DataFrame):
    day_totals = []
    for timezone_name, timezone_data in group.groupby("timezone"):
        local = pd.to_datetime(timezone_data["timestamp"], utc=True).dt.tz_convert(
            str(timezone_name)
        )
        temporary = timezone_data.copy()
        temporary["_date"] = local.dt.date
        temporary["_weekend"] = local.dt.dayofweek >= 5
        day_totals.append(
            temporary.groupby(["_date", "_weekend"])["energy_kwh"].sum().reset_index()
        )
    if not day_totals:
        return None, None
    daily = pd.concat(day_totals, ignore_index=True)
    weekday = daily.loc[~daily["_weekend"], "energy_kwh"].mean()
    weekend = daily.loc[daily["_weekend"], "energy_kwh"].mean()
    return weekday, weekend

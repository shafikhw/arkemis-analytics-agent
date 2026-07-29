"""Site ranking with explicit metric direction and limitations."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from src.analytics.common import (
    aggregate_demand_series,
    completeness,
    empty_result,
    meter_topology_warning,
    period_payload,
    to_serializable,
)

METRIC_DIRECTIONS = {
    "total_consumption": "descending",
    "average_daily_consumption": "descending",
    "load_factor": "descending",
    "completeness": "descending",
}


def rank_sites(data: pd.DataFrame, *, start, end, metric: str) -> Dict[str, Any]:
    if metric not in METRIC_DIRECTIONS:
        raise ValueError(f"metric must be one of: {', '.join(METRIC_DIRECTIONS)}")
    if data.empty:
        return empty_result(start=start, end=end)
    rows = []
    for (site_id, site_name, organization_id, organization_name), group in data.groupby(
        ["site_id", "site_name", "organization_id", "organization_name"]
    ):
        quality = completeness(group, start, end)
        value: float | None
        unit: str
        if metric == "total_consumption":
            value, unit = float(group["energy_kwh"].sum()), "kWh"
        elif metric == "average_daily_consumption":
            dates = _local_dates(group)
            value = float(group["energy_kwh"].sum() / len(dates)) if dates else None
            unit = "kWh/day"
        elif metric == "load_factor":
            demand, _ = aggregate_demand_series(group)
            if demand.empty:
                value = None
            else:
                peak = float(demand.max())
                value = float(demand.mean() / peak) if peak > 0 else None
            unit = "ratio"
        else:
            value, unit = quality["completeness_ratio"], "ratio"
        rows.append(
            {
                "site_id": str(site_id),
                "site_name": str(site_name),
                "organization_id": str(organization_id),
                "organization_name": str(organization_name),
                "metric_value": value,
                "unit": unit,
                "data_completeness": quality,
            }
        )
    rows.sort(
        key=lambda row: (
            row["metric_value"] is not None,
            row["metric_value"] if row["metric_value"] is not None else float("-inf"),
        ),
        reverse=True,
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    limitation = (
        "Raw consumption is scale-dependent; this ranking does not establish efficiency."
        if metric in {"total_consumption", "average_daily_consumption"}
        else "Rankings compare operational data only and may be affected by incomplete data."
    )
    topology = meter_topology_warning(data)
    warnings = [topology] if topology else []
    return to_serializable(
        {
            "status": "ok",
            "period": period_payload(start, end),
            "ranking_metric": metric,
            "ranking_direction": METRIC_DIRECTIONS[metric],
            "ranked_sites": rows,
            "justification_or_limitation": limitation,
            "warnings": warnings,
        }
    )


def _local_dates(group: pd.DataFrame) -> set:
    dates = set()
    for timezone_name, timezone_data in group.groupby("timezone"):
        local = pd.to_datetime(timezone_data["timestamp"], utc=True).dt.tz_convert(
            str(timezone_name)
        )
        dates.update(local.dt.date.tolist())
    return dates

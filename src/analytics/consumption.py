"""Total and average consumption."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from src.analytics.common import (
    completeness,
    data_warnings,
    empty_result,
    period_payload,
    to_serializable,
)
from src.data.aggregation import aggregate_energy


def consumption_summary(
    data: pd.DataFrame,
    *,
    start,
    end,
    resolution: str,
) -> Dict[str, Any]:
    if data.empty or data["energy_kwh"].dropna().empty:
        return empty_result(start=start, end=end)
    valid = data[data["energy_kwh"].notna()].copy()
    quality = completeness(data, start, end)
    aggregated = aggregate_energy(valid, resolution)
    series = []
    if resolution != "native":
        for _, row in aggregated.head(500).iterrows():
            series.append(
                {
                    "period_start": row["period_start"],
                    "period_end": row["period_end"],
                    "organization_id": row["organization_id"],
                    "organization_name": row["organization_name"],
                    "site_id": row["site_id"],
                    "site_name": row["site_name"],
                    "meter_id": row["meter_id"],
                    "meter_name": row["meter_name"],
                    "total_energy_kwh": row["total_energy_kwh"],
                    "completeness_ratio": row["completeness_ratio"],
                    "is_partial": row["is_partial"],
                }
            )
    series_truncated = resolution != "native" and len(aggregated) > 500
    result: Dict[str, Any] = {
        "status": "ok",
        "period": period_payload(start, end),
        "resolution": resolution,
        "total_energy_kwh": float(valid["energy_kwh"].sum()),
        "average_interval_energy_kwh": float(valid["energy_kwh"].mean()),
        "average_demand_kw": float(valid["demand_kw"].mean())
        if valid["demand_kw"].notna().any()
        else None,
        "units": {
            "total_energy": "kWh",
            "average_interval_energy": "kWh/interval",
            "average_demand": "kW",
        },
        "data_completeness": quality,
        "warnings": data_warnings(data, quality),
        "series_count": len(aggregated),
        "series_truncated": series_truncated,
        "series": series,
    }
    if resolution == "native":
        result["warnings"].append(
            "Native interval rows are withheld from tool output so raw data is not sent to the LLM."
        )
    elif series_truncated:
        result["warnings"].append(
            "The aggregate series was truncated to 500 records; summary values cover the full selection."
        )
    return to_serializable(result)

"""Load factor calculation."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from src.analytics.common import (
    aggregate_demand_series,
    completeness,
    data_warnings,
    empty_result,
    period_payload,
    to_serializable,
)


def calculate_load_factor(data: pd.DataFrame, *, start, end) -> Dict[str, Any]:
    demand, interval = aggregate_demand_series(data)
    if demand.empty:
        return empty_result(
            start=start, end=end, message="Demand is unavailable for this selection."
        )
    peak = float(demand.max())
    average = float(demand.mean())
    quality = completeness(data, start, end)
    warnings = data_warnings(data, quality)
    if peak <= 0:
        factor = None
        warnings.append("Load factor is unavailable because peak demand is zero.")
    else:
        factor = average / peak
    return to_serializable(
        {
            "status": "ok",
            "period": period_payload(start, end),
            "average_demand_kw": average,
            "peak_demand_kw": peak,
            "load_factor": factor,
            "load_factor_percentage": factor * 100.0 if factor is not None else None,
            "unit": "ratio",
            "formula": "average_demand_kw / peak_demand_kw",
            "demand_aggregation": {
                "method": "coincident_sum_by_timestamp",
                "meter_count": int(data["meter_id"].nunique()),
                "common_interval_minutes": interval,
            },
            "data_completeness": quality,
            "warnings": warnings,
        }
    )

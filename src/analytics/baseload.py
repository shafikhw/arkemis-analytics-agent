"""Robust percentile baseload estimate."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from src.analytics.common import (
    completeness,
    data_warnings,
    empty_result,
    period_payload,
    to_serializable,
)


def estimate_baseload(
    data: pd.DataFrame,
    *,
    start,
    end,
    group_by: str = "site",
    percentile: float = 10.0,
    minimum_observations: int = 96,
) -> Dict[str, Any]:
    if not 0 < percentile < 50:
        raise ValueError("percentile must be greater than 0 and less than 50.")
    if minimum_observations < 4:
        raise ValueError("minimum_observations must be at least 4.")
    if data.empty or data["demand_kw"].dropna().empty:
        return empty_result(start=start, end=end)
    id_column = f"{group_by}_id"
    name_column = f"{group_by}_name"
    if id_column not in data or name_column not in data:
        raise ValueError("group_by must be site or meter.")

    estimates = []
    warnings = []
    for (entity_id, entity_name), group in data.groupby([id_column, name_column]):
        meter_estimates: List[Dict[str, Any]] = []
        reliable = True
        for (meter_id, meter_name), meter_data in group.groupby(
            ["meter_id", "meter_name"]
        ):
            demand = meter_data["demand_kw"].dropna()
            if demand.empty:
                continue
            baseline_kw = float(demand.quantile(percentile / 100.0))
            interval_hours = meter_data["interval_minutes"].astype(float) / 60.0
            baseline_energy = (
                meter_data["demand_kw"].clip(upper=baseline_kw) * interval_hours
            ).sum()
            total_energy = meter_data["energy_kwh"].sum()
            observation_count = int(demand.count())
            meter_reliable = observation_count >= minimum_observations
            reliable = reliable and meter_reliable
            meter_estimates.append(
                {
                    "meter_id": str(meter_id),
                    "meter_name": str(meter_name),
                    "baseload_estimate_kw": baseline_kw,
                    "baseload_energy_kwh": float(baseline_energy),
                    "operational_energy_above_baseline_kwh": max(
                        0.0, float(total_energy - baseline_energy)
                    ),
                    "observation_count": observation_count,
                    "reliable": meter_reliable,
                }
            )
        if not meter_estimates:
            continue
        estimate = {
            f"{group_by}_id": str(entity_id),
            f"{group_by}_name": str(entity_name),
            "baseload_estimate_kw": sum(
                row["baseload_estimate_kw"] for row in meter_estimates
            ),
            "baseload_energy_kwh": sum(
                row["baseload_energy_kwh"] for row in meter_estimates
            ),
            "operational_energy_above_baseline_kwh": sum(
                row["operational_energy_above_baseline_kwh"] for row in meter_estimates
            ),
            "reliable": reliable,
            "meters": meter_estimates,
        }
        estimates.append(estimate)
        if not reliable:
            warnings.append(
                f"{entity_name}: too few valid intervals for the configured reliability threshold."
            )
    quality = completeness(data, start, end)
    warnings.extend(data_warnings(data, quality))
    warnings.append(
        "Baseload is a statistical low-load estimate, not a directly measured physical value."
    )
    return to_serializable(
        {
            "status": "ok",
            "period": period_payload(start, end),
            "group_by": group_by,
            "method": {
                "name": "per_meter_low_percentile",
                "percentile": percentile,
                "minimum_observations": minimum_observations,
                "description": (
                    "For each meter, take the configured low percentile of valid "
                    "interval demand. Site estimates sum meter estimates; energy above "
                    "baseline is calculated interval by interval."
                ),
            },
            "units": {
                "baseload_estimate": "kW",
                "baseload_energy": "kWh",
                "operational_energy_above_baseline": "kWh",
            },
            "estimates": estimates,
            "data_completeness": quality,
            "warnings": list(dict.fromkeys(warnings)),
        }
    )

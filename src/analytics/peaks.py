"""Peak demand calculation."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from src.analytics.common import (
    aggregate_demand_series,
    completeness,
    data_warnings,
    empty_result,
    period_payload,
    to_serializable,
)


def peak_demand(data: pd.DataFrame, *, start, end) -> Dict[str, Any]:
    valid = data.dropna(subset=["demand_kw"])
    if valid.empty:
        return empty_result(
            start=start,
            end=end,
            message="No valid measured or derived demand observations are available.",
        )
    quality = completeness(data, start, end)
    meter_count = int(valid["meter_id"].nunique())
    if meter_count == 1:
        row = valid.loc[valid["demand_kw"].idxmax()]
        peak_value = float(row["demand_kw"])
        peak_timestamp = pd.Timestamp(row["timestamp"])
        interval = int(row["interval_minutes"])
        source = str(row["demand_source"])
        meter_payload: Dict[str, Optional[str]] = {
            "id": str(row["meter_id"]),
            "name": str(row["meter_name"]),
        }
        contributing_count = 1
    else:
        demand, interval = aggregate_demand_series(valid)
        peak_timestamp = pd.Timestamp(demand.idxmax())
        peak_value = float(demand.max())
        source = "coincident_sum_of_selected_meter_demand"
        meter_payload = {
            "id": None,
            "name": "Aggregate of selected meter streams",
        }
        contributing_count = int(
            valid.loc[valid["timestamp"] == peak_timestamp, "meter_id"].nunique()
        )
        row = valid.iloc[0]
    timezones = valid["timezone"].dropna().astype(str).unique().tolist()
    timezone_name = timezones[0] if len(timezones) == 1 else None
    local_timestamp = (
        peak_timestamp.tz_convert(timezone_name) if timezone_name else None
    )
    organization_ids = valid["organization_id"].astype(str).unique()
    organization_names = valid["organization_name"].astype(str).unique()
    site_ids = valid["site_id"].astype(str).unique()
    site_names = valid["site_name"].astype(str).unique()
    return to_serializable(
        {
            "status": "ok",
            "period": period_payload(start, end),
            "peak_demand_kw": peak_value,
            "unit": "kW",
            "timestamp_utc": peak_timestamp,
            "timestamp_local": local_timestamp,
            "timezone": timezone_name,
            "organization": {
                "id": organization_ids[0] if len(organization_ids) == 1 else None,
                "name": organization_names[0]
                if len(organization_names) == 1
                else "Multiple organizations",
            },
            "site": {
                "id": site_ids[0] if len(site_ids) == 1 else None,
                "name": site_names[0] if len(site_names) == 1 else "Multiple sites",
            },
            "meter": meter_payload,
            "selected_meter_count": meter_count,
            "contributing_meter_count_at_peak": contributing_count,
            "interval_minutes": interval,
            "demand_source": source,
            "is_measured_directly": source == "measured_demand",
            "data_completeness": quality,
            "warnings": data_warnings(data, quality),
        }
    )

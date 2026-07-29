"""Deterministic data-quality metrics, including gap detection."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd


def data_quality_summary(
    data: pd.DataFrame,
    *,
    cleaning_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if data.empty:
        return {
            "status": "empty",
            "row_count": 0,
            "date_range": None,
            "organization_count": 0,
            "site_count": 0,
            "meter_count": 0,
            "duplicate_count": int((cleaning_report or {}).get("exact_duplicate_count", 0)),
            "conflicting_duplicate_count": int(
                (cleaning_report or {}).get("conflicting_duplicate_key_count", 0)
            ),
            "missing_interval_count": 0,
            "expected_observation_count": 0,
            "completeness_ratio": None,
            "completeness_percentage": None,
            "invalid_record_count": int(
                (cleaning_report or {}).get("invalid_record_count", 0)
            ),
            "timezone_assumptions": [],
        }

    frame = data.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    expected_total = 0
    observed_total = 0
    missing_total = 0
    unexpected_interval_count = 0
    for _, meter_data in frame.groupby("meter_id"):
        meter_data = meter_data.sort_values("timestamp")
        interval = int(meter_data["interval_minutes"].mode().iloc[0])
        start = meter_data["timestamp"].iloc[0]
        end = meter_data["timestamp"].iloc[-1]
        expected = int((end - start).total_seconds() // (interval * 60)) + 1
        observed = int(meter_data["timestamp"].nunique())
        expected_total += expected
        observed_total += observed
        missing_total += max(0, expected - observed)
        diffs = meter_data["timestamp"].diff().dropna().dt.total_seconds() / 60
        unexpected_interval_count += int(((diffs % interval) != 0).sum())

    ratio = observed_total / expected_total if expected_total else None
    assumption_mask = frame["timezone_assumed"].astype("boolean").fillna(False)
    assumptions = (
        frame.loc[assumption_mask, "timezone"]
        .dropna()
        .astype(str)
        .drop_duplicates()
        .tolist()
    )
    return {
        "status": "ok",
        "row_count": len(frame),
        "date_range": {
            "start": frame["timestamp"].min().isoformat(),
            "end": frame["timestamp"].max().isoformat(),
        },
        "organization_count": int(frame["organization_id"].nunique()),
        "site_count": int(frame["site_id"].nunique()),
        "meter_count": int(frame["meter_id"].nunique()),
        "duplicate_count": int((cleaning_report or {}).get("exact_duplicate_count", 0)),
        "conflicting_duplicate_count": int(
            (cleaning_report or {}).get("conflicting_duplicate_key_count", 0)
        ),
        "missing_interval_count": missing_total,
        "expected_observation_count": expected_total,
        "completeness_ratio": ratio,
        "completeness_percentage": ratio * 100 if ratio is not None else None,
        "invalid_record_count": int(
            (cleaning_report or {}).get("invalid_record_count", 0)
        ),
        "unexpected_interval_count": unexpected_interval_count,
        "timezone_assumptions": assumptions,
    }

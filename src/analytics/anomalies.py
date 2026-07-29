"""Explainable hour-of-week median/MAD anomaly detection."""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from src.analytics.common import (
    completeness,
    data_warnings,
    empty_result,
    period_payload,
    to_serializable,
)


def detect_anomalies(
    data: pd.DataFrame,
    *,
    start,
    end,
    threshold: float = 3.5,
    minimum_samples: int = 4,
    max_results: int = 100,
) -> Dict[str, Any]:
    if threshold <= 0:
        raise ValueError("threshold must be positive.")
    if minimum_samples < 4:
        raise ValueError("minimum_samples must be at least 4.")
    if max_results < 1 or max_results > 500:
        raise ValueError("max_results must be between 1 and 500.")
    if data.empty:
        return empty_result(start=start, end=end)

    annotated = _annotate_hour_of_week(data.dropna(subset=["energy_kwh"]))
    anomalies = []
    groups_evaluated = 0
    for (meter_id, comparable_hour), group in annotated.groupby(
        ["meter_id", "_hour_of_week"]
    ):
        values = group["energy_kwh"].astype(float)
        if len(values) < minimum_samples:
            continue
        median = float(values.median())
        mad = float(np.median(np.abs(values - median)))
        if mad == 0:
            q1, q3 = values.quantile([0.25, 0.75])
            scale = float((q3 - q1) / 1.349) if q3 > q1 else 0.0
            scale_method = "iqr_scaled"
        else:
            scale = 1.4826 * mad
            scale_method = "mad_scaled"
        if scale <= 0:
            continue
        groups_evaluated += 1
        scores = (values - median) / scale
        for index, score in scores.items():
            if abs(score) < threshold:
                continue
            row = group.loc[index]
            anomalies.append(
                {
                    "timestamp_utc": row["timestamp"],
                    "timestamp_local": row["_local_timestamp"],
                    "actual_energy_kwh": float(row["energy_kwh"]),
                    "baseline_energy_kwh": median,
                    "deviation_kwh": float(row["energy_kwh"] - median),
                    "anomaly_score": float(score),
                    "threshold": threshold,
                    "direction": "high" if score > 0 else "low",
                    "meter_id": str(row["meter_id"]),
                    "meter_name": str(row["meter_name"]),
                    "site_id": str(row["site_id"]),
                    "site_name": str(row["site_name"]),
                    "supporting_sample_size": len(values),
                    "comparable_hour_of_week": int(comparable_hour),
                    "scale_method": scale_method,
                }
            )
    anomalies.sort(key=lambda row: abs(row["anomaly_score"]), reverse=True)
    total_anomaly_count = len(anomalies)
    truncated = total_anomaly_count > max_results
    anomalies = anomalies[:max_results]
    quality = completeness(data, start, end)
    warnings = data_warnings(data, quality)
    if groups_evaluated == 0:
        warnings.append(
            "No comparable hour-of-week group met the sample and variability requirements."
        )
    if truncated:
        warnings.append("Results were truncated to the configured maximum.")
    return to_serializable(
        {
            "status": "ok",
            "period": period_payload(start, end),
            "method": {
                "name": "hour_of_week_robust_z_score",
                "threshold": threshold,
                "minimum_samples": minimum_samples,
                "description": (
                    "Each interval is compared with the median for the same local "
                    "hour of week. Dispersion uses scaled MAD, with scaled IQR fallback."
                ),
                "limitations": (
                    "This flags unusual interval energy relative to repeated weekly "
                    "patterns. It can miss gradual drift and cannot explain causes. "
                    "Missing intervals are excluded and treated as quality gaps."
                ),
            },
            "anomaly_count": total_anomaly_count,
            "returned_anomaly_count": len(anomalies),
            "anomalies": anomalies,
            "data_completeness": quality,
            "warnings": warnings,
        }
    )


def _annotate_hour_of_week(data: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for timezone_name, group in data.groupby("timezone"):
        temporary = group.copy()
        local = pd.to_datetime(temporary["timestamp"], utc=True).dt.tz_convert(
            str(timezone_name)
        )
        temporary["_local_timestamp"] = local
        temporary["_hour_of_week"] = local.dt.dayofweek * 24 + local.dt.hour
        parts.append(temporary)
    return pd.concat(parts, ignore_index=True)

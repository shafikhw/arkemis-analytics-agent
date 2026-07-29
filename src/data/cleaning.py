"""Deterministic canonical-data cleaning and duplicate policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from src.data.schemas import CANONICAL_COLUMNS


@dataclass
class CleaningResult:
    data: pd.DataFrame
    conflicts: pd.DataFrame
    report: Dict[str, Any]


def clean_records(records: pd.DataFrame) -> CleaningResult:
    """Validate canonical records; exclude invalid and conflicting observations."""
    frame = records.copy()
    for column in CANONICAL_COLUMNS:
        if column not in frame:
            frame[column] = np.nan
    frame = frame[CANONICAL_COLUMNS]
    input_count = len(frame)

    parsed_timestamps = pd.to_datetime(
        frame["timestamp"], utc=True, errors="coerce", format="mixed"
    )
    invalid_timestamp = parsed_timestamps.isna()
    frame["timestamp"] = parsed_timestamps
    frame["energy_kwh"] = pd.to_numeric(frame["energy_kwh"], errors="coerce")
    frame["demand_kw"] = pd.to_numeric(frame["demand_kw"], errors="coerce")
    frame["interval_minutes"] = pd.to_numeric(
        frame["interval_minutes"], errors="coerce"
    ).astype("Int64")
    invalid_interval = frame["interval_minutes"].isna() | (
        frame["interval_minutes"] <= 0
    )
    negative_energy = frame["energy_kwh"] < 0
    invalid_measurement = frame["energy_kwh"].isna() & frame["demand_kw"].isna()
    invalid_mask = (
        invalid_timestamp | invalid_interval | negative_energy | invalid_measurement
    )
    invalid_count = int(invalid_mask.sum())
    frame = frame.loc[~invalid_mask].copy()

    identity_columns = ["meter_id", "timestamp"]
    exact_duplicate_mask = frame.duplicated(keep="first")
    exact_duplicate_count = int(exact_duplicate_mask.sum())
    frame = frame.loc[~exact_duplicate_mask].copy()

    repeated = frame.duplicated(identity_columns, keep=False)
    repeated_rows = frame.loc[repeated].copy()
    conflict_keys: List[tuple] = []
    if not repeated_rows.empty:
        for key, group in repeated_rows.groupby(identity_columns, dropna=False):
            comparison = group[
                ["energy_kwh", "demand_kw", "original_value", "original_unit"]
            ].astype(str)
            if len(comparison.drop_duplicates()) > 1:
                conflict_keys.append(key if isinstance(key, tuple) else (key,))

    if conflict_keys:
        conflict_index = pd.MultiIndex.from_tuples(conflict_keys, names=identity_columns)
        row_index = pd.MultiIndex.from_frame(frame[identity_columns])
        conflict_mask = row_index.isin(conflict_index)
        conflicts = frame.loc[conflict_mask].copy()
        frame = frame.loc[~conflict_mask].copy()
    else:
        conflicts = frame.iloc[0:0].copy()

    frame = frame.sort_values(["meter_id", "timestamp"]).reset_index(drop=True)
    conflicts = conflicts.sort_values(["meter_id", "timestamp"]).reset_index(drop=True)
    report = {
        "input_row_count": input_count,
        "clean_row_count": len(frame),
        "exact_duplicate_count": exact_duplicate_count,
        "conflicting_duplicate_key_count": len(conflict_keys),
        "conflicting_duplicate_row_count": len(conflicts),
        "invalid_record_count": invalid_count,
        "invalid_timestamp_count": int(invalid_timestamp.sum()),
        "negative_energy_count": int(negative_energy.fillna(False).sum()),
        "invalid_interval_count": int(invalid_interval.sum()),
    }
    return CleaningResult(data=frame, conflicts=conflicts, report=report)

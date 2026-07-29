from __future__ import annotations

import pandas as pd

from src.data.cleaning import clean_records


def test_exact_duplicate_removed(energy_frame):
    duplicate = pd.concat([energy_frame, energy_frame.iloc[[0]]], ignore_index=True)
    result = clean_records(duplicate)
    assert len(result.data) == len(energy_frame)
    assert result.report["exact_duplicate_count"] == 1


def test_conflicting_duplicate_detected_and_excluded(energy_frame):
    conflict = energy_frame.iloc[[0]].copy()
    conflict["energy_kwh"] = conflict["energy_kwh"] + 1
    result = clean_records(pd.concat([energy_frame, conflict], ignore_index=True))
    assert result.report["conflicting_duplicate_key_count"] == 1
    assert len(result.conflicts) == 2
    assert energy_frame.iloc[0]["timestamp"] not in set(result.data["timestamp"])


def test_invalid_timestamp_and_negative_energy_are_excluded(energy_frame):
    invalid = energy_frame.iloc[:2].copy()
    invalid["timestamp"] = invalid["timestamp"].astype(object)
    invalid.loc[invalid.index[0], "timestamp"] = "not-a-date"
    invalid.loc[invalid.index[1], "energy_kwh"] = -1
    result = clean_records(invalid)
    assert result.data.empty
    assert result.report["invalid_record_count"] == 2

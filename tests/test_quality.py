from __future__ import annotations

from src.data.quality import data_quality_summary


def test_missing_interval_detection(energy_frame):
    frame = energy_frame.drop(index=[10, 11]).reset_index(drop=True)
    quality = data_quality_summary(frame)
    assert quality["missing_interval_count"] == 2
    assert quality["completeness_ratio"] < 1


def test_timezone_assumption_reported(energy_frame):
    frame = energy_frame.copy()
    frame["timezone"] = "Asia/Beirut"
    frame["timezone_assumed"] = True
    quality = data_quality_summary(frame)
    assert quality["timezone_assumptions"] == ["Asia/Beirut"]

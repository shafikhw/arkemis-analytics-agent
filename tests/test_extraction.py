from __future__ import annotations

import pandas as pd
import pytest

from src.data.extraction import (
    _segments_to_fetch,
    infer_interval_minutes,
    normalize_active_power,
)
from src.data.schemas import Meter


def meter(interval=15):
    return Meter(
        id="m1",
        name="Meter",
        site_id="s1",
        site_name="Site",
        organization_id="o1",
        organization_name="Org",
        measurement_type="electricity",
        unit=None,
        reading_type="Interval",
        interval_minutes=interval,
        timezone="UTC",
        timezone_assumed=True,
    )


def test_active_power_to_energy_conversion():
    rows = [{"timestamp": "2026-01-01T00:00:00Z", "total": 4000}]
    result = normalize_active_power(rows, meter())
    assert result[0]["demand_kw"] == pytest.approx(4.0)
    assert result[0]["energy_kwh"] == pytest.approx(1.0)
    assert result[0]["original_unit"] == "W"


def test_active_power_requires_interval():
    with pytest.raises(ValueError, match="positive meter interval"):
        normalize_active_power([], meter(interval=None))


def test_unknown_raw_field_rejected():
    with pytest.raises(ValueError, match="neither documented"):
        normalize_active_power(
            [{"timestamp": "2026-01-01T00:00:00Z", "mystery": 1}], meter()
        )


def test_interval_inference_uses_timestamp_mode():
    rows = [
        {"timestamp": "2026-01-01T00:00:00Z"},
        {"timestamp": "2026-01-01T00:15:00Z"},
        {"timestamp": "2026-01-01T00:30:00Z"},
        {"timestamp": "2026-01-01T01:00:00Z"},  # one gap
        {"timestamp": "2026-01-01T01:15:00Z"},
    ]
    assert infer_interval_minutes(rows) == 15


def test_incremental_segments_support_backfill_and_forward_extension():
    existing = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-03-02", periods=4, freq="15min", tz="UTC"),
            "interval_minutes": [15] * 4,
        }
    )
    segments = _segments_to_fetch(
        existing,
        pd.Timestamp("2026-03-01", tz="UTC").to_pydatetime(),
        pd.Timestamp("2026-03-03", tz="UTC").to_pydatetime(),
        interval_minutes=15,
        full_refresh=False,
    )
    assert len(segments) == 2
    assert segments[0][0].date().isoformat() == "2026-03-01"
    assert segments[1][1].date().isoformat() == "2026-03-03"

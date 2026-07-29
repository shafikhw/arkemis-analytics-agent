from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.schemas import CANONICAL_COLUMNS


def make_energy_frame(
    *,
    start: str = "2026-03-01T00:00:00Z",
    periods: int = 96 * 14,
    interval_minutes: int = 15,
    timezone: str = "UTC",
    meter_id: str = "m1",
    meter_name: str = "Main Meter",
    site_id: str = "s1",
    site_name: str = "Factory",
    organization_id: str = "o1",
    organization_name: str = "Food Corp.",
    demand_kw=None,
) -> pd.DataFrame:
    timestamps = pd.date_range(
        start=start, periods=periods, freq=f"{interval_minutes}min", tz="UTC"
    )
    if demand_kw is None:
        demand = 20.0 + 5.0 * np.sin(np.arange(periods) * 2 * np.pi / 96)
    elif np.isscalar(demand_kw):
        demand = np.full(periods, float(demand_kw))
    else:
        demand = np.asarray(demand_kw, dtype=float)
    energy = demand * interval_minutes / 60.0
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "organization_id": organization_id,
            "organization_name": organization_name,
            "site_id": site_id,
            "site_name": site_name,
            "meter_id": meter_id,
            "meter_name": meter_name,
            "energy_kwh": energy,
            "demand_kw": demand,
            "demand_source": "derived_from_documented_active_power_w",
            "measurement_type": "electricity_active_power",
            "original_value": demand * 1000.0,
            "original_unit": "W",
            "interval_minutes": interval_minutes,
            "timezone": timezone,
            "timezone_assumed": False,
            "source": "synthetic_test",
            "extraction_timestamp": pd.Timestamp("2026-04-01T00:00:00Z"),
        }
    )
    return frame[CANONICAL_COLUMNS]


@pytest.fixture
def energy_frame() -> pd.DataFrame:
    return make_energy_frame()

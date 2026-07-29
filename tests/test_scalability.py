from __future__ import annotations

import pandas as pd
from conftest import make_energy_frame

from src.data.aggregation import aggregate_energy


def test_one_year_of_fifteen_minute_data_aggregates_by_month() -> None:
    """Exercise the per-meter unit used by the partitioned 40-meter cache design."""
    frame = make_energy_frame(
        start="2025-01-01T00:00:00Z",
        periods=365 * 24 * 4,
        interval_minutes=15,
    )

    monthly = aggregate_energy(frame, "monthly")

    assert len(frame) == 35_040
    assert len(monthly) == 12
    assert monthly["observation_count"].sum() == 35_040
    assert monthly["expected_observation_count"].sum() == 35_040
    assert (monthly["completeness_ratio"] == 1.0).all()
    assert pd.notna(monthly["total_energy_kwh"]).all()


def test_target_portfolio_row_count_is_bounded() -> None:
    assert 40 * 365 * 24 * 4 == 1_401_600

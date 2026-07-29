from __future__ import annotations

import pytest

from src.data.aggregation import aggregate_energy


@pytest.mark.parametrize(
    ("resolution", "minimum_rows"),
    [("hourly", 24), ("daily", 1), ("weekly", 1), ("monthly", 1)],
)
def test_supported_aggregations_preserve_energy(energy_frame, resolution, minimum_rows):
    aggregated = aggregate_energy(energy_frame, resolution)
    assert len(aggregated) >= minimum_rows
    assert aggregated["total_energy_kwh"].sum() == pytest.approx(
        energy_frame["energy_kwh"].sum()
    )


def test_partial_period_completeness(energy_frame):
    partial = energy_frame.iloc[:90].copy()
    daily = aggregate_energy(partial, "daily")
    assert daily.iloc[0]["expected_observation_count"] == 96
    assert daily.iloc[0]["observation_count"] == 90
    assert bool(daily.iloc[0]["is_partial"])


def test_native_derived_demand_is_preserved(energy_frame):
    native = aggregate_energy(energy_frame.iloc[:1], "native")
    assert native.iloc[0]["average_demand_kw"] == pytest.approx(
        energy_frame.iloc[0]["demand_kw"]
    )

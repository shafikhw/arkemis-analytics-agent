from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from conftest import make_energy_frame

from src.analytics.anomalies import detect_anomalies
from src.analytics.baseload import estimate_baseload
from src.analytics.common import filter_local_period, safe_percentage_change
from src.analytics.comparison import compare_period_values
from src.analytics.load_factor import calculate_load_factor
from src.analytics.peaks import peak_demand
from src.analytics.profiles import compare_weekday_weekend
from src.analytics.ranking import rank_sites

START = date(2026, 3, 1)
END = date(2026, 3, 15)


def test_period_percentage_and_division_by_zero(energy_frame):
    assert safe_percentage_change(120, 100) == pytest.approx(20)
    assert safe_percentage_change(10, 0) is None
    result = compare_period_values(
        energy_frame,
        energy_frame.assign(energy_kwh=0),
        current_start=START,
        current_end=END,
        previous_start=date(2026, 2, 15),
        previous_end=START,
    )
    assert result["percentage_difference"] is None


def test_baseload_estimation(energy_frame):
    result = estimate_baseload(
        energy_frame,
        start=START,
        end=END,
        group_by="meter",
        percentile=10,
        minimum_observations=96,
    )
    estimate = result["estimates"][0]
    assert 14 < estimate["baseload_estimate_kw"] < 21
    assert estimate["reliable"] is True
    assert "statistical" in result["warnings"][-1].lower()


def test_peak_demand_and_source(energy_frame):
    result = peak_demand(energy_frame, start=START, end=END)
    assert result["peak_demand_kw"] == pytest.approx(25)
    assert result["is_measured_directly"] is False
    assert result["interval_minutes"] == 15


def test_load_factor(energy_frame):
    result = calculate_load_factor(energy_frame, start=START, end=END)
    assert result["average_demand_kw"] == pytest.approx(20)
    assert result["peak_demand_kw"] == pytest.approx(25)
    assert result["load_factor"] == pytest.approx(0.8)
    assert result["load_factor_percentage"] == pytest.approx(80)


def test_multi_meter_load_factor_uses_coincident_sum(energy_frame):
    second = energy_frame.copy()
    second["meter_id"] = "m2"
    second["meter_name"] = "Second"
    second["demand_kw"] = 5.0
    second["energy_kwh"] = 1.25
    combined = pd.concat([energy_frame, second], ignore_index=True)
    result = calculate_load_factor(combined, start=START, end=END)
    expected_average = 25.0
    expected_peak = 30.0
    assert result["average_demand_kw"] == pytest.approx(expected_average)
    assert result["peak_demand_kw"] == pytest.approx(expected_peak)
    assert result["demand_aggregation"]["meter_count"] == 2
    assert any("double-count" in warning for warning in result["warnings"])


def test_weekday_weekend_uses_local_dates():
    frame = make_energy_frame(
        start="2026-03-06T22:00:00Z",
        periods=16,
        timezone="Asia/Beirut",
        demand_kw=4,
    )
    result = compare_weekday_weekend(
        frame,
        start=date(2026, 3, 7),
        end=date(2026, 3, 8),
        include_hourly_profile=True,
    )
    assert result["weekday_total_kwh"] == 0
    assert result["weekend_total_kwh"] == pytest.approx(16)
    assert all(row["day_type"] == "weekend" for row in result["hourly_profile"])


def test_site_ranking(energy_frame):
    second = make_energy_frame(
        meter_id="m2",
        site_id="s2",
        site_name="Hotel",
        organization_id="o2",
        organization_name="Best Resorts Hotels",
        demand_kw=40,
    )
    result = rank_sites(
        pd.concat([energy_frame, second]),
        start=START,
        end=END,
        metric="total_consumption",
    )
    assert result["ranked_sites"][0]["site_id"] == "s2"
    assert "does not establish efficiency" in result["justification_or_limitation"]


def test_anomaly_detection():
    values = np.full(96 * 8, 10.0)
    # Give comparable groups non-zero spread and one clear high outlier.
    values[::96] = np.array([9, 10, 11, 9.5, 10.5, 10, 9.8, 80])
    frame = make_energy_frame(periods=len(values), demand_kw=values * 4)
    frame["energy_kwh"] = values
    result = detect_anomalies(
        frame,
        start=date(2026, 3, 1),
        end=date(2026, 3, 9),
        threshold=3.5,
        minimum_samples=4,
    )
    assert result["anomaly_count"] >= 1
    assert result["anomalies"][0]["direction"] == "high"


def test_local_period_filter_conversion():
    frame = make_energy_frame(
        start="2026-03-01T22:00:00Z",
        periods=4,
        timezone="Asia/Beirut",
    )
    filtered = filter_local_period(frame, date(2026, 3, 2), date(2026, 3, 3))
    assert len(filtered) == 4

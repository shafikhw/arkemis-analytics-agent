from __future__ import annotations

from src.llm.fallback_renderers import RENDERERS, render_fallback
from src.llm.result_validation import ValidatedToolResult

REQUIRED_RENDERERS = {
    "get_consumption_summary",
    "compare_periods",
    "compare_entities",
    "estimate_baseload",
    "get_peak_demand",
    "calculate_load_factor",
    "compare_weekday_weekend",
    "rank_sites",
    "detect_anomalies",
    "get_data_quality",
    "get_load_profile",
}


def test_all_primary_tool_renderers_are_registered():
    assert REQUIRED_RENDERERS <= set(RENDERERS)


def test_peak_fallback_uses_validated_fields_and_rounding():
    result = ValidatedToolResult(
        name="get_peak_demand",
        arguments={},
        result={
            "status": "ok",
            "period": {
                "start_date_inclusive": "2026-06-01",
                "end_date_exclusive": "2026-07-01",
            },
            "peak_demand_kw": 188.70695999999998,
            "unit": "kW",
            "timestamp_utc": "2026-06-12T16:25:00+00:00",
            "timestamp_local": "2026-06-12T16:25:00+00:00",
            "organization": {"name": "Food Corp."},
            "site": {"name": "Organic Farm"},
            "meter": {"name": "Effluent Area"},
            "interval_minutes": 5,
            "demand_source": "derived_from_documented_active_power_w",
            "is_measured_directly": False,
            "data_completeness": {
                "observation_count": 8636,
                "expected_observation_count": 8640,
                "completeness_percentage": 99.9537037037,
            },
            "warnings": ["The requested period is partial."],
        },
    )
    answer = render_fallback([result])
    assert "June 12, 2026 at 4:25 PM UTC" in answer
    assert "188.707 kW" in answer
    assert "8,636 of 8,640" in answer
    assert "Organic Farm" in answer
    assert "Effluent Area" in answer

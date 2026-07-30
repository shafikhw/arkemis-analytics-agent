from __future__ import annotations

from src.llm.fallback_renderers import RENDERERS, render_fallback
from src.llm.result_validation import ValidatedToolResult

REQUIRED_RENDERERS = {
    "list_organizations",
    "list_sites",
    "list_meters",
    "get_data_availability",
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


def test_multi_period_fallback_identifies_the_larger_increase():
    results = [
        ValidatedToolResult(
            name="compare_periods",
            arguments={"organization": "63"},
            result={
                "status": "ok",
                "organization": {"id": "63", "name": "Food Corp."},
                "absolute_difference_kwh": -1166.07544,
                "percentage_difference": -6.033914,
                "warnings": ["Food period is partial."],
            },
        ),
        ValidatedToolResult(
            name="compare_periods",
            arguments={"organization": "64"},
            result={
                "status": "ok",
                "organization": {
                    "id": "64",
                    "name": "Best Resorts Hotels",
                },
                "absolute_difference_kwh": 163.65922,
                "percentage_difference": 0.864255,
                "warnings": ["Hotel period is partial."],
            },
        ),
    ]

    answer = render_fallback(results)

    assert (
        "Best Resorts Hotels had the larger week-over-week increase at 0.864%."
        in answer
    )
    assert "Food Corp.: -6.034% (-1,166.075 kWh)" in answer
    assert "163.659 kWh" in answer


def test_site_and_meter_fallback_lists_entity_arrays_instead_of_only_timestamp():
    results = [
        ValidatedToolResult(
            name="list_sites",
            arguments={"organization": None},
            result={
                "status": "ok",
                "sites": [
                    {
                        "id": "106",
                        "name": "Organic Farm",
                        "organization_name": "Food Corp.",
                        "timezone": "UTC",
                        "timezone_assumed": True,
                    },
                    {
                        "id": "108",
                        "name": "Beta Resort & Spa",
                        "organization_name": "Best Resorts Hotels",
                        "timezone": "UTC",
                        "timezone_assumed": True,
                    },
                ],
                "discovered_at": "2026-07-29T20:23:37+00:00",
            },
        ),
        ValidatedToolResult(
            name="list_meters",
            arguments={"organization": None, "site": None},
            result={
                "status": "ok",
                "meters": [
                    {
                        "id": "751",
                        "name": "Effluent Area",
                        "site_name": "Organic Farm",
                        "organization_name": "Food Corp.",
                        "measurement_type": "electricity",
                        "unit": "Watt",
                        "reading_type": "cum",
                        "interval_minutes": 5,
                    }
                ],
                "discovered_at": "2026-07-29T20:23:37+00:00",
            },
        ),
    ]

    answer = render_fallback(results)

    assert "Available sites:" in answer
    assert "Organic Farm - Food Corp." in answer
    assert "Beta Resort & Spa - Best Resorts Hotels" in answer
    assert "Available meters:" in answer
    assert "Effluent Area" in answer
    assert "interval: 5 minutes" in answer
    assert "### list_sites" not in answer

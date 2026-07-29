from __future__ import annotations

from src.llm.response_validation import validate_numeric_grounding


def test_unsupported_model_number_is_flagged():
    result = validate_numeric_grounding(
        "Consumption was 999 kWh.",
        [{"total_energy_kwh": 120.5}],
    )
    assert result.valid is False
    assert result.unsupported_numbers == ["999"]


def test_returned_number_and_formatting_are_allowed():
    result = validate_numeric_grounding(
        "Consumption was 1,200.5 kWh.",
        [{"total_energy_kwh": 1200.5}],
    )
    assert result.valid is True


def test_single_digit_energy_value_is_not_ignored():
    result = validate_numeric_grounding(
        "Consumption was 5 kWh.",
        [{"total_energy_kwh": 4.0}],
    )
    assert result.valid is False
    assert result.unsupported_numbers == ["5"]


def test_markdown_ordered_list_marker_is_ignored():
    result = validate_numeric_grounding(
        "1. Consumption was 4.0 kWh.",
        [{"total_energy_kwh": 4.0}],
    )
    assert result.valid is True


def test_readable_and_iso_utc_timestamps_are_semantically_equivalent():
    source = [{"timestamp_utc": "2026-06-12T16:25:00+00:00"}]
    readable = validate_numeric_grounding(
        "The peak was June 12, 2026 at 4:25 PM UTC.", source
    )
    iso = validate_numeric_grounding("The peak was 2026-06-12T16:25:00Z.", source)
    assert readable.valid is True
    assert iso.valid is True
    assert readable.provenance[0].transformation == "equivalent_timestamp_format"


def test_rounding_trailing_zero_and_units_are_allowed():
    result = validate_numeric_grounding(
        "Peak demand was 188.7070kW.",
        [{"peak_demand_kw": 188.70695999999998}],
    )
    assert result.valid is True
    assert result.provenance[0].source_field == "$.peak_demand_kw"


def test_ratio_can_be_displayed_as_percentage():
    result = validate_numeric_grounding(
        "Completeness was 99.954%.",
        [{"data_completeness": {"completeness_ratio": 0.999537037}}],
    )
    assert result.valid is True
    assert result.provenance[0].transformation == "ratio_to_percentage"


def test_new_arithmetic_is_rejected_even_if_inputs_exist():
    result = validate_numeric_grounding(
        "The combined result is 200 kWh.",
        [{"first_kwh": 120.0, "second_kwh": 80.0}],
    )
    assert result.valid is False
    assert result.unsupported_numbers == ["200"]

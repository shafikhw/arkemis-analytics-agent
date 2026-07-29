from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.llm.usage_tracking import (
    PricingConfiguration,
    empty_usage,
    extract_usage,
    merge_usage,
)


def test_gpt_56_terra_regression_cost():
    pricing = PricingConfiguration.terra_standard()
    usage = empty_usage(pricing)
    response = SimpleNamespace(
        model="gpt-5.6-terra",
        service_tier="standard",
        usage=SimpleNamespace(
            input_tokens=9924,
            output_tokens=363,
            total_tokens=10287,
            input_tokens_details=SimpleNamespace(
                cached_tokens=0,
                cache_write_tokens=0,
            ),
        ),
    )
    merge_usage(usage, extract_usage(response), pricing=pricing)
    assert usage["uncached_input_tokens"] == 9924
    assert usage["estimated_cost_usd_exact"] == "0.030255"
    assert usage["estimated_cost_usd"] == pytest.approx(0.030255)


def test_cached_input_is_not_counted_twice():
    pricing = PricingConfiguration.terra_standard()
    usage = empty_usage(pricing)
    response = SimpleNamespace(
        model="gpt-5.6-terra",
        service_tier="standard",
        usage=SimpleNamespace(
            input_tokens=10_000,
            output_tokens=1_000,
            total_tokens=11_000,
            input_tokens_details=SimpleNamespace(
                cached_tokens=8_000,
                cache_write_tokens=500,
            ),
        ),
    )
    merge_usage(usage, extract_usage(response), pricing=pricing)
    expected = 2_000 / 1_000_000 * 2.5
    expected += 8_000 / 1_000_000 * 0.25
    expected += 500 / 1_000_000 * 3.125
    expected += 1_000 / 1_000_000 * 15
    assert usage["uncached_input_tokens"] == 2_000
    assert usage["estimated_cost_usd"] == pytest.approx(expected)


def test_unreported_cache_details_are_zero_with_assumptions():
    pricing = PricingConfiguration.terra_standard()
    usage = empty_usage(pricing)
    response = SimpleNamespace(
        model="gpt-5.6-terra",
        service_tier="standard",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            input_tokens_details=None,
        ),
    )
    merge_usage(usage, extract_usage(response), pricing=pricing)
    assert usage["cached_input_tokens"] == 0
    assert usage["cache_write_tokens"] == 0
    assert len(usage["assumptions"]) == 2
    assert usage["estimated_cost_usd"] is not None


def test_cost_unavailable_without_usage_or_matching_pricing():
    pricing = PricingConfiguration.terra_standard()
    no_usage = empty_usage(pricing)
    merge_usage(
        no_usage,
        extract_usage(SimpleNamespace(usage=None, model=None)),
        pricing=pricing,
    )
    assert no_usage["estimated_cost_usd"] is None

    unknown = empty_usage(pricing, model="unknown-model")
    merge_usage(
        unknown,
        {
            "model": "unknown-model",
            "input_tokens": 100,
            "cached_input_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 20,
            "total_tokens": 120,
            "cached_input_reported": True,
            "cache_write_reported": True,
        },
        pricing=pricing,
    )
    assert unknown["estimated_cost_usd"] is None

from __future__ import annotations

import pytest
from conftest import make_energy_frame

from src.data.cache import EnergyCache
from src.data.discovery import save_hierarchy
from src.data.schemas import Hierarchy, Meter, Organization, Site
from src.tools.energy_tools import EnergyTools
from src.tools.registry import ToolRegistry, ToolValidationError


def build_cache(tmp_path, with_data=True):
    cache = EnergyCache(tmp_path / "data")
    cache.ensure_directories()
    hierarchy = Hierarchy(
        organizations=[Organization(id="o1", name="Food Corp.")],
        sites=[
            Site(
                id="s1",
                name="Factory",
                organization_id="o1",
                organization_name="Food Corp.",
                timezone="UTC",
                timezone_assumed=False,
            )
        ],
        meters=[
            Meter(
                id="m1",
                name="Main Meter",
                site_id="s1",
                site_name="Factory",
                organization_id="o1",
                organization_name="Food Corp.",
                measurement_type="electricity",
                unit=None,
                reading_type="Interval",
                interval_minutes=15,
                timezone="UTC",
                timezone_assumed=False,
            )
        ],
        discovered_at="2026-04-01T00:00:00+00:00",
    )
    save_hierarchy(hierarchy, cache.hierarchy_path)
    if with_data:
        cache.write_meter("m1", make_energy_frame())
    return cache


def test_empty_tool_result(tmp_path):
    cache = build_cache(tmp_path, with_data=False)
    result = EnergyTools(cache).get_consumption_summary(
        organization="Food Corp.",
        site=None,
        meter=None,
        start_date="2026-03-01",
        end_date="2026-03-02",
        resolution="daily",
    )
    assert result["status"] == "empty"


def test_invalid_tool_parameters_rejected(tmp_path):
    registry = ToolRegistry(EnergyTools(build_cache(tmp_path)))
    with pytest.raises(ToolValidationError, match="resolution"):
        registry.execute(
            "get_consumption_summary",
            {
                "organization": None,
                "site": None,
                "meter": None,
                "start_date": "2026-03-01",
                "end_date": "2026-03-02",
                "resolution": "yearly",
            },
        )
    with pytest.raises(ToolValidationError, match="unsupported argument"):
        registry.execute("list_organizations", {"sql": "select *"})
    with pytest.raises(ToolValidationError, match="resolution"):
        registry.execute(
            "get_consumption_summary",
            {
                "organization": None,
                "site": None,
                "meter": None,
                "start_date": "2026-03-01",
                "end_date": "2026-03-02",
                "resolution": "native",
            },
        )


def test_consumption_tool_uses_cache(tmp_path):
    registry = ToolRegistry(EnergyTools(build_cache(tmp_path)))
    result = registry.execute(
        "get_consumption_summary",
        {
            "organization": "Food Corp.",
            "site": None,
            "meter": None,
            "start_date": "2026-03-01",
            "end_date": "2026-03-02",
            "resolution": "daily",
        },
    )
    assert result["status"] == "ok"
    assert result["total_energy_kwh"] == pytest.approx(480)

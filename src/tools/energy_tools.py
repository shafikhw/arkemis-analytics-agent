"""Concrete deterministic tool handlers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional

from src.analytics.common import filter_local_period, parse_date_period, to_serializable
from src.analytics.service import AnalyticsService
from src.data.cache import EnergyCache
from src.data.quality import data_quality_summary


class EnergyTools:
    def __init__(self, cache: EnergyCache) -> None:
        self.cache = cache
        self.analytics = AnalyticsService(cache)

    def list_organizations(self) -> Dict[str, Any]:
        hierarchy = self.cache.load_hierarchy()
        return {
            "status": "ok",
            "organizations": [asdict(row) for row in hierarchy.organizations],
            "discovered_at": hierarchy.discovered_at,
            "warnings": hierarchy.warnings,
        }

    def list_sites(self, organization: Optional[str]) -> Dict[str, Any]:
        hierarchy = self.cache.load_hierarchy()
        allowed = (
            set(self.cache.resolve_entity_ids("organization", organization))
            if organization
            else None
        )
        rows = [
            asdict(row)
            for row in hierarchy.sites
            if allowed is None or row.organization_id in allowed
        ]
        return {
            "status": "ok" if rows else "empty",
            "sites": rows,
            "discovered_at": hierarchy.discovered_at,
        }

    def list_meters(
        self, organization: Optional[str], site: Optional[str]
    ) -> Dict[str, Any]:
        hierarchy = self.cache.load_hierarchy()
        organization_ids = (
            set(self.cache.resolve_entity_ids("organization", organization))
            if organization
            else None
        )
        site_ids = set(self.cache.resolve_entity_ids("site", site)) if site else None
        rows = [
            asdict(row)
            for row in hierarchy.meters
            if (organization_ids is None or row.organization_id in organization_ids)
            and (site_ids is None or row.site_id in site_ids)
        ]
        return {
            "status": "ok" if rows else "empty",
            "meters": rows,
            "discovered_at": hierarchy.discovered_at,
        }

    def get_data_availability(
        self,
        organization: Optional[str],
        site: Optional[str],
        meter: Optional[str],
    ) -> Dict[str, Any]:
        data = self.cache.read_energy(organization=organization, site=site, meter=meter)
        if data.empty:
            return {
                "status": "empty",
                "message": "No processed observations match the filters.",
                "meters": [],
            }
        rows = []
        for (
            meter_id,
            meter_name,
            site_id,
            site_name,
            organization_id,
            organization_name,
        ), group in data.groupby(
            [
                "meter_id",
                "meter_name",
                "site_id",
                "site_name",
                "organization_id",
                "organization_name",
            ]
        ):
            rows.append(
                {
                    "meter_id": str(meter_id),
                    "meter_name": str(meter_name),
                    "site_id": str(site_id),
                    "site_name": str(site_name),
                    "organization_id": str(organization_id),
                    "organization_name": str(organization_name),
                    "start_timestamp_utc": group["timestamp"].min(),
                    "end_timestamp_utc": group["timestamp"].max(),
                    "observation_count": int(group["timestamp"].nunique()),
                    "interval_minutes": int(group["interval_minutes"].mode().iloc[0]),
                    "timezone": str(group["timezone"].iloc[0]),
                }
            )
        return to_serializable({"status": "ok", "meters": rows})

    def get_data_quality(
        self,
        organization: Optional[str],
        site: Optional[str],
        meter: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Dict[str, Any]:
        if not any((organization, site, meter, start_date, end_date)):
            cached = self.cache.read_quality()
            if cached:
                return cached
        data = self.cache.read_energy(organization=organization, site=site, meter=meter)
        period = None
        if start_date or end_date:
            if not start_date or not end_date:
                raise ValueError("Provide both start_date and end_date, or neither.")
            start, end = parse_date_period(start_date, end_date)
            data = filter_local_period(data, start, end)
            period = {
                "start_date_inclusive": start.isoformat(),
                "end_date_exclusive": end.isoformat(),
            }
        result = data_quality_summary(data)
        if period:
            result["period"] = period
        return to_serializable(result)

    def get_consumption_summary(self, **kwargs: Any) -> Dict[str, Any]:
        return self.analytics.consumption_summary(**kwargs)

    def compare_periods(self, **kwargs: Any) -> Dict[str, Any]:
        return self.analytics.compare_periods(**kwargs)

    def compare_entities(self, **kwargs: Any) -> Dict[str, Any]:
        return self.analytics.compare_entities(**kwargs)

    def estimate_baseload(self, **kwargs: Any) -> Dict[str, Any]:
        return self.analytics.estimate_baseload(**kwargs)

    def get_peak_demand(self, **kwargs: Any) -> Dict[str, Any]:
        return self.analytics.peak_demand(**kwargs)

    def calculate_load_factor(self, **kwargs: Any) -> Dict[str, Any]:
        return self.analytics.load_factor(**kwargs)

    def compare_weekday_weekend(self, **kwargs: Any) -> Dict[str, Any]:
        return self.analytics.weekday_weekend(**kwargs)

    def rank_sites(self, **kwargs: Any) -> Dict[str, Any]:
        return self.analytics.rank_sites(**kwargs)

    def detect_anomalies(self, **kwargs: Any) -> Dict[str, Any]:
        return self.analytics.anomalies(**kwargs)

    def get_load_profile(self, **kwargs: Any) -> Dict[str, Any]:
        return self.analytics.load_profile(**kwargs)

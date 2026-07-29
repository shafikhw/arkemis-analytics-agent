"""Cache-backed facade used exclusively by the validated LLM tool layer."""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.analytics.anomalies import detect_anomalies
from src.analytics.baseload import estimate_baseload
from src.analytics.common import (
    filter_local_period,
    parse_date_period,
    previous_equivalent_period,
)
from src.analytics.comparison import compare_entity_metric, compare_period_values
from src.analytics.consumption import consumption_summary
from src.analytics.load_factor import calculate_load_factor
from src.analytics.peaks import peak_demand
from src.analytics.profiles import compare_weekday_weekend, load_profile
from src.analytics.ranking import rank_sites
from src.data.cache import EnergyCache


class AnalyticsService:
    """Provides deterministic, serializable analytics over processed cache only."""

    def __init__(self, cache: EnergyCache) -> None:
        self.cache = cache

    def load(
        self,
        *,
        organization: Optional[str] = None,
        site: Optional[str] = None,
        meter: Optional[str] = None,
        start_date: str,
        end_date: str,
    ):
        start, end = parse_date_period(start_date, end_date)
        data = self.cache.read_energy(organization=organization, site=site, meter=meter)
        return filter_local_period(data, start, end), start, end

    def consumption_summary(self, **kwargs: Any) -> Dict[str, Any]:
        resolution = kwargs.pop("resolution", "daily")
        data, start, end = self.load(**kwargs)
        return consumption_summary(data, start=start, end=end, resolution=resolution)

    def compare_periods(
        self,
        *,
        organization: Optional[str] = None,
        site: Optional[str] = None,
        meter: Optional[str] = None,
        current_start_date: str,
        current_end_date: str,
        previous_start_date: Optional[str] = None,
        previous_end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        current_start, current_end = parse_date_period(
            current_start_date, current_end_date
        )
        if previous_start_date or previous_end_date:
            if not previous_start_date or not previous_end_date:
                raise ValueError(
                    "Provide both previous_start_date and previous_end_date, or neither."
                )
            previous_start, previous_end = parse_date_period(
                previous_start_date, previous_end_date
            )
        else:
            previous_start, previous_end = previous_equivalent_period(
                current_start, current_end
            )
        all_data = self.cache.read_energy(
            organization=organization, site=site, meter=meter
        )
        current = filter_local_period(all_data, current_start, current_end)
        previous = filter_local_period(all_data, previous_start, previous_end)
        return compare_period_values(
            current,
            previous,
            current_start=current_start,
            current_end=current_end,
            previous_start=previous_start,
            previous_end=previous_end,
        )

    def compare_entities(
        self,
        *,
        entity_kind: str,
        metric: str,
        start_date: str,
        end_date: str,
        organization: Optional[str] = None,
    ) -> Dict[str, Any]:
        data, start, end = self.load(
            organization=organization,
            start_date=start_date,
            end_date=end_date,
        )
        return compare_entity_metric(
            data, entity_kind=entity_kind, start=start, end=end, metric=metric
        )

    def estimate_baseload(self, **kwargs: Any) -> Dict[str, Any]:
        group_by = kwargs.pop("group_by", "site")
        percentile = kwargs.pop("percentile", 10.0)
        minimum_observations = kwargs.pop("minimum_observations", 96)
        data, start, end = self.load(**kwargs)
        return estimate_baseload(
            data,
            start=start,
            end=end,
            group_by=group_by,
            percentile=percentile,
            minimum_observations=minimum_observations,
        )

    def peak_demand(self, **kwargs: Any) -> Dict[str, Any]:
        data, start, end = self.load(**kwargs)
        return peak_demand(data, start=start, end=end)

    def load_factor(self, **kwargs: Any) -> Dict[str, Any]:
        data, start, end = self.load(**kwargs)
        return calculate_load_factor(data, start=start, end=end)

    def weekday_weekend(self, **kwargs: Any) -> Dict[str, Any]:
        include_hourly_profile = kwargs.pop("include_hourly_profile", False)
        data, start, end = self.load(**kwargs)
        return compare_weekday_weekend(
            data,
            start=start,
            end=end,
            include_hourly_profile=include_hourly_profile,
        )

    def rank_sites(self, **kwargs: Any) -> Dict[str, Any]:
        metric = kwargs.pop("metric")
        data, start, end = self.load(**kwargs)
        return rank_sites(data, start=start, end=end, metric=metric)

    def anomalies(self, **kwargs: Any) -> Dict[str, Any]:
        threshold = kwargs.pop("threshold", 3.5)
        minimum_samples = kwargs.pop("minimum_samples", 4)
        max_results = kwargs.pop("max_results", 100)
        data, start, end = self.load(**kwargs)
        return detect_anomalies(
            data,
            start=start,
            end=end,
            threshold=threshold,
            minimum_samples=minimum_samples,
            max_results=max_results,
        )

    def load_profile(self, **kwargs: Any) -> Dict[str, Any]:
        normalized = kwargs.pop("normalized", False)
        data, start, end = self.load(**kwargs)
        return load_profile(data, start=start, end=end, normalized=normalized)

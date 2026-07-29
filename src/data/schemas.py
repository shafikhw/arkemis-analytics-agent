"""Canonical schema definitions shared by data and analytics layers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


CANONICAL_COLUMNS = [
    "timestamp",
    "organization_id",
    "organization_name",
    "site_id",
    "site_name",
    "meter_id",
    "meter_name",
    "energy_kwh",
    "demand_kw",
    "demand_source",
    "measurement_type",
    "original_value",
    "original_unit",
    "interval_minutes",
    "timezone",
    "timezone_assumed",
    "source",
    "extraction_timestamp",
]


@dataclass(frozen=True)
class Organization:
    id: str
    name: str


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    organization_id: str
    organization_name: str
    timezone: str
    timezone_assumed: bool


@dataclass(frozen=True)
class Meter:
    id: str
    name: str
    site_id: str
    site_name: str
    organization_id: str
    organization_name: str
    measurement_type: str
    unit: Optional[str]
    reading_type: Optional[str]
    interval_minutes: Optional[int]
    timezone: str
    timezone_assumed: bool
    reference: Optional[str] = None


@dataclass
class Hierarchy:
    organizations: List[Organization] = field(default_factory=list)
    sites: List[Site] = field(default_factory=list)
    meters: List[Meter] = field(default_factory=list)
    discovered_at: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "organizations": [asdict(value) for value in self.organizations],
            "sites": [asdict(value) for value in self.sites],
            "meters": [asdict(value) for value in self.meters],
            "discovered_at": self.discovered_at,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "Hierarchy":
        return cls(
            organizations=[Organization(**row) for row in value.get("organizations", [])],
            sites=[Site(**row) for row in value.get("sites", [])],
            meters=[Meter(**row) for row in value.get("meters", [])],
            discovered_at=value.get("discovered_at"),
            warnings=list(value.get("warnings", [])),
        )


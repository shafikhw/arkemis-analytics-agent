"""Structured deterministic-first scope classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Optional, Sequence

from src.data.discovery import normalize_name
from src.tools.registry import ToolRegistry


class ScopeState(str, Enum):
    IN_SCOPE = "in_scope"
    ENERGY_BUT_UNSUPPORTED = "energy_but_unsupported"
    OUT_OF_SCOPE = "out_of_scope"
    NEEDS_CLARIFICATION = "needs_clarification"


@dataclass(frozen=True)
class ScopeDecision:
    state: ScopeState
    confidence: float
    reason: str
    deterministic_matches: tuple[str, ...] = ()
    suggested_tool: Optional[str] = None
    missing_information: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "deterministic_matches": list(self.deterministic_matches),
            "suggested_tool": self.suggested_tool,
            "missing_information": list(self.missing_information),
        }


INTENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "get_peak_demand",
        (
            r"\bwhen\b.*\bpeak(?:\s+demand)?\b",
            r"\bpeak(?:\s+demand)?\b.*\bwhen\b",
            r"\bhighest\s+(?:demand|load)\b",
            r"\btime\s+of\s+(?:the\s+)?peak\b",
        ),
    ),
    (
        "get_consumption_summary",
        (
            r"\btotal\s+(?:energy\s+)?consumption\b",
            r"\baverage\s+(?:energy\s+)?consumption\b",
            r"\bhow\s+much\s+(?:energy|electricity)\b",
        ),
    ),
    (
        "compare_periods",
        (
            r"\b(?:week|month|year)[ -]over[ -](?:week|month|year)\b",
            r"\bcompare\b.*\b(?:last|previous|prior|this|current)\s+(?:week|month|year)\b",
            r"\bchange\b.*\b(?:last|previous|prior|this|current)\s+(?:week|month|year)\b",
        ),
    ),
    (
        "detect_anomalies",
        (
            r"\b(?:anything|something)\s+unusual\b",
            r"\banomal(?:y|ies|ous)\b",
            r"\boutlier(?:s)?\b",
        ),
    ),
    (
        "estimate_baseload",
        (r"\bbaseload\b", r"\bbase\s+load\b", r"\boperational\s+load\b"),
    ),
    (
        "get_data_quality",
        (
            r"\bdata\s+(?:quality|completeness)\b",
            r"\bhow\s+complete\b",
            r"\bmissing\s+(?:data|intervals|readings)\b",
            r"\bdata\s+gaps?\b",
        ),
    ),
    (
        "calculate_load_factor",
        (r"\bload\s+factor\b",),
    ),
    (
        "compare_weekday_weekend",
        (
            r"\bweekday\b.*\bweekend\b",
            r"\bweekend\b.*\bweekday\b",
            r"\bweekend\s+consumption\b",
        ),
    ),
    (
        "rank_sites",
        (
            r"\brank(?:ing)?\s+(?:the\s+)?sites\b",
            r"\bbest\s+and\s+worst\s+(?:sites|performers)\b",
            r"\bwhich\s+site\b.*\b(?:most|least|largest|smallest)\b",
        ),
    ),
    (
        "get_load_profile",
        (
            r"\bload\s+profile\b",
            r"\b(?:hourly|daily|weekly|monthly)\s+profile\b",
        ),
    ),
)

SUPPORTED_TERMS = (
    "energy",
    "electricity",
    "consumption",
    "demand",
    "kwh",
    "kw",
    "meter",
    "site",
    "organization",
    "baseload",
    "load factor",
    "weekday",
    "weekend",
    "profile",
    "anomaly",
    "anomalies",
    "unusual",
    "completeness",
    "missing interval",
    "cache",
    "synchronization",
    "sync",
    "data quality",
)

UNSUPPORTED_CAPABILITIES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "forecasting",
        ("forecast", "predict future", "next month", "future consumption"),
        "Future prediction is not implemented and no forecasting model is available.",
    ),
    (
        "tariff_billing",
        ("electricity bill", "energy bill", "tariff", "billing cost"),
        "Tariff, demand-charge, tax, and billing-rule data are unavailable.",
    ),
    (
        "weather_normalization",
        ("weather-normal", "weather normal", "temperature adjusted", "degree day"),
        "Weather observations and a weather-normalization model are unavailable.",
    ),
    (
        "energy_intensity",
        (
            "energy intensity",
            "per square",
            "per guest",
            "per occupant",
            "per unit produced",
            "per production",
        ),
        "Floor area, occupancy, guest-night, and production denominators are unavailable.",
    ),
    (
        "efficiency_declaration",
        ("more efficient", "most efficient", "energy efficient"),
        "Raw kWh is scale-dependent and cannot establish energy efficiency.",
    ),
    (
        "carbon",
        ("carbon emission", "co2", "greenhouse gas", "emissions"),
        "No approved electricity emission factor is configured.",
    ),
)

SENSITIVE_OR_INJECTION_PATTERNS = (
    r"\b(?:api|access)\s+(?:key|token)\b",
    r"\bpassword\b",
    r"\bcredential(?:s)?\b",
    r"\bsystem\s+prompt\b",
    r"\bhidden\s+(?:prompt|instructions?)\b",
    r"\bignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions?\b",
    r"\bfilesystem\b",
    r"\bstack\s+trace\b",
    r"\bprivate\s+internal\s+data\b",
)

FOLLOW_UP_REFERENCES = (
    "that site",
    "that meter",
    "same month",
    "same period",
    "compare it",
    "compare them",
    "the hotel",
    "the factory",
    "what about",
)


class ScopeGuard:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def classify(
        self,
        question: str,
        *,
        history: Optional[Sequence[Mapping[str, str]]] = None,
    ) -> ScopeDecision:
        text = question.strip()
        lowered = text.casefold()
        history_text = "\n".join(
            item.get("content", "")
            for item in (history or [])[-8:]
            if item.get("role") in {"user", "assistant"}
        )
        combined = f"{history_text}\n{text}" if history_text else text
        combined_lower = combined.casefold()

        sensitive = [
            pattern
            for pattern in SENSITIVE_OR_INJECTION_PATTERNS
            if re.search(pattern, lowered)
        ]
        if sensitive:
            return ScopeDecision(
                state=ScopeState.OUT_OF_SCOPE,
                confidence=0.99,
                reason=(
                    "The request seeks restricted internals, secrets, or instruction "
                    "override behavior rather than energy analytics."
                ),
                deterministic_matches=tuple(sensitive),
            )

        for capability, terms, reason in UNSUPPORTED_CAPABILITIES:
            matches = tuple(term for term in terms if term in lowered)
            if matches:
                return ScopeDecision(
                    state=ScopeState.ENERGY_BUT_UNSUPPORTED,
                    confidence=0.98,
                    reason=reason,
                    deterministic_matches=(capability, *matches),
                )

        tool_hint, intent_matches = match_intent(text)
        if tool_hint is None and history_text:
            tool_hint, intent_matches = match_intent(combined)
        entity_matches = tuple(self._known_entity_matches(combined))
        energy_matches = tuple(
            term for term in SUPPORTED_TERMS if term in combined_lower
        )
        tool_capability_matches = tuple(
            schema["name"]
            for schema in self.registry.schemas
            if any(
                token in combined_lower
                for token in _capability_tokens(
                    schema["name"], schema.get("description", "")
                )
            )
        )

        deterministic = tuple(
            dict.fromkeys(
                (
                    *intent_matches,
                    *entity_matches,
                    *energy_matches,
                    *tool_capability_matches,
                )
            )
        )
        if tool_hint or entity_matches or tool_capability_matches:
            return ScopeDecision(
                state=ScopeState.IN_SCOPE,
                confidence=0.99 if tool_hint else 0.94,
                reason=(
                    "Deterministic capability or cached-entity matching identifies "
                    "an available energy analytics path."
                ),
                deterministic_matches=deterministic,
                suggested_tool=tool_hint,
            )

        if energy_matches:
            if (
                any(reference in lowered for reference in FOLLOW_UP_REFERENCES)
                and not history_text
            ):
                return ScopeDecision(
                    state=ScopeState.NEEDS_CLARIFICATION,
                    confidence=0.91,
                    reason=(
                        "The request uses an unresolved follow-up reference and no "
                        "conversation context is available."
                    ),
                    deterministic_matches=energy_matches,
                    missing_information=("referenced entity or period",),
                )
            return ScopeDecision(
                state=ScopeState.IN_SCOPE,
                confidence=0.82,
                reason=(
                    "The request contains supported energy terminology; tool "
                    "resolution must be attempted before any refusal."
                ),
                deterministic_matches=energy_matches,
                suggested_tool=tool_hint,
            )

        if any(reference in lowered for reference in FOLLOW_UP_REFERENCES):
            if history_text and any(term in combined_lower for term in SUPPORTED_TERMS):
                return ScopeDecision(
                    state=ScopeState.IN_SCOPE,
                    confidence=0.88,
                    reason="Conversation history resolves this as an energy follow-up.",
                    deterministic_matches=("conversation_follow_up",),
                )
            return ScopeDecision(
                state=ScopeState.NEEDS_CLARIFICATION,
                confidence=0.84,
                reason="The follow-up reference cannot be resolved safely.",
                deterministic_matches=("unresolved_follow_up",),
                missing_information=("referenced entity or period",),
            )

        return ScopeDecision(
            state=ScopeState.OUT_OF_SCOPE,
            confidence=0.90,
            reason=(
                "No registered energy capability, cached entity, supported metric, "
                "or energy terminology was identified."
            ),
        )

    def _known_entity_matches(self, text: str) -> Iterable[str]:
        normalized_text = f" {normalize_name(text)} "
        try:
            hierarchy = self.registry.tools.cache.load_hierarchy()
        except Exception:
            return ()
        matches = []
        for kind, collection in (
            ("organization", hierarchy.organizations),
            ("site", hierarchy.sites),
            ("meter", hierarchy.meters),
        ):
            for entity in collection:
                normalized = normalize_name(entity.name)
                variants = {normalized}
                if normalized.endswith("s"):
                    variants.add(normalized[:-1])
                else:
                    variants.add(normalized + "s")
                if any(f" {variant} " in normalized_text for variant in variants):
                    matches.append(f"{kind}:{entity.name}")
        if " food corp " in normalized_text:
            matches.append("organization_alias:Food Corp.")
        if " best resorts hotel " in normalized_text:
            matches.append("organization_alias:Best Resorts Hotel")
        return matches


def match_intent(text: str) -> tuple[Optional[str], tuple[str, ...]]:
    lowered = text.casefold()
    rank_match = re.search(r"\b(?:rank|ranking)\b.*\b(?:site|sites)\b", lowered)
    if rank_match:
        return "rank_sites", (rank_match.group(0),)
    peak_match = re.search(
        r"\b(?:what|show|give|when|time|highest|maximum)\b.*\bpeak(?:\s+demand)?\b",
        lowered,
    )
    if peak_match:
        return "get_peak_demand", (peak_match.group(0),)
    for tool_name, patterns in INTENT_PATTERNS:
        matches = tuple(pattern for pattern in patterns if re.search(pattern, lowered))
        if matches:
            return tool_name, matches
    return None, ()


def _capability_tokens(name: str, description: str) -> tuple[str, ...]:
    stop = {
        "get",
        "compare",
        "calculate",
        "estimate",
        "return",
        "the",
        "and",
        "with",
        "for",
        "use",
        "data",
    }
    values = re.findall(r"[a-z][a-z_ -]{2,}", name.casefold())
    values.extend(re.findall(r"\b[a-z]{4,}\b", description.casefold()))
    tokens = []
    for value in values:
        for token in re.split(r"[_ -]+", value):
            if token not in stop and len(token) >= 4:
                tokens.append(token)
    return tuple(dict.fromkeys(tokens))

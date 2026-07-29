"""Validation boundary for deterministic tool outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


@dataclass(frozen=True)
class ValidatedToolResult:
    name: str
    arguments: Dict[str, Any]
    result: Dict[str, Any]

    @property
    def status(self) -> str:
        return str(self.result["status"])

    def provenance_payload(self) -> dict:
        return {"source_tool": self.name, "result": self.result}


class ToolResultValidationError(ValueError):
    """A tool returned an invalid structured contract."""


def validate_tool_result(
    name: str,
    arguments: Mapping[str, Any],
    result: Any,
) -> ValidatedToolResult:
    if not isinstance(result, Mapping):
        raise ToolResultValidationError(
            f"{name} returned {type(result).__name__}, not a JSON object."
        )
    payload = dict(result)
    status = payload.get("status")
    if status not in {"ok", "empty", "error"}:
        raise ToolResultValidationError(
            f"{name} returned an invalid status {status!r}."
        )
    if status == "ok" and len(payload) <= 1:
        raise ToolResultValidationError(
            f"{name} returned status ok without factual fields."
        )
    if status in {"empty", "error"} and not (
        payload.get("message") or payload.get("warnings")
    ):
        payload["message"] = (
            "No factual result is available."
            if status == "empty"
            else "The tool reported an error."
        )
    return ValidatedToolResult(
        name=name,
        arguments=dict(arguments),
        result=payload,
    )

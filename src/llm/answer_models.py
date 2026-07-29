"""Structured intermediate answer representation and safe UI rendering."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AnswerStatus = Literal[
    "answered",
    "clarification_needed",
    "unsupported",
    "out_of_scope",
    "data_unavailable",
    "tool_error",
]


class AnswerFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    source_tool: str
    source_field: str


class AnswerEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AnswerStatus
    answer: str
    facts: list[AnswerFact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def render_answer(envelope: AnswerEnvelope) -> str:
    parts = [envelope.answer.strip()]
    if envelope.warnings:
        parts.append(
            "Warnings:\n" + "\n".join(f"- {warning}" for warning in envelope.warnings)
        )
    if envelope.limitations:
        parts.append(
            "Limitations:\n"
            + "\n".join(f"- {limitation}" for limitation in envelope.limitations)
        )
    return "\n\n".join(part for part in parts if part)

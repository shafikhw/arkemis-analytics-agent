"""OpenAI client construction isolated for testing."""

from __future__ import annotations

from openai import OpenAI


def build_openai_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, timeout=60.0, max_retries=2)

from __future__ import annotations

import json
from datetime import date

import httpx
from openai import OpenAI

from src.llm.orchestrator import EnergyAssistant


class Registry:
    schemas = [
        {
            "type": "function",
            "name": "get_total",
            "description": "Return a deterministic total.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "organization": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                },
                "required": ["organization", "start_date", "end_date"],
                "additionalProperties": False,
            },
        }
    ]

    def execute(self, name, arguments):
        assert name == "get_total"
        return {
            "status": "ok",
            "total_energy_kwh": 24.0,
            "period": {
                "start_date_inclusive": arguments["start_date"],
                "end_date_exclusive": arguments["end_date"],
            },
        }


def _base_response(response_id, output):
    return {
        "id": response_id,
        "object": "response",
        "created_at": 1782864000,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "model": "test-model",
        "output": output,
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "store": False,
        "temperature": 1.0,
        "text": {"format": {"type": "text"}, "verbosity": "medium"},
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1.0,
        "truncation": "disabled",
        "usage": {
            "input_tokens": 10,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 5,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 15,
        },
        "metadata": {},
    }


def test_real_sdk_serialization_with_mock_transport():
    request_bodies = []

    def handler(request):
        body = json.loads(request.content.decode("utf-8"))
        request_bodies.append(body)
        if len(request_bodies) == 1:
            payload = _base_response(
                "resp_1",
                [
                    {
                        "id": "fc_1",
                        "type": "function_call",
                        "status": "completed",
                        "arguments": json.dumps(
                            {
                                "organization": "Food Corp.",
                                "start_date": "2026-06-01",
                                "end_date": "2026-07-01",
                            }
                        ),
                        "call_id": "call_1",
                        "name": "get_total",
                    }
                ],
            )
        else:
            answer = json.dumps(
                {
                    "status": "answered",
                    "answer": "Food Corp. used 24.0 kWh.",
                    "facts": [
                        {
                            "label": "Consumption",
                            "value": "24.0 kWh",
                            "source_tool": "get_total",
                            "source_field": "$.total_energy_kwh",
                        }
                    ],
                    "warnings": [],
                    "limitations": [],
                }
            )
            payload = _base_response(
                "resp_2",
                [
                    {
                        "id": "msg_1",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "annotations": [],
                                "logprobs": [],
                                "text": answer,
                            }
                        ],
                    }
                ],
            )
        return httpx.Response(200, json=payload, request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAI(
        api_key="test-key",
        base_url="https://unit.test/v1",
        http_client=http_client,
        max_retries=0,
    )
    assistant = EnergyAssistant(
        client,
        model="test-model",
        registry=Registry(),
        max_tool_rounds=3,
        today_provider=lambda: date(2026, 7, 29),
    )
    result = assistant.ask("What was total consumption at Food Corp. last month?")

    assert result.answer == "Food Corp. used 24.0 kWh."
    assert result.grounding_status == "passed"
    assert result.usage["total_tokens"] == 30
    assert request_bodies[0]["tools"][0]["strict"] is True
    outputs = [
        item
        for item in request_bodies[1]["input"]
        if item.get("type") == "function_call_output"
    ]
    assert outputs[0]["call_id"] == "call_1"
    assert json.loads(outputs[0]["output"])["total_energy_kwh"] == 24.0

from __future__ import annotations

import pytest

from src.api.exceptions import (
    WatticsAuthenticationError,
    WatticsNotFoundError,
    WatticsPermissionError,
    WatticsRateLimitError,
    WatticsResponseError,
    WatticsServerError,
)
from src.api.wattics_client import WatticsClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.requests = []

    def mount(self, *_):
        pass

    def request(self, method, url, params=None, timeout=None):
        self.requests.append(
            {"method": method, "url": url, "params": params, "timeout": timeout}
        )
        return self.responses.pop(0)

    def close(self):
        pass


def client(*responses):
    return WatticsClient("secret", session=FakeSession(responses), max_retries=0)


def test_list_organizations_validates_shape():
    value = client(FakeResponse(payload=[{"id": 1, "name": "Org"}]))
    assert value.list_organizations() == [{"id": 1, "name": "Org"}]


def test_missing_required_response_field_rejected():
    value = client(FakeResponse(payload=[{"id": 1}]))
    with pytest.raises(WatticsResponseError, match="missing required"):
        value.list_organizations()


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, WatticsAuthenticationError),
        (403, WatticsPermissionError),
        (404, WatticsNotFoundError),
        (429, WatticsRateLimitError),
        (503, WatticsServerError),
    ],
)
def test_http_status_mapping(status, error):
    value = client(FakeResponse(status_code=status, payload={}))
    with pytest.raises(error):
        value.list_organizations()


def test_non_json_response_rejected():
    value = client(FakeResponse(payload=None, json_error=True))
    with pytest.raises(WatticsResponseError, match="non-JSON"):
        value.list_organizations()


def test_partner_style_pagination():
    session = FakeSession(
        [
            FakeResponse(payload=[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]),
            FakeResponse(payload=[{"id": 3, "name": "C"}]),
        ]
    )
    value = WatticsClient("secret", session=session, max_retries=0)
    rows = value.list_paginated_resources("/meters", page_size=2)
    assert [row["id"] for row in rows] == [1, 2, 3]
    assert session.requests[1]["params"]["pageNumber"] == "2"

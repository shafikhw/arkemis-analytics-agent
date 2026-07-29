from __future__ import annotations

from src.data.discovery import match_organization


def test_normalized_and_similar_organization_matching():
    organizations = [
        {"id": "a", "name": "Food Corp."},
        {"id": "b", "name": "Best Resorts Hotels"},
    ]
    exact = match_organization("food corp", organizations)
    similar = match_organization("Best Resorts Hotel", organizations)
    missing = match_organization("Unknown Company", organizations)
    assert exact["status"] == "found"
    assert similar["status"] == "similar"
    assert similar["organization"]["id"] == "b"
    assert missing["status"] == "not_found"

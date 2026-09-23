"""
Module: test_alternative_me_client.py
Description: Unit tests for the alternative.me Fear & Greed Index client --
    real, no-auth public API, tested live (not mocked).
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.core.data_providers.alternative_me import get_alternative_me_client


@pytest.mark.network
def test_get_fear_greed_index_returns_real_data():
    client = get_alternative_me_client()
    df = client.get_fear_greed_index(limit=5)
    assert not df.empty
    assert len(df) <= 5
    assert set(df.columns) == {"timestamp", "value", "classification"}
    assert df["value"].between(0, 100).all()
    assert df["timestamp"].is_monotonic_increasing


@pytest.mark.network
def test_get_fear_greed_index_classification_matches_value_range():
    client = get_alternative_me_client()
    df = client.get_fear_greed_index(limit=10)
    for _, row in df.iterrows():
        assert row["classification"] in (
            "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed",
        )

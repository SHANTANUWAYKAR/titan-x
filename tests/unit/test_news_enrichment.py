"""Unit tests for the Phase 11 news enrichment pipeline (E03).

engines/e03_news/enrichment.py: deterministic entity extraction, event-type
classification, market-impact scoring, and content-hash dedup.
"""

from project_titan_x.engines.e03_news.enrichment import (
    EVENT_TYPE_WEIGHTS,
    classify_event_type,
    extract_entities,
    market_impact_score,
    normalized_content_hash,
)


def test_extract_entities_matches_known_symbols():
    assert extract_entities("Gold rallies as the Fed signals a rate cut") == ["GOLD"]
    assert extract_entities("Bitcoin and Ethereum both surge on ETF inflows") == ["BTCUSD", "ETHUSD"]


def test_extract_entities_matches_equity_company_names():
    assert extract_entities("Apple unveils new iPhone lineup") == ["AAPL"]
    assert extract_entities("Reliance Industries posts record quarterly profit") == ["RELIANCE"]


def test_extract_entities_returns_empty_list_when_nothing_matches():
    assert extract_entities("A completely unrelated headline about weather patterns") == []


def test_extract_entities_handles_empty_text():
    assert extract_entities("") == []
    assert extract_entities(None) == []


def test_extract_entities_is_whole_word_not_substring():
    # "goldman" contains "gold" as a substring but must not match the
    # GOLD symbol -- whole-word matching, not naive substring search.
    assert "GOLD" not in extract_entities("Goldman Sachs reports quarterly earnings")


def test_classify_event_type_monetary_policy():
    assert classify_event_type("Federal Reserve raises interest rate by 25bps") == "monetary_policy"


def test_classify_event_type_earnings():
    assert classify_event_type("Apple beats estimates in quarterly results") == "earnings"


def test_classify_event_type_geopolitical():
    assert classify_event_type("Ceasefire talks collapse amid renewed conflict") == "geopolitical"


def test_classify_event_type_corporate_action():
    assert classify_event_type("Company announces merger with rival firm") == "corporate_action"


def test_classify_event_type_defaults_to_other():
    assert classify_event_type("A pleasant afternoon in the park") == "other"


def test_classify_event_type_priority_order_favors_monetary_policy_over_earnings():
    # Headline mentions both a rate decision and an earnings term --
    # monetary_policy is checked first in EVENT_KEYWORDS' fixed order.
    text = "Fed rate cut overshadows Apple earnings report"
    assert classify_event_type(text) == "monetary_policy"


def test_market_impact_score_is_abs_sentiment_times_event_weight():
    score = market_impact_score(-0.5, "monetary_policy")
    assert score == round(0.5 * EVENT_TYPE_WEIGHTS["monetary_policy"], 4)


def test_market_impact_score_none_without_a_sentiment_score():
    assert market_impact_score(None, "earnings") is None


def test_market_impact_score_uses_default_weight_for_other():
    assert market_impact_score(0.4, "other") == round(0.4 * EVENT_TYPE_WEIGHTS["other"], 4)


def test_normalized_content_hash_is_stable_across_case_and_punctuation():
    a = normalized_content_hash("Fed Raises Rates!")
    b = normalized_content_hash("fed raises rates")
    assert a == b


def test_normalized_content_hash_differs_for_different_titles():
    a = normalized_content_hash("Fed raises rates")
    b = normalized_content_hash("Fed cuts rates")
    assert a != b


def test_normalized_content_hash_collapses_whitespace():
    a = normalized_content_hash("Fed   raises    rates")
    b = normalized_content_hash("Fed raises rates")
    assert a == b

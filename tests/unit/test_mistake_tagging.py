"""
Module: test_mistake_tagging.py
Description: Unit tests for engines/e35_performance_analytics/
    mistake_tagging.py -- see that module's docstring for provenance.
Author: Shantanu Waykar
Version: 1.0.0
"""

from datetime import datetime, timezone

from project_titan_x.engines.e35_performance_analytics.mistake_tagging import (
    TradeRecord,
    evaluate_all_rules,
)

DEFAULT_RULE_MAP = {
    "below_confluence_threshold": {"enabled": True, "params": {"min_confidence": 65}},
    "outside_killzone": {"enabled": True, "params": {}},
    "position_size_exceeded": {"enabled": True, "params": {"max_risk_percent": 1.0}},
    "revenge_trade": {"enabled": True, "params": {"cooldown_minutes": 30}},
    "overtrading_session": {"enabled": True, "params": {"max_trades_per_day": 5}},
    "traded_in_daily_loss_red_zone": {"enabled": True, "params": {"max_daily_loss_pct": 5.0, "red_zone_threshold_pct": 25.0}},
    "consecutive_loss_violation": {"enabled": True, "params": {"max_consecutive_losses": 5}},
    "kelly_sizing_exceeded": {"enabled": True, "params": {"margin_multiplier": 1.5}},
    "overrode_disagreeing_layer": {"enabled": True, "params": {}},
}


def _t(id, entry, exit_, pnl_r=0.5, pnl_pct=0.5, confidence=80, risk=None, kelly=None, disagreeing=None):
    return TradeRecord(
        id=id, entry_time=entry, exit_time=exit_, pnl_r=pnl_r, pnl_percent=pnl_pct,
        confidence_at_entry=confidence, risk_percent_used=risk,
        kelly_recommended_risk_pct=kelly, signal_had_disagreeing_layer=disagreeing,
    )


def _utc(y, m, d, h=12, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_clean_trade_gets_no_tags():
    # NY Open (12:00-15:00 UTC in January), high confidence, no history.
    trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0), confidence=85)
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    assert tags == []


def test_below_confluence_threshold_fires():
    trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0), confidence=50)
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    keys = [t.tag_key for t in tags]
    assert "below_confluence_threshold" in keys
    tag = next(t for t in tags if t.tag_key == "below_confluence_threshold")
    assert tag.detail == {"required": 65, "actual": 50}
    assert tag.category == "rule_adherence"
    assert tag.negative is True


def test_below_confluence_threshold_skipped_when_confidence_missing():
    trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0), confidence=None)
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    assert "below_confluence_threshold" not in [t.tag_key for t in tags]


def test_outside_killzone_fires_in_a_real_dead_zone():
    # 18:30 UTC in January is a confirmed dead zone (see test_killzones.py).
    trade = _t(1, _utc(2026, 1, 15, 18, 30), _utc(2026, 1, 15, 19, 0))
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    assert "outside_killzone" in [t.tag_key for t in tags]


def test_outside_killzone_does_not_fire_inside_ny_open():
    trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0))
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    assert "outside_killzone" not in [t.tag_key for t in tags]


def test_position_size_exceeded_fires_when_provided_and_over_limit():
    trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0), risk=2.5)
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    tag = next(t for t in tags if t.tag_key == "position_size_exceeded")
    assert tag.detail == {"max_allowed": 1.0, "actual": 2.5}


def test_position_size_exceeded_skipped_when_not_provided():
    trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0), risk=None)
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    assert "position_size_exceeded" not in [t.tag_key for t in tags]


def test_kelly_sizing_exceeded_fires_when_over_margin():
    # kelly=1.0%, margin_multiplier=1.5 -> max_allowed=1.5%; actual 2.0% exceeds it.
    trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0), risk=2.0, kelly=1.0)
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    tag = next(t for t in tags if t.tag_key == "kelly_sizing_exceeded")
    assert tag.detail == {
        "kelly_recommended_pct": 1.0, "margin_multiplier": 1.5,
        "max_allowed_pct": 1.5, "actual_pct": 2.0,
    }


def test_kelly_sizing_within_margin_does_not_fire():
    trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0), risk=1.2, kelly=1.0)
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    assert "kelly_sizing_exceeded" not in [t.tag_key for t in tags]


def test_kelly_sizing_skipped_when_kelly_recommendation_absent():
    trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0), risk=5.0, kelly=None)
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    assert "kelly_sizing_exceeded" not in [t.tag_key for t in tags]


def test_overrode_disagreeing_layer_fires_when_true():
    trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0), disagreeing=True)
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    assert "overrode_disagreeing_layer" in [t.tag_key for t in tags]


def test_overrode_disagreeing_layer_does_not_fire_when_false_or_none():
    for value in (False, None):
        trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0), disagreeing=value)
        tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
        assert "overrode_disagreeing_layer" not in [t.tag_key for t in tags]


def test_revenge_trade_fires_after_a_quick_loss():
    previous = _t(1, _utc(2026, 1, 15, 9, 0), _utc(2026, 1, 15, 9, 40), pnl_r=-1.0)
    trade = _t(2, _utc(2026, 1, 15, 10, 0), _utc(2026, 1, 15, 10, 30))  # 20 min after previous exit
    tags = evaluate_all_rules(trade, [previous], DEFAULT_RULE_MAP)
    tag = next(t for t in tags if t.tag_key == "revenge_trade")
    assert tag.detail["actual_gap_minutes"] == 20.0
    assert tag.detail["previous_trade_pnl_r"] == -1.0


def test_revenge_trade_does_not_fire_after_a_win():
    previous = _t(1, _utc(2026, 1, 15, 9, 0), _utc(2026, 1, 15, 9, 40), pnl_r=1.5)
    trade = _t(2, _utc(2026, 1, 15, 10, 0), _utc(2026, 1, 15, 10, 30))
    tags = evaluate_all_rules(trade, [previous], DEFAULT_RULE_MAP)
    assert "revenge_trade" not in [t.tag_key for t in tags]


def test_revenge_trade_does_not_fire_outside_cooldown():
    previous = _t(1, _utc(2026, 1, 15, 9, 0), _utc(2026, 1, 15, 9, 40), pnl_r=-1.0)
    trade = _t(2, _utc(2026, 1, 15, 11, 0), _utc(2026, 1, 15, 11, 30))  # 80 min after previous exit
    tags = evaluate_all_rules(trade, [previous], DEFAULT_RULE_MAP)
    assert "revenge_trade" not in [t.tag_key for t in tags]


def test_revenge_trade_flags_size_increase_when_both_have_risk_data():
    previous = _t(1, _utc(2026, 1, 15, 9, 0), _utc(2026, 1, 15, 9, 40), pnl_r=-1.0, risk=0.5)
    trade = _t(2, _utc(2026, 1, 15, 10, 0), _utc(2026, 1, 15, 10, 30), risk=1.5)
    tags = evaluate_all_rules(trade, [previous], DEFAULT_RULE_MAP)
    tag = next(t for t in tags if t.tag_key == "revenge_trade")
    assert tag.detail["size_increased"] is True


def test_overtrading_session_fires_on_the_6th_trade_same_day():
    others = [_t(i, _utc(2026, 1, 15, 6 + i, 0), _utc(2026, 1, 15, 6 + i, 30)) for i in range(5)]
    trade = _t(99, _utc(2026, 1, 15, 20, 0), _utc(2026, 1, 15, 20, 30))
    tags = evaluate_all_rules(trade, others, DEFAULT_RULE_MAP)
    tag = next(t for t in tags if t.tag_key == "overtrading_session")
    assert tag.detail == {"max_allowed": 5, "actual": 6}


def test_overtrading_session_ignores_other_days():
    others = [_t(i, _utc(2026, 1, 14, 6 + i, 0), _utc(2026, 1, 14, 6 + i, 30)) for i in range(5)]
    trade = _t(99, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 12, 30))
    tags = evaluate_all_rules(trade, others, DEFAULT_RULE_MAP)
    assert "overtrading_session" not in [t.tag_key for t in tags]


def test_daily_loss_red_zone_fires_when_thin():
    # Two prior same-day trades closing -3% and -1.5% (4.5% of a 5% daily budget used -> 10% remaining <= 25% threshold).
    prior = [
        _t(1, _utc(2026, 1, 15, 6, 0), _utc(2026, 1, 15, 7, 0), pnl_pct=-3.0),
        _t(2, _utc(2026, 1, 15, 8, 0), _utc(2026, 1, 15, 9, 0), pnl_pct=-1.5),
    ]
    trade = _t(3, _utc(2026, 1, 15, 10, 0), _utc(2026, 1, 15, 10, 30))
    tags = evaluate_all_rules(trade, prior, DEFAULT_RULE_MAP)
    tag = next(t for t in tags if t.tag_key == "traded_in_daily_loss_red_zone")
    assert tag.detail["daily_budget_remaining_pct"] == 10.0


def test_daily_loss_red_zone_does_not_fire_when_budget_healthy():
    prior = [_t(1, _utc(2026, 1, 15, 6, 0), _utc(2026, 1, 15, 7, 0), pnl_pct=-0.5)]
    trade = _t(2, _utc(2026, 1, 15, 10, 0), _utc(2026, 1, 15, 10, 30))
    tags = evaluate_all_rules(trade, prior, DEFAULT_RULE_MAP)
    assert "traded_in_daily_loss_red_zone" not in [t.tag_key for t in tags]


def test_consecutive_loss_violation_fires_after_5_straight_losses():
    prior = [_t(i, _utc(2026, 1, 15, i, 0), _utc(2026, 1, 15, i, 30), pnl_r=-0.5) for i in range(1, 6)]
    trade = _t(99, _utc(2026, 1, 15, 20, 0), _utc(2026, 1, 15, 20, 30))
    tags = evaluate_all_rules(trade, prior, DEFAULT_RULE_MAP)
    tag = next(t for t in tags if t.tag_key == "consecutive_loss_violation")
    assert tag.detail == {"limit": 5, "actual_streak": 5}


def test_consecutive_loss_violation_streak_breaks_on_a_win():
    # Most recent (by exit_time) is a WIN, so the streak resets to 0 even
    # though 5 losses happened earlier that day.
    prior = [_t(i, _utc(2026, 1, 15, i, 0), _utc(2026, 1, 15, i, 30), pnl_r=-0.5) for i in range(1, 6)]
    prior.append(_t(6, _utc(2026, 1, 15, 6, 0), _utc(2026, 1, 15, 6, 30), pnl_r=1.0))
    trade = _t(99, _utc(2026, 1, 15, 20, 0), _utc(2026, 1, 15, 20, 30))
    tags = evaluate_all_rules(trade, prior, DEFAULT_RULE_MAP)
    assert "consecutive_loss_violation" not in [t.tag_key for t in tags]


def test_disabled_rule_never_fires_even_when_it_would_have():
    rules = dict(DEFAULT_RULE_MAP)
    rules["below_confluence_threshold"] = {"enabled": False, "params": {"min_confidence": 65}}
    trade = _t(1, _utc(2026, 1, 15, 12, 0), _utc(2026, 1, 15, 13, 0), confidence=10)
    tags = evaluate_all_rules(trade, [], rules)
    assert "below_confluence_threshold" not in [t.tag_key for t in tags]


def test_multiple_rules_can_fire_on_the_same_trade():
    trade = _t(1, _utc(2026, 1, 15, 18, 30), _utc(2026, 1, 15, 19, 0), confidence=40)  # dead zone AND low confidence
    tags = evaluate_all_rules(trade, [], DEFAULT_RULE_MAP)
    keys = {t.tag_key for t in tags}
    assert {"below_confluence_threshold", "outside_killzone"}.issubset(keys)

"""
Module: test_failure_modes.py
Description: Failure engineering — `reports/upgrade statergy.txt` PHASE 27,
    raised as **P2.3** in docs/INSTITUTIONAL_AUDIT.md. Closes the quality-gate
    line "Failure handling tested".

    PHASE 27's requirement is one sentence: *"Never generate a trade simply
    because a subsystem stopped responding."* Before this file that was a
    convention held up by careful code review, not a property anything
    enforced. The distinction matters because the dangerous failures here are
    the quiet ones — a fetch that falls back to a stale cache, an engine that
    returns `success=False` into a caller that forgot to check, a data frame
    that is technically well-formed and arithmetically impossible.

    Each test names the subsystem it kills and asserts the system produced
    NOTHING rather than something confident. A skipped instrument is a
    recoverable gap; a fabricated signal is a trade.

Author: Shantanu Waykar
Version: 1.0.0
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from project_titan_x.core import heartbeat as hb
from project_titan_x.engines.e24_strategy_research import forward_test as ft
from project_titan_x.engines.e40_data_quality.engine import DataQualityEngine

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _frame(n=200, start=None, bad=None):
    """A well-formed OHLCV frame in this platform's native shape, optionally
    corrupted in one specific way."""
    start = start or NOW - timedelta(days=n)
    idx = pd.date_range(start, periods=n, freq="1D", tz="UTC")
    close = np.linspace(100, 120, n)
    df = pd.DataFrame({
        "timestamp": idx,
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.full(n, 1000.0),
    })
    if bad == "negative_price":
        df.loc[10, "close"] = -50.0
    elif bad == "high_below_low":
        df.loc[10, "high"] = 1.0
        df.loc[10, "low"] = 999.0
    elif bad == "nan_close":
        df.loc[10, "close"] = np.nan
    elif bad == "duplicate_timestamp":
        df.loc[11, "timestamp"] = df.loc[10, "timestamp"]
    return df


# --------------------------------------------------------------------------
# A dead subsystem must produce nothing, not a default
# --------------------------------------------------------------------------

class _Result:
    def __init__(self, data=None, success=True, message=""):
        self.data, self.success, self.message = data, success, message


class _Registry:
    """Engine registry whose `fail_at` engine returns success=False."""

    def __init__(self, fail_at=None, bars=None, signal=None, raises_at=None):
        self.fail_at, self.bars, self.signal, self.raises_at = fail_at, bars, signal, raises_at

    def get(self, name):
        reg, engine_name = self, name

        class _E:
            def fetch_ohlcv(self, sym, tf, years=2):
                if reg.raises_at == engine_name:
                    raise ConnectionError("provider unreachable")
                if reg.fail_at == engine_name:
                    return _Result(success=False, message="rate limited")
                return _Result(data=reg.bars)

            def repair(self, df):
                return _Result(data=df)

            def analyze(self, df=None, symbol=None, timeframe=None):
                if reg.raises_at == engine_name:
                    raise RuntimeError("engine exploded")
                if reg.fail_at == engine_name:
                    return _Result(success=False, message="insufficient data")
                return _Result(data={"snapshot": object(), "df": df})

            def classify(self, df, snap, macro):
                if reg.fail_at == engine_name:
                    return _Result(success=False, message="cannot classify")
                return _Result(data=object())

            def generate_signal(self, *a, **k):
                return _Result(data=reg.signal, message="" if reg.signal else "no signal")

        if name == "e04_macro":
            class _Macro(_E):
                def analyze(self, *a, **k):
                    return _Result(data=None)
            return _Macro()
        return _E()


class _Signal:
    asset, direction = "ETHUSD", "LONG"
    entry, stop_loss, take_profit_1 = 100.0, 95.0, 110.0
    confidence_score = 80


def _override(tmp_path):
    import json
    (tmp_path / "ETH-USD_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "mss_trend_hold", "params": {"hold_bars": 5},
        "win_rate": 0.625, "total_trades": 64,
        "stage0": {"status": "VALIDATED", "measured": {"null_percentile": 100.0}},
    }), encoding="utf-8")
    return ft.validated_overrides(tmp_path)


@pytest.mark.parametrize("dead", ["e02_market_data", "e07_technical", "e08_regime"])
def test_a_dead_engine_produces_no_prediction(tmp_path, dead):
    """Each engine in the live chain, killed in turn. A gap in the evidence is
    recoverable; a prediction invented to fill it is not."""
    log = tmp_path / "log.jsonl"
    reg = _Registry(fail_at=dead, bars=_frame(), signal=_Signal())
    out = ft.scan_and_record(reg, _override(tmp_path), log_path=log, now=NOW)
    assert out["recorded"] == []
    assert len(out["skipped"]) == 1
    assert ft.load_log(log) == []


@pytest.mark.parametrize("dead", ["e02_market_data", "e07_technical"])
def test_an_engine_that_raises_is_caught_and_skipped(tmp_path, dead):
    """A raised exception must be as survivable as a returned failure -- one
    instrument must never take down a scan over all of them."""
    log = tmp_path / "log.jsonl"
    reg = _Registry(raises_at=dead, bars=_frame(), signal=_Signal())
    out = ft.scan_and_record(reg, _override(tmp_path), log_path=log, now=NOW)
    assert out["recorded"] == []
    assert len(out["skipped"]) == 1
    assert ft.load_log(log) == []


def test_an_empty_data_frame_produces_no_prediction(tmp_path):
    log = tmp_path / "log.jsonl"
    reg = _Registry(bars=pd.DataFrame(), signal=_Signal())
    out = ft.scan_and_record(reg, _override(tmp_path), log_path=log, now=NOW)
    assert out["recorded"] == []
    assert ft.load_log(log) == []


# --------------------------------------------------------------------------
# Stale data must not become a confident signal
# --------------------------------------------------------------------------

def test_a_stale_feed_is_refused_rather_than_traded(tmp_path):
    """The failure this is named for: a fetch chain that falls back to an old
    cache returns a perfectly well-formed frame. Nothing about its SHAPE says
    it is out of date."""
    log = tmp_path / "log.jsonl"
    stale = _frame(n=50, start=NOW - timedelta(days=400))
    reg = _Registry(bars=stale, signal=_Signal())
    out = ft.scan_and_record(reg, _override(tmp_path), log_path=log, now=NOW)
    assert out["recorded"] == []
    assert any("REFUSED" in why for _, why in out["skipped"])
    assert ft.load_log(log) == []


def test_an_abandoned_feed_is_stale_for_every_asset_class():
    ancient = NOW - timedelta(days=60)
    for sym in ("BTC-USD", "EURUSD=X", "AAPL", "GC=F"):
        assert hb.data_staleness_verdict(sym, "1d", ancient, NOW)["state"] == "stale"


def test_a_closed_market_is_not_mistaken_for_a_dead_feed():
    """The inverse failure, and the more insidious one: an alarm that fires
    every weekend stops being read before the real outage arrives."""
    friday = datetime(2026, 9, 11, tzinfo=timezone.utc)
    tuesday = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    assert hb.data_staleness_verdict("AAPL", "1d", friday, tuesday)["state"] == "ok"


# --------------------------------------------------------------------------
# Corrupted data must be detected, not silently consumed
# --------------------------------------------------------------------------

@pytest.mark.parametrize("corruption", [
    "negative_price", "high_below_low", "nan_close", "duplicate_timestamp",
])
def test_corrupted_bars_are_detected(corruption):
    """PHASE 3: 'Do not allow corrupted data into research silently.'"""
    engine = DataQualityEngine()
    engine.initialize()
    clean = engine.validate(_frame())
    dirty = engine.validate(_frame(bad=corruption))
    assert clean.success
    clean_score = getattr(clean.data, "quality_score", None)
    dirty_score = getattr(dirty.data, "quality_score", None)
    if clean_score is not None and dirty_score is not None:
        assert dirty_score < clean_score, f"{corruption} did not lower the quality score"
    else:
        # Older report shape: fall back to asserting an issue was recorded.
        assert getattr(dirty.data, "issues", None), f"{corruption} produced no issue"


# --------------------------------------------------------------------------
# Observability must survive its own failures
# --------------------------------------------------------------------------

def test_a_broken_heartbeat_store_does_not_break_the_job(tmp_path):
    """Recording is best-effort BY CONTRACT: the monitor must never be the
    reason the monitored work fails."""
    blocked = tmp_path / "a-file" / "beats.json"
    (tmp_path / "a-file").write_text("not a directory", encoding="utf-8")
    hb.record_success("job", 60, blocked)
    hb.record_failure("job", "err", 60, blocked)


def test_a_corrupt_heartbeat_store_does_not_report_healthy(tmp_path):
    """Losing the state file must fail LOUD, not silent -- an unreadable
    monitor that reports 'ok' is worse than no monitor."""
    p = tmp_path / "beats.json"
    p.write_text("{truncated", encoding="utf-8")
    statuses = hb.check({"forward_test": 3600}, p, now=NOW)
    assert hb.overall_state(statuses) == "degraded"


def test_a_missing_forward_test_log_is_not_an_error(tmp_path):
    """Absence of evidence must read as absence, not as a crash or as a
    passing result."""
    summary = ft.summarise(tmp_path / "never-created.jsonl")
    assert summary["total_predictions"] == 0
    assert summary["series"] == []

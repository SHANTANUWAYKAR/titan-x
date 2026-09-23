"""
Module: test_research_pipeline_integration.py
Description: End-to-end integration across the research-governance chain —
    `reports/upgrade statergy.txt` PHASE 28 ("integration tests"), the last
    `[ ]` on the quality gate that could be closed without new infrastructure.

    WHY THIS EXISTS SEPARATELY FROM THE UNIT TESTS. Every module in this chain
    is already unit-tested in isolation, and all of those passed while three
    real seam defects sat between them: `df.index[-1]` returning a row number
    because the frame shape differed from what the caller assumed, a resolver
    that rejected the only frame shape the platform actually produces, and a
    catalog keyed by a different symbol spelling than its callers use. Each was
    invisible to both sides' own tests. This file exercises the seams.

    The chain under test, with no network and no database:

        validated override  ->  scan_and_record   (a prediction is written)
                            ->  resolve_pending   (real bars settle it)
                            ->  summarise         (evidence is scored)
                            ->  compare_to_backtest (verdict vs the claim)
                            ->  hypothesis + experiment lineage

    Each stage consumes the previous stage's real output, never a fixture
    shaped like it.

Author: Shantanu Waykar
Version: 1.0.0
"""

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from project_titan_x.core import experiment as ex
from project_titan_x.core import heartbeat as hb
from project_titan_x.engines.e24_strategy_research import forward_test as ft
from project_titan_x.engines.e24_strategy_research import hypothesis as hyp

NOW = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)
BAR = NOW.replace(hour=0)


class _Result:
    def __init__(self, data=None, success=True, message=""):
        self.data, self.success, self.message = data, success, message


class _Signal:
    asset, direction = "ETHUSD", "LONG"
    entry, stop_loss, take_profit_1 = 100.0, 95.0, 110.0
    confidence_score = 71


def _native_frame(rows, start):
    """The platform's real OHLCV shape: RangeIndex, time in `timestamp`, and
    an all-null `date` column — the exact combination that produced the row
    number `729` on the forward test's first live run."""
    return pd.DataFrame({
        "date": [None] * len(rows),
        "timestamp": pd.to_datetime(
            [start + timedelta(days=i) for i in range(len(rows))], utc=True),
        "open": [r[2] for r in rows],
        "high": [r[0] for r in rows], "low": [r[1] for r in rows],
        "close": [r[2] for r in rows], "volume": [1000.0] * len(rows),
    })


class _Registry:
    def __init__(self, bars, signal):
        self.bars, self.signal = bars, signal

    def get(self, name):
        reg = self

        class _E:
            def fetch_ohlcv(self, sym, tf, years=2):
                return _Result(data=reg.bars)

            def repair(self, df):
                return _Result(data=df)

            def analyze(self, df=None, symbol=None, timeframe=None):
                return _Result(data={"snapshot": object(), "df": df})

            def classify(self, df, snap, macro):
                return _Result(data=object())

            def generate_signal(self, *a, **k):
                return _Result(data=reg.signal)

        if name == "e04_macro":
            class _Macro(_E):
                def analyze(self, *a, **k):
                    return _Result(data=None)
            return _Macro()
        return _E()


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "ETH-USD_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "mss_trend_hold", "params": {"hold_bars": 5},
        "win_rate": 0.625, "total_trades": 64, "is_sharpe": 1.12, "oos_sharpe": 1.08,
        "stage0": {"status": "VALIDATED", "measured": {"null_percentile": 100.0}},
    }), encoding="utf-8")
    return tmp_path


def test_a_prediction_flows_from_signal_to_scored_verdict(workspace):
    """The whole chain on one instrument, each stage fed the previous stage's
    actual output."""
    log = workspace / "forward.jsonl"
    overrides = ft.validated_overrides(workspace)
    assert [o["strategy"] for o in overrides] == ["mss_trend_hold"]

    # 1. Record -- the frame is the platform's native shape, so this exercises
    #    bar_timestamp rather than assuming a DatetimeIndex.
    reg = _Registry(_native_frame([(101, 99, 100)], BAR), _Signal())
    out = ft.scan_and_record(reg, overrides, log_path=log, now=NOW)
    assert len(out["recorded"]) == 1

    rec = ft.load_log(log)[0]
    assert rec.horizon_bars == 5                       # from the override params
    assert rec.backtest_claim["win_rate"] == 0.625     # claim frozen at record time
    assert rec.resolved is False

    # 2. Resolve -- target at 110 is hit on the first subsequent bar: +2.0R
    bars = _native_frame([(101, 99, 100), (111, 99, 110)], BAR)
    written = ft.resolve_pending(lambda s, tf: bars, log_path=log)
    assert len(written) == 1 and written[0]["outcome"] == "target"

    settled = ft.load_log(log)[0]
    assert settled.r_multiple == pytest.approx(2.0)
    assert settled.is_win is True

    # 3. Summarise -- one win is real evidence but not a verdict
    summary = ft.summarise(log)
    series = summary["series"][0]
    assert series["forward_trades"] == 1
    assert series["verdict"] == "insufficient_evidence"
    assert series["planned_reward_risk"] == pytest.approx(2.0)
    assert series["breakeven_win_rate"] == pytest.approx(1 / 3, abs=1e-3)


def test_the_prediction_line_is_never_rewritten_by_resolution(workspace):
    """Append-only across the seam, not just within one module."""
    log = workspace / "forward.jsonl"
    reg = _Registry(_native_frame([(101, 99, 100)], BAR), _Signal())
    ft.scan_and_record(reg, ft.validated_overrides(workspace), log_path=log, now=NOW)
    before = log.read_text(encoding="utf-8")

    ft.resolve_pending(
        lambda s, tf: _native_frame([(101, 99, 100), (111, 99, 110)], BAR), log_path=log)
    assert log.read_text(encoding="utf-8").startswith(before)


def test_a_settled_prediction_is_not_re_resolved(workspace):
    log = workspace / "forward.jsonl"
    reg = _Registry(_native_frame([(101, 99, 100)], BAR), _Signal())
    ft.scan_and_record(reg, ft.validated_overrides(workspace), log_path=log, now=NOW)
    bars = _native_frame([(101, 99, 100), (111, 99, 110)], BAR)
    assert len(ft.resolve_pending(lambda s, tf: bars, log_path=log)) == 1
    assert ft.resolve_pending(lambda s, tf: bars, log_path=log) == []


def test_accumulated_evidence_eventually_contradicts_a_bad_claim(workspace):
    """The chain's actual purpose. A 62.5% claim against forward evidence that
    is mostly losses must end at `degraded` -- and must get there on FORWARD
    evidence, not be blended away by the backtest prior."""
    log = workspace / "forward.jsonl"
    reg = _Registry(_native_frame([(101, 99, 100)], BAR), _Signal())
    ft.scan_and_record(reg, ft.validated_overrides(workspace), log_path=log, now=NOW)

    records = ft.load_log(log)
    # 10 wins / 20 losses, carrying the same frozen claim the chain recorded
    synthetic = []
    for i in range(30):
        r = ft.ForwardTestRecord(
            record_id=f"r{i}", symbol="ETH-USD", timeframe="1d",
            strategy="mss_trend_hold", direction="LONG",
            bar_time=f"2026-09-{(i % 28) + 1:02d}T00:00:00+00:00",
            recorded_at="2026-09-15T00:00:00+00:00",
            entry=100.0, stop_loss=95.0, take_profit=110.0, horizon_bars=5,
            outcome="target" if i < 10 else "stop",
            r_multiple=2.0 if i < 10 else -1.0,
            backtest_claim=records[0].backtest_claim)
        synthetic.append(r)

    cmp_ = ft.compare_to_backtest(synthetic, 0.625, 64)
    assert cmp_["verdict"] == "degraded"
    assert cmp_["posterior_with_backtest_prior"]["mean"] > cmp_["posterior_forward_only"]["mean"]


def test_governance_artifacts_agree_on_the_live_strategy(workspace):
    """The override, the hypothesis registry and the deployment audit must all
    name the same strategy -- a mismatch here means a dossier would describe
    one strategy while another traded."""
    hyp_path = workspace / "hypotheses.json"
    exp_path = workspace / "experiments.jsonl"

    ov = ft.validated_overrides(workspace)[0]
    hyp.seed(hyp_path)
    h = hyp.get(ov["strategy"], hyp_path)
    assert h is not None
    assert h.missing_fields() == []
    assert h.fails_when                       # retirement is possible for cause

    rec = ex.record_deployment_change(
        symbol=ov["yahoo_symbol"], timeframe=ov["timeframe"], strategy=ov["strategy"],
        previous_status=None, new_status="VALIDATED",
        reason=f"null percentile {ov['claim']['null_percentile']}",
        evidence=ov["claim"], log_path=exp_path)
    assert rec.strategy == ov["strategy"] == h.strategy
    assert ex.deployment_history(ov["yahoo_symbol"], log_path=exp_path)[0].experiment_id \
        == rec.experiment_id


def test_a_stale_feed_stops_the_chain_before_anything_is_recorded(workspace):
    """The guard and the reporter must agree: whatever /health would call
    stale, the recorder must refuse."""
    log = workspace / "forward.jsonl"
    old_bar = BAR - timedelta(days=400)
    reg = _Registry(_native_frame([(101, 99, 100)], old_bar), _Signal())

    verdict = hb.data_staleness_verdict("ETH-USD", "1d", old_bar)
    assert verdict["state"] == "stale"

    out = ft.scan_and_record(reg, ft.validated_overrides(workspace), log_path=log, now=NOW)
    assert out["recorded"] == []
    assert ft.load_log(log) == []

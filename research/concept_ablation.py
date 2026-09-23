"""
Module: concept_ablation.py
Description: Measures every ICT/SMC concept ONE BY ONE, then measures what
    combining them actually adds -- instead of assuming a longer confluence
    list is a better one.

    Two passes:

    PASS 1 -- SOLO. Each concept is turned into the simplest honest signal
    it can support (directional ones trade their own direction; filter-type
    ones like premium/discount or OTE trade the bias they imply) and graded
    alone on E26's real walk-forward bar. This answers "does this concept
    carry any edge by itself?"

    PASS 2 -- MARGINAL. Starting from the best solo concept, each remaining
    concept is added as a FILTER and re-graded. A concept is kept only if
    it improves expectancy. This answers the question that actually
    matters: "does adding this make the result better, or just narrower?"
    Greedy forward selection, so the reported stack is one that was
    measured at every step, not a list of everything that sounded good.

    Every concept is also checked for lookahead by truncation before it is
    graded: if the first half of a signal series changes when the second
    half of the data is removed, the concept is disqualified rather than
    reported. A lookahead bug would otherwise show up as a spectacular
    edge.

    RESEARCH CODE -- outside engines/, nothing live imports it. Reports
    only; never promotes.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine
from project_titan_x.engines.e07_technical.killzones import is_high_probability_window
from project_titan_x.engines.e07_technical.smart_money import (
    StructureEventKind, detect_liquidity_sweeps, detect_order_blocks,
    detect_structure_events, detect_fair_value_gaps,
)
from project_titan_x.engines.e07_technical.crt import detect_crt_setups
from project_titan_x.engines.e07_technical.cisd import detect_cisd_setups
from project_titan_x.engines.e07_technical.chart_patterns import detect_chart_patterns
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.research import ict_concepts as ic

HOLD = 10          # bars held after a trigger, when a concept has no exit of its own


def _hold(sig: pd.Series, bars: int = HOLD) -> pd.Series:
    """Turn a sparse trigger into a holdable position: carry the last
    non-zero signal forward `bars` bars. Concepts are point-in-time events;
    without this most would show ~0 trades and be judged unfairly."""
    out = np.zeros(len(sig), dtype=np.int8)
    arr = sig.to_numpy()
    left = 0
    cur = 0
    for i in range(len(arr)):
        if arr[i] != 0:
            cur, left = int(arr[i]), bars
        if left > 0:
            out[i] = cur
            left -= 1
    return pd.Series(out, index=sig.index, dtype=int)


# --- each concept as a standalone directional signal ----------------------
def _bos(df):
    out = np.zeros(len(df), dtype=np.int8)
    for e in detect_structure_events(df):
        out[e.index] = 1 if e.kind in (StructureEventKind.BOS_BULLISH, StructureEventKind.CHOCH_BULLISH) else -1
    return _hold(pd.Series(out, index=df.index))


def _choch(df):
    out = np.zeros(len(df), dtype=np.int8)
    for e in detect_structure_events(df):
        if e.kind == StructureEventKind.CHOCH_BULLISH:
            out[e.index] = 1
        elif e.kind == StructureEventKind.CHOCH_BEARISH:
            out[e.index] = -1
    return _hold(pd.Series(out, index=df.index))


def _sweep(df):
    out = np.zeros(len(df), dtype=np.int8)
    for s in detect_liquidity_sweeps(df):
        out[s.index] = 1 if s.direction == "bullish" else -1
    return _hold(pd.Series(out, index=df.index))


def _order_block(df):
    """Signal at the bar the block becomes KNOWN, not the bar it sits on.

    An order block is found by searching BACKWARD from a structure break,
    so a block at index i is only revealed once the break prints later --
    measured on real ETHUSD 4h data, 42 of 42 blocks were revealed 1-8 bars
    (median 2) after their own bar. Emitting at ob.index therefore trades
    on information that did not exist yet, and it is not a subtle effect:
    doing so scored 94.8% win rate at profit factor 171 in the first run of
    this ablation, which is what prompted the check.
    """
    events = detect_structure_events(df)
    reveal = sorted(e.index for e in events)
    out = np.zeros(len(df), dtype=np.int8)
    for ob in detect_order_blocks(df, events):
        j = np.searchsorted(reveal, ob.index, side="left")
        if j >= len(reveal):
            continue                      # never confirmed within this data
        out[reveal[j]] = 1 if ob.direction == "bullish" else -1
    return _hold(pd.Series(out, index=df.index))


def _fvg(df):
    """A 3-candle gap centred on bar i is only complete once bar i+1 has
    printed, so the signal belongs at i+1."""
    out = np.zeros(len(df), dtype=np.int8)
    for g in detect_fair_value_gaps(df):
        k = g.index + 1
        if k < len(df):
            out[k] = 1 if g.direction == "bullish" else -1
    return _hold(pd.Series(out, index=df.index))


def _crt(df):
    """CRT already emits at signal_index = i+1 internally (crt.py's own
    translation-trap fix, docs/ICT_SPEC_PHASE5.md 1.4) -- no reveal-bar
    shift needed here, unlike _order_block/_fvg above."""
    out = np.zeros(len(df), dtype=np.int8)
    for s in detect_crt_setups(df):
        out[s.signal_index] = 1 if s.direction == "bullish" else -1
    return _hold(pd.Series(out, index=df.index))


def _cisd(df):
    """CISD already emits at signal_index = b+1 internally (cisd.py's own
    translation-trap fix, docs/ICT_SPEC_PHASE5.md 2.3) -- no reveal-bar
    shift needed here, same as _crt above."""
    out = np.zeros(len(df), dtype=np.int8)
    for s in detect_cisd_setups(df):
        out[s.signal_index] = 1 if s.direction == "bullish" else -1
    return _hold(pd.Series(out, index=df.index))


def _chart_pattern(df):
    """Emits at confirmed_index, NEVER at a pattern's own last swing point
    -- chart_patterns.py reports a pattern the instant its geometry forms,
    long before any close has actually broken its neckline/trendline, so
    trading the geometry itself (rather than the confirmed break) would be
    exactly the same translation-trap class _order_block's own docstring
    already found and fixed for this ablation. Patterns still UNCONFIRMED
    as of the last available bar contribute nothing (correct: there is no
    real trade trigger yet)."""
    out = np.zeros(len(df), dtype=np.int8)
    for p in detect_chart_patterns(df):
        if p.confirmed and p.confirmed_index is not None:
            out[p.confirmed_index] = 1 if p.direction == "bullish" else -1
    return _hold(pd.Series(out, index=df.index))


def _killzone_trend(df):
    kz = is_high_probability_window(df).to_numpy(bool) if "timestamp" in df else np.zeros(len(df), bool)
    trend = np.sign(df["close"].diff(5).fillna(0).to_numpy())
    return _hold(pd.Series(np.where(kz, trend, 0).astype(np.int8), index=df.index))


CONCEPTS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    # already in e07_technical
    "bos_choch":        _bos,
    "choch_only":       _choch,
    "liquidity_sweep":  _sweep,
    "order_block":      _order_block,
    "fvg":              _fvg,
    "killzone":         _killzone_trend,
    # added in research/ict_concepts.py
    "displacement":     lambda d: _hold(ic.displacement(d)),
    "mss":              lambda d: _hold(ic.market_structure_shift(d)),
    "premium_discount": lambda d: _hold(-ic.premium_discount(d)),   # fade premium, buy discount
    "ote":              lambda d: _hold(ic.ote_zone(d).astype(int) * np.sign(d["close"].diff(5).fillna(0))),
    "liquidity_raid_d": lambda d: _hold(ic.liquidity_raid(d, "D")),
    "liquidity_raid_w": lambda d: _hold(ic.liquidity_raid(d, "W")),
    "turtle_soup":      lambda d: _hold(ic.turtle_soup(d)),
    "judas_swing":      lambda d: _hold(ic.judas_swing(d)),
    "power_of_three":   lambda d: _hold(ic.power_of_three(d)),
    "inverse_fvg":      lambda d: _hold(ic.inverse_fvg(d)),
    "bpr":              lambda d: _hold(ic.balanced_price_range(d).astype(int) * np.sign(d["close"].diff(5).fillna(0))),
    "ce":               lambda d: _hold(ic.fvg_consequent_encroachment(d).astype(int) * np.sign(d["close"].diff(5).fillna(0))),
    "eqh_eql":          lambda d: _hold((ic.equal_highs_lows(d)["eql"].astype(int) - ic.equal_highs_lows(d)["eqh"].astype(int))),
    "draw_on_liquidity": lambda d: _hold(pd.Series(np.sign(ic.draw_on_liquidity(d)).astype(np.int8), index=d.index)),
    # added 2026-09-13, docs/UPGRADE_ROADMAP.md P1 item 2
    "crt":              _crt,
    # added 2026-09-13, docs/UPGRADE_ROADMAP.md P2 item 6
    "cisd":             _cisd,
    # added 2026-09-13, engines/e07_technical/chart_patterns.py
    "chart_pattern":    _chart_pattern,
}

# Filter-type concepts: they gate an existing direction rather than pick one.
FILTERS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "killzone":         lambda d: is_high_probability_window(d) if "timestamp" in d else pd.Series(True, index=d.index),
    "displacement_any": lambda d: ic.displacement(d) != 0,
    "ote":              lambda d: ic.ote_zone(d),
    "discount_for_long": lambda d: ic.premium_discount(d) <= 0,
    "not_inducement":   lambda d: ~ic.inducement(d),
    "bpr":              lambda d: ic.balanced_price_range(d),
    "ce":               lambda d: ic.fvg_consequent_encroachment(d),
    "mss_confirmed":    lambda d: ic.market_structure_shift(d) != 0,
}


def _no_lookahead(fn, enriched, cuts: tuple[float, ...] = (0.35, 0.5, 0.65, 0.8, 0.93)) -> bool:
    """Truncate at SEVERAL points, not one.

    A single midpoint cut is too weak to catch short-lag lookahead: when a
    concept only peeks 1-8 bars ahead (an order block revealed by a later
    structure break, median lag 2 bars), almost every event in the first
    half still has its confirming bar inside the truncated window, so the
    two series match and the bug passes. That is exactly how the order-block
    concept scored 94.8% win rate / profit factor 171 before this was
    tightened. Cutting at multiple points -- including 0.93, deep enough
    that many events sit near the boundary -- makes short-lag peeking show
    up as a mismatch.
    """
    for frac in cuts:
        cut = int(len(enriched) * frac)
        if cut < 100:
            continue
        try:
            full, part = fn(enriched), fn(enriched.iloc[:cut])
            if not bool((full.iloc[:cut].to_numpy() == part.to_numpy()).all()):
                return False
        except Exception:
            return False
    return True


def _grade(bt, enriched, fn) -> Optional[dict]:
    try:
        res = bt.run_backtest(enriched, fn)
    except Exception:
        return None
    if not res.success or res.data is None:
        return None
    m = res.data.metrics
    if m.total_trades < 10:
        return None
    rr = abs(m.avg_win_r / m.avg_loss_r) if m.avg_loss_r else 0.0
    return {"trades": m.total_trades, "win_rate": m.win_rate, "expectancy": m.expectancy,
            "reward_risk": rr, "sharpe": m.sharpe_ratio, "max_dd": m.max_drawdown_pct,
            "profit_factor": m.profit_factor}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", default="ETHUSD")
    p.add_argument("--timeframe", default="4h")
    p.add_argument("--years", type=int, default=10)
    args = p.parse_args()

    md, ta, bt = MarketDataEngine(), TechnicalAnalysisEngine(), BacktestingEngine()
    for e in (md, ta, bt):
        e.initialize()

    from project_titan_x.core.config.assets import get_asset
    asset = get_asset(args.symbol)
    ysym = asset.yahoo_symbol if asset else args.symbol
    fetch = md.fetch_ohlcv(ysym, timeframe=args.timeframe, years=args.years)
    if not fetch.success:
        print(f"No data for {args.symbol}: {fetch.message}")
        return
    enriched = ta.analyze(fetch.data).data["df"].reset_index(drop=True)
    print(f"{args.symbol} {args.timeframe} -- {len(enriched)} bars\n")

    # ---------------- PASS 1: every concept alone ----------------
    print("=" * 96)
    print("PASS 1 -- EACH CONCEPT ALONE (real E26 backtest, costs included)")
    print("=" * 96)
    print(f"{'CONCEPT':20} {'TRADES':>7} {'WIN%':>6} {'R:R':>6} {'EXPECT':>8} {'PF':>6} {'SHARPE':>7} {'DD%':>6}")
    solo: dict[str, dict] = {}
    for name, fn in CONCEPTS.items():
        if not _no_lookahead(fn, enriched):
            print(f"{name:20}   DISQUALIFIED -- lookahead detected")
            continue
        r = _grade(bt, enriched, fn)
        if not r:
            print(f"{name:20}   too few trades to judge")
            continue
        solo[name] = r
        print(f"{name:20} {r['trades']:>7} {r['win_rate']*100:>5.1f}% {r['reward_risk']:>5.2f}R "
              f"{r['expectancy']:>8.3f} {r['profit_factor']:>6.2f} {r['sharpe']:>7.2f} {r['max_dd']:>6.2f}")

    if not solo:
        print("\nNo concept produced a gradeable result on this market.")
        return
    ranked = sorted(solo.items(), key=lambda kv: -kv[1]["expectancy"])
    print(f"\nBest solo concept: {ranked[0][0]} (expectancy {ranked[0][1]['expectancy']:.3f})")

    # ---------------- PASS 2: what each filter ADDS ----------------
    base_name, base = ranked[0]
    base_fn = CONCEPTS[base_name]
    print("\n" + "=" * 96)
    print(f"PASS 2 -- MARGINAL VALUE of each filter on top of '{base_name}'")
    print("=" * 96)
    print(f"{'ADDED FILTER':20} {'TRADES':>7} {'WIN%':>6} {'R:R':>6} {'EXPECT':>8} {'vs BASE':>9}")
    print(f"{'(base alone)':20} {base['trades']:>7} {base['win_rate']*100:>5.1f}% "
          f"{base['reward_risk']:>5.2f}R {base['expectancy']:>8.3f} {'--':>9}")

    marginal: dict[str, dict] = {}
    for fname, ffn in FILTERS.items():
        def combined(d, _f=ffn, _b=base_fn):
            return (_b(d).astype(int) * _f(d).astype(int)).astype(int)
        if not _no_lookahead(combined, enriched):
            print(f"{fname:20}   DISQUALIFIED -- lookahead")
            continue
        r = _grade(bt, enriched, combined)
        if not r:
            print(f"{fname:20}   too few trades once filtered")
            continue
        delta = r["expectancy"] - base["expectancy"]
        marginal[fname] = {**r, "delta_expectancy": delta}
        print(f"{fname:20} {r['trades']:>7} {r['win_rate']*100:>5.1f}% {r['reward_risk']:>5.2f}R "
              f"{r['expectancy']:>8.3f} {delta:>+9.3f}")

    helpful = {k: v for k, v in marginal.items() if v["delta_expectancy"] > 0}
    print(f"\n{len(helpful)} of {len(marginal)} filters IMPROVED expectancy: "
          f"{', '.join(sorted(helpful, key=lambda k: -helpful[k]['delta_expectancy'])) or 'none'}")
    if not helpful:
        print("Every filter narrowed the sample without improving it -- on this market,")
        print("stacking these concepts is subtraction, not confluence. Reported as-is.")

    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "symbol": args.symbol, "timeframe": args.timeframe, "bars": len(enriched),
           "solo": solo, "base_concept": base_name, "marginal": marginal}
    dest = Path(__file__).resolve().parent / f"ablation_{args.symbol}_{args.timeframe}.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nSaved to {dest}")


if __name__ == "__main__":
    main()

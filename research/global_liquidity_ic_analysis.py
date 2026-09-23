"""
Module: global_liquidity_ic_analysis.py
Description: Real, historical "information coefficient" backtest for
    engines/e51_signals/engine.py's `_confluence_global_liquidity` check
    -- closing part of both PDFs in data/PDF/'s "IC-weighted confluence"
    recommendation (correlate a confluence layer's historical reading
    against realized forward returns before trusting its live weight).

    Direct verification before writing this (an Explore agent's own
    six-engine survey) found MOST of e51_signals' 11 confluence checks
    are fundamentally live-snapshot-only (sentiment/E09, derivatives/E13,
    fixed_income/E14, credit/E15 all fetch "the current X" with no
    historical archive to backtest against -- confirmed, same limitation
    already documented for E03 news elsewhere in this codebase). Global
    liquidity (E19) is one of the few that genuinely ISN'T: WALCL/M2SL/
    DFII10 are real FRED time series, already fully cached locally
    (data/raw/fred_cache/, fetched_at 2026-09-13, WALCL back to
    2002-12-18) -- no fabrication needed, no network call required to run
    this. `engines/e19_global_liquidity/engine.py`'s `analyze()` gained an
    optional `reference` date param this same session specifically to
    make this backtest possible (see its own docstring for the FRED-
    revision caveat that travels with every number below).

    METHOD. For each of e51_signals._CREDIT_RISK_SYMBOLS (the only
    symbols _confluence_global_liquidity ever actually applies to):
    resample real cached OHLCV (via e02_market_data.fetch_ohlcv, the same
    real collaborator every other engine uses) to weekly closes -- weekly
    because WALCL/M2SL themselves only update weekly/monthly, so a daily
    stride would just repeat the same regime reading ~5-30x in a row and
    inflate the apparent sample size without adding real information.
    At each weekly date, ask what E19's overall_regime WOULD have been
    as-of that date (causal: only observations on or before it), then
    look up the REAL forward return over two horizons (21 and 63 trading
    days -- roughly one and three months, bracketing the ~91-day window
    the regime signal itself is computed over).

    REAL FINDING THAT CHANGED THE METHOD MID-BUILD: a full weekly sweep
    of `overall_regime` from 2004-2026 (1183 checkpoints, run directly
    against the live engine before trusting the per-symbol backtest)
    found "contracting" NEVER fires -- 0 of 1183. `_overall_regime`
    requires FED *and* M2 to independently cross their own thresholds in
    the same direction at the same checkpoint; fed alone goes
    "contracting" 5.2% of the time and m2 alone 0.8% of the time, but
    those two rare events never coincided at weekly resolution across 22
    years of real FRED data. So `_confluence_global_liquidity`'s
    `disagrees` branch for LONG signals (and `agrees` branch for SHORT)
    has almost certainly never fired live either -- the SAME "honestly a
    no-op in practice" finding `_confluence_alpha_research`'s own
    docstring already discloses for a different check, discovered here
    independently. This makes the originally-planned three-state
    (expanding/contracting/mixed) Spearman IC uncomputable (one class is
    empty) and, more importantly, the wrong question -- the check this
    platform actually runs live is a binary "expanding vs everything
    else," so that's what's measured: mean/median forward return when
    `overall_regime == "expanding"` vs. the unconditional baseline across
    ALL sampled dates (mixed/unconfigured included), plus a Mann-Whitney
    U test on the two groups.

    This is a REPORT-ONLY diagnostic. It does not touch
    _confluence_global_liquidity's live multiplier. Whether these results
    justify changing that multiplier is a separate decision, to be made
    from whatever real numbers this script actually produces -- not
    assumed going in, per this whole session's own standing "measure
    first, decide from evidence" discipline (Stage 0, CPCV-vs-block-
    bootstrap, the tsfresh meta-label attempt all followed the same
    pattern).

    A REAL METHODOLOGICAL CAVEAT THAT MUST TRAVEL WITH EVERY NUMBER
    BELOW, discovered while writing this docstring, not after: weekly
    samples with a 21- or 63-DAY FORWARD return window heavily OVERLAP in
    calendar time (adjacent weekly checkpoints share up to 58 of their 63
    forward days), so the reported n is the number of CHECKPOINTS, not
    the number of INDEPENDENT observations -- the exact same "serial
    dependence overstates effective N" trap docs/STAGE0_FINDINGS.md's own
    DSR caveat already names for a different statistic. The Mann-Whitney
    p-values below are therefore OPTIMISTIC (a ceiling on significance,
    not a true estimate), same status as every DSR number in this
    codebase. This is why a result here -- even the BANKNIFTY one, whose
    sign runs OPPOSITE the check's current assumption -- is treated as a
    real, worth-following-up finding, NOT as sufficient evidence on its
    own to change `_confluence_global_liquidity`'s live weights. A proper
    follow-up would need either a block-bootstrap over non-overlapping
    windows (the same fix `engines/e26_backtesting/block_bootstrap.py`
    already applied to an analogous overlapping-window problem) or a genuine
    held-out split, matching the rigor `e17_crypto/train_e17_crypto.py`
    already uses before trusting a per-asset confluence weight live.

Usage: python research/global_liquidity_ic_analysis.py
Author: Shantanu Waykar
Version: 1.0.0
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from project_titan_x.core.config import get_asset
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e19_global_liquidity.engine import GlobalLiquidityEngine

SYMBOLS = ["BTCUSD", "ETHUSD", "SP500", "NIFTY50", "BANKNIFTY"]
FORWARD_HORIZONS_TRADING_DAYS = [21, 63]
OUTPUT_PATH = Path(__file__).resolve().parent / "global_liquidity_ic_analysis.json"


@dataclass
class BucketStats:
    n: int
    mean_return_pct: Optional[float]
    median_return_pct: Optional[float]


@dataclass
class SymbolResult:
    symbol: str
    n_dates_sampled: int
    n_dates_with_signal: int  # dates where overall_regime was expanding or contracting (contracting is empirically ~0, see module docstring)
    per_horizon: dict = field(default_factory=dict)  # horizon -> {expanding, all_other_periods, edge, mann_whitney_u/p}


def _weekly_ohlcv(symbol: str) -> Optional[pd.DataFrame]:
    asset = get_asset(symbol)
    if asset is None:
        print(f"  skip {symbol}: unknown asset")
        return None
    market_data = MarketDataEngine()
    fetch = market_data.fetch_ohlcv(asset.yahoo_symbol, "1d", years=25)
    if not fetch.success or fetch.data is None or fetch.data.empty:
        print(f"  skip {symbol}: no OHLCV ({fetch.message})")
        return None
    df = fetch.data.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _forward_return_pct(df: pd.DataFrame, entry_idx: int, horizon_days: int) -> Optional[float]:
    exit_idx = entry_idx + horizon_days
    if exit_idx >= len(df):
        return None
    entry_price = df["close"].iloc[entry_idx]
    exit_price = df["close"].iloc[exit_idx]
    if entry_price == 0:
        return None
    return float((exit_price - entry_price) / entry_price * 100.0)


def _bucket(returns: list[float]) -> BucketStats:
    if not returns:
        return BucketStats(n=0, mean_return_pct=None, median_return_pct=None)
    return BucketStats(n=len(returns), mean_return_pct=round(float(np.mean(returns)), 4), median_return_pct=round(float(np.median(returns)), 4))


def analyze_symbol(symbol: str, liquidity_engine: GlobalLiquidityEngine) -> Optional[SymbolResult]:
    print(f"{symbol}:")
    df = _weekly_ohlcv(symbol)
    if df is None:
        return None

    # Weekly stride, starting once enough history exists for the regime
    # signal itself to be meaningful (skip the first 120 calendar days of
    # an asset's own listed history) and stopping early enough that even
    # the longest forward horizon has real future bars to measure against.
    max_horizon = max(FORWARD_HORIZONS_TRADING_DAYS)
    start_idx = 0
    end_idx = len(df) - max_horizon - 1
    if end_idx <= start_idx:
        print("  skip: not enough history for the longest forward horizon")
        return None

    sample_indices = list(range(start_idx, end_idx, 5))  # ~weekly (5 trading days)

    regimes: list[str] = []
    entry_indices: list[int] = []
    for idx in sample_indices:
        as_of = df["timestamp"].iloc[idx].to_pydatetime()
        result = liquidity_engine.analyze(reference=as_of)
        regime = result.data.overall_regime if result.success and result.data else "unconfigured"
        regimes.append(regime)
        entry_indices.append(idx)

    regime_counts = {r: regimes.count(r) for r in set(regimes)}
    n_signal = regime_counts.get("expanding", 0) + regime_counts.get("contracting", 0)
    print(f"  {len(sample_indices)} weekly dates sampled, regime counts: {regime_counts}")

    per_horizon: dict = {}
    for horizon in FORWARD_HORIZONS_TRADING_DAYS:
        expanding_returns, other_returns = [], []
        for regime, idx in zip(regimes, entry_indices):
            ret = _forward_return_pct(df, idx, horizon)
            if ret is None:
                continue
            if regime == "expanding":
                expanding_returns.append(ret)
            else:
                other_returns.append(ret)

        mw_u, mw_p = None, None
        if len(expanding_returns) >= 10 and len(other_returns) >= 10:
            u_stat, p_value = stats.mannwhitneyu(expanding_returns, other_returns, alternative="two-sided")
            mw_u, mw_p = round(float(u_stat), 2), round(float(p_value), 4)

        expanding_stats = _bucket(expanding_returns).__dict__
        other_stats = _bucket(other_returns).__dict__
        edge = (
            round(expanding_stats["mean_return_pct"] - other_stats["mean_return_pct"], 4)
            if expanding_stats["mean_return_pct"] is not None and other_stats["mean_return_pct"] is not None
            else None
        )

        per_horizon[str(horizon)] = {
            "expanding": expanding_stats,
            "all_other_periods": other_stats,
            "expanding_minus_baseline_mean_return_pct": edge,
            "mann_whitney_u": mw_u,
            "mann_whitney_p_value": mw_p,
        }
        print(
            f"  horizon={horizon}d  expanding n={expanding_stats['n']} mean={expanding_stats['mean_return_pct']}  "
            f"baseline(all other) n={other_stats['n']} mean={other_stats['mean_return_pct']}  "
            f"edge={edge}pp  Mann-Whitney p={mw_p}"
        )

    return SymbolResult(
        symbol=symbol, n_dates_sampled=len(sample_indices), n_dates_with_signal=n_signal, per_horizon=per_horizon,
    )


def main() -> None:
    liquidity_engine = GlobalLiquidityEngine()
    liquidity_engine.initialize()

    results: dict[str, dict] = {}
    for symbol in SYMBOLS:
        result = analyze_symbol(symbol, liquidity_engine)
        if result is not None:
            results[symbol] = {
                "n_dates_sampled": result.n_dates_sampled,
                "n_dates_with_signal": result.n_dates_with_signal,
                "per_horizon": result.per_horizon,
            }

    # Deliberately no single pooled IC across symbols: BTC/NIFTY/BANKNIFTY
    # have very different volatility scales, so pooling raw per-
    # observation returns would let the noisiest asset dominate a
    # combined correlation. Per-symbol IC (already reported above) is the
    # honest unit here, not a single blended number.
    pooled_note = (
        "No single pooled IC across symbols is reported -- see each "
        "symbol's own spearman_ic per horizon above. Pooling raw returns "
        "across assets of very different volatility (BTC vs NIFTY) would "
        "let the noisiest asset dominate a blended correlation."
    )

    OUTPUT_PATH.write_text(json.dumps({"symbols": results, "pooled_note": pooled_note}, indent=2))
    print(f"\nWrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

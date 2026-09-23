"""
Module: cross_asset_ic_analysis.py
Description: Real historical IC backtest for engines/e51_signals/
    engine.py's `_confluence_cross_asset` check -- closing part of both
    PDFs in data/PDF/'s "IC-weighted confluence" recommendation, same
    family as research/global_liquidity_ic_analysis.py (E19). E10's own
    regime classification (`_classify_regime`) is imported directly from
    the real engine, not reimplemented, so this measures exactly the
    logic that runs live.

    METHOD. For each of E10's 10 PAIR_DEFINITIONS: fetch full real price
    history for both tickers (bulk fetch, `period="max"`), compute a
    TRAILING 60-day rolling correlation at each weekly checkpoint
    (causal by construction -- a trailing window only ever looks
    backward), classify it against the real calibrated baseline
    (data/models/e10_cross_asset/baseline_correlations.json) using
    E10's own `_classify_regime`, then compare ticker_b's forward
    return (21/63 trading days) between "intact" and "not intact"
    (inverted/breaking_down) checkpoints via Mann-Whitney U -- same
    honest-baseline-vs-signal framing E19's own analysis already used.

    HONEST METHODOLOGICAL CAVEAT (same one E19's own script names):
    overlapping forward-return windows mean the checkpoint count is NOT
    the independent-observation count -- p-values here are a ceiling,
    not an estimate. Report-only; does not touch _confluence_cross_
    asset's live multiplier.
Author: Shantanu Waykar
Version: 1.0.0
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from project_titan_x.core.data_providers.yahoo import ticker_history
from project_titan_x.engines.e10_cross_asset.engine import PAIR_DEFINITIONS, ROLLING_WINDOW_DAYS, CrossAssetIntelligenceEngine

FORWARD_HORIZONS = [21, 63]
BASELINE_PATH = Path(__file__).resolve().parent.parent / "data" / "models" / "e10_cross_asset" / "baseline_correlations.json"
OUTPUT_PATH = Path(__file__).resolve().parent / "cross_asset_ic_analysis.json"


def _fetch_close(ticker: str) -> pd.Series | None:
    hist = ticker_history(ticker, "max", context="cross_asset_ic")
    if hist.empty:
        return None
    series = hist["Close"].copy()
    series.index = series.index.tz_localize(None).normalize()
    return series


def analyze_pair(name: str, ticker_a: str, label_a: str, ticker_b: str, label_b: str, baselines: dict) -> dict | None:
    print(f"{name} ({ticker_a} vs {ticker_b}):")
    close_a = _fetch_close(ticker_a)
    close_b = _fetch_close(ticker_b)
    if close_a is None or close_b is None:
        print("  skip: missing price data")
        return None

    df = pd.DataFrame({"a": close_a, "b": close_b}).dropna()
    if len(df) < ROLLING_WINDOW_DAYS + 100:
        print("  skip: not enough aligned history")
        return None

    returns = df.pct_change().dropna()
    rolling_corr = returns["a"].rolling(ROLLING_WINDOW_DAYS).corr(returns["b"])
    baseline = baselines.get(name, {}).get("baseline_correlation")
    if baseline is None:
        print("  skip: no calibrated baseline")
        return None

    close_prices = df["b"].reset_index(drop=True)
    rolling_corr = rolling_corr.reset_index(drop=True)
    max_horizon = max(FORWARD_HORIZONS)

    regimes = []
    for i in range(0, len(df) - max_horizon, 5):  # weekly stride
        c = rolling_corr.iloc[i]
        if pd.isna(c):
            continue
        regime, _ = CrossAssetIntelligenceEngine._classify_regime(float(c), baseline)
        regimes.append((i, regime))

    regime_counts = {}
    for _, r in regimes:
        regime_counts[r] = regime_counts.get(r, 0) + 1
    print(f"  {len(regimes)} weekly checkpoints, regime counts: {regime_counts}")

    per_horizon = {}
    for horizon in FORWARD_HORIZONS:
        intact_returns, other_returns = [], []
        for i, regime in regimes:
            exit_idx = i + horizon
            if exit_idx >= len(close_prices):
                continue
            entry_price = close_prices.iloc[i]
            exit_price = close_prices.iloc[exit_idx]
            if entry_price == 0:
                continue
            ret = float((exit_price - entry_price) / entry_price * 100.0)
            if regime == "intact":
                intact_returns.append(ret)
            else:
                other_returns.append(ret)

        mw_p = None
        if len(intact_returns) >= 10 and len(other_returns) >= 10:
            _, p = stats.mannwhitneyu(intact_returns, other_returns, alternative="two-sided")
            mw_p = round(float(p), 4)

        intact_mean = round(float(np.mean(intact_returns)), 4) if intact_returns else None
        other_mean = round(float(np.mean(other_returns)), 4) if other_returns else None
        edge = round(intact_mean - other_mean, 4) if intact_mean is not None and other_mean is not None else None

        per_horizon[str(horizon)] = {
            "intact": {"n": len(intact_returns), "mean_return_pct": intact_mean},
            "not_intact": {"n": len(other_returns), "mean_return_pct": other_mean},
            "edge_intact_minus_not_intact": edge,
            "mann_whitney_p_value": mw_p,
        }
        print(f"  horizon={horizon}d  intact n={len(intact_returns)} mean={intact_mean}  "
              f"not_intact n={len(other_returns)} mean={other_mean}  edge={edge}pp  p={mw_p}")

    return {"n_checkpoints": len(regimes), "regime_counts": regime_counts, "per_horizon": per_horizon}


def main() -> None:
    baselines = json.loads(BASELINE_PATH.read_text()).get("pairs", {})
    results = {}
    for name, ticker_a, label_a, ticker_b, label_b in PAIR_DEFINITIONS:
        result = analyze_pair(name, ticker_a, label_a, ticker_b, label_b, baselines)
        if result is not None:
            results[name] = result
    OUTPUT_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

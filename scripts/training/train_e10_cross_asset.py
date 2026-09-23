"""
Module: train_e10_cross_asset.py
Description: Calibrate Engine 10's long-run baseline correlation for each
    named cross-asset pair (DXY/Gold, Bonds/Stocks, Oil/CAD, Yields/USD,
    VIX/Risk Assets, Copper/Global Growth) from the maximum real historical
    daily price data yfinance can return for each ticker.

    Method: fetch the FULL available history (period="max") for every
    tracked ticker. Each pair is aligned INDEPENDENTLY on its own two
    tickers' common trading days -- not on one shared intersection across
    all 10 tickers -- since the 6 pairs don't share a single inception
    date (e.g. DXY/^TNX go back to the 1960s-70s, but ACWI only exists
    since 2008; capping every pair to ACWI's start would throw away
    decades of real, usable history for the other 5 pairs). Split each
    pair's own aligned returns chronologically into a train period (first
    70%) and a held-out test period (last 30%); compute the pair's
    correlation on both. This is a stability check, not a fit --
    correlation is a descriptive statistic, not a decision threshold, so
    there is nothing to "overfit" the way a strategy parameter can. If
    train-period and test-period correlation are reasonably close (see
    STABILITY_WARNING_THRESHOLD), the full-history correlation is
    persisted as the production baseline (standard practice: validate
    stability, then refit on all data). If they diverge sharply, the
    calibration is still persisted (the engine needs *some* honest number
    to compare against) but the report flags it as unstable so it can be
    revisited.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e10_cross_asset.engine import PAIR_DEFINITIONS

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e10_cross_asset"
LONG_LOOKBACK_PERIOD = "max"
TRAIN_FRACTION = 0.7
STABILITY_WARNING_THRESHOLD = 0.35  # |train_corr - test_corr| above this => flagged unstable
MIN_ALIGNED_PERIODS = 60  # below this, a correlation is too noisy to be a usable baseline


def _fetch_all_closes(tickers: list[str], period: str) -> dict[str, pd.Series]:
    closes: dict[str, pd.Series] = {}
    for ticker in tickers:
        hist = yf.Ticker(ticker).history(period=period)
        if hist.empty:
            logger.warning("No data returned for %s", ticker)
            continue
        series = hist["Close"]
        series.index = series.index.tz_localize(None).normalize()
        closes[ticker] = series
    return closes


def train() -> dict:
    unique_tickers = sorted({t for _, ta, _, tb, _ in PAIR_DEFINITIONS for t in (ta, tb)})
    closes = _fetch_all_closes(unique_tickers, LONG_LOOKBACK_PERIOD)
    missing = set(unique_tickers) - set(closes)
    if missing:
        raise RuntimeError(f"Could not fetch history for: {sorted(missing)}")

    pairs_report: dict[str, dict] = {}
    for name, ticker_a, _, ticker_b, _ in PAIR_DEFINITIONS:
        pair_df = pd.DataFrame({ticker_a: closes[ticker_a], ticker_b: closes[ticker_b]}).dropna()
        returns = pair_df.pct_change().dropna()
        if len(returns) < MIN_ALIGNED_PERIODS:
            logger.warning("%s: only %d aligned periods, skipping (need >= %d)", name, len(returns), MIN_ALIGNED_PERIODS)
            continue

        split_idx = int(len(returns) * TRAIN_FRACTION)
        train_returns, test_returns = returns.iloc[:split_idx], returns.iloc[split_idx:]

        full_corr = float(returns[ticker_a].corr(returns[ticker_b]))
        train_corr = float(train_returns[ticker_a].corr(train_returns[ticker_b]))
        test_corr = float(test_returns[ticker_a].corr(test_returns[ticker_b]))
        stability_gap = abs(train_corr - test_corr)

        pairs_report[name] = {
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "baseline_correlation": round(full_corr, 4),
            "train_period_correlation": round(train_corr, 4),
            "test_period_correlation": round(test_corr, 4),
            "stability_gap": round(stability_gap, 4),
            "stable": stability_gap <= STABILITY_WARNING_THRESHOLD,
            "n_total_periods": len(returns),
            "n_train_periods": len(train_returns),
            "n_test_periods": len(test_returns),
            "date_range": [str(returns.index[0].date()), str(returns.index[-1].date())],
        }
        if stability_gap > STABILITY_WARNING_THRESHOLD:
            logger.warning(
                "%s: train/test correlation gap %.3f exceeds stability threshold "
                "(train=%.3f, test=%.3f) -- relationship may be regime-dependent, "
                "baseline persisted anyway but flagged unstable",
                name, stability_gap, train_corr, test_corr,
            )

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "lookback_period": LONG_LOOKBACK_PERIOD,
        "train_fraction": TRAIN_FRACTION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "pairs": pairs_report,
        "caveat": (
            "Baseline correlations computed from the maximum real daily price "
            "history yfinance returns per ticker -- each pair aligned "
            "independently on its own two tickers' common trading days (not "
            "capped by the shortest-lived ticker across all 10 tracked "
            "instruments), so date ranges differ pair to pair; see each pair's "
            "own date_range. Train/test split is a stability check "
            "(correlation is descriptive, not a fit target) -- pairs flagged "
            f"stable=false have a train/test correlation gap above "
            f"{STABILITY_WARNING_THRESHOLD}, meaning the relationship shifted "
            "meaningfully within its own lookback window; treat their baseline "
            "as a rough anchor, not a precise constant."
        ),
    }
    calibration_path = MODELS_DIR / "baseline_correlations.json"
    calibration_path.write_text(json.dumps(report, indent=2))
    logger.info("Saved %d pair baselines to %s", len(pairs_report), calibration_path)
    for name, data in pairs_report.items():
        logger.info(
            "  %-30s baseline=%+.3f (train=%+.3f test=%+.3f stable=%s, n=%d, %s..%s)",
            name, data["baseline_correlation"], data["train_period_correlation"],
            data["test_period_correlation"], data["stable"], data["n_total_periods"],
            data["date_range"][0], data["date_range"][1],
        )
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    train()

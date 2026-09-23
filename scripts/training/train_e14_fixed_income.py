"""
Module: train_e14_fixed_income.py
Description: Calibrate Engine 14's two data-driven components from real
    historical price data:

    1. Empirical duration & convexity per government bond ETF (SHY/IEF/
       TLT/TIP). yfinance doesn't publish these (checked live -- no
       duration/convexity/maturity field exists in ticker.info for any of
       them), so they're estimated the standard quant way: regress each
       ETF's daily return against the daily change in the 10Y Treasury
       yield (^TNX). %price_return ~= -duration*delta_yield +
       0.5*convexity*delta_yield^2 (a quadratic fit gives both terms at
       once). Verified sane against real published figures before this
       script was written: SHY~1.6y (published ~1.8y), IEF~7.4y (published
       ~7.5y), TLT~14.1y (published ~16-17y, empirical vs the 10Y
       benchmark is naturally a bit lower since the curve doesn't shift
       perfectly in parallel), TIP~4.7y (muted vs NOMINAL 10Y yield
       changes, as expected for an inflation-protected, real-yield
       instrument).

    2. Credit-stress correlation baseline: HYG (high-yield corporate) vs
       IEF (7-10y Treasury) rolling vs. full-period correlation, same
       technique as train_e10_cross_asset.py -- a real historical
       distribution to compare today's HYG/IEF correlation against.

    NOT calibrated here (honest gap, same as e13_derivatives' options
    thresholds): the ABSOLUTE credit spread level (LQD/HYG yield minus a
    duration-matched Treasury yield) is classified against static,
    documented market conventions, not backtested -- yfinance's
    ticker.info['yield'] is a live-only snapshot with no free historical
    time series, so there is no real historical spread distribution to
    calibrate a tight/normal/wide threshold against.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e14_fixed_income"
YIELD_BENCHMARK_TICKER = "^TNX"
GOVT_ETF_TICKERS = {"SHY": "Short-Term Treasury (1-3y)", "IEF": "Intermediate Treasury (7-10y)",
                    "TLT": "Long-Term Treasury (20y+)", "TIP": "TIPS (Inflation-Protected)"}
CREDIT_STRESS_PAIR = ("HYG", "IEF")
TRAIN_FRACTION = 0.7
STABILITY_WARNING_THRESHOLD = 3.0  # years of duration -- train/test gap above this is flagged unstable


def _fetch_close(ticker: str, period: str = "max") -> pd.Series:
    hist = yf.Ticker(ticker).history(period=period)
    series = hist["Close"]
    series.index = series.index.tz_localize(None).normalize()
    return series


def _duration_convexity(price_returns: pd.Series, yield_changes: pd.Series) -> dict:
    aligned = pd.DataFrame({"r": price_returns, "y": yield_changes}).dropna()
    coeffs = np.polyfit(aligned["y"], aligned["r"], 2)  # [c, b, a] for c*y^2 + b*y + a
    c, b = coeffs[0], coeffs[1]
    predicted = np.polyval(coeffs, aligned["y"])
    ss_res = float(np.sum((aligned["r"] - predicted) ** 2))
    ss_tot = float(np.sum((aligned["r"] - aligned["r"].mean()) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot else 0.0
    return {
        "empirical_duration": round(float(-b), 3),
        "convexity": round(float(2 * c), 3),
        "r_squared": round(r_squared, 4),
        "n_observations": int(len(aligned)),
    }


def _train_duration_convexity() -> dict:
    benchmark = _fetch_close(YIELD_BENCHMARK_TICKER)
    results: dict[str, dict] = {}
    for ticker, label in GOVT_ETF_TICKERS.items():
        price = _fetch_close(ticker)
        df = pd.DataFrame({"price": price, "yield": benchmark}).dropna()
        price_returns = df["price"].pct_change().dropna()
        yield_changes = (df["yield"].diff() / 100).dropna()  # percentage points -> decimal

        split_idx = int(len(price_returns) * TRAIN_FRACTION)
        train_full = _duration_convexity(price_returns.iloc[:split_idx], yield_changes.iloc[:split_idx])
        test_full = _duration_convexity(price_returns.iloc[split_idx:], yield_changes.iloc[split_idx:])
        full = _duration_convexity(price_returns, yield_changes)

        stability_gap = abs(train_full["empirical_duration"] - test_full["empirical_duration"])
        results[ticker] = {
            "label": label,
            "empirical_duration": full["empirical_duration"],
            "convexity": full["convexity"],
            "r_squared": full["r_squared"],
            "n_observations": full["n_observations"],
            "train_period_duration": train_full["empirical_duration"],
            "test_period_duration": test_full["empirical_duration"],
            "stability_gap_years": round(stability_gap, 3),
            "stable": stability_gap <= STABILITY_WARNING_THRESHOLD,
        }
        if stability_gap > STABILITY_WARNING_THRESHOLD:
            logger.warning(
                "%s: train/test empirical duration gap %.2fy exceeds stability threshold "
                "(train=%.2fy, test=%.2fy)", ticker, stability_gap,
                train_full["empirical_duration"], test_full["empirical_duration"],
            )
    return results


def _train_credit_stress_correlation() -> dict:
    a_ticker, b_ticker = CREDIT_STRESS_PAIR
    a_price = _fetch_close(a_ticker)
    b_price = _fetch_close(b_ticker)
    df = pd.DataFrame({a_ticker: a_price, b_ticker: b_price}).dropna()
    returns = df.pct_change().dropna()

    split_idx = int(len(returns) * TRAIN_FRACTION)
    train_returns, test_returns = returns.iloc[:split_idx], returns.iloc[split_idx:]
    full_corr = float(returns[a_ticker].corr(returns[b_ticker]))
    train_corr = float(train_returns[a_ticker].corr(train_returns[b_ticker]))
    test_corr = float(test_returns[a_ticker].corr(test_returns[b_ticker]))
    stability_gap = abs(train_corr - test_corr)

    return {
        "pair": f"{a_ticker} vs {b_ticker}",
        "baseline_correlation": round(full_corr, 4),
        "train_period_correlation": round(train_corr, 4),
        "test_period_correlation": round(test_corr, 4),
        "stability_gap": round(stability_gap, 4),
        "stable": stability_gap <= 0.35,
        "n_total_periods": len(returns),
        "date_range": [str(returns.index[0].date()), str(returns.index[-1].date())],
    }


def train() -> dict:
    duration_convexity = _train_duration_convexity()
    credit_stress = _train_credit_stress_correlation()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "duration_convexity": duration_convexity,
        "credit_stress_correlation": credit_stress,
        "caveat": (
            "Empirical duration/convexity are regression estimates against 10Y Treasury "
            "yield changes (^TNX), not each fund's own published effective duration -- "
            "yfinance exposes no such field for these tickers. Credit-stress correlation "
            "baseline (HYG vs IEF) is a real historical distribution, same technique as "
            "e10_cross_asset. Absolute credit spread LEVEL (LQD/HYG yield minus a Treasury "
            "benchmark) is NOT calibrated here -- no free historical yield time series "
            "exists for these ETFs (only a live snapshot via ticker.info), so the engine "
            "classifies it against static, documented market conventions instead."
        ),
    }
    calibration_path = MODELS_DIR / "calibration.json"
    calibration_path.write_text(json.dumps(report, indent=2))
    logger.info("Saved E14 calibration to %s", calibration_path)
    for ticker, data in duration_convexity.items():
        logger.info(
            "  %-6s duration=%.2fy convexity=%.1f r2=%.3f (train=%.2fy test=%.2fy stable=%s)",
            ticker, data["empirical_duration"], data["convexity"], data["r_squared"],
            data["train_period_duration"], data["test_period_duration"], data["stable"],
        )
    logger.info(
        "  Credit stress %s: baseline=%+.3f (train=%+.3f test=%+.3f stable=%s)",
        credit_stress["pair"], credit_stress["baseline_correlation"],
        credit_stress["train_period_correlation"], credit_stress["test_period_correlation"],
        credit_stress["stable"],
    )
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    train()

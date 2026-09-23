"""
Module: train_e15_credit.py
Description: Calibrate Engine 15's sovereign credit-stress correlation
    baseline: EMB (iShares JP Morgan USD Emerging Markets Bond ETF, the
    standard free/liquid EM sovereign credit proxy) vs. IEF (7-10y
    Treasury, the same benchmark e14_fixed_income uses for corporate
    credit) rolling vs. full-period correlation, from real historical
    price data back to EMB's 2007 inception. Same technique as
    train_e10_cross_asset.py / train_e14_fixed_income.py's credit-stress
    calibration.

    NOT calibrated here (honest gap, same as e14_fixed_income's credit
    spread thresholds): the ABSOLUTE sovereign spread level and the
    default-probability-from-spread estimate are live-snapshot
    computations (yfinance's ticker.info['yield'] has no free historical
    time series), classified/estimated against static, documented
    conventions instead.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e15_credit"
SOVEREIGN_STRESS_PAIR = ("EMB", "IEF")
TRAIN_FRACTION = 0.7
STABILITY_WARNING_THRESHOLD = 0.35


def _fetch_close(ticker: str, period: str = "max", retries: int = 3) -> pd.Series:
    """Real bug found 2026-08-21: yfinance occasionally returns an EMPTY
    frame ("possibly delisted; no price data found") for a transient
    reason (rate-limiting, a momentary API hiccup) even for a real,
    actively-traded ticker -- the empty frame's index is a plain
    RangeIndex, not a DatetimeIndex, so the old code's blind
    `.tz_localize(None)` crashed with a confusing AttributeError instead
    of a clear "fetch failed" message. Retried with a short backoff
    (transient issues usually clear within seconds) before raising."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            hist = yf.Ticker(ticker).history(period=period)
            if not hist.empty:
                series = hist["Close"]
                series.index = series.index.tz_localize(None).normalize()
                return series
            last_error = RuntimeError(f"yfinance returned an empty frame for {ticker}")
        except Exception as e:
            last_error = e
        if attempt < retries - 1:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {ticker} after {retries} attempts: {last_error}")


def train() -> dict:
    a_ticker, b_ticker = SOVEREIGN_STRESS_PAIR
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

    credit_stress = {
        "pair": f"{a_ticker} vs {b_ticker}",
        "baseline_correlation": round(full_corr, 4),
        "train_period_correlation": round(train_corr, 4),
        "test_period_correlation": round(test_corr, 4),
        "stability_gap": round(stability_gap, 4),
        "stable": stability_gap <= STABILITY_WARNING_THRESHOLD,
        "n_total_periods": len(returns),
        "date_range": [str(returns.index[0].date()), str(returns.index[-1].date())],
    }
    if stability_gap > STABILITY_WARNING_THRESHOLD:
        logger.warning(
            "%s: train/test correlation gap %.3f exceeds stability threshold "
            "(train=%.3f, test=%.3f)", credit_stress["pair"], stability_gap, train_corr, test_corr,
        )

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "sovereign_credit_stress_correlation": credit_stress,
        "caveat": (
            "EMB-vs-IEF rolling correlation baseline is a real historical distribution "
            "(same technique as e10_cross_asset/e14_fixed_income). The absolute sovereign "
            "credit spread level and the market-implied default probability estimate are "
            "NOT calibrated here -- yfinance's ticker.info['yield'] is a live-only snapshot "
            "with no free historical time series, so there is no real historical spread "
            "distribution to calibrate a threshold against; the engine classifies/estimates "
            "these against static, documented conventions instead (see e15_credit/engine.py)."
        ),
    }
    calibration_path = MODELS_DIR / "calibration.json"
    calibration_path.write_text(json.dumps(report, indent=2))
    logger.info("Saved E15 calibration to %s", calibration_path)
    logger.info(
        "  Sovereign credit stress %s: baseline=%+.3f (train=%+.3f test=%+.3f stable=%s, n=%d, %s..%s)",
        credit_stress["pair"], credit_stress["baseline_correlation"],
        credit_stress["train_period_correlation"], credit_stress["test_period_correlation"],
        credit_stress["stable"], credit_stress["n_total_periods"],
        credit_stress["date_range"][0], credit_stress["date_range"][1],
    )
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    train()

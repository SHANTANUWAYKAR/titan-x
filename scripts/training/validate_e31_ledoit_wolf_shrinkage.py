"""
Module: validate_e31_ledoit_wolf_shrinkage.py
Description: Real, held-out validation for E31's new opt-in Ledoit-Wolf
    covariance shrinkage (covariance_matrix_from_returns(use_shrinkage=True)) --
    same Rule 3 discipline as every other calibrated parameter in this
    project: a candidate only replaces (or gets recommended over) the
    shipped default if it demonstrably beats it on real, genuinely
    held-out data, never assumed from theory alone.

    Method: for each of several real historical windows across this
    platform's own multi-asset-class universe, fit BOTH sample covariance
    and Ledoit-Wolf-shrunk covariance on an in-sample (fit) period, build
    min-variance weights from each, then measure REALIZED portfolio
    variance of those two fixed weight vectors against the genuinely
    unseen out-of-sample (holdout) period's actual returns. Lower realized
    OOS variance wins -- that is min-variance optimization's actual stated
    goal, so it is the correct, non-circular metric to judge this on (not
    in-sample variance, which shrinkage trivially always increases by
    construction).
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

import numpy as np

from project_titan_x.core.config import get_asset
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e31_portfolio_construction.engine import (
    covariance_matrix_from_returns,
    min_variance_weights,
)

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e31_portfolio_construction" / "ledoit_wolf_validation_report.json"

# One real basket per asset class this platform actually trades, per
# core/config/assets.py -- not an arbitrary large equity cross-section
# (skfolio/Ledoit-Wolf's original validation used hundreds of stocks;
# this platform's real universe is ~29 assets, so validating on ITS OWN
# real, small, cross-asset-class basket is the honest test, not a
# borrowed one).
UNIVERSE = ["EURUSD", "GBPUSD", "GOLD", "SILVER", "BTCUSD", "SP500"]

# Multiple independent fit/holdout splits (different windows), not one
# lucky/unlucky split -- same "don't trust a single split" discipline as
# E27 Walk-Forward Validation's own multi-fold design.
FIT_HOLDOUT_SPLITS = [
    (0, 500, 500, 650),   # fit on bars 0-500, hold out 500-650
    (150, 650, 650, 800),
    (300, 800, 800, 950),
]


def _realized_variance(weights: np.ndarray, holdout_returns: np.ndarray) -> float:
    portfolio_returns = holdout_returns @ weights
    return float(np.var(portfolio_returns, ddof=1))


def main() -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Explicit absolute data_dir: MarketDataEngine defaults to a cwd-relative
    # "data/" path, which would land in the wrong place if this script isn't
    # run from the project root -- same fix train_all_assets.py already
    # documents and applies.
    project_root = Path(__file__).resolve().parents[2]
    market_data = MarketDataEngine(data_dir=project_root / "data")

    returns_by_symbol: dict[str, np.ndarray] = {}
    for symbol in UNIVERSE:
        asset = get_asset(symbol)
        yahoo_symbol = asset.yahoo_symbol if asset else symbol
        fetch = market_data.fetch_ohlcv(yahoo_symbol, "1d", years=5)
        if not fetch.success or fetch.data is None or fetch.data.empty:
            logger.warning("%s: could not fetch OHLCV, excluding from validation", symbol)
            continue
        closes = fetch.data["close"].to_numpy(dtype=float)
        returns_by_symbol[symbol] = np.diff(closes) / closes[:-1]

    min_len = min(len(v) for v in returns_by_symbol.values())
    aligned = {s: v[-min_len:] for s, v in returns_by_symbol.items()}
    symbols = list(aligned.keys())
    logger.info("Real aligned data: %d symbols (%s), %d bars each", len(symbols), symbols, min_len)

    split_results = []
    for fit_start, fit_end, hold_start, hold_end in FIT_HOLDOUT_SPLITS:
        if hold_end > min_len:
            logger.warning("Split %s exceeds available %d bars, skipping", (fit_start, fit_end, hold_start, hold_end), min_len)
            continue

        fit_returns = {s: aligned[s][fit_start:fit_end] for s in symbols}
        holdout_matrix = np.column_stack([aligned[s][hold_start:hold_end] for s in symbols])

        _, cov_sample = covariance_matrix_from_returns(fit_returns, use_shrinkage=False)
        _, cov_shrunk = covariance_matrix_from_returns(fit_returns, use_shrinkage=True)

        w_sample = min_variance_weights(cov_sample, long_only=True)
        w_shrunk = min_variance_weights(cov_shrunk, long_only=True)

        var_sample = _realized_variance(w_sample, holdout_matrix)
        var_shrunk = _realized_variance(w_shrunk, holdout_matrix)
        shrinkage_wins = var_shrunk < var_sample

        result = {
            "fit_window": [fit_start, fit_end],
            "holdout_window": [hold_start, hold_end],
            "realized_oos_variance_sample_cov": var_sample,
            "realized_oos_variance_shrunk_cov": var_shrunk,
            "shrinkage_wins": shrinkage_wins,
            "improvement_pct": round((var_sample - var_shrunk) / var_sample * 100, 3) if var_sample > 0 else None,
        }
        split_results.append(result)
        logger.info(
            "Split fit=%s holdout=%s: sample_var=%.8f shrunk_var=%.8f shrinkage_wins=%s (%.2f%% change)",
            (fit_start, fit_end), (hold_start, hold_end), var_sample, var_shrunk, shrinkage_wins,
            result["improvement_pct"] or 0.0,
        )

    wins = sum(1 for r in split_results if r["shrinkage_wins"])
    total = len(split_results)
    # Rule 3's real bar: only recommend flipping the default if shrinkage
    # demonstrably beats sample covariance on a clear MAJORITY of genuinely
    # independent held-out splits, not a single favorable one.
    recommendation = (
        "adopt_as_default" if total > 0 and wins > total / 2
        else "keep_opt_in_only_not_default"
    )

    report = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "universe": symbols,
        "n_splits": total,
        "splits_where_shrinkage_won": wins,
        "recommendation": recommendation,
        "splits": split_results,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Recommendation: %s (%d/%d splits favored shrinkage)", recommendation, wins, total)
    logger.info("Report written to %s", OUTPUT_PATH)
    return report


if __name__ == "__main__":
    main()

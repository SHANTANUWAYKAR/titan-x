"""
Module: train_e19_global_liquidity.py
Description: Calibrate Engine 19's expanding/contracting regime thresholds
    for WALCL (Fed balance sheet) and M2SL (M2 money supply) against each
    series' own real historical 3-month percent-change distribution --
    replacing the previously static, undocumented +-1%/+-0.5% conventions.

    Newly possible because core.data_providers.fred now also fetches via
    FRED's public no-key CSV endpoint (fredgraph.csv, verified live --
    real 200s with full history, no API key required); the original
    static-threshold gap existed only because the REST API's api_key
    requirement was assumed to block ALL FRED access, which a separate
    live, verified request has since disproven (see fred.py's module
    docstring).

    Method: for every observation, compute the % change vs. the latest
    prior observation at least 91 days back -- a real calendar-date
    lookback, not a fixed observation-count offset (correct for both
    WALCL's weekly and M2SL's monthly release cadence, unlike the engine's
    previous "13 observations back" approximation). The calibrated
    threshold_pct is the 70th percentile of the ABSOLUTE value of that
    change distribution: a move must be in the top 30% of this series' own
    historical 3-month swings to count as a genuine expansion/contraction
    regime rather than routine drift -- same percentile-of-own-history
    convention as e11_microstructure's spread percentile / e16_commodity's
    Gold-Silver ratio bands.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.core.data_providers.fred import FredClient

logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_DIR / "data" / "models" / "e19_global_liquidity"
LOOKBACK_DAYS = 91  # ~3 months, matching the engine's own "3-month change" framing
THRESHOLD_PERCENTILE = 70.0
SERIES = ["WALCL", "M2SL"]


def _load_series(client: FredClient, series_id: str) -> pd.Series:
    obs = client.series_observations_csv(series_id)
    clean = [(o["date"], o["value"]) for o in obs if o.get("value") not in (None, ".", "")]
    dates = pd.to_datetime([d for d, _ in clean])
    values = np.array([float(v) for _, v in clean])
    return pd.Series(values, index=dates).sort_index()


def _three_month_pct_changes(series: pd.Series) -> np.ndarray:
    """% change of each observation vs. the latest prior observation at
    least LOOKBACK_DAYS earlier -- a real calendar-date lookback via binary
    search on the (sorted) date index, not a fixed row-count offset."""
    dates = series.index
    values = series.to_numpy()
    changes = []
    for i, d in enumerate(dates):
        cutoff = d - timedelta(days=LOOKBACK_DAYS)
        prior_idx = dates.searchsorted(cutoff, side="right") - 1
        if prior_idx < 0:
            continue
        past_value = values[prior_idx]
        if past_value == 0:
            continue
        changes.append((values[i] - past_value) / past_value * 100)
    return np.array(changes)


def train() -> dict:
    client = FredClient(cache_dir=PROJECT_DIR / "data" / "raw" / "fred_cache")
    report_series: dict[str, dict] = {}
    try:
        for series_id in SERIES:
            series = _load_series(client, series_id)
            changes = _three_month_pct_changes(series)
            abs_changes = np.abs(changes)
            threshold = float(np.percentile(abs_changes, THRESHOLD_PERCENTILE))
            report_series[series_id] = {
                "threshold_pct": round(threshold, 4),
                "percentile_used": THRESHOLD_PERCENTILE,
                "n_observations": int(len(series)),
                "n_change_samples": int(len(changes)),
                "date_range": [str(series.index[0].date()), str(series.index[-1].date())],
            }
            logger.info(
                "%s: threshold_pct=%.3f%% (n=%d changes, %s..%s)",
                series_id, threshold, len(changes),
                report_series[series_id]["date_range"][0], report_series[series_id]["date_range"][1],
            )
    finally:
        client.close()

    report = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "series": report_series,
        "caveat": (
            f"threshold_pct per series is the {THRESHOLD_PERCENTILE:.0f}th percentile of that "
            "series' own real historical |3-month % change| distribution (real calendar-date "
            "lookback, not a fixed observation-count offset) -- a move must be in the top "
            f"{100 - THRESHOLD_PERCENTILE:.0f}% of this series' own historical swings to be "
            "classified expanding/contracting rather than flat. Fetched via FRED's public "
            "no-key CSV endpoint (fredgraph.csv), full real history, no API key required."
        ),
    }
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    calibration_path = MODELS_DIR / "calibration.json"
    calibration_path.write_text(json.dumps(report, indent=2))
    logger.info("Saved E19 calibration to %s", calibration_path)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    train()

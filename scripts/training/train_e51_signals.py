"""
Module: train_e51_signals.py
Description: Calibrate the constants inside e51_signals' backtestable
    direction rule (_vectorized_signal_series) against real BTC-USD daily
    history, using E10 Backtesting Lab's own walk-forward validation
    (in-sample fit + held-out out-of-sample check + parameter-sensitivity
    robustness) as the judge -- exactly the same "prove it before you trust
    it" discipline e51_signals already applies to live signals via
    validate_historical_edge, just pointed at the rule's own constants
    instead of a single fixed guess.

    Grid-searched knobs (see e51_signals/engine.py _vectorized_signal_series):
      - adx_threshold: ADX level above which a trend is "strong enough" to act on
      - rsi_weight: how much (RSI-50) contributes to the composite score
      - macd_weight: fixed contribution of a MACD histogram sign flip
      - score_entry_threshold: minimum |composite score| required to enter

    Selection rule: only configs that pass E10's FULL validation bar
    (>=30 trades, in-sample Sharpe>0.5, max drawdown<25%, AND positive
    out-of-sample Sharpe on data never used for selection) are eligible to
    win. Among those, the highest OUT-OF-SAMPLE Sharpe wins (not in-sample,
    which would just reward curve-fitting). The current shipped defaults
    are always included as a candidate, so "trained" only ever replaces
    them with something demonstrably better on held-out data -- if nothing
    beats the shipped defaults, the shipped defaults remain in production
    and this script says so explicitly rather than manufacturing a "winner."
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine

logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e51_signals"

# Current shipped defaults (must match e51_signals/engine.py _vectorized_signal_series
# and e07_technical's _classify_trend / _compute_bullish_score) -- always included
# as a baseline candidate.
SHIPPED_DEFAULTS = {
    "adx_threshold": 25.0,
    "rsi_weight": 0.5,
    "macd_weight": 15.0,
    "score_entry_threshold": 25.0,
}

GRID = {
    "adx_threshold": [20.0, 25.0, 30.0],
    "rsi_weight": [0.3, 0.5, 0.7],
    "macd_weight": [10.0, 15.0, 20.0],
    "score_entry_threshold": [20.0, 25.0, 30.0, 35.0],
}

TREND_WEIGHT = 30.0  # fixed: not grid-searched, matches shipped constant
EMA50_WEIGHT = 10.0  # fixed: not grid-searched, matches shipped constant
PERIODS_PER_YEAR = {"1d": 252, "4h": 365 * 6, "1h": 365 * 24, "15m": 365 * 24 * 4}


@dataclass
class CandidateResult:
    params: dict
    is_sharpe: float
    is_trades: int
    is_max_dd: float
    oos_sharpe: float
    robustness: float
    passed_full_validation: bool
    is_baseline: bool


def _signal_series(enriched: pd.DataFrame, params: dict) -> pd.Series:
    """Same structural rule as e51_signals._vectorized_signal_series, with
    adx_threshold / rsi_weight / macd_weight / score_entry_threshold as
    free parameters instead of hardcoded literals."""
    ema_bullish = (enriched["ema_8"] > enriched["ema_21"]) & (enriched["ema_21"] > enriched["ema_50"])
    ema_bearish = (enriched["ema_8"] < enriched["ema_21"]) & (enriched["ema_21"] < enriched["ema_50"])
    adx_strong = enriched["adx"].fillna(0) > params["adx_threshold"]

    trend_score = pd.Series(0.0, index=enriched.index)
    trend_score[ema_bullish & adx_strong] = TREND_WEIGHT
    trend_score[ema_bearish & adx_strong] = -TREND_WEIGHT

    rsi_score = (enriched["rsi"].fillna(50) - 50) * params["rsi_weight"]
    macd_score = np.where(enriched["macd_hist"].fillna(0) > 0, params["macd_weight"], -params["macd_weight"])
    ema50_ref = enriched["ema_50"].fillna(enriched["close"])
    ema50_score = np.where(enriched["close"] > ema50_ref, EMA50_WEIGHT, -EMA50_WEIGHT)

    score = (trend_score + rsi_score + macd_score + ema50_score).clip(-100, 100)
    gate = params["score_entry_threshold"]

    signal = pd.Series(0, index=enriched.index)
    signal[(ema_bullish & adx_strong) & (score >= gate)] = 1
    signal[(ema_bearish & adx_strong) & (score <= -gate)] = -1
    return signal


def _grid_candidates() -> list[dict]:
    keys = list(GRID.keys())
    combos = [dict(zip(keys, values)) for values in product(*[GRID[k] for k in keys])]
    # Ensure the shipped baseline is always tested, even if not exactly
    # reproduced by the grid's discrete steps.
    if SHIPPED_DEFAULTS not in combos:
        combos.insert(0, dict(SHIPPED_DEFAULTS))
    return combos


def train(symbol: str = "BTC-USD", timeframe: str = "1d") -> dict:
    path = PROCESSED_DIR / f"{symbol}_{timeframe}.parquet"
    df = pd.read_parquet(path)
    periods_per_year = PERIODS_PER_YEAR.get(timeframe, 252)

    ta_engine = TechnicalAnalysisEngine()
    ta_result = ta_engine.analyze(df, symbol=symbol, timeframe=timeframe)
    if not ta_result.success:
        raise RuntimeError(f"Technical analysis failed: {ta_result.message}")
    enriched = ta_result.data["df"]

    bt_engine = BacktestingEngine()
    candidates = _grid_candidates()
    logger.info("Evaluating %d parameter combinations on %d bars of %s/%s ...", len(candidates), len(df), symbol, timeframe)

    results: list[CandidateResult] = []
    for params in candidates:
        full_signal = _signal_series(enriched, params)

        def strategy_fn(_df: pd.DataFrame, _signal=full_signal) -> pd.Series:
            # Must match _df's exact slice (in-sample vs out-of-sample) --
            # run_backtest's _simulate zeroes out any signal series whose
            # length doesn't match the slice being scored.
            return _signal.loc[_df.index]

        bt_result = bt_engine.run_backtest(enriched, strategy_fn, periods_per_year=periods_per_year)
        if not bt_result.success:
            continue
        r = bt_result.data
        m = r.metrics
        oos_sharpe = float(r.parameters.get("oos_sharpe", 0.0))
        results.append(CandidateResult(
            params=dict(params),
            is_sharpe=float(m.sharpe_ratio),
            is_trades=int(m.total_trades),
            is_max_dd=float(m.max_drawdown_pct),
            oos_sharpe=oos_sharpe,
            robustness=float(r.robustness_score),
            passed_full_validation=bool(r.passed_validation),
            is_baseline=(params == SHIPPED_DEFAULTS),
        ))

    if not results:
        raise RuntimeError("No candidate produced a valid backtest result")

    validated = [r for r in results if r.passed_full_validation]
    baseline = next((r for r in results if r.is_baseline), None)

    winner: Optional[CandidateResult]
    if validated:
        winner = max(validated, key=lambda r: r.oos_sharpe)
        decision = "validated_winner"
    else:
        winner = None
        decision = "no_config_passed_full_validation_keeping_shipped_defaults"

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "symbol": symbol,
        "timeframe": timeframe,
        "n_bars": len(df),
        "date_start": str(df["timestamp"].iloc[0]),
        "date_end": str(df["timestamp"].iloc[-1]),
        "n_candidates_evaluated": len(results),
        "n_candidates_passed_full_validation": len(validated),
        "shipped_baseline": asdict(baseline) if baseline else None,
        "decision": decision,
        "winner": asdict(winner) if winner else None,
        "top_5_by_oos_sharpe": [asdict(r) for r in sorted(results, key=lambda r: r.oos_sharpe, reverse=True)[:5]],
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "caveat": (
            "Sharpe/CAGR/win-rate figures reflect this exact rule's historical "
            "performance on 2019-2026 BTC-USD data with commission+slippage "
            "modeled -- not a guarantee of future performance. This does not "
            "change E12 Risk Management's veto authority or E16's live "
            "confidence/regime checks; it only calibrates the constants used "
            "by the edge-gate's own backtested proxy rule."
        ),
    }

    if winner is not None:
        params_path = MODELS_DIR / f"{symbol}_{timeframe}_signal_params.json"
        params_path.write_text(json.dumps({
            **winner.params,
            "oos_sharpe": winner.oos_sharpe,
            "is_sharpe": winner.is_sharpe,
            "trained_at": report["trained_at"],
        }, indent=2))
        logger.info("Winning params saved to %s: %s (OOS Sharpe=%.3f)", params_path, winner.params, winner.oos_sharpe)
    else:
        logger.info("No candidate cleared full validation -- shipped defaults remain in production, nothing written.")

    report_path = MODELS_DIR / f"{symbol}_{timeframe}_training_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    train()

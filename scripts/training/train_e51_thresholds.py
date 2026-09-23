"""
Module: train_e51_thresholds.py
Description: Per-asset PARAMETER tuning for _vectorized_signal_series
    (entry_threshold, adx_divisor) -- distinct from
    research_signal_strategies*.py, which searches for an entirely
    different STRUCTURAL rule (e.g. SP500's Donchian breakout). This
    script re-tunes the SAME Command-Center-style trend/momentum formula's
    constants, on the theory that some assets might just need a different
    threshold on the identical rule rather than a different rule
    altogether.

    Validation methodology: reuses e26_backtesting.run_backtest's own
    real in-sample (70%) / out-of-sample (30%) split -- the SAME bar
    SP500's Donchian override had to clear (IS trades>=30, IS Sharpe>0.5,
    IS max_drawdown<25%, OOS Sharpe>0). For each asset, every candidate in
    the grid is scored on IS Sharpe; the winner is then checked against
    passed_validation. A candidate is only saved as
    data/models/e51_signals/{yahoo_symbol}_{timeframe}_tuned_params.json
    if it clears the FULL bar -- an asset where nothing in the grid clears
    it gets NO file (Rule 3/4: no candidate beats the shipped default, so
    the shipped default -- and the edge-gate's honest veto -- stands).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import itertools
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from project_titan_x.core.config import get_settings
from project_titan_x.core.config.assets import list_assets
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.engines.e40_data_quality.engine import DataQualityEngine
from project_titan_x.engines.e51_signals.engine import SignalIntelligenceEngine, _load_strategy_override

logger = logging.getLogger(__name__)
MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e51_signals"

CANDIDATE_ENTRY_THRESHOLDS = [0.10, 0.15, 0.20, 0.25, 0.30]
CANDIDATE_ADX_DIVISORS = [20.0, 25.0, 30.0]

# SP500 already has its own validated STRUCTURAL override (Donchian) --
# re-tuning the general rule's parameters for it would be pointless (its
# live signal never uses this formula at all).
SKIP_SYMBOLS = {"SP500"}


def _grade_candidate(enriched, params, backtesting_engine):
    full_signal = SignalIntelligenceEngine._vectorized_signal_series(enriched, params)

    def strategy_fn(_df):
        return full_signal.loc[_df.index]

    result = backtesting_engine.run_backtest(enriched, strategy_fn)
    if not result.success:
        return None
    return result.data


def _load_price_history(market_data_engine, yahoo_symbol: str, timeframe: str):
    """Prefer the local processed-data cache over a live fetch: a live
    fetch_ohlcv(years=10) call would ignore the far deeper history now
    sitting in data/processed/ from imported datasets (some assets go
    back to 2000-2001, or carry 1-minute granularity yfinance's free
    tier can't reach at all). Falls back to a live fetch only when no
    local cache exists yet -- which also correctly seeds the cache for
    next time via e02_market_data's own merge-on-fetch behavior."""
    cache_path = market_data_engine.processed_dir / f"{yahoo_symbol}_{timeframe}.parquet"
    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        return df, f"local_cache ({cache_path.name})"
    fetch = market_data_engine.fetch_ohlcv(yahoo_symbol, timeframe, years=10)
    if not fetch.success:
        return None, f"fetch failed: {fetch.message}"
    return fetch.data, "live_fetch"


def train_asset(symbol: str, yahoo_symbol: str, timeframe: str, market_data_engine, technical_engine, backtesting_engine) -> dict:
    result: dict = {"symbol": symbol, "yahoo_symbol": yahoo_symbol}

    if _load_strategy_override(yahoo_symbol, timeframe):
        result["skipped"] = "has a structural strategy override already -- parameter tuning would never be used live"
        return result

    df, source = _load_price_history(market_data_engine, yahoo_symbol, timeframe)
    if df is None:
        result["error"] = source
        return result
    result["data_source"] = source
    dq_engine = DataQualityEngine()
    repaired = dq_engine.repair(df)
    if repaired.success:
        df = repaired.data
    result["n_bars"] = len(df)

    ta_result = technical_engine.analyze(df, symbol=symbol, timeframe=timeframe)
    if not ta_result.success:
        result["error"] = f"technical analysis failed: {ta_result.message}"
        return result
    enriched = ta_result.data["df"]

    candidates = []
    for entry_threshold, adx_divisor in itertools.product(CANDIDATE_ENTRY_THRESHOLDS, CANDIDATE_ADX_DIVISORS):
        params = {"entry_threshold": entry_threshold, "adx_divisor": adx_divisor}
        try:
            bt = _grade_candidate(enriched, params, backtesting_engine)
        except Exception as e:
            logger.warning("%s: candidate %s failed: %s", symbol, params, e)
            continue
        if bt is None:
            continue
        candidates.append({
            "params": params,
            "is_sharpe": bt.metrics.sharpe_ratio,
            "is_trades": bt.metrics.total_trades,
            "is_max_dd": bt.metrics.max_drawdown_pct,
            "is_win_rate": bt.metrics.win_rate,
            "oos_sharpe": bt.parameters.get("oos_sharpe", 0.0),
            "passed_validation": bt.passed_validation,
        })
        logger.info(
            "%s params=%s -> IS Sharpe=%.2f trades=%d maxDD=%.1f%% OOS Sharpe=%.2f validated=%s",
            symbol, params, bt.metrics.sharpe_ratio, bt.metrics.total_trades,
            bt.metrics.max_drawdown_pct, bt.parameters.get("oos_sharpe", 0.0), bt.passed_validation,
        )

    result["candidates"] = candidates
    if not candidates:
        result["decision"] = "no candidate could be backtested"
        return result

    # Prefer a validated winner (by IS Sharpe among those that passed);
    # fall back to reporting the best IS Sharpe even if nothing validated,
    # for visibility -- but only a VALIDATED winner ever gets saved.
    validated = [c for c in candidates if c["passed_validation"]]
    if validated:
        winner = max(validated, key=lambda c: c["is_sharpe"])
        result["decision"] = "validated tuning found -- saving override"
        result["winner"] = winner
        override = {
            **winner["params"],
            "win_rate": winner["is_win_rate"],
            "oos_sharpe": winner["oos_sharpe"],
            "total_trades": winner["is_trades"],
            # Tuned overrides use the platform's own blanket floor -- unlike
            # a structural override (e.g. Donchian), this is still the SAME
            # confidence formula the general rule always used, just with
            # re-tuned constants, so the general floor still applies.
            "min_confidence": get_settings().min_signal_confidence,
            "trained_at": datetime.now(timezone.utc).isoformat(),
        }
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        path = MODELS_DIR / f"{yahoo_symbol}_{timeframe}_tuned_params.json"
        path.write_text(json.dumps(override, indent=2))
        result["saved_to"] = str(path)
    else:
        best_unvalidated = max(candidates, key=lambda c: c["is_sharpe"])
        result["decision"] = "no candidate cleared the full IS+OOS validation bar -- honest gap, no override saved"
        result["best_unvalidated"] = best_unvalidated

    return result


def main() -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    project_root = Path(__file__).resolve().parents[2]
    market_data_engine = MarketDataEngine(data_dir=project_root / "data")
    market_data_engine.initialize()
    technical_engine = TechnicalAnalysisEngine()
    technical_engine.initialize()
    backtesting_engine = BacktestingEngine()
    backtesting_engine.initialize()

    results = {}
    for asset in list_assets():
        if asset.symbol in SKIP_SYMBOLS:
            results[asset.symbol] = {"symbol": asset.symbol, "skipped": "in SKIP_SYMBOLS (has a structural override)"}
            continue
        logger.info("=== Training thresholds for %s (%s) ===", asset.symbol, asset.yahoo_symbol)
        results[asset.symbol] = train_asset(
            asset.symbol, asset.yahoo_symbol, "1d", market_data_engine, technical_engine, backtesting_engine
        )

    report = {"trained_at": datetime.now(timezone.utc).isoformat(), "assets": results}
    (MODELS_DIR / "threshold_tuning_report.json").write_text(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    main()

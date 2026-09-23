"""
Module: train_engines.py
Description: Orchestrates training/calibration of PROJECT TITAN-X's
    engines against real historical data: rebuilds the BTC-USD dataset
    from the user-supplied 5-minute CSVs, calibrates Engine 08's
    regime-HMM hyperparameters, calibrates Engine 16's backtestable
    signal-rule constants, and calibrates Engine 05's NFP volatility
    multiplier -- then writes one consolidated, honest report covering
    every implemented engine, including the ones with nothing to train.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import load_btc_data
import train_e05_economic_calendar
import train_e08_regime
import train_e51_signals

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models"

NOTHING_TO_TRAIN = {
    "e01_knowledge": "Semantic search index over a fixed trader-wisdom corpus (sentence-transformers + Qdrant/FAISS) -- no supervised objective or backtestable performance metric to optimize against BTC price data.",
    "e02_market_data": "Data-fetch fallback chain (yfinance -> ccxt -> nselib -> Alpha Vantage). No model parameters; 'performance' here means source availability, not something fit to history.",
    "e04_macro": "Macro indicator fetch (Alpha Vantage + World Bank) with fixed, published thresholds (e.g. risk-on/off scoring) -- no free parameters calibrated against price history.",
    "e06_fundamental": "Yield curve / real-yield / WTI-Brent spread readings -- direct calculations from fetched series, no fittable parameters.",
    "e07_technical": "Indicator math (EMA/RSI/MACD/ADX/etc.) is deterministic, not fit; the two THRESHOLD constants that feed a backtestable rule live in e51_signals._vectorized_signal_series and were calibrated there (see e51_signals report).",
    "e03_news": "RSS ingestion + article extraction -- no model parameters.",
    "e12_quant_research": "Risk/statistics utilities (Sharpe, Kelly, VaR/CVaR, cointegration, Bayesian win-rate update) are stateless formulas invoked with live inputs -- no persisted weights to save.",
    "e09_sentiment": "FinBERT is a frozen pretrained model (fine-tuning it would need far more labeled text than this project has); VADER/TextBlob fallback is a fixed lexicon. Not retrained.",
    "e11_microstructure": "Corwin-Schultz spread estimator is a closed-form formula from OHLC alone -- no free parameters to fit.",
    "e45_risk": "CRO veto/risk-limit engine -- deliberately NOT optimized for backtested returns; its entire job is being a conservative hard limiter, independent of any single engine's historical performance.",
}


def main() -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("=== Step 1/4: rebuilding BTC-USD historical dataset ===")
    datasets = load_btc_data.build_all(save=True)
    logger.info(load_btc_data.summarize(datasets))

    logger.info("=== Step 2/4: calibrating E08 regime-HMM hyperparameters ===")
    e08_report = train_e08_regime.train(symbol="BTC-USD", timeframe="1d")

    logger.info("=== Step 3/4: calibrating E16 signal-rule constants ===")
    e16_report = train_e51_signals.train(symbol="BTC-USD", timeframe="1d")

    logger.info("=== Step 4/4: calibrating E05 NFP volatility multiplier ===")
    # train_e05_economic_calendar.train() dropped its symbol/timeframe params
    # 2026-08-18 (it now loops over EVERY event in EVENT_DATE_GENERATORS x
    # every supported asset internally, not just one asset) -- this call
    # site was never updated to match, so it TypeError'd every time
    # execution reached Step 4. Never actually reached before today: Step 1
    # always failed first (missing Binance CSVs) until the Dukascopy
    # fallback fixed that -- so this second, independent bug was masked
    # until now. Fixed by dropping the stale kwargs; the result is now an
    # all-events-all-assets report, not one BTC-USD-specific number.
    e05_report = train_e05_economic_calendar.train()

    consolidated = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_summary": {label: len(df) for label, df in datasets.items()},
        "e05_economic_calendar": {
            "action": "Calibrated expected-volatility multipliers for every event type in EVENT_DATE_GENERATORS (NFP plus whatever else has been added since), per asset, from realized historical moves around release times -- not scoped to BTC-USD alone.",
            "report_path": str(MODELS_DIR / "e05_economic_calendar" / "volatility_calibration.json"),
            "result": e05_report,
        },
        "e08_regime": {
            "action": "Hyperparameter search only (n_components, covariance_type). Live defaults changed ONLY if the wired constants in engine.py were edited -- check e08_regime/engine.py directly.",
            "report_path": str(MODELS_DIR / "e08_regime" / "BTC-USD_1d_hmm_meta.json"),
            "winner": e08_report.winner,
        },
        "e51_signals": {
            "action": "Grid search over ADX threshold / RSI weight / MACD weight / entry score gate, validated via E26 walk-forward backtest (in-sample + out-of-sample split).",
            "report_path": str(MODELS_DIR / "e51_signals" / "BTC-USD_1d_training_report.json"),
            "decision": e16_report["decision"],
            "winner": e16_report["winner"],
        },
        "not_trained": NOTHING_TO_TRAIN,
    }
    (MODELS_DIR / "training_report.json").write_text(json.dumps(consolidated, indent=2, default=str))
    return consolidated


if __name__ == "__main__":
    main()

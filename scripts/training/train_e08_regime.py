"""
Module: train_e08_regime.py
Description: Calibrate Engine 04's volatility-regime HMM hyperparameters
    (n_components, covariance_type) against real BTC-USD history.

    e08_regime/engine.py already fits a fresh 2-state diag-covariance
    GaussianHMM on whatever return series it's given, on every call --
    there are no persisted weights to "save" for live inference (a frozen
    model would go stale; refitting on ~60-1000 bars is already cheap).
    What genuinely IS worth training and saving here is the HYPERPARAMETER
    choice itself: is 2 states actually better than 3? Is diagonal
    covariance actually better than full? This script answers that with a
    real train/held-out-validation split (not in-sample fit quality, which
    trivially favors more states) and persists both the winning
    hyperparameters (JSON, for engine.py to read) and the fully-fit model
    object (joblib, for inspection/audit) to data/models/e08_regime/.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e08_regime"

CANDIDATE_N_COMPONENTS = [2, 3]
CANDIDATE_COVARIANCE_TYPES = ["diag", "full"]
VALIDATION_FRACTION = 0.2  # last 20% of history held out, time-ordered (no shuffling)
MIN_BARS = 250


@dataclass
class HMMCandidateResult:
    n_components: int
    covariance_type: str
    train_avg_loglik: float
    holdout_avg_loglik: float
    converged: bool


@dataclass
class HMMTrainingReport:
    symbol: str
    timeframe: str
    n_bars: int
    date_start: str
    date_end: str
    candidates: list[dict]
    winner: dict
    trained_at: str


def _log_returns(df: pd.DataFrame) -> np.ndarray:
    returns = np.log(df["close"]).diff().dropna().to_numpy()
    return returns.reshape(-1, 1)


def _fit_and_score(
    train: np.ndarray, holdout: np.ndarray, n_components: int, covariance_type: str
) -> HMMCandidateResult:
    model = GaussianHMM(
        n_components=n_components,
        covariance_type=covariance_type,
        n_iter=200,
        random_state=42,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(train)
        train_ll = model.score(train)
        holdout_ll = model.score(holdout)
    return HMMCandidateResult(
        n_components=n_components,
        covariance_type=covariance_type,
        train_avg_loglik=train_ll / len(train),
        holdout_avg_loglik=holdout_ll / len(holdout),
        converged=bool(model.monitor_.converged),
    )


def train(symbol: str = "BTC-USD", timeframe: str = "1d") -> HMMTrainingReport:
    """Grid-search HMM hyperparameters on `symbol`/`timeframe` history,
    select the config with the best HELD-OUT (not in-sample) average
    log-likelihood, refit on full history, and persist both the model and
    the winning hyperparameters."""
    path = PROCESSED_DIR / f"{symbol}_{timeframe}.parquet"
    df = pd.read_parquet(path)
    if len(df) < MIN_BARS:
        raise ValueError(f"Need at least {MIN_BARS} bars, got {len(df)} for {symbol}/{timeframe}")

    returns = _log_returns(df)
    split = int(len(returns) * (1 - VALIDATION_FRACTION))
    train_returns, holdout_returns = returns[:split], returns[split:]

    results: list[HMMCandidateResult] = []
    for n_components in CANDIDATE_N_COMPONENTS:
        for covariance_type in CANDIDATE_COVARIANCE_TYPES:
            try:
                result = _fit_and_score(train_returns, holdout_returns, n_components, covariance_type)
                results.append(result)
                logger.info(
                    "n_components=%d covariance_type=%s -> holdout avg log-lik=%.5f (train=%.5f, converged=%s)",
                    n_components, covariance_type, result.holdout_avg_loglik,
                    result.train_avg_loglik, result.converged,
                )
            except Exception as e:
                logger.warning("Candidate n_components=%d covariance_type=%s failed: %s", n_components, covariance_type, e)

    if not results:
        raise RuntimeError("No HMM candidate converged -- cannot select a winner")

    best = max(results, key=lambda r: r.holdout_avg_loglik)

    # Refit the winning config on the FULL history for the persisted artifact.
    final_model = GaussianHMM(
        n_components=best.n_components,
        covariance_type=best.covariance_type,
        n_iter=200,
        random_state=42,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        final_model.fit(returns)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"{symbol}_{timeframe}_hmm.pkl"
    joblib.dump(final_model, model_path)

    report = HMMTrainingReport(
        symbol=symbol,
        timeframe=timeframe,
        n_bars=len(df),
        date_start=str(df["timestamp"].iloc[0]),
        date_end=str(df["timestamp"].iloc[-1]),
        candidates=[asdict(r) for r in results],
        winner={"n_components": best.n_components, "covariance_type": best.covariance_type,
                "holdout_avg_loglik": best.holdout_avg_loglik},
        trained_at=datetime.now(timezone.utc).isoformat(),
    )
    report_path = MODELS_DIR / f"{symbol}_{timeframe}_hmm_meta.json"
    report_path.write_text(json.dumps(asdict(report), indent=2))
    logger.info("Winner: n_components=%d covariance_type=%s -> saved to %s", best.n_components, best.covariance_type, model_path)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    train()

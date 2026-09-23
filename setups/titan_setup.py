"""
Module: titan_setup.py
Description: One composed setup, built only from things that MEASURED as working
    during the 2026-09-20/21 audit. Every component below has a number behind
    it and a reason it is here rather than a plausible story.

    WHAT WENT IN, AND THE EVIDENCE

      Direction rule -- the existing live composite, unchanged. Not because it
        is good (it wins 33.6% against a 33.3% breakeven) but because
        meta-labelling needs a HIGH-RECALL primary, and this one fires 101,516
        times. Replacing it with something more selective would remove the very
        property the skip-filter exploits.

      Meta-label skip filter -- the one idea that turned the economics positive
        out of sample. Trained chronologically (never shuffled), it moved the
        net from -0.0458% to +0.3864% per trade at p>=0.60, with the win rate
        climbing 33.8% -> 48.2% and trade count falling 40,607 -> 197. Both
        directions monotone. Test ROC-AUC 0.5365 -- real but small, so the
        threshold is a dial, not a switch.

      Triple-barrier exits -- stop, target and a time limit, all ATR-scaled.
        Volatility-scaled barriers make the label regime-aware by construction
        rather than by a bolted-on filter.

      Risk-based sizing -- a stop-distance move costs exactly risk_pct. Under
        the old notional sizing a "1% risk" trade cost anywhere from 0.0070% to
        0.2197% of equity, a 31x spread on trades that should each have cost the
        same.

      ADX band gate -- the published institutional practice is ADX roughly
        20-30: enough trend to sustain a move, not so extended that reversal is
        due. Included as a CONFIGURABLE gate, defaulted OFF, because it is the
        one component here I have not measured on this book. Turning it on is a
        hypothesis to test, not a result to inherit.

      Volume confirmation -- likewise published practice (entry bar >= 1.5x its
        20-bar average), likewise defaulted OFF and unmeasured here.

    WHAT WAS DELIBERATELY LEFT OUT, AND WHY

      More indicators. The feature sweep collapsed 16 "informative" features
        into two redundant groups plus directional beta.
      Consensus across parameterisations. 27 variants measured 0.974 mean
        pairwise correlation and already agreed on 87.2% of bars -- one opinion
        repeated, so requiring agreement filtered 13% of trades and moved the
        win rate 0.07pt.
      Cross-asset breadth/dispersion/correlation. Helped longs and hurt shorts
        by matching amounts, which is beta wearing a costume.
      Wider stops. Looked net-positive until 65% of trades turned out never to
        resolve and were being silently excluded.

    HOW TO READ A RESULT FROM THIS. The skip filter is trained per fold on data
    strictly before the fold it is tested on. A setup that only works with the
    filter trained on the future is not a setup.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# E26's own cost assumption: 0.1% commission + 0.05% slippage per side.
COST_ROUND_TRIP = 0.003


@dataclass
class SetupConfig:
    """Every knob, with the measured default and why it is that value."""

    # --- direction (the live rule, unchanged) --------------------------------
    entry_threshold: float = 0.20
    adx_divisor: float = 25.0
    momentum_divisor: float = 25.0
    disagreement_dampening: float = 0.5

    # --- triple barrier ------------------------------------------------------
    atr_mult: float = 1.0          # stop distance in ATR
    reward_risk: float = 2.0       # target = reward_risk * stop
    horizon_bars: int = 20         # time barrier

    # --- sizing --------------------------------------------------------------
    risk_pct: float = 0.01
    max_leverage: float = 3.0      # notional cap; risk/stop explodes on tight stops

    # --- skip filter ---------------------------------------------------------
    use_meta_filter: bool = True
    meta_threshold: float = 0.50   # 0.60 was best in test but left only 197 trades
    meta_min_train: int = 2000     # below this a fold cannot train a useful filter

    # --- UNMEASURED on this book: default OFF -------------------------------
    use_adx_band: bool = False
    adx_band: tuple[float, float] = (20.0, 30.0)
    use_volume_confirm: bool = False
    volume_mult: float = 1.5

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["adx_band"] = list(self.adx_band)
        return d


def direction_score(e: pd.DataFrame, cfg: SetupConfig) -> np.ndarray:
    """The live rule's combined score. Causal: every input is known at the bar."""
    trend_sign = np.where(e["ema_8"] >= e["ema_21"], 1.0, -1.0)
    macd_sign = np.where(e["macd"].fillna(0) >= e["macd_signal"].fillna(0), 1.0, -1.0)
    adx_ratio = np.clip(e["adx"].fillna(0).to_numpy() / cfg.adx_divisor, -1, 1)
    trend = adx_ratio * trend_sign
    trend = np.where(macd_sign != trend_sign, trend * cfg.disagreement_dampening, trend)
    mom = np.clip((e["rsi"].fillna(50).to_numpy() - 50) / cfg.momentum_divisor, -1, 1)
    return (trend + mom) / 2.0


def _passes_gates(e: pd.DataFrame, i: int, cfg: SetupConfig) -> bool:
    if cfg.use_adx_band:
        adx = e["adx"].iloc[i]
        if not np.isfinite(adx) or not (cfg.adx_band[0] <= adx <= cfg.adx_band[1]):
            return False
    if cfg.use_volume_confirm and "volume" in e.columns:
        v = e["volume"].iloc[i]
        avg = e["volume"].iloc[max(0, i - 20):i].mean()
        if not np.isfinite(v) or not np.isfinite(avg) or avg <= 0 or v < cfg.volume_mult * avg:
            return False
    return True


FEATURE_SKIP = {"open", "high", "low", "close", "volume", "symbol", "timeframe",
                "timestamp", "dividends", "stock_splits"}
# Divided by close so an instrument at 4,000 and one at 1.08 land on one axis --
# a tree splits on thresholds, so raw levels would just encode "which market".
PRICE_SCALED = {
    "atr", "bb_width", "obv", "vwap", "bb_upper", "bb_lower", "bb_middle",
    "ema_8", "ema_21", "ema_50", "ema_200", "vwap_upper_1", "vwap_upper_2",
    "vwap_lower_1", "vwap_lower_2", "ichimoku_kijun", "ichimoku_tenkan",
    "ichimoku_senkou_a", "ichimoku_senkou_b", "macd", "macd_signal", "macd_hist",
}


def extract_signals(e: pd.DataFrame, cfg: SetupConfig) -> pd.DataFrame:
    """Every firing signal with its triple-barrier outcome and feature row.

    Entry is the NEXT bar's open: the score is only knowable once the bar
    closes, so entering at that close is a fill nobody could get. The stop is
    checked BEFORE the target on every bar, so a bar containing both is scored a
    loss -- OHLC cannot order two touches inside one bar, and this is the same
    convention forward_test uses.
    """
    comb = direction_score(e, cfg)
    hi = e["high"].to_numpy(float)
    lo = e["low"].to_numpy(float)
    op = e["open"].to_numpy(float)
    close = e["close"].to_numpy(float)
    atr = e["atr"].to_numpy(float)
    ts = (pd.to_datetime(e["timestamp"], utc=True, errors="coerce")
          if "timestamp" in e.columns else pd.to_datetime(e.index, utc=True, errors="coerce"))
    ts = pd.Series(ts).to_numpy()

    feats = [c for c in e.columns
             if c not in FEATURE_SKIP and pd.api.types.is_numeric_dtype(e[c])]
    F = {c: e[c].to_numpy(float) for c in feats}

    n = len(e)
    rows = []
    for i in range(n - cfg.horizon_bars - 1):
        s, A = comb[i], atr[i]
        if not np.isfinite(s) or abs(s) < cfg.entry_threshold:
            continue
        if not np.isfinite(A) or A <= 0:
            continue
        if not _passes_gates(e, i, cfg):
            continue
        d = 1 if s > 0 else -1
        entry = op[i + 1]
        if not np.isfinite(entry) or entry <= 0:
            continue

        stop_frac = (cfg.atr_mult * A) / entry
        if not np.isfinite(stop_frac) or stop_frac <= 0:
            continue
        stop = entry - d * cfg.atr_mult * A
        target = entry + d * cfg.reward_risk * cfg.atr_mult * A

        win, bars_held = None, 0
        for j in range(i + 1, min(i + 1 + cfg.horizon_bars, n)):
            bars_held = j - i
            if (d == 1 and lo[j] <= stop) or (d == -1 and hi[j] >= stop):
                win = 0
                break
            if (d == 1 and hi[j] >= target) or (d == -1 and lo[j] <= target):
                win = 1
                break
        if win is None:
            continue   # time barrier hit unresolved; excluded and COUNTED below

        row = {c: (F[c][i] / close[i] if (c in PRICE_SCALED and close[i]) else F[c][i])
               for c in feats}
        row["_dir"] = float(d)
        row["_conf"] = abs(s) * 100.0
        row["_win"] = win
        row["_ts"] = ts[i]
        row["_stop_frac"] = stop_frac
        row["_bars_held"] = bars_held
        # Notional actually deployed, capped exactly as E26 caps it.
        row["_notional"] = float(min(cfg.risk_pct / stop_frac, cfg.max_leverage))
        rows.append(row)
    return pd.DataFrame(rows)


def economics(df: pd.DataFrame, cfg: SetupConfig) -> dict[str, Any]:
    """Win rate, gross R and NET of costs at this setup's own turnover."""
    if df.empty:
        return {"trades": 0}
    y = df["_win"].to_numpy(float)
    wr = float(y.mean())
    gross_R = wr * cfg.reward_risk - (1 - wr)
    gross_pct = gross_R * cfg.risk_pct * 100
    cost_pct = float((COST_ROUND_TRIP * df["_notional"]).mean()) * 100
    return {
        "trades": int(len(df)),
        "win_rate": wr,
        "gross_R": gross_R,
        "gross_pct_per_trade": gross_pct,
        "cost_pct_per_trade": cost_pct,
        "net_pct_per_trade": gross_pct - cost_pct,
        "breakeven_win_rate": 1.0 / (1.0 + cfg.reward_risk),
        "mean_notional": float(df["_notional"].mean()),
        # Diagnostic only, and OPTIONAL: economics needs `_win` and `_notional`
        # and nothing else. Hard-requiring a diagnostic column made this raise
        # KeyError on any frame a caller had assembled or filtered down --
        # caught by tests/unit/test_setups.py, which passed exactly the columns
        # the calculation actually uses.
        "mean_bars_held": (float(df["_bars_held"].mean())
                           if "_bars_held" in df.columns else None),
    }


def fit_meta_filter(train: pd.DataFrame, cfg: SetupConfig):
    """Secondary model: given a signal fired, will it WIN?

    A different architecture from the primary on purpose. The primary is a
    linear weighted average thresholded at a constant; a gradient-boosted tree
    can represent interactions and regime-dependent thresholds on the same
    features that a weighted average structurally cannot. That asymmetry is the
    only honest reason to expect a second model to add anything -- when both
    models are the same shape, it cannot.
    """
    if len(train) < cfg.meta_min_train:
        return None
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
    except ImportError:
        logger.warning("scikit-learn unavailable -- meta filter disabled")
        return None
    cols = [c for c in train.columns if not c.startswith("_")]
    X = train[cols].replace([np.inf, -np.inf], np.nan)
    X = X.fillna(X.median(numeric_only=True))
    y = train["_win"].to_numpy(float)
    if len(np.unique(y)) < 2:
        return None
    clf = HistGradientBoostingClassifier(
        max_depth=4, max_iter=250, learning_rate=0.05, random_state=7)
    clf.fit(X, y)
    return (clf, cols, X.median(numeric_only=True))


def apply_meta_filter(model, test: pd.DataFrame, cfg: SetupConfig) -> pd.DataFrame:
    """Keep only signals the secondary model rates above the threshold."""
    if model is None or test.empty:
        return test
    clf, cols, med = model
    X = test[cols].replace([np.inf, -np.inf], np.nan).fillna(med)
    p = clf.predict_proba(X)[:, 1]
    out = test.copy()
    out["_p"] = p
    return out[out["_p"] >= cfg.meta_threshold]

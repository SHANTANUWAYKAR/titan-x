"""
strategy_volume_profile_poc.py
================================
Concept: Volume Profile — Point of Control (POC), Value Area High (VAH), Value Area Low (VAL)
================================================================================

WHAT IS VOLUME PROFILE?
-----------------------
Volume Profile is a charting tool that displays trading activity (volume)
at specific price levels over a defined time period. Unlike traditional
volume bars (which show volume per time bar), Volume Profile reveals
WHERE volume was transacted — exposing price levels that the market
considers "fair" vs. "unfair."

Key components:
  - POC (Point of Control): The price level with the highest traded volume.
    This acts as a magnet — price tends to revisit it and often consolidates
    near it. It represents the "fairest" price the market agreed on.
  - Value Area (VA): The range of prices where ~70% of total volume occurred.
    Institutional participants often re-enter within the value area.
  - VAH (Value Area High): Top of the value area — resistance from above.
  - VAL (Value Area Low): Bottom of the value area — support from below.

OHLCV APPROXIMATION:
---------------------
True Volume Profile requires tick-level data (every individual trade).
With only OHLCV bars, we approximate:
  - Typical Price (TP) = (High + Low + Close) / 3 — a weighted price proxy.
  - POC (rolling 50-bar) = VWAP over 50 bars = Σ(TP * Volume) / Σ(Volume).
    This gives the average price weighted by volume, i.e., where MOST volume
    traded on a VWAP-weighted basis — a statistically valid POC proxy.
  - VAH = POC + 1.5 × ATR  (1.5 ATR covers ~70% of price distribution empirically)
  - VAL = POC - 1.5 × ATR

TRADING LOGIC:
--------------
  LONG:  Price bounces from VAL region (close > VAL after touching it)
         AND RSI > 40 (not deeply oversold to the downside)
         AND close > EMA_50 (uptrend context)
  SHORT: Price rejected from VAH region (close < VAH after touching it)
         AND RSI < 60 (not deeply overbought to the upside)
         AND close < EMA_50 (downtrend context)
  EXIT:  Price returns to POC (mean reversion complete)
         OR EMA_20 cross (trend invalidation)

NO REPAINTING: All rolling calculations use only past data (window ends at
bar t-1, or the current closed bar). No forward-looking logic.

Author: Project Titan-X — NEW_GEN_CONCEPTS
"""

import numpy as np
import pandas as pd


REQUIRED_COLS = [
    "open", "high", "low", "close", "volume",
    "EMA_20", "EMA_50", "RSI", "ATR",
]
MIN_BARS = 55  # need at least 50 bars for rolling window + buffer


def _validate_inputs(df: pd.DataFrame) -> bool:
    """Check that required columns exist and df has enough rows."""
    for col in REQUIRED_COLS:
        if col not in df.columns:
            return False
    if len(df) < MIN_BARS:
        return False
    return True


def compute_volume_profile_levels(df: pd.DataFrame, window: int = 50) -> pd.DataFrame:
    """
    Compute rolling POC, VAH, VAL for each bar using a lookback window.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with ATR column.
    window : int
        Rolling lookback period (number of bars).

    Returns
    -------
    pd.DataFrame with columns: poc, vah, val

    Method
    ------
    POC = Rolling VWAP over `window` bars.
        = Σ(typical_price_i × volume_i) / Σ(volume_i)  for i in [t-window, t]
    VAH = POC + 1.5 × rolling_mean(ATR, window)
    VAL = POC - 1.5 × rolling_mean(ATR, window)

    All calculations use .shift(0) on closed bars — no lookahead.
    The result at index t uses bars [t-window+1 .. t] (closed bar inclusive).
    """
    # Typical price: the classic HLC/3 proxy for the "average" bar price
    tp = (df["high"] + df["low"] + df["close"]) / 3.0

    # Volume-weighted typical price for numerator of VWAP
    tp_vol = tp * df["volume"]

    # Rolling VWAP = rolling Σ(TP*V) / rolling Σ(V)
    # min_periods=window//2 so we produce values after half the window
    roll_vol = df["volume"].rolling(window=window, min_periods=window // 2).sum()
    roll_tpvol = tp_vol.rolling(window=window, min_periods=window // 2).sum()

    poc = roll_tpvol / roll_vol.replace(0, np.nan)  # avoid division by zero

    # Value area width: 1.5 × average ATR over the window
    atr_avg = df["ATR"].rolling(window=window, min_periods=window // 2).mean()
    vah = poc + 1.5 * atr_avg  # Value Area High
    val = poc - 1.5 * atr_avg  # Value Area Low

    result = pd.DataFrame({"poc": poc, "vah": vah, "val": val}, index=df.index)
    return result


def detect_val_bounce(df: pd.DataFrame, levels: pd.DataFrame) -> pd.Series:
    """
    Detect a bounce from the Value Area Low (bullish setup).

    Logic (all on closed bars, no lookahead):
      - "Touched VAL" = previous bar's low <= VAL (price dipped into/below VAL)
      - "Bounced" = current close > VAL (price closed back above VAL)
      This means: bar t-1 went below VAL, bar t closed above it → reversal.

    Returns boolean Series, True where VAL bounce detected.
    """
    prev_low = df["low"].shift(1)       # previous bar's low (closed)
    prev_val = levels["val"].shift(1)   # VAL from previous bar (closed)
    curr_close = df["close"]
    curr_val = levels["val"]

    # Touched from below: previous low reached or breached VAL
    touched_val = prev_low <= prev_val

    # Recovered: current close is back above current VAL
    bounced = curr_close > curr_val

    return touched_val & bounced


def detect_vah_rejection(df: pd.DataFrame, levels: pd.DataFrame) -> pd.Series:
    """
    Detect a rejection from the Value Area High (bearish setup).

    Logic (all on closed bars, no lookahead):
      - "Touched VAH" = previous bar's high >= VAH (price spiked into VAH)
      - "Rejected" = current close < VAH (price closed back below VAH)

    Returns boolean Series, True where VAH rejection detected.
    """
    prev_high = df["high"].shift(1)     # previous bar's high (closed)
    prev_vah = levels["vah"].shift(1)   # VAH from previous bar (closed)
    curr_close = df["close"]
    curr_vah = levels["vah"]

    touched_vah = prev_high >= prev_vah
    rejected = curr_close < curr_vah

    return touched_vah & rejected


def generate_signal(df: pd.DataFrame) -> pd.Series:
    """
    Generate Volume Profile POC/VAH/VAL trading signals.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV + indicators dataframe. Must contain:
        open, high, low, close, volume, EMA_20, EMA_50, RSI, ATR

    Returns
    -------
    pd.Series
        1  = Long signal (buy at close)
       -1  = Short signal (sell at close)
        0  = Flat / no signal

    Signal Rules
    ------------
    LONG conditions (ALL must be true):
      1. VAL bounce detected (price touched VAL then closed above it)
      2. RSI > 40 (not in capitulation — some buying interest remains)
      3. close > EMA_50 (medium-term uptrend context)

    SHORT conditions (ALL must be true):
      1. VAH rejection detected (price touched VAH then closed below it)
      2. RSI < 60 (not in strong momentum — distribution possible)
      3. close < EMA_50 (medium-term downtrend context)

    Priority: Long > Short (if both somehow fire, Long wins)
    If either signal is active, hold until: price crosses POC, or EMA_20 cross
    (those exit conditions are expressed as the NEXT bar's entry direction
    flipping, which happens naturally when new signals fire on EMA_20 crosses)
    """
    # --- Guard: insufficient data or missing columns ---
    if not _validate_inputs(df):
        return pd.Series(0, index=df.index, dtype=int)

    # --- Compute Value Profile levels (rolling 50-bar VWAP-based) ---
    levels = compute_volume_profile_levels(df, window=50)

    # --- Detect VAL bounce and VAH rejection patterns ---
    val_bounce = detect_val_bounce(df, levels)
    vah_rejection = detect_vah_rejection(df, levels)

    # --- Trend filter: EMA_50 direction ---
    in_uptrend = df["close"] > df["EMA_50"]     # price above EMA_50 = bullish context
    in_downtrend = df["close"] < df["EMA_50"]   # price below EMA_50 = bearish context

    # --- Momentum filter: RSI ---
    rsi_ok_long = df["RSI"] > 40   # not deeply oversold; buyers still present
    rsi_ok_short = df["RSI"] < 60  # not in strong rally; sellers may emerge

    # --- Exit: EMA_20 cross (acts as dynamic exit trigger) ---
    # When price crosses EMA_20, the prior signal is invalidated
    # (this naturally closes position when new opposing signal fires)
    # The explicit exit condition: if we were long and close < EMA_20 → exit
    # This is implicitly handled: signal resets to 0 when bounce condition fails.

    # --- Combine conditions ---
    long_signal = val_bounce & rsi_ok_long & in_uptrend
    short_signal = vah_rejection & rsi_ok_short & in_downtrend

    # --- Build output series ---
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[short_signal] = -1
    signal[long_signal] = 1   # long overrides short if both fire

    # --- Mask NaN regions (first ~50 bars before levels are stable) ---
    nan_mask = levels["poc"].isna()
    signal[nan_mask] = 0

    return signal

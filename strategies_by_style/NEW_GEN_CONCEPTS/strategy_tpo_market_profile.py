"""
strategy_tpo_market_profile.py
================================
Concept: TPO (Time Price Opportunity) / Market Profile
========================================================

WHAT IS MARKET PROFILE / TPO?
-------------------------------
Developed by J. Peter Steidlmayer at the CBOT in the 1980s, Market Profile
organizes price and time data into a statistical distribution that reveals
the market's "shape" — where it accepted vs. rejected prices.

TPO = Time Price Opportunity: a letter/block stamped for each 30-minute period
a market trades at a given price level. Stack TPOs and you get a bell curve:
the tallest column = Point of Control (POC). The middle 70% of TPOs = Value Area.

Key concepts:
  POC (Point of Control): Highest-volume / most-visited price level.
                          Acts as a gravitational magnet.
  Value Area (VA):        Range containing ~70% of all TPOs.
                          Inside VA = fair price. Outside VA = opportunity/rejection.
  IB (Initial Balance):   The price range of the first hour (first 2 bars on 30m chart).
                          The IB anchors the day's structure. Breakouts above/below IB
                          are significant.
  Single Prints:          Price levels with only ONE TPO — the market rushed through
                          quickly. Represents low-volume nodes. Price often revisits them.
  Value Area Extension:   If price breaks above VAH and stays → value area extends up.

OHLCV APPROXIMATION:
---------------------
True TPO needs a timestamp to assign letters per 30-min period. With only
OHLCV bars:
  - Control Price (POC proxy) = rolling 30-bar mode of round(close, 1).
    The most frequently occurring price level in the last 30 bars.
  - IB High = rolling max of high over first 2 bars of window.
    IB Low  = rolling min of low  over first 2 bars of window.
    Approximated as: max/min of [bar t-29, bar t-28] (the oldest 2 bars in window).
  - Single prints approximated as: price levels visited by exactly ONE bar
    in the 30-bar window (where close ≈ that level to 0.1%).

TRADING MODES:
--------------
  ADX > 25 → Trending / Breakout mode:
    - Price breaks above IB high → LONG (market extension up)
    - Price breaks below IB low  → SHORT (market extension down)

  ADX < 20 → Range / Mean Reversion mode:
    - Price far above control price → SHORT (mean reversion to POC)
    - Price far below control price → LONG (mean reversion to POC)
    - "Far" defined as > 1.5 × ATR from control price

  Single print: if price touches a single-print level, expect fast move through it.

NO REPAINTING: IB is computed from the oldest bars in the rolling window
(lookback only, no current-bar lookahead).

Author: Project Titan-X — NEW_GEN_CONCEPTS
"""

import numpy as np
import pandas as pd


REQUIRED_COLS = [
    "open", "high", "low", "close", "volume",
    "ATR", "ADX",
]
MIN_BARS = 35


def _validate_inputs(df: pd.DataFrame) -> bool:
    """Return True if df has required columns and sufficient rows."""
    for col in REQUIRED_COLS:
        if col not in df.columns:
            return False
    if len(df) < MIN_BARS:
        return False
    return True


def compute_control_price(df: pd.DataFrame, window: int = 30) -> pd.Series:
    """
    Approximate the Market Profile POC as the rolling modal close price.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    window : int
        Rolling lookback period.

    Returns
    -------
    pd.Series
        Control price (POC proxy) at each bar.

    Method
    ------
    For each bar t, take the last `window` close prices rounded to 1 decimal
    place. The mode (most common value) is the "control price" — the price
    level the market has spent the most time at.

    This is the closest OHLCV analog to TPO's highest-column price.
    Uses a rolling apply with no forward data.
    """
    rounded_close = df["close"].round(1)

    def _mode(x):
        """Return modal value of array, or NaN if insufficient data."""
        if len(x) < 2:
            return np.nan
        vals, counts = np.unique(x, return_counts=True)
        return vals[np.argmax(counts)]

    control_price = rounded_close.rolling(window=window, min_periods=window // 2).apply(
        _mode, raw=True
    )
    return control_price


def compute_initial_balance(df: pd.DataFrame, window: int = 30) -> tuple:
    """
    Approximate the Initial Balance (IB) using the oldest 2 bars of each window.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    window : int
        Rolling lookback window.

    Returns
    -------
    tuple of pd.Series: (ib_high, ib_low)

    Method
    ------
    In a rolling 30-bar window ending at bar t:
      - The "first 2 bars" of the session = bars at positions t-29 and t-28.
      - IB High = max(high[t-29], high[t-28])
      - IB Low  = min(low[t-29],  low[t-28])

    Approximated via shift(window-1) and shift(window-2) — pure lookback.
    No timestamp-based day detection needed.
    """
    # IB uses the high/low of bars that are `window-1` and `window-2` bars ago
    # These are the "first 2" bars of the rolling session window
    high_a = df["high"].shift(window - 1)    # oldest bar in window
    high_b = df["high"].shift(window - 2)    # second oldest bar in window
    low_a  = df["low"].shift(window - 1)
    low_b  = df["low"].shift(window - 2)

    ib_high = pd.concat([high_a, high_b], axis=1).max(axis=1)
    ib_low  = pd.concat([low_a,  low_b ], axis=1).min(axis=1)

    return ib_high, ib_low


def detect_single_prints(df: pd.DataFrame, window: int = 30,
                          tolerance_pct: float = 0.001) -> pd.Series:
    """
    Detect "single print" price levels — visited by only one bar in window.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    window : int
        Rolling lookback window.
    tolerance_pct : float
        % tolerance for matching two prices as the "same level."

    Returns
    -------
    pd.Series (bool)
        True if the current bar's close is near a single-print level.
        (Price moved to a fast-transit zone → expect continuation or fast reversal)

    Method
    ------
    For each close price in the window, count how many OTHER closes are within
    tolerance_pct. If only 1 bar visits a level → single print.
    Current bar's close is a single print if its level count == 1.
    """
    def _is_single_print(window_vals):
        """Check if last value in window is a single print."""
        if len(window_vals) < 3:
            return 0.0
        last_price = window_vals[-1]
        # Count bars that visited this price level (within tolerance)
        count = np.sum(np.abs(window_vals - last_price) / (last_price + 1e-9) <= tolerance_pct)
        return 1.0 if count == 1 else 0.0

    result = df["close"].rolling(window=window, min_periods=window // 2).apply(
        _is_single_print, raw=True
    )
    return result.fillna(0).astype(bool)


def generate_signal(df: pd.DataFrame) -> pd.Series:
    """
    Generate TPO / Market Profile trading signals.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV + indicators dataframe. Must contain:
        open, high, low, close, volume, ATR, ADX

    Returns
    -------
    pd.Series
        1  = Long signal
       -1  = Short signal
        0  = Flat / no signal

    Signal Rules (Mode-Dependent)
    ------------------------------
    TRENDING MODE (ADX > 25):
      LONG:  close breaks above IB_high AND ATR has expanded (ATR > ATR_avg)
             → Market extending above Initial Balance = continuation up
      SHORT: close breaks below IB_low AND ATR has expanded
             → Market extending below Initial Balance = continuation down

    MEAN REVERSION MODE (ADX < 20):
      LONG:  close is more than 1.5 × ATR BELOW control price (far from POC)
             → Mean reversion back toward POC
      SHORT: close is more than 1.5 × ATR ABOVE control price
             → Mean reversion back toward POC

    TRANSITION ZONE (20 ≤ ADX ≤ 25): No signal (ambiguous regime).

    Single print overlay:
      If close touches a single-print level → bias increases for continuation
      (single prints are low-volume nodes; price typically races through them).
    """
    # --- Guard ---
    if not _validate_inputs(df):
        return pd.Series(0, index=df.index, dtype=int)

    window = 30

    # --- Compute Market Profile components ---
    control_price = compute_control_price(df, window=window)
    ib_high, ib_low = compute_initial_balance(df, window=window)
    single_print = detect_single_prints(df, window=window)

    # --- ATR expansion: current ATR vs. rolling average ---
    atr_avg = df["ATR"].rolling(window=20, min_periods=10).mean()
    atr_expanded = df["ATR"] > atr_avg  # expanding volatility = momentum

    # --- Regime detection via ADX ---
    trending = df["ADX"] > 25   # trend mode: breakouts favored
    ranging  = df["ADX"] < 20   # range mode: mean reversion favored

    # --- Distance from control price (in ATR units) ---
    dist_from_poc = df["close"] - control_price
    dist_atr_units = dist_from_poc / df["ATR"].replace(0, np.nan)

    # --- TREND MODE signals ---
    # Breakout above Initial Balance → long
    trend_long  = trending & (df["close"] > ib_high) & atr_expanded
    # Breakdown below Initial Balance → short
    trend_short = trending & (df["close"] < ib_low)  & atr_expanded

    # --- MEAN REVERSION MODE signals ---
    # Price too far below POC → buy, expect return to POC
    mr_long  = ranging & (dist_atr_units < -1.5)
    # Price too far above POC → sell, expect return to POC
    mr_short = ranging & (dist_atr_units >  1.5)

    # --- Single print overlay: strengthens breakout signals ---
    # If price is at a single print level during a breakout, momentum likely continues
    trend_long  = trend_long  | (trending & single_print & (df["close"] > control_price))
    trend_short = trend_short | (trending & single_print & (df["close"] < control_price))

    long_signal  = trend_long  | mr_long
    short_signal = trend_short | mr_short

    # --- Build output ---
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[short_signal] = -1
    signal[long_signal] = 1   # long overrides short on conflict

    # --- Mask warmup ---
    nan_mask = control_price.isna() | ib_high.isna()
    signal[nan_mask] = 0

    return signal

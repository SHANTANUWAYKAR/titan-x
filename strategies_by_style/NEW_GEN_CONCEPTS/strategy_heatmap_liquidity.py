"""
strategy_heatmap_liquidity.py
==============================
Concept: Liquidity Heatmap — Where Stop Orders Cluster
=======================================================

WHAT IS A LIQUIDITY HEATMAP?
------------------------------
In modern markets, institutional participants (smart money) use heat maps to
visualize WHERE the largest clusters of stop-loss orders and limit orders sit.
These liquidity pools act as magnets: large players NEED liquidity to fill
their own large orders, so they engineer price moves TO those pools.

Key liquidity pool types:
  1. EQUAL HIGHS / EQUAL LOWS: Two or more prior swing highs/lows at the same
     level signal a cluster of buy-stops (above equal highs) or sell-stops
     (below equal lows). These are the most reliable liquidity targets.

  2. ROUND NUMBERS: Prices like 100.00, 150.00, 5000 attract orders naturally
     (psychological magnets). Large pools of stops accumulate just above/below
     round numbers.

  3. SWING HIGHS / LOWS: The structural high/low from recent sessions contain
     stops from traders who bought the high or shorted the low.

LIQUIDITY SWEEP (Stop Hunt):
-----------------------------
When price spikes ABOVE equal highs then CLOSES BELOW them:
  → Stops above equal highs were triggered (buy stops = additional demand for sellers)
  → Sellers got filled at premium prices from the triggered stops
  → This is bearish — smart money sold into the sweep
  → Called "sweep and reverse" or "stop hunt"

When price spikes BELOW equal lows then CLOSES ABOVE them:
  → Stops below equal lows were triggered (sell stops = additional supply for buyers)
  → Buyers got filled at discount prices from the triggered stops
  → This is bullish — smart money bought into the sweep
  → Also called "liquidity grab" or "false break"

ROUND NUMBER MAGNETISM:
------------------------
Price tends to move toward the nearest major round number (as a target).
This is used for exit/target calculation rather than entry.

OHLCV APPROXIMATION:
---------------------
  - Equal highs: last 2 pivot highs within 0.1% of each other.
  - Equal lows: last 2 pivot lows within 0.1% of each other.
  - Pivot high: local high that is >= all highs in ±N bars.
  - Liquidity sweep: current bar high > equal_high level AND close < equal_high.
  - Round numbers: price rounded to nearest 50 or 100 units.

NO REPAINTING: All pivot and equal level detection uses shift(1) to reference
prior bars only. The current bar's close is compared to prior structure.

Author: Project Titan-X — NEW_GEN_CONCEPTS
"""

import numpy as np
import pandas as pd


REQUIRED_COLS = [
    "open", "high", "low", "close", "volume",
    "EMA_20", "RSI",
]
MIN_BARS = 25


def _validate_inputs(df: pd.DataFrame) -> bool:
    """Return True if df has required columns and sufficient rows."""
    for col in REQUIRED_COLS:
        if col not in df.columns:
            return False
    if len(df) < MIN_BARS:
        return False
    return True


def detect_pivot_highs(df: pd.DataFrame, left: int = 5, right: int = 5) -> pd.Series:
    """
    Detect pivot (swing) highs using a left/right lookback.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    left : int
        Bars to the left that must be lower.
    right : int
        Bars to the right that must be lower.

    Returns
    -------
    pd.Series (bool)
        True at confirmed pivot high bars.

    Note: Uses shift() to ensure no lookahead at current bar t.
    Pivot at bar t confirmed when `right` bars later have lower highs.
    The pivot is attributed to bar t-right (which is safe to use at current bar).
    We detect pivot `right` bars ago so we always have the full right-side view.
    """
    highs = df["high"]
    # Rolling max to the LEFT of bar t-right (bars t-right-left to t-right-1)
    roll_left_max = highs.shift(right + 1).rolling(window=left, min_periods=left).max()
    # Rolling max to the RIGHT of bar t-right (bars t-right+1 to t)
    roll_right_max = highs.shift(1).rolling(window=right, min_periods=right).max()
    # The pivot bar's high (bar at t-right)
    pivot_high = highs.shift(right)

    is_pivot = (pivot_high > roll_left_max) & (pivot_high > roll_right_max)
    return is_pivot.fillna(False)


def detect_pivot_lows(df: pd.DataFrame, left: int = 5, right: int = 5) -> pd.Series:
    """
    Detect pivot (swing) lows using a left/right lookback.

    Returns boolean Series, True at confirmed pivot low bars.
    See detect_pivot_highs for the no-lookahead method.
    """
    lows = df["low"]
    roll_left_min = lows.shift(right + 1).rolling(window=left, min_periods=left).min()
    roll_right_min = lows.shift(1).rolling(window=right, min_periods=right).min()
    pivot_low = lows.shift(right)

    is_pivot = (pivot_low < roll_left_min) & (pivot_low < roll_right_min)
    return is_pivot.fillna(False)


def find_last_two_pivot_levels(pivots: pd.Series, prices: pd.Series,
                                lookback: int = 20) -> tuple:
    """
    Find the most recent two confirmed pivot price levels within lookback bars.

    Parameters
    ----------
    pivots : pd.Series (bool)
        Boolean mask of confirmed pivot bars.
    prices : pd.Series
        Price levels at those pivot bars (high or low).
    lookback : int
        How many bars back to search.

    Returns
    -------
    tuple: (level_1, level_2) — two pd.Series of recent pivot prices.
           NaN when fewer than 2 pivots exist in the window.
    """
    # For each bar t, find last 2 pivot prices in [t-lookback, t-1]
    def _last_two(idx):
        """Extract last 2 pivot levels up to this index."""
        start = max(0, idx - lookback)
        window_pivots = pivots.iloc[start:idx]
        window_prices = prices.iloc[start:idx]
        pivot_prices = window_prices[window_pivots].values
        if len(pivot_prices) >= 2:
            return pivot_prices[-1], pivot_prices[-2]  # last, second-last
        elif len(pivot_prices) == 1:
            return pivot_prices[-1], np.nan
        return np.nan, np.nan

    n = len(pivots)
    level_1 = np.full(n, np.nan)
    level_2 = np.full(n, np.nan)

    for i in range(lookback, n):
        l1, l2 = _last_two(i)
        level_1[i] = l1
        level_2[i] = l2

    return pd.Series(level_1, index=pivots.index), pd.Series(level_2, index=pivots.index)


def detect_equal_highs(df: pd.DataFrame, pivot_highs: pd.Series,
                        tolerance_pct: float = 0.001,
                        lookback: int = 20) -> tuple:
    """
    Detect equal highs — two recent pivot highs at nearly the same level.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    pivot_highs : pd.Series (bool)
        Confirmed pivot high locations.
    tolerance_pct : float
        Max price difference (%) to consider two highs "equal."
    lookback : int
        Bar lookback for recent pivot search.

    Returns
    -------
    tuple: (equal_high_exists, equal_high_level)
        equal_high_exists : pd.Series (bool) — True if equal high pattern exists
        equal_high_level  : pd.Series (float) — the average level of the equal highs
    """
    lvl1, lvl2 = find_last_two_pivot_levels(pivot_highs, df["high"], lookback)

    # Equal highs: both levels exist and are within tolerance
    both_exist = ~lvl1.isna() & ~lvl2.isna()
    pct_diff = (lvl1 - lvl2).abs() / (lvl2.replace(0, np.nan))
    equal = both_exist & (pct_diff <= tolerance_pct)

    avg_level = (lvl1 + lvl2) / 2.0

    return equal, avg_level


def detect_equal_lows(df: pd.DataFrame, pivot_lows: pd.Series,
                       tolerance_pct: float = 0.001,
                       lookback: int = 20) -> tuple:
    """
    Detect equal lows — two recent pivot lows at nearly the same level.

    Returns
    -------
    tuple: (equal_low_exists, equal_low_level)
    """
    lvl1, lvl2 = find_last_two_pivot_levels(pivot_lows, df["low"], lookback)

    both_exist = ~lvl1.isna() & ~lvl2.isna()
    pct_diff = (lvl1 - lvl2).abs() / (lvl2.abs().replace(0, np.nan))
    equal = both_exist & (pct_diff <= tolerance_pct)

    avg_level = (lvl1 + lvl2) / 2.0

    return equal, avg_level


def detect_liquidity_sweep_up(df: pd.DataFrame, equal_high_level: pd.Series) -> pd.Series:
    """
    Detect bullish liquidity sweep of equal highs (stop hunt up → bearish reversal).

    Logic (all on closed bar, no lookahead):
      - High of current bar spiked above equal high level (stops triggered)
      - Close of current bar is BELOW the equal high level (rejected close)
      → Price swept the stops above equal highs, then reversed → BEARISH

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    equal_high_level : pd.Series
        Rolling equal high price level.

    Returns
    -------
    pd.Series (bool)
        True where a sweep of equal highs (bearish outcome) occurred.
    """
    swept = df["high"] > equal_high_level          # high spiked above
    rejected = df["close"] < equal_high_level       # closed back below
    return swept & rejected


def detect_liquidity_sweep_down(df: pd.DataFrame, equal_low_level: pd.Series) -> pd.Series:
    """
    Detect bearish liquidity sweep of equal lows (stop hunt down → bullish reversal).

    Logic (all on closed bar, no lookahead):
      - Low of current bar spiked below equal low level (stops triggered)
      - Close of current bar is ABOVE the equal low level (recovered close)
      → Price swept the stops below equal lows, then reversed → BULLISH

    Returns
    -------
    pd.Series (bool)
        True where a sweep of equal lows (bullish outcome) occurred.
    """
    swept = df["low"] < equal_low_level            # low spiked below
    recovered = df["close"] > equal_low_level       # closed back above
    return swept & recovered


def nearest_round_number(price: pd.Series, round_to: float = 50.0) -> pd.Series:
    """
    Compute nearest round number for price magnetism analysis.

    Parameters
    ----------
    price : pd.Series
        Price series.
    round_to : float
        Round number unit (e.g., 50 for levels at 50, 100, 150...).

    Returns
    -------
    pd.Series
        Nearest round number for each price (target level).
    """
    return (price / round_to).round() * round_to


def generate_signal(df: pd.DataFrame) -> pd.Series:
    """
    Generate Liquidity Heatmap / Stop Hunt trading signals.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV + indicators dataframe. Must contain:
        open, high, low, close, volume, EMA_20, RSI

    Returns
    -------
    pd.Series
        1  = Long signal (bullish sweep — buy the stop hunt)
       -1  = Short signal (bearish sweep — sell the stop hunt)
        0  = Flat / no signal

    Signal Rules
    ------------
    LONG (Bullish liquidity sweep of equal lows):
      1. Equal lows detected in recent history (liquidity pool below)
      2. Current bar spiked below equal low but closed ABOVE it
         (sellers triggered stops but buyers absorbed everything)
      3. RSI recovering: RSI > RSI(1 bar ago) (momentum turning up)
      4. close > EMA_20 (short-term structure intact or reclaimed)

    SHORT (Bearish liquidity sweep of equal highs):
      1. Equal highs detected in recent history (liquidity pool above)
      2. Current bar spiked above equal high but closed BELOW it
         (buyers triggered stops but sellers absorbed everything)
      3. RSI fading: RSI < RSI(1 bar ago) (momentum turning down)
      4. close < EMA_20 (short-term structure lost)
    """
    # --- Guard ---
    if not _validate_inputs(df):
        return pd.Series(0, index=df.index, dtype=int)

    # --- Detect pivots (right=5 means pivot confirmed 5 bars later — no lookahead) ---
    pivot_highs = detect_pivot_highs(df, left=5, right=5)
    pivot_lows  = detect_pivot_lows(df,  left=5, right=5)

    # --- Detect equal highs and lows ---
    eq_high_exists, eq_high_level = detect_equal_highs(df, pivot_highs, tolerance_pct=0.001)
    eq_low_exists,  eq_low_level  = detect_equal_lows(df,  pivot_lows,  tolerance_pct=0.001)

    # --- Detect liquidity sweeps ---
    sweep_up   = detect_liquidity_sweep_up(df, eq_high_level)    # bearish (stop hunt up)
    sweep_down = detect_liquidity_sweep_down(df, eq_low_level)   # bullish (stop hunt down)

    # --- RSI momentum ---
    rsi_rising  = df["RSI"] > df["RSI"].shift(1)
    rsi_falling = df["RSI"] < df["RSI"].shift(1)

    # --- Price structure ---
    above_ema20 = df["close"] > df["EMA_20"]
    below_ema20 = df["close"] < df["EMA_20"]

    # --- Signal logic ---
    # LONG: sweep of equal lows (bullish) + RSI turning up + above EMA_20
    long_signal  = eq_low_exists  & sweep_down & rsi_rising  & above_ema20

    # SHORT: sweep of equal highs (bearish) + RSI turning down + below EMA_20
    short_signal = eq_high_exists & sweep_up   & rsi_falling & below_ema20

    # --- Build output ---
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[short_signal] = -1
    signal[long_signal] = 1

    # --- Round number target annotation (informational, not used for signal) ---
    # Price pulled toward nearest round number — useful as take-profit reference.
    # round_target = nearest_round_number(df["close"])
    # (Uncomment and use in backtesting framework as TP target)

    # --- Mask warmup period ---
    nan_mask = eq_high_level.isna() | eq_low_level.isna()
    signal[nan_mask] = 0

    return signal

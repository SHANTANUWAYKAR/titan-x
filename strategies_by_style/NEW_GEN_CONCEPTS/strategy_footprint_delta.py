"""
strategy_footprint_delta.py
============================
Concept: Footprint Chart — Cumulative Volume Delta (CVD)
=========================================================

WHAT IS A FOOTPRINT CHART?
---------------------------
A Footprint chart is an enhanced candlestick that shows the volume at
each price level AND the split between buy-initiated vs. sell-initiated
volume within each bar. It reveals the "microstructure" of each bar:
  - How aggressively buyers vs. sellers were transacting
  - Where absorption happened (lots of selling but price didn't fall)
  - Delta: the NET order flow pressure = Buy Volume - Sell Volume

CUMULATIVE VOLUME DELTA (CVD):
-------------------------------
Delta per bar = Buy Volume - Sell Volume
CVD = running cumulative sum of delta over a window.
Positive CVD = buyers have been more aggressive over the window.
Negative CVD = sellers have been more aggressive.

OHLCV APPROXIMATION:
---------------------
True footprint needs level-2 order flow data. With OHLCV we approximate:
  - Buy Volume  ≈ Volume × (Close - Low)  / (High - Low + ε)
    (price closing near the high implies buyers dominated)
  - Sell Volume ≈ Volume × (High - Close) / (High - Low + ε)
    (price closing near the low implies sellers dominated)
  - Delta = Buy_Vol - Sell_Vol
  - This is known as the "close location" volume split — a well-established
    approximation used in market microstructure research.

CVD DIVERGENCE (the key signal):
---------------------------------
Bullish Divergence:
  Price makes a LOWER LOW but CVD makes a HIGHER LOW.
  → Sellers are pushing price down but with LESS volume conviction.
  → Hidden buying pressure accumulating. Bullish reversal likely.

Bearish Divergence:
  Price makes a HIGHER HIGH but CVD makes a LOWER HIGH.
  → Buyers are pushing price up but with LESS volume conviction.
  → Hidden selling pressure accumulating. Bearish reversal likely.

DELTA EXHAUSTION:
-----------------
3 consecutive bars with delta strongly in one direction, but price
barely moving → the aggressive side is being absorbed. Reversal signal.

NO REPAINTING: All divergence lookbacks use shift(1) to reference the
previous bar's completed values only.

Author: Project Titan-X — NEW_GEN_CONCEPTS
"""

import numpy as np
import pandas as pd


REQUIRED_COLS = [
    "open", "high", "low", "close", "volume",
    "EMA_20", "RSI",
]
MIN_BARS = 30  # need at least 20-bar CVD window + buffer


def _validate_inputs(df: pd.DataFrame) -> bool:
    """Return True if df has required columns and sufficient rows."""
    for col in REQUIRED_COLS:
        if col not in df.columns:
            return False
    if len(df) < MIN_BARS:
        return False
    return True


def compute_cvd(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """
    Compute rolling Cumulative Volume Delta (CVD) over `window` bars.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    window : int
        Rolling window for CVD accumulation.

    Returns
    -------
    pd.Series
        CVD values (positive = net buying pressure, negative = net selling).

    Method
    ------
    1. Approximate buy/sell volume split using close location within the bar.
    2. Delta per bar = buy_vol - sell_vol.
    3. CVD = rolling sum of delta over `window` bars.

    The rolling window (vs. cumulative from inception) prevents old market
    structure from dominating and keeps the signal responsive to recent flow.
    """
    hl_range = df["high"] - df["low"]

    # Buy volume proxy: fraction of bar closed toward the high
    buy_vol = df["volume"] * (df["close"] - df["low"]) / (hl_range + 1e-9)

    # Sell volume proxy: fraction of bar closed toward the low
    sell_vol = df["volume"] * (df["high"] - df["close"]) / (hl_range + 1e-9)

    # Delta: positive = more buying aggression, negative = more selling
    delta = buy_vol - sell_vol

    # Rolling CVD: cumulative net order flow over recent window
    cvd = delta.rolling(window=window, min_periods=window // 2).sum()

    return cvd


def detect_bullish_cvd_divergence(df: pd.DataFrame, cvd: pd.Series,
                                   lookback: int = 5) -> pd.Series:
    """
    Detect bullish CVD divergence: price lower low, CVD higher low.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    cvd : pd.Series
        CVD series.
    lookback : int
        Number of bars to look back for the prior swing low.

    Returns
    -------
    pd.Series (bool)
        True at bars where bullish CVD divergence is present.

    Logic (no lookahead — all comparisons use .shift()):
    -------------------------------------------------------
    At bar t (current closed bar):
      - current_low = df['low'].iloc[t]   (current bar's low)
      - prior_low   = min(df['low'], lookback bars ending at t-1)
      - current_cvd = cvd.iloc[t]
      - prior_cvd   = min(cvd, lookback bars ending at t-1)

    Bullish divergence if:
      current_low < prior_low   (price made a lower low)
      AND current_cvd > prior_cvd  (but CVD made a higher low = less selling)
    """
    # Rolling minimum over lookback bars ENDING at t-1 (shift(1) prevents lookahead)
    prior_low_min = df["low"].shift(1).rolling(window=lookback, min_periods=2).min()
    prior_cvd_min = cvd.shift(1).rolling(window=lookback, min_periods=2).min()

    current_low = df["low"]
    current_cvd = cvd

    # Price made a lower low = bearish price action
    price_lower_low = current_low < prior_low_min

    # CVD made a higher low = hidden buying absorbed the selling pressure
    cvd_higher_low = current_cvd > prior_cvd_min

    return price_lower_low & cvd_higher_low


def detect_bearish_cvd_divergence(df: pd.DataFrame, cvd: pd.Series,
                                   lookback: int = 5) -> pd.Series:
    """
    Detect bearish CVD divergence: price higher high, CVD lower high.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    cvd : pd.Series
        CVD series.
    lookback : int
        Number of bars to look back for the prior swing high.

    Returns
    -------
    pd.Series (bool)
        True at bars where bearish CVD divergence is present.

    Logic (no lookahead — all comparisons use .shift()):
    -------------------------------------------------------
    At bar t:
      - current_high = df['high'].iloc[t]
      - prior_high   = max(df['high'], lookback bars ending at t-1)
      - Bearish divergence if: current_high > prior_high (higher high)
        AND current_cvd < prior_cvd (CVD lower high = less buying fuel)
    """
    prior_high_max = df["high"].shift(1).rolling(window=lookback, min_periods=2).max()
    prior_cvd_max = cvd.shift(1).rolling(window=lookback, min_periods=2).max()

    current_high = df["high"]
    current_cvd = cvd

    price_higher_high = current_high > prior_high_max
    cvd_lower_high = current_cvd < prior_cvd_max

    return price_higher_high & cvd_lower_high


def detect_delta_exhaustion(df: pd.DataFrame, cvd: pd.Series,
                             consec: int = 3,
                             price_threshold_pct: float = 0.003) -> tuple:
    """
    Detect delta exhaustion: aggressive one-sided delta but price not moving.

    When 3 consecutive bars show strong delta in one direction (buying or
    selling) but price barely moves, the aggressive side is being absorbed
    by the other side. This is a reversal warning.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    cvd : pd.Series
        CVD series.
    consec : int
        Number of consecutive bars of one-sided delta to require.
    price_threshold_pct : float
        Max price movement (as % of close) that qualifies as "not moving."

    Returns
    -------
    tuple of two pd.Series (bool):
        (bull_exhaustion, bear_exhaustion)
        bull_exhaustion: positive delta 3+ bars but price flat → sellers absorbing → bearish
        bear_exhaustion: negative delta 3+ bars but price flat → buyers absorbing → bullish
    """
    # Per-bar delta (not rolling sum)
    hl_range = df["high"] - df["low"]
    buy_vol = df["volume"] * (df["close"] - df["low"]) / (hl_range + 1e-9)
    sell_vol = df["volume"] * (df["high"] - df["close"]) / (hl_range + 1e-9)
    delta = buy_vol - sell_vol

    # Check last `consec` bars all had positive delta (buying pressure)
    # Use rolling min: if min of last N deltas > 0, all were positive
    rolling_min_delta = delta.rolling(window=consec, min_periods=consec).min()
    rolling_max_delta = delta.rolling(window=consec, min_periods=consec).max()

    all_positive_delta = rolling_min_delta > 0   # all 3 bars positive
    all_negative_delta = rolling_max_delta < 0   # all 3 bars negative

    # Price movement over same window (absolute % change)
    price_start = df["close"].shift(consec)      # close N bars ago
    price_change_pct = ((df["close"] - price_start) / price_start.replace(0, np.nan)).abs()
    price_not_moving = price_change_pct < price_threshold_pct

    # Bull exhaustion: buyers dominating but price flat → bearish reversal
    bull_exhaustion = all_positive_delta & price_not_moving

    # Bear exhaustion: sellers dominating but price flat → bullish reversal
    bear_exhaustion = all_negative_delta & price_not_moving

    return bull_exhaustion, bear_exhaustion


def generate_signal(df: pd.DataFrame) -> pd.Series:
    """
    Generate Footprint Delta / CVD trading signals.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV + indicators dataframe. Must contain:
        open, high, low, close, volume, EMA_20, RSI

    Returns
    -------
    pd.Series
        1  = Long signal (buy at close)
       -1  = Short signal (sell at close)
        0  = Flat / no signal

    Signal Rules
    ------------
    LONG conditions (divergence-based):
      Primary:
        1. Bullish CVD divergence (price lower low + CVD higher low)
        2. RSI < 50 but recovering (RSI > RSI 1 bar ago)
        3. close > EMA_20 (price above short-term MA for trend confirmation)
      OR
        4. Bear delta exhaustion (sellers absorbed, reversal imminent)
        5. RSI < 45 (oversold context)
        6. close > EMA_20

    SHORT conditions (divergence-based):
      Primary:
        1. Bearish CVD divergence (price higher high + CVD lower high)
        2. RSI > 50 but fading (RSI < RSI 1 bar ago)
        3. close < EMA_20
      OR
        4. Bull delta exhaustion (buyers absorbed, reversal imminent)
        5. RSI > 55 (overbought context)
        6. close < EMA_20
    """
    # --- Guard ---
    if not _validate_inputs(df):
        return pd.Series(0, index=df.index, dtype=int)

    # --- Compute CVD ---
    cvd = compute_cvd(df, window=20)

    # --- CVD Divergence signals ---
    bull_div = detect_bullish_cvd_divergence(df, cvd, lookback=5)
    bear_div = detect_bearish_cvd_divergence(df, cvd, lookback=5)

    # --- Delta exhaustion ---
    bull_exhaust, bear_exhaust = detect_delta_exhaustion(df, cvd, consec=3)

    # --- RSI momentum filter ---
    rsi_rising = df["RSI"] > df["RSI"].shift(1)       # RSI turning up
    rsi_falling = df["RSI"] < df["RSI"].shift(1)      # RSI turning down
    rsi_below_50 = df["RSI"] < 50
    rsi_above_50 = df["RSI"] > 50
    rsi_oversold = df["RSI"] < 45
    rsi_overbought = df["RSI"] > 55

    # --- Price vs EMA_20 filter ---
    above_ema20 = df["close"] > df["EMA_20"]
    below_ema20 = df["close"] < df["EMA_20"]

    # --- Long conditions ---
    # Path A: Bullish divergence entry
    long_div = bull_div & rsi_below_50 & rsi_rising & above_ema20
    # Path B: Bear exhaustion entry (buyers absorbing sellers)
    long_exhaust = bear_exhaust & rsi_oversold & above_ema20

    # --- Short conditions ---
    # Path A: Bearish divergence entry
    short_div = bear_div & rsi_above_50 & rsi_falling & below_ema20
    # Path B: Bull exhaustion entry (sellers absorbing buyers)
    short_exhaust = bull_exhaust & rsi_overbought & below_ema20

    long_signal = long_div | long_exhaust
    short_signal = short_div | short_exhaust

    # --- Build output ---
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[short_signal] = -1
    signal[long_signal] = 1  # long overrides short on conflict

    # --- Mask warmup period ---
    nan_mask = cvd.isna()
    signal[nan_mask] = 0

    return signal

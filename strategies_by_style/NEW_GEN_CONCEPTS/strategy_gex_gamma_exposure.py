"""
strategy_gex_gamma_exposure.py
================================
Concept: GEX (Gamma Exposure) — Options Market Impact on Spot Price
====================================================================

WHAT IS GEX (GAMMA EXPOSURE)?
-------------------------------
GEX measures the total delta-hedging flow that market makers (MMs) must
execute as the underlying price moves. It is calculated from the options
market's open interest and gamma of each strike.

Formula:
  GEX = Σ (Gamma × Open_Interest × Contract_Size) per strike

Why it matters for spot price:
  POSITIVE GEX (MMs net long gamma):
    → MMs are long options, short the underlying.
    → As price rises, MMs SELL the underlying to hedge (delta decreases).
    → As price falls, MMs BUY the underlying to hedge (delta increases).
    → This creates a MEAN-REVERTING force. Price gets "pinned" near the
      high-OI strikes (especially near monthly expiry).
    → Tight Bollinger Bands signal this regime.

  NEGATIVE GEX (MMs net short gamma):
    → MMs are short options, long the underlying.
    → As price rises, MMs BUY more underlying (amplifying the move).
    → As price falls, MMs SELL more underlying (amplifying the move).
    → This creates a MOMENTUM/TRENDING force. Price moves become explosive.
    → Wide Bollinger Bands signal this regime.

EXPIRY CYCLES:
--------------
GEX flips around expiry dates. Before monthly expiry (last Friday of month):
  - GEX typically becomes more negative (hedges unwound).
  - More volatile, trending conditions.
After a monthly expiry reset:
  - New OI builds up → GEX turns positive again → pinning resumes.
  - Weekly expiries (every Friday) cause smaller, briefer GEX shifts.

OHLCV APPROXIMATION (since real GEX needs live options data):
-------------------------------------------------------------
  - NARROW Bollinger Bands (BB_upper - BB_lower < 1.5 × ATR_avg_20):
    → Assume POSITIVE GEX environment → mean reversion mode.
  - WIDE Bollinger Bands (BB_upper - BB_lower > 2.5 × ATR_avg_20):
    → Assume NEGATIVE GEX environment → momentum/breakout mode.
  - Between 1.5× and 2.5×: transitional, no clear signal.

  Expiry proxy:
    - Weekly: bar_index mod 5 in [3, 4] (last 2 bars of 5-bar cycle)
    - Monthly: bar_index mod 21 in [19, 20] (last 2 bars of 21-bar cycle)
    - Near expiry → increase mean-reversion bias.

TRADING LOGIC:
--------------
  POSITIVE GEX (narrow bands) → mean reversion:
    LONG:  close <= BB_lower → buy (revert to BB_middle)
    SHORT: close >= BB_upper → sell (revert to BB_middle)

  NEGATIVE GEX (wide bands) → momentum/breakout:
    LONG:  close breaks above BB_upper + RSI > 50 + MACD bullish
    SHORT: close breaks below BB_lower + RSI < 50 + MACD bearish

  Near expiry modifier: shifts bias toward mean reversion in any regime.

CAUTION: This is a structural approximation. Real GEX is asset-class
specific (equities have well-measured GEX; crypto less so). Use as one
signal layer, not a standalone system.

NO REPAINTING: All Bollinger Band and ATR comparisons use pre-computed
indicator columns that close on each bar. No forward references.

Author: Project Titan-X — NEW_GEN_CONCEPTS
"""

import numpy as np
import pandas as pd


REQUIRED_COLS = [
    "open", "high", "low", "close",
    "ATR", "BB_upper", "BB_lower", "BB_middle",
    "RSI", "MACD", "MACD_signal",
]
MIN_BARS = 30


def _validate_inputs(df: pd.DataFrame) -> bool:
    """Return True if df has required columns and sufficient rows."""
    for col in REQUIRED_COLS:
        if col not in df.columns:
            return False
    if len(df) < MIN_BARS:
        return False
    return True


def classify_gex_regime(df: pd.DataFrame, narrow_mult: float = 1.5,
                          wide_mult: float = 2.5,
                          atr_window: int = 20) -> pd.DataFrame:
    """
    Classify the GEX regime as positive (pinning), negative (volatile), or neutral.

    Parameters
    ----------
    df : pd.DataFrame
        Dataframe with BB_upper, BB_lower, ATR columns.
    narrow_mult : float
        ATR multiplier below which bands are "narrow" → positive GEX.
    wide_mult : float
        ATR multiplier above which bands are "wide" → negative GEX.
    atr_window : int
        Rolling window for average ATR.

    Returns
    -------
    pd.DataFrame with columns:
        bb_width    : Bollinger Band width (BB_upper - BB_lower)
        atr_avg     : Rolling average ATR
        gex_positive: bool — narrow bands → positive GEX → mean reversion
        gex_negative: bool — wide bands → negative GEX → momentum
        gex_neutral : bool — transition zone

    Method
    ------
    Bollinger Band width is a standard volatility proxy used in many
    systematic strategies (e.g., "BB squeeze" = low volatility, ready to trend).
    Mapping it to GEX regimes is an original approximation.
    """
    bb_width = df["BB_upper"] - df["BB_lower"]  # raw band width in price units

    # Normalize by ATR to make comparison timeframe-agnostic
    atr_avg = df["ATR"].rolling(window=atr_window, min_periods=atr_window // 2).mean()

    # Narrow bands: width < 1.5 × average ATR → pinning regime (positive GEX)
    gex_positive = bb_width < (narrow_mult * atr_avg)

    # Wide bands: width > 2.5 × average ATR → explosive regime (negative GEX)
    gex_negative = bb_width > (wide_mult * atr_avg)

    # Neutral: between the two thresholds
    gex_neutral = ~gex_positive & ~gex_negative

    return pd.DataFrame({
        "bb_width"    : bb_width,
        "atr_avg"     : atr_avg,
        "gex_positive": gex_positive,
        "gex_negative": gex_negative,
        "gex_neutral" : gex_neutral,
    }, index=df.index)


def detect_expiry_proximity(df: pd.DataFrame,
                             weekly_cycle: int = 5,
                             monthly_cycle: int = 21,
                             near_bars: int = 2) -> pd.Series:
    """
    Approximate proximity to expiry using bar count modulo.

    Parameters
    ----------
    df : pd.DataFrame
        Dataframe (used only for index length).
    weekly_cycle : int
        Bars per weekly cycle (default 5 = 5 trading days).
    monthly_cycle : int
        Bars per monthly cycle (default 21 = ~1 trading month).
    near_bars : int
        Number of trailing bars in cycle to consider "near expiry."

    Returns
    -------
    pd.Series (bool)
        True if current bar is in the last `near_bars` of a weekly or monthly cycle.

    Note: This is a pure cycle approximation. Real expiry proximity requires
    calendar data. This proxy adds mean-reversion bias near cycle boundaries.
    """
    bar_idx = np.arange(len(df))

    # Weekly: last `near_bars` of each 5-bar cycle
    weekly_near = (bar_idx % weekly_cycle) >= (weekly_cycle - near_bars)

    # Monthly: last `near_bars` of each 21-bar cycle
    monthly_near = (bar_idx % monthly_cycle) >= (monthly_cycle - near_bars)

    near_expiry = weekly_near | monthly_near
    return pd.Series(near_expiry, index=df.index)


def generate_signal(df: pd.DataFrame) -> pd.Series:
    """
    Generate GEX (Gamma Exposure proxy) trading signals.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV + indicators dataframe. Must contain:
        open, high, low, close, ATR, BB_upper, BB_lower, BB_middle,
        RSI, MACD, MACD_signal

    Returns
    -------
    pd.Series
        1  = Long signal
       -1  = Short signal
        0  = Flat / no signal

    Signal Rules (Regime-Dependent)
    ---------------------------------
    POSITIVE GEX (narrow BB, market pinning):
      → Mean reversion mode — fade extremes back to midpoint
      LONG:  close <= BB_lower (price at lower extreme → revert to BB_middle)
      SHORT: close >= BB_upper (price at upper extreme → revert to BB_middle)
      Near expiry: apply positive GEX logic even if bands are not quite narrow.

    NEGATIVE GEX (wide BB, explosive moves):
      → Momentum mode — trade breakouts with confirmation
      LONG:  close > BB_upper (breakout above) AND RSI > 50 AND MACD > MACD_signal
      SHORT: close < BB_lower (breakdown below) AND RSI < 50 AND MACD < MACD_signal

    NEUTRAL GEX:
      → No signal (ambiguous volatility regime)

    Expiry Modifier:
      If near_expiry is True AND we would generate a momentum signal,
      downgrade it to neutral (expiry suppresses explosive moves).
      If near_expiry is True AND in neutral regime, apply mean reversion
      (expiry pulls toward pinning).

    Note: If both POSITIVE and NEGATIVE conditions fire (shouldn't happen
    logically, but data edge cases exist), POSITIVE GEX (mean reversion) wins
    because it has tighter confirmation requirements.
    """
    # --- Guard ---
    if not _validate_inputs(df):
        return pd.Series(0, index=df.index, dtype=int)

    # --- Classify GEX regime ---
    regime = classify_gex_regime(df)

    # --- Expiry proximity ---
    near_expiry = detect_expiry_proximity(df)

    # --- MACD momentum direction ---
    macd_bullish = df["MACD"] > df["MACD_signal"]  # bullish MACD crossover
    macd_bearish = df["MACD"] < df["MACD_signal"]  # bearish MACD crossover

    # ==========================================
    # POSITIVE GEX: Mean Reversion Signals
    # ==========================================
    pos_gex_active = regime["gex_positive"] | near_expiry  # expiry boosts pinning

    # Buy at lower Bollinger Band: price extended below → mean revert up
    mr_long  = pos_gex_active & (df["close"] <= df["BB_lower"])

    # Sell at upper Bollinger Band: price extended above → mean revert down
    mr_short = pos_gex_active & (df["close"] >= df["BB_upper"])

    # ==========================================
    # NEGATIVE GEX: Momentum / Breakout Signals
    # ==========================================
    neg_gex_active = regime["gex_negative"] & ~near_expiry  # suppress near expiry

    # Breakout above BB_upper with momentum confirmation
    mo_long  = neg_gex_active & (df["close"] > df["BB_upper"])  \
                              & (df["RSI"] > 50)                 \
                              & macd_bullish

    # Breakdown below BB_lower with momentum confirmation
    mo_short = neg_gex_active & (df["close"] < df["BB_lower"])  \
                              & (df["RSI"] < 50)                 \
                              & macd_bearish

    # ==========================================
    # COMBINE (positive GEX mean reversion takes priority)
    # ==========================================
    long_signal  = mr_long  | mo_long
    short_signal = mr_short | mo_short

    # Mean reversion overrides momentum on conflict
    long_signal[mr_long]   = True
    short_signal[mr_short] = True
    # Clear conflicting momentum signals if mean reversion is firing
    long_signal[mr_short]  = False
    short_signal[mr_long]  = False

    # --- Build output ---
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[short_signal] = -1
    signal[long_signal]  = 1

    # --- Mask warmup ---
    nan_mask = regime["atr_avg"].isna() | df["BB_upper"].isna()
    signal[nan_mask] = 0

    return signal

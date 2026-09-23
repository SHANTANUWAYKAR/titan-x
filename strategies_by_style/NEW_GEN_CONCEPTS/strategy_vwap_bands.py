"""
strategy_vwap_bands.py
=======================
Concept: VWAP with Standard Deviation Bands — Institutional Anchor
===================================================================

WHAT IS VWAP?
-------------
VWAP (Volume-Weighted Average Price) is the average price weighted by volume
over a session. It represents the "fair price" institutions and algorithms
anchor to for execution:
  - Large institutions buying below VWAP = accumulating at a discount.
  - Large institutions selling above VWAP = distributing at a premium.
  - Market makers quote around VWAP as a neutral reference.

Formula: VWAP = Σ(Typical_Price × Volume) / Σ(Volume)

VWAP STANDARD DEVIATION BANDS:
--------------------------------
Similar to Bollinger Bands but anchored to volume-weighted price:
  std_dev = rolling std of (typical_price - VWAP)
  Band 1 = VWAP ± 1 × std_dev   (~68% of price action within this range)
  Band 2 = VWAP ± 2 × std_dev   (~95% of price action within this range)

These bands reveal:
  ± 1 std: "normal" deviation zone. Common bounce/rejection point.
  ± 2 std: "extreme" deviation zone. High probability mean reversion.

INSTITUTIONAL LOGIC:
---------------------
  - Price ABOVE VWAP = bullish structure. Institutions paying premium = demand.
  - Price BELOW VWAP = bearish structure. Institutions selling at discount = supply.
  - Dip to VWAP in uptrend = buying opportunity (adding at fair value).
  - Rally to VWAP in downtrend = selling opportunity (exit/add short at fair value).

TRADING STRATEGIES:
--------------------
  1. TREND PULLBACK (primary):
     LONG: uptrend (EMA_50 rising) + price dips to VWAP or VWAP-1std → buy dip.
     SHORT: downtrend (EMA_50 falling) + price rallies to VWAP or VWAP+1std → sell rally.

  2. EXTREME MEAN REVERSION (scalp):
     LONG: price touches VWAP-2std → extreme oversold → revert to VWAP.
     SHORT: price touches VWAP+2std → extreme overbought → revert to VWAP.

  3. CVD CONFIRMATION:
     Only enter if buy_vol > sell_vol confirms the direction.

OHLCV APPROXIMATION:
---------------------
True VWAP resets at session open (daily). Without timestamps:
  - Rolling 390-bar VWAP (390 × 1-min bars = 6.5 hours = one US session)
  - For daily bars: rolling 20-bar VWAP (≈ 1 month)
  - For hourly bars: rolling 390-bar VWAP
  - This code uses a configurable rolling window (default: 50 bars) as a
    universal proxy that works across timeframes.
  - Std deviation computed as rolling std of deviations from rolling VWAP.

NO REPAINTING: All rolling calculations are bounded by closed bars only.
The rolling window at bar t includes bars [t-window+1 .. t] (no bar t+1).

Author: Project Titan-X — NEW_GEN_CONCEPTS
"""

import numpy as np
import pandas as pd


REQUIRED_COLS = [
    "open", "high", "low", "close", "volume",
    "EMA_50",
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


def compute_vwap_bands(df: pd.DataFrame, window: int = 50) -> pd.DataFrame:
    """
    Compute rolling VWAP and standard deviation bands.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    window : int
        Rolling window for VWAP computation (acts as session proxy).

    Returns
    -------
    pd.DataFrame with columns:
        vwap   : Volume-weighted average price
        upper1 : VWAP + 1 × std
        lower1 : VWAP - 1 × std
        upper2 : VWAP + 2 × std
        lower2 : VWAP - 2 × std

    Method
    ------
    1. Typical price TP = (H + L + C) / 3
    2. Rolling VWAP = Σ(TP × V) / Σ(V) over `window` bars
    3. Deviation = TP - VWAP (signed distance from fair value)
    4. std = rolling std of deviation
    5. Bands = VWAP ± N × std
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_vol = tp * df["volume"]

    # Rolling VWAP: volume-weighted mean price
    roll_vol  = df["volume"].rolling(window=window, min_periods=window // 2).sum()
    roll_tpvol = tp_vol.rolling(window=window, min_periods=window // 2).sum()
    vwap = roll_tpvol / roll_vol.replace(0, np.nan)

    # Deviation of each bar's typical price from VWAP
    deviation = tp - vwap

    # Rolling standard deviation of deviation (measures spread)
    std = deviation.rolling(window=window, min_periods=window // 2).std()

    result = pd.DataFrame({
        "vwap"  : vwap,
        "upper1": vwap + 1.0 * std,   # 1σ band
        "lower1": vwap - 1.0 * std,
        "upper2": vwap + 2.0 * std,   # 2σ band (extreme)
        "lower2": vwap - 2.0 * std,
        "std"   : std,
    }, index=df.index)

    return result


def compute_buy_vol_dominance(df: pd.DataFrame) -> pd.Series:
    """
    Compute whether buyers dominate the current bar.

    Uses the same close-location proxy as the footprint delta strategy.
    Returns True if buy volume > sell volume (net buying pressure).

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.

    Returns
    -------
    pd.Series (bool)
        True = buyers dominating (confirming long bias).
        False = sellers dominating (confirming short bias).
    """
    hl_range = df["high"] - df["low"]
    buy_vol  = df["volume"] * (df["close"] - df["low"])  / (hl_range + 1e-9)
    sell_vol = df["volume"] * (df["high"] - df["close"]) / (hl_range + 1e-9)
    return buy_vol > sell_vol


def detect_ema50_trend(df: pd.DataFrame, lookback: int = 5) -> tuple:
    """
    Detect EMA_50 trend direction.

    Parameters
    ----------
    df : pd.DataFrame
        Dataframe with EMA_50 column.
    lookback : int
        Bars to compare for trend direction.

    Returns
    -------
    tuple of pd.Series (bool): (ema_rising, ema_falling)
    """
    ema_prev = df["EMA_50"].shift(lookback)
    ema_rising  = df["EMA_50"] > ema_prev   # EMA sloping up over lookback bars
    ema_falling = df["EMA_50"] < ema_prev   # EMA sloping down over lookback bars
    return ema_rising, ema_falling


def generate_signal(df: pd.DataFrame) -> pd.Series:
    """
    Generate VWAP Bands institutional trading signals.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV + indicators dataframe. Must contain:
        open, high, low, close, volume, EMA_50

    Returns
    -------
    pd.Series
        1  = Long signal
       -1  = Short signal
        0  = Flat / no signal

    Signal Rules
    ------------
    TREND PULLBACK (primary, higher conviction):
      LONG:
        - EMA_50 rising (uptrend)
        - close touches or crosses below VWAP or lower1 band (dip to fair value)
        - Previous bar closed below the band; current bar closes back above
        - CVD confirms: buy_vol > sell_vol on current bar
      SHORT:
        - EMA_50 falling (downtrend)
        - close touches or crosses above VWAP or upper1 band (rally to fair value)
        - Previous bar closed above the band; current bar closes back below
        - CVD confirms: sell_vol > buy_vol

    EXTREME MEAN REVERSION (scalp, lower timeframe):
      LONG:  close <= lower2 band (extreme oversold) → revert to VWAP
      SHORT: close >= upper2 band (extreme overbought) → revert to VWAP
      (No trend requirement — these are pure statistical reversion trades)

    Combined: Extreme reversion takes priority if active.
    """
    # --- Guard ---
    if not _validate_inputs(df):
        return pd.Series(0, index=df.index, dtype=int)

    # --- Compute VWAP bands ---
    bands = compute_vwap_bands(df, window=50)

    # --- CVD confirmation ---
    buy_dominance = compute_buy_vol_dominance(df)

    # --- EMA_50 trend direction ---
    ema_rising, ema_falling = detect_ema50_trend(df, lookback=5)

    # ==========================================
    # TREND PULLBACK ENTRIES
    # ==========================================

    # LONG: Price dipped to VWAP or lower1 (dip to fair value in uptrend)
    # Previous bar breached below VWAP/lower1, current bar closes back above it
    prev_close = df["close"].shift(1)

    # Dip to VWAP level: previous close below VWAP, current above
    dipped_to_vwap = (prev_close < bands["vwap"]) & (df["close"] > bands["vwap"])

    # Dip to 1std band: previous close below lower1, current above lower1
    dipped_to_1std = (prev_close < bands["lower1"]) & (df["close"] > bands["lower1"])

    trend_long = ema_rising & (dipped_to_vwap | dipped_to_1std) & buy_dominance

    # SHORT: Price rallied to VWAP or upper1 (rally to fair value in downtrend)
    rallied_to_vwap = (prev_close > bands["vwap"]) & (df["close"] < bands["vwap"])
    rallied_to_1std = (prev_close > bands["upper1"]) & (df["close"] < bands["upper1"])

    trend_short = ema_falling & (rallied_to_vwap | rallied_to_1std) & (~buy_dominance)

    # ==========================================
    # EXTREME MEAN REVERSION ENTRIES
    # ==========================================

    # LONG: Price at or below lower2 band (2σ oversold — statistically extreme)
    extreme_long  = df["close"] <= bands["lower2"]

    # SHORT: Price at or above upper2 band (2σ overbought — statistically extreme)
    extreme_short = df["close"] >= bands["upper2"]

    # ==========================================
    # COMBINE: extreme reversion overrides trend pullback
    # ==========================================
    long_signal  = extreme_long  | trend_long
    short_signal = extreme_short | trend_short

    # --- Build output ---
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[short_signal] = -1
    signal[long_signal] = 1  # long overrides short on conflict

    # --- Mask warmup ---
    nan_mask = bands["vwap"].isna()
    signal[nan_mask] = 0

    return signal

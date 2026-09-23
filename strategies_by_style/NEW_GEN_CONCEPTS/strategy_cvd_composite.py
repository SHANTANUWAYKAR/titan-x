"""
strategy_cvd_composite.py
==========================
🚀 FLAGSHIP: CVD + Volume Profile + VWAP + Liquidity + Regime Composite
========================================================================

OVERVIEW
--------
This is the most advanced strategy in the NEW_GEN_CONCEPTS suite. It
synthesizes five distinct market-microstructure signals into a unified
scoring system that only generates a trade signal when MULTIPLE independent
edge sources agree simultaneously.

The core insight: no single new-gen concept has an edge alone. VWAP alone
can be faded. CVD alone has many false divergences. Liquidity sweeps alone
can extend. But when 4+ signals STACK in the same direction simultaneously,
the probability of a sustained move increases dramatically.

SCORING SYSTEM
--------------
Each component awards 1 point toward LONG or SHORT:

  LONG SCORING:
  ┌─────┬────────────────────────────────────────────────────────┐
  │ +1  │ CVD positive (net buying pressure last 3 bars)         │
  │ +1  │ Price above VWAP (bullish institutional bias)          │
  │ +1  │ Price bounced from VAL (Volume Profile support)        │
  │ +1  │ Liquidity sweep of equal lows in last 3 bars (stop     │
  │     │   hunt confirming demand absorption)                   │
  │ +1  │ RSI between 40-60 AND rising (healthy momentum zone)   │
  └─────┴────────────────────────────────────────────────────────┘

  SHORT SCORING (mirror of long):
  ┌─────┬────────────────────────────────────────────────────────┐
  │ +1  │ CVD negative (net selling pressure last 3 bars)        │
  │ +1  │ Price below VWAP (bearish institutional bias)          │
  │ +1  │ Price rejected from VAH (Volume Profile resistance)    │
  │ +1  │ Liquidity sweep of equal highs in last 3 bars          │
  │ +1  │ RSI between 40-60 AND falling (healthy fade zone)      │
  └─────┴────────────────────────────────────────────────────────┘

THRESHOLD: score >= 4 → signal fires.
MARKET REGIME: ADX < 20 → signals suppressed (range → all signals unreliable)

COMPONENT DESCRIPTIONS
-----------------------
1. CVD (Cumulative Volume Delta):
   Net order flow over recent bars. Positive = buyers more aggressive.
   Derived from close-location volume split (same as strategy_footprint_delta).

2. VWAP Position:
   Institutional fair value anchor. Being above VWAP in an uptrend means
   price is trading at a premium — bullish. Below VWAP = discount = bearish.
   Uses 50-bar rolling VWAP (universal proxy across timeframes).

3. Volume Profile POC Bounce/Reject:
   POC = rolling 50-bar VWAP (our OHLCV approximation).
   VAL = POC - 1.5 × ATR (value area low = demand zone).
   VAH = POC + 1.5 × ATR (value area high = supply zone).
   Bounce off VAL → long bias. Rejection from VAH → short bias.

4. Liquidity Sweep:
   Smart money engineers stop hunts to acquire positions at better prices.
   A sweep of equal lows (spike below, close above) = bullish conviction.
   A sweep of equal highs (spike above, close below) = bearish conviction.
   Detected in last 3 bars (sweep signal persists briefly).

5. Market Regime (ADX):
   ADX > 20: trending market → signals work.
   ADX < 20: pure chop → suppress all signals regardless of score.

OHLCV APPROXIMATIONS USED:
----------------------------
  - CVD: close-location volume split (Buy_Vol = V × (C-L)/(H-L+ε))
  - VWAP: rolling 50-bar volume-weighted average of typical price
  - POC/VAH/VAL: rolling VWAP ± 1.5 × ATR
  - Equal highs/lows: pivot detection via left/right bar comparison
  - Liquidity sweep: intrabar high/low vs. equal level + close comparison

NO REPAINTING GUARANTEE:
-------------------------
  - All rolling windows use data UP TO AND INCLUDING the current closed bar.
  - All pivot detections use shift() to reference prior-bar confirmed pivots.
  - No future bar data is accessed anywhere.
  - Signal at bar t uses only information available at bar t's close.

USAGE EXAMPLE:
--------------
    import pandas as pd
    from strategy_cvd_composite import generate_signal

    # df must have: open, high, low, close, volume,
    #               EMA_9, EMA_20, EMA_50, EMA_200,
    #               RSI, MACD, MACD_signal, ATR, ADX,
    #               BB_upper, BB_lower, BB_middle
    signals = generate_signal(df)  # returns pd.Series of 1/-1/0

INTEGRATION NOTES:
------------------
  - For E26 backtesting: pass generate_signal as the strategy_fn.
  - For E51 signal generation: use score (0-5) as a conviction metric.
  - Higher threshold (score >= 5): fewer but higher-conviction signals.
  - Lower threshold (score >= 3): more signals, lower precision.

Author: Project Titan-X — NEW_GEN_CONCEPTS (FLAGSHIP)
"""

import numpy as np
import pandas as pd


# ============================================================
# REQUIRED COLUMNS AND VALIDATION
# ============================================================

REQUIRED_COLS = [
    "open", "high", "low", "close", "volume",
    "EMA_20", "EMA_50", "RSI", "ATR", "ADX",
]

MIN_BARS = 60       # need 50 bars for VWAP + 10 buffer
SIGNAL_THRESHOLD = 4  # minimum score to generate a trade signal


def _validate_inputs(df: pd.DataFrame) -> bool:
    """
    Validate that the dataframe has required columns and sufficient rows.

    Returns False (and the caller returns all-zeros) if:
      - Any required column is missing
      - Fewer than MIN_BARS rows available
    """
    for col in REQUIRED_COLS:
        if col not in df.columns:
            return False
    if len(df) < MIN_BARS:
        return False
    return True


# ============================================================
# COMPONENT 1: CVD (Cumulative Volume Delta)
# ============================================================

def _compute_cvd(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """
    Compute rolling Cumulative Volume Delta (CVD).

    CVD measures net aggressive order flow: positive = buyers more aggressive,
    negative = sellers more aggressive. Uses close-location approximation.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    window : int
        Rolling window for CVD accumulation.

    Returns
    -------
    pd.Series
        CVD values. NaN for first (window//2 - 1) bars.
    """
    hl_range = df["high"] - df["low"]
    # Buy vol: proportion of bar range closed toward the high
    buy_vol  = df["volume"] * (df["close"] - df["low"])  / (hl_range + 1e-9)
    # Sell vol: proportion of bar range closed toward the low
    sell_vol = df["volume"] * (df["high"] - df["close"]) / (hl_range + 1e-9)
    delta = buy_vol - sell_vol   # per-bar net order flow
    # Rolling cumulative sum: recent net flow pressure
    cvd = delta.rolling(window=window, min_periods=window // 2).sum()
    return cvd


def score_cvd_long(df: pd.DataFrame, cvd: pd.Series, bars: int = 3) -> pd.Series:
    """
    Score +1 long if CVD has been positive for last `bars` bars.

    Positive CVD = buyers more aggressive than sellers.
    Persistence for 3 bars = sustained demand pressure, not noise.

    Returns
    -------
    pd.Series (int: 0 or 1)
    """
    # Rolling minimum over last `bars` bars: if min > 0, all were positive
    cvd_min = cvd.rolling(window=bars, min_periods=bars).min()
    return (cvd_min > 0).astype(int)


def score_cvd_short(df: pd.DataFrame, cvd: pd.Series, bars: int = 3) -> pd.Series:
    """
    Score +1 short if CVD has been negative for last `bars` bars.

    Negative CVD = sellers more aggressive. Persistence = real supply pressure.

    Returns
    -------
    pd.Series (int: 0 or 1)
    """
    cvd_max = cvd.rolling(window=bars, min_periods=bars).max()
    return (cvd_max < 0).astype(int)


# ============================================================
# COMPONENT 2: VWAP Position
# ============================================================

def _compute_vwap(df: pd.DataFrame, window: int = 50) -> pd.Series:
    """
    Compute rolling VWAP as the institutional fair-value anchor.

    VWAP = Σ(Typical_Price × Volume) / Σ(Volume) over rolling `window` bars.
    Rolling (vs. session-reset) VWAP is used as a universal timeframe proxy.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe.
    window : int
        Rolling window (50 bars ≈ 2.5 weeks on 1h, 2.5 days on 30m).

    Returns
    -------
    pd.Series
        VWAP values.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_vol = tp * df["volume"]
    roll_vol   = df["volume"].rolling(window=window, min_periods=window // 2).sum()
    roll_tpvol = tp_vol.rolling(window=window, min_periods=window // 2).sum()
    return roll_tpvol / roll_vol.replace(0, np.nan)


def score_vwap_long(df: pd.DataFrame, vwap: pd.Series) -> pd.Series:
    """
    Score +1 long if price is above VWAP (bullish institutional bias).

    Institutions executing at VWAP or below are accumulating.
    Price ABOVE VWAP = market paying premium = demand signal.

    Returns
    -------
    pd.Series (int: 0 or 1)
    """
    return (df["close"] > vwap).astype(int)


def score_vwap_short(df: pd.DataFrame, vwap: pd.Series) -> pd.Series:
    """
    Score +1 short if price is below VWAP (bearish institutional bias).

    Price BELOW VWAP = market at discount = supply signal / distribution.

    Returns
    -------
    pd.Series (int: 0 or 1)
    """
    return (df["close"] < vwap).astype(int)


# ============================================================
# COMPONENT 3: Volume Profile POC Bounce/Reject
# ============================================================

def _compute_poc_levels(df: pd.DataFrame, vwap: pd.Series,
                         window: int = 50) -> tuple:
    """
    Compute POC, VAH, VAL using rolling VWAP + ATR proxy.

    POC = rolling VWAP (best OHLCV approximation of volume-weighted center)
    VAH = POC + 1.5 × rolling_mean(ATR, window)   (value area high)
    VAL = POC - 1.5 × rolling_mean(ATR, window)   (value area low)

    These represent the "fair value zone" and its bounds.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV + ATR dataframe.
    vwap : pd.Series
        Pre-computed rolling VWAP.
    window : int
        Rolling window for ATR averaging.

    Returns
    -------
    tuple: (poc, vah, val) — three pd.Series
    """
    poc = vwap
    atr_avg = df["ATR"].rolling(window=window, min_periods=window // 2).mean()
    vah = poc + 1.5 * atr_avg
    val = poc - 1.5 * atr_avg
    return poc, vah, val


def score_poc_bounce_long(df: pd.DataFrame, val: pd.Series) -> pd.Series:
    """
    Score +1 long if price bounced from VAL (Value Area Low).

    VAL is the lower edge of where 70% of recent volume traded.
    A bounce off VAL = buyers defending the value area = bullish.

    Logic:
      - Previous bar's low touched or breached VAL (price went to the level)
      - Current close is back above VAL (price recovered = bounce confirmed)

    Returns
    -------
    pd.Series (int: 0 or 1)
    """
    prev_low = df["low"].shift(1)
    prev_val = val.shift(1)
    touched  = prev_low <= prev_val          # low tested the VAL
    recovered = df["close"] > val            # close back above = bounce
    return (touched & recovered).astype(int)


def score_poc_reject_short(df: pd.DataFrame, vah: pd.Series) -> pd.Series:
    """
    Score +1 short if price was rejected from VAH (Value Area High).

    VAH is the upper edge of the value area. A rejection there = sellers
    defending the upper bound = distribution = bearish.

    Logic:
      - Previous bar's high touched or exceeded VAH
      - Current close is back below VAH (rejection confirmed)

    Returns
    -------
    pd.Series (int: 0 or 1)
    """
    prev_high = df["high"].shift(1)
    prev_vah  = vah.shift(1)
    touched   = prev_high >= prev_vah        # high tested the VAH
    rejected  = df["close"] < vah            # close back below = rejection
    return (touched & rejected).astype(int)


# ============================================================
# COMPONENT 4: Liquidity Sweep Detection
# ============================================================

def _detect_pivots(df: pd.DataFrame, left: int = 5,
                    right: int = 5) -> tuple:
    """
    Detect pivot highs and lows using a left/right bar comparison.

    A pivot high at bar t-right: its high is the maximum of all bars
    in [t-right-left .. t-right+right]. Since we're at bar t, bars
    [t-right+1 .. t] are all available (right bars behind current).
    This ensures NO lookahead — the pivot is always confirmed.

    Returns
    -------
    tuple: (pivot_highs, pivot_lows) — two pd.Series (bool)
    """
    highs, lows = df["high"], df["low"]

    # Left side: max of bars BEFORE the pivot candidate
    left_max = highs.shift(right + 1).rolling(window=left, min_periods=left).max()
    left_min = lows.shift(right + 1).rolling(window=left, min_periods=left).min()

    # Right side: max of bars AFTER the pivot candidate (available since right bars ago)
    right_max = highs.shift(1).rolling(window=right, min_periods=right).max()
    right_min = lows.shift(1).rolling(window=right, min_periods=right).min()

    # Pivot candidate bar's price
    pivot_h = highs.shift(right)
    pivot_l = lows.shift(right)

    ph = (pivot_h > left_max) & (pivot_h > right_max)
    pl = (pivot_l < left_min) & (pivot_l < right_min)

    return ph.fillna(False), pl.fillna(False)


def _find_last_pivot_level(pivot_mask: pd.Series, price: pd.Series,
                            lookback: int = 30) -> tuple:
    """
    Find the most recent two pivot price levels for equal-high/low detection.

    Uses a rolling window to find last 2 confirmed pivot prices.
    Implemented efficiently with forward-only rolling to avoid lookahead.

    Returns
    -------
    tuple: (level_1, level_2) — two pd.Series of prices (NaN when unavailable)
    """
    n = len(pivot_mask)
    lvl1 = np.full(n, np.nan)
    lvl2 = np.full(n, np.nan)

    for i in range(lookback, n):
        window_mask  = pivot_mask.iloc[i - lookback : i]
        window_price = price.iloc[i - lookback : i]
        pprices = window_price[window_mask].values
        if len(pprices) >= 2:
            lvl1[i] = pprices[-1]
            lvl2[i] = pprices[-2]
        elif len(pprices) == 1:
            lvl1[i] = pprices[-1]

    return (pd.Series(lvl1, index=pivot_mask.index),
            pd.Series(lvl2, index=pivot_mask.index))


def _detect_sweep(df: pd.DataFrame, pivot_mask_h: pd.Series,
                   pivot_mask_l: pd.Series,
                   tolerance_pct: float = 0.001,
                   lookback: int = 20) -> tuple:
    """
    Detect liquidity sweeps of equal highs (bearish) and equal lows (bullish).

    Equal high sweep (bearish):
      - Two recent pivot highs within `tolerance_pct` of each other
      - Current bar's high exceeds that level AND closes below it
      → Stop hunt triggered, price rejected = bearish momentum

    Equal low sweep (bullish):
      - Two recent pivot lows within `tolerance_pct` of each other
      - Current bar's low breaches that level AND closes above it
      → Stop hunt triggered, price reclaimed = bullish momentum

    Returns
    -------
    tuple: (sweep_down_bullish, sweep_up_bearish) — two pd.Series (bool)
    """
    # Equal highs
    h1, h2 = _find_last_pivot_level(pivot_mask_h, df["high"], lookback)
    both_h = ~h1.isna() & ~h2.isna()
    pct_h  = (h1 - h2).abs() / (h2.replace(0, np.nan).abs() + 1e-9)
    eq_high = both_h & (pct_h <= tolerance_pct)
    eq_high_level = (h1 + h2) / 2.0
    sweep_up_bearish = eq_high & (df["high"] > eq_high_level) & (df["close"] < eq_high_level)

    # Equal lows
    l1, l2 = _find_last_pivot_level(pivot_mask_l, df["low"], lookback)
    both_l = ~l1.isna() & ~l2.isna()
    pct_l  = (l1 - l2).abs() / (l2.abs().replace(0, np.nan) + 1e-9)
    eq_low = both_l & (pct_l <= tolerance_pct)
    eq_low_level = (l1 + l2) / 2.0
    sweep_down_bullish = eq_low & (df["low"] < eq_low_level) & (df["close"] > eq_low_level)

    return sweep_down_bullish, sweep_up_bearish


def score_sweep_long(df: pd.DataFrame, sweep_down: pd.Series,
                      persist_bars: int = 3) -> pd.Series:
    """
    Score +1 long if a bullish liquidity sweep occurred in last `persist_bars`.

    The sweep signal persists for a few bars because the bullish structure
    set up by the sweep (absorption of sellers) typically plays out over
    1-3 bars, not just the sweep bar itself.

    Parameters
    ----------
    sweep_down : pd.Series (bool)
        True at bars where equal-low sweep occurred.
    persist_bars : int
        Number of bars the sweep signal remains active.

    Returns
    -------
    pd.Series (int: 0 or 1)
    """
    # Rolling max: if any bar in last N had a sweep, score stays active
    recent_sweep = sweep_down.astype(int).rolling(
        window=persist_bars, min_periods=1
    ).max()
    return (recent_sweep > 0).astype(int)


def score_sweep_short(df: pd.DataFrame, sweep_up: pd.Series,
                       persist_bars: int = 3) -> pd.Series:
    """
    Score +1 short if a bearish liquidity sweep occurred in last `persist_bars`.

    Returns
    -------
    pd.Series (int: 0 or 1)
    """
    recent_sweep = sweep_up.astype(int).rolling(
        window=persist_bars, min_periods=1
    ).max()
    return (recent_sweep > 0).astype(int)


# ============================================================
# COMPONENT 5: RSI Momentum Score
# ============================================================

def score_rsi_long(df: pd.DataFrame) -> pd.Series:
    """
    Score +1 long if RSI is in the healthy momentum zone and rising.

    RSI 40-60 + rising = momentum building from a healthy base.
    This avoids chasing overbought (> 70) or buying capitulation (< 30).
    The "neutral zone" RSI (40-60) rising is the sweet spot for new longs.

    Returns
    -------
    pd.Series (int: 0 or 1)
    """
    in_healthy_zone = (df["RSI"] >= 40) & (df["RSI"] <= 60)
    rsi_rising = df["RSI"] > df["RSI"].shift(1)
    return (in_healthy_zone & rsi_rising).astype(int)


def score_rsi_short(df: pd.DataFrame) -> pd.Series:
    """
    Score +1 short if RSI is in the healthy fade zone and falling.

    RSI 40-60 + falling = momentum rolling over from neutral.
    Avoids selling capitulation (< 30) or chasing oversold (< 30).

    Returns
    -------
    pd.Series (int: 0 or 1)
    """
    in_fade_zone = (df["RSI"] >= 40) & (df["RSI"] <= 60)
    rsi_falling = df["RSI"] < df["RSI"].shift(1)
    return (in_fade_zone & rsi_falling).astype(int)


# ============================================================
# REGIME FILTER
# ============================================================

def is_trending_regime(df: pd.DataFrame,
                        adx_threshold: float = 20.0) -> pd.Series:
    """
    Determine if market is in a trending regime suitable for signals.

    ADX > 20: Some directional movement present → signals work.
    ADX < 20: Pure chop → all signals are noise, suppress everything.

    Parameters
    ----------
    df : pd.DataFrame
        Dataframe with ADX column.
    adx_threshold : float
        ADX level above which market is considered "not pure chop."

    Returns
    -------
    pd.Series (bool)
        True when regime is safe for trading.
    """
    return df["ADX"] >= adx_threshold


# ============================================================
# MAIN SIGNAL GENERATOR
# ============================================================

def generate_signal(df: pd.DataFrame,
                     threshold: int = SIGNAL_THRESHOLD) -> pd.Series:
    """
    Generate composite CVD + VWAP + Volume Profile + Liquidity + Regime signals.

    This is the FLAGSHIP strategy. It scores 5 independent microstructure
    signals in each direction, then fires only when >= `threshold` agree.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV + indicators dataframe. Required columns:
        open, high, low, close, volume, EMA_20, EMA_50, RSI, ATR, ADX
        Optional (used if present): EMA_9, EMA_200, MACD, MACD_signal,
        BB_upper, BB_lower, BB_middle

    threshold : int
        Minimum composite score (0-5) required to generate a signal.
        Default 4 = high-conviction only. Use 3 for more frequent signals.

    Returns
    -------
    pd.Series
        1  = Long signal (score_long >= threshold)
       -1  = Short signal (score_short >= threshold)
        0  = Flat / no signal

    Score Breakdown (each direction, max 5):
    ----------------------------------------
    Long:
      [1] CVD positive for last 3 bars (net buying pressure)
      [2] Close above VWAP (bullish institutional position)
      [3] Price bounced from VAL — Volume Profile support
      [4] Bullish liquidity sweep in last 3 bars (stop hunt absorbed)
      [5] RSI 40-60 and rising (healthy momentum zone)

    Short (mirror):
      [1] CVD negative for last 3 bars
      [2] Close below VWAP
      [3] Price rejected from VAH
      [4] Bearish liquidity sweep in last 3 bars
      [5] RSI 40-60 and falling

    Regime gate: ADX < 20 → all signals suppressed (no-trade zone).

    Processing order (all on closed-bar data):
      1. Compute CVD (rolling 20-bar)
      2. Compute rolling VWAP (50-bar)
      3. Derive POC/VAH/VAL from VWAP + ATR
      4. Detect pivot highs/lows (right=5, so confirmed 5 bars prior)
      5. Detect equal highs/lows and sweeps
      6. Compute each component score (0 or 1 per component)
      7. Sum scores
      8. Apply regime gate
      9. Apply threshold
    """
    # ─── Guard ───────────────────────────────────────────────
    if not _validate_inputs(df):
        return pd.Series(0, index=df.index, dtype=int)

    # ─── Step 1: CVD ─────────────────────────────────────────
    cvd = _compute_cvd(df, window=20)

    s1_long  = score_cvd_long(df, cvd, bars=3)   # net buying last 3 bars
    s1_short = score_cvd_short(df, cvd, bars=3)  # net selling last 3 bars

    # ─── Step 2: VWAP ────────────────────────────────────────
    vwap = _compute_vwap(df, window=50)

    s2_long  = score_vwap_long(df, vwap)    # above VWAP = bullish bias
    s2_short = score_vwap_short(df, vwap)   # below VWAP = bearish bias

    # ─── Step 3: Volume Profile POC/VAH/VAL ─────────────────
    poc, vah, val = _compute_poc_levels(df, vwap, window=50)

    s3_long  = score_poc_bounce_long(df, val)    # bounce off VAL
    s3_short = score_poc_reject_short(df, vah)   # reject from VAH

    # ─── Step 4: Liquidity Sweeps ────────────────────────────
    pivot_h, pivot_l = _detect_pivots(df, left=5, right=5)
    sweep_down, sweep_up = _detect_sweep(df, pivot_h, pivot_l,
                                          tolerance_pct=0.001,
                                          lookback=20)
    s4_long  = score_sweep_long(df, sweep_down, persist_bars=3)
    s4_short = score_sweep_short(df, sweep_up, persist_bars=3)

    # ─── Step 5: RSI Momentum ────────────────────────────────
    s5_long  = score_rsi_long(df)     # RSI 40-60, rising
    s5_short = score_rsi_short(df)    # RSI 40-60, falling

    # ─── Sum Scores ──────────────────────────────────────────
    score_long  = s1_long  + s2_long  + s3_long  + s4_long  + s5_long
    score_short = s1_short + s2_short + s3_short + s4_short + s5_short

    # ─── Regime Gate ─────────────────────────────────────────
    # ADX < 20 = choppy market → all concepts fail → suppress signals
    trending = is_trending_regime(df, adx_threshold=20.0)

    score_long[~trending]  = 0  # zero out in choppy market
    score_short[~trending] = 0

    # ─── Apply Threshold ─────────────────────────────────────
    long_signal  = score_long  >= threshold   # requires >= 4 of 5 agreeing
    short_signal = score_short >= threshold

    # ─── Build Output ────────────────────────────────────────
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[short_signal] = -1
    signal[long_signal]  = 1   # long overrides short if both fire (rare)

    # ─── Mask Warmup Period ──────────────────────────────────
    # Suppress signals until all components have enough history
    nan_mask = vwap.isna() | cvd.isna() | val.isna()
    signal[nan_mask] = 0

    return signal


# ============================================================
# BONUS: Score Inspector (for research/debugging)
# ============================================================

def get_component_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a DataFrame with all 10 component scores (5 long + 5 short).

    Useful for:
      - Understanding WHY a signal fired (which components contributed)
      - Identifying which components are most/least informative
      - Tuning the threshold
      - Building signal attribution dashboards

    Parameters
    ----------
    df : pd.DataFrame
        Same OHLCV + indicators dataframe as generate_signal.

    Returns
    -------
    pd.DataFrame with columns:
        s1_long, s1_short   : CVD scores
        s2_long, s2_short   : VWAP position scores
        s3_long, s3_short   : Volume Profile bounce/reject scores
        s4_long, s4_short   : Liquidity sweep scores
        s5_long, s5_short   : RSI momentum scores
        score_long          : Total long score (0-5)
        score_short         : Total short score (0-5)
        regime_ok           : Whether ADX > 20 (signal allowed)
        final_signal        : -1/0/1 final signal
    """
    if not _validate_inputs(df):
        empty = pd.DataFrame(0, index=df.index, columns=[
            "s1_long", "s1_short", "s2_long", "s2_short",
            "s3_long", "s3_short", "s4_long", "s4_short",
            "s5_long", "s5_short", "score_long", "score_short",
            "regime_ok", "final_signal"
        ])
        return empty

    cvd = _compute_cvd(df, window=20)
    vwap = _compute_vwap(df, window=50)
    poc, vah, val = _compute_poc_levels(df, vwap, window=50)
    pivot_h, pivot_l = _detect_pivots(df, left=5, right=5)
    sweep_down, sweep_up = _detect_sweep(df, pivot_h, pivot_l)

    s1l = score_cvd_long(df, cvd, bars=3)
    s1s = score_cvd_short(df, cvd, bars=3)
    s2l = score_vwap_long(df, vwap)
    s2s = score_vwap_short(df, vwap)
    s3l = score_poc_bounce_long(df, val)
    s3s = score_poc_reject_short(df, vah)
    s4l = score_sweep_long(df, sweep_down, persist_bars=3)
    s4s = score_sweep_short(df, sweep_up, persist_bars=3)
    s5l = score_rsi_long(df)
    s5s = score_rsi_short(df)

    sl  = s1l + s2l + s3l + s4l + s5l
    ss  = s1s + s2s + s3s + s4s + s5s
    reg = is_trending_regime(df)

    sl[~reg] = 0
    ss[~reg] = 0

    signal = pd.Series(0, index=df.index, dtype=int)
    signal[ss >= SIGNAL_THRESHOLD] = -1
    signal[sl >= SIGNAL_THRESHOLD] = 1
    nan_mask = vwap.isna() | cvd.isna() | val.isna()
    signal[nan_mask] = 0

    return pd.DataFrame({
        "s1_long"     : s1l,   "s1_short"    : s1s,
        "s2_long"     : s2l,   "s2_short"    : s2s,
        "s3_long"     : s3l,   "s3_short"    : s3s,
        "s4_long"     : s4l,   "s4_short"    : s4s,
        "s5_long"     : s5l,   "s5_short"    : s5s,
        "score_long"  : sl,
        "score_short" : ss,
        "regime_ok"   : reg,
        "final_signal": signal,
    }, index=df.index)

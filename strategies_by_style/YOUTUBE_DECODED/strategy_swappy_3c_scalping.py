"""
Strategy: Swappy 3-Candle Scalping (SwappyTrading0101)
=======================================================
Decoded from SwappyTrading0101's YouTube / PDF breakdown.

TRADER BACKGROUND
-----------------
SwappyTrading0101 is a Gold (XAUUSD) scalper who focuses on a clean
3-candle momentum pattern near key S/R levels. The core insight is that
two consecutive strong-bodied candles (≥ 80% of their range is body, i.e.
tiny wicks) signal institutional momentum, and an inside candle that follows
acts as a compression / energy-coil. A breakout above the pattern high
(or below the pattern low) triggers an entry.

DECODED RULES
-------------
1. TIMEFRAME     : 5-minute bars (XAUUSD primary)
2. PATTERN       :
   - Candle C1 : body_ratio >= 0.80 (|close - open| / (high - low) >= 0.80)
   - Candle C2 : body_ratio >= 0.80 (same check, one bar later)
   - Candle C3 : INSIDE candle — high <= C2.high AND low >= C2.low
   Both C1 and C2 must point the SAME direction (both bullish or both bearish)
   for a clean momentum read.
3. LOCATION FILTER :
   - BUY  setup → pattern must occur near SUPPORT
     (proxy: close ≤ EMA_50 and close ≤ BB_lower * 1.002 OR close ≤ EMA_200)
   - SELL setup → pattern must occur near RESISTANCE
     (proxy: close ≥ EMA_50 and close ≥ BB_upper * 0.998 OR close ≥ EMA_200)
4. TRIGGER :
   - BUY  : current candle CLOSES above the swing HIGH of the 3-candle pattern
             (pattern_high = max(C1.high, C2.high, C3.high))
   - SELL : current candle CLOSES below the swing LOW of the pattern
             (pattern_low  = min(C1.low,  C2.low,  C3.low))
5. ENTRY  : on the CLOSE of the breakout candle (no repainting)
6. STOP   : below/above the 3-candle pattern range (approximated via ATR;
             exact level must be set per trade in live execution)
7. TARGET : 1 : 3 risk-reward (for signal generation only — sizing is
             handled externally using ATR)
8. FILTERS:
   - ADX >= 20 : avoid sideways / ranging markets
   - Volume confirmation : breakout bar volume > 1.2× 20-bar average volume

APPROXIMATIONS
--------------
- "Near support / resistance" is approximated using BB_lower/BB_upper bands
  and EMA_50/EMA_200.  In live trading SwappyTrading0101 uses hand-drawn S/R
  zones — these are the closest equivalent available in the standard df columns.
- Session / news filter (avoid major news windows) cannot be implemented
  without an external calendar; omitted with a graceful fallback comment.
- ATR-based position sizing: a sizing_units() helper is provided for reference
  but is NOT part of the signal series itself (signal = 1 / -1 / 0 only).

USAGE
-----
    signal = strategy_swappy_3c_scalping(df)
    # signal is a pd.Series aligned to df.index
    # 1 = go long, -1 = go short, 0 = no position
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helper: body ratio of a single candle
# ---------------------------------------------------------------------------
def _body_ratio(o: pd.Series, h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    """Return |close - open| / (high - low), with NaN where range == 0."""
    rng = h - l
    body = (c - o).abs()
    # avoid division-by-zero on doji candles with zero range
    return body.where(rng > 0, other=np.nan) / rng.where(rng > 0, other=np.nan)


# ---------------------------------------------------------------------------
# Optional helper: ATR-based position sizing (for reference, not the signal)
# ---------------------------------------------------------------------------
def sizing_units(account_equity: float, risk_pct: float, atr: float,
                 atr_stop_mult: float = 1.5, point_value: float = 1.0) -> float:
    """
    Compute how many units to trade given an ATR-based stop.

    Parameters
    ----------
    account_equity : total account size in base currency
    risk_pct       : fraction of equity to risk per trade (e.g. 0.01 = 1%)
    atr            : current ATR value in price units
    atr_stop_mult  : multiples of ATR used as the stop distance (default 1.5)
    point_value    : monetary value per 1-unit move (e.g. for Gold futures)

    Returns
    -------
    float : number of units / contracts to trade
    """
    risk_amount = account_equity * risk_pct            # $ risk per trade
    stop_dist = atr * atr_stop_mult                    # stop distance in price
    return risk_amount / (stop_dist * point_value)     # size = risk / (stop × tick_value)


# ---------------------------------------------------------------------------
# Main strategy function
# ---------------------------------------------------------------------------
def strategy_swappy_3c_scalping(df: pd.DataFrame) -> pd.Series:
    """
    Swappy 3-Candle Scalping strategy.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain: open, high, low, close, volume,
                      EMA_50, EMA_200, ATR, ADX,
                      BB_upper, BB_lower, BB_middle

    Returns
    -------
    pd.Series
        +1 (long signal), -1 (short signal), 0 (flat) — triggers on candle CLOSE
    """
    # -------------------------------------------------------------------------
    # 0. Validate required columns
    # -------------------------------------------------------------------------
    required = ["open", "high", "low", "close", "volume",
                "EMA_50", "EMA_200", "ATR", "ADX", "BB_upper", "BB_lower"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"strategy_swappy_3c_scalping: missing column '{col}'")

    n = len(df)
    signal = pd.Series(0, index=df.index, dtype=int)

    if n < 5:  # need at least 5 bars to look back 3 pattern candles + 1 trigger
        return signal

    # -------------------------------------------------------------------------
    # 1. Pre-compute body ratios for every bar (vectorised)
    # -------------------------------------------------------------------------
    br = _body_ratio(df["open"], df["high"], df["low"], df["close"])
    # br[i] == np.nan means doji with zero range; treat as 0 body ratio
    br = br.fillna(0.0)

    # -------------------------------------------------------------------------
    # 2. Pre-compute 20-bar rolling average volume for volume confirmation
    # -------------------------------------------------------------------------
    vol_avg20 = df["volume"].rolling(20, min_periods=5).mean()

    # -------------------------------------------------------------------------
    # 3. Identify bullish / bearish candle direction
    # -------------------------------------------------------------------------
    bullish = df["close"] > df["open"]   # True where candle closed up
    bearish = df["close"] < df["open"]   # True where candle closed down

    # -------------------------------------------------------------------------
    # 4. Loop over bars starting at index 4 (need bars i-3, i-2, i-1, i)
    #    Pattern candles: C1=i-3, C2=i-2, C3=i-1 (inside candle)
    #    Trigger candle : C4=i (current close)
    # -------------------------------------------------------------------------
    for i in range(3, n):
        # --- Extract pattern candles (index positions) ---
        c1_idx = i - 3   # candle 1
        c2_idx = i - 2   # candle 2
        c3_idx = i - 1   # inside candle (candle 3)
        c4_idx = i       # current / trigger candle

        # --- ADX filter: skip sideways markets ---
        if df["ADX"].iloc[c4_idx] < 20:
            # ADX < 20 → market is ranging; Swappy says to skip
            continue

        # --- Volume confirmation: current bar must have above-average volume ---
        avg_vol = vol_avg20.iloc[c4_idx]
        if pd.isna(avg_vol) or df["volume"].iloc[c4_idx] < 1.2 * avg_vol:
            # breakout candle must show elevated volume (1.2× threshold)
            continue

        # --- Body ratio check for C1 and C2 ---
        c1_strong = br.iloc[c1_idx] >= 0.80   # C1 is a strong momentum candle
        c2_strong = br.iloc[c2_idx] >= 0.80   # C2 is a strong momentum candle
        if not (c1_strong and c2_strong):
            continue   # at least one of the first two candles lacks conviction

        # --- Inside candle check for C3 ---
        c3_inside = (
            df["high"].iloc[c3_idx] <= df["high"].iloc[c2_idx] and  # C3 high ≤ C2 high
            df["low"].iloc[c3_idx]  >= df["low"].iloc[c2_idx]       # C3 low  ≥ C2 low
        )
        if not c3_inside:
            continue   # C3 is NOT an inside candle; pattern invalid

        # --- Directionality: C1 and C2 must agree ---
        c1_bull = bullish.iloc[c1_idx]
        c2_bull = bullish.iloc[c2_idx]
        c1_bear = bearish.iloc[c1_idx]
        c2_bear = bearish.iloc[c2_idx]
        both_bull = c1_bull and c2_bull   # both candles up → bullish momentum
        both_bear = c1_bear and c2_bear   # both candles down → bearish momentum
        if not (both_bull or both_bear):
            continue   # mixed direction; skip ambiguous patterns

        # --- Pattern swing high / low (the 3-candle range) ---
        pattern_high = max(
            df["high"].iloc[c1_idx],
            df["high"].iloc[c2_idx],
            df["high"].iloc[c3_idx],
        )
        pattern_low = min(
            df["low"].iloc[c1_idx],
            df["low"].iloc[c2_idx],
            df["low"].iloc[c3_idx],
        )

        # --- Current bar close and EMA/BB context ---
        c4_close = df["close"].iloc[c4_idx]
        ema50    = df["EMA_50"].iloc[c4_idx]
        ema200   = df["EMA_200"].iloc[c4_idx]
        bb_upper = df["BB_upper"].iloc[c4_idx]
        bb_lower = df["BB_lower"].iloc[c4_idx]

        # =====================================================================
        # BUY SIGNAL
        # Pattern: both_bull (momentum up), C3 inside → coil near support
        # Location proxy: price ≤ EMA_50 OR near BB_lower (support zone)
        # Trigger: current close breaks ABOVE the pattern high
        # =====================================================================
        if both_bull:
            # Support proximity: close is at or below EMA_50 OR near BB_lower
            near_support = (c4_close <= ema50) or (c4_close <= bb_lower * 1.003)
            # Alternatively near EMA_200 major support
            near_ema200_support = (c4_close <= ema200 * 1.003) and (c4_close >= ema200 * 0.997)
            at_support = near_support or near_ema200_support

            if at_support and c4_close > pattern_high:
                # Close breaks above the 3-candle swing high → BUY signal
                signal.iloc[i] = 1

        # =====================================================================
        # SELL SIGNAL
        # Pattern: both_bear (momentum down), C3 inside → coil near resistance
        # Location proxy: price ≥ EMA_50 OR near BB_upper (resistance zone)
        # Trigger: current close breaks BELOW the pattern low
        # =====================================================================
        elif both_bear:
            # Resistance proximity: close is at or above EMA_50 OR near BB_upper
            near_resistance = (c4_close >= ema50) or (c4_close >= bb_upper * 0.997)
            near_ema200_resist = (c4_close <= ema200 * 1.003) and (c4_close >= ema200 * 0.997)
            at_resistance = near_resistance or near_ema200_resist

            if at_resistance and c4_close < pattern_low:
                # Close breaks below the 3-candle swing low → SELL signal
                signal.iloc[i] = -1

    return signal

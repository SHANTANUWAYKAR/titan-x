"""
Strategy: Umar Punjabi Gold – London Open ICM/SMC Sweep (UmarPunjabiLive)
=========================================================================
Decoded from UmarPunjabiLive YouTube channel (PDF breakdowns + live sessions).

TRADER BACKGROUND
-----------------
Umar Punjabi is a London-based Gold (XAUUSD) trader who uses Smart Money
Concepts (SMC) / ICM to trade the London Open session.  His edge revolves
around the Asian session range acting as a liquidity pool: smart money sweeps
above/below that range just before London opens, triggering retail stop-losses,
then reverses — a classic "Asia range raid → BOS → entry" workflow.

DECODED RULES
-------------
1. ASSET           : XAUUSD (Gold) primary; can apply to major indices
2. SESSION WINDOWS (UTC) :
   - Asia session  : 00:00 – 06:00 UTC (range-building)
   - London open   : 07:00 – 10:00 UTC (trade window)
3. ASIA RANGE :
   - asia_high : the highest HIGH recorded during 00:00–06:00 UTC
   - asia_low  : the lowest  LOW  recorded during 00:00–06:00 UTC
4. PRE-LONDON SWEEP (liquidity grab, triggers BEFORE/AT London open) :
   - BULLISH setup : price sweeps (wicks or closes) BELOW asia_low during
     the 06:00–08:00 UTC window (just before / just after London open)
   - BEARISH setup : price sweeps ABOVE asia_high in the same window
5. BREAK OF STRUCTURE (BOS) — entry trigger :
   - BULLISH : after a sweep of asia_low, find the most recent swing HIGH
     (20-bar lookback); a 5-min candle that CLOSES ABOVE that swing high
     confirms the BOS → BUY on that candle's close
   - BEARISH : after a sweep of asia_high, find the most recent swing LOW;
     a candle CLOSING BELOW it → SELL
6. CONFIRMATION FILTER : RSI ≥ 45 for BUY, RSI ≤ 55 for SELL (momentum
   not over-extended in the wrong direction)
7. STOP :
   - Beyond the sweep wick: sl = sweep_low − ATR × 0.5  (for BUY)
                             sl = sweep_high + ATR × 0.5 (for SELL)
   - Hard minimum: 7 pips / 70 ticks for Gold (approximated as 0.70 USD)
8. TAKE PROFIT :
   - TP1 = entry + 1 × risk_distance  (close 50 %, move SL to breakeven)
   - TP2 = entry + 2 × risk_distance  (trail remainder)
   (For signal series only direction is returned; TP/SL are per-trade levels)
9. BIAS         : one direction per session; do NOT flip unless the original
                  setup is fully invalidated (price returns into Asia range)
10. ADD-ON      : only after TP1 secured, on a 1-min or 3-min structure retest
11. 4H FIB SETUP (secondary, not in this function):
    The 0.382 Fibonacci retracement on a 4-hour swing aligned with session bias
    provides a secondary entry; this requires 4H data and is out of scope for
    the 5-min / 1-min signal function here.

APPROXIMATIONS
--------------
- Asia range is computed as the rolling HIGH/LOW across the 72 bars before
  each London-session bar (72 × 5 min = 360 min = 6 h) when the index is a
  DatetimeIndex; otherwise a 72-bar rolling window is used as a proxy.
- When a DatetimeIndex is present, an 'hour' filter restricts:
    • Asia-range measurement : hours 0–5
    • London-open trade window: hours 7–9 (inclusive)
  Without a DatetimeIndex these filters are skipped (graceful fallback).
- The "most recent swing high / low" for BOS detection uses a simple
  rolling 20-bar max/min rather than a formal fractal, since no fractals
  column is in the standard df.
- Per-bar RSI is used as the momentum confirmation proxy.
- The "one direction per session" bias is enforced by tracking the current
  day's (or 80-bar window's) first triggered direction and blocking opposite
  signals for the rest of that session.
- Sweep detection: we check whether the candle's LOW wicked below asia_low
  (for bullish) or HIGH wicked above asia_high (for bearish) — a wick sweep
  is more common than a full-candle-body sweep in practice.

USAGE
-----
    signal = strategy_umar_punjabi_gold_london(df)
    # +1 = long, -1 = short, 0 = flat — triggers on 5-min bar CLOSE
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helper: rolling swing high / low for BOS detection
# ---------------------------------------------------------------------------
def _swing_high(series_high: pd.Series, window: int = 20) -> pd.Series:
    """Rolling maximum of 'high' over the past `window` bars (inclusive)."""
    return series_high.rolling(window, min_periods=3).max()


def _swing_low(series_low: pd.Series, window: int = 20) -> pd.Series:
    """Rolling minimum of 'low' over the past `window` bars (inclusive)."""
    return series_low.rolling(window, min_periods=3).min()


# ---------------------------------------------------------------------------
# Helper: build the Asia session high / low series
# ---------------------------------------------------------------------------
def _asia_range(df: pd.DataFrame) -> tuple:
    """
    Return (asia_high, asia_low) as pd.Series aligned to df.index.

    If DatetimeIndex: high/low across 00:00–05:59 UTC, forward-filled for
    the rest of each day (so every bar during the London session knows the
    Asia range for THAT day).

    Fallback: 72-bar rolling high/low (72 × 5 min ≈ 6 h).
    """
    if isinstance(df.index, pd.DatetimeIndex):
        # ----- DatetimeIndex path -----
        # 1. Filter to Asia-session bars only
        asia_mask = df.index.hour < 6   # hours 0, 1, 2, 3, 4, 5

        # 2. Compute daily Asia high / low using groupby on the date component
        dates = df.index.normalize()    # floor to midnight → usable as group key

        # Build series of high/low only during Asia hours; NaN outside
        asia_highs = df["high"].where(asia_mask, other=np.nan)
        asia_lows  = df["low"].where(asia_mask, other=np.nan)

        # 3. Daily aggregate (per calendar date)
        daily_asia_high = asia_highs.groupby(dates).transform("max")
        daily_asia_low  = asia_lows.groupby(dates).transform("min")

        # 4. Forward-fill within each day so London bars inherit the Asia range
        #    (groupby + ffill per group handles the day boundary correctly)
        def _ffill_per_day(s):
            return s.groupby(dates).transform(lambda x: x.ffill())

        asia_high = _ffill_per_day(daily_asia_high)
        asia_low  = _ffill_per_day(daily_asia_low)

    else:
        # ----- Integer-index fallback -----
        # 72 bars × 5 min = 360 min ≈ 6-hour Asia session
        asia_high = df["high"].rolling(72, min_periods=12).max()
        asia_low  = df["low"].rolling(72, min_periods=12).min()

    return asia_high, asia_low


# ---------------------------------------------------------------------------
# Main strategy function
# ---------------------------------------------------------------------------
def strategy_umar_punjabi_gold_london(df: pd.DataFrame) -> pd.Series:
    """
    Umar Punjabi Gold – London Open Asia-Range-Sweep + BOS strategy.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain: open, high, low, close, RSI, ATR
        Optional but used if present: EMA_20, EMA_50

    Returns
    -------
    pd.Series
        +1 (long), -1 (short), 0 (flat) — all signals on candle CLOSE
    """
    # -------------------------------------------------------------------------
    # 0. Column validation
    # -------------------------------------------------------------------------
    required = ["open", "high", "low", "close", "RSI", "ATR"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"strategy_umar_punjabi_gold_london: missing column '{col}'")

    n = len(df)
    signal = pd.Series(0, index=df.index, dtype=int)

    if n < 80:   # need enough bars to build a meaningful Asia range
        return signal

    # -------------------------------------------------------------------------
    # 1. Compute Asia session High / Low for each bar
    # -------------------------------------------------------------------------
    asia_high, asia_low = _asia_range(df)

    # -------------------------------------------------------------------------
    # 2. Detect session hour for London-window filter
    # -------------------------------------------------------------------------
    has_datetime_index = isinstance(df.index, pd.DatetimeIndex)
    if has_datetime_index:
        bar_hour = df.index.hour   # UTC hour of each bar
    else:
        bar_hour = None            # fallback: no session filter possible

    # -------------------------------------------------------------------------
    # 3. Pre-compute rolling swing levels for BOS detection
    # -------------------------------------------------------------------------
    swing_hi_20 = _swing_high(df["high"], window=20)   # 20-bar rolling high (recent swing high)
    swing_lo_20 = _swing_low(df["low"],  window=20)    # 20-bar rolling low  (recent swing low)

    # -------------------------------------------------------------------------
    # 4. State machine: track sweep and BOS per session
    #    State variables (reset each session / day boundary):
    #      swept_low   : True if asia_low was swept this session
    #      swept_high  : True if asia_high was swept this session
    #      sweep_low_price  : the lowest wick during the sweep
    #      sweep_high_price : the highest wick during the sweep
    #      session_bias : +1 / -1 / 0 (one direction per session)
    # -------------------------------------------------------------------------
    swept_low         = False
    swept_high        = False
    sweep_low_price   = np.nan   # the sweep wick low (for stop calculation)
    sweep_high_price  = np.nan   # the sweep wick high
    session_bias      = 0        # tracks the first signal direction this session

    # Track current calendar date for session resets
    prev_date = None

    for i in range(72, n):   # start after enough bars to have a valid Asia range
        c = df["close"].iloc[i]
        h = df["high"].iloc[i]
        l = df["low"].iloc[i]
        rsi = df["RSI"].iloc[i]
        atr = df["ATR"].iloc[i]

        a_hi = asia_high.iloc[i]   # today's Asia session high
        a_lo = asia_low.iloc[i]    # today's Asia session low

        if pd.isna(a_hi) or pd.isna(a_lo) or pd.isna(atr):
            continue

        # ---- Session reset logic ----
        if has_datetime_index:
            cur_date = df.index[i].date()
            cur_hour = bar_hour[i]

            # New calendar day → reset all session state
            if cur_date != prev_date:
                swept_low        = False
                swept_high       = False
                sweep_low_price  = np.nan
                sweep_high_price = np.nan
                session_bias     = 0
                prev_date        = cur_date

            # Only act during London Open window (07:00–09:59 UTC)
            in_london_window = 7 <= cur_hour <= 9
            # The sweep itself can happen in the 06:00–08:00 pre-open window
            in_sweep_window  = 6 <= cur_hour <= 8
        else:
            # No datetime info: treat every bar as potentially in the London window
            in_london_window = True
            in_sweep_window  = True

            # Crude session reset: every 80 bars (≈ 400 min ≈ a session)
            if i % 80 == 0:
                swept_low        = False
                swept_high       = False
                sweep_low_price  = np.nan
                sweep_high_price = np.nan
                session_bias     = 0

        # ----------------------------------------------------------------
        # STEP 1 — DETECT SWEEP of Asia Range
        # ----------------------------------------------------------------
        if in_sweep_window:
            # Bullish sweep: wick dips BELOW asia_low (stop hunt on longs)
            if l < a_lo and not swept_low and session_bias >= 0:
                swept_low       = True
                sweep_low_price = l    # the exact wick low (used for SL later)

            # Bearish sweep: wick spikes ABOVE asia_high (stop hunt on shorts)
            if h > a_hi and not swept_high and session_bias <= 0:
                swept_high       = True
                sweep_high_price = h   # the exact wick high (used for SL later)

        # ----------------------------------------------------------------
        # STEP 2 — DETECT BOS (Break of Structure) → Entry signal
        # Only within the London open trade window
        # Only if the corresponding sweep was detected first
        # ----------------------------------------------------------------
        if not in_london_window:
            continue

        # --- BULLISH BOS (after sweep of Asia Low) ---
        if swept_low and session_bias >= 0:
            recent_swing_hi = swing_hi_20.iloc[i]   # 20-bar rolling swing high

            # BOS trigger: close breaks ABOVE the most recent swing high
            bos_bull = c > recent_swing_hi

            # RSI confirmation: not oversold (momentum supports the move up)
            rsi_ok   = rsi >= 45

            if bos_bull and rsi_ok and not pd.isna(recent_swing_hi):
                # Compute stop distance (min 0.70 USD hard floor for Gold)
                sl_dist = max((c - sweep_low_price) + atr * 0.5, 0.70)

                # Only take the trade if R:R is viable (TP1 = 1× sl_dist above entry)
                # — always true here since TP1 is exactly 1R; check is informational
                signal.iloc[i] = 1
                session_bias   = 1      # lock session direction to bullish only
                swept_low      = False  # consume the sweep; don't double-signal

        # --- BEARISH BOS (after sweep of Asia High) ---
        elif swept_high and session_bias <= 0:
            recent_swing_lo = swing_lo_20.iloc[i]   # 20-bar rolling swing low

            # BOS trigger: close breaks BELOW the most recent swing low
            bos_bear = c < recent_swing_lo

            # RSI confirmation: not overbought (momentum supports the move down)
            rsi_ok   = rsi <= 55

            if bos_bear and rsi_ok and not pd.isna(recent_swing_lo):
                sl_dist = max((sweep_high_price - c) + atr * 0.5, 0.70)

                signal.iloc[i] = -1
                session_bias   = -1     # lock session direction to bearish only
                swept_high     = False  # consume the sweep

    return signal

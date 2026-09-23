"""
Strategy: Gautam Jha Liquidity Breakout (GautamJhaa YouTube)
=============================================================
Decoded from GautamJhaa's YouTube channel / live trading breakdowns.

TRADER BACKGROUND
-----------------
Gautam Jha is an Indian intraday trader who focuses on a "false breakout →
liquidity sweep → reversal" concept.  His primary setup targets the previous
day's High and Low as liquidity pools.  The logic is that large players (smart
money) deliberately push price THROUGH these obvious levels to collect the
stop-loss orders of retail traders, then reverse sharply — giving a clean
high-probability entry in the real direction.

DECODED RULES
-------------
1. TIMEFRAME      : 1-minute bars (equity indices or Nifty; can apply to any
                    liquid futures / FX pair)
2. KEY LEVELS     :
   - prev_day_high (PDH) : previous calendar day's highest close (or high)
   - prev_day_low  (PDL) : previous calendar day's lowest  close (or low)
3. BUY SETUP (sweep of PDL, then reversal UP) :
   a. Price BREAKS BELOW prev_day_low on a candle close
      (liquidity collected below PDL)
   b. Wait for a STRONG GREEN candle that CLOSES BACK ABOVE PDL
      (strong = body_ratio ≥ 0.60, i.e. green candle with conviction)
   c. TRIGGER: the NEXT candle closes ABOVE the high of that strong green candle
   d. Entry on the close of the trigger candle
   e. Stop Loss  : below the low  of the strong green candle (per-trade)
   f. Target     : nearest previous swing high (external; R:R ≥ 1.5 recommended)
4. SELL SETUP (sweep of PDH, then reversal DOWN) :
   a. Price BREAKS ABOVE prev_day_high on a candle close
   b. Wait for a STRONG RED candle that CLOSES BACK BELOW PDH
      (strong = body_ratio ≥ 0.60)
   c. TRIGGER: the NEXT candle closes BELOW the low of that strong red candle
   d. Entry on the close of the trigger candle
   e. Stop Loss  : above the high of the strong red candle (per-trade)
   f. Target     : nearest previous swing low (external)
5. LIQUIDITY GRAB ENHANCEMENT (Trend-pullback version) :
   - In an UPTREND (close > EMA_20 > EMA_50) look for a red candle;
     mark its low as a "liquidity pool"
   - When price later sweeps that low AND a strong green candle closes ABOVE it,
     treat this as a BUY signal (same trigger logic as rule 3c above)
   - Proxy for "in uptrend": close > EMA_20 and EMA_20 > EMA_50
6. RISK              : 1–2 % of account per trade (sizing external)
7. STATE MACHINE     : once a sweep is detected, the strategy enters a
                       "waiting" state for the confirmation candle.
                       State resets at the next sweep of the opposite level.

APPROXIMATIONS
--------------
- prev_day_high / prev_day_low : these should ideally be the actual prior
  calendar day's H/L.  Since exact session boundaries are not guaranteed in
  `df`, we proxy them as:
    • If df.index is a DatetimeIndex: group by calendar date and compute the
      prior day's high/low using a shifted daily resample.
    • Otherwise (plain integer index): use a 390-bar rolling max/min
      (390 ≈ minutes in a US equity session) as an approximation of the
      previous day's range.
- The "strong" candle body_ratio threshold is set at 0.60 rather than Gautam's
  informal "big/strong" visual judgment — this is a reasonable quantification.
- Per-trade SL/TP calculation is noted in the signal metadata comments but the
  returned series contains only the direction (1 / -1 / 0).
- The liquidity-grab enhancement looks back only 20 bars for the reference
  red candle low (to avoid stale pools from much earlier in the day).
- One signal per sweep event: after a BUY or SELL fires, the state resets so
  the same sweep cannot generate duplicate signals.

USAGE
-----
    signal = strategy_gautam_jha_liquidity_breakout(df)
    # +1 = long, -1 = short, 0 = flat; triggers on bar CLOSE
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Internal helper: body ratio
# ---------------------------------------------------------------------------
def _body_ratio(o: pd.Series, h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    """Absolute body as a fraction of full candle range; NaN on zero-range bars."""
    rng  = h - l
    body = (c - o).abs()
    return body.where(rng > 0, other=np.nan) / rng.where(rng > 0, other=np.nan)


# ---------------------------------------------------------------------------
# Helper: derive prev-day High / Low
# ---------------------------------------------------------------------------
def _prev_day_levels(df: pd.DataFrame) -> tuple:
    """
    Return (pdh, pdl) as pd.Series aligned to df.index.

    Strategy:
      - DatetimeIndex  → resample by calendar date, shift(1) to get PRIOR day's
        H/L, then forward-fill within each day (so every 1-min bar knows PDH/PDL)
      - Integer index  → rolling 390-bar high/low (≈ one US session)
    """
    if isinstance(df.index, pd.DatetimeIndex):
        # daily high / low per calendar day
        daily_high = df["high"].resample("D").max()
        daily_low  = df["low"].resample("D").min()
        # shift 1 day → each day now holds PRIOR day's values
        pdh_daily = daily_high.shift(1)
        pdl_daily = daily_low.shift(1)
        # reindex back to the 1-min bar frequency, forward-fill within each day
        pdh = pdh_daily.reindex(df.index, method="ffill")
        pdl = pdl_daily.reindex(df.index, method="ffill")
    else:
        # fallback: 390-bar rolling window ≈ previous session's H/L
        pdh = df["high"].rolling(390, min_periods=30).max().shift(1)
        pdl = df["low"].rolling(390, min_periods=30).min().shift(1)
    return pdh, pdl


# ---------------------------------------------------------------------------
# Main strategy function
# ---------------------------------------------------------------------------
def strategy_gautam_jha_liquidity_breakout(df: pd.DataFrame) -> pd.Series:
    """
    Gautam Jha Liquidity Breakout / Sweep-and-Reverse strategy.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain: open, high, low, close, EMA_20, EMA_50

    Returns
    -------
    pd.Series
        +1 (long), -1 (short), 0 (flat) — triggers on candle CLOSE, no repaint
    """
    # -------------------------------------------------------------------------
    # 0. Column validation
    # -------------------------------------------------------------------------
    required = ["open", "high", "low", "close", "EMA_20", "EMA_50"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"strategy_gautam_jha_liquidity_breakout: missing '{col}'")

    n = len(df)
    signal = pd.Series(0, index=df.index, dtype=int)

    if n < 10:
        return signal

    # -------------------------------------------------------------------------
    # 1. Compute prev-day High / Low
    # -------------------------------------------------------------------------
    pdh, pdl = _prev_day_levels(df)

    # -------------------------------------------------------------------------
    # 2. Pre-compute body ratios and candle direction
    # -------------------------------------------------------------------------
    br      = _body_ratio(df["open"], df["high"], df["low"], df["close"]).fillna(0.0)
    is_green = df["close"] > df["open"]   # bullish candle
    is_red   = df["close"] < df["open"]   # bearish candle

    # -------------------------------------------------------------------------
    # 3. State machine (stateful per-row loop)
    #    States:
    #      "idle"        : scanning for a sweep of PDH or PDL
    #      "wait_buy"    : PDL was swept; looking for a strong green candle
    #      "wait_sell"   : PDH was swept; looking for a strong red candle
    #      "confirm_buy" : strong green found; next bar close above its high → BUY
    #      "confirm_sell": strong red  found; next bar close below its low  → SELL
    # -------------------------------------------------------------------------
    state         = "idle"
    anchor_high   = np.nan   # high of the strong confirmation candle
    anchor_low    = np.nan   # low  of the strong confirmation candle

    # For liquidity-grab enhancement: track the most recent red candle in uptrend
    liq_grab_red_low  = np.nan   # low of the reference red candle
    liq_grab_lookback = 20       # only look back this many bars for the red candle

    for i in range(3, n):
        c = df["close"].iloc[i]
        h = df["high"].iloc[i]
        l = df["low"].iloc[i]
        cur_pdh = pdh.iloc[i]
        cur_pdl = pdl.iloc[i]

        # Skip bars where PDH/PDL are not yet available (first day)
        if pd.isna(cur_pdh) or pd.isna(cur_pdl):
            continue

        # -------------------------------------------------------------------
        # STATE: idle — check for sweeps of PDH or PDL
        # -------------------------------------------------------------------
        if state == "idle":
            # BUY sweep: close BELOW prev day low (retail stops collected)
            if c < cur_pdl:
                state = "wait_buy"

            # SELL sweep: close ABOVE prev day high
            elif c > cur_pdh:
                state = "wait_sell"

        # -------------------------------------------------------------------
        # STATE: wait_buy — looking for strong green reversal candle
        # -------------------------------------------------------------------
        elif state == "wait_buy":
            # If price now sweeps PDH instead, abandon and flip to sell watch
            if c > cur_pdh:
                state = "wait_sell"
                continue

            # Strong green candle that closes back ABOVE PDL (real reversal)
            if is_green.iloc[i] and br.iloc[i] >= 0.60 and c > cur_pdl:
                # This is the anchor candle; store its high/low
                anchor_high = h    # breakout trigger is above THIS high
                anchor_low  = l    # stop loss would be below THIS low
                state = "confirm_buy"

        # -------------------------------------------------------------------
        # STATE: confirm_buy — trigger fires when next bar closes above anchor_high
        # -------------------------------------------------------------------
        elif state == "confirm_buy":
            if c > anchor_high:
                # Close above the strong green candle high → BUY signal
                signal.iloc[i] = 1
                state = "idle"     # reset; one trade per sweep event
                anchor_high = np.nan
                anchor_low  = np.nan
            else:
                # Trigger failed (price stalled); reset state to avoid stale signal
                state = "idle"
                anchor_high = np.nan
                anchor_low  = np.nan

        # -------------------------------------------------------------------
        # STATE: wait_sell — looking for strong red reversal candle
        # -------------------------------------------------------------------
        elif state == "wait_sell":
            # If price now sweeps PDL instead, abandon and flip to buy watch
            if c < cur_pdl:
                state = "wait_buy"
                continue

            # Strong red candle that closes back BELOW PDH (real reversal)
            if is_red.iloc[i] and br.iloc[i] >= 0.60 and c < cur_pdh:
                anchor_high = h    # stop loss would be above THIS high
                anchor_low  = l    # breakout trigger is below THIS low
                state = "confirm_sell"

        # -------------------------------------------------------------------
        # STATE: confirm_sell — trigger fires when next bar closes below anchor_low
        # -------------------------------------------------------------------
        elif state == "confirm_sell":
            if c < anchor_low:
                # Close below the strong red candle low → SELL signal
                signal.iloc[i] = -1
                state = "idle"
                anchor_high = np.nan
                anchor_low  = np.nan
            else:
                state = "idle"
                anchor_high = np.nan
                anchor_low  = np.nan

        # -------------------------------------------------------------------
        # LIQUIDITY GRAB ENHANCEMENT (in parallel with the state machine above)
        # Uptrend context: close > EMA_20 > EMA_50
        # Look for a red candle, store its low; if price later sweeps below and
        # a strong green closes above → buy signal
        # -------------------------------------------------------------------
        if signal.iloc[i] == 0:   # only generate liq-grab signal if no primary signal yet
            ema20 = df["EMA_20"].iloc[i]
            ema50 = df["EMA_50"].iloc[i]

            in_uptrend = (c > ema20) and (ema20 > ema50)   # price above both EMAs, EMAs stacked

            if in_uptrend:
                if is_red.iloc[i]:
                    # Record this red candle's low as a liquidity pool in uptrend
                    liq_grab_red_low = l

                elif not pd.isna(liq_grab_red_low) and i > liq_grab_lookback:
                    # Check if we recently swept below the recorded red candle low
                    lows_window = df["low"].iloc[i - liq_grab_lookback : i + 1]
                    swept_below = (lows_window < liq_grab_red_low).any()  # sweep occurred

                    if swept_below and is_green.iloc[i] and br.iloc[i] >= 0.60 and c > liq_grab_red_low:
                        # Strong green close back ABOVE the liquidity pool → BUY
                        signal.iloc[i] = 1
                        liq_grab_red_low = np.nan   # reset pool after use
            else:
                # No longer in uptrend; discard stale liquidity pool
                liq_grab_red_low = np.nan

    return signal

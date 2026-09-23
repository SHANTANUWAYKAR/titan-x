"""
Module: smc_sniper.py
Description: Port of the profittown-sniper-smc entry model
    (https://github.com/manuelinfosec/profittown-sniper-smc, cloned
    read-only for reference; sources: backtest.py, shared/rules/
    structure.py, ob_filters.py, liquidity.py, fibonacci.py).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-08-21
"""

import numpy as np
import pandas as pd


def smc_bos_ob_confluence(
    enriched: pd.DataFrame,
    bos_lookback: int = 20,
    ob_search: int = 20,
    min_score: int = 3,
    rr_target: float = 3.0,
    fib_window: int = 100,
) -> pd.Series:
    """profittown-sniper-smc's full entry model, walked forward bar by bar:

    1. BOS (structure.py detect_bos): current close beyond the prior
       `bos_lookback`-bar extreme (window excludes the current bar).
    2. Order block (ob_filters.py find_order_block): the LAST opposing
       candle (bearish candle for a bullish BOS, bullish for bearish)
       within the last `ob_search` bars before the breakout bar.
    3. Confluence score, >= `min_score` of 4 to enter (backtest.py's own
       "score >= 3" acceptance threshold):
       a. liquidity sweep just before the OB (liquidity.py),
       b. OB inside the 61.8%-78.6% fib retracement zone (fibonacci.py),
       c. FVG/imbalance around the OB = "clean structure" (structure.py
          check_clean_structure),
       d. impulse from the OB actually broke the BOS level (ob_filters.py
          check_impulse_from_ob).
    4. Entry in the BOS direction; stop at the OB's far edge; target at
       `rr_target` R (backtest.py's 3R).

    Honest adaptations + source bugs found during the port (fixed here,
    documented, never silently copied):
    - SOURCE BUG: liquidity.py's check_liquidity_sweep includes the sweep
      candle itself in the 10-bar window it takes the swing low/high from,
      so `sweep_low < min(lows incl. itself)` can never be true -- the
      check ALWAYS returns False in the original repo. Ported as clearly
      intended: the candle just before the OB must wick beyond the extreme
      of the bars before IT (itself excluded).
    - The source's fib zone uses the WHOLE loaded dataframe's high/low
      (df['high'].max() over all history) -- meaningless in a 10-year
      walk-forward. Bounded here to the trailing `fib_window` bars.
    - check_impulse_from_ob is trivially true at the BOS bar itself (the
      breaking close IS the impulse), kept for score parity with the
      source's own 4-check scale.
    - Entries/exits are close-based (entry at the signal bar's close, SL/
      TP evaluated on closes), the same simplification E26 applies to
      every strategy in this library -- the source used limit fills at the
      OB edge with intrabar SL/TP, which this platform's series model
      cannot represent.
    """
    n = len(enriched)
    highs = enriched["high"].to_numpy(dtype=float)
    lows = enriched["low"].to_numpy(dtype=float)
    closes = enriched["close"].to_numpy(dtype=float)
    opens = enriched["open"].to_numpy(dtype=float)

    signal = np.zeros(n, dtype=int)
    position = 0
    sl = tp = 0.0
    start = max(bos_lookback, fib_window) + 1

    for i in range(start, n):
        if position != 0:
            c = closes[i]
            if position == 1 and (c <= sl or c >= tp):
                position = 0
            elif position == -1 and (c >= sl or c <= tp):
                position = 0
            signal[i] = position
            if position != 0:
                continue

        # 1. BOS on the prior `bos_lookback` bars, current bar excluded.
        swing_high = highs[i - bos_lookback:i].max()
        swing_low = lows[i - bos_lookback:i].min()
        c = closes[i]
        if c > swing_high:
            direction = 1
        elif c < swing_low:
            direction = -1
        else:
            continue
        bos_level = swing_high if direction == 1 else swing_low

        # 2. Last opposing candle in the `ob_search` bars before this one.
        ob_idx = -1
        for j in range(i - 1, max(i - 1 - ob_search, 0), -1):
            if direction == 1 and closes[j] < opens[j]:
                ob_idx = j
                break
            if direction == -1 and closes[j] > opens[j]:
                ob_idx = j
                break
        if ob_idx <= 1:
            continue
        ob_high, ob_low = highs[ob_idx], lows[ob_idx]

        # 3a. Liquidity sweep just before the OB (source bug fixed: the
        # sweep candle is excluded from the window it must wick beyond).
        sw_start = max(0, ob_idx - 10)
        sweep = False
        if ob_idx - 1 > sw_start:
            if direction == 1:
                sweep = lows[ob_idx - 1] < lows[sw_start:ob_idx - 1].min()
            else:
                sweep = highs[ob_idx - 1] > highs[sw_start:ob_idx - 1].max()

        # 3b. OB in the 61.8-78.6% fib zone of the trailing window's swing.
        w_high = highs[i - fib_window:i + 1].max()
        w_low = lows[i - fib_window:i + 1].min()
        rng = w_high - w_low
        if rng <= 0:
            continue
        if direction == 1:
            fib_ok = (w_high - rng * 0.786) <= ob_high <= (w_high - rng * 0.618)
        else:
            fib_ok = (w_low + rng * 0.618) <= ob_low <= (w_low + rng * 0.786)

        # 3c. FVG/imbalance around the OB ("clean structure").
        fvg_ok = False
        if ob_idx + 1 <= i:
            fvg_ok = (lows[ob_idx + 1] > highs[ob_idx - 1]) or (highs[ob_idx + 1] < lows[ob_idx - 1])

        # 3d. Impulse from the OB broke the BOS level (close-based).
        post = closes[ob_idx + 1:i + 1]
        impulse_ok = bool(post.max() > bos_level) if direction == 1 else bool(post.min() < bos_level)

        # int() casts matter: sweep/fib_ok/fvg_ok are np.bool_, and numpy
        # boolean "+" is logical OR, not integer addition -- summing them
        # raw caps the score at 1 and the threshold could never pass.
        score = int(sweep) + int(fib_ok) + int(fvg_ok) + int(impulse_ok)
        if score >= min_score:
            position = direction
            if direction == 1:
                sl = ob_low
                tp = c + (c - sl) * rr_target
            else:
                sl = ob_high
                tp = c - (sl - c) * rr_target
            if (direction == 1 and sl >= c) or (direction == -1 and sl <= c):
                position = 0  # degenerate OB (stop on the wrong side of entry)
            signal[i] = position

    return pd.Series(signal, index=enriched.index)

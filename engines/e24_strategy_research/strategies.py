"""
Module: strategies.py
Description: Strategy signal-series library for e24_strategy_research.
    Ported verbatim from scripts/training/research_signal_strategies.py
    (the v1-v5 one-off research scripts this engine formalizes) -- same
    functions, same no-lookahead guarantees, now owned by an engine instead
    of copy-pasted into each new hand-written research script. The original
    scripts are left untouched (they already produced real, reported
    historical results -- see data/models/e51_signals/strategy_research_
    report*.json); this is the reusable path for research GOING FORWARD.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-19
"""

from typing import Callable

import numpy as np
import pandas as pd

from project_titan_x.engines.e07_technical.wyckoff import detect_springs_and_upthrusts, detect_trading_range
from project_titan_x.engines.e07_technical.smart_money import market_structure_shift
from project_titan_x.engines.e07_technical.order_flow import compute_cumulative_delta
from project_titan_x.engines.e07_technical.volume_profile import compute_volume_profile


def session_mask(df: pd.DataFrame, start: str, end: str, tz: str = "Asia/Kolkata") -> pd.Series:
    """Boolean mask, True for bars whose LOCAL time-of-day (in `tz`) falls
    within [start, end) -- e.g. session_mask(df, "06:30", "09:30") for a
    trader whose actual trading window is 6:30-9:30 IST. `df["timestamp"]`
    must be tz-aware (e02_market_data.fetch_ohlcv always returns UTC-aware
    timestamps); converted to `tz` here, not assumed already local."""
    local = df["timestamp"].dt.tz_convert(tz)
    start_t = pd.to_datetime(start).time()
    end_t = pd.to_datetime(end).time()
    local_time = local.dt.time
    return pd.Series((local_time >= start_t) & (local_time < end_t), index=df.index)


def apply_session_filter(signal: pd.Series, mask: pd.Series) -> pd.Series:
    """Force `signal` to 0 (flat) on every bar outside `mask` -- i.e. only
    allow this strategy to be in a position during the trader's actual
    session. A position open going into the session boundary is
    automatically closed the moment the mask goes False (signal forced to
    0), not carried overnight/cross-session. Session bars keep the
    underlying strategy's own signal unchanged."""
    out = signal.copy()
    out[~mask] = 0
    return out


def _stateful_from_entries_exits(
    entry_long: pd.Series, exit_long: pd.Series,
    entry_short: pd.Series, exit_short: pd.Series,
) -> pd.Series:
    """Build a persistent position series (hold until an explicit exit
    condition) via forward-fill -- ffill only ever looks backward in time,
    so this introduces no lookahead.

    Real bug found and fixed 2026-08-21: entries must be assigned AFTER
    exits, not before. exit_long/exit_short are raw price-condition masks
    (true for every bar price remains beyond that channel/threshold, not
    just the transition bar) -- they don't know whether a long/short
    position is actually open, so exit_long can be simultaneously True
    with entry_short on the exact SAME bar. For every donchian-family
    strategy in this module using entry_n > exit_n (the standard, almost
    universally used parameterization -- e.g. SP500's real live-shipped
    override, entry_n=15/exit_n=7), this is not a rare edge case: since
    the exit channel is a SUBSET of the entry channel's lookback window,
    exit_low >= entry_low ALWAYS (a subset's min can never be lower than
    the full set's), meaning close < entry_low (a fresh short breakout)
    mathematically GUARANTEES close < exit_low (a simultaneous "exit
    long" reading) on that exact bar, every single time. Same mechanism
    hits rsi_mean_reversion's short side too (overbought=70 vs
    exit_level=50 -- rsi>70 always implies rsi>50).

    Under the OLD order (entry_short, exit_short, entry_long, exit_long
    -- exits-that-conflict-with-entries applied LAST), exit_long silently
    overwrote entry_short back to 0 on literally every short-breakout
    bar, and the mirror-image conflict (entry_long vs exit_short) just
    happened to resolve correctly by accident (entry_long was already
    last among ITS conflicts). Net effect, confirmed live: donchian_
    breakout produced ZERO short trades on a real, clean 500-bar
    downtrend (should have been overwhelmingly short) while working
    fine on an uptrend -- silently long-only in practice for its entire
    history (this helper's own docstring already says it was "ported
    verbatim from scripts/training/research_signal_strategies.py", so
    this predates this engine and likely predates this whole project's
    donchian research). Fixed by assigning exits first, entries last --
    a fresh, real entry signal now always wins over a stale/coincidental
    exit reading of the OPPOSITE side's channel on the same bar; a
    genuine exit with no coinciding new entry is completely unaffected
    (unconditionally correct, ordering can't have written self-then-
    self).

    SECOND real bug found and fixed 2026-08-22 -- the ordering fix above
    was necessary but not sufficient, because the underlying approach was
    unsound: a forward-filled mask assignment has NO IDEA WHICH SIDE IS
    OPEN, so an exit mask meant for one direction silently closed the
    other. exit_short is "rsi < exit_level" / "close > exit_high" -- raw
    price conditions that are True across most of the region where a LONG
    is supposed to be held. Result: raw[exit_short]=0 closed longs the
    instant price left the long entry zone, long before exit_long could
    fire.

    Demonstrated concretely on rsi_mean_reversion(oversold=30,
    exit_level=65) over an RSI ramp 20->80: the long entered below 30 and
    was killed at RSI 30.8 by exit_short (30.8 < 65), never surviving to
    its own exit at RSI > 65. The visible symptom was that `exit_level`
    became a DEAD PARAMETER -- sweeping it 35/40/45/50/55/60/65/70 on real
    ETHUSD 1d data produced byte-identical metrics (168 trades, 58.3% win
    rate) for every value, because the long's real exit was always
    exit_short, which no exit_level choice can move.

    Fixed by tracking actual position state: an exit condition is only
    ever consulted for the side that is genuinely open, and a fresh
    opposite entry still flips the position directly (preserving the
    intent of the ordering fix above). This is an explicit loop rather
    than vectorised ffill because the correct semantics are inherently
    sequential -- whether bar i exits depends on what position bar i-1
    left open, which no amount of mask ordering can express."""
    el = entry_long.to_numpy(dtype=bool); xl = exit_long.to_numpy(dtype=bool)
    es = entry_short.to_numpy(dtype=bool); xs = exit_short.to_numpy(dtype=bool)

    out = np.zeros(len(el), dtype=np.int8)
    pos = 0
    for i in range(len(el)):
        if pos == 1:
            # Only the LONG's own exit can close a long. A fresh short
            # entry still flips directly (never via the long sitting on a
            # coincidental exit_short reading).
            if es[i]:
                pos = -1
            elif xl[i]:
                pos = 0
        elif pos == -1:
            if el[i]:
                pos = 1
            elif xs[i]:
                pos = 0
        if pos == 0:
            # Flat: a genuine entry opens a position. Longs win a
            # simultaneous long+short reading, matching the previous
            # ordering (entries assigned last, entry_long last of all).
            if el[i]:
                pos = 1
            elif es[i]:
                pos = -1
        out[i] = pos
    return pd.Series(out, index=entry_long.index, dtype=int)


def baseline_trend(enriched: pd.DataFrame) -> pd.Series:
    """The shipped e51_signals composite rule -- included for a direct,
    like-for-like comparison against every alternative below."""
    ema_bullish = (enriched["ema_8"] > enriched["ema_21"]) & (enriched["ema_21"] > enriched["ema_50"])
    ema_bearish = (enriched["ema_8"] < enriched["ema_21"]) & (enriched["ema_21"] < enriched["ema_50"])
    adx_strong = enriched["adx"].fillna(0) > 25.0

    trend_score = pd.Series(0.0, index=enriched.index)
    trend_score[ema_bullish & adx_strong] = 30.0
    trend_score[ema_bearish & adx_strong] = -30.0
    rsi_score = (enriched["rsi"].fillna(50) - 50) * 0.5
    macd_score = np.where(enriched["macd_hist"].fillna(0) > 0, 15.0, -15.0)
    ema50_ref = enriched["ema_50"].fillna(enriched["close"])
    ema50_score = np.where(enriched["close"] > ema50_ref, 10.0, -10.0)
    score = (trend_score + rsi_score + macd_score + ema50_score).clip(-100, 100)

    signal = pd.Series(0, index=enriched.index)
    signal[(ema_bullish & adx_strong) & (score >= 25.0)] = 1
    signal[(ema_bearish & adx_strong) & (score <= -25.0)] = -1
    return signal


def ma_cross_50_200(enriched: pd.DataFrame) -> pd.Series:
    """Classic golden/death cross."""
    signal = pd.Series(0, index=enriched.index)
    signal[enriched["ema_50"] > enriched["ema_200"]] = 1
    signal[enriched["ema_50"] < enriched["ema_200"]] = -1
    return signal


def macd_cross(enriched: pd.DataFrame) -> pd.Series:
    """Pure MACD line/signal crossover, no EMA-stack or ADX filter."""
    signal = pd.Series(0, index=enriched.index)
    signal[enriched["macd"] > enriched["macd_signal"]] = 1
    signal[enriched["macd"] < enriched["macd_signal"]] = -1
    return signal


def donchian_breakout(enriched: pd.DataFrame, entry_n: int = 20, exit_n: int = 10) -> pd.Series:
    """Turtle-style channel breakout: enter long on a new `entry_n`-bar
    high, exit on a new `exit_n`-bar low (mirrored for shorts). `.shift(1)`
    on the rolling window excludes the current bar -- no lookahead."""
    entry_high = enriched["high"].shift(1).rolling(entry_n).max()
    entry_low = enriched["low"].shift(1).rolling(entry_n).min()
    exit_high = enriched["high"].shift(1).rolling(exit_n).max()
    exit_low = enriched["low"].shift(1).rolling(exit_n).min()

    entry_long = enriched["close"] > entry_high
    entry_short = enriched["close"] < entry_low
    exit_long = enriched["close"] < exit_low
    exit_short = enriched["close"] > exit_high
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def donchian_atr_trail(enriched: pd.DataFrame, entry_n: int = 20, atr_mult: float = 2.0) -> pd.Series:
    """Turtle-style channel-breakout ENTRY (same as donchian_breakout),
    but a volatility (ATR) trailing stop EXIT instead of a fixed exit
    channel -- directly sourced from this platform's own book corpus
    (e01_knowledge): "stop placement is an art... consider using a
    volatility stop," and the classic trend-following critique that a
    fixed-bar exit gives back a constant fraction of profit regardless of
    how much the market has actually moved in your favor, where an ATR
    trail tightens automatically as the trend matures. Long: exit when
    close drops more than `atr_mult` x ATR below the highest close seen
    since entry (mirrored for shorts). Implemented as an explicit loop
    (not vectorized) -- correctness/clarity over speed here, same
    convention e26_backtesting's own core _simulate already uses, and
    this is a grid-search research tool, not a hot path. No lookahead:
    entry_high/entry_low are already shifted by one bar, ATR is a
    backward-looking rolling mean, and the trailing extreme only ever
    incorporates bars up to and including the current one."""
    entry_high = enriched["high"].shift(1).rolling(entry_n).max()
    entry_low = enriched["low"].shift(1).rolling(entry_n).min()
    close = enriched["close"]
    atr = enriched["atr"]

    signal = pd.Series(0, index=enriched.index)
    position = 0
    trail_extreme = 0.0
    for i in range(len(enriched)):
        c = close.iloc[i]
        a = atr.iloc[i]
        eh = entry_high.iloc[i]
        el = entry_low.iloc[i]
        if position == 0:
            if pd.notna(eh) and c > eh:
                position, trail_extreme = 1, c
            elif pd.notna(el) and c < el:
                position, trail_extreme = -1, c
        elif position == 1:
            trail_extreme = max(trail_extreme, c)
            if pd.notna(a) and c < trail_extreme - atr_mult * a:
                position, trail_extreme = 0, 0.0
        elif position == -1:
            trail_extreme = min(trail_extreme, c)
            if pd.notna(a) and c > trail_extreme + atr_mult * a:
                position, trail_extreme = 0, 0.0
        signal.iloc[i] = position
    return signal


def donchian_breakout_volume_confirmed(
    enriched: pd.DataFrame, entry_n: int = 20, exit_n: int = 10, volume_mult: float = 1.5
) -> pd.Series:
    """donchian_breakout, but a breakout only counts as a real entry when
    it's accompanied by above-average participation (volume > `volume_mult`
    x its own `entry_n`-bar trailing average) -- sourced from this
    platform's book corpus's own breakout-volume performance tables.
    Filters out thin, low-conviction breakouts that are more likely to be
    noise/false starts than genuine trend initiations. `.shift(1)` on the
    volume average excludes the current bar, same no-lookahead discipline
    as the price channels themselves."""
    entry_high = enriched["high"].shift(1).rolling(entry_n).max()
    entry_low = enriched["low"].shift(1).rolling(entry_n).min()
    exit_high = enriched["high"].shift(1).rolling(exit_n).max()
    exit_low = enriched["low"].shift(1).rolling(exit_n).min()
    vol_avg = enriched["volume"].shift(1).rolling(entry_n).mean()
    volume_confirmed = enriched["volume"] > vol_avg * volume_mult

    entry_long = (enriched["close"] > entry_high) & volume_confirmed
    entry_short = (enriched["close"] < entry_low) & volume_confirmed
    exit_long = enriched["close"] < exit_low
    exit_short = enriched["close"] > exit_high
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def donchian_breakout_volatility_confirmed(
    enriched: pd.DataFrame, entry_n: int = 20, exit_n: int = 10, atr_expansion_mult: float = 1.0
) -> pd.Series:
    """donchian_breakout, but a breakout only counts as a real entry when
    ATR is currently ABOVE its own `entry_n`-bar trailing average (i.e.
    volatility is expanding, not contracting) -- sourced from this
    platform's book corpus's discussion of volatility clustering
    ("periods of high volatility tend to be followed by more high
    volatility... particularly important in quantitative trading").
    A breakout during volatility expansion is a more plausible genuine
    trend start than one during a quiet, contracting-volatility
    stretch. `.shift(1)` on the ATR average excludes the current bar."""
    entry_high = enriched["high"].shift(1).rolling(entry_n).max()
    entry_low = enriched["low"].shift(1).rolling(entry_n).min()
    exit_high = enriched["high"].shift(1).rolling(exit_n).max()
    exit_low = enriched["low"].shift(1).rolling(exit_n).min()
    atr_avg = enriched["atr"].shift(1).rolling(entry_n).mean()
    vol_expanding = enriched["atr"] > atr_avg * atr_expansion_mult

    entry_long = (enriched["close"] > entry_high) & vol_expanding
    entry_short = (enriched["close"] < entry_low) & vol_expanding
    exit_long = enriched["close"] < exit_low
    exit_short = enriched["close"] > exit_high
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def donchian_breakout_buffer_confirmed(
    enriched: pd.DataFrame,
    entry_n: int = 20,
    exit_n: int = 10,
    atr_buffer_mult: float = 0.1,
    min_body_pct: float = 0.2,
) -> pd.Series:
    """donchian_breakout, but a breakout only counts as a real entry when
    TWO extra conditions both hold, sourced directly from
    timoanttila/turtle-trading's real Pine Script implementation (fetched
    and read, "Daddy's Turtle Strategy" -- a different, distinct filter
    concept from this module's own volume/volatility confirmation
    variants above, not a duplicate):

    1. Buffer past the level: close must clear the `entry_n`-bar high/low
       by an ATR-scaled margin (`atr_buffer_mult` x ATR), not just barely
       poke through it -- reduces the classic false-breakout whipsaw
       where price ticks one cent past a level and immediately reverses.
    2. Candle-body quality: the breakout candle's real body (|close-open|)
       must be at least `min_body_pct` of its full high-low range --
       rejects weak, indecisive candles (small bodies, long wicks) that
       technically closed past the level but show little real
       directional conviction.

    `.shift(1)` on both rolling channels excludes the current bar, same
    no-lookahead discipline as every other donchian variant here."""
    entry_high = enriched["high"].shift(1).rolling(entry_n).max()
    entry_low = enriched["low"].shift(1).rolling(entry_n).min()
    exit_high = enriched["high"].shift(1).rolling(exit_n).max()
    exit_low = enriched["low"].shift(1).rolling(exit_n).min()
    atr_buffer = enriched["atr"] * atr_buffer_mult

    candle_range = enriched["high"] - enriched["low"]
    body = (enriched["close"] - enriched["open"]).abs()
    strong_body = body >= (candle_range * min_body_pct).where(candle_range > 0, 0.0)

    entry_long = (enriched["close"] > entry_high + atr_buffer) & strong_body
    entry_short = (enriched["close"] < entry_low - atr_buffer) & strong_body
    exit_long = enriched["close"] < exit_low
    exit_short = enriched["close"] > exit_high
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def rsi_mean_reversion(
    enriched: pd.DataFrame, oversold: float = 30.0, overbought: float = 70.0, exit_level: float = 50.0
) -> pd.Series:
    """Contrarian: buy oversold, sell overbought, exit back at `exit_level`
    (default 50, the midline -- preserves the original hardcoded exit
    exactly for every existing caller that doesn't pass exit_level).
    A tighter exit (e.g. 40/60 instead of 50) takes profit sooner --
    typically raises win rate at the cost of average win size, the classic
    mean-reversion trade-off; this parameter exists specifically to search
    that trade-off, not to weaken the strategy's own logic."""
    rsi = enriched["rsi"].fillna(50)
    entry_long = rsi < oversold
    exit_long = rsi > exit_level
    entry_short = rsi > overbought
    exit_short = rsi < exit_level
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def bollinger_reversion(enriched: pd.DataFrame) -> pd.Series:
    """Contrarian: buy at lower-band touch, sell at upper-band touch, exit
    at the middle band (20-period SMA)."""
    entry_long = enriched["close"] <= enriched["bb_lower"]
    exit_long = enriched["close"] >= enriched["bb_middle"]
    entry_short = enriched["close"] >= enriched["bb_upper"]
    exit_short = enriched["close"] <= enriched["bb_middle"]
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def bollinger_reversion_tuned(enriched: pd.DataFrame, period: int = 20, std_mult: float = 2.0) -> pd.Series:
    """Same contrarian logic as bollinger_reversion, but with a genuinely
    tunable band (period, std_mult) instead of e07_technical's fixed
    20-period/2.0-std columns -- computed directly from `close` so it's an
    independent search dimension. A tighter band (lower std_mult) touches
    more often (more trades, typically lower win rate); a wider one
    touches rarely but each touch is a more extreme/reliable reversion
    setup (fewer trades, typically higher win rate) -- the same frequency/
    win-rate trade-off rsi_mean_reversion's exit_level searches, from a
    different angle."""
    sma = enriched["close"].rolling(period).mean()
    std = enriched["close"].rolling(period).std()
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    entry_long = enriched["close"] <= lower
    exit_long = enriched["close"] >= sma
    entry_short = enriched["close"] >= upper
    exit_short = enriched["close"] <= sma
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def rsi_mean_reversion_trend_filtered(
    enriched: pd.DataFrame, oversold: float = 30.0, overbought: float = 70.0, exit_level: float = 50.0
) -> pd.Series:
    """Classic "buy the dip in an uptrend / sell the rip in a downtrend":
    same RSI contrarian entries as rsi_mean_reversion, but LONG entries
    only fire above the 200-day EMA and SHORT entries only fire below it
    -- a well-established technique for improving a mean-reversion
    system's win rate by not fighting the dominant trend (fighting a
    strong trend is the classic way a mean-reversion system loses big on
    its rare losers). ema_200 is already computed by e07_technical, not
    re-derived here."""
    rsi = enriched["rsi"].fillna(50)
    uptrend = enriched["close"] > enriched["ema_200"].fillna(enriched["close"])
    downtrend = enriched["close"] < enriched["ema_200"].fillna(enriched["close"])
    entry_long = (rsi < oversold) & uptrend
    exit_long = rsi > exit_level
    entry_short = (rsi > overbought) & downtrend
    exit_short = rsi < exit_level
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def wyckoff_spring_reversal(
    enriched: pd.DataFrame, lookback: int = 50, atr_period: int = 14,
    max_atr_multiple: float = 6.0, grace_bars_after_range: int = 10,
) -> pd.Series:
    """Enter LONG on a Wyckoff spring (a candle that wicks below a
    detected trading range's support then closes back inside it -- the
    classic accumulation-phase stop-hunt/shakeout reversal e07_technical's
    wyckoff.py already detects descriptively), SHORT on the mirror
    upthrust at resistance. Exit at the opposite range boundary in either
    direction: reaching the far boundary is the target (spring -> rally to
    resistance), closing back through the entry's own boundary is the
    stop (the spring failed and the range is breaking down for real).

    LOOKAHEAD SAFETY: detect_trading_range/detect_springs_and_upthrusts
    were built for e07_technical's own single point-in-time "as of the
    last bar" descriptive reads -- reusing them for a walk-forward
    backtest signal requires recomputing them at EVERY bar from only the
    data available up to that bar, not once over the full history. Unlike
    smart_money.py's structure-event functions (built on find_swing_points'
    CENTERED rolling window, whose confirmation is unavoidably delayed by
    `lookback` bars past the swing's own index -- not safe to reuse this
    way without a separate confirmation-delay correction), wyckoff.py's
    functions are already purely backward-looking (df.tail(lookback) plus
    a backward rolling ATR, spring/upthrust scan bounded at the window's
    own last bar) -- recomputing them on a bounded TRAILING window ending
    at the current bar is both correct and, empirically (verified against
    the unbounded expanding-window equivalent on real GBPUSD data, 0/40
    mismatches), identical to what an unbounded walk-forward recomputation
    would find. The trailing window is capped at
    lookback+atr_period+grace_bars_after_range+5 bars purely for speed
    (O(n) instead of O(n^2) total); it does not change which bars are
    visible to detect_trading_range itself, which only ever reads its own
    last `lookback`/`atr_period` bars regardless of how much history is
    handed to it."""
    n = len(enriched)
    signal = pd.Series(0, index=enriched.index)
    window_size = lookback + atr_period + grace_bars_after_range + 5
    min_bars = lookback + atr_period
    position = 0
    range_low = range_high = None

    for i in range(min_bars, n):
        close_i = enriched["close"].iloc[i]
        if position == 1:
            if close_i < range_low or close_i > range_high:
                position = 0
        elif position == -1:
            if close_i > range_high or close_i < range_low:
                position = 0

        if position == 0:
            window_df = enriched.iloc[max(0, i + 1 - window_size): i + 1].reset_index(drop=True)
            trading_range = detect_trading_range(
                window_df, lookback=lookback, atr_period=atr_period, max_atr_multiple=max_atr_multiple
            )
            if trading_range is not None:
                last_local_idx = len(window_df) - 1
                springs, upthrusts = detect_springs_and_upthrusts(
                    window_df, trading_range, grace_bars_after_range=grace_bars_after_range
                )
                if springs and springs[-1].index == last_local_idx:
                    position, range_low, range_high = 1, trading_range.support, trading_range.resistance
                elif upthrusts and upthrusts[-1].index == last_local_idx:
                    position, range_low, range_high = -1, trading_range.support, trading_range.resistance

        signal.iloc[i] = position
    return signal


def liquidity_sweep_reversal(enriched: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Enter on a liquidity sweep: a bar that wicks BEYOND the prior
    `lookback`-bar extreme (where resting stop orders cluster) but CLOSES
    back inside it -- the failed-breakout/stop-hunt reversal. LONG on a
    swept low, SHORT on a swept high; exit when close reaches either
    rolling extreme (opposite side = the target liquidity pool taken,
    same side = the sweep failed and the break was real).

    Knowledge provenance (E01 hybrid_search over the real ingested corpus,
    2026-08-21 -- this strategy codifies retrieved content, none of it
    invented here):
    - "MASTER Liquidity Concepts Trading in 55 Minutes (Free Course)" /
      "Market Makers & Institutions Exposed" (score 0.778): "a stop hunt
      is when smart money traders are looking for liquidity and they
      usually use ... these very clear highs where retail traders like me
      and you we have our stop losses" -> liquidity sits at recent clear
      extremes, hence the rolling `lookback` high/low.
    - "What is LIQUIDITY in Trading? (Trading Liquidity Grabs & Sweeps)":
      "one of the best strategies and one of the most simple method to
      trade the liquidity grabs is to enter at the candle close just
      below the liquidity zone" -> entry at the CLOSE of the sweep bar
      that finishes back inside, exactly as implemented.
    - "Learn ICT Concepts in 71 Minutes! (ICT Exposed)" (score 0.687):
      names this exact wick-beyond-then-reject pattern "liquidity sweeps".
    e07_technical's smart_money.detect_liquidity_sweeps already detects
    this DESCRIPTIVELY for signal context, but (per wyckoff_spring_
    reversal's own lookahead note) it sits on find_swing_points' CENTERED
    window and is not safe to reuse as a walk-forward signal -- this is
    the purpose-built, shift(1)-rolling, no-lookahead tradable version.
    """
    prior_high = enriched["high"].shift(1).rolling(lookback).max()
    prior_low = enriched["low"].shift(1).rolling(lookback).min()

    entry_long = (enriched["low"] < prior_low) & (enriched["close"] > prior_low)
    entry_short = (enriched["high"] > prior_high) & (enriched["close"] < prior_high)
    closed_beyond = (enriched["close"] > prior_high) | (enriched["close"] < prior_low)
    return _stateful_from_entries_exits(entry_long, closed_beyond, entry_short, closed_beyond)


def liquidity_sweep_reversal_trend_filtered(enriched: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """liquidity_sweep_reversal gated by the dominant trend: only buy
    swept lows above the 200-EMA, only sell swept highs below it -- the
    corpus's own confluence guidance ("MASTER AI Trading in 70 Minutes":
    "one type of confluence is if the indicator ... agree with the
    overall trend"), applied the same way rsi_mean_reversion_trend_
    filtered already applies it to RSI entries. A sweep WITH the trend is
    the classic shakeout-then-continuation; against it, it is more often
    the start of the real break."""
    prior_high = enriched["high"].shift(1).rolling(lookback).max()
    prior_low = enriched["low"].shift(1).rolling(lookback).min()
    ema_200 = enriched["ema_200"].fillna(enriched["close"])

    entry_long = (enriched["low"] < prior_low) & (enriched["close"] > prior_low) & (enriched["close"] > ema_200)
    entry_short = (enriched["high"] > prior_high) & (enriched["close"] < prior_high) & (enriched["close"] < ema_200)
    closed_beyond = (enriched["close"] > prior_high) | (enriched["close"] < prior_low)
    return _stateful_from_entries_exits(entry_long, closed_beyond, entry_short, closed_beyond)


def regime_adaptive(enriched: pd.DataFrame) -> pd.Series:
    """Trend-follow (EMA8/21 cross direction) when ADX>25, mean-revert (RSI
    extremes) when ADX<20, flat in between."""
    adx = enriched["adx"].fillna(0)
    trend_dir = pd.Series(0, index=enriched.index)
    trend_dir[enriched["ema_8"] > enriched["ema_21"]] = 1
    trend_dir[enriched["ema_8"] < enriched["ema_21"]] = -1

    meanrev = rsi_mean_reversion(enriched)

    signal = pd.Series(0, index=enriched.index)
    signal[adx > 25] = trend_dir[adx > 25]
    signal[adx < 20] = meanrev[adx < 20]
    return signal


def trend_pullback_atr_trail(
    enriched: pd.DataFrame,
    oversold: float = 40.0,
    overbought: float = 60.0,
    atr_mult: float = 3.0,
    adx_min: float = 20.0,
) -> pd.Series:
    """Mean-reversion ENTRY timing with a trend-following EXIT -- added
    2026-08-22, designed for a specific, explicitly chosen profile:
    roughly 50-60% win rate with 2-4R average winners, in preference to a
    high win rate carrying small winners and rare huge losers.

    Nothing already in this module targets that combination, and the gap
    is structural rather than a matter of parameters:
      - rsi_mean_reversion_trend_filtered enters the same way but exits at
        the RSI midline, capping winners at a fraction of R. It buys a
        good win rate by cutting winners short -- measured on ETHUSD 1d,
        0.21-0.55R average winners, which needs an unreachable 65-82% win
        rate merely to break even.
      - donchian_atr_trail exits the same way but enters on a BREAKOUT,
        which buys big winners with a low hit rate (breakouts fail often).
      - regime_adaptive switches between the two rather than combining
        them, so it inherits whichever profile the regime hands it.

    The combination is the classic "buy the dip in an uptrend, then let
    the trend pay you", and each half is chosen for the metric it drives:

      TREND GATE (which direction is allowed):
        longs only above EMA200, shorts only below. Trading with the
        dominant trend is what stops a pullback entry from becoming a
        falling-knife catch -- the single largest source of the rare huge
        losers this profile is trying to avoid.
      ADX GATE (whether to trade at all):
        require ADX > adx_min. A pullback only resolves into a
        continuation if a trend actually exists; in a range the same
        entry just oscillates.
      ENTRY (drives WIN RATE):
        a pullback, not a breakout -- RSI dipping below `oversold` in an
        uptrend. Deliberately shallower defaults (40/60, versus the 20-35
        this module's pure mean-reversion rules use) because the aim is a
        brief pause inside a live trend, not an exhausted extreme.
      EXIT (drives R):
        an ATR trailing stop from the best close since entry, never a
        fixed target and never the RSI midline. This is the half that
        produces 2-4R: it lets a winner run as far as the trend goes while
        tightening automatically as ATR falls.

    No lookahead: ema_200/rsi/adx/atr are all backward-looking columns
    from e07_technical, and the trailing extreme only ever incorporates
    bars up to and including the current one. Explicit loop for the same
    reason donchian_atr_trail uses one -- a trailing stop is inherently
    sequential.
    """
    close = enriched["close"]
    rsi = enriched["rsi"].fillna(50)
    atr = enriched["atr"]
    ema200 = enriched["ema_200"].fillna(close)
    adx = enriched["adx"].fillna(0)

    c_a = close.to_numpy(dtype=float)
    r_a = rsi.to_numpy(dtype=float)
    a_a = atr.to_numpy(dtype=float)
    e_a = ema200.to_numpy(dtype=float)
    x_a = adx.to_numpy(dtype=float)

    out = np.zeros(len(enriched), dtype=np.int8)
    position = 0
    trail = 0.0
    for i in range(len(enriched)):
        c, r, a, e, x = c_a[i], r_a[i], a_a[i], e_a[i], x_a[i]
        if position == 0:
            if not np.isnan(a) and x > adx_min:
                if c > e and r < oversold:
                    position, trail = 1, c
                elif c < e and r > overbought:
                    position, trail = -1, c
        elif position == 1:
            trail = max(trail, c)
            # Trend gate also governs the EXIT: losing the 200EMA means the
            # premise the trade was taken on is gone, regardless of ATR.
            if (not np.isnan(a) and c < trail - atr_mult * a) or c < e:
                position, trail = 0, 0.0
        else:
            trail = min(trail, c)
            if (not np.isnan(a) and c > trail + atr_mult * a) or c > e:
                position, trail = 0, 0.0
        out[i] = position

    return pd.Series(out, index=enriched.index, dtype=int)


# --------------------------------------------------------------------------
# NEW CONCEPT FAMILIES -- MSS (ICT structure), VWAP bands, CVD (order-flow
# proxy), and rolling Volume Profile. Added 2026-09-12 in direct response to
# a request for genuinely new/enhanced concepts beyond the EMA/RSI/MACD/
# Donchian/Bollinger/Wyckoff/liquidity-sweep families already in this
# module. None of these are invented from nothing:
#   - market_structure_shift already exists in e07_technical.smart_money,
#     ALREADY MEASURED positive solo expectancy on BTCUSD (+0.474), ETHUSD
#     (+0.915) and GOLD (+0.015) at 4h with 69/69/46 trades
#     (research/concept_ablation.py's own ablation run, see
#     docs/ICT_CONCEPT_DIFF.md section 5's explicit recommendation: "Port
#     mss from research/ into engines/... One concept, already written,
#     already measured.") -- it was ported into e07_technical but NEVER
#     wired into a STRATEGIES entry, so it has never been reachable by
#     e24_strategy_research's grid or promotable to a live e51_signals
#     override. That is the exact gap being closed here.
#   - VWAP + bands (vwap/vwap_upper_N/vwap_lower_N) are already computed by
#     e07_technical.engine._add_vwap on every enriched df (present on 100%
#     of assets, unlike volume-profile's volume-presence gate) but were
#     never turned into a tradeable signal function anywhere in this file.
#   - CVD (cumulative volume delta) is e07_technical.order_flow's own
#     documented OHLCV-only proxy for real order flow (see that module's
#     docstring for the honesty caveat: an approximation from Close
#     Location Value, not real tick-level tape). Genuinely new information
#     axis for this file: every existing strategy reads price/momentum
#     indicators, none reads a buy/sell-pressure proxy.
#   - Volume Profile (POC / value area) is e07_technical.volume_profile's
#     own point-in-time snapshot tool, previously used only for live signal
#     CONTEXT (engine.py's _generate_signals reads value_area_high/low for
#     one narrative check) -- never as a backtestable rolling series. The
#     rolling wrapper below is new, built specifically so this concept can
#     be graded by E26/Stage 0 like every other candidate here.
#
# Every function below is verified causal (uses only bar i and earlier):
#   - market_structure_shift's own module docstring + confirm-window proof
#     is unchanged (called here, not reimplemented).
#   - VWAP is already a cumulative (expanding-window) calculation.
#   - CVD is a cumsum of a per-bar quantity -- expanding by construction.
#   - _rolling_volume_profile_levels recomputes only from
#     enriched.iloc[i-lookback+1 : i+1] (bar i inclusive, nothing later)
#     and forward-fills the result only into FUTURE bars until the next
#     recompute point -- never backward.
# No claim of solo edge is made for the VWAP/CVD/Volume-Profile functions
# below (unlike MSS, which has a real prior measurement) -- they exist to
# be tested, not asserted. Whether any of them clears Stage 0 for a given
# asset/timeframe is exactly what running the grid answers.
# --------------------------------------------------------------------------
def mss_trend_hold(
    enriched: pd.DataFrame, hold_bars: int = 10, atr_mult: float = 1.5, confirm_bars: int = 3,
) -> pd.Series:
    """Trade e07_technical.smart_money.market_structure_shift's own +1/-1/0
    event series, held for `hold_bars` bars after each trigger (a sparse
    structural event needs a hold window to be tradeable at all, same
    reasoning research/concept_ablation.py's own `_hold` helper documents).
    A later opposite-direction MSS event overrides the hold immediately
    rather than waiting for it to expire.

    Causal: forward-fill-with-limit only ever propagates a value into
    LATER bars, and market_structure_shift itself is already proven causal
    (see that function's own docstring/tests). hold_bars is a free grid
    parameter here (not fixed at the ablation's HOLD=10), so this is
    re-searched against current data rather than assumed still optimal.
    """
    mss = market_structure_shift(enriched, atr_mult=atr_mult, confirm_bars=confirm_bars)
    sparse = mss.replace(0, np.nan)
    held = sparse.ffill(limit=max(1, hold_bars - 1))
    return held.fillna(0).astype(int)


def mss_trend_filtered(
    enriched: pd.DataFrame, hold_bars: int = 10, atr_mult: float = 1.5,
) -> pd.Series:
    """mss_trend_hold gated by the 200-EMA trend filter -- only bullish
    MSS events above EMA200, only bearish below -- the same "confluence
    with the dominant trend" convention already applied by
    liquidity_sweep_reversal_trend_filtered and rsi_mean_reversion_trend_
    filtered elsewhere in this module."""
    raw = mss_trend_hold(enriched, hold_bars=hold_bars, atr_mult=atr_mult)
    ema_200 = enriched["ema_200"].fillna(enriched["close"])
    out = raw.copy()
    out[(raw == 1) & (enriched["close"] < ema_200)] = 0
    out[(raw == -1) & (enriched["close"] > ema_200)] = 0
    return out


def vwap_mean_reversion(enriched: pd.DataFrame, band: int = 1) -> pd.Series:
    """Fade back to VWAP: long when price closes beyond the LOWER band
    (oversold relative to the session's volume-weighted average), short
    beyond the UPPER band, exit once price reverts to the VWAP line
    itself. `band` selects the 1x or 2x standard-deviation band already
    computed by e07_technical.engine._add_vwap.

    VWAP and its bands are already fully causal (expanding/cumulative
    calculations), so this entry/exit logic adds no lookahead of its own.
    """
    upper = enriched[f"vwap_upper_{band}"]
    lower = enriched[f"vwap_lower_{band}"]
    vwap = enriched["vwap"]
    close = enriched["close"]

    entry_long = close < lower
    entry_short = close > upper
    exit_long = close >= vwap
    exit_short = close <= vwap
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def vwap_breakout(enriched: pd.DataFrame, band: int = 2) -> pd.Series:
    """The opposite read of vwap_mean_reversion: trade WITH a breakout
    beyond the band as momentum/continuation (a move that reaches 2
    standard deviations from the volume-weighted average and keeps going,
    read as institutional participation continuing rather than a fadeable
    extreme), exiting when price falls back inside the band it broke."""
    upper = enriched[f"vwap_upper_{band}"]
    lower = enriched[f"vwap_lower_{band}"]

    entry_long = enriched["close"] > upper
    entry_short = enriched["close"] < lower
    exit_long = enriched["close"] < upper
    exit_short = enriched["close"] > lower
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def cvd_trend_confirmation(enriched: pd.DataFrame, cvd_fast: int = 8, cvd_slow: int = 21) -> pd.Series:
    """EMA8/EMA21 price-trend direction, taken ONLY when Cumulative Volume
    Delta (e07_technical.order_flow's OHLCV-only buy/sell-pressure proxy)
    is ALSO trending the same way -- i.e. price and (proxy) order flow
    must agree before a trend trade is taken. A genuinely new confirmation
    axis for this module: every existing trend rule confirms price against
    other PRICE-derived indicators (ADX/MACD/RSI); this confirms it against
    a volume-pressure read instead.

    On an asset/timeframe with no usable volume column,
    compute_cumulative_delta returns an all-zero series (documented,
    honest degenerate case, not a crash) -- cvd_fast/slow EMAs of a
    constant 0 are equal, so cvd_bullish is always False and this produces
    zero long entries and zero short entries alike (both directions
    filtered out identically -- an honest "no confirmation available"
    result, not a fabricated bias in either direction).

    Causal: CVD is cumsum of a per-bar quantity (expanding, backward-only);
    its EMAs and price EMAs are standard trailing indicators.
    """
    cvd = compute_cumulative_delta(enriched)
    cvd_fast_ema = cvd.ewm(span=cvd_fast, adjust=False).mean()
    cvd_slow_ema = cvd.ewm(span=cvd_slow, adjust=False).mean()
    cvd_bullish = cvd_fast_ema > cvd_slow_ema
    cvd_bearish = cvd_fast_ema < cvd_slow_ema

    price_bullish = enriched["ema_8"] > enriched["ema_21"]
    price_bearish = enriched["ema_8"] < enriched["ema_21"]

    entry_long = price_bullish & cvd_bullish
    entry_short = price_bearish & cvd_bearish
    exit_long = price_bearish
    exit_short = price_bullish
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def cvd_price_divergence_fade(enriched: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Rolling, causal CVD/price-divergence fade -- a fresh price extreme
    NOT confirmed by an equally fresh CVD extreme is read as a weakening
    move and faded. Deliberately NOT built on
    e07_technical.order_flow.detect_cvd_divergences, which (like
    detect_liquidity_sweeps -- see liquidity_sweep_reversal's own
    docstring) sits on find_swing_points' CENTERED window and is
    documented as unsafe for a walk-forward signal. This uses only
    shift(1).rolling() extremes instead, the same no-lookahead pattern
    liquidity_sweep_reversal already uses for price.

    Short: price makes a new `lookback`-bar high AND CVD does NOT (buying
    pressure proxy failing to confirm the new high -- bearish divergence).
    Long: mirror image at the low.
    Exit: price reverts to the midpoint of its own rolling range.
    """
    cvd = compute_cumulative_delta(enriched)
    close = enriched["close"]

    price_prior_high = close.shift(1).rolling(lookback).max()
    price_prior_low = close.shift(1).rolling(lookback).min()
    cvd_prior_high = cvd.shift(1).rolling(lookback).max()
    cvd_prior_low = cvd.shift(1).rolling(lookback).min()

    price_new_high = close > price_prior_high
    price_new_low = close < price_prior_low
    cvd_confirms_high = cvd >= cvd_prior_high
    cvd_confirms_low = cvd <= cvd_prior_low

    entry_short = price_new_high & ~cvd_confirms_high
    entry_long = price_new_low & ~cvd_confirms_low

    mid = (price_prior_high + price_prior_low) / 2
    exit_long = close < mid
    exit_short = close > mid
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def _rolling_volume_profile_levels(
    enriched: pd.DataFrame, lookback: int = 200, recompute_every: int = 10, n_bins: int = 24,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """POC / value-area-high / value-area-low as CAUSAL rolling series --
    e07_technical.volume_profile.compute_volume_profile only ever computes
    one point-in-time snapshot over a trailing window; this repeatedly
    calls it at every `recompute_every`-th bar using ONLY
    enriched.iloc[i-lookback+1 : i+1] (bar i inclusive, nothing later),
    then forward-fills that snapshot into the bars strictly AFTER i, up to
    the next recompute point. No value at any bar depends on data from a
    later bar -- the defining no-lookahead property every other rolling
    calculation in this module already relies on.

    recompute_every > 1 is a real, deliberate cost control: compute_volume_
    profile's own binning loop is O(lookback) per call in pure Python;
    calling it at every single bar over a 12,000-bar 1h series would be
    ~60x more expensive than calling it every 10 bars for a profile that
    does not meaningfully shift bar-to-bar. Returns NaN (forward-filled
    from the first successful computation) for bars before `lookback`
    warms up -- never a fabricated level.
    """
    n = len(enriched)
    poc = np.full(n, np.nan)
    va_high = np.full(n, np.nan)
    va_low = np.full(n, np.nan)

    for i in range(min(lookback, n) - 1, n, max(1, recompute_every)):
        window = enriched.iloc[max(0, i - lookback + 1): i + 1]
        vp = compute_volume_profile(window, lookback=lookback, n_bins=n_bins)
        if vp is None:
            continue
        end = min(i + recompute_every, n)
        poc[i:end] = vp.poc_price
        va_high[i:end] = vp.value_area_high
        va_low[i:end] = vp.value_area_low

    idx = enriched.index
    return (
        pd.Series(poc, index=idx).ffill(),
        pd.Series(va_high, index=idx).ffill(),
        pd.Series(va_low, index=idx).ffill(),
    )


def volume_profile_fade(enriched: pd.DataFrame, lookback: int = 200, recompute_every: int = 10) -> pd.Series:
    """Fade back to the Point of Control: long when price trades below the
    rolling value area's LOW (undervalued relative to where most volume
    traded), short above the value area's HIGH, exit once price reverts to
    the POC itself. Returns an all-flat (all-zero) series, not an error,
    on an asset with no usable volume column (compute_volume_profile's own
    documented None-on-no-volume behavior propagates through as NaN levels
    here, and NaN comparisons are always False)."""
    poc, va_high, va_low = _rolling_volume_profile_levels(enriched, lookback, recompute_every)
    close = enriched["close"]

    entry_long = close < va_low
    entry_short = close > va_high
    exit_long = close >= poc
    exit_short = close <= poc
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def volume_profile_breakout(enriched: pd.DataFrame, lookback: int = 200, recompute_every: int = 10) -> pd.Series:
    """The opposite read of volume_profile_fade: trade WITH a breakout
    beyond the rolling value area as acceptance of a new price range,
    exiting once price falls back inside the value area it broke out of."""
    poc, va_high, va_low = _rolling_volume_profile_levels(enriched, lookback, recompute_every)
    close = enriched["close"]

    entry_long = close > va_high
    entry_short = close < va_low
    exit_long = close < va_high
    exit_short = close > va_low
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


STRATEGIES: dict[str, Callable[..., pd.Series]] = {
    "baseline_trend": baseline_trend,
    "ma_cross_50_200": ma_cross_50_200,
    "macd_cross": macd_cross,
    "donchian_breakout": donchian_breakout,
    "donchian_atr_trail": donchian_atr_trail,
    "donchian_breakout_volume_confirmed": donchian_breakout_volume_confirmed,
    "donchian_breakout_volatility_confirmed": donchian_breakout_volatility_confirmed,
    "donchian_breakout_buffer_confirmed": donchian_breakout_buffer_confirmed,
    "rsi_mean_reversion": rsi_mean_reversion,
    "rsi_mean_reversion_trend_filtered": rsi_mean_reversion_trend_filtered,
    "bollinger_reversion": bollinger_reversion,
    "bollinger_reversion_tuned": bollinger_reversion_tuned,
    "wyckoff_spring_reversal": wyckoff_spring_reversal,
    "liquidity_sweep_reversal": liquidity_sweep_reversal,
    "liquidity_sweep_reversal_trend_filtered": liquidity_sweep_reversal_trend_filtered,
    "regime_adaptive": regime_adaptive,
    "trend_pullback_atr_trail": trend_pullback_atr_trail,
    # New concept families added 2026-09-12 -- see the module comment block
    # immediately above mss_trend_hold's definition for full provenance.
    "mss_trend_hold": mss_trend_hold,
    "mss_trend_filtered": mss_trend_filtered,
    "vwap_mean_reversion": vwap_mean_reversion,
    "vwap_breakout": vwap_breakout,
    "cvd_trend_confirmation": cvd_trend_confirmation,
    "cvd_price_divergence_fade": cvd_price_divergence_fade,
    "volume_profile_fade": volume_profile_fade,
    "volume_profile_breakout": volume_profile_breakout,
}

# External-repo strategy plugins (see plugins/__init__.py for the full
# audited-repo registry and per-strategy provenance). Imported at the
# bottom so plugin modules never need to import back into this module --
# they depend only on numpy/pandas/e07 -- keeping the dependency one-way.
from project_titan_x.engines.e24_strategy_research.plugins import PLUGIN_STRATEGIES  # noqa: E402

STRATEGIES.update(PLUGIN_STRATEGIES)


# ---------------------------------------------------------------------------
# Expected-move band family
#
# DECODED FROM an options "IV walls / expected range" approach: take the option
# market's own expected move for the period, draw it as a band around the prior
# close, and treat its edges as the statistically likely high/low of the
# period. The claim being tested is that touching the edge marks the extreme,
# so fading it back toward the middle has edge.
#
# WHY REALIZED VOL AND NOT IMPLIED. e13_derivatives can read a live option
# chain (Deribit for BTC/ETH, Kite for the Indian indices) and already computes
# nearest_expiry_atm_iv, max_pain_strike and iv_minus_rv -- but NO historical
# IV is stored anywhere in this repo (data/models/e13_derivatives holds only a
# realized-vol percentile baseline). A backtest on implied vol is therefore
# impossible without first recording chains forward for months. Realized vol is
# the honest stand-in, and testing it first is the cheap experiment: if the
# effect is absent with RV bands it is unlikely to appear with IV bands, and
# that is worth knowing BEFORE building options plumbing.
#
# WHAT THE SUBSTITUTION COSTS. IV normally exceeds RV -- that spread is the
# variance risk premium, which this project already measures as
# DerivativesSnapshot.iv_minus_rv. So an RV band is NARROWER than the IV band
# the original uses: it is touched more often, producing more trades that are
# each a weaker claim. Read the trade count accordingly; more trades here is
# not more evidence.
#
# CAUSALITY. sigma is computed on returns lagged by one bar and the band is
# anchored to the PRIOR close, so the whole band is known before the bar opens.
# Whether the bar then touched it is settled at that bar's close, and E26
# shifts every signal one bar and fills at the next open -- so the earliest
# possible execution is the open after the touch, which is reachable in real
# trading.
# ---------------------------------------------------------------------------


def _expected_move_band(
    enriched: pd.DataFrame, vol_n: int, band_mult: float
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(floor, mid, ceiling) for the expected-move band. Fully causal."""
    close = enriched["close"]
    prev_close = close.shift(1)
    log_ret = np.log(close / prev_close)
    # .shift(1) again so the CURRENT bar's own return never enters its own band
    sigma = log_ret.shift(1).rolling(vol_n).std()
    em = prev_close * sigma * band_mult
    return prev_close - em, prev_close, prev_close + em


def expected_move_fade(
    enriched: pd.DataFrame, vol_n: int = 20, band_mult: float = 1.0
) -> pd.Series:
    """Fade a touch of the expected-move band, exit back at the midpoint.

    Short when the bar's high reaches the ceiling, long when its low reaches
    the floor; close the position once price returns to the anchor (the prior
    close the band was built around).
    """
    floor, mid, ceiling = _expected_move_band(enriched, vol_n, band_mult)
    close = enriched["close"]

    entry_short = enriched["high"] >= ceiling
    entry_long = enriched["low"] <= floor
    exit_short = close <= mid
    exit_long = close >= mid
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def expected_move_rejection(
    enriched: pd.DataFrame, vol_n: int = 20, band_mult: float = 1.0
) -> pd.Series:
    """Fade the band only when the bar CLOSES back inside it.

    The stricter reading of the original: a level only counts as rejected when
    price pokes through and fails, leaving a wick. A bar that closes beyond the
    band is a breakout, not a rejection, and fading it is the losing side of
    the same setup -- this variant declines those, so it should trade less
    often than `expected_move_fade` on identical parameters. If it does not,
    the two are not measuring what their names claim.
    """
    floor, mid, ceiling = _expected_move_band(enriched, vol_n, band_mult)
    close = enriched["close"]

    entry_short = (enriched["high"] >= ceiling) & (close < ceiling)
    entry_long = (enriched["low"] <= floor) & (close > floor)
    exit_short = close <= mid
    exit_long = close >= mid
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)

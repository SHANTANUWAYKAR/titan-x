"""
Module: engine.py
Description: Engine 10 — Backtesting Laboratory with rigorous validation.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)


@dataclass
class BacktestMetrics:
    """Comprehensive backtest performance metrics."""

    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    total_return_pct: float = 0.0
    cagr: float = 0.0
    # WARNING ON UNITS (documented 2026-08-24 after this was measured):
    # despite the `_r` suffix these are NOT R-multiples in the usual sense
    # of "multiple of the cash amount risked". pnl_r is computed as
    # `pnl_pct / risk_pct`, and pnl_pct is the raw PRICE MOVE fraction, so
    # at the default risk_pct=0.01 these values are numerically identical
    # to the price move expressed in PERCENT. Verified directly on ETHUSD
    # 1d: reported expectancy 22.280 against a measured mean trade
    # pnl_pct of 22.280%.
    #
    # This matters enormously and is easy to misread. A true R-multiple
    # needs a stop distance, and these signal-flip strategies have no
    # stop -- so "expectancy 22.28" means "the average trade moved 22.28%
    # in price", NOT "the average trade made 22.28x the amount risked".
    # The equity effect is far smaller: _simulate sizes each position at
    # risk_pct of equity, so per-trade equity change is
    # expectancy% * risk_pct -- 0.2228% here, not 22.28%. Reading these as
    # R-multiples overstates returns by roughly 100x at the default
    # risk_pct.
    #
    # Left named as-is rather than renamed: these keys are persisted in
    # every promoted *_strategy_override.json and every sweep report on
    # disk, so a rename would silently invalidate that history. Documented
    # instead, at the definition, where a reader will actually hit it.
    avg_win_r: float = 0.0      # mean WINNING trade's price move, in % (at risk_pct=0.01)
    avg_loss_r: float = 0.0     # mean LOSING trade's price move, in % (negative)
    expectancy: float = 0.0     # win_rate*avg_win_r + (1-win_rate)*avg_loss_r, same units
    recovery_factor: float = 0.0


@dataclass
class BacktestResult:
    """Full backtest result with trades and equity curve."""

    metrics: BacktestMetrics
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    parameters: dict[str, Any] = field(default_factory=dict)
    robustness_score: float = 0.0
    passed_validation: bool = False
    monte_carlo_sequencing: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# STAGE 0 -- TIMEFRAME-AWARE PROMOTION THRESHOLDS
#
# MEASURED, not chosen. Each min_selection_score is the 95th percentile of
# the winning min(IS, OOS) Sharpe produced by running this exact 167-candidate
# pipeline on stationary-block-bootstrap data built to contain NO edge
# (research/synthetic_null.py; 150 paths per timeframe, 3 block lengths x 50).
# A candidate clearing this floor beat 95% of pure-noise sweeps at its own
# timeframe. See the "WHICH p95" note below -- the denominator matters.
#
# WHY TIMEFRAME-AWARE. The old single bar (IS Sharpe > 0.5, 30 trades) was
# cleared by 137 of 150 pure-noise 4h sweeps -- 91%. The median noise winner
# had IS Sharpe 0.93, nearly double the bar. Worse, the noise distribution
# differs sharply by timeframe (1h p95 2.37, 4h 1.50, 1d 0.66), so ONE global
# bar was silently far stricter on 1d than on 1h without anyone choosing that.
#
# min_trades is NOT measured. The null campaigns record per-path pass counts
# and winner Sharpes but NOT the trade count of each passing candidate, so
# there is nothing to calibrate a trade floor against. 60 is convention
# (Sharpe SE at n=60 is ~0.158 under an IID assumption these strategies
# violate, so even that is a lower bound on the true uncertainty).
#
# DSR IS DELIBERATELY NOT A GATE. It is computed on IS Sharpe alone, while
# the selection score is min(IS, OOS), so DSR cannot see in-sample to
# out-of-sample decay. On the live book the two rank almost inversely:
# ETH-USD_1h scores DSR 0.878 (best in the book) on IS 3.18 -> OOS 0.42,
# null percentile 16.7; INFY.NS_1d scores DSR 0.009 with null percentile
# 97.3. AND-gating two statistics that disagree that violently rejects
# everything -- it rejected all 45 live overrides -- and a bar that rejects
# 100% cannot distinguish a bad book from a bad bar. DSR is reported as a
# diagnostic instead. See docs/STAGE0_FINDINGS.md.
# WHICH p95. The floor is the score whose percentile against ALL 150 null
# paths is 95 -- NOT the 95th percentile of the winning scores alone. The two
# differ because paths where noise produced no passing candidate at all are
# real outcomes the candidate beat, so they belong in the denominator. On 1d
# the gap is decisive: only 39 of 150 daily paths produced any winner, so the
# winners-only p95 (0.663) actually sits at the 98.7th all-paths percentile.
# Gating on 0.663 would reject BOTH overrides that clear "null percentile
# >= 95" -- the bar would contradict the audit that set it. Measured gap:
# 1h 2.367 -> 2.336, 4h 1.496 -> 1.486, 1d 0.663 -> 0.593.
# RE-CALIBRATED 1d, 2026-09-19. The floors above were measured against a null
# campaign run at 167 candidates per path. The live grid has since grown to 830
# -- 4.97x -- and best-of-N climbs with N on noise alone, so the old floor no
# longer buys the percentile it claims.
#
# Re-running the 1d campaign at 830 candidates (150 paths, 50 per block length;
# experiment null_campaign-20260919T161123-e3030f) measured this directly:
#
#     mean candidates "passing" per path   1.6-3.0  ->  7.0-14.1
#     paths where noise found NO winner    38/50    ->  17/50 (block 10)
#     all-paths p95 of best selection      0.593    ->  0.706
#
# So 0.59 sat at the 94.7th percentile of the old null and sits at only the
# **79.3rd** of the correctly-sized one: noise clears it roughly one run in
# five, not one in twenty. The corrected floor is 0.706 -- the old bar was 20%
# too low, which independently confirms the 21-32% estimate already recorded in
# reports/STRATEGY_LEADERBOARD.md from a completely different argument.
#
# 1h AND 4h ARE STILL ON THE OLD NULL and are therefore MORE LENIENT THAN THEY
# READ, by roughly the same margin. They are deliberately left unchanged rather
# than scaled by a guess: a floor nobody measured is exactly what this whole
# exercise exists to remove. Re-run those campaigns before trusting them.
STAGE0_TIMEFRAME_THRESHOLDS: dict[str, dict[str, float]] = {
    "1h": {"min_selection_score": 2.34, "min_trades": 60},   # UNDER-CALIBRATED (167-cand null)
    "4h": {"min_selection_score": 1.49, "min_trades": 60},   # UNDER-CALIBRATED (167-cand null)
    "1d": {"min_selection_score": 0.706, "min_trades": 60},  # measured at 830 candidates
}


class BacktestingEngine(BaseEngine):
    """
    Backtesting Laboratory — rigorous strategy validation.

    Features: walk-forward, out-of-sample, Monte Carlo, cost modeling,
    parameter sensitivity, stress testing.
    """

    engine_id = "e26_backtesting"
    engine_name = "Backtesting Laboratory"
    version = "1.0.0"

    MIN_TRADES = 30
    STRESS_PERIODS = {
        "2008_gfc": ("2008-01-01", "2009-03-31"),
        "2020_covid": ("2020-02-01", "2020-04-30"),
        "2022_rate_shock": ("2022-01-01", "2022-12-31"),
        # Added 2026-08-02: the master prompt's stress-testing scope
        # explicitly names "banking crises" as its own category, distinct
        # from the three periods above -- none of them are a banking
        # crisis (2008 GFC predates it, 2020/2022 are unrelated shocks).
        # Real, well-documented dates, not guessed: Silicon Valley Bank
        # closed by regulators 2023-03-10, Signature Bank 2023-03-12,
        # Credit Suisse's forced UBS merger announced 2023-03-19, First
        # Republic Bank failed 2023-05-01 -- the window below covers the
        # acute crisis through that final failure and its immediate
        # aftermath.
        "2023_banking_crisis": ("2023-03-01", "2023-05-15"),
    }

    def initialize(self) -> EngineResult:
        """Initialize backtesting engine."""
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Backtesting Laboratory initialized")

    def health_check(self) -> EngineResult:
        """Health check."""
        return EngineResult(success=True, message="Healthy")

    # ------------------------------------------------------------------
    # RISK-BASED POSITION SIZING (added 2026-09-20)
    #
    # The previous formula was `pnl = equity * risk_pct * price_move`, which
    # caps the position NOTIONAL at risk_pct of equity. That is a real and
    # deliberate fix over what came before it (which bet full equity and drove
    # a CRUDE account negative), but it is still not risk sizing: what a trade
    # costs depends on how far price travelled, not on a risk budget.
    #
    # Measured on ETHUSD 1d mss_trend_hold, 71 trades: the LOSING trades cost
    # between 0.0070% and 0.2197% of equity -- a 31x spread on trades that
    # should each have cost the same. Across all trades the spread is 271x.
    # A stop-out is supposed to cost exactly risk_pct, every time.
    #
    # The fix sizes each position so that a STOP-DISTANCE adverse move costs
    # exactly risk_pct:
    #
    #     notional_frac = risk_pct / stop_distance_frac
    #     pnl           = equity * notional_frac * price_move_frac
    #
    # so at price_move == -stop_distance the loss is exactly equity*risk_pct.
    #
    # WHAT SERVES AS THE STOP DISTANCE. When barriers are configured, the real
    # stop (stop_atr_mult * ATR) is used. When they are not -- which is most of
    # this project's backtests, since stop_atr_mult defaults to None -- one ATR
    # is used as the risk unit instead. That is volatility-targeted sizing: it
    # makes risk comparable across trades and instruments even with no explicit
    # stop, which is the whole point of Law 11. It is NOT a claim that a stop
    # exists; the exit is still whatever the strategy says.
    #
    # LEVERAGE CAP. risk_pct/stop_distance explodes when ATR is tiny relative
    # to price, so notional is capped. Without the cap a quiet instrument would
    # be sized into absurd leverage and the equity curve would be dominated by
    # whichever asset happened to have the lowest volatility.
    # ------------------------------------------------------------------
    DEFAULT_RISK_ATR_MULT = 1.0    # risk unit when no explicit stop is set
    MAX_NOTIONAL_LEVERAGE = 3.0    # notional may not exceed 3x equity

    @staticmethod
    def _notional_fraction(
        risk_pct: float, entry_price: float, atr: float,
        stop_atr_mult: Optional[float], max_leverage: float,
        risk_atr_mult: float,
    ) -> float:
        """Fraction of equity to deploy so a stop-distance move costs risk_pct.

        Falls back to the legacy notional cap (`risk_pct`) when ATR is missing
        or non-finite, so a frame without enough history to form an ATR behaves
        exactly as it did before rather than silently taking a different size.
        """
        if not atr or not np.isfinite(atr) or atr <= 0 or not entry_price:
            return risk_pct
        k = stop_atr_mult if stop_atr_mult else risk_atr_mult
        stop_frac = (k * atr) / float(entry_price)
        if stop_frac <= 0 or not np.isfinite(stop_frac):
            return risk_pct
        return float(min(risk_pct / stop_frac, max_leverage))

    def run_backtest(
        self,
        df: pd.DataFrame,
        strategy_fn: Callable[[pd.DataFrame], pd.Series],
        initial_capital: float = 10_000.0,
        risk_per_trade: float = 0.01,
        commission_pct: float = 0.001,
        slippage_pct: float = 0.0005,
        oos_split: float = 0.7,
        periods_per_year: float = 252,
        run_monte_carlo_sequencing: bool = False,
        timeframe: Optional[str] = None,
        stop_atr_mult: Optional[float] = None,
        tp_atr_mult: Optional[float] = None,
        atr_period: int = 14,
        compute_robustness: bool = True,
        # "risk": size so a stop-distance move costs exactly risk_per_trade.
        # "notional": the legacy cap (position = risk_per_trade of equity),
        # kept so a previously published number can still be reproduced.
        sizing_mode: str = "risk",
        max_leverage: float = MAX_NOTIONAL_LEVERAGE,
    ) -> EngineResult:
        """
        Run a full backtest with out-of-sample validation.

        Args:
            df: OHLCV DataFrame.
            strategy_fn: Function that returns signal series (1=long, -1=short, 0=flat).
            initial_capital: Starting capital.
            risk_per_trade: Risk per trade as fraction of capital.
            commission_pct: Commission per trade.
            slippage_pct: Slippage per trade.
            oos_split: In-sample fraction (rest is out-of-sample).
            periods_per_year: Bars per year, used to annualize Sharpe/Sortino
                and to convert bar count to years for CAGR. Defaults to 252
                (one bar per trading day) to preserve existing behavior for
                every daily-timeframe caller already in production (e.g.
                e51_signals' live edge-gate). Pass the true bar frequency
                (e.g. ~105,120 for 5-minute crypto bars, 8,760 for hourly)
                when backtesting intraday data -- otherwise Sharpe/CAGR are
                silently off by whatever factor separates the assumed and
                actual bar frequency.
            run_monte_carlo_sequencing: Opt-in (default False, so no existing caller's
                behavior/runtime changes). When True, attaches a permutation
                sequencing test (see monte_carlo_sequencing_test) to the
                IS result's `monte_carlo_sequencing` field -- answers "is this Sharpe
                distinguishable from randomly reordering the same trades?",
                a real statistical rigor check this engine didn't have
                before (added 2026-08-21, adapted from HKUDS/Vibe-Trading's
                MIT-licensed agent/backtest/validation.py:monte_carlo_test
                -- same shuffle-the-PnL-order technique, ported to this
                engine's own trade-dict shape rather than its TradeRecord
                class). Purely additive: does NOT change passed_validation
                or any existing threshold, so it can't silently alter any
                already-shipped calibration.
            compute_robustness: Opt-OUT (default True, so no existing
                caller's behavior/runtime changes). Runs 2 EXTRA full
                _simulate passes (+-10% risk/commission perturbation, see
                _parameter_sensitivity's own docstring) -- profiled directly
                (cProfile, a real 167-candidate grid sweep, 2026-09-11):
                52.2% of total grid-search wall-clock time, computing a
                `robustness_score` that e24_strategy_research's own
                `_selection_score` docstring says it deliberately does NOT
                use for ranking ("real sweep values cluster in a narrow
                0.91-0.99 band and cannot discriminate between candidates").
                E30 AdversarialTestingEngine's own parameter-fragility check
                DOES read `robustness_score` on a real, already-selected
                candidate -- that caller (and every other caller) keeps the
                default True. Only e24_strategy_research's own grid-search
                worker (_run_one_candidate_worker, which discards the value
                for exactly the documented reason above) opts out. When
                False, `robustness_score` stays at BacktestResult's own
                0.0 default -- indistinguishable from a genuinely-computed
                zero, same as any other field a caller chose not to compute.

        Returns:
            EngineResult with BacktestResult.
        """
        try:
            self._set_status(EngineStatus.RUNNING)

            split_idx = int(len(df) * oos_split)
            is_df = df.iloc[:split_idx].copy()
            oos_df = df.iloc[split_idx:].copy()

            is_result = self._simulate(
                is_df, strategy_fn, initial_capital, risk_per_trade,
                commission_pct, slippage_pct, periods_per_year,
                stop_atr_mult=stop_atr_mult, tp_atr_mult=tp_atr_mult,
                atr_period=atr_period, sizing_mode=sizing_mode,
                max_leverage=max_leverage,
            )
            oos_result = self._simulate(
                oos_df, strategy_fn, initial_capital, risk_per_trade,
                commission_pct, slippage_pct, periods_per_year,
                stop_atr_mult=stop_atr_mult, tp_atr_mult=tp_atr_mult,
                atr_period=atr_period, sizing_mode=sizing_mode,
                max_leverage=max_leverage,
            )

            robustness = 0.0
            if compute_robustness:
                robustness = self._parameter_sensitivity(
                    is_df, strategy_fn, initial_capital, risk_per_trade,
                    commission_pct, slippage_pct, periods_per_year,
                    base_result=is_result,
                )

            # LEGACY BAR -- kept as the default so the eight existing
            # callers that pass no timeframe are unaffected by Stage 0.
            passed = (
                is_result.metrics.total_trades >= self.MIN_TRADES
                and is_result.metrics.sharpe_ratio > 0.5
                and is_result.metrics.max_drawdown_pct < 25.0
                and oos_result.metrics.sharpe_ratio > 0.0
            )
            gate_applied = "legacy"
            selection_score = min(float(is_result.metrics.sharpe_ratio),
                                  float(oos_result.metrics.sharpe_ratio))
            stage0 = STAGE0_TIMEFRAME_THRESHOLDS.get(timeframe) if timeframe else None
            if stage0 is not None:
                # The selection-score floor subsumes the legacy Sharpe
                # conditions: min(IS, OOS) >= floor forces BOTH above it, and
                # every floor exceeds the old 0.5/0.0 pair. Drawdown is kept
                # because it gates a different failure mode entirely.
                passed = (
                    is_result.metrics.total_trades >= stage0["min_trades"]
                    and is_result.metrics.max_drawdown_pct < 25.0
                    and selection_score >= stage0["min_selection_score"]
                )
                gate_applied = f"stage0:{timeframe}"

            is_result.robustness_score = robustness
            is_result.passed_validation = passed
            if run_monte_carlo_sequencing:
                is_result.monte_carlo_sequencing = self.monte_carlo_sequencing_test(
                    is_result.trades, initial_capital,
                )
            is_result.parameters = {
                "gate_applied": gate_applied,
                # Which exit model produced these numbers. A Sharpe from
                # signal-flip exits and one from barrier exits are not
                # comparable, so the report must say which it is.
                "exit_model": ("barriers" if (stop_atr_mult or tp_atr_mult)
                               else "signal_flip_only"),
                "stop_atr_mult": stop_atr_mult,
                "tp_atr_mult": tp_atr_mult,
                "selection_score": selection_score,
                "initial_capital": initial_capital,
                "risk_per_trade": risk_per_trade,
                "commission_pct": commission_pct,
                "slippage_pct": slippage_pct,
                "oos_sharpe": oos_result.metrics.sharpe_ratio,
            }

            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=is_result,
                message=f"Backtest complete: Sharpe={is_result.metrics.sharpe_ratio:.2f}, "
                f"DD={is_result.metrics.max_drawdown_pct:.1f}%, "
                f"Validated={'PASS' if passed else 'FAIL'}",
                metadata={
                    "sharpe": is_result.metrics.sharpe_ratio,
                    "max_dd": is_result.metrics.max_drawdown_pct,
                    "passed": passed,
                },
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Backtest failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _barrier_levels(entry_price, position, atr_arr, i, stop_atr_mult, tp_atr_mult):
        """Stop/target prices for a position opened at bar `i`.

        ATR is read at the ENTRY bar and then frozen for the life of the
        trade -- these are the levels a trader would actually have placed
        when the order went in. Recomputing them each bar would be a
        trailing stop, which is a different mechanism with different
        behaviour, not a detail.

        Returns (None, None) whenever ATR is unavailable (warm-up window,
        NaN) so a trade opened before ATR exists simply runs unbarriered
        rather than being given a fabricated level.
        """
        if atr_arr is None:
            return None, None
        atr = atr_arr[i]
        if atr is None or atr != atr or atr <= 0:   # NaN-safe
            return None, None
        stop = entry_price - stop_atr_mult * atr * position if stop_atr_mult else None
        tp = entry_price + tp_atr_mult * atr * position if tp_atr_mult else None
        return stop, tp

    def _simulate(
        self,
        df: pd.DataFrame,
        strategy_fn: Callable[[pd.DataFrame], pd.Series],
        capital: float,
        risk_pct: float,
        commission: float,
        slippage: float,
        periods_per_year: float = 252,
        signals: Optional[pd.Series] = None,
        stop_atr_mult: Optional[float] = None,
        tp_atr_mult: Optional[float] = None,
        atr_period: int = 14,
        sizing_mode: str = "risk",
        max_leverage: float = MAX_NOTIONAL_LEVERAGE,
    ) -> BacktestResult:
        """Run single-period simulation.

        signals: OPTIONAL pre-computed strategy_fn(df) output. None
        (default) computes it here, exactly as before. Added 2026-08-02:
        _parameter_sensitivity calls this 3x on the SAME df with the SAME
        strategy_fn to test risk_pct/commission perturbation -- but
        strategy_fn's output depends only on df, never on risk_pct/
        commission/slippage, so all 3 calls were recomputing an identical
        signal series from scratch. For a cheap strategy_fn this is
        negligible; for one with real per-bar work (e.g.
        e24_strategy_research.strategies.wyckoff_spring_reversal, an
        explicit O(n * window) loop measured at several seconds on a few
        thousand bars) it's pure waste, 3x over, every single
        run_backtest() call."""
        if signals is None:
            signals = strategy_fn(df)
        if signals is None or len(signals) != len(df):
            signals = pd.Series(0, index=df.index)

        # Fill-timing fix (added 2026-08-20): a signal at signals.iloc[i]
        # is only KNOWABLE once bar i's close prints -- every real
        # strategy_fn in this codebase (e.g. e24_strategy_research.
        # strategies.donchian_breakout) compares its lagged threshold
        # against `close` at the SAME index it's evaluated at, meaning the
        # signal is confirmed the instant bar i closes. Before this fix,
        # `_simulate` filled trades at that SAME bar i's own close --
        # transacting at the exact print that revealed the signal, which
        # no real order could ever reach. Real gap found while reviewing
        # nautilus_trader's own backtesting-realism docs (cloned read-only
        # for reference): "a bar's ts_init represents the close... orders
        # submitted from on_bar arrive only after [that] bar has been
        # processed" -- i.e. action on bar i's signal can only happen at
        # bar i+1 or later, never bar i's own close. This is NOT classic
        # look-ahead bias (every strategy_fn here already correctly lags
        # its OWN rolling thresholds via .shift(1); no future data leaks
        # into signal generation) -- it's a narrower, still-real issue:
        # an unrealistically instant execution assumption.
        #
        # Fix: shift the signal series forward by one bar (signals.iloc[i-1]
        # becomes "acted on" at index i) and fill entries/exits at that
        # bar's OPEN (the first realistic tradeable price once the prior
        # bar's close, and therefore the signal, is actually known) --
        # NOT its close, which would just move the same optimism one bar
        # later. The ongoing mark-to-market valuation of an already-open
        # position below still uses CLOSE (the standard EOD equity-curve
        # convention) -- this fix only changes the actual transaction
        # price for NEW entries/exits, not how an open position is valued
        # day to day.
        execution_signals = signals.shift(1).fillna(0)

        # `equity` is the MARK-TO-MARKET value tracked every bar (what
        # feeds equity_curve, and therefore Sharpe/Sortino/drawdown);
        # `realized_equity` is the settled value as of the last trade
        # close/open, the baseline unrealized P&L is measured against
        # while a position is held open. Before this fix, `equity` was
        # only ever updated on entry/exit bars, leaving it frozen for
        # every bar a position was held -- a position open for 50 bars
        # contributed 49 exactly-zero-return observations to the return
        # series regardless of how much it actually moved day to day, and
        # any intra-trade drawdown that recovered before exit was
        # invisible to max_drawdown_pct entirely. Caught live: a
        # buy-and-hold position that never exited (0 trades) produced
        # Sharpe=0.0 from a completely flat equity curve, against a true
        # mark-to-market Sharpe of 2.85 on the same real price path --
        # confirmed the fix below reproduces ~2.85 (see e26 test suite)
        # and leaves final realized equity exactly unchanged (this only
        # changes the shape of the curve BETWEEN trades, not final P&L).
        # BARRIER EXITS (added 2026-09-09, OPT-IN -- both None = exactly the
        # previous behaviour, byte for byte).
        #
        # WHY THIS EXISTS. Until now this simulator exited on signal flip
        # ONLY. E51 shows a stop_loss and take_profit on every live signal,
        # and NOTHING here ever tested them -- so every Sharpe, win rate and
        # Stage 0 percentile on this platform describes a strategy that
        # holds until the signal reverses, not the strategy a human
        # following the stated levels actually trades. That gap is recorded
        # in CLAUDE.md and in docs/REPOSITORY_FEATURE_MATRIX.md section 5.
        #
        # Default stays None so nothing already validated silently changes
        # its numbers. Turning this on is a deliberate act, and comparing
        # the two is the measurement that says how wrong signal-flip-only
        # validation was.
        use_barriers = (stop_atr_mult is not None) or (tp_atr_mult is not None)
        atr_arr = None
        # ATR is now needed for SIZING as well as for barriers, so it is built
        # whenever either wants it. Previously it existed only when barriers
        # were configured, which is why risk-based sizing had nothing to size
        # against on the default path.
        if use_barriers or sizing_mode == "risk":
            tr = pd.concat([
                df["high"] - df["low"],
                (df["high"] - df["close"].shift()).abs(),
                (df["low"] - df["close"].shift()).abs(),
            ], axis=1).max(axis=1)
            atr_arr = tr.rolling(atr_period).mean().to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        opens = df["open"].to_numpy(dtype=float)
        # PERFORMANCE (added 2026-09-11): closes/execution_signals extracted
        # to raw numpy arrays for the SAME reason highs/lows/opens already
        # were -- profiled directly (cProfile, a real 167-candidate grid
        # pass): 2.9M calls to df["close"].iloc[i]/execution_signals.iloc[i]
        # inside this loop cost 78s of 170.9s total runtime (45.7%), all in
        # pandas' single-element access machinery (type checks, block-
        # manager lookups), not in any actual computation. Indexing a numpy
        # array by position skips all of that. Output is unchanged -- this
        # swaps WHERE a value comes from, never WHAT value it is; verified
        # byte-identical against the pre-change simulator (see this
        # commit's own test run).
        closes = df["close"].to_numpy(dtype=float)
        exec_signals_arr = execution_signals.to_numpy(dtype=float)

        realized_equity = capital
        equity = capital
        equity_curve = [equity]
        trades: list[dict[str, Any]] = []
        position = 0
        # Notional deployed for the OPEN trade, as a fraction of equity. Fixed
        # at entry and held until exit -- a position's size does not change
        # mid-trade just because volatility did.
        pos_frac = risk_pct
        entry_price = 0.0
        entry_idx = 0
        stop_level: Optional[float] = None
        tp_level: Optional[float] = None

        for i in range(1, len(df)):
            signal = exec_signals_arr[i] if i < len(exec_signals_arr) else 0
            price = closes[i]  # mark-to-market reference -- unchanged, see comment above
            fill_price = opens[i]  # realistic transaction price for NEW entries/exits this bar

            # Entry
            if position == 0 and signal != 0:
                position = int(signal)
                entry_price = fill_price * (1 + slippage * position)
                pos_frac = (
                    self._notional_fraction(
                        risk_pct, entry_price,
                        atr_arr[i] if atr_arr is not None else None,
                        stop_atr_mult, max_leverage, self.DEFAULT_RISK_ATR_MULT)
                    if sizing_mode == "risk" else risk_pct
                )
                entry_idx = i
                stop_level, tp_level = self._barrier_levels(
                    entry_price, position, atr_arr, i, stop_atr_mult, tp_atr_mult)
                # Commission is a cost on the DOLLAR VALUE TRADED (position
                # notional = risk_pct * equity), not on total equity -- see
                # the exit-side comment below for why this has to move
                # together with the position-sizing fix.
                realized_equity -= realized_equity * pos_frac * commission
                equity = realized_equity

            # Exit on signal change
            elif position != 0 and (signal == 0 or signal != position):
                exit_price = fill_price * (1 - slippage * position)
                pnl_pct = position * (exit_price - entry_price) / entry_price
                # Position notional is capped at risk_pct of equity -- this
                # is a real fix, not cosmetic: the previous formula
                # `equity * risk_pct * (pnl_pct / risk_pct)` algebraically
                # cancels to `equity * pnl_pct` for ANY risk_pct > 0, making
                # risk_per_trade a complete no-op and every trade bet full,
                # unleveraged, un-risk-managed equity on the raw price move.
                # Caught live: a CRUDE candidate's single-trade loss drove
                # equity negative (>100% "drawdown", NaN CAGR) during the
                # 2020 negative-oil-price event -- impossible for a trader
                # who was ever actually risking a bounded fraction of
                # capital per trade.
                #
                # Commission must scale by the SAME risk_pct: it was
                # previously charged as a flat % of total equity, which was
                # self-consistent only when position notional == full
                # equity (the old no-op sizing). With genuine fractional
                # sizing, an unscaled commission would be charged against a
                # notional far larger than what's actually deployed,
                # swamping every properly-risk-managed trade's real (small,
                # scaled-down) edge. Slippage needs no equivalent change --
                # it's already baked into entry/exit price, so it's already
                # proportional to whatever position size ultimately gets
                # multiplied through.
                pnl = realized_equity * pos_frac * pnl_pct
                realized_equity += pnl - realized_equity * pos_frac * commission
                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": i,
                    "direction": "LONG" if position > 0 else "SHORT",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct * 100,
                    "pnl_r": pnl_pct / risk_pct if risk_pct > 0 else 0,
                    # Fraction of equity this trade actually deployed. Recorded
                    # so "does a stop-out cost a constant amount" is CHECKABLE
                    # rather than asserted -- equity impact is pos_frac *
                    # pnl_pct, and neither factor alone tells you.
                    "pos_frac": pos_frac,
                })
                position = 0
                if signal != 0:
                    position = int(signal)
                    entry_price = fill_price * (1 + slippage * position)
                    pos_frac = (
                        self._notional_fraction(
                            risk_pct, entry_price,
                            atr_arr[i] if atr_arr is not None else None,
                            stop_atr_mult, max_leverage, self.DEFAULT_RISK_ATR_MULT)
                        if sizing_mode == "risk" else risk_pct
                    )
                    entry_idx = i
                    stop_level, tp_level = self._barrier_levels(
                        entry_price, position, atr_arr, i, stop_atr_mult, tp_atr_mult)
                    realized_equity -= realized_equity * pos_frac * commission
                else:
                    stop_level = tp_level = None
                equity = realized_equity

            # Holding -- mark to market against the still-open position's
            # entry price, so the return series (and therefore Sharpe/
            # Sortino/drawdown) reflects real day-to-day volatility while
            # a trade is open, not just the jump at its eventual close.
            elif position != 0:
                unrealized_pnl_pct = position * (price - entry_price) / entry_price
                equity = realized_equity + realized_equity * pos_frac * unrealized_pnl_pct
            else:
                equity = realized_equity

            # BARRIER CHECK -- runs AFTER the signal-flip block on purpose.
            #
            # CHRONOLOGY. A signal confirmed at bar i-1's close is acted on
            # at bar i's OPEN; a barrier is touched somewhere DURING bar i,
            # which is necessarily at or after that open. So a signal-flip
            # exit genuinely happens first, and only a position still open
            # after it can be stopped or targeted out on this bar. An entry
            # filled at this bar's open is eligible immediately -- a trade
            # can and does get stopped out on the bar it was opened.
            if position != 0 and (stop_level is not None or tp_level is not None):
                hi, lo, op = highs[i], lows[i], opens[i]
                hit_stop = stop_level is not None and (
                    lo <= stop_level if position > 0 else hi >= stop_level)
                hit_tp = tp_level is not None and (
                    hi >= tp_level if position > 0 else lo <= tp_level)

                if hit_stop or hit_tp:
                    # SAME-BAR TIE GOES TO THE STOP. Bar data cannot say
                    # which level was touched first, and assuming the
                    # favourable one is exactly how a backtest flatters
                    # itself. Same convention research/pdf_strategies.py
                    # _rr_exit already established on this platform.
                    if hit_stop:
                        level, reason = stop_level, "stop"
                    else:
                        level, reason = tp_level, "target"

                    # GAP HANDLING. A resting order fills at its level only
                    # if price actually traded through it during the bar.
                    # If the bar OPENED beyond the level, the gap already
                    # passed it and the realistic fill is the open -- worse
                    # than the stop, better than the target. Ignoring this
                    # would hand every gap-down its stop price back.
                    if position > 0:
                        raw = min(op, level) if reason == "stop" else max(op, level)
                    else:
                        raw = max(op, level) if reason == "stop" else min(op, level)

                    exit_price = raw * (1 - slippage * position)
                    pnl_pct = position * (exit_price - entry_price) / entry_price
                    pnl = realized_equity * pos_frac * pnl_pct
                    realized_equity += pnl - realized_equity * pos_frac * commission
                    trades.append({
                        "entry_idx": entry_idx,
                        "exit_idx": i,
                        "direction": "LONG" if position > 0 else "SHORT",
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "pnl_pct": pnl_pct * 100,
                        "pnl_r": pnl_pct / risk_pct if risk_pct > 0 else 0,
                    # Fraction of equity this trade actually deployed. Recorded
                    # so "does a stop-out cost a constant amount" is CHECKABLE
                    # rather than asserted -- equity impact is pos_frac *
                    # pnl_pct, and neither factor alone tells you.
                    "pos_frac": pos_frac,
                        "exit_reason": reason,
                    })
                    position = 0
                    stop_level = tp_level = None
                    equity = realized_equity

            equity_curve.append(equity)

        metrics = self._compute_metrics(trades, pd.Series(equity_curve), capital, len(df), periods_per_year)
        return BacktestResult(
            metrics=metrics,
            trades=trades,
            equity_curve=pd.Series(equity_curve),
        )

    def monte_carlo_sequencing_test(
        self,
        trades: list[dict[str, Any]],
        initial_capital: float,
        n_simulations: int = 1000,
        seed: int = 42,
    ) -> dict[str, Any]:
        """Is this strategy's edge distinguishable from random luck?

        Shuffles the SAME trades' PnL into random order n_simulations times
        and recomputes Sharpe/max-drawdown for each shuffle -- the null
        hypothesis is that the trade SEQUENCE carries no real information,
        i.e. any ordering of these exact wins/losses is equally likely.
        p_value_sharpe is the fraction of random shufflings that matched or
        beat the actual Sharpe; a strategy whose edge comes from genuine
        skill (not just a couple of lucky large wins) should beat MOST
        random orderings, landing p_value_sharpe close to 0.

        Deliberately answers a DIFFERENT question than run_backtest's own
        IS/OOS/robustness gate: that gate asks "does this generalize to
        unseen data / nearby parameters?"; this asks "is the in-sample edge
        itself real, or could this exact trade sequence just as easily have
        been random?" -- both can matter (e.g. 30 trades that clear
        MIN_TRADES but are dominated by one outsized win are exactly the
        case this catches that the existing gate does not).

        Adapted from HKUDS/Vibe-Trading's agent/backtest/validation.py
        (MIT-licensed) monte_carlo_test -- same technique, reshaped for
        this engine's own trade dicts (pnl_pct-based, not a TradeRecord
        with a precomputed dollar pnl): each trade's dollar PnL is derived
        here as pnl_pct/100 * initial_capital, a fixed-capital-basis
        simplification for the significance test only (run_backtest's own
        equity curve already correctly compounds against realized_equity;
        this test isn't trying to reproduce that, just to permute the same
        realized outcomes)."""
        if len(trades) < 3:
            return {"error": f"need at least 3 trades, got {len(trades)}", "p_value_sharpe": 1.0}

        pnls = np.array([t["pnl_pct"] / 100.0 * initial_capital for t in trades])

        def _path_metrics(seq: np.ndarray) -> tuple[float, float]:
            equity = initial_capital + np.cumsum(seq)
            prev = np.concatenate(([initial_capital], equity[:-1]))
            rets = np.where(prev != 0, (equity - prev) / prev, 0.0)
            std = rets.std()
            sharpe = float(rets.mean() / std) if std > 0 else 0.0
            peak = np.maximum.accumulate(equity)
            dd = (equity - peak) / np.where(peak > 0, peak, 1.0)
            return sharpe, float(dd.min())

        actual_sharpe, actual_max_dd = _path_metrics(pnls)

        rng = np.random.default_rng(seed)
        sim_sharpes = np.empty(n_simulations)
        sharpe_count = 0
        dd_count = 0
        for i in range(n_simulations):
            shuffled = rng.permutation(pnls)
            sim_sharpe, sim_max_dd = _path_metrics(shuffled)
            sim_sharpes[i] = sim_sharpe
            if sim_sharpe >= actual_sharpe:
                sharpe_count += 1
            if sim_max_dd >= actual_max_dd:  # less negative = "better"
                dd_count += 1

        return {
            "actual_sharpe": round(actual_sharpe, 4),
            "actual_max_dd": round(actual_max_dd, 4),
            "p_value_sharpe": round(sharpe_count / n_simulations, 4),
            "p_value_max_dd": round(dd_count / n_simulations, 4),
            "simulated_sharpe_mean": round(float(sim_sharpes.mean()), 4),
            "simulated_sharpe_std": round(float(sim_sharpes.std()), 4),
            "simulated_sharpe_p5": round(float(np.percentile(sim_sharpes, 5)), 4),
            "simulated_sharpe_p95": round(float(np.percentile(sim_sharpes, 95)), 4),
            "n_simulations": n_simulations,
            "n_trades": len(trades),
            "significant_at_5pct": sharpe_count / n_simulations < 0.05,
        }

    def _compute_metrics(
        self,
        trades: list[dict],
        equity: pd.Series,
        initial_capital: float,
        n_periods: int,
        periods_per_year: float = 252,
    ) -> BacktestMetrics:
        """Compute performance metrics from trades and equity curve."""
        if not trades:
            return BacktestMetrics()

        wins = [t for t in trades if t["pnl_pct"] > 0]
        losses = [t for t in trades if t["pnl_pct"] <= 0]
        win_rate = len(wins) / len(trades) if trades else 0

        gross_profit = sum(t["pnl_pct"] for t in wins)
        gross_loss = abs(sum(t["pnl_pct"] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        returns = equity.pct_change().dropna()
        sharpe = (returns.mean() / returns.std() * np.sqrt(periods_per_year)) if returns.std() > 0 else 0

        downside = returns[returns < 0]
        sortino = (
            returns.mean() / downside.std() * np.sqrt(periods_per_year)
            if len(downside) > 0 and downside.std() > 0
            else 0
        )

        peak = equity.expanding().max()
        drawdown = (equity - peak) / peak * 100
        max_dd = abs(drawdown.min())

        final_equity = float(equity.iloc[-1])
        total_return = (final_equity / initial_capital - 1) * 100
        years = max(n_periods / periods_per_year, 0.1)
        # A ruined account has negative final equity, and a NEGATIVE base
        # raised to a fractional power is NaN -- so the worst possible outcome
        # was being reported as a MISSING number rather than a total loss, and
        # anything ranking on cagr silently skipped it. Reachable since
        # risk-based sizing allowed leverage above 1x; previously observed on a
        # CRUDE candidate during the 2020 negative-oil event.
        if final_equity <= 0:
            cagr = -100.0
        else:
            cagr = ((final_equity / initial_capital) ** (1 / years) - 1) * 100
        calmar = cagr / max_dd if max_dd > 0 else 0

        avg_win_r = np.mean([t["pnl_r"] for t in wins]) if wins else 0
        avg_loss_r = np.mean([t["pnl_r"] for t in losses]) if losses else 0
        expectancy = win_rate * avg_win_r + (1 - win_rate) * avg_loss_r

        return BacktestMetrics(
            total_trades=len(trades),
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            max_drawdown_pct=max_dd,
            total_return_pct=total_return,
            cagr=cagr,
            avg_win_r=avg_win_r,
            avg_loss_r=avg_loss_r,
            expectancy=expectancy,
            recovery_factor=total_return / max_dd if max_dd > 0 else 0,
        )

    def _parameter_sensitivity(
        self,
        df: pd.DataFrame,
        strategy_fn: Callable,
        capital: float,
        risk_pct: float,
        commission: float,
        slippage: float,
        periods_per_year: float = 252,
        perturbation: float = 0.1,
        base_result: Optional[BacktestResult] = None,
    ) -> float:
        """Test strategy robustness to +-10% parameter perturbation.

        base_result: OPTIONAL already-computed _simulate(df, strategy_fn,
        capital, risk_pct, commission, slippage, periods_per_year) result.
        None (default) computes it here, exactly as before. Added
        2026-08-02: run_backtest's own is_result is ALREADY exactly this
        same call with these exact same arguments -- computing it again
        here was a second full bar-by-bar simulation (not just a
        redundant strategy_fn call) for a result already sitting in the
        caller's hands. Also computes strategy_fn(df) once and shares it
        across the two perturbation _simulate calls (see _simulate's own
        docstring) -- risk_pct/commission never affect what the strategy
        signal itself is, only how a fixed signal gets sized/costed."""
        base = base_result if base_result is not None else self._simulate(
            df, strategy_fn, capital, risk_pct, commission, slippage, periods_per_year
        )
        base_sharpe = base.metrics.sharpe_ratio
        if base_sharpe == 0:
            return 0.0

        signals = strategy_fn(df)
        sharpes = [base_sharpe]
        for mult in [1 - perturbation, 1 + perturbation]:
            result = self._simulate(
                df, strategy_fn, capital, risk_pct * mult, commission * mult, slippage, periods_per_year,
                signals=signals,
            )
            sharpes.append(result.metrics.sharpe_ratio)

        stability = 1 - (np.std(sharpes) / (abs(np.mean(sharpes)) + 1e-9))
        return max(0.0, min(1.0, stability))

    def monte_carlo(
        self,
        trades: list[dict],
        n_simulations: int = 1000,
        initial_capital: float = 10_000.0,
    ) -> EngineResult:
        """
        Monte Carlo simulation by randomizing trade order.

        NOT the same test as monte_carlo_sequencing_test, despite sharing
        the shuffle. This one reports RUIN RISK -- how often a reordering
        of the same trades draws down past a threshold -- and is consumed
        by e30_adversarial_testing. The sequencing test reports a p-value
        for whether the Sharpe survives reordering. Neither is Stage 0's
        synthetic_null_edge, which asks a different question again: how
        often the pipeline finds a 'winner' in data with no edge at all.
        Name left as-is because e30 calls it; the distinction is documented
        here rather than churned through another engine.

        Args:
            trades: List of trade dicts with pnl_r field.
            n_simulations: Number of simulation paths.
            initial_capital: Starting capital.

        Returns:
            EngineResult with risk of ruin and distribution stats.
        """
        if not trades:
            return EngineResult(success=False, message="No trades for Monte Carlo")

        pnls = [t.get("pnl_r", t.get("pnl_pct", 0) / 100) for t in trades]
        final_equities = []
        max_drawdowns = []
        ruin_count = 0

        for _ in range(n_simulations):
            shuffled = np.random.choice(pnls, size=len(pnls), replace=True)
            equity = initial_capital
            peak = equity
            max_dd = 0.0
            ruined = False

            for pnl_r in shuffled:
                equity *= (1 + pnl_r * 0.01)
                peak = max(peak, equity)
                dd = (peak - equity) / peak
                max_dd = max(max_dd, dd)
                if equity <= initial_capital * 0.5:
                    ruined = True
                    break

            final_equities.append(equity)
            max_drawdowns.append(max_dd * 100)
            if ruined:
                ruin_count += 1

        risk_of_ruin = ruin_count / n_simulations * 100
        return EngineResult(
            success=True,
            data={
                "risk_of_ruin_pct": risk_of_ruin,
                "median_final_equity": float(np.median(final_equities)),
                "p5_final_equity": float(np.percentile(final_equities, 5)),
                "p95_final_equity": float(np.percentile(final_equities, 95)),
                "median_max_dd": float(np.median(max_drawdowns)),
                "n_simulations": n_simulations,
            },
            message=f"Monte Carlo: Risk of Ruin={risk_of_ruin:.2f}%",
        )

    def stress_test(
        self,
        df: pd.DataFrame,
        strategy_fn: Callable,
        period_name: str,
        capital: float = 100_000.0,
        risk_pct: float = 0.01,
    ) -> EngineResult:
        """
        Run strategy against historical stress periods.

        Args:
            df: Full OHLCV DataFrame.
            strategy_fn: Strategy signal function.
            period_name: Key from STRESS_PERIODS.
            capital: Initial capital.
            risk_pct: Risk per trade.

        Returns:
            EngineResult with stress period metrics.
        """
        if period_name not in self.STRESS_PERIODS:
            return EngineResult(
                success=False,
                message=f"Unknown period. Available: {list(self.STRESS_PERIODS.keys())}",
            )

        start, end = self.STRESS_PERIODS[period_name]
        mask = (df["timestamp"] >= start) & (df["timestamp"] <= end)
        stress_df = df[mask].copy()

        if len(stress_df) < 10:
            return EngineResult(success=False, message=f"Insufficient data for {period_name}")

        result = self._simulate(stress_df, strategy_fn, capital, risk_pct, 0.001, 0.0005)
        return EngineResult(
            success=True,
            data=result,
            message=f"Stress test {period_name}: DD={result.metrics.max_drawdown_pct:.1f}%",
        )

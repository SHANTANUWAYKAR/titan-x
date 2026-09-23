"""
Module: engine.py
Description: Engine 51 — Signal Intelligence System.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-08-02
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from project_titan_x.core.config import get_asset, get_settings, is_asset_supported
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e04_macro.engine import MacroSnapshot
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e05_economic_calendar.engine import CalendarSnapshot, EconomicCalendarEngine
from project_titan_x.engines.e08_regime.engine import RegimeClassification
from project_titan_x.engines.e06_fundamental.engine import FundamentalSnapshot, relevance_for_symbol
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine, TechnicalSnapshot, TrendDirection
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.engines.e24_strategy_research.strategies import STRATEGIES, donchian_breakout_volume_confirmed
from project_titan_x.engines.e11_microstructure.engine import MarketMicrostructureEngine
from project_titan_x.engines.e45_risk.engine import RiskManagementEngine, TradeRiskProposal

logger = logging.getLogger(__name__)
settings = get_settings()

_CALIBRATED_PARAMS_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e51_signals"
_TUNED_PARAM_KEYS = ("entry_threshold", "adx_divisor", "momentum_divisor", "disagreement_dampening")


def _load_tuned_params(symbol: str, timeframe: str) -> Optional[dict]:
    """Load a backtest-validated PARAMETER tuning (entry_threshold/
    adx_divisor/momentum_divisor/disagreement_dampening) for
    _vectorized_signal_series/_determine_direction's own formula, if
    scripts/training/train_e51_thresholds.py found one that clears E26's
    real in-sample+out-of-sample validation bar for this EXACT
    symbol+timeframe (see data/models/e51_signals/*_tuned_params.json).
    Distinct from _load_strategy_override: this keeps the SAME formula,
    just re-tunes its constants -- a genuinely different archetype (like
    SP500's Donchian breakout) belongs in the override file instead, and
    that file is checked FIRST by generate_signal/validate_historical_edge
    so a structural override always wins over a mere parameter tune.
    Returns None (shipped hardcoded defaults apply) for every other
    symbol/timeframe -- a tuning proven on one asset's history must never
    be silently applied to an asset it was never validated against."""
    path = _CALIBRATED_PARAMS_DIR / f"{symbol}_{timeframe}_tuned_params.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return {k: data[k] for k in _TUNED_PARAM_KEYS if k in data}
    except Exception as e:
        logger.warning("Failed to load tuned signal params from %s: %s", path, e)
        return None


# Overrides suppressed by the Stage 0 gate this process, keyed by
# (symbol, timeframe). Populated by _load_strategy_override; read by
# stage0_skipped_overrides() for auditing what stopped firing.
_STAGE0_SKIPPED: dict[tuple[str, str], dict] = {}


def stage0_skipped_overrides() -> dict[tuple[str, str], dict]:
    """Every override the Stage 0 gate suppressed so far in this process."""
    return dict(_STAGE0_SKIPPED)


def _load_strategy_override(symbol: str, timeframe: str) -> Optional[dict]:
    """Load a backtest-validated STRUCTURAL strategy override -- a genuinely
    different direction-determination archetype, not just a parameter tweak
    within the baseline EMA-stack composite rule -- for this EXACT symbol+
    timeframe, if scripts/training/research_signal_strategies*.py found one
    that clears E26's full walk-forward validation bar (see
    data/models/e51_signals/strategy_research_report*.json for the full
    comparison that produced it). Returns None (the baseline composite rule
    applies) for every other symbol/timeframe -- an archetype proven on
    SP500 daily data must never be silently applied to an asset/timeframe
    it was never validated against. This exists because the baseline rule's
    OWN parameter grid (train_e51_signals.py) found zero validated configs
    for 10 of 11 tested assets -- the problem was the rule's structure, not
    its constants, so some assets need an entirely different rule rather
    than a re-tuned version of the same one.

    STAGE 0 GATE (added 2026-09-07; default flipped to DENY-BY-DEFAULT
    2026-09-13 -- see docs/UPGRADE_ROADMAP.md P0 item 1). An override is
    only treated as live if it carries an EXPLICIT
    `"stage0": {"status": "VALIDATED"}` tag. Anything else -- an explicit
    `"UNVALIDATED"` tag, a missing `stage0` block entirely, or a
    malformed one -- falls back to the baseline composite rule, the same
    path an asset with no override at all takes.

    This is a deliberate reversal from the gate's original design (missing
    tag defaulted to ACTIVE, only an explicit UNVALIDATED tag vetoed).
    That design recurred as a real gap THREE times in one session: every
    time `_promote()` (engines/e24_strategy_research/engine.py) or an
    external promotion process wrote a fresh override file, it went live
    immediately -- tagging is a separate pass
    (`research/score_overrides_stage0.py` + `scripts/apply_stage0_tags.py`)
    that has to be remembered and re-run every time, and forgetting it is
    silent (no error, just a live-but-unvalidated rule). Denying by
    default closes this structurally instead of relying on remembering to
    re-tag after every promotion.

    Measured against a synthetic no-edge null: as of the last full
    tagging run, 43 of 45 live overrides sit below the 95th percentile of
    what this pipeline produces from pure noise at their own timeframe
    (see docs/STAGE0_FINDINGS.md) and are explicitly tagged UNVALIDATED;
    2 are explicitly tagged VALIDATED. Driving live signals from a rule
    indistinguishable from noise is worse than having no override, because
    it displaces a rule that was at least never claimed to be validated.

    Reversible by design: the tag is data, not code. Add/edit the
    `stage0` block (or `git checkout` a previously-tagged version of the
    file) to change an override's live status -- but going live now
    requires adding an explicit VALIDATED tag, not removing anything.
    """
    path = _CALIBRATED_PARAMS_DIR / f"{symbol}_{timeframe}_strategy_override.json"
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text())
    except Exception as e:
        logger.warning("Failed to load strategy override from %s: %s", path, e)
        return None

    # Added 2026-09-13 (docs/UPGRADE_ROADMAP.md P2 item 10): a real
    # retirement tombstone, closing e25_strategy_lifecycle's own
    # documented "retired" gap ("no real mechanism exists anywhere yet...
    # if a future engine adds a real retirement flow, e.g. a retired_at
    # field, this engine should read that"). Checked BEFORE stage0 --
    # retirement is a stronger, terminal statement than "not yet
    # validated" and must veto regardless of stage0 status (a stale
    # VALIDATED tag on an explicitly retired override must never
    # resurrect it).
    if isinstance(doc, dict) and doc.get("retired_at"):
        key = (symbol, timeframe)
        if key not in _STAGE0_SKIPPED:
            _STAGE0_SKIPPED[key] = {"status": "RETIRED", "retired_at": doc.get("retired_at")}
            logger.warning(
                "RETIRED: %s %s override (%s) was explicitly retired at %s -- "
                "falling back to baseline composite rule. Reason: %s",
                symbol, timeframe, doc.get("strategy"), doc.get("retired_at"),
                doc.get("retired_reason", "unspecified"),
            )
        return None

    stage0 = doc.get("stage0") if isinstance(doc, dict) else None
    if isinstance(stage0, dict) and stage0.get("status") == "VALIDATED":
        return doc

    key = (symbol, timeframe)
    # Deduped per process, not per call. Every DISTINCT override that
    # isn't live is still reported -- which is the question being asked --
    # while a scan loop touching the same assets on every cycle does not
    # bury that signal under thousands of repeats.
    if key not in _STAGE0_SKIPPED:
        if isinstance(stage0, dict):
            _STAGE0_SKIPPED[key] = stage0
            m = stage0.get("measured", {})
            logger.warning(
                "STAGE 0 SKIP: %s %s override (%s) is %s -- "
                "null percentile %s (bar %s), %s trades (bar %s); "
                "falling back to baseline composite rule. Reasons: %s",
                symbol, timeframe, doc.get("strategy"), stage0.get("status", "not VALIDATED"),
                m.get("null_percentile"),
                (stage0.get("bar") or {}).get("min_null_percentile"),
                m.get("trades"), (stage0.get("bar") or {}).get("min_trades"),
                "; ".join(stage0.get("reasons") or ["unspecified"]),
            )
        else:
            _STAGE0_SKIPPED[key] = {"status": "NO_TAG"}
            logger.warning(
                "STAGE 0 SKIP: %s %s override (%s) has no stage0 tag at all -- "
                "deny-by-default, falling back to baseline composite rule. "
                "Run research/score_overrides_stage0.py + scripts/apply_stage0_tags.py "
                "to evaluate and tag it.",
                symbol, timeframe, doc.get("strategy") if isinstance(doc, dict) else None,
            )
    return None


@dataclass
class TradingSignal:
    """Complete trading signal with all required metadata."""

    asset: str
    direction: str  # LONG or SHORT
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_percent: float
    expected_value: float
    confidence_score: int
    regime: str
    supporting_evidence: list[str] = field(default_factory=list)
    invalidation: str = ""
    historical_context: str = ""
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    checks_passed: dict[str, bool] = field(default_factory=dict)
    edge_validation: Optional["EdgeValidationResult"] = None
    macro_context: Optional[dict] = None
    fundamental_context: Optional[dict] = None
    microstructure_context: Optional[dict] = None
    economic_calendar_context: Optional[dict] = None
    knowledge_context: Optional[dict] = None
    news_context: Optional[dict] = None
    # Added 2026-09-11: {check_name: error_message} for any confluence
    # check that genuinely raised during THIS call (see
    # _apply_confluence_adjustments' own docstring for why this exists --
    # a caught exception was previously indistinguishable from a
    # legitimate "checked, found neutral" read, both silently producing
    # the same confidence and the same absent evidence line). None (not
    # an empty dict) when every check either succeeded or was never wired
    # -- same "None means nothing to report" convention as every other
    # *_context field here. Informational only, read by nothing else in
    # this class.
    confluence_errors: Optional[dict] = None
    # Added 2026-08-05 (E21/E23) -- both informational only, same
    # convention as every other *_context field: attached for
    # transparency/audit, read by NOTHING else in this class, never
    # touch confidence or direction (E23 in particular exists
    # specifically to "avoid deterministic predictions" per its own
    # master-prompt scope -- using it as a hard gate would contradict
    # that).
    feature_context: Optional[dict] = None
    forecast_context: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize signal to API response format."""
        return {
            "asset": self.asset,
            "direction": self.direction,
            "entry": round(self.entry, 4),
            "stop_loss": round(self.stop_loss, 4),
            "take_profit_1": round(self.take_profit_1, 4),
            "take_profit_2": round(self.take_profit_2, 4),
            "risk_percent": self.risk_percent,
            "expected_value": round(self.expected_value, 2),
            "confidence_score": self.confidence_score,
            "regime": self.regime,
            "supporting_evidence": self.supporting_evidence,
            "invalidation": self.invalidation,
            "historical_context": self.historical_context,
            "status": self.status,
            # bool(...) cast defends against numpy.bool_ leaking in from any
            # check computed via a numpy/pandas-typed comparison (e.g. an ATR-
            # derived value) -- unlike numpy.float64 (a genuine subclass of
            # Python float, serializes fine), numpy.bool_ is NOT a subclass of
            # Python bool and crashes FastAPI's jsonable_encoder outright.
            "checks_passed": {k: bool(v) for k, v in self.checks_passed.items()},
            "edge_validation": self.edge_validation.to_dict() if self.edge_validation else None,
            "macro_context": self.macro_context,
            "fundamental_context": self.fundamental_context,
            "microstructure_context": self.microstructure_context,
            "economic_calendar_context": self.economic_calendar_context,
            "knowledge_context": self.knowledge_context,
            "news_context": self.news_context,
            "confluence_errors": self.confluence_errors,
            "feature_context": self.feature_context,
            "forecast_context": self.forecast_context,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class EdgeValidationResult:
    """
    Result of backtesting THIS engine's own direction rule against real
    history before trusting a live signal from it.

    Mirrors the edge-gate/alpha-decay discipline already proven valuable in
    the other TITAN-X system (Command Center): a signal that "looks
    reasonable" today and a signal with a real statistical edge are
    different things, and the only way to tell them apart is testing the
    exact rule against data it wasn't eyeballed against.
    """

    status: str  # proven_positive_edge | proven_negative_edge | not_significant | insufficient_data
    total_trades: int
    win_rate: float
    sharpe_ratio: float
    max_drawdown_pct: float
    passed_validation: bool
    message: str
    # Beta-Binomial Bayesian update of this edge's TRUE win rate (E12
    # bayesian_win_rate_update), computed from this same backtest's win/loss
    # counts. None when no quant_engine was injected. Purely descriptive --
    # a wide credible interval on a small sample is real information (this
    # "passed" edge could still be a coin flip), but never changes
    # status/passed_validation/confidence; those stay the raw Sharpe/p-value
    # read they always were.
    bayesian_posterior_mean: Optional[float] = None
    bayesian_credible_interval_90pct: Optional[tuple] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "passed_validation": bool(self.passed_validation),
            "message": self.message,
            "bayesian_posterior_mean": self.bayesian_posterior_mean,
            "bayesian_credible_interval_90pct": self.bayesian_credible_interval_90pct,
        }


class SignalIntelligenceEngine(BaseEngine):
    """
    Signal Intelligence System — generates validated trading signals.

    Signal fires only when ALL criteria pass:
    - Confidence > 80%
    - R:R >= 2:1
    - Regime matches strategy
    - Asset in supported whitelist (no equities)
    - CRO risk approval
    """

    engine_id = "e51_signals"
    engine_name = "Signal Intelligence System"
    version = "1.0.0"

    # Below this Sharpe on a validated backtest, a signal is treated as a
    # proven negative edge and vetoed outright -- same threshold philosophy
    # as Command Center's edge_gate.py (a negative average R-multiple over a
    # real sample is not noise, it's the rule telling you it loses money).
    NEGATIVE_EDGE_SHARPE_THRESHOLD = 0.0

    def __init__(
        self,
        risk_engine: Optional[RiskManagementEngine] = None,
        technical_engine: Optional[TechnicalAnalysisEngine] = None,
        backtesting_engine: Optional[BacktestingEngine] = None,
        microstructure_engine: Optional[MarketMicrostructureEngine] = None,
        economic_calendar_engine: Optional[EconomicCalendarEngine] = None,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        cross_asset_engine: Optional[Any] = None,
        news_engine: Optional[Any] = None,
        sentiment_engine: Optional[Any] = None,
        derivatives_engine: Optional[Any] = None,
        commodity_engine: Optional[Any] = None,
        crypto_engine: Optional[Any] = None,
        fixed_income_engine: Optional[Any] = None,
        credit_engine: Optional[Any] = None,
        quant_engine: Optional[Any] = None,
        global_liquidity_engine: Optional[Any] = None,
        feature_engineering_engine: Optional[Any] = None,
        alpha_research_engine: Optional[Any] = None,
        forecasting_engine: Optional[Any] = None,
        meta_learning_engine: Optional[Any] = None,
        model_risk_engine: Optional[Any] = None,
    ) -> None:
        super().__init__()
        self._risk_engine = risk_engine or RiskManagementEngine()
        # All optional and None by default: without them, generate_signal()
        # behaves exactly as before (no edge-gate check, no microstructure/
        # calendar/knowledge context). Pass real instances (as registry.py
        # does) to turn them on.
        self._technical_engine = technical_engine
        self._backtesting_engine = backtesting_engine
        self._microstructure_engine = microstructure_engine
        self._economic_calendar_engine = economic_calendar_engine
        self._knowledge_engine = knowledge_engine
        # Confluence collaborators (see _apply_confluence_adjustments) --
        # every one of this platform's real intelligence engines gets a
        # say in ONE signal's confidence, inspired by Command Center's own
        # higher-timeframe/cross-asset confluence multipliers but broader
        # in coverage since this platform has far more real engines than
        # Command Center does. All optional/None by default: without them,
        # confluence for that specific engine is silently skipped, never
        # blocks the signal.
        self._cross_asset_engine = cross_asset_engine
        self._news_engine = news_engine
        self._sentiment_engine = sentiment_engine
        self._derivatives_engine = derivatives_engine
        self._commodity_engine = commodity_engine
        self._crypto_engine = crypto_engine
        self._fixed_income_engine = fixed_income_engine
        self._credit_engine = credit_engine
        # Also powers _bayesian_edge_calibration's enrichment of
        # validate_historical_edge -- a statistically-principled companion
        # to the raw Sharpe/p-value edge-gate check, not a replacement.
        self._quant_engine = quant_engine
        # Added 2026-08-02, after e19_global_liquidity went from
        # permanently inert (no FRED_API_KEY) to genuinely live (a real,
        # verified no-key FRED CSV endpoint) this same session -- see
        # _confluence_global_liquidity for the actual read.
        self._global_liquidity_engine = global_liquidity_engine
        # Added 2026-08-05 (E21/E22/E23, see each engine's own module
        # docstring). E21/E23 are INFORMATIONAL only (feature_context/
        # forecast_context on the signal) -- never touch confidence or
        # direction, matching e21's "mechanical assembly" and e23's own
        # "avoid deterministic predictions" scope exactly. E22 is the one
        # of the three wired into _apply_confluence_adjustments as a
        # genuine confluence check (see _confluence_alpha_research) --
        # same "only when validated" discipline as E17's crypto confluence.
        self._feature_engineering_engine = feature_engineering_engine
        self._alpha_research_engine = alpha_research_engine
        self._forecasting_engine = forecasting_engine
        # Added 2026-08-05 (E37/E39, see each engine's own module
        # docstring). Both wired as genuine confluence checks, same
        # "only when validated" discipline as E17/E22: E37 only nudges
        # confidence for an asset its own precomputed regime_fit_database
        # flagged as genuinely regime_dependent; E39 only nudges (always
        # downward, never up) when this asset's LIVE model file is
        # missing the governance fields its own training script always
        # writes -- a real, honest "this wasn't validated by the real
        # pipeline" signal, never a fabricated risk score.
        self._meta_learning_engine = meta_learning_engine
        self._model_risk_engine = model_risk_engine

    def initialize(self) -> EngineResult:
        self._risk_engine.initialize()
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Signal Intelligence System initialized")

    def health_check(self) -> EngineResult:
        return self._risk_engine.health_check()

    def generate_signal(
        self,
        symbol: str,
        df: pd.DataFrame,
        technical: TechnicalSnapshot,
        regime: RegimeClassification,
        macro_risk_score: float = 0.0,
        macro_snapshot: Optional[MacroSnapshot] = None,
        fundamental_snapshot: Optional[FundamentalSnapshot] = None,
        news_items: Optional[list] = None,
        cross_asset_result: Optional[EngineResult] = None,
        enriched_df: Optional[pd.DataFrame] = None,
        include_extended_context: bool = True,
    ) -> EngineResult:
        """
        Generate a trading signal for an asset if all criteria met.

        Args:
            symbol: Asset symbol.
            df: OHLCV DataFrame.
            technical: Technical snapshot.
            regime: Regime classification.
            macro_risk_score: Macro risk-on/off score (already folded into
                direction/confidence via _determine_direction).
            macro_snapshot: Full E03 macro snapshot, attached to every asset's
                output for transparency -- informational only, does not
                change anything beyond what macro_risk_score already does.
            fundamental_snapshot: Full E06 fundamental snapshot (global, not
                per-asset data), attached to every asset with an HONEST
                relevance tag -- real yield/WTI-Brent are only surfaced for
                GOLD/SILVER/CRUDE respectively, never fabricated for assets
                they have no financial relationship to. See
                e06_fundamental.relevance_for_symbol.
            news_items: Pre-fetched E03 headlines (global, not per-asset --
                the same RSS feeds regardless of which asset is being
                evaluated), used for the news/sentiment confluence check.
                None (default) makes this method fetch headlines itself,
                correct for a single-symbol call. scan_all_assets fetches
                ONCE and passes the same list into every asset's call --
                without this, a 13-asset scan re-fetched all 4 RSS feeds
                13 times (52 redundant network round-trips), which was the
                dominant cost in a full scan (~8-10s/asset, ~150s total).
            cross_asset_result: Pre-computed E10 EngineResult (global, not
                per-asset -- one correlation matrix across ~14 tracked
                tickers, same regardless of which asset is being
                evaluated). None (default) makes this method call
                cross_asset_engine.analyze() itself. scan_all_assets calls
                it ONCE and passes the same result into every asset --
                without this, E10.analyze() (which live-fetches ~14
                tickers from Yahoo Finance every call) ran once PER ASSET,
                ~14x13=182 redundant live fetches for a 13-asset scan --
                the single largest remaining cost after the news fix
                above (measured ~5-9s/asset even with news shared).
            enriched_df: Pre-computed full-history technical_engine.analyze()
                output (its `data["df"]`) for this exact `df`, if the caller
                already ran it (scan_all_assets / api/main.py / the E00
                workflow all call technical_engine.analyze() to build
                `technical` before calling this method, then discarded the
                enriched frame). None (default) makes validate_historical_edge
                recompute it via a second full analyze() call, correct for a
                standalone caller (e.g. /api/v1/signals/validate-edge) that
                never ran analyze() itself. Without this, every signal call
                whose caller already has an enriched frame re-ran the entire
                EMA/RSI/MACD/ADX/SMC/Wyckoff/harmonic-pattern pipeline a
                second time on the same data for no reason.
            include_extended_context: Added 2026-08-21 as a real, measured
                scan-performance fix -- when False, skips building
                microstructure_context, economic_calendar_context,
                knowledge_context, feature_context, and forecast_context.
                Safe to skip because every one of those five is already
                documented, individually, as "informational only... never
                changes confidence or direction" (see each _build_*_context
                method's own docstring) -- they exist purely for transparency
                in a single-symbol detail view, and were never part of the
                direction/confidence/evidence computation. Live-profiled:
                these five together cost ~1.5-2s of real per-asset work
                (feature_context alone measured 1.15s warm), the dominant
                share of generate_signal's ~2.1-2.9s total -- for a
                29-asset scan across 6 workers this is the single largest
                controllable contributor to wall-clock scan time. Defaults
                to True so every existing single-symbol caller (/signals/
                generate, /signals/validate-edge, direct engine callers)
                keeps its exact prior behavior unchanged; only
                scan_all_assets passes False. macro_context/
                fundamental_context (cheap, already batched by the caller)
                and everything that actually feeds confidence/evidence
                (news/cross-asset confluence, edge validation) are
                UNAFFECTED by this flag either way.

        Returns:
            EngineResult with TradingSignal or None if no signal.
        """
        try:
            self._set_status(EngineStatus.RUNNING)
            checks: dict[str, bool] = {}
            asset_def = get_asset(symbol)
            asset_name = asset_def.symbol if asset_def else symbol

            macro_context = self._build_macro_context(macro_snapshot)
            fundamental_context = self._build_fundamental_context(asset_name, fundamental_snapshot)
            # microstructure_context/economic_calendar_context are NOT
            # behind include_extended_context, despite their own docstrings
            # claiming "informational only, never changes confidence" --
            # verified false: _apply_confluence_adjustments below (~L1225,
            # ~L1229) genuinely multiplies confidence by 0.9/0.85 off these
            # two specifically. Always computed, in every call, regardless
            # of the flag -- a real, pre-existing docstring/behavior
            # mismatch caught while building this optimization, not
            # something safe to skip.
            microstructure_context = self._build_microstructure_context(
                df, asset_name, technical.timeframe, asset_def.asset_class.value if asset_def else ""
            )
            economic_calendar_context = self._build_economic_calendar_context(asset_name)
            if include_extended_context:
                knowledge_context = self._build_knowledge_context(regime, asset_name)
                feature_context = self._build_feature_context(asset_name, df, technical.timeframe, technical)
                forecast_context = self._build_forecast_context(asset_name, asset_def)
            else:
                # Honest None, not a fabricated/cached stand-in -- a scan
                # result's card can re-fetch the full single-symbol signal
                # (with these populated) if a trader clicks into it. Confirmed
                # inert: unlike microstructure/economic_calendar above, none
                # of these three appear anywhere in _apply_confluence_adjustments
                # or any other conditional logic in this file -- only in
                # metadata dicts and the final TradingSignal's own fields.
                knowledge_context = None
                feature_context = None
                forecast_context = None

            # Check 1: Asset supported (no equities)
            checks["asset_supported"] = is_asset_supported(symbol)
            if not checks["asset_supported"]:
                return EngineResult(
                    success=True,
                    data=None,
                    message=f"Asset {symbol} not supported — equities excluded",
                    metadata={
                        "macro_context": macro_context,
                        "fundamental_context": fundamental_context,
                        "microstructure_context": microstructure_context,
                        "economic_calendar_context": economic_calendar_context,
                        "knowledge_context": knowledge_context,
                        "feature_context": feature_context,
                        "forecast_context": forecast_context,
                    },
                )

            close = float(df["close"].iloc[-1])
            atr = technical.indicators.get("atr", close * 0.01)

            # Determine direction: a validated, asset-specific structural
            # strategy override (see _load_strategy_override) takes priority
            # over the baseline composite rule when one exists for this
            # EXACT symbol+timeframe -- e.g. SP500 daily uses a validated
            # Donchian breakout because the baseline rule found zero edge
            # for it (and its own parameter grid found none either, see
            # data/models/e51_signals/GC=F_1d_training_report.json-style
            # reports). bypass_regime_filter is set alongside it because the
            # regime/ADX filter was never part of what was actually
            # backtested for the override -- applying it now would block
            # trades the validation run never excluded.
            lookup_symbol = asset_def.yahoo_symbol if asset_def else symbol
            strategy_override = _load_strategy_override(lookup_symbol, technical.timeframe)
            bypass_regime_filter = False
            # Populated only on the general heuristic path below -- an
            # asset with its own validated structural override keeps its
            # confidence undiluted by confluence (see
            # _apply_confluence_adjustments' own docstring), so it has no
            # news confluence read to attach either; stays None/empty for
            # that path, an honest gap rather than a fabricated one.
            news_context: dict = {}
            confluence_errors: dict = {}
            if strategy_override:
                direction, confidence, evidence = self._determine_direction_from_override(
                    df, strategy_override, enriched_df=enriched_df
                )
                checks["confidence_threshold"] = confidence >= strategy_override.get("min_confidence", 50)
                bypass_regime_filter = True
            else:
                tuned_params = _load_tuned_params(lookup_symbol, technical.timeframe)
                direction, confidence, evidence = self._determine_direction(
                    technical, regime, macro_risk_score, tuned_params
                )
                if tuned_params:
                    evidence.append(f"Using validated tuned parameters {tuned_params} for this asset")
                if direction is not None:
                    confidence = self._apply_confluence_adjustments(
                        direction, confidence, asset_name,
                        microstructure_context, economic_calendar_context, evidence,
                        news_items=news_items, cross_asset_result=cross_asset_result,
                        news_context_out=news_context,
                        confluence_errors_out=confluence_errors,
                    )
                checks["confidence_threshold"] = confidence >= settings.min_signal_confidence

            if direction is None:
                return EngineResult(
                    success=True,
                    data=None,
                    message="No clear directional bias",
                    metadata={
                        "checks": checks,
                        "direction": None,
                        "confidence": confidence,
                        "macro_context": macro_context,
                        "fundamental_context": fundamental_context,
                        "microstructure_context": microstructure_context,
                        "economic_calendar_context": economic_calendar_context,
                        "knowledge_context": knowledge_context,
                        "feature_context": feature_context,
                        "forecast_context": forecast_context,
                    },
                )

            # Calculate levels using ATR (accurate, volatility-adjusted)
            # Note (2026-08-03): cross-referencing this engine against the
            # YouTube knowledge pipeline's extraction (Mind Math Money, 97
            # videos) found this engine's 1.5x ATR stop distance sits at
            # the conservative end of a real, repeatedly-taught range --
            # "a very common rule of thumb is that we usually want the
            # stop loss to be 1.5 to 2x the ATR" -- so this constant is
            # already within convention, not a mismatch needing a change.
            # The R:R RATIO structure below (2:1 at TP1, 3:1 at TP2) also
            # already matches the source material's own convention
            # ("stop-loss multiple of 2x, a common profit target multiple
            # is 4x" = 2:1). Left as-is; a move to the wider (2.0x) end of
            # the taught range would in any case need real validation
            # first, not a swap on a rule of thumb alone (Rule 3) -- and
            # per direct inspection of e26_backtesting._simulate, this
            # codebase doesn't yet have a path-dependent, level-based
            # backtest (it's signal-based, not bar-by-bar stop/target
            # fills) to validate an ATR stop-multiple against anyway.
            stop_distance = atr * 1.5
            if direction == "LONG":
                stop_loss = close - stop_distance
                take_profit_1 = close + stop_distance * 2.0
                take_profit_2 = close + stop_distance * 3.0
                invalidation = f"Candle closes below {stop_loss:.4f}"
            else:
                stop_loss = close + stop_distance
                take_profit_1 = close - stop_distance * 2.0
                take_profit_2 = close - stop_distance * 3.0
                invalidation = f"Candle closes above {stop_loss:.4f}"

            # risk_reward and regime_match are surfaced as evidence/context,
            # not hard gates that suppress the signal outright -- matching
            # this platform's own prior system (command_center/signal_engine.py):
            # it always showed entry/stop/target with the real computed R:R
            # and used regime as a confidence-adjusting confluence check, not
            # a binary pass/fail. Neither of these is E45's actual risk veto
            # (that's cro_approved below, untouched, per CLAUDE.md Rule 5 --
            # E45 keeps absolute veto authority) nor the proven-negative-edge
            # block (edge_not_proven_negative below, also untouched) -- these
            # two were this engine's OWN additional strictness on top of
            # those two real safety rules, and independently suppressed
            # signals that would otherwise have shown with an honest caveat.
            risk_amount = abs(close - stop_loss)
            reward_amount = abs(take_profit_1 - close)
            rr_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
            # Same floating-point tolerance as e45_risk.evaluate_trade's
            # own R:R check, for the same reason (see that method's
            # comment) -- take_profit_1 above is constructed as EXACTLY
            # 2x stop_distance from close, but reward_amount/risk_amount
            # are recomputed via subtraction, which can round the ratio
            # to just under 2.0 for a real, non-hypothetical fraction of
            # price/ATR combinations.
            if rr_ratio < settings.min_risk_reward_ratio - 1e-9:
                evidence.append(
                    f"Risk:reward is {rr_ratio:.1f}:1, below the {settings.min_risk_reward_ratio:.0f}:1 "
                    "guideline -- shown anyway, weigh it yourself"
                )

            risk_pct = min(settings.default_risk_per_trade_pct, settings.max_risk_per_trade_pct)
            if bypass_regime_filter:
                evidence.append("Regime filter bypassed — not part of what this strategy override validated")
            else:
                # Always True -- see _regime_matches_direction's own docstring;
                # regime is already informational-only, kept as a call (not
                # inlined) so its evidence.append side effect still runs.
                self._regime_matches_direction(direction, regime, evidence)

            # Expected value: (win_prob * avg_win) - (loss_prob * avg_loss) in R
            win_prob = confidence / 100
            expected_value = (win_prob * rr_ratio) - ((1 - win_prob) * 1.0)

            # CRO risk check
            proposal = TradeRiskProposal(
                asset=asset_name,
                direction=direction,
                entry_price=close,
                stop_loss=stop_loss,
                take_profit=take_profit_1,
                risk_percent=risk_pct,
                confidence_score=confidence,
                regime=regime.primary_regime.value,
                timeframe=technical.timeframe,
            )
            risk_result = self._risk_engine.evaluate_trade(proposal)
            checks["cro_approved"] = risk_result.success and risk_result.data.approved

            if risk_result.data and risk_result.data.adjusted_risk_pct:
                risk_pct = risk_result.data.adjusted_risk_pct

            # Edge gate: only runs if real engine instances were injected
            # (see __init__ / registry.py). Backtests THIS rule's own
            # direction logic against real history; a proven negative edge
            # vetoes the signal outright, same discipline as Command Center.
            edge_validation: Optional[EdgeValidationResult] = None
            if self._technical_engine is not None and self._backtesting_engine is not None:
                edge_result = self.validate_historical_edge(
                    asset_name, df, self._technical_engine, self._backtesting_engine,
                    timeframe=technical.timeframe, enriched_df=enriched_df,
                )
                if edge_result.success:
                    edge_validation = edge_result.data
                    checks["edge_not_proven_negative"] = edge_validation.status != "proven_negative_edge"
                    if not checks["edge_not_proven_negative"]:
                        evidence.append(edge_validation.message)
                # A failed/unavailable edge check (e.g. too little history)
                # does not veto -- absence of proof is not proof of harm,
                # unlike an actual proven-negative result.

            all_passed = all(checks.values())
            if not all_passed:
                failed = [k for k, v in checks.items() if not v]
                return EngineResult(
                    success=True,
                    data=None,
                    message=f"Signal criteria not met: {', '.join(failed)}",
                    metadata={
                        "checks": checks,
                        "direction": direction,
                        "confidence": confidence,
                        "rr": rr_ratio,
                        "edge_validation": edge_validation.to_dict() if edge_validation else None,
                        "macro_context": macro_context,
                        "fundamental_context": fundamental_context,
                        "microstructure_context": microstructure_context,
                        "economic_calendar_context": economic_calendar_context,
                        "knowledge_context": knowledge_context,
                        "feature_context": feature_context,
                        "forecast_context": forecast_context,
                    },
                )

            signal = TradingSignal(
                asset=asset_name,
                direction=direction,
                entry=close,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                risk_percent=risk_pct,
                expected_value=expected_value,
                confidence_score=confidence,
                regime=regime.primary_regime.value,
                supporting_evidence=evidence + technical.signals[:3],
                invalidation=invalidation,
                historical_context=(
                    f"ATR-based stop ({atr:.4f}), R:R {rr_ratio:.1f}:1, "
                    f"regime {regime.primary_regime.value} ({regime.confidence:.0f}% conf)"
                ),
                status="pending",
                checks_passed=checks,
                edge_validation=edge_validation,
                macro_context=macro_context,
                fundamental_context=fundamental_context,
                microstructure_context=microstructure_context,
                economic_calendar_context=economic_calendar_context,
                knowledge_context=knowledge_context,
                news_context=news_context or None,
                confluence_errors=confluence_errors or None,
                feature_context=feature_context,
                forecast_context=forecast_context,
            )

            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=signal,
                message=f"Signal generated: {direction} {asset_name} @ {close:.4f}",
                metadata={"confidence": confidence, "rr": rr_ratio},
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Signal generation failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def validate_historical_edge(
        self,
        symbol: str,
        df: pd.DataFrame,
        technical_engine: TechnicalAnalysisEngine,
        backtesting_engine: BacktestingEngine,
        timeframe: str = "1d",
        enriched_df: Optional[pd.DataFrame] = None,
    ) -> EngineResult:
        """
        Backtest this engine's OWN direction rule (the same trend/RSI/MACD/
        EMA50 score _determine_direction uses) against real history before
        trusting a live signal from it -- a signal that "looks reasonable"
        and a signal with a real statistical edge are different things.

        Excludes the live path's regime/macro CONFIDENCE adjustments and the
        text-signal-count component of the score (RSI oversold/overbought,
        MACD crossover events, Bollinger touches) -- those are informational
        boosts on top of the core direction call, not reproducible bar-by-bar
        from raw indicator columns without re-running full analysis at every
        historical index, which would be far slower for negligible extra
        fidelity. This is an explicit, documented scope reduction, not a
        hidden one -- exactly the same kind of scope limit Command Center's
        own backtest_engine.py states about its own live-signal parity gaps.

        The rule's own constants (entry_threshold, adx_divisor,
        momentum_divisor, disagreement_dampening) use
        scripts/training/train_e51_thresholds.py's backtest-validated
        tuning when one exists for this EXACT symbol+timeframe (see
        _load_tuned_params) -- otherwise the original shipped defaults
        apply unchanged.

        Args:
            symbol: Asset symbol (for logging/messages and calibration lookup).
            df: OHLCV DataFrame (same one generate_signal was called with).
            technical_engine: Used to compute indicators once, vectorized,
                over the full history (no lookahead: EMA/RSI/MACD/ADX are all
                backward-looking rolling/EWM computations).
            backtesting_engine: Runs the walk-forward validated backtest.
            timeframe: Bar timeframe of `df` -- used only to look up a
                calibration trained for this exact symbol+timeframe.
            enriched_df: Pre-computed technical_engine.analyze() output
                (`data["df"]`) for this exact `df`, if the caller already ran
                it. None (default) computes it here via analyze() -- correct
                for a standalone caller with no enriched frame of its own
                (e.g. /api/v1/signals/validate-edge).

        Returns:
            EngineResult with an EdgeValidationResult in data.
        """
        try:
            if len(df) < 60:
                return EngineResult(success=False, message="Not enough history to validate an edge")

            if enriched_df is not None:
                enriched = enriched_df
            else:
                ta_result = technical_engine.analyze(df, symbol=symbol)
                if not ta_result.success:
                    return EngineResult(success=False, message=f"Cannot validate edge: {ta_result.message}")
                enriched = ta_result.data["df"]

            # Must test the SAME rule that actually produces this asset's
            # live direction call -- an asset with a validated strategy
            # override (see _load_strategy_override) is no longer driven by
            # the baseline composite rule at all, so backtesting the
            # baseline rule here would silently veto every signal the
            # override rule generates by grading the wrong strategy.
            strategy_fn = self.build_strategy_fn(symbol, timeframe, enriched)

            bt_result = backtesting_engine.run_backtest(enriched, strategy_fn)
            if not bt_result.success:
                return EngineResult(success=False, message=f"Backtest failed: {bt_result.message}")

            result = bt_result.data
            m = result.metrics

            if m.total_trades < backtesting_engine.MIN_TRADES:
                status = "insufficient_data"
                message = (
                    f"Only {m.total_trades} historical trades for {symbol} -- not enough to "
                    "validate this edge either way."
                )
            elif result.passed_validation:
                status = "proven_positive_edge"
                message = (
                    f"Validated on {symbol}: Sharpe={m.sharpe_ratio:.2f}, "
                    f"win rate={m.win_rate:.1%}, max DD={m.max_drawdown_pct:.1f}%."
                )
            elif m.sharpe_ratio < self.NEGATIVE_EDGE_SHARPE_THRESHOLD:
                status = "proven_negative_edge"
                message = (
                    f"This exact signal logic has a NEGATIVE historical Sharpe "
                    f"({m.sharpe_ratio:.2f}) on {symbol} over {m.total_trades} trades -- "
                    "vetoed to avoid repeating a demonstrated losing pattern."
                )
            else:
                status = "not_significant"
                message = (
                    f"Sharpe={m.sharpe_ratio:.2f} on {symbol} did not clear full validation "
                    "thresholds -- treat with caution, not proven either way."
                )

            bayesian_mean, bayesian_ci = self._bayesian_edge_calibration(status, m.win_rate, m.total_trades)

            validation = EdgeValidationResult(
                status=status,
                total_trades=m.total_trades,
                win_rate=m.win_rate,
                sharpe_ratio=m.sharpe_ratio,
                max_drawdown_pct=m.max_drawdown_pct,
                passed_validation=result.passed_validation,
                message=message,
                bayesian_posterior_mean=bayesian_mean,
                bayesian_credible_interval_90pct=bayesian_ci,
            )
            return EngineResult(success=True, data=validation, message=message)
        except Exception as e:
            logger.error("Edge validation failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _bayesian_edge_calibration(
        self, status: str, win_rate: float, total_trades: int
    ) -> tuple[Optional[float], Optional[tuple]]:
        """
        E12 Beta-Binomial Bayesian update of this backtest's win rate --
        best-effort, informational enrichment of EdgeValidationResult, never
        touches status/passed_validation/confidence. Skipped for
        insufficient_data (no wins/losses worth updating on) and when no
        quant_engine was injected.
        """
        if self._quant_engine is None or status == "insufficient_data" or total_trades <= 0:
            return None, None
        try:
            wins = int(round(win_rate * total_trades))
            losses = total_trades - wins
            result = self._quant_engine.bayesian_win_rate_update(wins, losses)
            if result.success and result.data is not None:
                return result.data.posterior_mean, result.data.credible_interval_90pct
        except Exception as e:
            logger.warning("Bayesian edge calibration unavailable: %s", e)
        return None, None

    def build_strategy_fn(self, symbol: str, timeframe: str, enriched: pd.DataFrame) -> Callable[[pd.DataFrame], pd.Series]:
        """Resolve this asset's EXACT live direction rule (structural
        override > validated parameter tuning > baseline composite rule --
        same precedence _determine_direction/validate_historical_edge use)
        into a vectorized strategy_fn callable. Extracted out of
        validate_historical_edge so anything that needs to backtest/stress-
        test/walk-forward-validate this asset -- e24_strategy_research,
        e27_walk_forward, e28_stress_testing -- grades the SAME rule that's
        actually live, not a second reimplementation that could quietly
        drift out of sync. Single source of truth; validate_historical_edge
        itself now calls this too.
        """
        asset_def = get_asset(symbol)
        lookup_symbol = asset_def.yahoo_symbol if asset_def else symbol
        strategy_override = _load_strategy_override(lookup_symbol, timeframe)
        override_strategy = strategy_override.get("strategy") if strategy_override else None
        if override_strategy == "donchian_breakout":
            params = strategy_override.get("params", {})
            full_signal = self._donchian_signal_series(
                enriched, params.get("entry_n", 20), params.get("exit_n", 10)
            )
        elif override_strategy == "donchian_breakout_volume_confirmed":
            params = strategy_override.get("params", {})
            full_signal = donchian_breakout_volume_confirmed(
                enriched, params.get("entry_n", 20), params.get("exit_n", 10), params.get("volume_mult", 1.5)
            )
        else:
            # A validated PARAMETER tuning (see _load_tuned_params) -- not a
            # structural override -- must be graded here too, for the exact
            # same reason: this must test the SAME rule that actually
            # produces the asset's live direction call.
            tuned_params = _load_tuned_params(lookup_symbol, timeframe)
            full_signal = self._vectorized_signal_series(enriched, tuned_params)

        def strategy_fn(_df: pd.DataFrame) -> pd.Series:
            # run_backtest calls this once per in-sample/out-of-sample SLICE
            # of `enriched`, not the whole thing -- _simulate discards
            # (zeroes out) any signal series whose length doesn't match the
            # slice it was asked to score. Re-index to the slice actually
            # being scored rather than returning the full-length series
            # regardless of `_df`.
            return full_signal.loc[_df.index]

        return strategy_fn

    @staticmethod
    def _vectorized_signal_series(enriched: pd.DataFrame, params: Optional[dict] = None) -> pd.Series:
        """
        Command-Center-style heuristic direction rule -- replaces the
        retired strict EMA8>21>50-stack+ADX>25 composite rule, which
        required a very specific trend alignment before ever escaping
        "neutral" and was the main reason live signals fired so rarely.
        Ported deliberately, at explicit user request, in exchange for
        signals firing far more often than the retired rule ever did.

        trend_component = clamp(adx/25, -1, 1) * sign(ema_8 - ema_21),
        dampened to half strength when MACD disagrees with that sign (not
        flipped -- a dissenting momentum reading softens conviction, it
        doesn't override the trend read). momentum_component =
        clamp((rsi-50)/25, -1, 1). combined = mean of the two; entering
        long at combined>=0.2, short at combined<=-0.2, otherwise flat --
        same thresholds _determine_direction uses for the live scalar
        read, kept in sync deliberately so the edge-gate backtest below
        grades the SAME rule that's actually live, not a reimplementation
        that could quietly drift out of sync.

        Computed at every historical bar from already-vectorized
        (backward-looking, no-lookahead) indicator columns. `params`
        optionally overrides the four tunable constants (entry_threshold,
        adx_divisor, momentum_divisor, disagreement_dampening) -- see
        _load_tuned_params. None (the default for every asset without a
        validated tuning) reproduces today's exact shipped formula.
        """
        params = params or {}
        entry_threshold = params.get("entry_threshold", 0.2)
        adx_divisor = params.get("adx_divisor", 25.0)
        momentum_divisor = params.get("momentum_divisor", 25.0)
        disagreement_dampening = params.get("disagreement_dampening", 0.5)

        trend_sign = pd.Series(
            np.where(enriched["ema_8"] >= enriched["ema_21"], 1.0, -1.0), index=enriched.index
        )
        macd_sign = pd.Series(
            np.where(enriched["macd"].fillna(0) >= enriched["macd_signal"].fillna(0), 1.0, -1.0),
            index=enriched.index,
        )
        adx_ratio = (enriched["adx"].fillna(0) / adx_divisor).clip(-1, 1)
        trend_component = adx_ratio * trend_sign
        disagree = macd_sign != trend_sign
        trend_component = trend_component.where(~disagree, trend_component * disagreement_dampening)

        momentum_component = ((enriched["rsi"].fillna(50) - 50) / momentum_divisor).clip(-1, 1)
        combined = (trend_component + momentum_component) / 2

        signal = pd.Series(0, index=enriched.index)
        signal[combined >= entry_threshold] = 1
        signal[combined <= -entry_threshold] = -1
        return signal

    @staticmethod
    def _donchian_signal_series(df: pd.DataFrame, entry_n: int, exit_n: int) -> pd.Series:
        """Turtle-style channel breakout: long on a new `entry_n`-bar high,
        exit on a new `exit_n`-bar low (mirrored for shorts) -- a validated
        structural alternative to the baseline EMA-stack composite rule for
        specific assets where the composite rule found no edge at all (see
        _load_strategy_override). `.shift(1)` on the rolling window excludes
        the current bar, so a breakout only ever uses bars strictly before
        the one it fires on -- no lookahead. Stateful via ffill (which only
        ever looks backward): holds a position from entry until the
        opposite-side exit condition, not just "is this single bar's raw
        condition true."
        """
        entry_high = df["high"].shift(1).rolling(entry_n).max()
        entry_low = df["low"].shift(1).rolling(entry_n).min()
        exit_high = df["high"].shift(1).rolling(exit_n).max()
        exit_low = df["low"].shift(1).rolling(exit_n).min()

        entry_long = df["close"] > entry_high
        entry_short = df["close"] < entry_low
        exit_long = df["close"] < exit_low
        exit_short = df["close"] > exit_high

        raw = pd.Series(np.nan, index=df.index)
        raw[entry_short] = -1
        raw[exit_short] = 0
        raw[entry_long] = 1
        raw[exit_long] = 0
        return raw.ffill().fillna(0).astype(int)

    def _determine_direction_from_override(
        self, df: pd.DataFrame, override: dict, enriched_df: Optional[pd.DataFrame] = None,
    ) -> tuple[Optional[str], int, list[str]]:
        """Direction call for an asset with a validated structural strategy
        override (see _load_strategy_override). Confidence here is the
        override's own REAL backtested win rate, not the baseline composite
        score heuristic -- honestly usually far below the generic 80%
        confidence bar, because that bar was calibrated around a different,
        unvalidated rule and real trend/breakout systems win on reward size,
        not win frequency. `min_confidence` (stored alongside the override,
        checked by the caller) is THIS rule's own meaningful bar instead.

        Dispatches generically through e24_strategy_research.strategies.
        STRATEGIES (added 2026-08-21) -- previously this only had two
        hardcoded branches (donchian_breakout, via a SEPARATE parallel
        reimplementation in _donchian_signal_series below rather than the
        real strategies.donchian_breakout;
        donchian_breakout_volume_confirmed), so a real, validated edge in
        any OTHER archetype (macd_cross, regime_adaptive,
        rsi_mean_reversion, ...) could pass E26's full validation and
        still never reach a live signal -- confirmed as a real gap by
        this session's own 1h/1d universe sweeps (3-7 assets each found
        a genuinely validated edge the platform had no way to act on).
        Calling the EXACT SAME function from STRATEGIES that
        research()/E26 validated the candidate against also closes a
        real correctness gap the old donchian-only path had: the live
        driver and the research/validation path could silently drift out
        of sync since they were two independently hand-maintained
        implementations of "the same" logic.

        enriched_df: the full technical_engine.analyze() output (its
        `data["df"]`) -- required by every STRATEGIES function except the
        donchian family (which only touch high/low/close, present on raw
        OHLCV too). None (default) triggers a real, on-demand
        self._technical_engine.analyze() call ONLY when the specific
        strategy actually needs enriched columns and the caller didn't
        already have one to pass through -- never silently substitutes
        raw `df` for a strategy that needs indicator columns raw OHLCV
        doesn't have.
        """
        evidence: list[str] = []
        strategy = override.get("strategy")
        params = override.get("params", {})
        strategy_fn = STRATEGIES.get(strategy)
        if strategy_fn is None:
            logger.warning("Unknown strategy override type: %s", strategy)
            return None, 0, evidence

        # donchian family only ever reads high/low/close -- present on the
        # raw df too, so no enrichment (and no extra analyze() call) is
        # needed even when the caller has no enriched_df on hand.
        needs_enriched = strategy not in ("donchian_breakout", "donchian_breakout_volume_confirmed")
        frame = df
        if needs_enriched:
            if enriched_df is not None:
                frame = enriched_df
            elif self._technical_engine is not None:
                # symbol/timeframe are pure metadata on TechnicalAnalysisEngine.
                # analyze() (indicator math is bar-count-based, not
                # calendar-time-based, so the label doesn't change the
                # computation) -- the override dict itself never stores
                # them (see _promote's own written schema), so there's
                # nothing real to pass through here regardless.
                ta_result = self._technical_engine.analyze(df)
                if not ta_result.success:
                    logger.warning("Could not compute enriched frame for %s override: %s", strategy, ta_result.message)
                    return None, 0, evidence
                frame = ta_result.data["df"]
            else:
                logger.warning("Strategy override %s needs an enriched frame but none was available", strategy)
                return None, 0, evidence

        try:
            signal_series = strategy_fn(frame, **params)
        except Exception as e:
            logger.warning("Strategy override %s failed to compute a signal: %s", strategy, e)
            return None, 0, evidence

        last_signal = int(signal_series.iloc[-1])
        if last_signal == 0:
            return None, 0, evidence

        direction = "LONG" if last_signal > 0 else "SHORT"
        win_rate = override.get("win_rate", 0.5)
        # Clamped (added 2026-09-13, docs/UPGRADE_BRIEF.md Phase 17's own
        # "confidence always 0-100" invariant): win_rate is read from an
        # on-disk override file this function doesn't otherwise validate --
        # a malformed value (e.g. a future write bug expressing win_rate
        # as a 0-100 percentage instead of a 0-1 fraction, or a stray
        # negative) would otherwise flow straight into confidence_score
        # and downstream into E45's own floor checks unclamped.
        confidence = max(0, min(100, round(win_rate * 100)))
        evidence.append(
            f"Validated {strategy} override {params}: {win_rate:.1%} historical win rate, "
            f"OOS Sharpe {override.get('oos_sharpe', 0):.2f} over {override.get('total_trades', 0)} trades"
        )
        return direction, confidence, evidence

    def scan_all_assets(
        self,
        market_data_engine: Any,
        technical_engine: Any,
        regime_engine: Any,
        macro_engine: Any,
        timeframe: str = "1d",
        fundamental_engine: Any = None,
        data_quality_engine: Any = None,
        symbols: Optional[list[str]] = None,
    ) -> EngineResult:
        """
        Scan all supported assets and rank signals.

        symbols: OPTIONAL whitelist of asset symbols to scan. None (default)
            scans every supported asset, exactly as before. Added
            2026-08-22 for a real, measured cost: the dashboard's market
            filter (Forex / Crypto / Metals / ...) was applied CLIENT-side,
            so choosing "Crypto" still ran the full multi-engine pipeline
            across all 29 assets and then threw ~27 of them away. Measured
            live at 188s for a crypto scan that needed 2 assets. Passing the
            filter through turns that into work proportional to what was
            actually asked for.

        Args:
            fundamental_engine: Optional E06 engine. Fetched ONCE here (its
                data is global/asset-independent -- yield curve, real yield,
                WTI-Brent -- not per-symbol), then attached to every asset's
                signal with an honest per-asset relevance tag. Optional so
                callers/tests that don't need it aren't forced to provide it.
            data_quality_engine: Optional E40 engine, repairs each asset's
                OHLCV the same way the single-symbol /signals/generate path
                does (see api/main.py's _prepare_ohlcv) -- without this, a
                scan and a single-symbol analyze could silently disagree on
                the same asset because one saw repaired data and the other
                didn't. Optional so callers/tests that don't need it aren't
                forced to provide it.

        Returns:
            EngineResult with list of TradingSignal sorted by confidence.
        """
        from project_titan_x.core.config import list_assets

        macro_result = macro_engine.analyze()
        macro = macro_result.data if macro_result.success else None
        macro_score = macro.risk_on_off_score if macro else 0.0

        fundamental_snapshot = None
        if fundamental_engine is not None:
            fundamental_result = fundamental_engine.analyze()
            fundamental_snapshot = fundamental_result.data if fundamental_result.success else None

        # Fetched ONCE, same reasoning as macro/fundamental above -- these
        # are the same 4 RSS feeds regardless of which asset is currently
        # being evaluated. Without this, generate_signal's own per-asset
        # news/sentiment confluence check re-fetched all 4 feeds for EVERY
        # asset (52 redundant network round-trips for a 13-asset scan),
        # which measured as the dominant cost of a full scan (~8-10s/asset,
        # ~150s total) -- see generate_signal's news_items docstring.
        news_items = None
        if self._news_engine is not None:
            news_result = self._news_engine.fetch_headlines(limit_per_feed=10)
            news_items = news_result.data if news_result.success and news_result.data else []

        # Same reasoning as news_items above: one correlation matrix across
        # ~14 tracked tickers, not per-asset data. E10.analyze() live-fetches
        # every one of those tickers from Yahoo Finance on every call --
        # calling it once per asset in the loop below meant ~14x13=182
        # redundant live fetches for a 13-asset scan, the single largest
        # remaining cost in a full scan after the news fix above.
        cross_asset_result = None
        if self._cross_asset_engine is not None:
            cross_asset_result = self._cross_asset_engine.analyze()

        def _scan_one(asset) -> Optional[TradingSignal]:
            try:
                # years=2 (not 1) and data-quality repair -- must match
                # api/main.py's _prepare_ohlcv exactly, otherwise this scan
                # and a single-symbol /signals/generate call for the SAME
                # asset can silently disagree. allow_cache=True (added
                # 2026-08-21, see MarketDataEngine.fetch_ohlcv's own
                # docstring): the one opted-in caller for the short-TTL
                # (settings.ohlcv_cache_ttl_seconds, default 180s) Redis
                # OHLCV cache -- a real, measured scan-speed fix. Honest
                # tradeoff, not a free lunch: within that same window, a
                # scan result and a single-symbol /signals/generate call
                # for the same asset (which always fetches fresh,
                # allow_cache defaults False) COULD show data from
                # slightly different moments if a new bar formed mid-
                # window -- an acceptable staleness bound for a screening
                # scan across many assets, chosen specifically because a
                # 1d/1h bar can't meaningfully change within 180s.
                fetch = market_data_engine.fetch_ohlcv(asset.yahoo_symbol, timeframe, years=2, allow_cache=True)
                if not fetch.success:
                    # Recorded, not swallowed. A data-provider outage or rate
                    # limit degrades a scan silently otherwise -- measured
                    # 2026-09-22, the same 4h scan returned 0 FETCH_FAIL and
                    # then 10 minutes apart, purely from upstream throttling.
                    _suppressed.append({"symbol": asset.symbol, "reason": "fetch_failed",
                                        "failed_checks": [], "confidence": None,
                                        "detail": (fetch.message or "")[:80]})
                    return None
                df = fetch.data
                if data_quality_engine is not None:
                    repaired = data_quality_engine.repair(df)
                    df = repaired.data if repaired.success else df
                ta = technical_engine.analyze(df, symbol=asset.symbol, timeframe=timeframe)
                if not ta.success:
                    _suppressed.append({"symbol": asset.symbol, "reason": "technical_failed",
                                        "failed_checks": [], "confidence": None,
                                        "detail": (ta.message or "")[:80]})
                    return None
                snapshot = ta.data["snapshot"]
                regime = regime_engine.classify(df, snapshot, macro)
                if not regime.success:
                    _suppressed.append({"symbol": asset.symbol, "reason": "regime_failed",
                                        "failed_checks": [], "confidence": None,
                                        "detail": (regime.message or "")[:80]})
                    return None
                sig = self.generate_signal(
                    asset.symbol, df, snapshot, regime.data, macro_score,
                    macro_snapshot=macro, fundamental_snapshot=fundamental_snapshot,
                    news_items=news_items, cross_asset_result=cross_asset_result,
                    enriched_df=ta.data.get("df"),
                    # Real, measured scan-performance fix (2026-08-21): skips
                    # only the 3 context builders confirmed inert w.r.t.
                    # confidence/direction (knowledge/feature/forecast --
                    # see generate_signal's own docstring for the full
                    # verification). microstructure/economic-calendar
                    # confluence checks still run for every asset, unaffected.
                    include_extended_context=False,
                )
                if sig.success and sig.data is not None:
                    return sig.data
                # WHY an asset produced nothing is the single most useful thing
                # a scan can tell you, and it was being discarded here. An
                # empty intraday scan looked identical whether the market was
                # quiet or whether every candidate had been vetoed for
                # PROVEN NEGATIVE EDGE -- measured 2026-09-22, when 15m/5m
                # returned 0 signals and the cause turned out to be the veto
                # firing on every asset at confidence 37-91. Recorded, never
                # used to change a decision.
                meta = sig.metadata or {}
                failed = [k for k, v in (meta.get("checks") or {}).items() if not v]
                _suppressed.append({
                    "symbol": asset.symbol,
                    "reason": (failed[0] if failed else
                               ("no_direction" if meta.get("direction") is None else "unknown")),
                    "failed_checks": failed,
                    "confidence": meta.get("confidence"),
                })
                return None
            except Exception as e:
                logger.warning("Scan failed for %s: %s", asset.symbol, e)
                return None

        # Parallelized across assets -- each asset's work here is almost
        # entirely I/O-bound (network fetches to yfinance/ccxt/Deribit/
        # etc.), and every input each call reads (macro/fundamental/news/
        # cross_asset_result) was already fetched ONCE above and is never
        # mutated per-asset, so there's no shared-state race to worry
        # about; each thread only ever appends its own independent result.
        # Bounded at 6 workers -- enough to turn this scan's wall-clock
        # cost from "sum of every asset's fetch time" into roughly "the
        # slowest asset's fetch time", without hammering Yahoo Finance
        # with 29 simultaneous requests (real rate-limiting risk observed
        # this same session under heavy sequential load already). The
        # per-provider throttle locks in core/data_providers (finnhub.py,
        # fred.py) were already built assuming concurrent callers, which
        # is what makes this safe rather than a new risk.
        # NOT `with ThreadPoolExecutor(...) as executor:` -- the context
        # manager's __exit__ calls shutdown(wait=True), which blocks until
        # EVERY submitted thread finishes, even ones this loop has already
        # given up waiting on via the per-future timeout below. A single
        # asset whose network call hangs (observed for real this session
        # under Yahoo Finance throttling) would otherwise still hang the
        # entire scan, defeating the whole point of parallelizing it.
        # shutdown(wait=False) below lets this method return as soon as
        # every future has either finished or been given up on -- any
        # still-running straggler thread keeps running harmlessly in the
        # background and its result is simply discarded when it finishes.
        signals: list[TradingSignal] = []
        # Appended from worker threads. list.append is atomic under the GIL,
        # which is all this needs -- nothing reads it until the pool is done.
        _suppressed: list[dict] = []
        assets = list_assets()
        if symbols:
            wanted = {s.upper() for s in symbols}
            assets = [a for a in assets if a.symbol.upper() in wanted]
            if not assets:
                return EngineResult(
                    success=False,
                    message=f"None of the requested symbols are supported: {sorted(wanted)}",
                )
        # 12, not 6 -- measured on a full 29-asset 1d scan: 77.1s at 6 workers
        # vs 33.5s at 12, with an IDENTICAL 21 signals out, so the speedup costs
        # nothing in coverage. _scan_one is almost entirely I/O wait (Yahoo,
        # ECB, news feeds), which is why threads help at all.
        #
        # NOT higher. 18 was measured too and came back SLOWER at 38.6s --
        # past ~12 the added threads contend rather than overlap, since the
        # remote endpoints are the shared resource. The curve is 77.1 -> 33.5
        # -> 38.6, so 12 is a measured optimum, not a safety margin.
        executor = ThreadPoolExecutor(max_workers=min(12, len(assets)) or 1)
        try:
            futures = {executor.submit(_scan_one, asset): asset for asset in assets}
            for future in as_completed(futures, timeout=180):
                asset = futures[future]
                try:
                    result = future.result(timeout=30)
                except Exception as e:
                    logger.warning("Scan timed out or errored for %s: %s", asset.symbol, e)
                    _suppressed.append({"symbol": asset.symbol, "reason": "worker_error",
                                        "failed_checks": [], "confidence": None,
                                        "detail": f"{type(e).__name__}: {str(e)[:60]}"})
                    continue
                if result is not None:
                    signals.append(result)
        except TimeoutError:
            logger.warning(
                "scan_all_assets: overall 180s budget exceeded with %d/%d assets still pending -- "
                "returning what completed rather than hanging indefinitely", len(assets) - len(signals), len(assets),
            )
        finally:
            executor.shutdown(wait=False)

        signals.sort(key=lambda s: s.confidence_score, reverse=True)
        by_reason: dict[str, int] = {}
        for row in _suppressed:
            by_reason[row["reason"]] = by_reason.get(row["reason"], 0) + 1
        msg = f"Scan complete: {len(signals)} signal(s)"
        if _suppressed:
            # Named in the message, not just the metadata: a caller that only
            # logs `message` still learns that an empty scan was a VETO and
            # not a quiet market.
            msg += (" · " + str(len(_suppressed)) + " suppressed ("
                    + ", ".join(f"{k}={v}" for k, v in sorted(
                        by_reason.items(), key=lambda kv: -kv[1])) + ")")
        return EngineResult(
            success=True,
            data=signals,
            message=msg,
            metadata={
                "count": len(signals),
                "suppressed_count": len(_suppressed),
                "suppressed_by_reason": by_reason,
                "suppressed": _suppressed,
            },
        )

    # Keyword aliases relating the platform's own cross-asset pairs and
    # news headlines back to a symbol -- same substring-matching approach
    # the dashboard already uses, kept here so E51 can do the same
    # filtering server-side for the general (non-override) signal path.
    _CROSS_ASSET_ALIASES = {
        "GOLD": ["gold"], "SILVER": ["silver"], "CRUDE": ["oil"],
        "EURUSD": ["eur/usd"], "GBPUSD": ["gbp/usd"], "USDJPY": ["usd/jpy"],
        "US10Y": ["yields", "bonds"], "SP500": ["stocks", "risk assets"],
    }
    _NEWS_ALIASES = {
        "GOLD": ["gold"], "SILVER": ["silver"], "CRUDE": ["oil", "crude", "wti"],
        "EURUSD": ["euro"], "GBPUSD": ["pound", "sterling"], "USDJPY": ["yen"],
        "BTCUSD": ["bitcoin", "btc"], "ETHUSD": ["ethereum", "eth"],
        "NIFTY50": ["nifty"], "BANKNIFTY": ["bank nifty", "banknifty"],
        "US10Y": ["treasury", "yield"], "SP500": ["s&p", "stocks"],
    }
    # Corporate high-yield credit spreads (E14) are a textbook risk-on/
    # risk-off barometer -- wide HY spreads = credit stress, historically a
    # headwind for growth/risk assets; tight spreads = credit-market
    # complacency, historically a tailwind. Restricted to this platform's
    # actual risk-on instruments (US10Y is a defensive/bond asset -- its
    # price reaction to credit stress is not a well-established one-way
    # call, so it's deliberately excluded rather than guessed).
    _CREDIT_RISK_SYMBOLS = frozenset({"BTCUSD", "ETHUSD", "SP500", "NIFTY50", "BANKNIFTY"})
    # Sovereign EM credit spreads (E15, EMB-vs-Treasury) are this platform's
    # most relevant EM-stress proxy for its actual EM exposure -- India-
    # linked instruments and the USD/INR pair itself.
    _SOVEREIGN_RISK_SYMBOLS = frozenset({"USDINR", "NIFTY50", "BANKNIFTY"})

    def _apply_confluence_adjustments(
        self,
        direction: str,
        confidence: int,
        symbol: str,
        microstructure_context: Optional[dict],
        economic_calendar_context: Optional[dict],
        evidence: list[str],
        news_items: Optional[list] = None,
        cross_asset_result: Optional[EngineResult] = None,
        news_context_out: Optional[dict] = None,
        confluence_errors_out: Optional[dict] = None,
    ) -> int:
        """
        Layer independent confluence reads from every real intelligence
        engine this platform has on top of the core technical score --
        inspired by Command Center's higher-timeframe/cross-asset
        confluence multipliers (roughly +-15%/x0.6), broadened to cover
        this platform's much larger real engine roster instead of just
        one or two partners. Every adjustment here touches CONFIDENCE
        only, never direction, and every one is best-effort: a failed or
        unavailable read just skips its own adjustment silently, never
        blocks the signal (same convention as the *_context builders
        above). Only applied to the general heuristic-score path -- an
        asset with its own validated structural override (e.g. SP500's
        Donchian breakout) keeps its confidence as the real backtested
        win rate it actually is, undiluted by heuristic confluence noise.

        news_context_out: an optional caller-supplied dict this method
        populates IN PLACE with the actual matched headlines (not just an
        evidence count string) when the sentiment confluence block finds
        symbol-relevant news -- lets generate_signal attach a real
        news_context to the returned TradingSignal (see dashboard's "what's
        moving this pair" section) without changing this method's existing
        `-> int` return contract, which ~25 existing tests assert directly.
        Deliberately an out-parameter, not module/instance state: this
        method now runs concurrently across threads (scan_all_assets'
        ThreadPoolExecutor), so each caller must own its own dict.

        confluence_errors_out: an optional caller-supplied dict populated
        IN PLACE with {check_name: error_message} for any check below
        that genuinely raised during THIS call. Added 2026-09-11 to close
        a real observability gap: every check here returns None both when
        it legitimately evaluates to "no adjustment" and when it catches
        an exception (logged via logger.warning, then silently degrading
        the same way) -- from the confidence score and evidence list
        alone, a confluence engine that has been broken for weeks is
        indistinguishable from one that has simply found nothing notable
        that whole time. This does not change any adjustment, threshold,
        or the confidence calculation itself -- purely additive
        visibility into which checks actually ran vs. actually failed.
        """
        conf = float(confidence)

        if microstructure_context and microstructure_context.get("execution_risk") == "high":
            conf *= 0.9
            evidence.append("Confluence: high execution risk (E11) — confidence tempered")

        if economic_calendar_context and economic_calendar_context.get("high_impact_within_24h"):
            conf *= 0.85
            evidence.append("Confluence: high-impact event within 24h (E05) — confidence tempered")

        # The 8 blocks below (cross-asset, sentiment/news, derivatives,
        # crypto, commodity, fixed income, credit, global liquidity) each make a real,
        # independent network/engine call -- profiled live 2026-07-20 on
        # BTCUSD: cross_asset 4.7s, derivatives 3.1s, crypto 9.4s, news
        # 1.7s, together the dominant cost of generate_signal (~25s of a
        # ~42s single-asset call). Run concurrently (I/O-bound, no shared
        # mutable state between them -- each reads its own engine, no
        # writes to anything but its own local result) via a bounded
        # ThreadPoolExecutor, same safety reasoning as scan_all_assets'
        # own parallelization. Applied to `conf` SEQUENTIALLY afterward,
        # in this exact original order -- not the order threads happen to
        # finish in -- because each step's `min(100.0, conf * m)` clamp is
        # order-sensitive (a boost that would have been clamped to 100
        # before a later REDUCING step must still be clamped at that
        # point, not after collecting every multiplier raw and clamping
        # once at the end, which can give a different final number in a
        # mixed boost-then-reduce case). Parallelizing the SLOW part (the
        # network calls) while keeping the FAST part (applying arithmetic
        # to a shared float) sequential preserves the exact original
        # behavior every existing test already asserts on.
        checks = [
            ("cross_asset", lambda: self._confluence_cross_asset(symbol, cross_asset_result, confluence_errors_out)),
            ("sentiment", lambda: self._confluence_sentiment(direction, symbol, news_items, news_context_out, confluence_errors_out)),
            ("derivatives", lambda: self._confluence_derivatives(direction, symbol, confluence_errors_out)),
            ("crypto", lambda: self._confluence_crypto(direction, symbol, confluence_errors_out)),
            ("commodity", lambda: self._confluence_commodity(direction, symbol, confluence_errors_out)),
            ("fixed_income", lambda: self._confluence_fixed_income(direction, symbol, confluence_errors_out)),
            ("credit", lambda: self._confluence_credit(direction, symbol, confluence_errors_out)),
            ("global_liquidity", lambda: self._confluence_global_liquidity(direction, symbol, confluence_errors_out)),
            ("alpha_research", lambda: self._confluence_alpha_research(symbol, direction, confluence_errors_out)),
            ("meta_learning", lambda: self._confluence_meta_learning(symbol, direction, confluence_errors_out)),
            ("model_risk", lambda: self._confluence_model_risk(symbol, confluence_errors_out)),
        ]
        # Capped well below len(checks) (11, after adding alpha_research/
        # meta_learning/model_risk 2026-08-05): this pool nests INSIDE
        # scan_all_assets' own 6-worker pool during a full scan (up to
        # 6 x 4 = 24 concurrent requests, not 6 x 7 = 42) -- real external
        # rate-limiting (Yahoo Finance) was hit live this same session
        # under heavy concurrent load, so this stays deliberately
        # conservative rather than maximizing parallelism for its own sake.
        # Real bug found and fixed 2026-08-05: `with ThreadPoolExecutor(...)
        # as executor:` blocks on `shutdown(wait=True)` at the end of the
        # block -- same anti-pattern scan_all_assets' own docstring already
        # documents fixing (a single slow/hung check would block exit even
        # after every other check's result was already collected). Worse,
        # `as_completed(futures, timeout=60)` had NO exception handling
        # around the for-loop itself: when growing this list from 9 to 11
        # checks (adding meta_learning/model_risk) increased contention on
        # the same 4 workers, a real live scan hit the 60s timeout on 1
        # straggler check -- `as_completed` raising TimeoutError there
        # propagated all the way up through generate_signal's outer
        # try/except, failing the ENTIRE signal (not just skipping that one
        # confluence check, which is what every other failure mode here
        # already degrades to via the inner try/except below). Verified
        # live: this was silently reducing scan_all_assets' real signal
        # count platform-wide.
        results: dict[str, Optional[tuple[float, str]]] = {}
        executor = ThreadPoolExecutor(max_workers=4)
        try:
            futures = {executor.submit(fn): name for name, fn in checks}
            try:
                for future in as_completed(futures, timeout=60):
                    name = futures[future]
                    try:
                        results[name] = future.result(timeout=30)
                    except Exception as e:
                        logger.warning("Confluence check %s unavailable for %s: %s", name, symbol, e)
                        results[name] = None
            except TimeoutError:
                unfinished = [name for future, name in futures.items() if not future.done()]
                logger.warning(
                    "Confluence checks timed out for %s after 60s -- proceeding with %d/%d completed (%s never finished)",
                    symbol, len(results), len(checks), unfinished,
                )
        finally:
            executor.shutdown(wait=False)

        for name, _fn in checks:
            outcome = results.get(name)
            if outcome is None:
                continue
            multiplier, evidence_line = outcome
            conf = min(100.0, conf * multiplier) if multiplier >= 1.0 else conf * multiplier
            evidence.append(evidence_line)

        return int(round(max(0.0, min(100.0, conf))))

    def _confluence_cross_asset(
        self, symbol: str, cross_asset_result: Optional[EngineResult], errors_out: Optional[dict] = None,
    ) -> Optional[tuple[float, str]]:
        if cross_asset_result is None and self._cross_asset_engine is None:
            return None
        try:
            result = cross_asset_result if cross_asset_result is not None else self._cross_asset_engine.analyze()
            if result.success and result.data:
                keys = self._CROSS_ASSET_ALIASES.get(symbol, [])
                relevant = [
                    p for p in result.data.pairs
                    if keys and any(k in (p.name + p.label_a + p.label_b).lower() for k in keys)
                ]
                if relevant:
                    if any(p.regime in ("breaking_down", "inverted") for p in relevant):
                        return 0.92, "Confluence: a tracked cross-asset relationship (E10) is breaking down"
                    elif all(p.regime == "intact" for p in relevant):
                        return 1.05, "Confluence: tracked cross-asset relationship(s) (E10) intact"
        except Exception as e:
            logger.warning("Cross-asset confluence unavailable for %s: %s", symbol, e)
            if errors_out is not None:
                errors_out["cross_asset"] = str(e)
        return None

    def _confluence_sentiment(
        self, direction: str, symbol: str, news_items: Optional[list], news_context_out: Optional[dict],
        errors_out: Optional[dict] = None,
    ) -> Optional[tuple[float, str]]:
        if self._sentiment_engine is None or (news_items is None and self._news_engine is None):
            return None
        try:
            if news_items is None:
                news_result = self._news_engine.fetch_headlines(limit_per_feed=10)
                news_items = news_result.data if news_result.success and news_result.data else []
            if news_items:
                keys = self._NEWS_ALIASES.get(symbol, [symbol.lower()])
                matches = [i for i in news_items if any(k in i.title.lower() for k in keys)]
                if matches:
                    batch = self._sentiment_engine.analyze_batch([i.title for i in matches])
                    if batch.success:
                        agg = batch.data["aggregate_score"]
                        agrees = (direction == "LONG" and agg > 0.05) or (direction == "SHORT" and agg < -0.05)
                        disagrees = (direction == "LONG" and agg < -0.05) or (direction == "SHORT" and agg > 0.05)
                        if news_context_out is not None:
                            # Real matched headlines, not just the count
                            # string in `evidence` -- capped at 5 so the UI
                            # shows "what's moving this pair" without
                            # dumping every RSS match.
                            news_context_out["matched_headlines"] = [
                                {
                                    "title": item.title, "source": item.source, "link": item.link,
                                    "published": item.published.isoformat() if item.published else None,
                                }
                                for item in matches[:5]
                            ]
                            news_context_out["aggregate_sentiment_score"] = round(float(agg), 3)
                            news_context_out["agrees_with_direction"] = bool(agrees)
                            news_context_out["disagrees_with_direction"] = bool(disagrees)
                        if agrees:
                            return 1.12, f"Confluence: {len(matches)} symbol-specific headline(s) (E09) agree with direction"
                        elif disagrees:
                            return 0.8, f"Confluence: {len(matches)} symbol-specific headline(s) (E09) disagree with direction"
        except Exception as e:
            logger.warning("Sentiment confluence unavailable for %s: %s", symbol, e)
            if errors_out is not None:
                errors_out["sentiment"] = str(e)
        return None

    def _confluence_derivatives(
        self, direction: str, symbol: str, errors_out: Optional[dict] = None,
    ) -> Optional[tuple[float, str]]:
        if self._derivatives_engine is None or symbol not in ("BTCUSD", "ETHUSD"):
            return None
        try:
            result = self._derivatives_engine.analyze(symbol=symbol)
            if result.success and result.data is not None:
                skew = result.data.skew_label
                agrees = (direction == "LONG" and skew == "call_skew") or (direction == "SHORT" and skew == "put_skew")
                disagrees = (direction == "LONG" and skew == "put_skew") or (direction == "SHORT" and skew == "call_skew")
                if agrees:
                    return 1.1, f"Confluence: options skew ({skew}, E13) agrees with direction"
                elif disagrees:
                    return 0.85, f"Confluence: options skew ({skew}, E13) disagrees with direction"
        except Exception as e:
            logger.warning("Derivatives confluence unavailable for %s: %s", symbol, e)
            if errors_out is not None:
                errors_out["derivatives"] = str(e)
        return None

    def _confluence_crypto(
        self, direction: str, symbol: str, errors_out: Optional[dict] = None,
    ) -> Optional[tuple[float, str]]:
        if self._crypto_engine is None or symbol not in ("BTCUSD", "ETHUSD"):
            return None
        try:
            result = self._crypto_engine.analyze(symbol=symbol)
            if result.success and result.data is not None and result.data.funding_positioning is not None:
                positioning = result.data.funding_positioning
                regime = positioning.regime
                # Contrarian read: crowded_long (everyone already long,
                # paying funding to stay there) leans bearish; crowded_short
                # leans bullish. Only applied at full weight when THIS
                # asset's own held-out calibration confirmed the effect
                # (see e17_crypto/train_e17_crypto.py) -- an unconfirmed
                # regime (e.g. ETHUSD today) still shows up in evidence but
                # at a much smaller weight, honestly reflecting that it's
                # unvalidated, not proven noise.
                weight = 1.0 if positioning.contrarian_effect_validated else 0.3
                agrees = (direction == "SHORT" and regime == "crowded_long") or (direction == "LONG" and regime == "crowded_short")
                disagrees = (direction == "LONG" and regime == "crowded_long") or (direction == "SHORT" and regime == "crowded_short")
                validated_note = "held-out validated" if positioning.contrarian_effect_validated else "unvalidated on this asset, reduced weight"
                if agrees:
                    return 1 + 0.1 * weight, f"Confluence: funding-rate positioning ({regime}, E17, {validated_note}) agrees with direction"
                elif disagrees:
                    return 1 - 0.15 * weight, f"Confluence: funding-rate positioning ({regime}, E17, {validated_note}) disagrees with direction"
        except Exception as e:
            logger.warning("Crypto confluence unavailable for %s: %s", symbol, e)
            if errors_out is not None:
                errors_out["crypto"] = str(e)
        return None

    def _confluence_alpha_research(
        self, symbol: str, direction: str, errors_out: Optional[dict] = None,
    ) -> Optional[tuple[float, str]]:
        """Delegates to E22's own evaluate_live_confluence -- see that
        method's docstring for exactly what makes a hypothesis eligible
        (real, statistically significant on its last research run, AND
        cheaply re-checkable live). Only two hypothesis types are wired
        that way today (trending-regime, risk-off) -- both currently
        report not_significant/mixed for every tested asset per
        train_e22_alpha_research.py's real 2026-08-05 run, so this
        confluence check is honestly a no-op in practice right now, not
        silently disabled -- it activates automatically the moment a
        future research run finds a genuinely significant, currently-
        applicable effect for a given symbol."""
        if self._alpha_research_engine is None:
            return None
        try:
            return self._alpha_research_engine.evaluate_live_confluence(symbol, direction)
        except Exception as e:
            logger.warning("Alpha research confluence unavailable for %s: %s", symbol, e)
            if errors_out is not None:
                errors_out["alpha_research"] = str(e)
        return None

    def _confluence_meta_learning(
        self, symbol: str, direction: str, errors_out: Optional[dict] = None,
    ) -> Optional[tuple[float, str]]:
        """Delegates to E37's own evaluate_live_confluence -- a cheap
        read of the precomputed regime_fit_database.json (see that
        engine's own module docstring), never a live backtest on this
        hot path."""
        if self._meta_learning_engine is None:
            return None
        try:
            return self._meta_learning_engine.evaluate_live_confluence(symbol, direction)
        except Exception as e:
            logger.warning("Meta-learning confluence unavailable for %s: %s", symbol, e)
            if errors_out is not None:
                errors_out["meta_learning"] = str(e)
        return None

    def _confluence_model_risk(
        self, symbol: str, errors_out: Optional[dict] = None,
    ) -> Optional[tuple[float, str]]:
        """Delegates to E39's own cheap check_symbol -- direction-
        independent (a governance flag, not an edge read), so this
        ignores the `direction` param every other confluence check takes.
        Only ever returns a DOWNWARD multiplier (never a boost -- an
        unverified model earning EXTRA confidence would be backwards) and
        only when a real live model file exists but is missing the
        governance fields its own training script always writes;
        baseline_composite_rule (code, not a file) and verified files
        both return None (no adjustment), same as every other confluence
        check when there's nothing to flag."""
        if self._model_risk_engine is None:
            return None
        try:
            asset = get_asset(symbol)
            if asset is None:
                return None
            entry = self._model_risk_engine.check_symbol(asset.symbol, asset.yahoo_symbol, "1d")
            if entry.provenance in ("unverified", "missing_required_fields"):
                return 0.85, (
                    f"Model risk: {symbol}'s live {entry.model_kind} file is missing real training "
                    f"provenance ({', '.join(entry.missing_fields) or 'unreadable'}, E39)"
                )
        except Exception as e:
            logger.warning("Model risk confluence unavailable for %s: %s", symbol, e)
            if errors_out is not None:
                errors_out["model_risk"] = str(e)
        return None

    def _confluence_commodity(
        self, direction: str, symbol: str, errors_out: Optional[dict] = None,
    ) -> Optional[tuple[float, str]]:
        if self._commodity_engine is None or symbol not in ("GOLD", "SILVER", "CRUDE"):
            return None
        try:
            result = self._commodity_engine.analyze(symbol=symbol)
            if result.success and result.data is not None and result.data.commodities:
                seasonality = result.data.commodities[0].seasonality
                if seasonality and seasonality.significant:
                    dir_bullish = seasonality.direction == "bullish"
                    agrees = (direction == "LONG" and dir_bullish) or (direction == "SHORT" and not dir_bullish)
                    disagrees = (direction == "LONG" and not dir_bullish) or (direction == "SHORT" and dir_bullish)
                    if agrees:
                        return 1.1, f"Confluence: significant seasonality ({seasonality.direction}, E16) agrees with direction"
                    elif disagrees:
                        return 0.85, f"Confluence: significant seasonality ({seasonality.direction}, E16) disagrees with direction"
        except Exception as e:
            logger.warning("Commodity confluence unavailable for %s: %s", symbol, e)
            if errors_out is not None:
                errors_out["commodity"] = str(e)
        return None

    def _confluence_fixed_income(
        self, direction: str, symbol: str, errors_out: Optional[dict] = None,
    ) -> Optional[tuple[float, str]]:
        if self._fixed_income_engine is None or symbol not in self._CREDIT_RISK_SYMBOLS:
            return None
        try:
            result = self._fixed_income_engine.analyze()
            if result.success and result.data is not None and result.data.credit_spread:
                hy_regime = result.data.credit_spread.hy_regime
                agrees = (direction == "SHORT" and hy_regime == "wide") or (direction == "LONG" and hy_regime == "tight")
                disagrees = (direction == "LONG" and hy_regime == "wide") or (direction == "SHORT" and hy_regime == "tight")
                if agrees:
                    return 1.1, f"Confluence: corporate credit spreads {hy_regime} (E14) agrees with direction"
                elif disagrees:
                    return 0.85, f"Confluence: corporate credit spreads {hy_regime} (E14) disagrees with direction"
        except Exception as e:
            logger.warning("Fixed income confluence unavailable for %s: %s", symbol, e)
            if errors_out is not None:
                errors_out["fixed_income"] = str(e)
        return None

    def _confluence_credit(
        self, direction: str, symbol: str, errors_out: Optional[dict] = None,
    ) -> Optional[tuple[float, str]]:
        if self._credit_engine is None or symbol not in self._SOVEREIGN_RISK_SYMBOLS:
            return None
        try:
            result = self._credit_engine.analyze()
            if result.success and result.data is not None and result.data.sovereign_credit:
                sov_regime = result.data.sovereign_credit.regime
                agrees = (direction == "SHORT" and sov_regime == "wide") or (direction == "LONG" and sov_regime == "tight")
                disagrees = (direction == "LONG" and sov_regime == "wide") or (direction == "SHORT" and sov_regime == "tight")
                if agrees:
                    return 1.1, f"Confluence: sovereign EM credit spread {sov_regime} (E15) agrees with direction"
                elif disagrees:
                    return 0.85, f"Confluence: sovereign EM credit spread {sov_regime} (E15) disagrees with direction"
        except Exception as e:
            logger.warning("Credit confluence unavailable for %s: %s", symbol, e)
            if errors_out is not None:
                errors_out["credit"] = str(e)
        return None

    def _confluence_global_liquidity(
        self, direction: str, symbol: str, errors_out: Optional[dict] = None,
    ) -> Optional[tuple[float, str]]:
        """Fed balance sheet / M2 regime (E19) vs. direction, restricted to
        this platform's actual risk-on instruments (same
        _CREDIT_RISK_SYMBOLS set _confluence_credit already uses --
        expanding/contracting global liquidity is a genuine risk-appetite
        tailwind/headwind for crypto/equity-index exposure; there's no
        comparably well-established one-way read for e.g. a specific FX
        cross, so this deliberately doesn't apply everywhere). E19 itself
        is market-wide, not per-asset (same as E17's Fear & Greed note) --
        overall_regime is either "expanding"/"contracting" (a real signal)
        or "mixed"/"unconfigured" (no signal, skipped)."""
        if self._global_liquidity_engine is None or symbol not in self._CREDIT_RISK_SYMBOLS:
            return None
        try:
            result = self._global_liquidity_engine.analyze()
            if not (result.success and result.data is not None):
                return None
            liquidity_regime = result.data.overall_regime
            agrees = (direction == "LONG" and liquidity_regime == "expanding") or (
                direction == "SHORT" and liquidity_regime == "contracting"
            )
            disagrees = (direction == "LONG" and liquidity_regime == "contracting") or (
                direction == "SHORT" and liquidity_regime == "expanding"
            )
            if agrees:
                return 1.1, f"Confluence: global liquidity {liquidity_regime} (E19) agrees with direction"
            elif disagrees:
                return 0.85, f"Confluence: global liquidity {liquidity_regime} (E19) disagrees with direction"
        except Exception as e:
            logger.warning("Global liquidity confluence unavailable for %s: %s", symbol, e)
            if errors_out is not None:
                errors_out["global_liquidity"] = str(e)
        return None

    def _determine_direction(
        self,
        technical: TechnicalSnapshot,
        regime: RegimeClassification,
        macro_score: float,
        params: Optional[dict] = None,
    ) -> tuple[Optional[str], int, list[str]]:
        """
        Command-Center-style heuristic direction/confidence -- replaces the
        retired strict rule (technical.trend required a full EMA8>21>50
        stack plus ADX>25 just to escape "neutral" at all, which was the
        main reason live signals fired so rarely). Mirrors
        _vectorized_signal_series's bar-by-bar rule exactly (kept in sync
        deliberately, so the edge-gate backtest grades the SAME rule that's
        live) -- see that method's docstring for the formula's rationale,
        including what `params` overrides.

        Confidence is honestly |combined_score|*100 -- a heuristic
        conviction score, NOT a calibrated win-probability. Ported
        deliberately, at explicit user request, in exchange for signals
        firing far more often than the retired rule ever did; real
        historical performance still only comes from edge_validation
        (validate_historical_edge), never from this number.
        """
        from project_titan_x.engines.e08_regime.engine import MarketRegime

        params = params or {}
        entry_threshold = params.get("entry_threshold", 0.2)
        adx_divisor = params.get("adx_divisor", 25.0)
        momentum_divisor = params.get("momentum_divisor", 25.0)
        disagreement_dampening = params.get("disagreement_dampening", 0.5)

        evidence: list[str] = []
        ind = technical.indicators
        ema_fast = ind.get("ema_8", 0.0)
        ema_slow = ind.get("ema_21", 0.0)
        adx_val = ind.get("adx", 0.0)
        macd_val = ind.get("macd", 0.0)
        macd_signal_val = ind.get("macd_signal", 0.0)
        rsi_val = ind.get("rsi", 50.0)

        # Crisis regime forces no signal regardless of technical score,
        # same override Command Center applies -- every other regime is
        # informational only (see _regime_matches_direction), never a hard
        # directional veto.
        if regime.primary_regime == MarketRegime.CRISIS:
            return None, 0, ["Crisis regime — no signal regardless of technical score"]

        trend_sign = 1.0 if ema_fast >= ema_slow else -1.0
        macd_sign = 1.0 if macd_val >= macd_signal_val else -1.0
        trend_component = max(-1.0, min(1.0, adx_val / adx_divisor)) * trend_sign
        if macd_sign != trend_sign:
            trend_component *= disagreement_dampening
        momentum_component = max(-1.0, min(1.0, (rsi_val - 50.0) / momentum_divisor))
        combined = (trend_component + momentum_component) / 2

        if combined >= entry_threshold:
            direction = "LONG"
        elif combined <= -entry_threshold:
            direction = "SHORT"
        else:
            return None, 0, evidence

        confidence = int(round(min(100.0, abs(combined) * 100)))
        evidence.append(
            f"Heuristic technical score {combined:.2f} (trend {trend_component:.2f}, "
            f"momentum {momentum_component:.2f}) — a conviction read, not a backtested "
            f"win rate; see edge_validation for this asset's real historical edge"
        )

        if macro_score < -0.4 and direction == "LONG":
            confidence = max(0, confidence - 10)
            evidence.append("Macro divergence penalty applied")
        elif macro_score > 0.4 and direction == "SHORT":
            confidence = max(0, confidence - 10)
            evidence.append("Macro divergence penalty applied")

        return direction, confidence, evidence

    @staticmethod
    def _regime_matches_direction(
        direction: str,
        regime: RegimeClassification,
        evidence: list[str],
    ) -> bool:
        """Regime is informational only here, never a hard directional
        veto -- Crisis is already filtered out upstream in
        _determine_direction (forces no signal regardless of score), so by
        the time this runs, direction is already non-None and regime isn't
        Crisis. Matches Command Center's own philosophy of using regime as
        a confidence adjustment, not a gate."""
        evidence.append(f"Regime: {regime.primary_regime.value} (informational, not a directional veto)")
        return True

    @staticmethod
    def _build_macro_context(macro_snapshot: Optional[MacroSnapshot]) -> Optional[dict]:
        """Full E03 macro detail attached to every asset's output --
        macro_risk_score already affects confidence; this is the transparency
        layer so a human can see WHY, not just the resulting number."""
        if macro_snapshot is None:
            return None
        return {
            "risk_on_off_score": macro_snapshot.risk_on_off_score,
            "regime_label": macro_snapshot.regime_label,
            "liquidity_signal": macro_snapshot.liquidity_signal,
            "currency_strength": macro_snapshot.currency_strength,
            "notes": macro_snapshot.notes,
        }

    @staticmethod
    def _build_fundamental_context(symbol: str, fundamental_snapshot: Optional[FundamentalSnapshot]) -> Optional[dict]:
        """E06 fundamental detail attached to EVERY asset -- but honestly
        scoped: real yield and WTI-Brent are only included when genuinely
        relevant to this specific symbol (GOLD/SILVER, CRUDE), never
        fabricated for assets with no financial relationship to them. Yield
        curve (a broad macro-regime backdrop) is included for every asset,
        same role as macro_context above."""
        if fundamental_snapshot is None:
            return None
        relevance = relevance_for_symbol(symbol)
        return {
            "yield_curve": (
                fundamental_snapshot.yield_curve.__dict__
                if relevance["yield_curve_relevant"] and fundamental_snapshot.yield_curve
                else None
            ),
            "real_yield": (
                fundamental_snapshot.real_yield.__dict__
                if relevance["real_yield_relevant"] and fundamental_snapshot.real_yield
                else None
            ),
            "crude_oil": (
                fundamental_snapshot.crude_oil.__dict__
                if relevance["crude_oil_relevant"] and fundamental_snapshot.crude_oil
                else None
            ),
            "relevance": relevance,
            "note": (
                "Real yield and WTI-Brent drivers are only populated when genuinely "
                "relevant to this asset (GOLD/SILVER and CRUDE respectively) -- null "
                "here means 'not applicable', not 'unavailable'."
            ),
        }

    def _build_microstructure_context(
        self, df: pd.DataFrame, symbol: str, timeframe: str, asset_class: str
    ) -> Optional[dict]:
        """E11 execution-risk read attached to every asset, computed from the
        SAME OHLCV bars already fetched for this signal (no extra fetch).
        Best-effort: only runs if a real engine instance was injected (see
        __init__ / registry.py), and returns None (not an error) on any
        failure.

        CORRECTION 2026-08-21: this docstring previously claimed
        "informational only... never changes confidence or direction" --
        false. `_apply_confluence_adjustments` (~L1225) multiplies
        confidence by 0.9x when execution_risk == "high". Found while
        verifying a scan-performance optimization that would otherwise
        have silently skipped this in scan_all_assets, degrading real
        signal accuracy. Always computed, in every call path, regardless
        of include_extended_context."""
        if self._microstructure_engine is None:
            return None
        try:
            result = self._microstructure_engine.analyze(
                df, symbol=symbol, timeframe=timeframe, asset_class=asset_class
            )
        except Exception as e:
            logger.warning("Microstructure context unavailable for %s: %s", symbol, e)
            return None
        if not result.success:
            return None
        snapshot = result.data
        return {
            "estimated_spread_pct": snapshot.estimated_spread_pct,
            "estimated_spread_percentile": snapshot.estimated_spread_percentile,
            "relative_volume": snapshot.relative_volume,
            "volume_label": snapshot.volume_label,
            "amihud_illiquidity_x1e6": snapshot.amihud_illiquidity_x1e6,
            "amihud_illiquidity_percentile": snapshot.amihud_illiquidity_percentile,
            "session": snapshot.session,
            "execution_risk": snapshot.execution_risk,
            "notes": snapshot.notes,
        }

    def _build_economic_calendar_context(self, asset_name: str) -> Optional[dict]:
        """E05 upcoming high-impact recurring macro releases, attached to
        every asset's output for transparency. expected_volatility_multiplier
        reflects THIS asset's own calibrated NFP reaction (see
        scripts/training/train_e05_economic_calendar.py) -- e.g. GOLD and
        EURUSD get different, real multipliers here, not one global number
        -- falling back to the cross-asset average for an asset with no
        calibration of its own. Best-effort: only runs if a real engine
        instance was injected (see __init__ / registry.py), and returns
        None (not an error) on any failure.

        CORRECTION 2026-08-21: this docstring previously claimed
        "informational only... never changes confidence or direction" --
        false. `_apply_confluence_adjustments` (~L1229) multiplies
        confidence by 0.85x when high_impact_within_24h is true. Found
        while verifying a scan-performance optimization that would
        otherwise have silently skipped this in scan_all_assets,
        degrading real signal accuracy. Always computed, in every call
        path, regardless of include_extended_context."""
        if self._economic_calendar_engine is None:
            return None
        try:
            result = self._economic_calendar_engine.analyze(symbol=asset_name)
        except Exception as e:
            logger.warning("Economic calendar context unavailable: %s", e)
            return None
        if not result.success:
            return None
        snapshot: CalendarSnapshot = result.data
        return {
            "high_impact_within_24h": snapshot.high_impact_within_24h,
            "high_impact_within_1h": snapshot.high_impact_within_1h,
            "upcoming_events": [
                {
                    "name": e.name,
                    "date": e.date.isoformat(),
                    "impact": e.impact.value,
                    "date_confirmed": e.date_confirmed,
                    "expected_volatility_multiplier": e.expected_volatility_multiplier,
                }
                for e in snapshot.upcoming_events
            ],
        }

    def _build_knowledge_context(self, regime: RegimeClassification, asset_name: str) -> Optional[dict]:
        """E01 relevant trader/book knowledge for the current regime,
        attached to every signal for transparency (requirement #16:
        "every engine should retrieve relevant knowledge before making
        decisions") -- informational only, same convention as every other
        *_context field above: never changes confidence or direction.
        Calls document_store.hybrid_search directly (not the async
        KnowledgeEngine.search()) since generate_signal is synchronous and
        this already runs off the request thread in the API layer."""
        if self._knowledge_engine is None:
            return None
        try:
            query = f"{regime.primary_regime.value} market regime trading strategy for {asset_name}"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {
            "query": query,
            "results": [r.to_dict() for r in results],
        }

    def _build_feature_context(self, asset_name: str, df: pd.DataFrame, timeframe: str, technical: TechnicalSnapshot) -> Optional[dict]:
        """E21's assembled feature vector, attached for transparency --
        informational only, same convention as every *_context field
        here. Passes the ALREADY-COMPUTED `technical` snapshot straight
        through so E21 never re-runs analyze() a second time for the
        same bar (Rule 4)."""
        if self._feature_engineering_engine is None:
            return None
        try:
            result = self._feature_engineering_engine.compute_features(
                asset_name, df, timeframe=timeframe, technical_snapshot=technical,
            )
        except Exception as e:
            logger.warning("Feature context unavailable for %s: %s", asset_name, e)
            return None
        if not result.success:
            return None
        return result.data.to_dict()

    def _build_forecast_context(self, asset_name: str, asset_def) -> Optional[dict]:
        """E23's empirical probability-distribution forecast, attached
        for transparency -- informational only, NEVER a gate or a
        confidence input (E23 exists specifically to give a real
        probabilistic alternative to a deterministic prediction; using
        it to filter signals would turn it back into exactly the kind
        of point-prediction claim its own master-prompt scope says to
        avoid)."""
        if self._forecasting_engine is None:
            return None
        try:
            yahoo_symbol = asset_def.yahoo_symbol if asset_def else asset_name
            result = self._forecasting_engine.forecast(asset_name, yahoo_symbol, horizon_days=20)
        except Exception as e:
            logger.warning("Forecast context unavailable for %s: %s", asset_name, e)
            return None
        if not result.success:
            return None
        return result.data.to_dict()

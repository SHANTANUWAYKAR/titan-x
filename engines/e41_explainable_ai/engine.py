"""
Module: engine.py
Description: Engine 41 -- Explainable AI. Master prompt scope (draft
    detail, item #27 "Explainable AI Layer"): "every signal must answer
    technical/fundamental/macro/risk reasons + historical evidence. No
    black-box decisions."

    Deliberately NOT a new data pipeline or model -- e51_signals.TradingSignal
    already carries every field this needs (supporting_evidence,
    macro_context, fundamental_context, microstructure_context,
    economic_calendar_context, edge_validation, checks_passed,
    knowledge_context, news_context): every real engine on this platform
    already attaches its reasoning to the ONE signal E51 produces (see
    registry.py's own comment on this). What was missing was a caller having
    to manually piece together ~10 separate JSON blobs into one coherent
    story. This engine's entire job is that synthesis: a real
    aggregation/narrative layer over data that already exists per-signal,
    not a new source of truth. If a field is absent (no macro_snapshot
    passed, no knowledge_engine wired), this reports "not available"
    honestly rather than fabricating a reason.

    FIXED 2026-08-02: news_context (real, live matched headlines +
    aggregate sentiment from E09/E51's own confluence check -- see
    e51_signals._confluence_sentiment) was a real field on every
    TradingSignal, serialized in its own to_dict(), but was never read
    here at all. The generic "Confluence: N headline(s) agree/disagree"
    string already reaches confluence_reasons via supporting_evidence, but
    the actual HEADLINES driving that call were invisible -- exactly the
    "no black-box decisions" gap this engine exists to close: a trader
    could see THAT news agreed with the direction, never WHAT the news
    was.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-08-02
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)


@dataclass
class SignalExplanation:
    """Synthesized, human-readable rationale trace for one TradingSignal."""

    headline: str
    core_reasons: list[str] = field(default_factory=list)
    confluence_reasons: list[str] = field(default_factory=list)
    macro_summary: Optional[str] = None
    fundamental_summary: Optional[str] = None
    risk_summary: list[str] = field(default_factory=list)
    historical_evidence: Optional[str] = None
    knowledge_summary: Optional[str] = None
    news_summary: Optional[str] = None
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "core_reasons": self.core_reasons,
            "confluence_reasons": self.confluence_reasons,
            "macro_summary": self.macro_summary,
            "fundamental_summary": self.fundamental_summary,
            "risk_summary": self.risk_summary,
            "historical_evidence": self.historical_evidence,
            "knowledge_summary": self.knowledge_summary,
            "news_summary": self.news_summary,
            "caveats": self.caveats,
        }


class ExplainableAIEngine(BaseEngine):
    """
    Explainable AI Engine (#41) -- turns a TradingSignal's already-attached
    evidence into one coherent, prioritized narrative: technical/structural
    reasons, cross-engine confluence, macro/fundamental backdrop, risk
    caveats, and historical (backtested) evidence. Never computes a new
    number, never changes confidence/direction -- purely descriptive, over
    data that's already real.
    """

    engine_id = "e41_explainable_ai"
    engine_name = "Explainable AI Engine"
    version = "1.0.0"

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Explainable AI Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def explain(self, signal: Any) -> EngineResult:
        """Build a SignalExplanation from an e51_signals.TradingSignal (or
        anything with the same attribute shape -- typed Any deliberately,
        same decoupling convention e51_signals itself uses for its optional
        collaborators, to avoid a hard import-time dependency on e51 from
        this engine)."""
        try:
            self._set_status(EngineStatus.RUNNING)

            evidence = list(getattr(signal, "supporting_evidence", []) or [])
            core_reasons = [e for e in evidence if not e.startswith("Confluence:")]
            confluence_reasons = [e for e in evidence if e.startswith("Confluence:")]

            headline = (
                f"{signal.direction} {signal.asset} @ {signal.entry:.4f} -- "
                f"confidence {signal.confidence_score}/100, regime {signal.regime}"
            )

            macro_summary = self._summarize_macro(getattr(signal, "macro_context", None))
            fundamental_summary = self._summarize_fundamental(getattr(signal, "fundamental_context", None))
            risk_summary = self._summarize_risk(signal)
            historical_evidence = self._summarize_historical(signal)
            knowledge_summary = self._summarize_knowledge(getattr(signal, "knowledge_context", None))
            news_summary = self._summarize_news(getattr(signal, "news_context", None))
            caveats = self._build_caveats(signal)

            explanation = SignalExplanation(
                headline=headline,
                core_reasons=core_reasons,
                confluence_reasons=confluence_reasons,
                macro_summary=macro_summary,
                fundamental_summary=fundamental_summary,
                risk_summary=risk_summary,
                historical_evidence=historical_evidence,
                knowledge_summary=knowledge_summary,
                news_summary=news_summary,
                caveats=caveats,
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=explanation, message=headline)
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Explanation synthesis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _summarize_macro(macro_context: Optional[dict]) -> Optional[str]:
        if not macro_context:
            return None
        parts = []
        if macro_context.get("regime_label"):
            parts.append(f"macro regime {macro_context['regime_label']}")
        if macro_context.get("risk_on_off_score") is not None:
            parts.append(f"risk-on/off score {macro_context['risk_on_off_score']:.2f}")
        if macro_context.get("liquidity_signal"):
            parts.append(f"liquidity {macro_context['liquidity_signal']}")
        if macro_context.get("currency_strength"):
            parts.append(f"currency strength {macro_context['currency_strength']}")
        return "; ".join(parts) if parts else None

    @staticmethod
    def _summarize_fundamental(fundamental_context: Optional[dict]) -> Optional[str]:
        if not fundamental_context:
            return None
        relevant = {k: v for k, v in fundamental_context.items() if v}
        if not relevant:
            return "no fundamental factor specifically relevant to this asset"
        return f"relevant fundamental context: {', '.join(relevant.keys())}"

    @staticmethod
    def _summarize_risk(signal: Any) -> list[str]:
        out: list[str] = []
        invalidation = getattr(signal, "invalidation", None)
        if invalidation:
            out.append(f"Invalidated if: {invalidation}")

        micro = getattr(signal, "microstructure_context", None)
        if micro and micro.get("execution_risk") == "high":
            out.append("Execution risk flagged HIGH (E11 microstructure) -- wide spread/thin volume")

        cal = getattr(signal, "economic_calendar_context", None)
        if cal and cal.get("high_impact_within_1h"):
            out.append("A high-impact economic release is due within 1 hour (E05)")
        elif cal and cal.get("high_impact_within_24h"):
            out.append("A high-impact economic release is due within 24 hours (E05)")

        checks = getattr(signal, "checks_passed", {}) or {}
        failed = [k for k, v in checks.items() if not v]
        if failed:
            out.append(f"Failed checks: {', '.join(failed)}")
        return out

    @staticmethod
    def _summarize_historical(signal: Any) -> Optional[str]:
        edge = getattr(signal, "edge_validation", None)
        if edge is not None:
            return edge.message if hasattr(edge, "message") else str(edge)
        return getattr(signal, "historical_context", None)

    @staticmethod
    def _summarize_knowledge(knowledge_context: Optional[dict]) -> Optional[str]:
        if not knowledge_context or not knowledge_context.get("results"):
            return None
        top = knowledge_context["results"][0]
        title = top.get("title") or top.get("source") or "relevant book content"
        return f"Related to trader knowledge base: {title} (query: {knowledge_context.get('query', '')})"

    @staticmethod
    def _summarize_news(news_context: Optional[dict]) -> Optional[str]:
        """news_context (see e51_signals._confluence_sentiment) carries
        the actual matched headlines and aggregate sentiment score, not
        just a "N headlines agree" count -- surfaces the real WHAT, not
        just the THAT, matching this engine's "no black-box decisions"
        mandate."""
        if not news_context or not news_context.get("matched_headlines"):
            return None
        headlines = news_context["matched_headlines"]
        titles = "; ".join(h.get("title", "") for h in headlines[:3] if h.get("title"))
        score = news_context.get("aggregate_sentiment_score")
        if news_context.get("agrees_with_direction"):
            stance = "agreeing with"
        elif news_context.get("disagrees_with_direction"):
            stance = "disagreeing with"
        else:
            stance = "neutral relative to"
        score_part = f", aggregate sentiment {score:+.2f}" if score is not None else ""
        return f"{len(headlines)} matched headline(s) {stance} the signal direction{score_part}: {titles}"

    @staticmethod
    def _build_caveats(signal: Any) -> list[str]:
        caveats: list[str] = []
        edge = getattr(signal, "edge_validation", None)
        if edge is not None:
            status = getattr(edge, "status", None)
            if status == "not_significant":
                caveats.append("This exact rule's historical edge did not clear full statistical validation -- treat with caution")
            elif status == "insufficient_data":
                caveats.append("Not enough historical trades to validate this rule's edge either way")
        else:
            caveats.append("No historical edge validation was run for this signal (no technical/backtesting engine injected)")

        confidence_score = getattr(signal, "confidence_score", None)
        if confidence_score is not None and confidence_score < 50:
            caveats.append(f"Confidence ({confidence_score}/100) is a heuristic conviction score, not a calibrated win probability")

        # Added 2026-08-03: cross-referencing this engine against the
        # YouTube knowledge pipeline's extraction (Mind Math Money, 97
        # videos) found this specific mistake called out repeatedly and
        # explicitly by name -- "a very common mistake that many traders
        # [make] when they use the RSI is that they see the RSI between
        # 70 and 100 as a sell signal, and... between 30 and 0... as a
        # buy signal." e07_technical's OWN signals list emits exactly
        # that ("RSI oversold (<30)" / "RSI overbought (>70)"), and up to
        # 3 of those signals flow straight into supporting_evidence (see
        # e51_signals.generate_signal's `technical.signals[:3]`) -- so a
        # user reading this signal's evidence can see that exact
        # unqualified line. This is a caveat only (does not touch
        # e07_technical's own score/signal logic, a separate, larger
        # design question); it just discloses the known limitation
        # wherever that evidence line is actually shown.
        evidence = getattr(signal, "supporting_evidence", None) or []
        if any("rsi oversold" in e.lower() or "rsi overbought" in e.lower() for e in evidence):
            caveats.append(
                "RSI overbought/oversold alone is a commonly misused signal -- in a strong "
                "trend RSI can stay overbought/oversold for extended periods without reversing; "
                "treat as context, not a standalone reversal trigger"
            )
        return caveats

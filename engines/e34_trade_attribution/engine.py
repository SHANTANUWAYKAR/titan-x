"""
Module: engine.py
Description: Engine 34 -- Trade Attribution. Master prompt scope: "why a
    trade won or lost; attribute to regime, news, execution, timing,
    volatility, strategy quality. Lessons database."

    Groups logged trades (see e35_performance_analytics.PerformanceAnalyticsEngine,
    which owns the trade journal itself) by a dimension -- strategy, regime,
    session, symbol, direction -- and computes each group's own performance
    summary, to answer "under which conditions does this actually work" at
    the population level rather than trade-by-trade. Depends on E35 for
    both the trade journal read and the summarize() math (same convention
    as every other cross-engine dependency on this platform: an Optional
    constructor param, defaults to a real instance, so this engine behaves
    identically standalone or wired).

    No calibration/training step applies (Rule 3) -- pure grouping and
    arithmetic on logged numbers, same honest-gap category as E35.

    FIXED 2026-08-02: day_of_week_tag() existed in this module (exported,
    even unit-tested) but was dead code -- attribute_by_field never
    actually called it, so "day_of_week" wasn't a usable attribution
    dimension despite entry_time already being a real column on every
    trade. The master prompt's own scope names "timing" as an attribution
    dimension; wired it in as a derived field (see _DERIVED_FIELDS)
    alongside the stored ones.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-08-02
"""

import datetime as dt
import logging
import re
from collections import defaultdict
from typing import Any, Optional

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e35_performance_analytics.engine import PerformanceAnalyticsEngine, summarize

logger = logging.getLogger(__name__)

ALLOWED_ATTRIBUTION_FIELDS = frozenset(
    {"strategy_name", "regime_at_entry", "session_tag", "symbol", "direction", "day_of_week"}
)

# Fields not stored directly on a Trade row -- derived per-trade from
# another real column instead of a plain dict lookup. "day_of_week" is the
# one case here: day_of_week_tag() existed in this module (and was
# exported/tested) but was never actually wired into attribute_by_field --
# a real gap against this engine's own master-prompt scope ("attribute to
# ...timing...") given entry_time is already a real column on every trade.
_DERIVED_FIELDS = frozenset({"day_of_week"})

_LONDON_NY_OVERLAP_HOURS = range(12, 16)
_ACTIVE_HOURS = set(range(7, 21))

# Added 2026-08-21 for the confluence-accuracy scoreboard. Matches the
# real, consistent "(E##)" tagging convention e51_signals._apply_
# confluence_adjustments already writes into every confluence evidence
# line it generates (e.g. "Confluence: tracked cross-asset
# relationship(s) (E10) intact", "...corporate credit spreads risk_on
# (E14) agrees with direction") -- confirmed against the real source,
# not guessed. A trade's evidence comes from its linked Signal.evidence
# (see e35_performance_analytics.list_trades_with_evidence).
_ENGINE_TAG_RE = re.compile(r"\(E\d+\)")
# Real positive/negative marker phrases found in the actual evidence
# text this codebase generates -- an evidence line naming a tag but
# using neither is classified "unclassified" (honest gap) rather than
# guessed into agree/disagree.
_POSITIVE_MARKERS = ("agrees with direction", "intact")
_NEGATIVE_MARKERS = ("disagrees with direction", "breaking down", "tempered")


def day_of_week_tag(entry_time: dt.datetime) -> str:
    return entry_time.strftime("%A")


def session_tag_from_hour(hour_utc: int) -> str:
    """Rough UTC-hour session classification (Asian/London/New York), with
    the London-New York overlap called out separately since it is
    meaningfully the most liquid FX window, not just "somewhere in both"."""
    if hour_utc in _LONDON_NY_OVERLAP_HOURS:
        return "london_ny_overlap"
    if hour_utc in _ACTIVE_HOURS:
        return "london_or_new_york"
    return "asian"


class TradeAttributionEngine(BaseEngine):
    """Trade Attribution Engine (#34) -- groups the logged trade journal by
    strategy/regime/session/symbol/direction and reports each group's own
    performance, plus which group is behaving best/worst by expectancy."""

    engine_id = "e34_trade_attribution"
    engine_name = "Trade Attribution Engine"
    version = "1.0.0"

    def __init__(self, performance_engine: Optional[PerformanceAnalyticsEngine] = None) -> None:
        super().__init__()
        self._performance_engine = performance_engine or PerformanceAnalyticsEngine()

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Trade Attribution Engine initialized")

    def health_check(self) -> EngineResult:
        return self._performance_engine.health_check()

    def attribute_by_field(self, field: str, limit: int = 5000) -> EngineResult:
        """field must be one of ALLOWED_ATTRIBUTION_FIELDS -- a column that
        actually exists on every trade, not an arbitrary/injectable string."""
        if field not in ALLOWED_ATTRIBUTION_FIELDS:
            return EngineResult(
                success=False,
                message=f"field must be one of {sorted(ALLOWED_ATTRIBUTION_FIELDS)}",
            )

        trades_result = self._performance_engine.list_trades(limit=limit)
        if not trades_result.success:
            return trades_result
        trades = trades_result.data
        if not trades:
            return EngineResult(success=False, message="No trades found")

        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for trade in trades:
            if field in _DERIVED_FIELDS:
                entry_time = trade.get("entry_time")
                key = day_of_week_tag(entry_time) if entry_time is not None else "unspecified"
            else:
                key = trade.get(field) or "unspecified"
            groups[key].append(trade)

        results = {}
        for key, group_trades in groups.items():
            pnl_rs = [t["pnl_r"] or 0.0 for t in group_trades]
            pnl_pcts = [t["pnl_percent"] or 0.0 for t in group_trades]
            results[key] = summarize(pnl_rs, pnl_pcts)

        best_group = max(results, key=lambda k: results[k].expectancy_r)
        worst_group = min(results, key=lambda k: results[k].expectancy_r)

        return EngineResult(
            success=True,
            data={"groups": results, "best_group": best_group, "worst_group": worst_group},
            message=f"Attributed {len(trades)} trade(s) across {len(results)} {field} group(s)",
        )

    def attribute_by_confluence_tag(self, limit: int = 5000) -> EngineResult:
        """Confluence-accuracy scoreboard, added 2026-08-21: "when engine
        E## agreed with the trade's direction, did we actually win more
        often." Reads each trade's real linked-signal evidence (E35's
        list_trades_with_evidence) and, for every (E##) tag found in it,
        buckets that trade into agree/disagree/unclassified for that tag
        -- then reports each bucket's real win_rate/expectancy, same
        summarize() math as attribute_by_field. A trade with no linked
        signal (or a signal whose evidence never mentioned a given tag)
        simply doesn't contribute to that tag's buckets -- not forced
        into a fabricated "no confluence" bucket.

        This directly closes the loop _persist_signal's own docstring
        set up but never had an analysis on top of: real signals have
        been queryable since evidence was first persisted, this is the
        first thing that actually asks "was that evidence predictive."
        """
        trades_result = self._performance_engine.list_trades_with_evidence(limit=limit)
        if not trades_result.success:
            return trades_result
        trades = trades_result.data
        if not trades:
            return EngineResult(success=False, message="No trades found")

        # tag -> classification ("agree"/"disagree"/"unclassified") -> trades
        buckets: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for trade in trades:
            for line in trade.get("evidence") or []:
                tags = _ENGINE_TAG_RE.findall(line)
                if not tags:
                    continue
                lowered = line.lower()
                if any(m in lowered for m in _POSITIVE_MARKERS):
                    classification = "agree"
                elif any(m in lowered for m in _NEGATIVE_MARKERS):
                    classification = "disagree"
                else:
                    classification = "unclassified"
                for tag in tags:
                    buckets[tag][classification].append(trade)

        if not buckets:
            return EngineResult(success=False, message="No confluence-tagged evidence found in any trade's linked signal")

        scoreboard: dict[str, dict[str, Any]] = {}
        for tag, classes in buckets.items():
            tag_result: dict[str, Any] = {}
            for classification, group_trades in classes.items():
                pnl_rs = [t["pnl_r"] or 0.0 for t in group_trades]
                pnl_pcts = [t["pnl_percent"] or 0.0 for t in group_trades]
                tag_result[classification] = summarize(pnl_rs, pnl_pcts)
            scoreboard[tag] = tag_result

        return EngineResult(
            success=True,
            data=scoreboard,
            message=f"Confluence-accuracy scoreboard across {len(scoreboard)} engine tag(s) from {len(trades)} trade(s)",
        )

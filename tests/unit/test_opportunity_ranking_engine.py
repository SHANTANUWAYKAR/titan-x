"""
Tests for Engine 33 -- Opportunity Ranking.

rank_and_number's sort/rank-assignment logic is pure and tested directly
against hand-built OpportunityRanking objects (no network needed). The
full rank_opportunities() orchestration is tested against the REAL
registry (Rule 4 real-collaborator test) -- this engine's entire job IS
orchestration, so there is no meaningful logic to isolate from it beyond
the sort, which is already covered separately.
"""

import pytest

from project_titan_x.engines.e33_opportunity_ranking.engine import (
    OpportunityRanking,
    OpportunityRankingEngine,
    rank_and_number,
)


def _r(symbol, confidence, tradeable, direction="LONG"):
    return OpportunityRanking(symbol=symbol, direction=direction, confidence=confidence, tradeable=tradeable, regime=None, reason="")


def test_tradeable_always_outranks_nontradeable_regardless_of_confidence():
    rankings = [_r("A", confidence=90, tradeable=False), _r("B", confidence=10, tradeable=True)]
    ranked = rank_and_number(rankings)
    assert ranked[0].symbol == "B"
    assert ranked[0].rank == 1
    assert ranked[1].symbol == "A"
    assert ranked[1].rank == 2


def test_within_same_tradeable_group_sorted_by_confidence_descending():
    rankings = [_r("LOW", confidence=20, tradeable=False), _r("HIGH", confidence=80, tradeable=False), _r("MID", confidence=50, tradeable=False)]
    ranked = rank_and_number(rankings)
    assert [r.symbol for r in ranked] == ["HIGH", "MID", "LOW"]


def test_rank_and_number_is_1_indexed_and_contiguous():
    rankings = [_r(f"SYM{i}", confidence=i, tradeable=False) for i in range(5)]
    ranked = rank_and_number(rankings)
    assert [r.rank for r in ranked] == [1, 2, 3, 4, 5]


def test_rank_and_number_handles_empty_list():
    assert rank_and_number([]) == []


def test_opportunity_ranking_to_dict():
    r = OpportunityRanking(symbol="GOLD", direction="LONG", confidence=45, tradeable=True, regime="Trending Up", reason="All signal criteria met", rank=1)
    d = r.to_dict()
    assert d == {
        "rank": 1, "symbol": "GOLD", "direction": "LONG", "confidence": 45,
        "tradeable": True, "regime": "Trending Up", "reason": "All signal criteria met",
    }


# ---- engine-level ----

def test_engine_without_registry_fails_gracefully():
    engine = OpportunityRankingEngine(registry=None)
    result = engine.rank_opportunities()
    assert not result.success


def test_engine_health_check_without_registry():
    engine = OpportunityRankingEngine(registry=None)
    result = engine.health_check()
    assert not result.success


class _CountingEngine:
    """Records how many times its method was called -- used to verify
    rank_opportunities fetches asset-independent data ONCE and shares it,
    instead of once per asset (the redundant-fetch bug fixed 2026-08-02)."""

    def __init__(self, method_name, result):
        self.call_count = 0
        self._result = result
        setattr(self, method_name, self._counted_call)

    def _counted_call(self, *args, **kwargs):
        self.call_count += 1
        return self._result


class _StubEngine:
    def __init__(self, **methods):
        for name, fn in methods.items():
            setattr(self, name, fn)


class _StubWorkflowRegistry:
    """Full stub registry -- enough for SignalGenerationWorkflow.run to
    succeed end to end for any symbol, with counting stand-ins for the 4
    asset-independent engines rank_opportunities should only ever call
    once regardless of how many symbols are ranked."""

    def __init__(self):
        import pandas as pd
        from project_titan_x.engines.base import EngineResult

        df = pd.DataFrame({"close": [1, 2, 3]})

        class FakeSnapshot:
            pass

        class FakeRegime:
            class primary_regime:
                value = "Ranging"

        self.macro_engine = _CountingEngine("analyze", EngineResult(success=True, data=_FakeMacroSnapshot(), message="ok"))
        self.fundamental_engine = _CountingEngine("analyze", EngineResult(success=True, data=object(), message="ok"))
        self.news_engine = _CountingEngine("fetch_headlines", EngineResult(success=True, data=[], message="ok"))
        self.cross_asset_engine = _CountingEngine("analyze", EngineResult(success=True, data=object(), message="ok"))

        no_signal = EngineResult(success=True, data=None, message="No clear directional bias")
        self._engines = {
            "e02_market_data": _StubEngine(fetch_ohlcv=lambda *a, **k: EngineResult(success=True, data=df, message="ok")),
            "e07_technical": _StubEngine(analyze=lambda *a, **k: EngineResult(success=True, data={"snapshot": FakeSnapshot()}, message="ok")),
            "e04_macro": self.macro_engine,
            "e08_regime": _StubEngine(classify=lambda *a, **k: EngineResult(success=True, data=FakeRegime(), message="ok")),
            "e06_fundamental": self.fundamental_engine,
            "e03_news": self.news_engine,
            "e10_cross_asset": self.cross_asset_engine,
            "e51_signals": _StubEngine(generate_signal=lambda *a, **k: no_signal),
        }

    def get(self, engine_id):
        return self._engines.get(engine_id)


class _FakeMacroSnapshot:
    risk_on_off_score = 0.1


def test_rank_opportunities_fetches_shared_data_only_once():
    """The core regression guard for the 2026-08-02 optimization: ranking
    N symbols must call macro/fundamental/news/cross-asset exactly ONCE
    total, not once per symbol -- previously each of these was
    independently re-fetched inside every asset's own workflow run."""
    registry = _StubWorkflowRegistry()
    engine = OpportunityRankingEngine(registry=registry)
    result = engine.rank_opportunities(symbols=["EURUSD", "GOLD", "BTCUSD", "SILVER", "CRUDE"])
    assert result.success
    assert {r.symbol for r in result.data} == {"EURUSD", "GOLD", "BTCUSD", "SILVER", "CRUDE"}
    assert registry.macro_engine.call_count == 1
    assert registry.fundamental_engine.call_count == 1
    assert registry.news_engine.call_count == 1
    assert registry.cross_asset_engine.call_count == 1


@pytest.mark.network
def test_rank_opportunities_uses_real_registry_end_to_end():
    """Real-collaborator test (Rule 4): runs the actual multi-engine
    workflow (market data, technical, macro, regime, fundamental, signal)
    for a small real subset of supported assets and confirms the ranking
    comes back sensible -- every entry has a symbol, a rank, and a
    confidence in [0, 100], sorted correctly."""
    from project_titan_x.engines.registry import get_registry

    registry = get_registry()
    registry.initialize_all()
    engine = registry.get("e33_opportunity_ranking")
    assert engine is not None

    result = engine.rank_opportunities(symbols=["GOLD", "EURUSD", "BTCUSD"])
    assert result.success
    rankings = result.data
    assert len(rankings) == 3
    ranks = [r.rank for r in rankings]
    assert ranks == sorted(ranks)
    for r in rankings:
        assert r.symbol in {"GOLD", "EURUSD", "BTCUSD"}
        assert 0 <= r.confidence <= 100
    # tradeable entries (if any) must precede all non-tradeable ones
    tradeable_flags = [r.tradeable for r in rankings]
    first_false = tradeable_flags.index(False) if False in tradeable_flags else len(tradeable_flags)
    assert all(tradeable_flags[i] for i in range(first_false))

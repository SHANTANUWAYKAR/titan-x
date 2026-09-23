"""
Module: test_titan_brain.py
Description: Unit tests for Engine 00 (Titan Brain) -- event bus,
    platform state, task scheduler, workflow orchestration (against a
    fake registry so these tests don't hit the network), and the
    TitanBrainEngine facade's dispatch/run_workflow/health_snapshot.
Author: Shantanu Waykar
Version: 1.0.0
"""

import asyncio

import pytest

from project_titan_x.engines.base import EngineResult
from project_titan_x.engines.e00_titan_brain.engine import TitanBrainEngine
from project_titan_x.engines.e00_titan_brain.event_bus import EventBus
from project_titan_x.engines.e00_titan_brain.scheduler import TaskScheduler
from project_titan_x.engines.e00_titan_brain.state import PlatformState
from project_titan_x.engines.e00_titan_brain.workflows import SignalGenerationWorkflow

# ---------------------------------------------------------------------------
# event_bus.py
# ---------------------------------------------------------------------------


def test_event_bus_publish_calls_subscribed_handler():
    bus = EventBus()
    received = []
    bus.subscribe("test_event", lambda e: received.append(e.payload))
    bus.publish("test_event", {"x": 1})
    assert received == [{"x": 1}]


def test_event_bus_unrelated_subscribers_not_called():
    bus = EventBus()
    calls = []
    bus.subscribe("a", lambda e: calls.append("a"))
    bus.subscribe("b", lambda e: calls.append("b"))
    bus.publish("a", {})
    assert calls == ["a"]


def test_event_bus_handler_exception_does_not_break_other_handlers():
    bus = EventBus()
    calls = []

    def bad_handler(event):
        raise RuntimeError("boom")

    bus.subscribe("evt", bad_handler)
    bus.subscribe("evt", lambda e: calls.append("ok"))
    bus.publish("evt", {})
    assert calls == ["ok"]


def test_event_bus_unsubscribe():
    bus = EventBus()
    calls = []
    handler = lambda e: calls.append(1)
    bus.subscribe("evt", handler)
    bus.unsubscribe("evt", handler)
    bus.publish("evt", {})
    assert calls == []


def test_event_bus_history_filters_by_type_and_limit():
    bus = EventBus()
    for i in range(5):
        bus.publish("a", {"i": i})
    bus.publish("b", {})
    assert len(bus.history(event_type="a")) == 5
    assert len(bus.history(event_type="a", limit=2)) == 2
    assert len(bus.history()) == 6


def test_event_bus_history_is_bounded():
    bus = EventBus(history_size=3)
    for i in range(10):
        bus.publish("a", {"i": i})
    assert len(bus.history(limit=100)) == 3


# ---------------------------------------------------------------------------
# state.py
# ---------------------------------------------------------------------------


def test_platform_state_set_and_get(tmp_path):
    state = PlatformState(persist_path=tmp_path / "state.json")
    state.set("regime.BTCUSD", "Trending Up")
    assert state.get("regime.BTCUSD") == "Trending Up"


def test_platform_state_get_missing_key_returns_default(tmp_path):
    state = PlatformState(persist_path=tmp_path / "state.json")
    assert state.get("nonexistent", "fallback") == "fallback"


def test_platform_state_persists_across_instances(tmp_path):
    path = tmp_path / "state.json"
    state1 = PlatformState(persist_path=path)
    state1.set("key", {"nested": [1, 2, 3]})

    state2 = PlatformState(persist_path=path)
    assert state2.get("key") == {"nested": [1, 2, 3]}


def test_platform_state_delete(tmp_path):
    state = PlatformState(persist_path=tmp_path / "state.json")
    state.set("k", "v")
    state.delete("k")
    assert state.get("k") is None


def test_platform_state_keys_with_prefix(tmp_path):
    state = PlatformState(persist_path=tmp_path / "state.json")
    state.set("signal.BTCUSD", 1)
    state.set("signal.EURUSD", 2)
    state.set("regime.BTCUSD", 3)
    assert sorted(state.keys(prefix="signal.")) == ["signal.BTCUSD", "signal.EURUSD"]


# ---------------------------------------------------------------------------
# scheduler.py
# ---------------------------------------------------------------------------


async def test_scheduler_schedule_once_runs_after_delay():
    scheduler = TaskScheduler()
    calls = []
    scheduler.schedule_once("once", 0.01, lambda: calls.append(1))
    await asyncio.sleep(0.05)
    assert calls == [1]
    await scheduler.stop_all()


async def test_scheduler_schedule_interval_runs_multiple_times():
    scheduler = TaskScheduler()
    calls = []
    scheduler.schedule_interval("recurring", 0.01, lambda: calls.append(1))
    await asyncio.sleep(0.05)
    await scheduler.stop_all()
    assert len(calls) >= 2


async def test_scheduler_cancel_stops_future_runs():
    """cancel() must stop the RECURRING LOOP -- which is a different claim
    from "no callback can ever run again", and only the first is true.

    WHY THIS IS NOT AN EXACT-EQUALITY ASSERTION ANY MORE. `_invoke` runs a
    sync callable via `asyncio.to_thread`, and a thread that has already
    been handed to the executor CANNOT be cancelled -- cancelling the
    awaiting coroutine raises CancelledError in the coroutine while the
    worker thread runs to completion. So exactly one already-dispatched
    callback may still land after cancel().

    That is real asyncio behaviour, not a slow machine, and the old
    `== count_at_cancel` assertion was asserting a guarantee the runtime
    does not make. Reproduced deliberately: 1 of 25 trials produced exactly
    one extra callback, which is why this only ever failed under full-suite
    load and always passed when run alone.

    The contract that IS guaranteed, and what the test now proves: after
    the in-flight callback drains, the count stops growing entirely.
    """
    scheduler = TaskScheduler()
    calls = []
    scheduler.schedule_interval("recurring", 0.01, lambda: calls.append(1))
    await asyncio.sleep(0.03)
    assert calls, "the task never ran; the rest of this test would be vacuous"

    scheduler.cancel("recurring")
    count_at_cancel = len(calls)

    # Long enough for any in-flight thread to finish and for many further
    # intervals (0.01s) to have elapsed had the loop still been alive.
    await asyncio.sleep(0.05)
    after_drain = len(calls)
    assert after_drain <= count_at_cancel + 1, (
        f"{after_drain - count_at_cancel} callbacks ran after cancel; at most one "
        "already-dispatched thread may drain"
    )

    # The real assertion: the recurring loop is dead, so nothing more runs.
    await asyncio.sleep(0.05)
    assert len(calls) == after_drain, "cancel() did not stop the recurring loop"

    await scheduler.stop_all()


async def test_scheduler_records_error_without_crashing():
    scheduler = TaskScheduler()

    def failing():
        raise ValueError("nope")

    scheduler.schedule_once("bad", 0.01, failing)
    await asyncio.sleep(0.05)
    tasks = scheduler.list_tasks()
    assert tasks[0]["last_error"] == "nope"
    await scheduler.stop_all()


async def test_scheduler_supports_async_callables():
    scheduler = TaskScheduler()
    calls = []

    async def async_fn():
        calls.append(1)

    scheduler.schedule_once("async_once", 0.01, async_fn)
    await asyncio.sleep(0.05)
    assert calls == [1]
    await scheduler.stop_all()


# ---------------------------------------------------------------------------
# workflows.py -- fake registry, no network calls
# ---------------------------------------------------------------------------


class _StubEngine:
    def __init__(self, **methods):
        for name, fn in methods.items():
            setattr(self, name, fn)


class _StubRegistry:
    def __init__(self, engines: dict):
        self._engines = engines

    def get(self, engine_id):
        return self._engines.get(engine_id)

    def health_check_all(self):
        return {
            eid: (engine.health_check().success if hasattr(engine, "health_check") else True)
            for eid, engine in self._engines.items()
        }


def test_signal_generation_workflow_stops_at_first_failed_step():
    registry = _StubRegistry({
        "e02_market_data": _StubEngine(fetch_ohlcv=lambda *a, **k: EngineResult(success=False, message="fetch failed")),
    })
    workflow = SignalGenerationWorkflow(registry)
    result = workflow.run("EURUSD")
    assert result.success is False
    assert result.steps[0].step_name == "fetch_market_data"
    assert result.steps[0].success is False
    assert len(result.steps) == 1  # never reached later steps


def test_signal_generation_workflow_missing_engine_reported_by_name():
    registry = _StubRegistry({})  # no e02_market_data registered at all
    workflow = SignalGenerationWorkflow(registry)
    result = workflow.run("EURUSD")
    assert result.success is False
    assert "E02" in result.steps[0].message


def test_signal_generation_workflow_runs_full_pipeline_with_stubs():
    import pandas as pd

    df = pd.DataFrame({"close": [1, 2, 3]})

    class FakeSnapshot:
        pass

    class FakeRegime:
        class primary_regime:
            value = "Ranging"

    fake_signal_result = EngineResult(success=True, data=None, message="No clear directional bias")

    registry = _StubRegistry({
        "e02_market_data": _StubEngine(fetch_ohlcv=lambda *a, **k: EngineResult(success=True, data=df, message="ok")),
        "e40_data_quality": _StubEngine(
            validate=lambda df, expected_freq=None: EngineResult(success=True, data=None, message="ok"),
            repair=lambda df: EngineResult(success=True, data=df, message="ok"),
        ),
        "e07_technical": _StubEngine(
            analyze=lambda *a, **k: EngineResult(success=True, data={"snapshot": FakeSnapshot()}, message="ok")
        ),
        "e04_macro": _StubEngine(analyze=lambda: EngineResult(success=False, message="unavailable")),
        "e08_regime": _StubEngine(classify=lambda *a, **k: EngineResult(success=True, data=FakeRegime(), message="ok")),
        "e06_fundamental": _StubEngine(analyze=lambda: EngineResult(success=False, message="unavailable")),
        "e51_signals": _StubEngine(generate_signal=lambda *a, **k: fake_signal_result),
    })
    workflow = SignalGenerationWorkflow(registry)
    result = workflow.run("EURUSD")
    assert result.success is True
    step_names = [s.step_name for s in result.steps]
    assert step_names == [
        "fetch_market_data", "data_quality_validate", "data_quality_repair", "technical_analysis",
        "macro_analysis", "regime_classification", "fundamental_analysis", "generate_signal",
    ]
    assert result.final_data["signal"] is None  # no signal fired, no committee step


# ---------------------------------------------------------------------------
# engine.py -- TitanBrainEngine facade
# ---------------------------------------------------------------------------


@pytest.fixture
def brain(tmp_path) -> TitanBrainEngine:
    registry = _StubRegistry({
        "e02_market_data": _StubEngine(
            fetch_ohlcv=lambda *a, **k: EngineResult(success=True, data="fake_df", message="fetched"),
            health_check=lambda: EngineResult(success=True, message="ok"),
        ),
    })
    engine = TitanBrainEngine(registry=registry, state_path=tmp_path / "state.json")
    engine.initialize()
    return engine


def test_dispatch_calls_target_engine_method(brain):
    result = brain.dispatch("e02_market_data", "fetch_ohlcv", "EURUSD=X", "1d")
    assert result.success
    assert result.data == "fake_df"


def test_dispatch_unknown_engine_fails_gracefully(brain):
    result = brain.dispatch("nonexistent_engine", "some_method")
    assert result.success is False
    assert "not registered" in result.message


def test_dispatch_unknown_method_fails_gracefully(brain):
    result = brain.dispatch("e02_market_data", "nonexistent_method")
    assert result.success is False
    assert "no callable method" in result.message


def test_dispatch_records_state_and_publishes_event(brain):
    brain.dispatch("e02_market_data", "fetch_ohlcv", "EURUSD=X", "1d")
    assert brain.get_state("last_dispatch.e02_market_data.fetch_ohlcv") is not None
    events = brain.event_bus.history(event_type="dispatch")
    assert len(events) == 1


def test_run_workflow_unknown_name_fails(brain):
    result = brain.run_workflow("nonexistent_workflow", symbol="EURUSD")
    assert result.success is False
    assert "Unknown workflow" in result.message


async def test_schedule_and_cancel_workflow(brain):
    result = brain.schedule_workflow("test_job", "signal_generation", 0.01, symbol="EURUSD")
    assert result.success
    await asyncio.sleep(0.03)
    cancelled = brain.cancel_scheduled("test_job")
    assert cancelled.success
    await brain.scheduler.stop_all()


async def test_schedule_bybit_capture_wires_capture_and_persist_onto_scheduler(brain, monkeypatch):
    """Doesn't hit the real Bybit network -- monkeypatches
    capture_and_persist at its own module so this test verifies the
    SCHEDULING wiring (right function, right kwargs, runs as an async
    task) deterministically. The real network path was verified
    separately, live, against Bybit's production feed (see CLAUDE.md)."""
    import project_titan_x.core.data_providers.bybit_trade_feed as feed_module

    calls = []

    async def fake_capture_and_persist(duration_seconds, bar_seconds, symbols):
        calls.append((duration_seconds, bar_seconds, symbols))
        return {s: 1 for s in symbols}

    monkeypatch.setattr(feed_module, "capture_and_persist", fake_capture_and_persist)

    result = brain.schedule_bybit_capture(
        name="test_bybit_job", interval_seconds=1.0, capture_duration_seconds=0.01,
        bar_seconds=5, symbols=["BTCUSD"],
    )
    assert result.success
    await asyncio.sleep(0.05)
    cancelled = brain.cancel_scheduled("test_bybit_job")
    assert cancelled.success
    await brain.scheduler.stop_all()

    assert len(calls) >= 1
    assert calls[0] == (0.01, 5, ["BTCUSD"])


def test_health_snapshot_reports_engine_health(brain):
    snapshot = brain.health_snapshot()
    assert snapshot.success
    assert snapshot.data["engines_total"] == 1
    assert "scheduled_tasks" in snapshot.data
    assert "recent_events" in snapshot.data

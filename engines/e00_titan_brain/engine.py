"""
Module: engine.py
Description: Engine 00 -- Titan Brain (Master Orchestrator).

    Composes four primitives around the existing EngineRegistry rather
    than replacing it:
      - dispatch()        Controls every engine: generic call-through to
                           any registered engine's method, with event
                           routing and state tracking.
      - run_workflow()     Workflow orchestration: runs a named, multi-
                           engine pipeline (see workflows.py) end to end
                           with a full per-step audit trail.
      - schedule_workflow() Task scheduling: repeats a workflow on an
                           interval (see scheduler.py).
      - event_bus / state  Agent communication + event routing + state
                           management (see event_bus.py / state.py).

    Governance: Titan Brain orchestrates RESEARCH pipelines (fetch,
    analyze, classify, signal, committee review). It has no execution
    engine to hand off to, and must never gain the authority to bypass
    E45's veto or execute trades without human approval -- consistent
    with every other engine in this platform.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e00_titan_brain.event_bus import EventBus
from project_titan_x.engines.e00_titan_brain.scheduler import TaskScheduler
from project_titan_x.engines.e00_titan_brain.state import PlatformState
from project_titan_x.engines.e00_titan_brain.workflows import WORKFLOWS

logger = logging.getLogger(__name__)


class TitanBrainEngine(BaseEngine):
    """Master Orchestrator -- controls every engine, schedules and runs
    workflows, tracks platform state, and routes events between engines."""

    engine_id = "e00_titan_brain"
    engine_name = "Titan Brain (Master Orchestrator)"
    version = "1.0.0"

    def __init__(self, registry: Any, state_path: Optional[Path] = None) -> None:
        super().__init__()
        self.registry = registry
        self.event_bus = EventBus()
        self.state = PlatformState(persist_path=state_path)
        self.scheduler = TaskScheduler()
        self._workflows = {name: cls(registry) for name, cls in WORKFLOWS.items()}

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(
            success=True,
            message="Titan Brain initialized",
            metadata={"workflows": list(self._workflows.keys()), "engines_controlled": len(self.registry._engines)},
        )

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    # ---- controls every engine ----

    def dispatch(self, engine_id: str, method_name: str, *args, **kwargs) -> EngineResult:
        """Generic call-through to any registered engine's method."""
        engine = self.registry.get(engine_id)
        if engine is None:
            return EngineResult(success=False, message=f"Engine {engine_id!r} not registered")
        method = getattr(engine, method_name, None)
        if method is None or not callable(method):
            return EngineResult(success=False, message=f"{engine_id} has no callable method {method_name!r}")

        try:
            result = method(*args, **kwargs)
        except Exception as e:
            logger.error("Dispatch %s.%s failed: %s", engine_id, method_name, e)
            self.event_bus.publish(
                "dispatch_error", {"engine_id": engine_id, "method": method_name, "error": str(e)}, source="titan_brain"
            )
            return EngineResult(success=False, message=str(e), errors=[str(e)])

        self.state.set(
            f"last_dispatch.{engine_id}.{method_name}",
            {"success": result.success, "message": result.message, "timestamp": datetime.now(timezone.utc).isoformat()},
        )
        self.event_bus.publish(
            "dispatch", {"engine_id": engine_id, "method": method_name, "success": result.success}, source="titan_brain"
        )
        return result

    # ---- workflow orchestration ----

    def run_workflow(self, workflow_name: str, **kwargs: Any) -> EngineResult:
        workflow = self._workflows.get(workflow_name)
        if workflow is None:
            return EngineResult(
                success=False,
                message=f"Unknown workflow {workflow_name!r}. Available: {list(self._workflows.keys())}",
            )
        result = workflow.run(**kwargs)
        state_key = f"last_workflow.{workflow_name}." + str(kwargs.get("symbol", "default"))
        self.state.set(state_key, result.to_dict())
        self.event_bus.publish(
            "workflow_completed",
            {"workflow_name": workflow_name, "success": result.success, "steps": [s.step_name for s in result.steps]},
            source="titan_brain",
        )
        return EngineResult(
            success=result.success,
            data=result,
            message=f"Workflow {workflow_name}: {'completed' if result.success else 'failed'} "
                     f"({len(result.steps)} step(s))",
        )

    def list_workflows(self) -> list[str]:
        return list(self._workflows.keys())

    # ---- task scheduling ----

    def schedule_workflow(self, name: str, workflow_name: str, interval_seconds: float, **kwargs: Any) -> EngineResult:
        """Repeats run_workflow(workflow_name, **kwargs) on an interval.
        Nothing is scheduled by default anywhere in this codebase -- this
        is a capability a caller opts into explicitly."""
        if workflow_name not in self._workflows:
            return EngineResult(success=False, message=f"Unknown workflow {workflow_name!r}")

        def runner() -> EngineResult:
            return self.run_workflow(workflow_name, **kwargs)

        self.scheduler.schedule_interval(name, interval_seconds, runner)
        return EngineResult(success=True, message=f"Scheduled '{workflow_name}' every {interval_seconds}s as '{name}'")

    def schedule_bybit_capture(
        self,
        name: str = "bybit_order_flow_capture",
        interval_seconds: float = 300.0,
        capture_duration_seconds: float = 280.0,
        bar_seconds: int = 60,
        symbols: Optional[list[str]] = None,
    ) -> EngineResult:
        """Recurring REAL crypto order-flow capture (genuine buy/sell-
        tagged Bybit trade ticks -- see core/data_providers/
        bybit_trade_feed.py) for BTCUSD/ETHUSD, merged into
        data/processed/live_order_flow/ on every run.

        Wired directly onto the scheduler rather than through the
        WORKFLOWS/run_workflow abstraction on purpose: that abstraction
        specifically sequences REGISTERED ENGINE calls with a per-step
        audit trail (see workflows.py's own docstring); this doesn't call
        any registered engine at all, it's an I/O-bound streaming
        ingestion job, closer in kind to a scheduled maintenance/data
        pull than a multi-engine analysis pipeline. TaskScheduler's own
        _invoke already awaits async callables directly, so
        capture_and_persist runs as-is -- no sync-wrapping needed the way
        a WORKFLOWS entry would require.

        capture_duration_seconds defaults to comfortably less than
        interval_seconds (a 20s gap) so each run finishes before the next
        is due -- TaskScheduler.schedule_interval sleeps interval_seconds
        AFTER each run completes (see its own runner()), so a
        capture_duration_seconds >= interval_seconds would make runs
        drift/queue rather than run back-to-back cleanly.

        Nothing is scheduled by default anywhere in this codebase -- this
        is a capability a caller opts into explicitly, same as
        schedule_workflow."""
        from project_titan_x.core.data_providers.bybit_trade_feed import capture_and_persist

        symbols = symbols or ["BTCUSD", "ETHUSD"]
        self.scheduler.schedule_interval(
            name, interval_seconds, capture_and_persist,
            duration_seconds=capture_duration_seconds, bar_seconds=bar_seconds, symbols=symbols,
        )
        return EngineResult(
            success=True,
            message=f"Scheduled real Bybit order-flow capture every {interval_seconds}s as '{name}' "
                     f"({capture_duration_seconds}s capture window, {bar_seconds}s bars, symbols={symbols})",
        )

    def cancel_scheduled(self, name: str) -> EngineResult:
        cancelled = self.scheduler.cancel(name)
        return EngineResult(success=cancelled, message="Cancelled" if cancelled else f"No scheduled task named {name!r}")

    def list_scheduled(self) -> list[dict[str, Any]]:
        return self.scheduler.list_tasks()

    async def shutdown(self) -> None:
        await self.scheduler.stop_all()

    # ---- state + events ----

    def get_state(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def state_snapshot(self) -> dict[str, Any]:
        return self.state.snapshot()

    def subscribe(self, event_type: str, handler) -> None:
        self.event_bus.subscribe(event_type, handler)

    def publish(self, event_type: str, payload: Optional[dict[str, Any]] = None) -> None:
        self.event_bus.publish(event_type, payload, source="external")

    # ---- platform-wide health ----

    def health_snapshot(self) -> EngineResult:
        engine_health = self.registry.health_check_all()
        return EngineResult(
            success=True,
            data={
                "engines": engine_health,
                "engines_healthy": sum(1 for ok in engine_health.values() if ok),
                "engines_total": len(engine_health),
                "scheduled_tasks": self.scheduler.list_tasks(),
                "recent_events": [e.to_dict() for e in self.event_bus.history(limit=20)],
            },
            message=f"{sum(1 for ok in engine_health.values() if ok)}/{len(engine_health)} engines healthy",
        )

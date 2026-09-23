"""
Module: state.py
Description: Platform-wide state store for Titan Brain -- last known
    regime/signal/health per asset, workflow run history. In-memory with
    JSON persistence to disk (data/state/platform_state.json) so state
    survives a process restart; no database server required, matching
    every other lightweight-persistence pattern already in this project
    (data/models/*.json, data/processed/*.parquet).
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("data/state/platform_state.json")


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class PlatformState:
    """Thread-safe key/value store with disk persistence. Keys are
    dotted-ish strings by convention (e.g. "signal.EURUSD",
    "regime.BTCUSD") but any string works -- no schema is enforced."""

    def __init__(self, persist_path: Optional[Path] = None) -> None:
        self._persist_path = persist_path or DEFAULT_STATE_PATH
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self._persist_path.exists():
            return
        try:
            self._data = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load platform state from %s: %s", self._persist_path, e)
            self._data = {}

    def save(self) -> None:
        with self._lock:
            try:
                self._persist_path.write_text(
                    json.dumps(self._data, indent=2, default=_json_default), encoding="utf-8"
                )
            except Exception as e:
                logger.error("Failed to persist platform state: %s", e)

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        with self._lock:
            self._data[key] = value
        if persist:
            self.save()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def delete(self, key: str, persist: bool = True) -> None:
        with self._lock:
            self._data.pop(key, None)
        if persist:
            self.save()

    def keys(self, prefix: str | None = None) -> list[str]:
        with self._lock:
            all_keys = list(self._data.keys())
        return [k for k in all_keys if prefix is None or k.startswith(prefix)]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

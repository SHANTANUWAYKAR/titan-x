"""
Module: base.py
Description: Base engine interface for all PROJECT TITAN-X engines.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class EngineStatus(str, Enum):
    """Engine operational status."""

    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class EngineResult:
    """Standard result container for engine operations."""

    success: bool
    data: Any = None
    message: str = ""
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseEngine(ABC):
    """
    Abstract base class for all Titan-X engines.

    Every engine must implement initialize() and health_check().
    """

    engine_id: str = "base"
    engine_name: str = "Base Engine"
    version: str = "1.0.0"

    def __init__(self) -> None:
        self._status = EngineStatus.IDLE
        self._last_run: Optional[datetime] = None
        self.logger = logging.getLogger(f"titanx.{self.engine_id}")

    @property
    def status(self) -> EngineStatus:
        """Current engine status."""
        return self._status

    @abstractmethod
    def initialize(self) -> EngineResult:
        """
        Initialize engine resources.

        Returns:
            EngineResult indicating success or failure.
        """

    @abstractmethod
    def health_check(self) -> EngineResult:
        """
        Check engine health.

        Returns:
            EngineResult with health status.
        """

    def _set_status(self, status: EngineStatus) -> None:
        """Update engine status."""
        self._status = status
        self._last_run = datetime.now(timezone.utc)

    def get_info(self) -> dict[str, Any]:
        """Return engine metadata."""
        return {
            "engine_id": self.engine_id,
            "engine_name": self.engine_name,
            "version": self.version,
            "status": self._status.value,
            "last_run": self._last_run.isoformat() if self._last_run else None,
        }

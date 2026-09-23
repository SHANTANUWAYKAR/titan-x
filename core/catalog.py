"""
Module: catalog.py
Description: Dataset catalog -- an append-only audit log plus a queryable
    "latest state" registry for every dataset an engine fetches (symbol,
    timeframe, source, row count, date range, quality score, checksum,
    version). Real, file-based (JSONL + JSON), consistent with this
    project's existing parquet/file storage -- no new database dependency
    for what is fundamentally metadata about files already on disk.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-16
"""

import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_DIR = Path("data") / "catalog"


@dataclass
class DatasetRecord:
    """One versioned entry in the catalog -- one fetch event for one dataset."""

    dataset_id: str  # f"{symbol}_{timeframe}"
    symbol: str
    timeframe: str
    source: str
    rows: int
    date_range: list = field(default_factory=list)  # [start_iso, end_iso]
    quality_score: Optional[float] = None
    file_path: str = ""
    checksum: str = ""
    fetched_at: str = ""
    version: int = 1


class DatasetCatalog:
    """
    Append-only audit log (`audit_log.jsonl`) + latest-state registry
    (`registry.json`, keyed by dataset_id) for every dataset fetched by any
    engine. `version` increments each time the SAME dataset_id is recorded
    again (e.g. a daily re-fetch of BTC-USD_1d), giving a real, inspectable
    fetch history without needing a database.
    """

    def __init__(self, catalog_dir: Optional[Path] = None) -> None:
        self.catalog_dir = catalog_dir or DEFAULT_CATALOG_DIR
        self.catalog_dir.mkdir(parents=True, exist_ok=True)
        self._audit_log_path = self.catalog_dir / "audit_log.jsonl"
        self._registry_path = self.catalog_dir / "registry.json"
        # Real bug found and fixed 2026-07-20: record() does a read-modify-
        # write on registry.json (load whole file, mutate one key, write
        # the whole file back) -- harmless when MarketDataEngine (which
        # owns ONE shared DatasetCatalog instance) was only ever called
        # sequentially. It stopped being harmless the moment
        # e51_signals.scan_all_assets was parallelized (this same
        # session): concurrent fetches for different assets now call
        # record() from multiple threads on the SAME catalog instance,
        # racing on this file. Confirmed live -- a real
        # "Failed to load dataset registry: Expecting value: line 1
        # column 1 (char 0)" turned up in the server log, exactly what a
        # reader mid-truncate on a non-atomic write_text() produces. A
        # lost update (two threads read the same snapshot, the second
        # writer's version silently overwrites the first's entry) is the
        # quieter failure mode of the same race. This lock serializes the
        # read-modify-write critical section; it does NOT serialize the
        # actual network fetches happening in parallel elsewhere, so it
        # doesn't undo the scan speedup -- registry writes are a tiny
        # fraction of a fetch's total time.
        self._registry_lock = threading.Lock()

    @staticmethod
    def checksum_file(path: Path) -> str:
        """SHA-256 of a file's contents -- for detecting silent corruption
        or an unexpected change between two fetches of the same dataset."""
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def record(
        self,
        symbol: str,
        timeframe: str,
        source: str,
        rows: int,
        date_range: tuple,
        file_path: Path,
        quality_score: Optional[float] = None,
    ) -> DatasetRecord:
        """Append one fetch event to the audit log and update the
        registry's latest-state entry for this dataset."""
        dataset_id = f"{symbol}_{timeframe}"
        checksum = self.checksum_file(file_path) if file_path.exists() else ""

        # Everything from here on touches the shared registry.json (and,
        # for simplicity, the audit log too) -- serialized so concurrent
        # scan_all_assets threads can never race on the read-modify-write
        # below (see __init__'s comment on this lock for the real bug this
        # fixes). The checksum above is deliberately computed BEFORE
        # acquiring the lock -- it's real file I/O with no shared-state
        # dependency, so there's no reason to hold other threads up for it.
        with self._registry_lock:
            registry = self._load_registry()
            prev_version = registry.get(dataset_id, {}).get("version", 0)

            entry = DatasetRecord(
                dataset_id=dataset_id,
                symbol=symbol,
                timeframe=timeframe,
                source=source,
                rows=rows,
                date_range=[str(date_range[0]), str(date_range[1])],
                quality_score=quality_score,
                file_path=str(file_path),
                checksum=checksum,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                version=prev_version + 1,
            )

            with open(self._audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry)) + "\n")

            registry[dataset_id] = asdict(entry)
            self._registry_path.write_text(json.dumps(registry, indent=2))
        return entry

    def _load_registry(self) -> dict[str, dict]:
        if not self._registry_path.exists():
            return {}
        try:
            return json.loads(self._registry_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to load dataset registry: %s", e)
            return {}

    def get_dataset(self, symbol: str, timeframe: str) -> Optional[dict[str, Any]]:
        """Latest catalog entry for one dataset, or None if never recorded."""
        # Same lock as record()'s write -- registry.json's write_text() isn't
        # atomic, so an unguarded read here can race a concurrent record()
        # (e.g. a status/dashboard call during scan_all_assets) and see a
        # truncated file, misreported as "dataset not found".
        with self._registry_lock:
            return self._load_registry().get(f"{symbol}_{timeframe}")

    def list_datasets(self) -> list[dict[str, Any]]:
        """Every dataset's latest catalog entry."""
        with self._registry_lock:
            return list(self._load_registry().values())

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """Most recent `limit` fetch events across all datasets, newest first."""
        if not self._audit_log_path.exists():
            return []
        lines = self._audit_log_path.read_text(encoding="utf-8").splitlines()
        entries = [json.loads(line) for line in lines if line.strip()]
        return list(reversed(entries))[:limit]


_catalog: Optional[DatasetCatalog] = None


def get_catalog() -> DatasetCatalog:
    """Process-wide cached DatasetCatalog singleton."""
    global _catalog
    if _catalog is None:
        _catalog = DatasetCatalog()
    return _catalog

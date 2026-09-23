"""
Module: checkpoint.py
Description: Resumability for the YouTube Knowledge Import Pipeline.
    One checkpoint file per channel (data/YOUTUBE DATA/channels/<slug>/
    checkpoint.json), tracking each video's status through every phase
    independently. Every pipeline stage checks this before doing real
    work and skips anything already marked done -- an interrupted run
    (Ctrl-C, crash, machine sleep) resumes from exactly where it left
    off instead of re-downloading/re-extracting from video #1.

    Written after EVERY video (not batched) so a mid-run interruption
    never loses more than the one video in flight.
Author: Shantanu Waykar
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class VideoCheckpoint:
    transcript_status: str = "pending"  # pending | success | unavailable | failed
    transcript_language: Optional[str] = None
    knowledge_extracted: bool = False
    n_concepts_extracted: int = 0
    integrated: bool = False
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: Optional[str] = None


class Checkpoint:
    """Loads/saves one channel's per-video progress. Safe to construct
    even if the file doesn't exist yet (starts empty)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.videos: dict[str, VideoCheckpoint] = {}
        # transcript_collector.py now runs multiple videos concurrently
        # (ThreadPoolExecutor) -- each worker calls update()/save() for
        # its OWN video_id, but they all share this ONE Checkpoint
        # instance and the same on-disk file. Without a lock, two
        # concurrent save() calls (read self.videos -> serialize -> write
        # tmp -> rename) can interleave and either corrupt the write or
        # silently drop one thread's update. A single lock around the
        # read-modify-write in update() and the write in save() is
        # correct and cheap here -- these are fast dict/JSON operations,
        # not a real contention bottleneck against the multi-second
        # network calls each thread spends most of its time on.
        # RLock (not Lock): update() acquires it, then calls save() which
        # acquires it again on the SAME thread -- a plain Lock would
        # deadlock there.
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.videos = {vid: VideoCheckpoint(**data) for vid, data in raw.get("videos", {}).items()}
        except Exception:
            # Corrupt checkpoint must never crash the pipeline or silently
            # discard real progress -- back it up and start this channel's
            # tracking fresh rather than guessing at partial JSON.
            if self.path.exists():
                backup = self.path.with_suffix(".json.corrupt")
                self.path.rename(backup)
            self.videos = {}

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "videos": {vid: asdict(cp) for vid, cp in self.videos.items()},
            }
            # Write to a temp file then replace -- avoids a truncated/corrupt
            # checkpoint if the process is killed mid-write. A per-thread
            # unique tmp filename avoids two concurrent save() calls
            # colliding on the SAME tmp path (the lock already serializes
            # them, but this is cheap extra safety against any lock-free
            # caller).
            tmp_path = self.path.with_suffix(f".json.tmp.{threading.get_ident()}")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            # This whole project lives inside a OneDrive-synced folder --
            # OneDrive's own sync client transiently locks a file during
            # upload, which can make os.replace() raise PermissionError
            # (WinError 5) for a call that would otherwise succeed a moment
            # later. Verified live 2026-08-09: this crashed a real pipeline
            # run partway through Phase 5 (checkpoint.update() calls
            # save() once PER VIDEO, so a long integration batch has many
            # chances to collide with a sync window). Retry with a short
            # backoff instead of letting one transient lock kill hours of
            # real progress -- same class of fix already used for this
            # project's PornBlock hosts-file lock (a different app, same
            # "another process transiently holds the file" root cause).
            last_error: Optional[OSError] = None
            for attempt in range(5):
                try:
                    tmp_path.replace(self.path)
                    return
                except OSError as e:
                    last_error = e
                    time.sleep(0.5 * (attempt + 1))
            raise last_error

    def get(self, video_id: str) -> VideoCheckpoint:
        with self._lock:
            if video_id not in self.videos:
                self.videos[video_id] = VideoCheckpoint()
            return self.videos[video_id]

    def update(self, video_id: str, **fields) -> None:
        with self._lock:
            cp = self.get(video_id)
            for k, v in fields.items():
                setattr(cp, k, v)
            cp.last_updated = datetime.now(timezone.utc).isoformat()
            self.save()

    def needs_transcript(self, video_id: str) -> bool:
        return self.get(video_id).transcript_status not in ("success", "unavailable")

    def needs_extraction(self, video_id: str) -> bool:
        cp = self.get(video_id)
        return cp.transcript_status == "success" and not cp.knowledge_extracted

    def needs_integration(self, video_id: str) -> bool:
        cp = self.get(video_id)
        return cp.knowledge_extracted and not cp.integrated

    def summary(self) -> dict:
        total = len(self.videos)
        return {
            "total_tracked": total,
            "transcript_success": sum(1 for v in self.videos.values() if v.transcript_status == "success"),
            "transcript_unavailable": sum(1 for v in self.videos.values() if v.transcript_status == "unavailable"),
            "transcript_failed": sum(1 for v in self.videos.values() if v.transcript_status == "failed"),
            "transcript_pending": sum(1 for v in self.videos.values() if v.transcript_status == "pending"),
            "knowledge_extracted": sum(1 for v in self.videos.values() if v.knowledge_extracted),
            "integrated": sum(1 for v in self.videos.values() if v.integrated),
            "total_concepts": sum(v.n_concepts_extracted for v in self.videos.values()),
        }

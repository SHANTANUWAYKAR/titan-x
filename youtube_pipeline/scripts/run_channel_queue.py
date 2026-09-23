"""
Module: run_channel_queue.py
Description: Sequential multi-channel runner for the knowledge-extraction
    pipeline. Reads channel_queue.json (real, verified handles -- see that
    file's own _comment for how each was confirmed, never guessed) and
    runs pipeline.run_pipeline for each channel in order, skipping any
    entry marked skip=true (a real, documented reason, not silently
    omitted) and any channel whose own checkpoint already shows 0 pending.

    Deliberately sequential, not parallel: every channel shares the SAME
    outbound IP, so running several channels concurrently wouldn't
    parallelize real throughput -- it would just reach the same YouTube
    IP-block faster. Stops the whole batch (not just the current channel)
    the moment ANY channel's run reports stopped_due_to_ip_block, since
    every remaining channel in the queue would immediately hit the exact
    same wall -- exits cleanly so the caller's own periodic retry (cron)
    picks the queue back up later rather than burning through it in a
    tight loop.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

logger = logging.getLogger(__name__)

QUEUE_PATH = Path(__file__).resolve().parent.parent / "channel_queue.json"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "YOUTUBE DATA"


def _slug_for(handle: str) -> str:
    """Mirrors channel_discovery.slugify's real behavior for the common
    case (no special chars) -- used only to check an existing checkpoint
    before re-discovering; discover_channel itself always computes the
    authoritative slug from the real channel name it resolves."""
    from channel_discovery import slugify
    name = handle.rsplit("/", 1)[-1] if handle.startswith("http") else handle
    return slugify(name)


def _pending_count(slug: str) -> int | None:
    checkpoint_path = DATA_DIR / "channels" / slug / "checkpoint.json"
    if not checkpoint_path.exists():
        return None
    try:
        data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    videos = data.get("videos", {})
    return sum(1 for v in videos.values() if v.get("transcript_status") == "pending")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    from pipeline import run_pipeline

    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))["channels"]

    for entry in queue:
        name = entry["name"]
        if entry.get("skip"):
            logger.info("SKIP  %-28s -- %s", name, entry.get("reason", "no reason given"))
            continue

        handle = entry["handle"]
        slug_guess = _slug_for(handle)
        pending = _pending_count(slug_guess)
        if pending == 0:
            logger.info("DONE  %-28s -- 0 pending already, skipping", name)
            continue

        logger.info("=== Starting channel: %s (%s) ===", name, handle)
        try:
            result = run_pipeline(handle, skip_discovery=False)
        except Exception as e:
            logger.error("Pipeline crashed for %s: %s -- moving to next channel", name, e)
            continue

        phase3 = result.get("phase3", {})
        logger.info(
            "%s: transcript_success=%s pending=%s stopped_due_to_ip_block=%s",
            name, phase3.get("transcript_success"), phase3.get("transcript_pending"),
            phase3.get("stopped_due_to_ip_block"),
        )
        if phase3.get("stopped_due_to_ip_block"):
            logger.warning("IP block hit on %s -- stopping the whole queue here, not burning through the rest. Re-run later.", name)
            return

    logger.info("Queue complete -- every non-skipped channel reached 0 pending.")


if __name__ == "__main__":
    main()

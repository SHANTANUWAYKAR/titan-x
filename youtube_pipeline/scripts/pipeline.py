"""
Module: pipeline.py
Description: YouTube Knowledge Import Pipeline -- master orchestrator.
    Runs Phases 2-7 for one channel, end to end, resumable at every
    phase via checkpoint.py. Safe to Ctrl-C and re-run: each phase only
    does work for videos that haven't reached that phase yet.

    Usage:
        python pipeline.py <channel_query> [--limit N] [--skip-discovery]

    Phase order matches the master spec: discovery -> transcripts ->
    extraction -> integration -> validation -> report. Each phase runs to
    completion (over every video not yet done) before the next starts --
    NOT interleaved per-video -- so a partial run always leaves the
    channel in a coherent state (e.g. every video that has a transcript
    gets extraction attempted before any of them move on to integration).
Author: Shantanu Waykar
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "YOUTUBE DATA"


def run_pipeline(channel_query: str, limit: int = None, skip_discovery: bool = False, slug: str = None) -> dict:
    from channel_discovery import discover_channel, slugify
    from transcript_collector import collect_all_transcripts
    from knowledge_extractor import extract_all
    from titanx_integrator import integrate_all
    from validator import validate_channel
    from report_generator import generate_report

    t_start = time.time()
    results: dict = {"channel_query": channel_query}

    # Phase 2
    if skip_discovery:
        # slugify(channel_query) is NOT reliable here: the real channel
        # NAME yt-dlp returns (used to build the actual directory in
        # discover_channel) can slugify differently from the QUERY string
        # used to look it up -- confirmed directly ("MindMathMoney" query
        # -> "mindmathmoney", but the real channel name "Mind Math Money"
        # -> "mind_math_money", a different string). An explicit --slug
        # avoids guessing; falling back to slugify(channel_query) only
        # when the caller hasn't already run discovery and doesn't know
        # the real slug yet.
        resolved_slug = slug or slugify(channel_query)
        channel_dir = DATA_DIR / "channels" / resolved_slug
        if not (channel_dir / "channel_metadata.json").exists():
            raise FileNotFoundError(f"--skip-discovery given but no existing metadata at {channel_dir}")
        logger.info("[Phase 2] Skipped (using existing channel_metadata.json)")
    else:
        logger.info("[Phase 2] Discovering channel: %s", channel_query)
        channel = discover_channel(channel_query, DATA_DIR)
        channel_dir = DATA_DIR / "channels" / channel.slug
        results["phase2_videos_discovered"] = len(channel.videos)
        logger.info("[Phase 2] Done: %d videos discovered", len(channel.videos))

    # Phase 3
    logger.info("[Phase 3] Collecting transcripts (limit=%s)...", limit)
    t3 = time.time()
    phase3 = collect_all_transcripts(channel_dir, limit=limit)
    results["phase3"] = phase3
    logger.info("[Phase 3] Done in %.1fs: %s", time.time() - t3, phase3)

    # Phase 4
    logger.info("[Phase 4] Extracting knowledge...")
    t4 = time.time()
    phase4 = extract_all(channel_dir, limit=limit)
    results["phase4"] = phase4
    logger.info("[Phase 4] Done in %.1fs: %s", time.time() - t4, phase4)

    # Phase 5
    logger.info("[Phase 5] Integrating into Titan-X knowledge store...")
    t5 = time.time()
    phase5 = integrate_all(channel_dir, limit=limit)
    results["phase5"] = phase5
    logger.info("[Phase 5] Done in %.1fs: %s", time.time() - t5, phase5)

    # Phase 6
    logger.info("[Phase 6] Validating...")
    t6 = time.time()
    phase6 = validate_channel(channel_dir)
    results["phase6"] = phase6.__dict__
    logger.info("[Phase 6] Done in %.1fs", time.time() - t6)

    # Phase 7
    logger.info("[Phase 7] Generating final report...")
    report = generate_report(channel_dir)
    results["phase7_report"] = report.__dict__

    results["total_elapsed_seconds"] = round(time.time() - t_start, 1)
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser()
    parser.add_argument("channel", nargs="?", default="MindMathMoney")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-discovery", action="store_true")
    parser.add_argument("--slug", default=None, help="Real channel slug (see discovery output) -- required with --skip-discovery if it differs from slugify(channel)")
    args = parser.parse_args()

    result = run_pipeline(args.channel, limit=args.limit, skip_discovery=args.skip_discovery, slug=args.slug)
    print(json.dumps(result, indent=2, default=str))

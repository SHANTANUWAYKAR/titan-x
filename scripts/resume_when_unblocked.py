"""
Module: resume_when_unblocked.py
Description: Waits out a YouTube IP block, then starts the transcript scrape.

    WHY THIS EXISTS. The first tier-1 attempt was IP-blocked around video 20.
    The only legitimate responses to that are to wait longer and to ask for
    less -- never to route around it -- so the waiting has to happen
    somewhere, and a script does it more reliably than remembering to check
    back.

    HOW IT PROBES. One transcript fetch, then a long sleep. That is the
    whole loop. Probing hard would be the same mistake that caused the
    block: a rapid "are you still blocking me?" poll IS more traffic from
    the IP YouTube just told to stop. So the first wait is the longest, the
    gap never drops below an hour, and the probe is a single request against
    a video already on disk (nothing is downloaded to test).

    WHAT IT RUNS. Deliberately slower and shallower than the attempt that
    got blocked: fewer videos per channel and a much wider delay. Breadth
    across channels serves a RAG corpus better than depth on any one
    channel anyway, so the safer setting is also the more useful one.

    NO EVASION, same as the scraper it launches: no proxy, no IP rotation,
    no header games. If the block never clears, this gives up and says so.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("resume")

# A video already on disk -- probing must not download anything new.
PROBE_VIDEO = "GlYgs6v2YfU"


def is_blocked() -> tuple[bool, str]:
    """One request. True if YouTube is still refusing this IP."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import IpBlocked, RequestBlocked
    except ImportError:
        return True, "youtube-transcript-api not installed"
    try:
        api = YouTubeTranscriptApi()
        api.list(PROBE_VIDEO).find_transcript(["en", "en-US", "en-GB"]).fetch()
        return False, "clear"
    except (RequestBlocked, IpBlocked) as e:
        return True, type(e).__name__
    except Exception as e:
        # Anything else is a problem with the probe video, not the IP --
        # treat as clear rather than waiting forever on a bad probe.
        return False, f"probe inconclusive ({type(e).__name__}), assuming clear"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--first-wait-hours", type=float, default=8.0,
                    help="wait before the first probe (default 8)")
    ap.add_argument("--retry-hours", type=float, default=2.0,
                    help="wait between later probes (default 2, floor 1)")
    ap.add_argument("--max-probes", type=int, default=10)
    ap.add_argument("--tier", default="1")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--delay-min", type=float, default=12.0)
    ap.add_argument("--delay-max", type=float, default=25.0)
    ap.add_argument("--channels-file", default="data/YOUTUBE DATA/channels/channels.txt")
    ap.add_argument("--probe-now", action="store_true",
                    help="probe immediately instead of waiting first")
    args = ap.parse_args()

    retry = max(1.0, args.retry_hours)          # never poll a blocked IP hourly-or-faster
    wait = 0.0 if args.probe_now else args.first_wait_hours

    logger.info("Resume watcher started.")
    logger.info("Plan: tier %s, %d videos/channel, %.0f-%.0fs between videos.",
                args.tier, args.limit, args.delay_min, args.delay_max)
    logger.info("No proxies, no IP rotation -- waiting is the only remedy used here.")

    for probe in range(1, args.max_probes + 1):
        if wait:
            resume_at = datetime.now(timezone.utc) + timedelta(hours=wait)
            logger.info("Sleeping %.1fh (probe %d/%d at ~%s UTC)",
                        wait, probe, args.max_probes, resume_at.strftime("%H:%M"))
            time.sleep(wait * 3600)

        blocked, why = is_blocked()
        if blocked:
            logger.warning("Still blocked (%s).", why)
            wait = retry
            continue

        logger.info("Block cleared (%s). Starting the scrape.", why)
        cmd = [sys.executable, "-u", str(ROOT / "scripts" / "youtube_scraper.py"),
               "--channels-file", args.channels_file,
               "--tier", args.tier, "--limit", str(args.limit),
               "--filter-mode", "all",
               "--delay-min", str(args.delay_min), "--delay-max", str(args.delay_max)]
        logger.info("  %s", " ".join(cmd[2:]))
        raise SystemExit(subprocess.call(cmd, cwd=str(ROOT)))

    logger.error("Still blocked after %d probes over ~%.0f hours. Giving up rather than "
                 "pushing harder -- resume manually once YouTube has cooled off.",
                 args.max_probes, args.first_wait_hours + retry * (args.max_probes - 1))
    raise SystemExit(1)


if __name__ == "__main__":
    main()

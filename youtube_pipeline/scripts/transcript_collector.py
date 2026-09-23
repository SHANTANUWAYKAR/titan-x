"""
Module: transcript_collector.py
Description: YouTube Knowledge Import Pipeline -- Phase 3, Transcript
    Collection. For every video in a channel's metadata, downloads the
    transcript via youtube-transcript-api (captions YouTube already
    has -- auto-generated or uploaded, never re-transcribes audio, which
    would need a separate ASR model this pipeline doesn't run). Missing
    transcripts are recorded and reported, never treated as a pipeline
    failure -- a video with captions disabled is a normal, expected
    outcome, not an error condition to abort on (per the master spec's
    own "report it without failing the pipeline").

    Resumable via checkpoint.py: skips any video whose checkpoint already
    shows transcript_status in (success, unavailable). Never overwrites
    an existing raw/clean transcript file for a video already marked
    success unless force=True is passed.
Author: Shantanu Waykar
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from channel_discovery import enrich_video_metadata
from checkpoint import Checkpoint

logger = logging.getLogger(__name__)

# Same .env convention core.config.settings already uses (project root,
# not this pipeline's own directory) -- one shared secrets file for the
# whole project rather than a second one just for this pipeline.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


# PROXY SUPPORT REMOVED 2026-08-27, and it must not be reintroduced.
#
# This module previously routed requests through Webshare ROTATING
# RESIDENTIAL proxies whenever WEBSHARE_PROXY_USERNAME/PASSWORD were set,
# added in response to a real IpBlocked error. The justification recorded
# at the time was that a 63-minute wait had not cleared the block, so it
# was "a genuine IP-level ban, not a short-lived rate limit".
#
# That reasoning is exactly backwards. A block that survives an hour is
# YouTube stating the request rate was too high -- the answer is to
# request LESS, not to arrive from a different IP. Cycling residential
# proxies to defeat an IP block is circumventing a technical access
# restriction, and it is against YouTube's terms regardless of the
# library documenting it as a "workaround".
#
# When blocked, the supported responses are: wait longer, lower the rate,
# or stop and resume later. If evasion is the only remaining option, this
# pipeline stops and says so. scripts/youtube_scraper.py exists as the
# sequential, rate-limited collector built on that principle.

# Polite pacing PER WORKER between transcript fetches -- youtube-transcript-api
# hits YouTube's own timedtext endpoint directly; a tight loop over hundreds
# of videos risks a temporary IP-level rate limit (observed behavior across
# the ecosystem of tools using this same endpoint, not specific to this
# library). This is a conservative default, not a documented YouTube rate
# limit -- deliberately cautious rather than asserting a number unverified.
MIN_SECONDS_BETWEEN_REQUESTS = 1.5

# Collection is SEQUENTIAL as of 2026-08-27. A 5-worker pool lived here,
# justified on throughput (~5.7s/video sequential, so 533 videos took ~50
# minutes) and paced 1.5s per worker on the reasoning that this was "not
# simultaneous hammering". It works out at roughly 3.3 requests/second to
# YouTube's timedtext endpoint from a single IP, and this pipeline was
# IP-blocked on a real run -- the speed was bought with precisely the
# burst rate that causes the block. Kept sequential deliberately: a run
# that finishes fast and gets the IP banned collects less than a slower
# one that completes, and checkpointing already makes long runs resumable.


@dataclass
class TranscriptSegment:
    text: str
    start: float
    duration: float


def _clean_text(segments: list[TranscriptSegment]) -> str:
    """Plain, readable text -- concatenated segment text, normalized
    whitespace, no timestamps. Kept separate from the raw (timestamped)
    version per the spec's explicit 'raw transcript' + 'clean transcript'
    requirement -- clean is what knowledge extraction reads, raw is what
    timestamp references (Phase 5's 'preserve timestamp references') are
    built from."""
    joined = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
    return re.sub(r"\s+", " ", joined).strip()


def collect_transcript(video_id: str) -> tuple[Optional[list[TranscriptSegment]], Optional[str], Optional[str]]:
    """Returns (segments, language_code, error). error is None on success;
    a non-None error with segments=None means "no transcript available or
    fetch failed" -- caller decides unavailable/failed/blocked based on
    the error's own PREFIX (see below), not by re-parsing free-text
    messages.

    Classification verified against the REAL exception hierarchy
    (youtube_transcript_api._errors), not guessed -- listed every
    CouldNotRetrieveTranscript subclass directly and confirmed live that
    a members-only video raises VideoUnplayable, NOT RequestBlocked (an
    earlier version of this function treated ALL non-network failures as
    a single "blocked" bucket after seeing ONE video raise IpBlocked --
    wrong; a second, different members-only video raised VideoUnplayable
    instead, a genuinely different, permanent condition):

      unavailable (permanent fact about THIS video, never retry):
        TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
        VideoUnplayable, AgeRestricted
      blocked (about THIS MACHINE's access, not the video -- retry later):
        RequestBlocked (covers its IpBlocked subclass too), PoTokenRequired
      failed (unexpected -- worth investigating, not silently assumed
        benign): everything else (InvalidVideoId, YouTubeRequestFailed,
        YouTubeDataUnparsable, FailedToCreateConsentCookie, ...)
    """
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        AgeRestricted,
        NoTranscriptFound,
        PoTokenRequired,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
        VideoUnplayable,
    )

    try:
        api = YouTubeTranscriptApi()          # direct only -- see the note above
        transcript_list = api.list(video_id)
        # Prefer a real (manually created or auto-generated) English
        # transcript; fall back to whatever the first available language
        # is rather than failing outright -- the corpus is still useful
        # in another language for a viewer who wants it, and Phase 4 can
        # honestly record the language rather than silently skip.
        try:
            transcript = transcript_list.find_transcript(["en", "en-US", "en-GB"])
        except Exception:
            transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
        segments = [TranscriptSegment(text=s.text, start=s.start, duration=s.duration) for s in fetched]
        return segments, transcript.language_code, None
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnplayable, AgeRestricted) as e:
        return None, None, f"unavailable: {e}"
    except VideoUnavailable as e:
        return None, None, f"unavailable: video unavailable ({e})"
    except (RequestBlocked, PoTokenRequired) as e:
        # About THIS MACHINE's access (an anti-bot block or missing proof-
        # of-origin token), not a fact about the video -- says nothing
        # about whether the video itself has a transcript. Distinct,
        # explicitly retryable status (see checkpoint.needs_transcript and
        # the circuit breaker in collect_all_transcripts) -- never
        # conflated with "unavailable" (a real, permanent fact about the
        # video) or "failed" (an unexpected error worth investigating).
        return None, None, f"blocked: {e}"
    except Exception as e:
        return None, None, f"failed: {e}"


def _collect_one(video: dict, videos_dir: Path, checkpoint: Checkpoint, force: bool, stop_event: threading.Event) -> None:
    """One video's full transcript-collection unit of work -- pulled out
    of collect_all_transcripts so it can run inside a thread pool. Only
    touches this video's OWN directory/checkpoint entry; the checkpoint
    itself is the one shared object, and it's lock-protected (see
    checkpoint.py) for exactly this reason.

    stop_event: circuit breaker, shared across every worker in the pool.
    All futures are submitted to the executor upfront (see
    collect_all_transcripts), so this is the only point where an
    loop can bail out once a block is detected -- checked first thing,
    before making any network call at all, so a block stops the run
    immediately rather than burning the rest of the queue against it."""
    if stop_event.is_set():
        return

    vid = video["video_id"]
    video_dir = videos_dir / vid
    video_dir.mkdir(parents=True, exist_ok=True)
    video_meta_path = video_dir / "metadata.json"
    if not video_meta_path.exists() or force:
        # Real publish_date/description/view_count -- flat channel
        # discovery genuinely can't carry these (see
        # channel_discovery.py's own docstring on this), so this is the
        # one full per-video fetch that backfills them. Reuses this
        # loop's existing per-video pass rather than a second full sweep
        # over the channel just for metadata. Best-effort: this hits a
        # SEPARATE endpoint (yt-dlp's own video-info fetch, not
        # youtube-transcript-api) that can fail independently of the
        # transcript call below -- must not lose the transcript attempt
        # over an enrichment-only failure.
        try:
            enriched = enrich_video_metadata(vid)
            merged = {**video, **{k: v for k, v in enriched.items() if v}}
        except Exception as e:
            logger.warning("Metadata enrichment failed for %s (using flat-discovery metadata only): %s", vid, e)
            merged = video
        video_meta_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    segments, language, error = collect_transcript(vid)

    if segments is not None:
        raw_path = video_dir / "transcript_raw.json"
        clean_path = video_dir / "transcript_clean.txt"
        if not raw_path.exists() or force:
            raw_path.write_text(
                json.dumps({"language": language, "segments": [asdict(s) for s in segments]}, indent=2),
                encoding="utf-8",
            )
        clean_text = _clean_text(segments)
        if not clean_path.exists() or force:
            clean_path.write_text(clean_text, encoding="utf-8")
        checkpoint.update(vid, transcript_status="success", transcript_language=language, error=None)
        logger.info("OK    %s  %-60s (%d segments, lang=%s)", vid, video["title"][:60], len(segments), language)
    elif error and error.startswith("unavailable"):
        checkpoint.update(vid, transcript_status="unavailable", error=error)
        logger.info("SKIP  %s  %-60s (%s)", vid, video["title"][:60], error)
    elif error and error.startswith("blocked"):
        # Leave transcript_status as "pending" (NOT "failed"/"blocked" as
        # a terminal state) -- this video hasn't actually been evaluated
        # yet, so needs_transcript() must keep offering it for a future
        # retry once the block clears, same as if it had never been
        # attempted at all.
        checkpoint.update(vid, transcript_status="pending", error=error)
        logger.error("BLOCKED %s  %-60s (%s)", vid, video["title"][:60], error)
        stop_event.set()
    else:
        checkpoint.update(vid, transcript_status="failed", error=error)
        logger.warning("FAIL  %s  %-60s (%s)", vid, video["title"][:60], error)

    # Pacing between sequential requests. Now that the worker pool is
    # gone this IS the whole request rate, rather than one of five
    # concurrent streams -- so it is both simpler and far gentler.
    time.sleep(MIN_SECONDS_BETWEEN_REQUESTS)


def collect_all_transcripts(channel_dir: Path, force: bool = False, limit: Optional[int] = None) -> dict:
    """Iterates channel_metadata.json's video list, fetching each
    transcript and writing raw/clean/metadata files under
    videos/<video_id>/. Resumable via the channel's checkpoint.json.
    Returns a summary dict (also what Phase 7's final report reads).

    Runs SEQUENTIALLY. A 5-worker pool was used here until 2026-08-27
    and was removed after this pipeline was IP-blocked on a real run:
    five workers pacing 1.5s each is ~3.3 requests/second from one IP,
    which is the burst rate that triggers the block. Measured live at
    ~5.7s/video sequential (17 videos in 97s), which
    would put 533 videos at ~50 minutes for this phase alone."""
    metadata_path = channel_dir / "channel_metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"No channel_metadata.json in {channel_dir} -- run channel discovery first")
    channel = json.loads(metadata_path.read_text(encoding="utf-8"))

    checkpoint = Checkpoint(channel_dir / "checkpoint.json")
    videos_dir = channel_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    videos = channel["videos"]
    if limit is not None:
        videos = videos[:limit]

    to_process = [v for v in videos if force or checkpoint.needs_transcript(v["video_id"])]
    processed_this_run = 0
    stop_event = threading.Event()

    # SEQUENTIAL 2026-08-27, replacing a 5-worker ThreadPoolExecutor.
    #
    # The parallel version was justified on throughput -- ~5.7s/video
    # measured sequentially, so 533 videos took ~50 minutes -- and paced
    # each worker 1.5s apart, reasoning that 5 workers at 1.5s was "not
    # simultaneous hammering". In practice it is ~3.3 requests/second
    # against YouTube's timedtext endpoint from one IP, and this pipeline
    # did get IP-blocked on a real run. Speed was bought with exactly the
    # burst rate that causes the block.
    #
    # Running sequentially is slower and that is the point: a run that
    # finishes in 50 minutes and gets the IP banned collects less than one
    # that takes two hours and completes. Checkpointing already makes a
    # long run resumable, so wall-clock time was never the real constraint.
    for video in to_process:
        if stop_event.is_set():
            break
        try:
            _collect_one(video, videos_dir, checkpoint, force, stop_event)
            processed_this_run += 1
        except Exception as e:
            # An unexpected crash (not the ordinary
            # unavailable/failed outcomes collect_transcript already
            # returns normally) must not end the batch or lose the
            # checkpoint record of every other video that succeeded.
            logger.error("Unexpected error processing %s: %s", video["video_id"], e)
            checkpoint.update(video["video_id"], transcript_status="failed", error=f"worker error: {e}")

    if stop_event.is_set():
        logger.error(
            "Stopped early: YouTube blocked this machine's requests mid-run. "
            "Unattempted/left-pending videos remain 'pending' and will be retried "
            "automatically on the next run (once the block clears -- typically minutes "
            "to a few hours; not something to retry immediately in a tight loop)."
        )

    summary = checkpoint.summary()
    summary["processed_this_run"] = processed_this_run
    summary["stopped_due_to_ip_block"] = stop_event.is_set()
    return summary


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    slug = sys.argv[1] if len(sys.argv) > 1 else "mind_math_money"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    channel_dir = Path(__file__).resolve().parents[2] / "data" / "YOUTUBE DATA" / "channels" / slug
    result = collect_all_transcripts(channel_dir, limit=limit)
    print(json.dumps(result, indent=2))

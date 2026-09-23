"""
Module: channel_discovery.py
Description: YouTube Knowledge Import Pipeline -- Phase 2, Channel
    Discovery. Uses yt-dlp's flat playlist extraction (no YouTube Data API
    key required -- none is configured in this project's .env, and
    requesting one requires the user to set up a Google Cloud project,
    which is their call, not something to silently work around). yt-dlp
    reads the same public channel/videos listing a browser would, no
    quota, no key.

    If GOOGLE_API_KEY / YOUTUBE_API_KEY is ever set in .env, this module
    could be extended to use google-api-python-client instead for richer
    metadata (exact view counts, category IDs) -- not required for the
    fields this pipeline actually needs (title, description, publish
    date, duration, URL), which yt-dlp already provides.
Author: Shantanu Waykar
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    video_id: str
    title: str
    description: str
    publish_date: Optional[str]  # ISO date, None if yt-dlp couldn't determine it
    duration_seconds: Optional[int]
    url: str
    channel_id: str
    channel_name: str
    is_short: bool = False
    is_live: bool = False
    view_count: Optional[int] = None
    # Best-effort heuristic per the "Approved YouTube Knowledge Sources"
    # policy's exclusion list (Shorts, promotional/announcement videos,
    # giveaways, live streams that aren't themselves educational). A
    # TITLE-pattern heuristic is necessarily imprecise -- this flags
    # likely-non-educational content so Phase 3 can skip it by default,
    # but never deletes the record itself (the full metadata is kept for
    # every discovered video, honest and complete; only what gets
    # TRANSCRIBED is filtered).
    likely_educational: bool = True
    exclusion_reason: Optional[str] = None


@dataclass
class ChannelMetadata:
    channel_id: str
    channel_name: str
    channel_url: str
    slug: str  # filesystem-safe identifier, e.g. "mind_math_money"
    playlist_ids: list[str] = field(default_factory=list)
    videos: list[VideoMetadata] = field(default_factory=list)
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def slugify(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")


# Title substrings that, per the "Approved YouTube Knowledge Sources"
# policy, mark a video as non-educational (promotional announcements,
# giveaways, pure clickbait) rather than the market-structure/psychology/
# risk-management content this pipeline is meant to extract. Deliberately
# narrow and title-only (not attempting sentiment/topic classification on
# a title alone, which would be unreliable) -- errs toward INCLUDING a
# borderline video rather than silently dropping real educational content.
#
# "free course"/"channel members" as standalone patterns were tried and
# REMOVED after a direct check against real data: they wrongly flagged
# real, substantial educational content -- "MASTER Day Trading in 98
# Minutes (FREE COURSE)" and "MASTER Liquidity Concepts Trading in 55
# Minutes (Free Course)" are genuine long-form courses, not promotional
# fluff, and got caught by "free course" alone. "out now:" is kept
# because it's a precise announcement-style prefix this channel actually
# uses specifically for "I just shipped a new paid resource" posts, not
# for educational video titles.
_EXCLUSION_PATTERNS = [
    ("out now:", "promotional/product announcement"),
    ("giveaway", "giveaway"),
    ("live now", "live stream announcement"),
    ("q&a live", "live stream"),
]


def classify_educational(title: str, is_short: bool, is_live: bool, duration_seconds: Optional[int]) -> tuple[bool, Optional[str]]:
    if is_short or (duration_seconds is not None and duration_seconds <= 60):
        return False, "short-form video (<=60s)"
    if is_live:
        return False, "live stream"
    lowered = title.lower()
    for pattern, reason in _EXCLUSION_PATTERNS:
        if pattern in lowered:
            return False, reason
    return True, None


def discover_channel(channel_query: str, data_dir: Path) -> ChannelMetadata:
    """Resolve a channel by name/URL and enumerate every real video on it
    (flat extraction -- IDs/titles/durations without downloading each
    video's full page, fast even for a channel with hundreds of videos).
    Writes channel_metadata.json under data_dir/channels/<slug>/ and
    returns the parsed result. Idempotent: safe to re-run, always
    overwrites with the current live channel state (metadata, unlike
    transcripts, has no "don't overwrite" requirement -- titles/counts
    can legitimately change)."""
    import yt_dlp

    search_url = channel_query if channel_query.startswith("http") else f"https://www.youtube.com/@{channel_query}"

    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_url, download=False)

    if info is None:
        raise RuntimeError(f"Could not resolve channel: {channel_query}")

    channel_id = info.get("channel_id") or info.get("id") or channel_query
    channel_name = info.get("channel") or info.get("uploader") or channel_query
    channel_url = info.get("channel_url") or search_url
    slug = slugify(channel_name)

    videos: list[VideoMetadata] = []
    entries = info.get("entries") or []
    for entry in entries:
        if entry is None:
            continue
        # A channel's "Videos" tab flat-extracts one level; a "Shorts" tab
        # or nested playlist entry would show up as its own dict with an
        # "entries" key instead of a real video id -- skip those rather
        # than mis-recording a playlist as a video.
        if entry.get("_type") == "playlist" or entry.get("entries") is not None:
            continue
        vid = entry.get("id")
        if not vid:
            continue
        duration = entry.get("duration")
        is_short = bool(duration is not None and duration <= 60)
        is_live = entry.get("live_status") in ("is_live", "is_upcoming")
        title = entry.get("title") or ""
        educational, exclusion_reason = classify_educational(title, is_short, is_live, duration)
        videos.append(VideoMetadata(
            video_id=vid,
            title=title,
            # Flat extraction genuinely has no "description" field (verified
            # directly against a real entry -- confirmed absent, not just
            # empty). Backfilled during transcript_collector.py's per-video
            # pass instead, which already does one network round-trip per
            # video -- fetching full metadata there avoids a SECOND full
            # per-video pass just for descriptions.
            description=entry.get("description") or "",
            # Flat entries carry `timestamp` (Unix epoch), not `upload_date`
            # -- confirmed directly against a real entry (upload_date is
            # simply absent in flat mode, which silently produced None for
            # every video before this fix).
            publish_date=_normalize_timestamp(entry.get("timestamp")),
            duration_seconds=int(duration) if duration is not None else None,
            url=entry.get("url") or f"https://www.youtube.com/watch?v={vid}",
            channel_id=channel_id,
            channel_name=channel_name,
            is_short=is_short,
            is_live=is_live,
            view_count=entry.get("view_count"),
            likely_educational=educational,
            exclusion_reason=exclusion_reason,
        ))

    channel = ChannelMetadata(
        channel_id=channel_id, channel_name=channel_name, channel_url=channel_url,
        slug=slug, playlist_ids=[], videos=videos,
    )

    out_dir = data_dir / "channels" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "channel_metadata.json").write_text(
        json.dumps(asdict(channel), indent=2), encoding="utf-8"
    )
    logger.info("Discovered %s: %d videos -> %s", channel_name, len(videos), out_dir / "channel_metadata.json")
    return channel


def _normalize_timestamp(timestamp: Optional[float]) -> Optional[str]:
    """yt-dlp flat-extraction entries carry a `timestamp` key (Unix epoch
    seconds), but it's genuinely unpopulated (None) for a channel's videos
    listing -- confirmed directly against real entries, not a parsing bug.
    Getting a real publish_date requires a full per-video fetch, which
    this function doesn't do (flat extraction is what makes discovering
    hundreds of videos fast); see enrich_video_metadata below, called
    during transcript collection's own per-video pass instead of a
    second full sweep just for dates."""
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).date().isoformat()
    except (ValueError, OSError):
        return None


def enrich_video_metadata(video_id: str) -> dict:
    """Full (non-flat) single-video metadata fetch -- real publish_date,
    description, and view_count that flat channel-level extraction
    doesn't carry. One extra network round-trip per video; called from
    transcript_collector's own per-video loop (which already does one
    round-trip per video for the transcript) rather than a second full
    pass over the whole channel just for this."""
    import yt_dlp

    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True, "ignoreerrors": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    if info is None:
        return {}
    return {
        "description": info.get("description") or "",
        "publish_date": _normalize_timestamp(info.get("timestamp")) or _upload_date_to_iso(info.get("upload_date")),
        "view_count": info.get("view_count"),
        "duration_seconds": info.get("duration"),
    }


def _upload_date_to_iso(upload_date: Optional[str]) -> Optional[str]:
    """Non-flat single-video extraction DOES carry upload_date (YYYYMMDD)
    -- real fallback when timestamp itself isn't set."""
    if not upload_date or len(upload_date) != 8:
        return None
    return f"{upload_date[0:4]}-{upload_date[4:6]}-{upload_date[6:8]}"


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    query = sys.argv[1] if len(sys.argv) > 1 else "MindMathMoney"
    data_dir = Path(__file__).resolve().parents[2] / "data" / "YOUTUBE DATA"
    result = discover_channel(query, data_dir)
    print(f"{result.channel_name} ({result.channel_id}): {len(result.videos)} videos")

"""
Module: youtube_scraper.py
Description: YouTube transcript collector for a local RAG knowledge base.

    Collects captions YouTube already has (manual or auto-generated) --
    it never re-transcribes audio, which would need an ASR model this
    script does not run.

    NOT a replacement for youtube_pipeline/scripts/transcript_collector.py.
    That one has no corpus/tier separation, no timestamp preservation and
    no quality gate. This is a separate, RAG-oriented collector; the two
    do not share state. (It previously also ran a ThreadPoolExecutor and
    routed around blocks with rotating proxies -- both were removed on
    2026-08-28 for the same reason they are refused here, so it is no
    longer a counter-example, just a different tool.)

    ON BLOCK EVASION -- a hard rule, stated where it will be read before
    anyone "fixes" a block: this script contains NO proxy support, no IP
    rotation, no User-Agent spoofing and no fake headers, and none may be
    added. Rotating proxies to slip past a rate limit is circumventing a
    technical restriction, not tuning a parameter. When YouTube pushes
    back, the correct responses are: wait longer, request less, or stop
    and resume later. If the only remaining way forward is evasion, this
    script STOPS and says so.

Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import json
import os
import logging
import random
import re
from urllib.parse import urlparse
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        AgeRestricted, InvalidVideoId, IpBlocked, NoTranscriptFound,
        NotTranslatable, PoTokenRequired, RequestBlocked,
        TranslationLanguageNotAvailable, TranscriptsDisabled,
        VideoUnavailable, VideoUnplayable,
    )
except ImportError:
    sys.exit("Missing dependency. Install with:  pip install youtube-transcript-api")

try:
    import yt_dlp
except ImportError:
    sys.exit("Missing dependency. Install with:  pip install yt-dlp")


ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS = ROOT / "transcripts"
STATE = ROOT / "state"
CONFIG = ROOT / "config"
FAILED_LOG = ROOT / "failed_videos.txt"
UNRESOLVED_LOG = ROOT / "logs" / "unresolved_channels.txt"
PROGRESS_LOG = ROOT / "logs" / "scrape_progress.log"

# --- rate limiting. Deliberately conservative; see the module docstring. ---
DELAY_MIN, DELAY_MAX = 3.0, 6.0        # randomised, never a fixed interval
LONG_PAUSE_EVERY = 50
LONG_PAUSE_MIN, LONG_PAUSE_MAX = 60, 90
BACKOFF_SCHEDULE = (60, 180, 600)      # 3 attempts, then give up and log
CHANNEL_PAUSE_MIN, CHANNEL_PAUSE_MAX = 120, 180

# --- quality gate ---
MIN_WORDS = 300
MAX_FILLER_RATIO = 0.40
LARGE_CHANNEL_MB = 500

logger = logging.getLogger("yt_scraper")

# Failures that will NEVER succeed however long we wait: the captions are
# off, the video is gone, or it needs a token this script does not mint.
# Retrying these costs 60+180+600s of sleeping for a guaranteed failure --
# on a 2,200-video run that is hours spent proving nothing.
PERMANENT_ERRORS = (
    TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, VideoUnplayable,
    AgeRestricted, InvalidVideoId, NotTranslatable,
    TranslationLanguageNotAvailable, PoTokenRequired,
)

# YouTube telling us to back off. Not an error to retry past -- it is the
# signal the run must slow down or stop. See _handle_block().
BLOCK_ERRORS = (RequestBlocked, IpBlocked)

_INTERRUPTED = False
_BLOCKED = False


def _handle_sigint(signum, frame):
    """Ctrl+C sets a flag rather than killing mid-write.

    Every transcript is already flushed to disk the moment it is fetched,
    so nothing in memory is ever at risk -- this only prevents a partial
    file if the interrupt lands during a write."""
    global _INTERRUPTED
    _INTERRUPTED = True
    logger.warning("\nInterrupt received -- finishing the current video, then stopping cleanly.")


# ---------------------------------------------------------------------------
# Title filtering
# ---------------------------------------------------------------------------
SKIP_PATTERNS = [
    r"\bdaily\b", r"\bweekly recap\b", r"\blive ?stream\b", r"\bmarket update\b",
    r"\bmorning call\b", r"\btrades of the week\b", r"\bvlog\b", r"\bpodcast ep",
    r"\bq ?& ?a\b", r"\bgiveaway\b", r"\bnews\b", r"\brecap\b",
    # a bare date: "Sept 12", "12/09/25", "2025-09-12"
    # Full month names FIRST so the alternation cannot stop at a 3-letter
    # prefix. The previous form ended in [a-z]*, which let a month
    # abbreviation swallow any word starting with those letters: "Maybe 3
    # Reasons Your Backtest Lies" and "Decide 5 Things Before You Enter A
    # Trade" both matched and were skipped as dated content. No title in
    # the 1,953-title tier-1 sample changes verdict from this fix -- the
    # five it stops matching all carry a numeric date caught below -- so
    # this is correctness insurance, not yield.
    r"\b(january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?\s+\d{1,2}\b",
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
]
KEEP_PATTERNS = [
    r"\bhow to\b", r"\bexplained\b", r"\btutorial\b", r"\bguide\b", r"\bbasics\b",
    r"\bmasterclass\b", r"\bstrategy\b", r"\bconcept", r"\bpart ?\d\b", r"\bseries\b",
    r"\bbeginners?\b", r"\blecture\b", r"\bcourse\b", r"\bintroduction\b", r"\bfundamentals\b",
    # named techniques
    r"\bfvg\b", r"\bfair value gap\b", r"\border ?block\b", r"\bliquidity\b",
    r"\bkill ?zone\b", r"\brisk management\b", r"\bposition sizing\b", r"\bbacktest",
    r"\bmarket structure\b", r"\bchoch\b", r"\bbos\b", r"\bsupply and demand\b",
    r"\bindicator\b", r"\bpsychology\b", r"\bvaluation\b", r"\bportfolio\b",
    # Added after auditing 1,953 real tier-1 titles: each was sitting in
    # the "no-keep-match" bucket on titles with obvious educational intent.
    # Measured individually against that sample -- lessons +10, what-is +9,
    # mistakes +9, candlestick +7, framework +5, order-book +1, sharpe +1.
    # Deliberately NOT added: bare "why", "data", "risk", "options",
    # "python" -- they appear in 81/35/25/51/43 rejected titles each and
    # would turn concepts mode into all mode.
    r"\bwhat is\b", r"\bmistakes?\b", r"\blessons?\b", r"\bframework\b",
    r"\bcandlestick", r"\border ?book\b", r"\bsharpe\b",
    # For interview channels kept on the whitelist: admits the strong
    # episodes by title rather than opening the whole channel. +4 each,
    # overlapping on one title.
    r"\bmarket wizards?\b", r"\brules?\b",
]


def should_keep_title(title: str, mode: str = "whitelist") -> tuple[bool, str]:
    """Concepts-mode title filter. Returns (keep, reason).

    SKIP always wins, in both modes: a video called "Daily Market Update -
    Order Blocks Explained" is still a dated daily video, and dated content
    is what pollutes a concept corpus.

    MODE decides what happens to a title no skip rule caught.

      whitelist (default) -- keep only on a KEEP_PATTERNS match. Correct
        for channels that mix teaching with commentary, where the title is
        the only signal separating the two.

      blacklist -- keep everything that survived the skip rules. This is
        CHANNEL-LEVEL TRUST, not filtering: measured on 1,953 real tier-1
        titles, the skip rules catch only 10.8%, so blacklist mode admits
        roughly 99% of a channel. Grant it only where the rejected titles
        were checked and found genuinely evergreen. It is the wrong mode
        for any channel publishing UNDATED topical commentary -- daily
        crypto or macro takes carry no date in the title, so no skip rule
        sees them and blacklist swallows the lot.
    """
    low = title.lower()
    for pat in SKIP_PATTERNS:
        if re.search(pat, low):
            return False, f"skip:{pat}"
    for pat in KEEP_PATTERNS:
        if re.search(pat, low):
            return True, f"keep:{pat}"
    if mode == "blacklist":
        return True, "blacklist:no-skip-match"
    return False, "no-keep-match"


# ---------------------------------------------------------------------------
# channels.txt parsing
# ---------------------------------------------------------------------------
@dataclass
class ChannelEntry:
    url: str
    corpus: str
    tier: str
    mode: str = "whitelist"        # see should_keep_title for what this buys

    @property
    def handle(self) -> str:
        """Filesystem-safe channel name from the URL/@handle."""
        raw = self.url.rstrip("/").split("/")[-1]
        return re.sub(r"[^A-Za-z0-9_.-]", "_", raw.lstrip("@")) or "unknown"


_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com",
             "music.youtube.com", "youtu.be", "www.youtu.be"}


def _apply_delays(dmin: float, dmax: float) -> None:
    """Raise the inter-video delay. Only ever SLOWER, never faster.

    Accepting a smaller value would turn the one real defence against a
    block into a footgun -- and the reason these flags exist at all is that
    the defaults were already too fast for this IP, which YouTube blocked
    around video 20 of the first tier-1 attempt.
    """
    global DELAY_MIN, DELAY_MAX
    if dmin < DELAY_MIN or dmax < DELAY_MAX:
        logger.warning("Ignoring a request to speed up: delays may only be raised "
                       "(floor stays %.1f-%.1fs).", DELAY_MIN, DELAY_MAX)
    DELAY_MIN = max(DELAY_MIN, dmin)
    DELAY_MAX = max(DELAY_MAX, dmax, DELAY_MIN + 0.5)


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON so the file is either complete or absent, never partial.

    Serialise FIRST (so a serialisation error never touches the target),
    write to a temp file beside it, flush and fsync so the bytes are really
    on the platter, then os.replace -- atomic on Windows and POSIX. Without
    this, a kill during write leaves a truncated file that the resume check
    would happily accept as a finished download.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _looks_like_channel(s: str) -> bool:
    """True only for a YouTube channel reference.

    Accepts a bare @handle or a URL whose HOST is YouTube. The host is
    parsed rather than string-matched: searching for "youtube.com" anywhere
    in the line would accept "https://evil.com/youtube.com/@x", and my
    first attempt at anchoring that search instead rejected every real URL,
    because in "https://youtube.com/..." the domain follows "//" rather
    than a dot. urlparse settles it without either failure mode.

    Deliberately strict: wrongly rejecting a line costs a visible warning
    the user can act on, while wrongly accepting one costs a silent
    nine-minute detour scraping an English sentence (see
    parse_channels_file).
    """
    s = s.strip()
    if s.startswith("@"):
        return bool(re.fullmatch(r"@[A-Za-z0-9_.-]+", s))
    if not re.match(r"https?://", s, re.I):
        return False
    host = (urlparse(s).hostname or "").lower()
    return host in _YT_HOSTS


def _valid_mode(value: str, lineno: int) -> str:
    """Reject an unknown mode loudly instead of guessing.

    A typo like "blacklsit" silently falling back to whitelist would look
    exactly like a channel that simply matched few keep patterns -- a
    filtering decision made by a spelling mistake, invisible in the output.
    """
    v = value.strip().lower()
    if v in ("whitelist", "blacklist"):
        return v
    logger.warning("channels.txt line %d: unknown mode %r -- using whitelist. "
                   "Valid values are 'whitelist' and 'blacklist'.", lineno, value)
    return "whitelist"


def parse_channels_file(path: Path) -> list[ChannelEntry]:
    """Parse channels.txt.

    Comments are ignored EXCEPT '# CORPUS:' and '# TIER:', which are
    section markers: every channel inherits the corpus and tier of the
    section it sits under. That inheritance is why corpus never has to be
    repeated per line.

    A non-comment line must LOOK like a channel (a youtube.com/youtu.be URL
    or a bare @handle) to be accepted. Anything else is reported as
    malformed and skipped, never attempted.

    Found on a real file: the channel list ends with a three-line prose note
    ("Note: some @handles above may be slightly off..."). Those lines carry
    no leading '#', so accepting every non-comment line turned them into
    three phantom channels. Each would have cost a yt-dlp resolution attempt
    plus the 2-3 minute inter-channel pause -- about nine minutes of a run
    spent failing to download a sentence -- and then landed in
    unresolved_channels.txt, where the file is supposed to list handles
    worth fixing by hand. Silently scraping prose is worse than refusing it,
    so malformed lines are surfaced with their line number instead.

    Encoding note: splitlines() plus strip() handles CRLF, which this file
    uses; utf-8-sig is used so a BOM from a Windows editor cannot glue
    itself to the first '# TIER:' marker and lose that whole section.
    """
    entries: list[ChannelEntry] = []
    malformed: list[tuple[int, str]] = []
    corpus, tier, mode = "uncategorised", "all", "whitelist"
    for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            m = re.match(r"#\s*CORPUS:\s*(\S+)", s, re.I)
            if m:
                corpus = m.group(1).lower()
                continue
            m = re.match(r"#\s*TIER:\s*(\S+)", s, re.I)
            if m:
                tier = m.group(1).lower()
                continue
            m = re.match(r"#\s*MODE:\s*(\S+)", s, re.I)
            if m:
                mode = _valid_mode(m.group(1), lineno)
            continue

        # A trailing "# mode: blacklist" overrides the section default. The
        # channels earning blacklist are scattered across topic sections, so
        # a section marker alone cannot express the real assignment.
        line_mode = mode
        if "#" in s:
            s, _, trailing = s.partition("#")
            s = s.strip()
            m = re.search(r"mode:\s*(\S+)", trailing, re.I)
            if m:
                line_mode = _valid_mode(m.group(1), lineno)
        if not _looks_like_channel(s):
            malformed.append((lineno, s))
            continue
        entries.append(ChannelEntry(url=s, corpus=corpus, tier=tier, mode=line_mode))

    if malformed:
        logger.warning("Ignored %d line(s) in %s that are not channel references:",
                       len(malformed), path.name)
        for lineno, text in malformed:
            logger.warning("    line %d: %.60s", lineno, text)
    return entries


# ---------------------------------------------------------------------------
# Jargon correction
# ---------------------------------------------------------------------------
def load_jargon_map() -> dict[str, str]:
    path = CONFIG / "jargon_map.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    flat: dict[str, str] = {}
    for _group, mapping in data.items():
        if isinstance(mapping, dict):
            flat.update({k.lower(): v for k, v in mapping.items()})
    return flat


def apply_jargon(text: str, mapping: dict[str, str]) -> tuple[str, list[dict]]:
    """Correct auto-caption mistranscriptions.

    Returns (cleaned_text, changes). The original is NEVER modified --
    cleaned_text is a separate field precisely so every substitution can
    be audited later. Longest phrases are replaced first, so "fair value
    gap" is fixed before a rule touching "gap" alone can interfere.
    """
    if not mapping:
        return text, []
    cleaned, changes = text, []
    for wrong in sorted(mapping, key=len, reverse=True):
        right = mapping[wrong]
        pat = re.compile(rf"\b{re.escape(wrong)}\b", re.I)
        found = pat.findall(cleaned)
        if found:
            cleaned = pat.sub(right, cleaned)
            changes.append({"from": wrong, "to": right, "count": len(found)})
    return cleaned, changes


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------
def quality_check(segments: list[dict], flat: str) -> tuple[bool, str]:
    """Reject transcripts that would pollute the corpus.

    Two failure modes seen in real caption tracks: music/intro videos
    whose 'transcript' is a handful of words, and broken auto-caption
    tracks that emit one word per segment. Both retrieve badly and dilute
    embeddings, so they are skipped and logged rather than saved.
    """
    words = len(flat.split())
    if words < MIN_WORDS:
        return False, f"too_short:{words}w"
    if segments:
        singles = sum(1 for s in segments if len(str(s.get("text", "")).split()) <= 1)
        ratio = singles / len(segments)
        if ratio > MAX_FILLER_RATIO:
            return False, f"filler:{ratio:.0%}"
    return True, "ok"


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------
@dataclass
class RunStats:
    ok: int = 0
    failed: int = 0
    skipped_existing: int = 0
    skipped_filter: int = 0
    skipped_quality: int = 0
    per_channel: dict = field(default_factory=dict)
    per_corpus: dict = field(default_factory=dict)
    manifest: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)


class YouTubeScraper:
    def __init__(self, filter_mode: str = "all", dry_run: bool = False):
        self.filter_mode = filter_mode
        self.dry_run = dry_run
        self.api = YouTubeTranscriptApi()
        self.jargon = load_jargon_map()
        self.stats = RunStats()
        self._since_pause = 0
        for d in (TRANSCRIPTS, STATE, CONFIG):
            d.mkdir(parents=True, exist_ok=True)

    # -- listing -----------------------------------------------------------
    def list_videos(self, channel_url: str, limit: int) -> list[dict]:
        """List videos via yt-dlp WITHOUT downloading media.

        extract_flat keeps this to a metadata listing. A channel that
        cannot be resolved (renamed handle, private, deleted) raises, and
        the caller logs it and moves on -- one bad handle must never end a
        multi-channel run.

        TAB FALLBACK. Appending "/videos" is right for most channels but
        not all: yt-dlp answers "this channel does not have a videos tab"
        for channels that publish only live streams or shorts, and that
        error is indistinguishable from a dead handle in the log. Since
        this list is expected to contain slightly-wrong handles that the
        user wants reported for manual fixing, mislabelling a LIVE channel
        as unresolved would send them chasing a handle that is fine. So
        "/videos" is tried first, then the bare channel URL, then
        "/streams", and only a channel that yields nothing from any of
        them is reported unresolved. A caller who pins a tab explicitly is
        taken at their word and gets no fallback.
        """
        opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
                "playlistend": limit, "ignoreerrors": True, "skip_download": True}
        base = channel_url.rstrip("/")
        pinned = base.endswith(("/videos", "/streams", "/shorts"))
        candidates = [base] if pinned else [base + "/videos", base, base + "/streams"]

        info = None
        for candidate in candidates:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    got = ydl.extract_info(candidate, download=False)
            except Exception as e:
                logger.debug("    %s -> %s", candidate, str(e)[:90])
                continue
            if got and got.get("entries"):
                info = got
                break

        if not info or not info.get("entries"):
            raise RuntimeError("no entries returned")

        out = []
        for e in info["entries"]:
            if not e or not e.get("id"):
                continue
            out.append({
                "video_id": e["id"],
                "title": e.get("title") or "",
                "duration_seconds": e.get("duration"),
                "view_count": e.get("view_count"),
                "upload_date": e.get("upload_date"),
                "channel": info.get("channel") or info.get("uploader") or "",
            })
        return out[:limit]

    # -- fetching ----------------------------------------------------------
    def fetch_video_metadata(self, video_id: str) -> dict:
        """Fill in the fields the flat channel listing does not carry.

        yt-dlp's extract_flat listing returns id/title/duration/view_count
        but NOT upload_date or like_count -- YouTube does not put them in
        the channel-tab payload, so they came back None for every video.
        upload_date is needed in three places (attribution on the record,
        the incremental re-run cutoff, and retrieval weighting), so it has
        to come from the video page.

        COST, stated plainly rather than hidden: this is a SECOND request,
        so a SAVED video costs two instead of one. Three things keep that
        honest against the no-block rule. It runs only AFTER the transcript
        succeeded and passed the quality gate, so nothing is spent on
        videos that are skipped, filtered, or rejected. It sits inside the
        same paced loop, so it adds no burst -- just depth per video. And
        if it fails the transcript is still saved with whatever the listing
        gave: losing a good transcript over a missing like count would be
        absurd.
        """
        opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                "ignoreerrors": True}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}", download=False) or {}
        except Exception as e:                       # never fatal -- see docstring
            logger.debug("    metadata unavailable for %s: %s", video_id, e)
            return {}
        # Drop Nones so a failed lookup cannot blank a value the listing had.
        return {k: v for k, v in {
            "upload_date": info.get("upload_date"),
            "like_count": info.get("like_count"),
            "view_count": info.get("view_count"),
            "duration_seconds": info.get("duration"),
            "title": info.get("title"),
            "channel": info.get("channel") or info.get("uploader"),
        }.items() if v is not None}

    def fetch_transcript(self, video_id: str) -> Optional[dict]:
        """Fetch one transcript, with exponential backoff.

        Distinguishes PERMANENT failures (captions disabled, video gone,
        no transcript) from TRANSIENT ones (rate limiting, network).
        Retrying a video whose captions are switched off just burns quota
        against the same guaranteed failure, so those return immediately.
        """
        for attempt, wait in enumerate((0, *BACKOFF_SCHEDULE), start=0):
            if wait:
                logger.warning("    retry %d after %ds", attempt, wait)
                time.sleep(wait)
            try:
                listing = self.api.list(video_id)
                transcript = None
                is_generated = True
                # Prefer a MANUAL track: auto captions mangle trading
                # jargon, and the caller needs to know which it got.
                try:
                    transcript = listing.find_manually_created_transcript(["en", "en-US", "en-GB"])
                    is_generated = False
                except Exception:
                    transcript = listing.find_transcript(["en", "en-US", "en-GB"])
                    is_generated = bool(getattr(transcript, "is_generated", True))
                fetched = transcript.fetch()
                raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
                return {
                    "segments": [{"start_seconds": round(float(s.get("start", 0.0)), 3),
                                  "duration": round(float(s.get("duration", 0.0)), 3),
                                  "text": str(s.get("text", "")).strip()} for s in raw],
                    "caption_type": "auto" if is_generated else "manual",
                    "language": getattr(transcript, "language_code", "en"),
                }
            except PERMANENT_ERRORS as e:
                return {"error": type(e).__name__}          # permanent, do not retry
            except BLOCK_ERRORS as e:
                # YouTube is refusing us. Back off through the schedule, and
                # if it still refuses, stop the RUN -- do not grind through
                # the remaining videos collecting identical failures, and do
                # not route around it. Requirement 7 is explicit that the
                # answer to a block is to slow down or stop, never to evade.
                global _BLOCKED
                logger.error("    BLOCKED on %s: %s", video_id, str(e)[:100])
                if attempt >= len(BACKOFF_SCHEDULE):
                    _BLOCKED = True
                    return {"error": f"BLOCKED: {type(e).__name__}"}
            except Exception as e:
                if attempt >= len(BACKOFF_SCHEDULE):
                    return {"error": f"{type(e).__name__}: {str(e)[:120]}"}
        return {"error": "exhausted_retries"}

    # -- per-video ---------------------------------------------------------
    def process_video(self, meta: dict, entry: ChannelEntry, channel_dir: Path) -> str:
        vid = meta["video_id"]
        out_path = channel_dir / f"{vid}.json"
        if out_path.exists():
            # Trust the file only if it PARSES. A process killed mid-write
            # (power loss, task manager, SIGKILL) can leave a truncated
            # JSON file behind, and a plain exists() check would treat that
            # corpse as done and skip it on every future run -- a silently
            # lost video that no counter reports. Re-fetching costs one
            # request; skipping forever costs the video.
            try:
                probe = json.loads(out_path.read_text(encoding="utf-8"))
                if probe.get("video_id"):
                    self.stats.skipped_existing += 1
                    return "exists"
                raise ValueError("no video_id")
            except Exception as e:
                logger.warning("  re-fetching %s -- existing file is unusable (%s)",
                               vid, str(e)[:60])
                out_path.unlink(missing_ok=True)

        result = self.fetch_transcript(vid)
        if result is None or "error" in result:
            reason = (result or {}).get("error", "unknown")
            self._log_failure(vid, entry, reason)
            self.stats.failed += 1
            return "failed"

        segments = result["segments"]
        raw_text = " ".join(s["text"] for s in segments if s["text"]).strip()
        ok, why = quality_check(segments, raw_text)
        if not ok:
            self._log_failure(vid, entry, f"quality_{why}")
            self.stats.skipped_quality += 1
            return "low_quality"

        # Only now -- the transcript is real and worth keeping.
        meta = {**meta, **self.fetch_video_metadata(vid)}

        cleaned_text, changes = apply_jargon(raw_text, self.jargon)
        record = {
            "video_id": vid,
            "title": meta.get("title", ""),
            "channel": meta.get("channel") or entry.handle,
            "channel_url": entry.url,
            "corpus": entry.corpus,
            "tier": entry.tier,
            "video_url": f"https://youtu.be/{vid}",
            "timestamp_link_format": f"https://youtu.be/{vid}?t={{seconds}}",
            "upload_date": meta.get("upload_date"),
            "duration_seconds": meta.get("duration_seconds"),
            "view_count": meta.get("view_count"),
            "like_count": meta.get("like_count"),
            "caption_type": result["caption_type"],
            "language": result.get("language", "en"),
            "word_count": len(raw_text.split()),
            "segment_count": len(segments),
            # Segments are the point: without per-segment timestamps a
            # retrieved chunk can never be linked back to the moment in
            # the video, and flattening is irreversible without re-scraping.
            "segments": segments,
            "raw_text": raw_text,
            "cleaned_text": cleaned_text,
            "jargon_corrections": changes,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }
        # Written IMMEDIATELY -- nothing is buffered, so an interrupt or a
        # block can never cost more than the video in flight.
        #
        # ATOMIC: serialise to a temp file in the same directory, then
        # os.replace, which is atomic on Windows and POSIX alike. A direct
        # write_text can be interrupted halfway, leaving a half-written
        # JSON file that looks complete to a bare exists() check. Either
        # the whole transcript lands or nothing does; there is no state in
        # between for a resume to trip over.
        _atomic_write_json(out_path, record)

        self.stats.ok += 1
        self.stats.manifest.append({
            "video_id": vid, "corpus": entry.corpus, "channel": entry.handle,
            "title": record["title"], "word_count": record["word_count"],
            "caption_type": record["caption_type"], "path": str(out_path.relative_to(ROOT)),
        })
        return "ok"

    def _log_failure(self, vid: str, entry: ChannelEntry, reason: str) -> None:
        with FAILED_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()}\t{entry.corpus}\t"
                    f"{entry.handle}\t{vid}\t{reason}\n")

    # -- per-channel -------------------------------------------------------
    def process_channel(self, entry: ChannelEntry, limit: int, retry_failed: bool = False) -> None:
        global _INTERRUPTED
        logger.info("\n%s", "=" * 78)
        logger.info("CHANNEL %s   corpus=%s tier=%s", entry.url, entry.corpus, entry.tier)

        try:
            videos = self.list_videos(entry.url, limit)
        except Exception as e:
            logger.error("  UNRESOLVED: %s (%s) -- logged, continuing", entry.url, str(e)[:70])
            with UNRESOLVED_LOG.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()}\t{entry.url}\t{str(e)[:150]}\n")
            self.stats.unresolved.append(entry.url)
            return

        # Incremental: only videos newer than the last run for this channel.
        state_path = STATE / f"{entry.handle}.json"
        last_seen = None
        if state_path.exists() and not retry_failed:
            try:
                last_seen = json.loads(state_path.read_text(encoding="utf-8")).get("newest_video_id")
            except Exception:
                last_seen = None
        if last_seen:
            ids = [v["video_id"] for v in videos]
            if last_seen in ids:
                cut = ids.index(last_seen)
                if cut == 0:
                    logger.info("  no new videos since last run")
                    return
                logger.info("  incremental: %d new since %s", cut, last_seen)
                videos = videos[:cut]

        if self.filter_mode == "concepts":
            kept = [(v, should_keep_title(v["title"], entry.mode)) for v in videos]
            videos = [v for v, (keep, _) in kept if keep]
            self.stats.skipped_filter += sum(1 for _, (keep, _) in kept if not keep)
            logger.info("  concepts filter [%s]: %d of %d titles kept",
                        entry.mode, len(videos), len(kept))
            for v in videos:
                logger.info("     - %s", v["title"][:88])
            if not videos:
                return
            if not self.dry_run:
                ans = input(f"\n  Download these {len(videos)} videos? [y/N] ").strip().lower()
                if ans != "y":
                    logger.info("  skipped by user")
                    return

        if self.dry_run:
            logger.info("  DRY RUN -- %d videos would be fetched", len(videos))
            return

        channel_dir = TRANSCRIPTS / entry.corpus / entry.handle
        channel_dir.mkdir(parents=True, exist_ok=True)

        started = time.time()
        total = len(videos)
        newest = videos[0]["video_id"] if videos else last_seen
        finished_channel = True
        for i, meta in enumerate(videos, start=1):
            if _INTERRUPTED or _BLOCKED:
                why = "blocked by YouTube" if _BLOCKED else "interrupted"
                logger.warning("  stopping early (%s) -- progress is on disk, re-run to resume", why)
                finished_channel = False
                break

            status = self.process_video(meta, entry, channel_dir)
            elapsed = time.time() - started
            rate = elapsed / i
            remaining = rate * (total - i)
            logger.info("  [%d/%d] %-11s ok=%d fail=%d | %.0fs elapsed, ~%.0fs left | %s",
                        i, total, status, self.stats.ok, self.stats.failed,
                        elapsed, remaining, meta["title"][:52])

            if status == "exists":
                continue

            # Randomised gap -- a fixed interval is itself a bot signature.
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            self._since_pause += 1
            if self._since_pause >= LONG_PAUSE_EVERY:
                pause = random.uniform(LONG_PAUSE_MIN, LONG_PAUSE_MAX)
                logger.info("  -- %d videos done, pausing %.0fs to stay under the limit --",
                            LONG_PAUSE_EVERY, pause)
                time.sleep(pause)
                self._since_pause = 0

        self.stats.per_channel[entry.handle] = self.stats.per_channel.get(entry.handle, 0) + self.stats.ok
        self.stats.per_corpus[entry.corpus] = self.stats.per_corpus.get(entry.corpus, 0) + 1
        # ONLY advance the incremental cursor when the whole channel was
        # processed. `newest` is videos[0] -- the newest video in the
        # listing -- and it is decided BEFORE the loop runs. Writing it
        # after an interrupted loop claims the channel is up to date when
        # it is not: stop after 10 of 100 and the next run asks for
        # "videos newer than the newest one", finds none, and the other 90
        # are skipped on that run and every run after it. The transcripts
        # already downloaded would survive, so this looked safe, but the
        # QUEUE would be silently lost -- which is what requirement 3 is
        # actually protecting.
        #
        # Leaving the cursor where it was costs one channel listing on the
        # next run and nothing else: already-saved videos are skipped by
        # the out_path.exists() check before any network call, so no
        # transcript is fetched twice.
        if newest and finished_channel:
            _atomic_write_json(state_path, {
                "channel": entry.handle, "corpus": entry.corpus,
                "newest_video_id": newest,
                "last_run": datetime.now(timezone.utc).isoformat(),
            })
        elif not finished_channel:
            logger.info("  incremental cursor left unchanged -- channel was interrupted, "
                        "so the remaining videos stay queued for the next run")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def write_manifest(stats: RunStats) -> None:
    """Index of everything ON DISK, for the embedding pipeline.

    Built by SCANNING ./transcripts, not from this run's stats. The
    difference is not cosmetic: the manifest was previously written from
    stats.manifest, which holds only what the current run saved, so a
    re-run that saved nothing -- the normal case once a channel is
    up to date -- overwrote the file with an empty list. Observed live:
    four transcripts on disk, "videos": 0 in the manifest. Since the
    stated purpose of this file is to spare the embedding pipeline from
    walking the tree, an empty manifest silently yields an empty vector
    store while the data sits right there.

    Scanning makes the file a true index at all times, and makes it
    self-healing: transcripts written by an interrupted run, or restored
    from a backup, are picked up on the next run rather than being
    invisible forever.

    `stats` is still accepted so the caller is unchanged, and is used only
    to report how many of these were added by this run.
    """
    videos: list[dict] = []
    per_corpus: dict[str, dict] = {}
    for path in sorted(TRANSCRIPTS.rglob("*.json")):
        if path.name == "manifest.json":
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:                  # a truncated file must not abort the index
            logger.warning("  manifest: skipping unreadable %s (%s)", path.name, e)
            continue
        if not d.get("video_id"):
            continue
        corpus = d.get("corpus") or "uncategorised"
        caption = d.get("caption_type") or "auto"
        words = int(d.get("word_count") or 0)
        videos.append({
            "video_id": d["video_id"],
            "corpus": corpus,
            "channel": d.get("channel") or path.parent.name,
            "title": d.get("title", ""),
            "word_count": words,
            "caption_type": caption,
            "upload_date": d.get("upload_date"),
            "video_url": d.get("video_url", ""),
            "path": str(path),
        })
        c = per_corpus.setdefault(corpus, {"videos": 0, "words": 0, "manual": 0, "auto": 0})
        c["videos"] += 1
        c["words"] += words
        c["manual" if caption == "manual" else "auto"] += 1

    _atomic_write_json(TRANSCRIPTS / "manifest.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "added_this_run": len(stats.manifest),
        "totals_per_corpus": per_corpus,
        "videos": videos,
    })
    logger.info("manifest -> %s  (%d videos indexed, %d new this run)",
                TRANSCRIPTS / "manifest.json", len(videos), len(stats.manifest))


def storage_report() -> None:
    if not TRANSCRIPTS.exists():
        return
    logger.info("\nSTORAGE")
    for corpus_dir in sorted(p for p in TRANSCRIPTS.iterdir() if p.is_dir()):
        total = 0
        for chan in sorted(p for p in corpus_dir.iterdir() if p.is_dir()):
            size = sum(f.stat().st_size for f in chan.glob("*.json"))
            total += size
            if size > LARGE_CHANNEL_MB * 1024 * 1024:
                logger.warning("  WARNING %s/%s is %.0f MB (over %d MB)",
                               corpus_dir.name, chan.name, size / 1048576, LARGE_CHANNEL_MB)
        logger.info("  %-14s %.1f MB", corpus_dir.name, total / 1048576)


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--channel", help="single channel URL or @handle")
    ap.add_argument("--channels-file", type=Path, help="channels.txt with # CORPUS:/# TIER: markers")
    ap.add_argument("--tier", default="all", help="1 | 2 | 3 | all")
    ap.add_argument("--limit", type=int, default=100, help="max videos PER CHANNEL (default 100)")
    ap.add_argument("--filter-mode", choices=("all", "concepts"), default="all")
    ap.add_argument("--corpus", default="trading", help="corpus tag for --channel")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--retry-failed", action="store_true", help="ignore saved state and re-scan")
    # Pacing is adjustable UPWARDS from the command line because the right
    # delay is not a constant -- it depends on how much this IP has already
    # asked for today. After the first tier-1 attempt was IP-blocked around
    # video 20, the useful lever was a slower run, not a cleverer one.
    ap.add_argument("--delay-min", type=float, default=DELAY_MIN,
                    help=f"min seconds between videos (default {DELAY_MIN})")
    ap.add_argument("--delay-max", type=float, default=DELAY_MAX,
                    help=f"max seconds between videos (default {DELAY_MAX})")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(PROGRESS_LOG, encoding="utf-8")])
    signal.signal(signal.SIGINT, _handle_sigint)
    # SIGTERM too: Ctrl+C is not the only way a long run ends. A task
    # manager kill, a shutdown, or a supervisor stopping the job all send
    # SIGTERM, and without a handler the process dies mid-video with no
    # chance to finish the write it is in.
    try:
        signal.signal(signal.SIGTERM, _handle_sigint)
    except (AttributeError, ValueError):
        pass                                   # not available on this platform

    if args.channels_file:
        if not args.channels_file.exists():
            sys.exit(f"channels file not found: {args.channels_file}")
        entries = parse_channels_file(args.channels_file)
        if args.tier.lower() != "all":
            entries = [e for e in entries if e.tier == args.tier.lower()]
    elif args.channel:
        entries = [ChannelEntry(url=args.channel, corpus=args.corpus, tier="all")]
    else:
        sys.exit("Provide --channel or --channels-file")

    if not entries:
        sys.exit(f"No channels matched tier={args.tier}")

    logger.info("%d channel(s) | tier=%s | limit=%d/channel | filter=%s%s",
                len(entries), args.tier, args.limit, args.filter_mode,
                " | DRY RUN" if args.dry_run else "")
    logger.info("Sequential only, randomised %.0f-%.0fs between videos. No proxies, by design.",
                DELAY_MIN, DELAY_MAX)

    _apply_delays(args.delay_min, args.delay_max)

    scraper = YouTubeScraper(filter_mode=args.filter_mode, dry_run=args.dry_run)
    run_start = time.time()

    for idx, entry in enumerate(entries, start=1):
        if _INTERRUPTED or _BLOCKED:
            break
        logger.info("\n>>> channel %d/%d", idx, len(entries))
        try:
            scraper.process_channel(entry, args.limit, retry_failed=args.retry_failed)
        except Exception as e:      # one bad channel must not end the run
            logger.error("  channel error (continuing): %s", str(e)[:120])
            with UNRESOLVED_LOG.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()}\t{entry.url}\t{str(e)[:150]}\n")
            scraper.stats.unresolved.append(entry.url)
        if idx < len(entries) and not _INTERRUPTED and not _BLOCKED and not args.dry_run:
            pause = random.uniform(CHANNEL_PAUSE_MIN, CHANNEL_PAUSE_MAX)
            logger.info("  pausing %.0fs before the next channel", pause)
            time.sleep(pause)

    s = scraper.stats
    logger.info("\n%s\nRUN SUMMARY  (%.0f min)", "=" * 78, (time.time() - run_start) / 60)
    logger.info("  saved            %d", s.ok)
    logger.info("  already present  %d", s.skipped_existing)
    logger.info("  filtered out     %d", s.skipped_filter)
    logger.info("  low quality      %d", s.skipped_quality)
    logger.info("  failed           %d", s.failed)
    if s.per_corpus:
        logger.info("  channels/corpus: %s", dict(s.per_corpus))
    if not args.dry_run:
        write_manifest(s)      # logs its own path and counts
        storage_report()
    if s.failed:
        logger.info("failures -> %s", FAILED_LOG.name)
    # Only if THIS run failed to resolve something. The file persists
    # between runs, so testing existence alone told a clean run it had
    # unresolved channels -- pointing the user at stale entries they had
    # already dealt with.
    if s.unresolved:
        logger.info("unresolved channels (%d this run) -> %s",
                    len(s.unresolved), UNRESOLVED_LOG.name)
    if _BLOCKED:
        logger.warning('STOPPED: YouTube blocked our requests and kept blocking through the full backoff. Everything fetched is on disk and the incremental cursors were NOT advanced, so re-running the same command later resumes exactly where this left off. Wait a few hours before resuming. There is no proxy or IP-rotation option here by design -- the only correct responses to a block are to wait longer or request less.')
    elif _INTERRUPTED:
        logger.info("\nStopped early. Everything fetched is on disk -- re-run the same command to resume.")


if __name__ == "__main__":
    main()

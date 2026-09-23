"""
Module: ingest_local_subs.py
Description: Turns locally-downloaded subtitle files into the same transcript
    JSON the scraper produces -- no YouTube requests at all.

    WHY THIS EXISTS. This IP is currently blocked: the transcript API returns
    IpBlocked and yt-dlp's own subtitle fetch returns HTTP 429. Both remedies
    for that are slow (wait it out) or external (fetch the files from a
    machine or network that is not blocked). This script covers the second:
    you bring the subtitle files, it produces the corpus.

    This is NOT block evasion. Nothing here masks an identity, rotates an
    address, or forges a header. It makes no network request whatsoever --
    it reads files that already exist on disk. Where those files came from
    is a question for whoever downloaded them; from this script's side it is
    ordinary local parsing.

    DOWNLOAD SUBTITLES, NOT VIDEOS. A .vtt caption track is a few kilobytes
    and carries exactly the data the API would have returned, timestamps
    included. The video is hundreds of megabytes and would then need an ASR
    model and ffmpeg to get back to worse text than the captions already
    hold. There is no version of this where downloading the video is the
    better plan. The recommended command is printed by --help-download.

    OUTPUT IS IDENTICAL to the scraper's: same schema, same quality gate,
    same jargon map, same folders. The two paths can be mixed freely, and
    the manifest indexes whatever is on disk regardless of origin.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from youtube_scraper import (  # noqa: E402  -- same behaviour, deliberately reused
    TRANSCRIPTS, _atomic_write_json, apply_jargon, load_jargon_map,
    quality_check, write_manifest, RunStats,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("ingest")

DOWNLOAD_HELP = """
Fetches ONLY subtitles and metadata -- no video, no audio.

A word on WHERE you run it, because I put this badly the first time. I
originally wrote "run it on another network, a VPS, or a phone hotspot",
which is close to the IP-cycling this project refuses. Moving to a fresh
address to keep up a request rate YouTube already refused is evasion in
substance, whatever the mechanism. Running it slowly on a connection you
were going to use anyway is ordinary use. The honest difference is the
rate, not the address -- so pace it either way and do not treat a new IP
as a reset button.

  yt-dlp --skip-download --write-subs --write-auto-subs \\
         --sub-langs "en.*" --sub-format vtt --write-info-json \\
         --output "%(channel)s/%(id)s.%(ext)s" \\
         "https://youtube.com/@CHANNEL/videos" --playlist-end 30

That produces one folder per channel holding <id>.en.vtt and
<id>.info.json. Copy those folders anywhere and point this script at the
parent:

  python scripts/ingest_local_subs.py --source ./downloads --corpus trading

The .info.json is optional but worth having: without it there is no title,
upload_date, view_count or like_count to record, and the attribution the
RAG layer depends on gets thinner.

Pace that download too. It is the same IP asking the same service for the
same data -- a fast loop there earns the same block this script exists to
work around. --sleep-requests 3 is a sensible floor.
"""

_TS = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})")


def _seconds(ts: str) -> float:
    m = _TS.search(ts)
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def _clean_cue(text: str) -> str:
    """Strip the markup YouTube puts inside caption cues."""
    text = re.sub(r"<[^>]+>", "", text)          # <c>, <00:00:01.234>, <i>
    text = re.sub(r"\{\\[^}]*\}", "", text)      # ASS-style overrides
    text = text.replace("&nbsp;", " ")
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#39;", "'"), ("&quot;", '"')):
        text = text.replace(a, b)
    return " ".join(text.split())


def _dedupe_rolling(prev_words: list[str], words: list[str]) -> list[str]:
    """Drop the part of a cue that merely repeats the end of the previous one.

    YouTube's auto-captions scroll: each cue re-prints the tail of the cue
    before it so the text appears to roll up the screen. The overlap is a
    SUFFIX of the previous cue matching a PREFIX of this one -- not a whole
    repeated line -- so a startswith() check catches almost none of it.
    Concatenating cues naively inflates a transcript by roughly half, which
    corrupts the word count, wastes embedding budget, and makes retrieval
    return the same sentence several times over.

    Longest overlap wins, so the shortest genuinely-new remainder is kept.
    """
    limit = min(len(prev_words), len(words))
    for k in range(limit, 0, -1):
        if prev_words[-k:] == words[:k]:
            return words[k:]
    return words


def parse_vtt(raw: str) -> list[dict]:
    """Parse WebVTT into timestamped segments, undoing rolling captions.

    Each segment keeps only the words it actually introduces, with its own
    start time, so timestamps stay accurate and no text is counted twice.
    """
    segments: list[dict] = []
    prev_words: list[str] = []
    for block in re.split(r"\n\s*\n", raw.replace("\r\n", "\n")):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if idx is None:
            continue
        start_s, _, end_s = lines[idx].partition("-->")
        start, end = _seconds(start_s), _seconds(end_s)
        text = _clean_cue(" ".join(lines[idx + 1:]))
        if not text:
            continue
        words = text.split()
        fresh = _dedupe_rolling(prev_words, words) if prev_words else words
        prev_words = words
        if not fresh:
            # Pure repeat: extend the previous segment rather than dropping
            # the time it was on screen.
            if segments:
                segments[-1]["duration"] = round(
                    max(segments[-1]["duration"], end - segments[-1]["start_seconds"]), 3)
            continue
        segments.append({"start_seconds": round(start, 3),
                         "duration": round(max(0.0, end - start), 3),
                         "text": " ".join(fresh)})
    return segments


def parse_srt(raw: str) -> list[dict]:
    segments: list[dict] = []
    for block in re.split(r"\n\s*\n", raw.replace("\r\n", "\n")):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if idx is None:
            continue
        start_s, _, end_s = lines[idx].partition("-->")
        text = _clean_cue(" ".join(lines[idx + 1:]))
        if text:
            start, end = _seconds(start_s), _seconds(end_s)
            segments.append({"start_seconds": round(start, 3),
                             "duration": round(max(0.0, end - start), 3),
                             "text": text})
    return segments


def _is_auto_caption(path: Path, info: dict, segments: list[dict]) -> bool:
    """Manual or auto-generated? This drives retrieval weighting, so guessing
    badly here quietly mis-ranks the whole corpus.

    yt-dlp writes BOTH kinds to the same "<id>.en.vtt" name, so the filename
    settles nothing -- an earlier version keyed off ".auto" in the name and
    labelled obviously auto-generated rolling captions as manual.

    The .info.json does know: a language present in "subtitles" was uploaded
    by the channel, while one appearing only under "automatic_captions" is
    ASR. When there is no sidecar, fall back to the shape of the text --
    auto-captions arrive lowercase and unpunctuated, so a track with almost
    no sentence punctuation is ASR whatever it is called.
    """
    langs = lambda d: {k.split("-")[0] for k in (d or {})}
    manual_langs = langs(info.get("subtitles"))
    auto_langs = langs(info.get("automatic_captions"))
    if "en" in manual_langs:
        return False
    if "en" in auto_langs:
        return True

    sample = " ".join(s["text"] for s in segments[:60])
    if not sample:
        return True
    punctuation = sum(sample.count(c) for c in ".?!")
    words = max(1, len(sample.split()))
    return (punctuation / words) < 0.01          # ~1 mark per 100 words


def _sidecar(sub_path: Path) -> dict:
    """yt-dlp's .info.json, if it was downloaded alongside."""
    vid = sub_path.name.split(".")[0]
    for cand in (sub_path.with_name(f"{vid}.info.json"),
                 sub_path.parent / f"{vid}.info.json"):
        if cand.exists():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("  unreadable info.json for %s (%s)", vid, str(e)[:50])
    return {}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, help="folder holding per-channel subfolders")
    ap.add_argument("--corpus", default="trading", help="corpus tag for everything ingested")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--help-download", action="store_true",
                    help="print the yt-dlp command that produces the right files")
    args = ap.parse_args()

    if args.help_download or not args.source:
        print(DOWNLOAD_HELP)
        return
    if not args.source.exists():
        raise SystemExit(f"No such folder: {args.source}")

    jargon = load_jargon_map()
    stats = RunStats()
    subs = [p for p in args.source.rglob("*") if p.suffix.lower() in (".vtt", ".srt")]
    if not subs:
        raise SystemExit(f"No .vtt or .srt files under {args.source}. "
                         f"Run with --help-download for the command that makes them.")

    logger.info("%d subtitle file(s) under %s -> corpus '%s'%s",
                len(subs), args.source, args.corpus, "  [DRY RUN]" if args.dry_run else "")

    for i, path in enumerate(sorted(subs), 1):
        vid = path.name.split(".")[0]
        info = _sidecar(path)
        channel = (info.get("channel") or info.get("uploader")
                   or path.parent.name or "unknown")
        chan_slug = re.sub(r"[^A-Za-z0-9_.-]", "_", channel).strip("_") or "unknown"

        raw = path.read_text(encoding="utf-8", errors="replace")
        segments = parse_vtt(raw) if path.suffix.lower() == ".vtt" else parse_srt(raw)
        flat = " ".join(s["text"] for s in segments).strip()
        ok, why = quality_check(segments, flat)
        if not ok:
            logger.info("  [%d/%d] skip %s -- %s", i, len(subs), vid, why)
            stats.skipped_quality += 1
            continue

        out_dir = TRANSCRIPTS / args.corpus / chan_slug
        out_path = out_dir / f"{vid}.json"
        if out_path.exists():
            stats.skipped_existing += 1
            continue

        cleaned, changes = apply_jargon(flat, jargon)
        auto = _is_auto_caption(path, info, segments)
        record = {
            "video_id": vid,
            "title": info.get("title", ""),
            "channel": channel,
            "channel_url": info.get("channel_url", ""),
            "corpus": args.corpus,
            "tier": "local",
            "video_url": f"https://youtu.be/{vid}",
            "upload_date": info.get("upload_date"),
            "duration_seconds": info.get("duration"),
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "caption_type": "auto" if auto else "manual",
            "language": "en",
            "segments": segments,
            "segment_count": len(segments),
            "word_count": len(flat.split()),
            "raw_text": flat,
            "cleaned_text": cleaned,
            "jargon_corrections": changes,
            "timestamp_link_format": f"https://youtu.be/{vid}?t={{seconds}}",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "source": "local_subtitles",       # provenance, so origin stays auditable
        }
        if args.dry_run:
            logger.info("  [%d/%d] would save %s (%d words, %d segs) %s",
                        i, len(subs), vid, record["word_count"], len(segments),
                        record["title"][:40])
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(out_path, record)
        stats.ok += 1
        stats.manifest.append({"video_id": vid, "corpus": args.corpus, "channel": chan_slug,
                               "title": record["title"], "word_count": record["word_count"],
                               "caption_type": record["caption_type"],
                               "path": str(out_path)})
        logger.info("  [%d/%d] ok %s  %d words  %s",
                    i, len(subs), vid, record["word_count"], record["title"][:44])

    logger.info("\nSUMMARY\n  saved %d\n  already present %d\n  low quality %d",
                stats.ok, stats.skipped_existing, stats.skipped_quality)
    if not args.dry_run:
        write_manifest(stats)


if __name__ == "__main__":
    main()

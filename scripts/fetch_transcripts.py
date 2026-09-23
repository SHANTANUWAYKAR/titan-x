"""Pull YouTube transcripts into data/knowledge/transcripts/ for study and search.

WHY THIS EXISTS. Trading education arrives as video, which is the worst possible
format for checking a claim. A transcript is greppable: when a presenter says
"based on my backtesting" you can find every such phrase across sixteen hours in
a second and see how many are followed by an actual number. (In the 2026-09-22
corpus of 11 videos, the answer was none.)

HONESTY ABOUT WHAT THIS IS. A caption track is what was SAID, not what was
SHOWN. Every one of these videos is chart-driven, so a transcript loses the
part the presenter is pointing at. Anything read from here is evidence about
the spoken claim and nothing more -- do not write "the chart showed" from a
transcript.

    python scripts/fetch_transcripts.py https://youtu.be/VIDEOID ...
    python scripts/fetch_transcripts.py --file urls.txt
    python scripts/fetch_transcripts.py --status
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "knowledge" / "transcripts"
INDEX = OUT / "_fetch_report.json"

# youtu.be/ID, youtube.com/watch?v=ID, /shorts/ID, /embed/ID
_ID = re.compile(
    r"(?:youtu\.be/|v=|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def video_id(url: str) -> str | None:
    m = _ID.search(url)
    return m.group(1) if m else (url if re.fullmatch(r"[A-Za-z0-9_-]{11}", url) else None)


def title_of(vid: str) -> tuple[str, str]:
    """(channel, title) via oEmbed, or ('', '') when unavailable.

    Deliberately non-fatal: a missing title must never cost us a transcript.
    """
    q = urllib.parse.urlencode({"url": f"https://youtu.be/{vid}", "format": "json"})
    try:
        d = json.load(urllib.request.urlopen(
            f"https://www.youtube.com/oembed?{q}", timeout=20))
        return d.get("author_name", ""), d.get("title", "")
    except Exception:  # noqa: BLE001
        return "", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--file", help="text file with one URL per line")
    ap.add_argument("--status", action="store_true", help="show what is stored")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    if args.status:
        rows = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else []
        got = [r for r in rows if r.get("ok")]
        print(f"{len(got)} transcript(s) in {OUT}")
        for r in got:
            print(f"  {r['id']}  {r.get('minutes', '?'):>6} min  "
                  f"{r.get('chars', 0):>7,} ch  {r.get('channel', '')} :: {r.get('title', '')}")
        missing = [r for r in rows if not r.get("ok")]
        for r in missing:
            print(f"  {r['id']}  FAILED: {r.get('error')}")
        return 0

    urls = list(args.urls)
    if args.file:
        urls += [ln.strip() for ln in Path(args.file).read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
    if not urls:
        ap.error("give at least one URL, or --file, or --status")

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("pip install youtube-transcript-api")
        return 2

    api = YouTubeTranscriptApi()
    rows = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else []
    known = {r["id"] for r in rows}

    for u in urls:
        vid = video_id(u)
        if not vid:
            print(f"  ?? could not parse a video id from {u!r}")
            continue
        channel, title = title_of(vid)
        rec = {"id": vid, "url": f"https://youtu.be/{vid}",
               "channel": channel, "title": title}
        try:
            tr = api.fetch(vid)
            text = " ".join(sn.text.replace("\n", " ") for sn in tr)
            dur = max((sn.start + sn.duration) for sn in tr) if len(tr) else 0
            (OUT / f"{vid}.txt").write_text(text, encoding="utf-8")
            rec.update(ok=True, chars=len(text), segments=len(tr),
                       minutes=round(dur / 60, 1))
            print(f"  ok {vid}  {rec['minutes']:>6} min  {rec['chars']:>7,} ch  "
                  f"{channel} :: {title}")
        except Exception as e:  # noqa: BLE001
            # Named explicitly: "no transcript" and "blocked" are different
            # problems and only one of them is worth retrying.
            rec.update(ok=False, error=f"{type(e).__name__}: {str(e)[:160]}")
            print(f"  -- {vid}  {rec['error']}")
        rows = [r for r in rows if r["id"] != vid] + [rec]
        known.add(vid)

    INDEX.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    ok = sum(1 for r in rows if r.get("ok"))
    print(f"\n{ok}/{len(rows)} stored in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

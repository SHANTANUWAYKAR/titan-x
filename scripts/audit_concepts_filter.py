"""
Module: audit_concepts_filter.py
Description: Audits the concepts-mode title filter against real channel
    titles, WITHOUT scraping anything.

    Titles come from the channel listing endpoint, which is a different
    request from the caption endpoint that is currently IP-blocked, so this
    audit runs while the block is in force. Nothing here fetches a
    transcript.

    REPORTS, NEVER CHANGES. The filter is left exactly as it is. The point
    is to see where it is wrong before touching it -- a filter tuned to
    look good on its own summary statistics is how a corpus quietly ends up
    full of the wrong videos.

    What it answers:
      1. what was ACCEPTED, per channel, with counts
      2. a sample of REJECTED titles, to hunt false negatives
      3. channels whose accept rate looks implausible in either direction
      4. which patterns actually fire, and which are dead weight
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from youtube_scraper import KEEP_PATTERNS, SKIP_PATTERNS, should_keep_title  # noqa: E402

LOOSE_ABOVE = 0.60
TIGHT_BELOW = 0.05


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--titles", type=Path, required=True,
                    help="JSON: {channel: [title, ...]}")
    ap.add_argument("--show-rejected", type=int, default=30)
    args = ap.parse_args()

    data = json.loads(args.titles.read_text(encoding="utf-8"))
    per_channel: dict[str, dict] = {}
    reasons = Counter()
    rejected_pool: list[tuple[str, str, str]] = []

    for channel, titles in sorted(data.items()):
        acc, rej = [], []
        for t in titles:
            keep, why = should_keep_title(t)
            reasons[why] += 1
            (acc if keep else rej).append((t, why))
            if not keep:
                rejected_pool.append((channel, t, why))
        per_channel[channel] = {"accepted": acc, "rejected": rej,
                                "total": len(titles),
                                "rate": len(acc) / len(titles) if titles else 0.0}

    # ---- 1. accepted, grouped by channel -------------------------------
    print("=" * 96)
    print("1. ACCEPTED TITLES BY CHANNEL")
    print("=" * 96)
    for ch, d in sorted(per_channel.items(), key=lambda kv: -kv[1]["rate"]):
        print(f"\n  {ch}  --  {len(d['accepted'])}/{d['total']} accepted ({d['rate']*100:.0f}%)")
        for t, why in d["accepted"][:12]:
            print(f"      + {t[:78]}")
        if len(d["accepted"]) > 12:
            print(f"      ... {len(d['accepted']) - 12} more")

    # ---- 2. rejected sample --------------------------------------------
    print("\n" + "=" * 96)
    print(f"2. {args.show_rejected} REJECTED TITLES  (check for false negatives)")
    print("=" * 96)
    # Spread the sample across channels rather than dumping the first
    # channel's rejects -- a false negative that only affects one channel
    # is invisible in a sample drawn from one channel.
    by_ch: dict[str, list] = {}
    for ch, t, why in rejected_pool:
        by_ch.setdefault(ch, []).append((t, why))
    sample, i = [], 0
    while len(sample) < args.show_rejected and any(v[i:] for v in by_ch.values() if len(v) > i):
        for ch, items in by_ch.items():
            if i < len(items) and len(sample) < args.show_rejected:
                sample.append((ch, *items[i]))
        i += 1
    for ch, t, why in sample:
        print(f"  [{why:<46}] {ch[:16]:<16} {t[:56]}")

    # ---- 3. suspicious accept rates ------------------------------------
    print("\n" + "=" * 96)
    print("3. CHANNELS WITH A SUSPICIOUS ACCEPT RATE")
    print("=" * 96)
    loose = [(c, d) for c, d in per_channel.items() if d["rate"] > LOOSE_ABOVE and d["total"]]
    tight = [(c, d) for c, d in per_channel.items() if d["rate"] < TIGHT_BELOW and d["total"]]
    if loose:
        print(f"\n  TOO LOOSE (>{LOOSE_ABOVE*100:.0f}% accepted):")
        for c, d in sorted(loose, key=lambda kv: -kv[1]["rate"]):
            print(f"    {c:<28} {d['rate']*100:>5.0f}%  ({len(d['accepted'])}/{d['total']})")
    if tight:
        print(f"\n  TOO TIGHT (<{TIGHT_BELOW*100:.0f}% accepted):")
        for c, d in sorted(tight, key=lambda kv: kv[1]["rate"]):
            print(f"    {c:<28} {d['rate']*100:>5.0f}%  ({len(d['accepted'])}/{d['total']})")
    if not loose and not tight:
        print("\n  none outside the thresholds")

    # ---- 4. pattern usage ----------------------------------------------
    print("\n" + "=" * 96)
    print("4. PATTERN USAGE")
    print("=" * 96)
    fired = Counter()
    for why, n in reasons.items():
        if ":" in why:
            fired[why.split(":", 1)[1]] += n

    print("\n  SKIP patterns, most-fired first:")
    for pat in sorted(SKIP_PATTERNS, key=lambda p: -fired.get(p, 0)):
        n = fired.get(pat, 0)
        print(f"    {n:>5}  {pat}" + ("      <-- NEVER FIRES" if n == 0 else ""))
    print("\n  KEEP patterns, most-fired first:")
    for pat in sorted(KEEP_PATTERNS, key=lambda p: -fired.get(p, 0)):
        n = fired.get(pat, 0)
        print(f"    {n:>5}  {pat}" + ("      <-- NEVER FIRES" if n == 0 else ""))

    total = sum(d["total"] for d in per_channel.values())
    acc = sum(len(d["accepted"]) for d in per_channel.values())
    nomatch = reasons.get("no-keep-match", 0)
    print("\n" + "=" * 96)
    print(f"  {total} titles   accepted {acc} ({acc/total*100:.1f}%)   rejected {total-acc}")
    print(f"  of the rejections, {nomatch} ({nomatch/max(1,total-acc)*100:.0f}%) matched NO keep "
          f"pattern rather than hitting a skip rule")
    print("=" * 96)


if __name__ == "__main__":
    main()

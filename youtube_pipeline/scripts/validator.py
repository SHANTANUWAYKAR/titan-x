"""
Module: validator.py
Description: YouTube Knowledge Import Pipeline -- Phase 6, Validation.

    Real, mechanical checks over the aggregated extracted knowledge
    (across every processed video in a channel):
      - Duplicate concepts: near-identical TEXT (not semantic similarity
        -- that would need embeddings compared pairwise across
        potentially tens of thousands of items, expensive and still
        approximate; a normalized-text exact/near-exact match is honest
        about what it actually catches: the SAME point stated in
        near-identical wording across videos, which happens constantly
        on an educational channel revisiting the same core lessons).
      - Conflicting ideas: two DEFINITIONS for the same term whose
        definition text disagrees -- flagged for human review, never
        auto-resolved (this pipeline has no basis to decide which
        creator statement is "more correct").
      - Confidence scores: rule_based extraction gets a lower base
        confidence than llm extraction (see knowledge_extractor.py), then
        adjusted by corroboration -- an item whose near-duplicate appears
        across MULTIPLE videos is more likely a real, stable point the
        creator actually teaches (not a one-off remark), so repetition
        raises confidence within a bounded cap.
      - Opinion vs evidence: category == "supporting_evidence" is
        evidence; every other category defaults to "opinion" UNLESS it's
        linked to real evidence in the EvidenceGraph (Phase 5), in which
        case it's "evidence_backed" -- a real, checkable distinction
        rather than a guess.
Author: Shantanu Waykar
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", _PUNCT.sub("", text.lower())).strip()


@dataclass
class ValidationReport:
    total_items: int
    unique_items: int
    duplicate_groups: int
    duplicates_removed: int
    conflicting_definitions: list[dict] = field(default_factory=list)
    evidence_backed_count: int = 0
    opinion_count: int = 0
    evidence_count: int = 0
    mean_confidence: float = 0.0


def deduplicate(all_items: list[dict]) -> tuple[list[dict], int]:
    """Groups items by normalized text; keeps the FIRST occurrence but
    records how many videos independently made the same point (stored as
    `corroboration_count` on the kept item, used by score_confidence
    below) rather than silently discarding the repetition-count signal."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in all_items:
        groups[_normalize(item["text"])].append(item)

    kept: list[dict] = []
    duplicate_groups = 0
    for normalized, group in groups.items():
        representative = dict(group[0])
        representative["corroboration_count"] = len(group)
        representative["source_videos"] = list({g["video_id"] for g in group})
        kept.append(representative)
        if len(group) > 1:
            duplicate_groups += 1

    duplicates_removed = len(all_items) - len(kept)
    return kept, duplicate_groups, duplicates_removed  # type: ignore[return-value]


def find_conflicting_definitions(definitions: list[dict]) -> list[dict]:
    """Two DIFFERENT definition texts for the SAME (normalized) term,
    from different videos, where the definitions don't share enough
    overlapping words to plausibly be the same statement reworded --
    flagged for human review, not resolved. A real, if coarse, conflict
    signal: word-overlap below a threshold between same-term definitions
    is either genuine disagreement or just very different phrasing --
    either way, worth a human glance rather than silently picking one."""
    by_term: dict[str, list[dict]] = defaultdict(list)
    for d in definitions:
        by_term[_normalize(d["term"])].append(d)

    conflicts = []
    for term, defs in by_term.items():
        if len(defs) < 2:
            continue
        seen_texts = []
        for d in defs:
            norm = _normalize(d["definition"])
            words = set(norm.split())
            is_conflict_with_all_seen = True
            for seen_norm, seen_words in seen_texts:
                overlap = len(words & seen_words) / max(len(words | seen_words), 1)
                if overlap > 0.35:  # substantial shared wording -- treat as the same statement, not a conflict
                    is_conflict_with_all_seen = False
                    break
            if is_conflict_with_all_seen and seen_texts:
                conflicts.append({
                    "term": d["term"],
                    "definitions": [{"text": d["definition"], "video_id": d["video_id"], "video_title": d["video_title"]} for d in defs],
                })
                break
            seen_texts.append((norm, words))
    return conflicts


def score_confidence(item: dict) -> float:
    """base (extraction method) + corroboration bonus, capped at 0.95 --
    never 1.0, since this remains a heuristic read of unverified spoken
    content, not a mathematically certain fact regardless of how many
    times it's repeated."""
    base = 0.75 if item.get("extraction_method") == "llm" else 0.5
    corroboration = item.get("corroboration_count", 1)
    bonus = min(0.05 * (corroboration - 1), 0.2)
    return round(min(base + bonus, 0.95), 3)


def classify_opinion_vs_evidence(item: dict, evidence_backed_ids: set[str]) -> str:
    if item.get("category") == "supporting_evidence":
        return "evidence"
    if item.get("item_id") in evidence_backed_ids:
        return "evidence_backed"
    return "opinion"


def validate_channel(channel_dir: Path) -> ValidationReport:
    """Loads every processed video's knowledge.json, aggregates all
    items + definitions, and runs the checks above. Writes
    validation_report.json next to the channel's other outputs."""
    videos_dir = channel_dir / "videos"
    all_items: list[dict] = []
    all_definitions: list[dict] = []

    for video_dir in videos_dir.iterdir():
        knowledge_path = video_dir / "knowledge.json"
        if not knowledge_path.exists():
            continue
        knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
        all_items.extend(knowledge.get("items", []))
        all_definitions.extend(knowledge.get("definitions", []))

    kept, duplicate_groups, duplicates_removed = deduplicate(all_items)
    conflicts = find_conflicting_definitions(all_definitions)

    eg_path = channel_dir / "evidence_graph.json"
    evidence_backed_ids: set[str] = set()
    if eg_path.exists():
        import networkx as nx
        eg_data = json.loads(eg_path.read_text(encoding="utf-8"))
        graph = nx.node_link_graph(eg_data, edges="edges")
        for u, v, data in graph.edges(data=True):
            if data.get("relation") == "supports":
                evidence_backed_ids.add(v)

    opinion_count = evidence_count = evidence_backed_count = 0
    confidences = []
    for item in kept:
        item_id = None  # kept items from deduplicate don't carry item_id unless present in source
        classification = classify_opinion_vs_evidence(item, evidence_backed_ids)
        item["classification"] = classification
        if classification == "opinion":
            opinion_count += 1
        elif classification == "evidence":
            evidence_count += 1
        else:
            evidence_backed_count += 1
        item["confidence_score"] = score_confidence(item)
        confidences.append(item["confidence_score"])

    report = ValidationReport(
        total_items=len(all_items),
        unique_items=len(kept),
        duplicate_groups=duplicate_groups,
        duplicates_removed=duplicates_removed,
        conflicting_definitions=conflicts,
        evidence_backed_count=evidence_backed_count,
        opinion_count=opinion_count,
        evidence_count=evidence_count,
        mean_confidence=round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
    )

    (channel_dir / "validation_report.json").write_text(
        json.dumps(asdict(report), indent=2), encoding="utf-8"
    )
    (channel_dir / "validated_items.json").write_text(
        json.dumps(kept, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    slug = sys.argv[1] if len(sys.argv) > 1 else "mind_math_money"
    channel_dir = Path(__file__).resolve().parents[2] / "data" / "YOUTUBE DATA" / "channels" / slug
    report = validate_channel(channel_dir)
    print(json.dumps(asdict(report), indent=2, default=str))

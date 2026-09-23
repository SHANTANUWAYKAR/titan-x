"""
Module: report_generator.py
Description: YouTube Knowledge Import Pipeline -- Phase 7, Final Report.
    Aggregates checkpoint.json (Phase 3 transcript stats), validation_report.json
    (Phase 6), and every video's knowledge.json (category/engine
    distribution) into one honest summary. Every number here is read
    from real, already-written pipeline output -- nothing here is
    computed fresh or estimated.
Author: Shantanu Waykar
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from checkpoint import Checkpoint
from engine_mapping import CATEGORY_TO_ENGINE, engine_distribution

logger = logging.getLogger(__name__)


@dataclass
class FinalReport:
    channel_name: str
    channel_slug: str
    generated_at: str
    total_videos_discovered: int
    videos_excluded_non_educational: int
    total_videos_targeted: int
    transcript_success: int
    transcript_unavailable: int
    transcript_failed: int
    transcript_pending: int
    concepts_extracted_total: int
    concepts_extracted_unique: int
    duplicate_groups: int
    conflicting_definitions_found: int
    knowledge_graph_nodes: int
    knowledge_graph_edges: int
    evidence_graph_nodes: int
    evidence_graph_edges: int
    engine_distribution: dict[str, int] = field(default_factory=dict)
    category_distribution: dict[str, int] = field(default_factory=dict)
    mean_confidence: float = 0.0
    opinion_vs_evidence: dict[str, int] = field(default_factory=dict)
    unmapped_categories_needing_new_engine: list[str] = field(default_factory=list)
    suggested_improvements: list[str] = field(default_factory=list)


def _suggest_improvements(category_distribution: dict[str, int], engine_dist: dict[str, int], validation: dict) -> list[str]:
    """Real, data-derived suggestions -- each one is conditioned on an
    actual number from THIS run, not a generic template list."""
    suggestions = []
    if category_distribution.get("risk_management", 0) > 0 and engine_dist.get("e45_risk", 0) > 20:
        suggestions.append(
            f"e45_risk: {engine_dist.get('e45_risk', 0)} risk-management statements extracted -- "
            "worth a follow-up pass cross-referencing these against e45's existing veto rules for any "
            "genuinely new risk heuristic not yet encoded (e.g. specific position-sizing ratios or "
            "circuit-breaker conditions mentioned repeatedly across videos)."
        )
    if category_distribution.get("market_structure", 0) > 0 and engine_dist.get("e07_technical", 0) > 20:
        suggestions.append(
            f"e07_technical: {engine_dist.get('e07_technical', 0)} market-structure/technical statements "
            "extracted -- cross-reference against e07's existing SMC/ICT/Wyckoff detectors for terminology "
            "or setups this channel teaches that aren't yet named/detected there."
        )
    if category_distribution.get("failure_conditions", 0) > 5:
        suggestions.append(
            f"e38_alpha_decay_monitor / e28_stress_testing: {category_distribution['failure_conditions']} "
            "explicit 'this fails when...' statements extracted -- a real, checkable source of candidate "
            "stress-test scenarios or decay triggers, distinct from this platform's own backtested findings."
        )
    if category_distribution.get("psychology", 0) > 20 or category_distribution.get("mental_models", 0) > 10:
        suggestions.append(
            "No dedicated engine on this platform currently models individual trader psychology/discipline "
            f"(as opposed to e09_sentiment's MARKET sentiment) -- {category_distribution.get('psychology', 0) + category_distribution.get('mental_models', 0)} "
            "psychology/mental-model statements were extracted with nowhere platform-specific to go. Worth "
            "a genuine scoping conversation about whether that's in scope for this project, not a forced fit "
            "into an existing engine."
        )
    if validation.get("conflicting_definitions"):
        suggestions.append(
            f"{len(validation['conflicting_definitions'])} term(s) have conflicting definitions across "
            "videos/creators -- flagged in validation_report.json for human review, not auto-resolved."
        )
    return suggestions


def generate_report(channel_dir: Path) -> FinalReport:
    metadata = json.loads((channel_dir / "channel_metadata.json").read_text(encoding="utf-8"))
    checkpoint = Checkpoint(channel_dir / "checkpoint.json")
    cp_summary = checkpoint.summary()

    validation_path = channel_dir / "validation_report.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else {}

    category_distribution: dict[str, int] = {}
    for video_dir in (channel_dir / "videos").iterdir():
        knowledge_path = video_dir / "knowledge.json"
        if not knowledge_path.exists():
            continue
        knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
        for item in knowledge.get("items", []):
            category_distribution[item["category"]] = category_distribution.get(item["category"], 0) + 1
        if knowledge.get("definitions"):
            category_distribution["definitions"] = category_distribution.get("definitions", 0) + len(knowledge["definitions"])

    engine_dist = engine_distribution(category_distribution)
    unmapped_categories = [c for c, (engine_id, _) in CATEGORY_TO_ENGINE.items() if engine_id is None and category_distribution.get(c, 0) > 0]

    kg_path = channel_dir / "knowledge_graph_state.json"
    eg_path = channel_dir / "evidence_graph.json"
    kg_nodes = kg_edges = 0
    eg_nodes = eg_edges = 0
    if kg_path.exists():
        import networkx as nx
        kg_graph = nx.node_link_graph(json.loads(kg_path.read_text(encoding="utf-8")), edges="edges")
        kg_nodes, kg_edges = kg_graph.number_of_nodes(), kg_graph.number_of_edges()
    if eg_path.exists():
        import networkx as nx
        eg_graph = nx.node_link_graph(json.loads(eg_path.read_text(encoding="utf-8")), edges="edges")
        eg_nodes, eg_edges = eg_graph.number_of_nodes(), eg_graph.number_of_edges()

    all_videos = metadata["videos"]
    excluded = sum(1 for v in all_videos if not v.get("likely_educational", True))

    report = FinalReport(
        channel_name=metadata["channel_name"],
        channel_slug=metadata["slug"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_videos_discovered=len(all_videos),
        videos_excluded_non_educational=excluded,
        total_videos_targeted=len(all_videos) - excluded,
        transcript_success=cp_summary["transcript_success"],
        transcript_unavailable=cp_summary["transcript_unavailable"],
        transcript_failed=cp_summary["transcript_failed"],
        transcript_pending=cp_summary["transcript_pending"],
        concepts_extracted_total=validation.get("total_items", cp_summary["total_concepts"]),
        concepts_extracted_unique=validation.get("unique_items", 0),
        duplicate_groups=validation.get("duplicate_groups", 0),
        conflicting_definitions_found=len(validation.get("conflicting_definitions", [])),
        knowledge_graph_nodes=kg_nodes,
        knowledge_graph_edges=kg_edges,
        evidence_graph_nodes=eg_nodes,
        evidence_graph_edges=eg_edges,
        engine_distribution=engine_dist,
        category_distribution=category_distribution,
        mean_confidence=validation.get("mean_confidence", 0.0),
        opinion_vs_evidence={
            "opinion": validation.get("opinion_count", 0),
            "evidence": validation.get("evidence_count", 0),
            "evidence_backed": validation.get("evidence_backed_count", 0),
        },
        unmapped_categories_needing_new_engine=unmapped_categories,
        suggested_improvements=_suggest_improvements(category_distribution, engine_dist, validation),
    )

    reports_dir = channel_dir.parents[1] / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"{metadata['slug']}_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    logger.info("Report written to %s", out_path)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    slug = sys.argv[1] if len(sys.argv) > 1 else "mind_math_money"
    channel_dir = Path(__file__).resolve().parents[2] / "data" / "YOUTUBE DATA" / "channels" / slug
    report = generate_report(channel_dir)
    print(json.dumps(asdict(report), indent=2))

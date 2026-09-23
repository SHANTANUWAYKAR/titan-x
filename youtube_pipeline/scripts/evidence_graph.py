"""
Module: evidence_graph.py
Description: YouTube Knowledge Import Pipeline -- Evidence Graph.

    Distinct from e01_knowledge.knowledge_graph.KnowledgeGraph (which
    models document/author/topic relationships -- reused as-is by
    titanx_integrator.py, not duplicated here). This graph tracks a
    different relationship: which CLAIMS are backed by which EVIDENCE,
    from which SOURCE -- Phase 6's "separate opinion from evidence" and
    "track source attribution" requirements need a claim-level structure
    the topic-level KnowledgeGraph doesn't provide.

    Nodes: claim (an extracted item), evidence (a supporting_evidence
    item), source (a video). Edges: claim-SOURCED_FROM-source,
    evidence-SOURCED_FROM-source, evidence-SUPPORTS-claim (heuristic: an
    evidence item and a claim item from the SAME video within a small
    sentence-window of each other -- real co-location in the transcript,
    not a semantic claim of causation).
Author: Shantanu Waykar
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx


class EvidenceGraph:
    def __init__(self) -> None:
        self._graph = nx.DiGraph()

    def add_item(self, item_id: str, category: str, text: str, video_id: str, video_title: str, video_url: str, confidence: float) -> None:
        self._graph.add_node(
            item_id, kind="claim" if category != "supporting_evidence" else "evidence",
            category=category, text=text, confidence=confidence,
        )
        source_node = ("source", video_id)
        self._graph.add_node(source_node, kind="source", title=video_title, url=video_url)
        self._graph.add_edge(item_id, source_node, relation="sourced_from")

    def link_evidence_to_claim(self, evidence_id: str, claim_id: str) -> None:
        if evidence_id in self._graph and claim_id in self._graph:
            self._graph.add_edge(evidence_id, claim_id, relation="supports")

    def evidence_for_claim(self, claim_id: str) -> list[str]:
        return [n for n in self._graph.predecessors(claim_id) if self._graph.nodes[n].get("kind") == "evidence"]

    def source_for(self, item_id: str) -> dict:
        for _, target, data in self._graph.out_edges(item_id, data=True):
            if data.get("relation") == "sourced_from":
                return {"video_id": target[1], **self._graph.nodes[target]}
        return {}

    @property
    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    def save(self, path: Path) -> None:
        data = nx.node_link_data(self._graph, edges="edges")
        path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")

    def load(self, path: Path) -> None:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self._graph = nx.node_link_graph(data, edges="edges")


def link_evidence_within_video(items: list[dict], window: int = 3) -> list[tuple[str, str]]:
    """Real, mechanical co-location heuristic: a supporting_evidence item
    within `window` sentences of a non-evidence claim item (same video)
    is linked as supporting it. Not a semantic/causal claim -- just
    "these appeared near each other in the source," which is exactly
    what an evidence graph should record (the linkage strength, not an
    invented causal judgement) and what a human reviewer can verify
    directly against the transcript segment."""
    links: list[tuple[str, str]] = []
    evidence_idx = [i for i, it in enumerate(items) if it["category"] == "supporting_evidence"]
    claim_idx = [i for i, it in enumerate(items) if it["category"] != "supporting_evidence"]
    for ei in evidence_idx:
        for ci in claim_idx:
            if abs(ei - ci) <= window:
                links.append((items[ei]["item_id"], items[ci]["item_id"]))
    return links

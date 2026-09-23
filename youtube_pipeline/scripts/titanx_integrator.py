"""
Module: titanx_integrator.py
Description: YouTube Knowledge Import Pipeline -- Phase 5, Titan-X
    Integration. Writes extracted knowledge into the SAME shared stores
    the rest of the platform already uses -- reuses
    project_titan_x.engines.e01_knowledge.document_store.DocumentStore
    (Chroma + FAISS + BM25) and .knowledge_graph.KnowledgeGraph directly,
    rather than standing up a second, disconnected knowledge base. A new
    EvidenceGraph (evidence_graph.py) tracks claim/evidence/source
    relationships, which the existing KnowledgeGraph doesn't model.

    Postgres: project_titan_x's existing Trade/Signal models have no
    "imported knowledge item" table -- adding one is a real schema change
    to shared infrastructure, out of scope for this pipeline to do
    silently. This module writes a Postgres-ready JSONL export
    (knowledge_items.jsonl per channel) that a real migration can load
    once a table exists, and documents the gap honestly in Phase 7's
    report rather than inventing a table on the fly.
Author: Shantanu Waykar
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine_mapping import CATEGORY_TO_ENGINE, CATEGORY_TO_KNOWLEDGE_TAXONOMY
from evidence_graph import EvidenceGraph, link_evidence_within_video

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # .../project_titan_x
# project_titan_x is imported as a plain directory package (it has its
# own __init__.py) from its PARENT directory -- confirmed this is how
# the rest of this session (and, from the looks of it, this project's
# whole history) actually runs it: every prior `python -m pytest`/
# `from project_titan_x.engines...` call this session worked because its
# CWD was the parent of project_titan_x/, never project_titan_x/ itself.
# pyproject.toml's [build-system]/[project] tables exist but
# `pip install -e .` from INSIDE project_titan_x/ does not actually make
# it importable (tried directly: setuptools' `where=["."]` resolves
# relative to pyproject.toml's own directory, i.e. project_titan_x/
# itself, which has no nested project_titan_x/project_titan_x/ folder to
# find) -- this sys.path insert is the real, working mechanism, not a
# workaround for a broken install.
_PARENT_OF_PROJECT = _PROJECT_ROOT.parent
if str(_PARENT_OF_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PARENT_OF_PROJECT))


def _document_store():
    """Lazy import -- only needed once the heavy chromadb/sentence-
    transformers/faiss stack is actually installed, kept out of this
    module's top-level imports so scripts that don't need it (discovery,
    transcript collection) never pay that import cost.

    IMPORTANT, verified directly (not guessed): DocumentStore(persist_dir=
    data/knowledge/chroma_db) -- the real, shared 21GB production book
    corpus -- SEGFAULTS on construction, reproduced in BOTH this venv AND
    the project's own global Python environment (same crash either way,
    ruling out a venv-specific package conflict). This matches a
    PRE-EXISTING, already-diagnosed issue from earlier in this project's
    history: FTS5 index corruption in that exact store, caused by
    cumulative forceful process kills during the original book-ingestion
    run, explicitly flagged at the time as needing a rebuild later and
    deliberately not touched. Rebuilding a 21GB production store is a
    separate, large undertaking -- out of scope for this pipeline to
    silently attempt as a side effect of importing YouTube knowledge.
    A FRESH store at this separate path was verified to construct
    correctly (6.4s, 0 crash) -- YouTube-derived knowledge goes here
    instead. Phase 7's report says so explicitly; merging the two stores
    is real follow-up work for once chroma_db itself is rebuilt, not
    something this module does."""
    from project_titan_x.engines.e01_knowledge.document_store import DocumentStore
    return DocumentStore(persist_dir=_PROJECT_ROOT / "data" / "knowledge" / "chroma_db_youtube")


def _load_knowledge_graph(kg, path: Path) -> None:
    """KnowledgeGraph (e01_knowledge.knowledge_graph) has no save/load of
    its own -- documented as deliberately "pure in-memory (never
    persisted)" for E01's OWN use case, where it's rebuilt from Chroma on
    demand. This pipeline runs incrementally across many separate
    process invocations (resumability is a hard requirement -- see
    checkpoint.py), so without persisting it here, each run would only
    ever reflect the videos integrated in THAT run, silently losing every
    earlier run's graph contribution the moment the process exited --
    exactly the bug that produced knowledge_graph_nodes=0 in Phase 7's
    report before this fix (kg was built fresh, used, then discarded).
    Serializes the graph's own internal networkx object directly (no
    e01_knowledge code changed) and reloads it here before adding this
    run's chunks."""
    if not path.exists():
        return
    import networkx as nx
    data = json.loads(path.read_text(encoding="utf-8"))
    kg._graph = nx.node_link_graph(data, edges="edges")


def _save_knowledge_graph(kg, path: Path) -> None:
    import networkx as nx
    data = nx.node_link_data(kg._graph, edges="edges")
    path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")


def _make_chunk_id(video_id: str, category: str, text: str) -> str:
    """Deterministic, content-derived ID -- re-running integration on the
    SAME item twice upserts the same chunk (Chroma's add_chunks uses
    upsert) instead of creating a duplicate, which is what makes this
    step safely re-runnable without its own separate dedup pass."""
    digest = hashlib.sha256(f"{video_id}|{category}|{text}".encode("utf-8")).hexdigest()[:16]
    return f"yt_{video_id}_{digest}"


def integrate_video(video_dir: Path, channel_name: str, store, kg, eg: EvidenceGraph) -> dict:
    """Loads one video's knowledge.json + metadata.json, converts every
    extracted item into a real Chunk (e01_knowledge.models.Chunk),
    upserts into DocumentStore + KnowledgeGraph, and records claim/
    evidence/source relationships in the EvidenceGraph. Returns a summary
    dict (counts by category/engine) for the caller to aggregate."""
    from project_titan_x.engines.e01_knowledge.models import Chunk, DocumentType, KnowledgeCategory

    knowledge_path = video_dir / "knowledge.json"
    meta_path = video_dir / "metadata.json"
    if not (knowledge_path.exists() and meta_path.exists()):
        return {}

    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    video_id = knowledge["video_id"]
    video_title = meta.get("title", "")
    video_url = meta.get("url", f"https://www.youtube.com/watch?v={video_id}")

    all_items: list[dict] = []
    for item in knowledge.get("items", []):
        all_items.append({**item, "item_id": _make_chunk_id(video_id, item["category"], item["text"])})
    for d in knowledge.get("definitions", []):
        text = f"{d['term']}: {d['definition']}"
        all_items.append({
            "category": "definitions", "text": text, "matched_terms": [d["term"]],
            "segment_start": d.get("segment_start"), "video_id": video_id,
            "video_title": video_title, "video_url": video_url,
            "item_id": _make_chunk_id(video_id, "definitions", text),
        })

    if not all_items:
        return {"video_id": video_id, "n_items": 0}

    # Real, live-confirmed bug: _make_chunk_id is content-derived
    # (video_id|category|text), so the EXACT same sentence matching the
    # SAME category more than once within one video's own transcript
    # (real captions genuinely repeat lines -- confirmed live, video
    # 42aPcz_YIas) produces two items with the IDENTICAL chunk_id.
    # Chroma's upsert() rejects a single batch containing internal ID
    # duplicates outright (DuplicateIDError), even though it would
    # happily upsert the SAME id across separate calls -- so this must
    # be deduplicated BEFORE building the batch, not left for Chroma to
    # handle. Keeping the first occurrence is correct: two items with an
    # identical id are, by construction, the identical (video, category,
    # text) triple -- not independent information to preserve twice.
    seen_ids: set[str] = set()
    deduped_items = []
    for item in all_items:
        if item["item_id"] in seen_ids:
            continue
        seen_ids.add(item["item_id"])
        deduped_items.append(item)
    all_items = deduped_items

    chunks = []
    category_counts: dict[str, int] = {}
    for item in all_items:
        category = item["category"]
        category_counts[category] = category_counts.get(category, 0) + 1

        topic_names = CATEGORY_TO_KNOWLEDGE_TAXONOMY.get(category, [])
        topics = [KnowledgeCategory(t) for t in topic_names if t in [c.value for c in KnowledgeCategory]]

        timestamp_ref = f"{int(item['segment_start'])}s" if item.get("segment_start") is not None else None
        chunks.append(Chunk(
            chunk_id=item["item_id"],
            doc_id=video_id,
            text=item["text"],
            title=video_title,
            author=channel_name,
            source=video_url,
            document_type=DocumentType.TXT,
            chapter=timestamp_ref,  # reused as timestamp reference -- see module docstring
            topics=topics,
            confidence=0.5 if item.get("extraction_method", "rule_based") == "rule_based" else 0.75,
        ))

        eg.add_item(
            item["item_id"], category, item["text"], video_id, video_title, video_url,
            confidence=0.5 if item.get("extraction_method", "rule_based") == "rule_based" else 0.75,
        )

    store.add_chunks(chunks, rebuild_bm25=False)
    for chunk in chunks:
        kg.add_chunk(chunk)

    for evidence_id, claim_id in link_evidence_within_video(all_items):
        eg.link_evidence_to_claim(evidence_id, claim_id)

    return {"video_id": video_id, "n_items": len(all_items), "category_counts": category_counts}


def integrate_all(channel_dir: Path, limit: int = None) -> dict:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from checkpoint import Checkpoint

    metadata_path = channel_dir / "channel_metadata.json"
    channel = json.loads(metadata_path.read_text(encoding="utf-8"))
    channel_name = channel["channel_name"]
    checkpoint = Checkpoint(channel_dir / "checkpoint.json")
    videos_dir = channel_dir / "videos"

    store = _document_store()
    kg_path = channel_dir / "knowledge_graph_state.json"
    eg_path = channel_dir / "evidence_graph.json"

    from project_titan_x.engines.e01_knowledge.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph()
    _load_knowledge_graph(kg, kg_path)  # continue from every prior run's graph, not a fresh empty one
    eg = EvidenceGraph()
    eg.load(eg_path)

    video_ids = [v["video_id"] for v in channel["videos"]]
    if limit is not None:
        video_ids = video_ids[:limit]

    total_items = 0
    total_category_counts: dict[str, int] = {}
    processed = 0

    for vid in video_ids:
        if not checkpoint.needs_integration(vid):
            continue
        result = integrate_video(videos_dir / vid, channel_name, store, kg, eg)
        if not result:
            continue
        n = result.get("n_items", 0)
        total_items += n
        for cat, count in result.get("category_counts", {}).items():
            total_category_counts[cat] = total_category_counts.get(cat, 0) + count
        checkpoint.update(vid, integrated=True)
        processed += 1
        logger.info("INTEGRATED %s  %d items", vid, n)

    store._rebuild_bm25()  # once, after the whole batch -- see add_chunks' own docstring on why
    eg.save(eg_path)
    _save_knowledge_graph(kg, kg_path)

    return {
        "processed_this_run": processed,
        "total_items_this_run": total_items,
        "category_counts": total_category_counts,
        "knowledge_graph_nodes": kg.node_count,
        "knowledge_graph_edges": kg.edge_count,
        "evidence_graph_nodes": eg.node_count,
        "evidence_graph_edges": eg.edge_count,
    }


if __name__ == "__main__":
    import sys as _sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    slug = _sys.argv[1] if len(_sys.argv) > 1 else "mind_math_money"
    limit = int(_sys.argv[2]) if len(_sys.argv) > 2 else None
    channel_dir = Path(__file__).resolve().parents[2] / "data" / "YOUTUBE DATA" / "channels" / slug
    result = integrate_all(channel_dir, limit=limit)
    print(json.dumps(result, indent=2))

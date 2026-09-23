"""
Module: engine.py
Description: Engine 01 — Global Knowledge Intelligence Library.

    Two complementary subsystems live here:
    1. Trader-profile knowledge base (PostgreSQL + Qdrant/FAISS via
       core.vector_store) -- pre-existing, unchanged by the additions below.
    2. Document-ingestion RAG pipeline (PDF/EPUB/DOCX/TXT/HTML/Markdown ->
       structure-aware chunking -> topic classification -> Chroma+FAISS+BM25
       hybrid search -> knowledge graph), exposed via the async
       search/retrieve/answer/related_topics/similar_chunks/get_sources/
       get_citations API required across the rest of the platform.
Author: Shantanu Waykar
Version: 2.0.0
Last Modified: 2026-07-15
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from project_titan_x.core.database import TraderProfile, get_db_session
from project_titan_x.core.vector_store import VectorStoreClient
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.document_store import CombinedDocumentStore, DocumentStore
from project_titan_x.engines.e01_knowledge.ingestion import IngestionPipeline

logger = logging.getLogger(__name__)


class KnowledgeEngine(BaseEngine):
    """
    Global Knowledge Intelligence Engine.

    Stores trader frameworks in PostgreSQL + Qdrant.
    Supports semantic search and knowledge graph queries.
    """

    engine_id = "e01_knowledge"
    engine_name = "Knowledge Intelligence Engine"
    version = "1.0.0"

    def __init__(
        self,
        knowledge_dir: Optional[Path] = None,
        data_root: Optional[Path] = None,
        document_store: Optional[DocumentStore] = None,
    ) -> None:
        super().__init__()
        self.knowledge_dir = knowledge_dir or Path("data/knowledge")
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.vector_store = VectorStoreClient()

        # Document-ingestion RAG pipeline. Constructed eagerly (not lazily
        # in initialize()) so a caller can ingest_document()/ingest_all()
        # in tests without going through the full engine lifecycle -- but
        # the heavy embedding-model load already happened once, cached, in
        # core.vector_store's _get_embedding_model(), so this is cheap.
        # NOT `document_store or DocumentStore()`: DocumentStore defines
        # __len__, so an empty-but-real instance (0 chunks so far) is
        # falsy, and `or` would silently discard it in favor of a brand
        # new store the instant it's passed in with nothing ingested yet.
        #
        # Real bug found 2026-07-29: this used to construct `DocumentStore()`
        # with no persist_dir at all, silently ignoring knowledge_dir entirely
        # -- every caller passing knowledge_dir=some_isolated_path (expecting
        # isolation, e.g. a test's tmp_path) actually still got the real
        # production store at DocumentStore's own default path. Harmless at
        # small scale, but surfaced as a real segfault once the production
        # corpus passed ~1.7M chunks (the known chromadb Rust .get() crash,
        # see document_store.py's _rehydrate docstring) and a test tried to
        # rehydrate against it. Every other test call site already sidesteps
        # this by passing an explicit document_store=; this makes
        # knowledge_dir itself actually do what its name promises.
        self.document_store = (
            document_store if document_store is not None else DocumentStore(persist_dir=self.knowledge_dir / "chroma_db")
        )
        # Added 2026-08-05: transparently merges in the separately-stored
        # YouTube-extracted knowledge (data/knowledge/chroma_db_youtube --
        # see youtube_pipeline/scripts/titanx_integrator.py) at query time,
        # via CombinedDocumentStore -- see that class's own docstring for
        # why this is a query-time merge, not a write into the main store.
        # Only applied to the DEFAULT store (an explicitly injected
        # document_store, e.g. from a test, is left exactly as passed in,
        # matching every other test-isolation guarantee this constructor
        # already provides). ingestion still targets self.document_store
        # directly (before wrapping) so new ingestion writes only ever go
        # to the main store, never the read-only secondary.
        self.ingestion = IngestionPipeline(data_root=data_root, store=self.document_store)
        if document_store is None:
            youtube_store_dir = self.knowledge_dir / "chroma_db_youtube"
            if youtube_store_dir.exists():
                try:
                    youtube_store = DocumentStore(persist_dir=youtube_store_dir)
                    self.document_store = CombinedDocumentStore(self.document_store, youtube_store)
                except Exception as e:
                    logger.warning("YouTube knowledge store unavailable (%s) -- continuing with book corpus only", e)
            # Added 2026-09-14: same pattern as YouTube above, for the same
            # reason -- the main book collection's writes are confirmed
            # broken past its real scale (see scripts/training/
            # ingest_book_batch.py's module docstring and document_store.py's
            # CombinedDocumentStore docstring), so books ingested from this
            # point on land in this second, small store instead. Nested
            # (CombinedDocumentStore wrapping a CombinedDocumentStore) rather
            # than widening CombinedDocumentStore to N-ary -- its interface
            # (hybrid_search, __len__, __getattr__) already works unchanged
            # against a secondary that is itself a CombinedDocumentStore, so
            # this is the smallest change that merges all three stores at
            # query time.
            overflow_store_dir = self.knowledge_dir / "chroma_db_overflow"
            if overflow_store_dir.exists():
                try:
                    overflow_store = DocumentStore(persist_dir=overflow_store_dir)
                    self.document_store = CombinedDocumentStore(self.document_store, overflow_store)
                except Exception as e:
                    logger.warning("Overflow book knowledge store unavailable (%s) -- continuing without it", e)

    def initialize(self) -> EngineResult:
        """Initialize knowledge engine and vector store."""
        try:
            self._set_status(EngineStatus.RUNNING)
            connected = self.vector_store.connect()
            seed_path = self.knowledge_dir / "traders_seed.json"
            if seed_path.exists():
                self._load_seed_data(seed_path)
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                message="Knowledge Engine initialized",
                metadata={
                    "vector_store": connected,
                    "vector_store_backend": self.vector_store.backend,
                    "document_chunks_indexed": len(self.document_store),
                },
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def health_check(self) -> EngineResult:
        """Health check."""
        return EngineResult(success=True, message="Healthy")

    def add_trader_profile(self, profile: dict[str, Any]) -> EngineResult:
        """
        Add or update a trader knowledge profile.

        Args:
            profile: Trader profile dict with name, category, philosophy, etc.

        Returns:
            EngineResult with trader ID.
        """
        try:
            name = profile.get("name", "")
            if not name:
                raise ValueError("Trader name is required")

            text_for_embedding = self._profile_to_text(profile)
            embedding_id = self.vector_store.upsert(
                text=text_for_embedding,
                metadata={"name": name, "category": profile.get("category", "")},
            )

            with get_db_session() as session:
                existing = session.query(TraderProfile).filter_by(name=name).first()
                if existing:
                    for key, value in profile.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                    existing.embedding_id = embedding_id
                    trader_id = existing.id
                else:
                    trader = TraderProfile(
                        name=name,
                        category=profile.get("category", ""),
                        biography=profile.get("biography", ""),
                        philosophy=profile.get("philosophy", {}),
                        frameworks=profile.get("frameworks", {}),
                        success_patterns=profile.get("success_patterns", {}),
                        failure_patterns=profile.get("failure_patterns", {}),
                        regime_suitability=profile.get("regime_suitability", {}),
                        embedding_id=embedding_id,
                    )
                    session.add(trader)
                    session.flush()
                    trader_id = trader.id

            return EngineResult(
                success=True,
                data={"trader_id": trader_id, "name": name},
                message=f"Trader profile saved: {name}",
            )
        except Exception as e:
            logger.error("Failed to add trader profile: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def search_knowledge(self, query: str, limit: int = 10) -> EngineResult:
        """
        Semantic search across trader knowledge base.

        Args:
            query: Natural language query.
            limit: Max results.

        Returns:
            EngineResult with matching knowledge documents.
        """
        results = self.vector_store.search(query, limit=limit)
        return EngineResult(
            success=True,
            data=results,
            message=f"Found {len(results)} results for: {query}",
        )

    def get_trader(self, name: str) -> EngineResult:
        """Get trader profile by name."""
        try:
            with get_db_session() as session:
                trader = session.query(TraderProfile).filter_by(name=name).first()
                if not trader:
                    return EngineResult(success=False, message=f"Trader not found: {name}")
                return EngineResult(
                    success=True,
                    data={
                        "id": trader.id,
                        "name": trader.name,
                        "category": trader.category,
                        "biography": trader.biography,
                        "philosophy": trader.philosophy,
                        "frameworks": trader.frameworks,
                        "success_patterns": trader.success_patterns,
                        "failure_patterns": trader.failure_patterns,
                        "regime_suitability": trader.regime_suitability,
                    },
                )
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def list_traders(self, category: Optional[str] = None) -> EngineResult:
        """List all trader profiles, optionally filtered by category."""
        try:
            with get_db_session() as session:
                query = session.query(TraderProfile)
                if category:
                    query = query.filter_by(category=category)
                traders = query.all()
                return EngineResult(
                    success=True,
                    data=[
                        {"id": t.id, "name": t.name, "category": t.category}
                        for t in traders
                    ],
                    message=f"Found {len(traders)} traders",
                )
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def analyze_framework_conflict(
        self, framework_a: str, framework_b: str
    ) -> EngineResult:
        """
        Analyze conflict between two trading frameworks.

        Args:
            framework_a: First framework name (e.g., 'Warren Buffett').
            framework_b: Second framework name (e.g., 'George Soros').

        Returns:
            EngineResult with conflict analysis.
        """
        result_a = self.get_trader(framework_a)
        result_b = self.get_trader(framework_b)
        if not result_a.success or not result_b.success:
            return EngineResult(success=False, message="One or both traders not found")

        a, b = result_a.data, result_b.data
        conflicts = []
        synergies = []

        a_regimes = set(a.get("regime_suitability", {}).get("best", []))
        b_regimes = set(b.get("regime_suitability", {}).get("best", []))
        overlap = a_regimes & b_regimes
        if overlap:
            synergies.append(f"Both excel in: {', '.join(overlap)}")
        a_worst = set(a.get("regime_suitability", {}).get("worst", []))
        b_best = set(b.get("regime_suitability", {}).get("best", []))
        if a_worst & b_best:
            conflicts.append(
                f"{framework_a} avoids regimes where {framework_b} thrives"
            )

        return EngineResult(
            success=True,
            data={"conflicts": conflicts, "synergies": synergies},
            message=f"Conflict analysis: {framework_a} vs {framework_b}",
        )

    # ------------------------------------------------------------------
    # Document-ingestion RAG API (async: internally offloads the CPU-bound
    # embedding/Chroma/FAISS/BM25 work to a thread rather than blocking the
    # event loop, since none of that work is actually I/O-bound).
    # ------------------------------------------------------------------

    async def ingest_document(self, path: Path) -> EngineResult:
        """Ingest a single document. Only paths under data/{books,research,
        annual_reports,sec_filings,trading_journals,notes} are accepted --
        see ingestion.IngestionPipeline._validate_path."""
        try:
            chunks = await asyncio.to_thread(self.ingestion.ingest_file, path)
            return EngineResult(
                success=True,
                data=chunks,
                message=f"Ingested {Path(path).name}: {len(chunks)} chunk(s)",
                metadata={"n_chunks": len(chunks)},
            )
        except Exception as e:
            logger.error("Document ingestion failed for %s: %s", path, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    async def ingest_all(self) -> EngineResult:
        """Ingest every supported document currently in the allowed directories."""
        results = await asyncio.to_thread(self.ingestion.ingest_all)
        n_ok = sum(1 for r in results.values() if r.get("success"))
        return EngineResult(
            success=True,
            data=results,
            message=f"Ingested {n_ok}/{len(results)} document(s)",
            metadata={"n_documents": len(results), "n_succeeded": n_ok},
        )

    async def search(
        self, query: str, limit: int = 10, metadata_filter: Optional[dict[str, Any]] = None
    ) -> EngineResult:
        """General-purpose hybrid search (vector + keyword + metadata) over
        every ingested chunk. Returns full ranked SearchResult objects."""
        results = await asyncio.to_thread(
            self.document_store.hybrid_search, query, limit, 0.6, 0.4, metadata_filter
        )
        return EngineResult(
            success=True,
            data=results,
            message=f"Found {len(results)} result(s) for: {query}",
            metadata={"n_results": len(results)},
        )

    async def retrieve(
        self, query: str, limit: int = 5, metadata_filter: Optional[dict[str, Any]] = None
    ) -> EngineResult:
        """Retrieval for another engine's decision-making context: the top
        chunks for `query`, concatenated into one context block with a
        citation trail -- what generate_signal()-style callers should use
        before producing output (see requirement #16)."""
        results = await asyncio.to_thread(
            self.document_store.hybrid_search, query, limit, 0.6, 0.4, metadata_filter
        )
        context = "\n\n---\n\n".join(
            f"[{r.chunk.title}, p.{r.chunk.page or '?'}] {r.chunk.text}" for r in results
        )
        return EngineResult(
            success=True,
            data={"context": context, "results": results, "citations": [r.citation.to_dict() for r in results]},
            message=f"Retrieved {len(results)} chunk(s) for context",
            metadata={"n_results": len(results)},
        )

    async def answer(self, query: str, limit: int = 5) -> EngineResult:
        """Extractive answer: the single best-matching chunk's text, plus
        supporting citations from the next-best matches. This platform has
        no LLM wired in, so 'answer' here means 'the most relevant passage
        found', not a synthesized/generated sentence -- an honest scope
        limit rather than a fabricated-sounding summary."""
        results = await asyncio.to_thread(self.document_store.hybrid_search, query, limit, 0.6, 0.4, None)
        if not results:
            return EngineResult(success=True, data=None, message="No relevant knowledge found")
        best = results[0]
        return EngineResult(
            success=True,
            data={
                "answer": best.chunk.text,
                "confidence": best.score,
                "citation": best.citation.to_dict(),
                "supporting_citations": [r.citation.to_dict() for r in results[1:]],
            },
            message="Extractive answer (best-matching passage, not LLM-generated)",
        )

    async def related_topics(self, topic: str, limit: int = 5) -> EngineResult:
        """Topics that most frequently co-occur with `topic` across ingested documents."""
        related = await asyncio.to_thread(self.ingestion.graph.related_topics, topic, limit)
        return EngineResult(
            success=True,
            data=related,
            message=f"Found {len(related)} related topic(s) for {topic}",
        )

    async def similar_chunks(self, chunk_id: str, limit: int = 5) -> EngineResult:
        """Chunks most semantically similar to an already-ingested chunk."""
        results = await asyncio.to_thread(self.document_store.similar_chunks, chunk_id, limit)
        return EngineResult(success=True, data=results, message=f"Found {len(results)} similar chunk(s)")

    async def get_sources(self, topic: Optional[str] = None) -> EngineResult:
        """Document titles covering `topic`, or every distinct ingested
        source if no topic is given."""
        if topic:
            sources = await asyncio.to_thread(self.ingestion.graph.sources_for_topic, topic)
        else:
            chunks = await asyncio.to_thread(self.document_store.all_chunks)
            sources = sorted({c.title for c in chunks})
        return EngineResult(success=True, data=sources, message=f"Found {len(sources)} source(s)")

    async def get_citations(self, query: str, limit: int = 5) -> EngineResult:
        """Citation trail (title/author/source/page/chapter/excerpt) for
        the top results of `query`, without the full chunk text."""
        results = await asyncio.to_thread(self.document_store.hybrid_search, query, limit, 0.6, 0.4, None)
        citations = [r.citation.to_dict() for r in results]
        return EngineResult(success=True, data=citations, message=f"Found {len(citations)} citation(s)")

    def _load_seed_data(self, path: Path) -> None:
        """Load seed trader data from JSON file, skipping any trader whose
        name already has a persisted profile.

        This used to call add_trader_profile() unconditionally for every
        seed trader on EVERY server startup -- each call re-embeds the
        profile text regardless of whether anything changed, which forces
        the (otherwise lazily-loaded) sentence-transformers model to
        import+load synchronously during initialize(). Measured cost:
        ~23s of a ~33s cold start, paid on every single restart even
        though this seed data is effectively static reference content.
        Skipping already-persisted names means a normal restart triggers
        zero embeddings, so that cost only lands on whoever actually
        exercises live semantic search, not on every dashboard launch.
        Trade-off: editing an existing trader's entry in the seed JSON
        no longer updates it automatically -- delete that trader's row
        from Postgres (or add a new name) to force a re-seed.

        Real bug found and fixed 2026-07-20: when Postgres is unreachable,
        the existence check below used to fall back to `existing_names =
        set()` -- i.e. "assume nothing is seeded yet" -- which then tried
        add_trader_profile() for EVERY seed trader individually. Each of
        those calls opens its OWN db session (see add_trader_profile) and
        pays the full ~2s connect_timeout before failing, since Postgres
        being unreachable is not a per-row problem, it's a can't-connect-
        at-all problem -- every one of those N attempts was guaranteed to
        fail identically. With ~70 seed traders this turned a single
        Postgres-down startup into a ~145s hang (measured directly this
        session) instead of a fast, honest skip. Now: if the existence
        check itself fails, seeding is skipped ENTIRELY for this run (not
        silently marked done -- just deferred) rather than blindly
        retrying a doomed connection dozens of times.
        """
        with open(path, encoding="utf-8") as f:
            traders = json.load(f)

        try:
            with get_db_session() as session:
                existing_names = {row.name for row in session.query(TraderProfile.name).all()}
        except Exception as e:
            logger.warning(
                "Could not check existing trader profiles (%s) -- Postgres appears unreachable, "
                "skipping seed-data loading entirely for this run (will retry on next startup once "
                "the database is reachable, not silently marked as already loaded)",
                e,
            )
            return

        to_load = [t for t in traders if t.get("name", "") not in existing_names]
        skipped = len(traders) - len(to_load)
        loaded = sum(1 for t in to_load if self.add_trader_profile(t).success)

        if loaded < len(to_load):
            logger.warning(
                "Only %d/%d new trader profiles from seed data actually persisted (%d already present, skipped) -- "
                "check Postgres connectivity (see the per-profile error logged above)",
                loaded, len(to_load), skipped,
            )
        else:
            logger.info("Loaded %d new trader profile(s) from seed data (%d already present, skipped)", loaded, skipped)

    @staticmethod
    def _profile_to_text(profile: dict[str, Any]) -> str:
        """Convert profile to searchable text."""
        parts = [
            profile.get("name", ""),
            profile.get("category", ""),
            profile.get("biography", ""),
            str(profile.get("philosophy", {})),
            str(profile.get("frameworks", {})),
        ]
        return " ".join(parts)

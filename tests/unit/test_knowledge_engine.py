"""
Module: test_knowledge_engine.py
Description: Unit tests for Engine 01's document-ingestion RAG pipeline --
    loaders (real PDF/EPUB/DOCX/TXT/HTML/Markdown fixtures, not mocks),
    structure detection, chunking, classification, the hybrid document
    store, the knowledge graph, ingestion scope enforcement, and the
    async KnowledgeEngine API.
Author: Shantanu Waykar
Version: 1.0.0
"""

from pathlib import Path

import docx as docx_lib
import pymupdf
import pytest
from ebooklib import epub

from project_titan_x.engines.e01_knowledge import DocumentType, KnowledgeCategory
from project_titan_x.engines.e01_knowledge.chunking import chunk_document
from project_titan_x.engines.e01_knowledge.classification import TopicClassifier
from project_titan_x.engines.e01_knowledge.document_store import DocumentStore
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e01_knowledge.ingestion import (
    DocumentOutsideAllowedDirectoryError,
    IngestionPipeline,
)
from project_titan_x.engines.e01_knowledge.knowledge_graph import KnowledgeGraph
from project_titan_x.engines.e01_knowledge.loaders import (
    load_docx,
    load_epub,
    load_html,
    load_markdown,
    load_pdf,
    load_txt,
)
from project_titan_x.engines.e01_knowledge.models import Chunk, DocumentMetadata, StructuralElement, StructureType
from project_titan_x.engines.e01_knowledge.structure import (
    is_probable_figure_caption,
    is_probable_formula,
    is_probable_heading,
    segment_plain_text,
)

# ---------------------------------------------------------------------------
# structure.py
# ---------------------------------------------------------------------------


def test_is_probable_heading_accepts_short_titlecase_line():
    assert is_probable_heading("Risk Management Fundamentals")


def test_is_probable_heading_rejects_full_sentences():
    assert not is_probable_heading("This is a full sentence that ends with a period.")


def test_is_probable_formula_detects_latex_delimiters():
    assert is_probable_formula(r"$E = mc^2$")


def test_is_probable_formula_detects_symbol_density():
    assert is_probable_formula("V = P0 * (1 + r)^n / (1 - t)")


def test_is_probable_formula_rejects_prose():
    assert not is_probable_formula("The market moved sharply higher today on strong earnings.")


def test_is_probable_figure_caption():
    assert is_probable_figure_caption("Figure 3: Weekly candlestick chart")
    assert not is_probable_figure_caption("The chart above shows a clear uptrend.")


def test_segment_plain_text_tracks_chapter_across_paragraphs():
    text = "Chapter 1: Introduction\n\nThis is the first paragraph.\n\nThis is the second paragraph."
    elements = segment_plain_text(text)
    chapter_elements = [e for e in elements if e.kind == StructureType.CHAPTER]
    paragraph_elements = [e for e in elements if e.kind == StructureType.PARAGRAPH]
    assert len(chapter_elements) == 1
    assert all(e.chapter == "Chapter 1: Introduction" for e in paragraph_elements)


# ---------------------------------------------------------------------------
# loaders.py -- real fixture files, not mocks
# ---------------------------------------------------------------------------


def test_load_txt_extracts_chapters_and_figure_caption(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text(
        "Chapter 1: Risk Management\n\n"
        "Position sizing determines how much capital to risk per trade.\n\n"
        "Figure 1: Position sizing chart.",
        encoding="utf-8",
    )
    loaded = load_txt(path)
    kinds = [e.kind for e in loaded.elements]
    assert StructureType.CHAPTER in kinds
    assert StructureType.FIGURE_CAPTION in kinds
    assert loaded.total_pages is None


def test_load_markdown_extracts_headings_and_table(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(
        "# Options Trading\n\n"
        "Options traders track delta and gamma.\n\n"
        "## Implied Volatility\n\n"
        "IV reflects expected future movement.\n\n"
        "| Greek | Meaning |\n|---|---|\n| Delta | Price sensitivity |\n",
        encoding="utf-8",
    )
    loaded = load_markdown(path)
    kinds = [e.kind for e in loaded.elements]
    assert StructureType.CHAPTER in kinds  # h1
    assert StructureType.HEADING in kinds  # h2
    assert StructureType.TABLE in kinds


def test_load_html_extracts_structure(tmp_path):
    path = tmp_path / "doc.html"
    path.write_text(
        "<html><head><title>Macro Outlook</title></head><body>"
        "<h1>Macroeconomics</h1>"
        "<p>Central bank rate decisions drive currency valuations globally.</p>"
        "<table><tr><th>Indicator</th><th>Impact</th></tr><tr><td>CPI</td><td>High</td></tr></table>"
        "</body></html>",
        encoding="utf-8",
    )
    loaded = load_html(path)
    assert loaded.title == "Macro Outlook"
    kinds = [e.kind for e in loaded.elements]
    assert StructureType.CHAPTER in kinds
    assert StructureType.TABLE in kinds


def test_load_docx_extracts_heading_levels_and_table(tmp_path):
    path = tmp_path / "doc.docx"
    document = docx_lib.Document()
    document.core_properties.title = "Wyckoff Guide"
    document.core_properties.author = "Test Author"
    document.add_heading("Wyckoff Method", level=1)
    document.add_paragraph("Accumulation and distribution describe the composite man's behavior.")
    document.add_heading("Springs", level=2)
    document.add_paragraph("A spring is a false breakdown that traps sellers.")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Phase"
    table.cell(0, 1).text = "Stopping action"
    document.save(str(path))

    loaded = load_docx(path)
    assert loaded.title == "Wyckoff Guide"
    assert loaded.author == "Test Author"
    kinds = [e.kind for e in loaded.elements]
    assert StructureType.CHAPTER in kinds
    assert StructureType.HEADING in kinds
    assert StructureType.TABLE in kinds
    assert loaded.total_pages is None  # DOCX has no fixed pagination in the document model


def test_load_epub_extracts_chapter(tmp_path):
    path = tmp_path / "doc.epub"
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Elliott Wave Principles")
    book.add_author("Wave Author")
    chapter = epub.EpubHtml(title="Wave Theory", file_name="chap1.xhtml", lang="en")
    chapter.content = "<h1>Wave Theory</h1><p>Impulse waves move with the trend in five sub-waves.</p>"
    book.add_item(chapter)
    book.toc = (chapter,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)

    loaded = load_epub(path)
    assert loaded.title == "Elliott Wave Principles"
    assert loaded.author == "Wave Author"
    assert any(e.kind == StructureType.CHAPTER for e in loaded.elements)
    assert loaded.total_pages is None  # EPUB has no fixed pagination either


def test_load_pdf_extracts_metadata_and_heading(tmp_path):
    path = tmp_path / "doc.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Candlestick Patterns", fontsize=20)
    page.insert_text((72, 110), "A doji forms when open and close prices are nearly equal.", fontsize=11)
    pdf.set_metadata({"title": "Candlestick Guide", "author": "PDF Author"})
    pdf.save(str(path))
    pdf.close()

    loaded = load_pdf(path)
    assert loaded.title == "Candlestick Guide"
    assert loaded.author == "PDF Author"
    assert loaded.total_pages == 1
    assert any(e.kind == StructureType.HEADING for e in loaded.elements)


# ---------------------------------------------------------------------------
# chunking.py
# ---------------------------------------------------------------------------


def _doc_meta(doc_id="doc1") -> DocumentMetadata:
    return DocumentMetadata(doc_id=doc_id, title="T", author="A", source="s", document_type=DocumentType.TXT)


def test_chunk_document_keeps_table_as_dedicated_chunk():
    elements = [
        StructuralElement(kind=StructureType.PARAGRAPH, text="Intro paragraph." * 5, page=1),
        StructuralElement(kind=StructureType.TABLE, text="A | B\n1 | 2", page=1),
        StructuralElement(kind=StructureType.PARAGRAPH, text="Closing paragraph." * 5, page=2),
    ]
    chunks = chunk_document(elements, _doc_meta())
    table_chunks = [c for c in chunks if c.contains_table]
    assert len(table_chunks) == 1
    assert table_chunks[0].text == "A | B\n1 | 2"


def test_chunk_document_splits_on_target_size():
    long_paragraph = StructuralElement(kind=StructureType.PARAGRAPH, text="x" * 1200, page=1)
    chunks = chunk_document([long_paragraph], _doc_meta())
    assert len(chunks) == 1
    assert len(chunks[0].text) >= 1200


def test_chunk_document_figure_caption_is_standalone():
    elements = [StructuralElement(kind=StructureType.FIGURE_CAPTION, text="Figure 1: chart", page=1)]
    chunks = chunk_document(elements, _doc_meta())
    assert len(chunks) == 1
    assert chunks[0].figure_captions == ["Figure 1: chart"]


# ---------------------------------------------------------------------------
# classification.py
# ---------------------------------------------------------------------------


def _fake_embed_factory():
    """Deterministic bag-of-words embedding for classification tests --
    avoids loading the real sentence-transformers model just to prove the
    classifier's cosine-similarity ranking logic is correct."""
    vocab: dict[str, int] = {}

    def embed(text: str):
        import numpy as np

        words = text.lower().split()
        for w in words:
            vocab.setdefault(w, len(vocab))
        vec = np.zeros(max(len(vocab), 1))
        for w in words:
            vec[vocab[w]] += 1
        # pad to a stable max size across calls by re-embedding is fine here
        # since classify() always calls embed() fresh per anchor+query in
        # the same process, vocab keeps growing consistently.
        full = np.zeros(200)
        full[: len(vec)] = vec[:200]
        return full.tolist()

    return embed


def test_topic_classifier_ranks_best_match_first():
    classifier = TopicClassifier(embed_fn=_fake_embed_factory(), top_k=3, threshold=0.0)
    topics, confidence = classifier.classify("stop loss position sizing risk of ruin drawdown")
    assert KnowledgeCategory.RISK_MANAGEMENT in topics
    assert confidence >= 0.0


def test_topic_classifier_always_returns_at_least_one_topic():
    classifier = TopicClassifier(embed_fn=_fake_embed_factory(), top_k=3, threshold=1.1)  # impossible threshold
    topics, _ = classifier.classify("something")
    assert len(topics) == 1


# ---------------------------------------------------------------------------
# document_store.py
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path) -> DocumentStore:
    return DocumentStore(persist_dir=tmp_path / "chroma")


def _chunk(chunk_id, text, topics=None) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, doc_id="doc1", text=text, title="T", author="A", source="s",
        document_type=DocumentType.TXT, topics=topics or [],
    )


def test_document_store_add_and_vector_search(store):
    store.add_chunks([
        _chunk("c1", "Position sizing and risk of ruin in trading"),
        _chunk("c2", "The weather today is sunny with light wind"),
    ])
    results = store.vector_search("risk management and position sizing", limit=2)
    assert results
    assert results[0][0] == "c1"


def test_document_store_faiss_search_matches_vector_search_top_hit(store):
    store.add_chunks([_chunk("c1", "Kelly criterion position sizing"), _chunk("c2", "unrelated text about cooking")])
    chroma_hits = store.vector_search("position sizing", limit=1)
    faiss_hits = store.faiss_search("position sizing", limit=1)
    assert chroma_hits[0][0] == faiss_hits[0][0] == "c1"


def test_document_store_keyword_search_exact_term_match(store):
    # A 3rd, unrelated chunk avoids BM25's small-corpus IDF degeneracy: with
    # only 2 documents, a term appearing in exactly half the corpus gets
    # IDF=log(1)=0, which would zero out both chunks' scores and make them
    # indistinguishable -- not a bug, just not a representative corpus size.
    store.add_chunks([
        _chunk("c1", "gamma exposure and dealer positioning"),
        _chunk("c2", "bond yield curve steepening"),
        _chunk("c3", "candlestick pattern recognition basics"),
    ])
    hits = store.keyword_search("gamma exposure", limit=5)
    assert hits and hits[0][0] == "c1"


def test_document_store_metadata_filter(store):
    store.add_chunks([
        _chunk("c1", "risk text", topics=[KnowledgeCategory.RISK_MANAGEMENT]),
        _chunk("c2", "options text", topics=[KnowledgeCategory.OPTIONS]),
    ])
    matches = store.filter_chunk_ids(topic=KnowledgeCategory.OPTIONS)
    assert matches == {"c2"}


def test_document_store_hybrid_search_respects_metadata_filter(store):
    store.add_chunks([
        _chunk("c1", "position sizing risk management", topics=[KnowledgeCategory.RISK_MANAGEMENT]),
        _chunk("c2", "position sizing in options trading", topics=[KnowledgeCategory.OPTIONS]),
    ])
    results = store.hybrid_search("position sizing", limit=5, metadata_filter={"topic": KnowledgeCategory.OPTIONS})
    assert len(results) == 1
    assert results[0].chunk.chunk_id == "c2"


def test_document_store_hybrid_search_caches_repeated_queries(store, monkeypatch):
    store.add_chunks([
        _chunk("c1", "position sizing risk management"),
        _chunk("c2", "unrelated cooking content"),
    ])
    calls = []
    original = store.keyword_search

    def counting_keyword_search(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "keyword_search", counting_keyword_search)

    r1 = store.hybrid_search("position sizing", limit=5)
    r2 = store.hybrid_search("position sizing", limit=5)
    assert len(calls) == 1  # second call served from cache, no re-scan
    assert [r.chunk.chunk_id for r in r1] == [r.chunk.chunk_id for r in r2]


def test_document_store_hybrid_search_cache_distinguishes_by_params(store):
    store.add_chunks([_chunk("c1", "position sizing risk management")])
    store.hybrid_search("position sizing", limit=1)
    store.hybrid_search("position sizing", limit=5)
    # Different limit -> different cache key -> both computed and cached
    # separately, not conflated into one entry.
    assert len(store._hybrid_search_cache) == 2


def test_document_store_add_chunks_invalidates_hybrid_search_cache(store):
    store.add_chunks([_chunk("c1", "alpha strategies exploit market inefficiencies")])
    r1 = store.hybrid_search("alpha strategies", limit=5)
    assert len(r1) == 1
    assert len(store._hybrid_search_cache) == 1

    store.add_chunks([_chunk("c2", "alpha strategies and factor exposure")])
    assert len(store._hybrid_search_cache) == 0  # invalidated by the write

    r2 = store.hybrid_search("alpha strategies", limit=5)
    assert len(r2) == 2  # sees the newly added chunk, not a stale cached result


# ---- _rehydrate on-disk cache (2026-07-20 perf fix) ----
# Real bug: rebuilding FAISS+BM25 from Chroma on every process start
# measured at 100-140s against this project's real 319K-chunk corpus.
# These use a tiny synthetic corpus so they run fast while still
# exercising the real cache read/write/invalidate code paths.


def test_rehydrate_uses_cache_on_second_construction(tmp_path):
    """The cache is written at the END of a real _rehydrate() rebuild --
    which only runs when Chroma already has content to rehydrate (see
    _rehydrate's own count==0 early-return). So: construct+write chunks
    (nothing to rehydrate yet, no cache written), construct AGAIN (now
    Chroma has content -- this is the real rebuild that writes the
    cache), then a THIRD construction must hit that cache."""
    persist_dir = tmp_path / "chroma"
    store1 = DocumentStore(persist_dir=persist_dir)
    store1.add_chunks([_chunk("c1", "trend following turtle breakout"), _chunk("c2", "mean reversion RSI oversold")])
    assert not store1._rehydrate_cache_meta_path.exists()  # nothing to rehydrate yet at construction time

    store2 = DocumentStore(persist_dir=persist_dir)  # real rebuild from Chroma -- writes the cache at the end
    assert len(store2._chunks) == 2
    assert store2._rehydrate_cache_meta_path.exists()
    assert store2._rehydrate_cache_faiss_path.exists()

    store3 = DocumentStore(persist_dir=persist_dir)  # should hit the cache written by store2
    assert len(store3._chunks) == 2
    assert store3._bm25 is not None
    assert store3.hybrid_search("trend following", limit=2)


def test_rehydrate_cache_miss_falls_back_to_full_rebuild_when_count_changes(tmp_path):
    """Simulates a real ingestion happening between two process starts --
    the second start's Chroma count differs from what's cached, so it
    must NOT silently serve the stale (smaller) cached corpus."""
    persist_dir = tmp_path / "chroma"
    store1 = DocumentStore(persist_dir=persist_dir)
    store1.add_chunks([_chunk("c1", "trend following turtle breakout")])
    del store1

    # A second, independent process-like write happens directly via a
    # fresh DocumentStore over the SAME persist_dir (add_chunks already
    # invalidates the cache on write -- this also covers that path).
    store2 = DocumentStore(persist_dir=persist_dir)
    store2.add_chunks([_chunk("c2", "mean reversion RSI oversold")])
    assert not store2._rehydrate_cache_meta_path.exists()  # invalidated by the write above

    store3 = DocumentStore(persist_dir=persist_dir)
    assert len(store3._chunks) == 2  # both chunks present, not just the stale-cache's one


def test_rehydrate_cache_corrupt_file_falls_back_gracefully(tmp_path):
    persist_dir = tmp_path / "chroma"
    store1 = DocumentStore(persist_dir=persist_dir)
    store1.add_chunks([_chunk("c1", "trend following turtle breakout")])
    store1._rehydrate_cache_meta_path.write_bytes(b"not a valid pickle")

    store2 = DocumentStore(persist_dir=persist_dir)  # must not raise
    assert len(store2._chunks) == 1


def test_invalidate_rehydrate_cache_removes_both_files(tmp_path):
    persist_dir = tmp_path / "chroma"
    store1 = DocumentStore(persist_dir=persist_dir)
    store1.add_chunks([_chunk("c1", "trend following turtle breakout")])
    store2 = DocumentStore(persist_dir=persist_dir)  # real rebuild -- writes the cache
    assert store2._rehydrate_cache_meta_path.exists()

    store2._invalidate_rehydrate_cache()
    assert not store2._rehydrate_cache_meta_path.exists()
    assert not store2._rehydrate_cache_faiss_path.exists()
    store2._invalidate_rehydrate_cache()  # must be idempotent, not raise on missing files


def test_document_store_hybrid_search_cache_respects_ttl(store, monkeypatch):
    import project_titan_x.engines.e01_knowledge.document_store as ds_module

    store.add_chunks([_chunk("c1", "position sizing risk management")])
    store.hybrid_search("position sizing", limit=5)
    assert len(store._hybrid_search_cache) == 1

    monkeypatch.setattr(ds_module, "_HYBRID_SEARCH_CACHE_TTL_SECONDS", -1)  # force immediate expiry
    cache_key = store._hybrid_search_cache_key("position sizing", 5, 0.6, 0.4, None)
    assert store._get_cached_hybrid_search(cache_key) is None


def test_document_store_similar_chunks_excludes_self(store):
    store.add_chunks([
        _chunk("c1", "Kelly criterion for position sizing"),
        _chunk("c2", "position sizing using the Kelly criterion formula"),
        _chunk("c3", "completely unrelated cooking recipe text"),
    ])
    results = store.similar_chunks("c1", limit=2)
    assert all(r.chunk.chunk_id != "c1" for r in results)


# ---------------------------------------------------------------------------
# knowledge_graph.py
# ---------------------------------------------------------------------------


def test_knowledge_graph_related_topics_from_cooccurrence():
    graph = KnowledgeGraph()
    graph.add_chunk(_chunk("c1", "t", topics=[KnowledgeCategory.RISK_MANAGEMENT, KnowledgeCategory.OPTIONS]))
    graph.add_chunk(_chunk("c2", "t", topics=[KnowledgeCategory.RISK_MANAGEMENT, KnowledgeCategory.OPTIONS]))
    related = graph.related_topics(KnowledgeCategory.RISK_MANAGEMENT.value)
    assert related and related[0][0] == KnowledgeCategory.OPTIONS.value


def test_knowledge_graph_sources_for_topic():
    graph = KnowledgeGraph()
    chunk = _chunk("c1", "t", topics=[KnowledgeCategory.CRYPTO])
    chunk.title = "Bitcoin Book"
    graph.add_chunk(chunk)
    assert graph.sources_for_topic(KnowledgeCategory.CRYPTO.value) == ["Bitcoin Book"]


def test_knowledge_graph_unknown_topic_returns_empty():
    graph = KnowledgeGraph()
    assert graph.related_topics("Nonexistent Topic") == []


# ---------------------------------------------------------------------------
# ingestion.py -- directory-scope enforcement
# ---------------------------------------------------------------------------


def test_ingestion_rejects_paths_outside_allowed_directories(tmp_path):
    store_ = DocumentStore(persist_dir=tmp_path / "chroma")
    pipeline = IngestionPipeline(data_root=tmp_path / "data", store=store_)

    outside_path = tmp_path / "somewhere_else" / "doc.txt"
    outside_path.parent.mkdir(parents=True, exist_ok=True)
    outside_path.write_text("hello", encoding="utf-8")

    with pytest.raises(DocumentOutsideAllowedDirectoryError):
        pipeline.ingest_file(outside_path)


def test_ingestion_accepts_paths_inside_allowed_directories(tmp_path):
    store_ = DocumentStore(persist_dir=tmp_path / "chroma")
    pipeline = IngestionPipeline(data_root=tmp_path / "data", store=store_)

    allowed_path = tmp_path / "data" / "notes" / "doc.txt"
    allowed_path.parent.mkdir(parents=True, exist_ok=True)
    allowed_path.write_text("Chapter 1\n\nSome content about trading psychology and discipline.", encoding="utf-8")

    chunks = pipeline.ingest_file(allowed_path)
    assert len(chunks) > 0


def test_ingestion_creates_all_six_required_directories(tmp_path):
    store_ = DocumentStore(persist_dir=tmp_path / "chroma")
    IngestionPipeline(data_root=tmp_path / "data", store=store_)
    for sub in ["books", "research", "annual_reports", "sec_filings", "trading_journals", "notes"]:
        assert (tmp_path / "data" / sub).is_dir()


# ---------------------------------------------------------------------------
# engine.py -- async API
# ---------------------------------------------------------------------------


@pytest.fixture
def knowledge_engine(tmp_path) -> KnowledgeEngine:
    store_ = DocumentStore(persist_dir=tmp_path / "chroma")
    engine = KnowledgeEngine(knowledge_dir=tmp_path / "kd", data_root=tmp_path / "data", document_store=store_)
    notes = tmp_path / "data" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "doc.txt").write_text(
        "Chapter 1: Risk Management\n\n"
        "Position sizing determines how much capital to risk per trade using the Kelly criterion.",
        encoding="utf-8",
    )
    return engine


async def test_engine_ingest_all_and_search(knowledge_engine):
    ingest_result = await knowledge_engine.ingest_all()
    assert ingest_result.success
    assert ingest_result.metadata["n_succeeded"] == 1

    search_result = await knowledge_engine.search("position sizing kelly criterion")
    assert search_result.success
    assert len(search_result.data) > 0


async def test_engine_retrieve_returns_context_and_citations(knowledge_engine):
    await knowledge_engine.ingest_all()
    result = await knowledge_engine.retrieve("risk per trade")
    assert result.success
    assert "context" in result.data
    assert result.data["citations"]


async def test_engine_answer_is_extractive_not_generated(knowledge_engine):
    await knowledge_engine.ingest_all()
    result = await knowledge_engine.answer("kelly criterion position sizing")
    assert result.success
    assert "Kelly criterion" in result.data["answer"]
    assert "not LLM-generated" in result.message


async def test_engine_get_sources_lists_ingested_titles(knowledge_engine):
    await knowledge_engine.ingest_all()
    result = await knowledge_engine.get_sources()
    assert result.success
    assert len(result.data) == 1


async def test_engine_get_citations_includes_source_and_page(knowledge_engine):
    await knowledge_engine.ingest_all()
    result = await knowledge_engine.get_citations("risk management")
    assert result.success
    assert all("source" in c and "excerpt" in c for c in result.data)


async def test_engine_search_on_empty_store_returns_no_results(tmp_path):
    store_ = DocumentStore(persist_dir=tmp_path / "chroma")
    engine = KnowledgeEngine(knowledge_dir=tmp_path / "kd", data_root=tmp_path / "data", document_store=store_)
    result = await engine.search("anything")
    assert result.success
    assert result.data == []


# ---- _load_seed_data (real Postgres) ----
# Real (not mocked) DB, same convention as this codebase's other live-infra
# tests (see test_performance_analytics_engine.py's module docstring) --
# Postgres is genuinely running via docker-compose for local development.


@pytest.mark.network
def test_load_seed_data_skips_already_persisted_traders(tmp_path):
    """Regression test for a real startup-time bug: _load_seed_data used
    to call add_trader_profile() -- which always re-embeds the profile
    text -- for EVERY seed trader on EVERY server start, regardless of
    whether anything changed. That forced the (otherwise lazily-loaded)
    sentence-transformers model to import+load synchronously during
    initialize(), measured at ~19-23s of a ~30s cold start. A second call
    for the SAME trader name must persist zero new embeddings/DB rows --
    proving the skip logic actually works, not just that seeding is
    idempotent by accident."""
    import json

    from project_titan_x.core.database import TraderProfile, get_db_session

    name = "ZZZ_UNIT_TEST_TRADER_DO_NOT_KEEP"
    seed_path = tmp_path / "traders_seed.json"
    seed_path.write_text(json.dumps([{"name": name, "category": "test", "biography": "unit test fixture"}]))

    engine = KnowledgeEngine(knowledge_dir=tmp_path / "kd", data_root=tmp_path / "data")
    try:
        engine._load_seed_data(seed_path)
        with get_db_session() as session:
            first_row = session.query(TraderProfile).filter_by(name=name).first()
            assert first_row is not None
            first_embedding_id = first_row.embedding_id

        # Second call for the SAME name: must be skipped, not re-embedded.
        engine._load_seed_data(seed_path)
        with get_db_session() as session:
            rows = session.query(TraderProfile).filter_by(name=name).all()
            assert len(rows) == 1  # no duplicate row from a second insert
            assert rows[0].embedding_id == first_embedding_id  # not re-embedded
    finally:
        with get_db_session() as session:
            session.query(TraderProfile).filter_by(name=name).delete()

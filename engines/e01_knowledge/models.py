"""
Module: models.py
Description: Typed data model for Engine 01's document-ingestion RAG
    pipeline (distinct from the pre-existing TraderProfile/PostgreSQL
    model in engine.py, which this module does not touch).
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class DocumentType(str, Enum):
    """Supported ingestion formats."""

    PDF = "pdf"
    EPUB = "epub"
    DOCX = "docx"
    TXT = "txt"
    HTML = "html"
    MARKDOWN = "markdown"


class KnowledgeCategory(str, Enum):
    """Fixed taxonomy every chunk is classified into (see classification.py)."""

    TECHNICAL_ANALYSIS = "Technical Analysis"
    SMART_MONEY_CONCEPTS = "Smart Money Concepts"
    ICT = "ICT"
    WYCKOFF = "Wyckoff"
    VOLUME_PROFILE = "Volume Profile"
    MARKET_PROFILE = "Market Profile"
    ELLIOTT_WAVE = "Elliott Wave"
    HARMONICS = "Harmonics"
    CANDLESTICK_PATTERNS = "Candlestick Patterns"
    RISK_MANAGEMENT = "Risk Management"
    PORTFOLIO_MANAGEMENT = "Portfolio Management"
    QUANTITATIVE_FINANCE = "Quantitative Finance"
    MACHINE_LEARNING = "Machine Learning"
    STATISTICS = "Statistics"
    BEHAVIORAL_FINANCE = "Behavioral Finance"
    MACROECONOMICS = "Macroeconomics"
    FIXED_INCOME = "Fixed Income"
    OPTIONS = "Options"
    FUTURES = "Futures"
    FOREX = "Forex"
    CRYPTO = "Crypto"
    COMMODITIES = "Commodities"
    INVESTING_PSYCHOLOGY = "Investing Psychology"


class StructureType(str, Enum):
    """Structural element kinds detected during parsing (see structure.py)."""

    CHAPTER = "chapter"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    FIGURE_CAPTION = "figure_caption"
    FORMULA = "formula"


@dataclass
class StructuralElement:
    """One parsed block of a document, tagged with its structural role."""

    kind: StructureType
    text: str
    page: Optional[int] = None
    level: int = 0  # heading depth (1 = top-level chapter heading, 2 = subheading, ...)
    chapter: Optional[str] = None  # nearest enclosing chapter title, if any


@dataclass
class LoadedDocument:
    """Raw output of a format-specific loader (loaders.py) before chunking:
    extracted title/author/page count plus every structural element found."""

    title: str
    author: str
    total_pages: Optional[int]
    elements: list[StructuralElement] = field(default_factory=list)


@dataclass
class DocumentMetadata:
    """Document-level metadata, attached to every chunk derived from it."""

    doc_id: str
    title: str
    author: str
    source: str  # absolute file path
    document_type: DocumentType
    total_pages: Optional[int] = None
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """A single retrievable unit of text with full required metadata."""

    chunk_id: str
    doc_id: str
    text: str
    title: str
    author: str
    source: str
    document_type: DocumentType
    page: Optional[int] = None
    chapter: Optional[str] = None
    topics: list[KnowledgeCategory] = field(default_factory=list)
    confidence: float = 0.0  # classification confidence of the top topic
    contains_table: bool = False
    contains_formula: bool = False
    figure_captions: list[str] = field(default_factory=list)

    def to_metadata_dict(self) -> dict[str, Any]:
        """Flat metadata dict for vector-store payloads (Chroma requires
        scalar values only, so list[topics] is joined into a string)."""
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "title": self.title,
            "author": self.author,
            "source": self.source,
            "document_type": self.document_type.value,
            "page": self.page if self.page is not None else -1,
            "chapter": self.chapter or "",
            "topics": ",".join(t.value for t in self.topics),
            "confidence": self.confidence,
            "contains_table": self.contains_table,
            "contains_formula": self.contains_formula,
        }


@dataclass
class Citation:
    """Source attribution for a retrieved chunk."""

    title: str
    author: str
    source: str
    page: Optional[int]
    chapter: Optional[str]
    excerpt: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "author": self.author,
            "source": self.source,
            "page": self.page,
            "chapter": self.chapter,
            "excerpt": self.excerpt,
        }


@dataclass
class SearchResult:
    """One ranked result from search()/retrieve()/similar_chunks()."""

    chunk: Chunk
    score: float
    vector_score: Optional[float] = None
    keyword_score: Optional[float] = None

    @property
    def citation(self) -> Citation:
        excerpt = self.chunk.text[:280] + ("..." if len(self.chunk.text) > 280 else "")
        return Citation(
            title=self.chunk.title,
            author=self.chunk.author,
            source=self.chunk.source,
            page=self.chunk.page,
            chapter=self.chunk.chapter,
            excerpt=excerpt,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.chunk.text,
            "score": round(self.score, 4),
            "vector_score": round(self.vector_score, 4) if self.vector_score is not None else None,
            "keyword_score": round(self.keyword_score, 4) if self.keyword_score is not None else None,
            "topics": [t.value for t in self.chunk.topics],
            "confidence": round(self.chunk.confidence, 4),
            "citation": self.citation.to_dict(),
        }

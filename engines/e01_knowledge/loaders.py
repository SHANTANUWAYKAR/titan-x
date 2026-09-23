"""
Module: loaders.py
Description: Format-specific document loaders for Engine 01's ingestion
    pipeline. Each loader extracts text plus as much real structure as the
    format actually exposes (DOCX paragraph styles, EPUB/HTML tags), and
    falls back to structure.py's plain-text heuristics only where the
    format has no native structural markup (TXT, and PDF body text once
    reduced to lines).

    Page numbers: preserved wherever the format has real fixed pagination
    (PDF). EPUB and DOCX have no fixed pagination in their own document
    model (pagination is a rendering-time concept for both) -- page is
    left None rather than a fabricated number.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
import os
import re
import statistics
from pathlib import Path

import docx
import ebooklib
import pymupdf
import pdfplumber
import trafilatura
from bs4 import BeautifulSoup
from ebooklib import epub

from project_titan_x.engines.e01_knowledge.models import LoadedDocument, StructuralElement, StructureType
from project_titan_x.engines.e01_knowledge.structure import (
    classify_plain_text_block,
    is_probable_chapter,
    segment_plain_text,
)

logger = logging.getLogger(__name__)

_HEADING_SIZE_RATIO = 1.15  # a line must be >=15% larger than the page's modal font size to count as a heading


def _openable_path(path: Path) -> str:
    """Real bug found and fixed 2026-09-14: a 619-page book
    ("...The Economics of Business Enterprise...") sat in NOT READED
    BOOKS through 65+ ingestion iterations across two separate overnight
    runs without ever once appearing in a log line -- not processed, not
    skipped, not errored, just silently invisible. Root cause: its
    absolute path is 263 characters, 3 over Windows' legacy 260-char
    MAX_PATH. pathlib/os (used for iterdir/stat/move everywhere else in
    this pipeline) are long-path-aware and see it fine; pymupdf.open()
    and pdfplumber.open() are not, and raise FileNotFoundError on a file
    that demonstrably exists -- confirmed directly, not guessed
    (`pathlib.Path.iterdir()` lists it, `pymupdf.open()` on the identical
    path fails). This project's book-naming convention (full title +
    subtitle + author + edition + year + a hash suffix) makes a path over
    260 chars a real, recurring risk, not a one-off. Fix: Windows'
    documented `\\\\?\\` long-path-prefix opts a single path into the
    extended-length API (up to ~32,767 chars) without needing the
    system-wide long-path registry setting enabled -- confirmed live,
    the exact stuck file opens correctly through this prefix. Harmless
    everywhere else: a no-op passthrough on non-Windows platforms and on
    a UNC path (`\\\\server\\share\\...`, which uses a different prefix
    already incompatible with this one)."""
    resolved = str(path.resolve())
    if os.name == "nt" and not resolved.startswith("\\\\"):
        return "\\\\?\\" + resolved
    return resolved


def load_pdf(path: Path, start_page: int = 0, end_page: int | None = None) -> LoadedDocument:
    """PyMuPDF for text + font-size-based heading detection (fast, gives
    per-span font metrics); pdfplumber specifically for table extraction
    (purpose-built for it, PyMuPDF's own table support is comparatively
    weak). Both open the same file independently -- an acceptable double
    pass for the accuracy gain on tables.

    start_page/end_page (added 2026-08-01): restrict parsing to a page
    range [start_page, end_page) instead of the whole document, so a
    large book can be split into several safe-sized slices by the caller
    instead of being deferred entirely. total_pages always reflects the
    REAL full document length regardless of the slice, so downstream
    metadata still shows the book's true size -- only which pages get
    parsed on THIS call is restricted. page numbers on every returned
    element stay absolute (page_index + 1 in the full document), never
    relative to the slice, so citations and page ordering stay correct
    when multiple slices of the same book end up in the store."""
    elements: list[StructuralElement] = []
    current_chapter: str | None = None

    with pymupdf.open(_openable_path(path)) as doc:
        title = (doc.metadata or {}).get("title") or path.stem
        author = (doc.metadata or {}).get("author") or "Unknown"
        total_pages = doc.page_count
        page_end = doc.page_count if end_page is None else min(end_page, doc.page_count)

        for page_index in range(start_page, page_end):
            page = doc[page_index]
            page_num = page_index + 1
            raw = page.get_text("dict")
            sizes = [
                span["size"]
                for block in raw.get("blocks", [])
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if span.get("text", "").strip()
            ]
            body_size = statistics.median(sizes) if sizes else 10.0

            for block in raw.get("blocks", []):
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    text = "".join(s.get("text", "") for s in spans).strip()
                    if not text:
                        continue
                    max_size = max(s.get("size", body_size) for s in spans)
                    is_bold = any("bold" in s.get("font", "").lower() for s in spans)

                    if is_probable_chapter(text):
                        current_chapter = text
                        elements.append(StructuralElement(
                            kind=StructureType.CHAPTER, text=text, page=page_num, level=1, chapter=text,
                        ))
                        continue

                    if (max_size >= body_size * _HEADING_SIZE_RATIO or is_bold) and len(text.split()) <= 14:
                        elements.append(StructuralElement(
                            kind=StructureType.HEADING, text=text, page=page_num, level=2, chapter=current_chapter,
                        ))
                        continue

                    element = classify_plain_text_block(text, page=page_num, chapter=current_chapter)
                    elements.append(element)

    # Table extraction: separate pass with pdfplumber. pdf.pages is lazy
    # (each page is only actually parsed when indexed/iterated), so slicing
    # to [start_page, page_end) here means pages outside the requested
    # range are never touched by pdfplumber's comparatively expensive
    # per-page parse at all, not just skipped after being parsed.
    try:
        with pdfplumber.open(_openable_path(path)) as pdf:
            for page_index in range(start_page, page_end):
                page = pdf.pages[page_index]
                for table in page.extract_tables():
                    if not table:
                        continue
                    rendered = "\n".join(
                        " | ".join(cell or "" for cell in row) for row in table if row
                    )
                    if rendered.strip():
                        elements.append(StructuralElement(
                            kind=StructureType.TABLE, text=rendered, page=page_index + 1,
                        ))
    except Exception as e:
        logger.warning("pdfplumber table extraction failed for %s: %s", path, e)

    return LoadedDocument(title=title, author=author, total_pages=total_pages, elements=elements)


def load_epub(path: Path) -> LoadedDocument:
    """ebooklib for container/spine parsing, BeautifulSoup for the actual
    per-chapter HTML structure (headings/paragraphs/tables/captions)."""
    book = epub.read_epub(str(path))

    def _meta(namespace_tag: str) -> str:
        values = book.get_metadata("DC", namespace_tag)
        return values[0][0] if values else ""

    title = _meta("title") or path.stem
    author = _meta("creator") or "Unknown"

    elements: list[StructuralElement] = []
    current_chapter: str | None = None

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "figcaption"]):
            text = tag.get_text(strip=True)
            if not text:
                continue
            if tag.name in ("h1", "h2"):
                current_chapter = text
                elements.append(StructuralElement(kind=StructureType.CHAPTER, text=text, level=1, chapter=text))
            elif tag.name.startswith("h"):
                elements.append(StructuralElement(
                    kind=StructureType.HEADING, text=text, level=int(tag.name[1]), chapter=current_chapter,
                ))
            elif tag.name == "table":
                rows = [
                    " | ".join(cell.get_text(strip=True) for cell in row.find_all(["td", "th"]))
                    for row in tag.find_all("tr")
                ]
                rendered = "\n".join(r for r in rows if r)
                if rendered:
                    elements.append(StructuralElement(kind=StructureType.TABLE, text=rendered, chapter=current_chapter))
            elif tag.name == "figcaption":
                elements.append(StructuralElement(kind=StructureType.FIGURE_CAPTION, text=text, chapter=current_chapter))
            else:
                elements.append(classify_plain_text_block(text, chapter=current_chapter))

    return LoadedDocument(title=title, author=author, total_pages=None, elements=elements)


def load_docx(path: Path) -> LoadedDocument:
    """python-docx: paragraph styles give real heading levels directly
    (no font-size guessing needed, unlike PDF); tables are walked
    separately via document.tables."""
    document = docx.Document(str(path))
    core = document.core_properties
    title = core.title or path.stem
    author = core.author or "Unknown"

    elements: list[StructuralElement] = []
    current_chapter: str | None = None

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = (paragraph.style.name if paragraph.style else "") or ""
        heading_match = re.match(r"heading\s*(\d)", style_name, re.IGNORECASE)
        if style_name.lower() == "title" or (heading_match and heading_match.group(1) == "1"):
            current_chapter = text
            elements.append(StructuralElement(kind=StructureType.CHAPTER, text=text, level=1, chapter=text))
        elif heading_match:
            elements.append(StructuralElement(
                kind=StructureType.HEADING, text=text, level=int(heading_match.group(1)), chapter=current_chapter,
            ))
        else:
            elements.append(classify_plain_text_block(text, chapter=current_chapter))

    for table in document.tables:
        rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
        rendered = "\n".join(r for r in rows if r)
        if rendered:
            elements.append(StructuralElement(kind=StructureType.TABLE, text=rendered, chapter=current_chapter))

    return LoadedDocument(title=title, author=author, total_pages=None, elements=elements)


def load_txt(path: Path) -> LoadedDocument:
    text = path.read_text(encoding="utf-8", errors="ignore")
    elements = segment_plain_text(text)
    return LoadedDocument(title=path.stem, author="Unknown", total_pages=None, elements=elements)


def load_html(path: Path) -> LoadedDocument:
    """BeautifulSoup walks the real tag structure (headings/tables/figure
    captions preserved); trafilatura's boilerplate-stripped main-text
    extraction is used as a fallback ONLY when the tag walk finds close to
    nothing structural (e.g. a div-soup page with no semantic markup) --
    both libraries get a genuine, distinct role rather than one being
    installed unused."""
    raw_html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(raw_html, "html.parser")

    title_tag = soup.find("title") or soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else path.stem

    elements: list[StructuralElement] = []
    current_chapter: str | None = None
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "figcaption"]):
        text = tag.get_text(strip=True)
        if not text:
            continue
        if tag.name in ("h1", "h2"):
            current_chapter = text
            elements.append(StructuralElement(kind=StructureType.CHAPTER, text=text, level=1, chapter=text))
        elif tag.name.startswith("h"):
            elements.append(StructuralElement(
                kind=StructureType.HEADING, text=text, level=int(tag.name[1]), chapter=current_chapter,
            ))
        elif tag.name == "table":
            rows = [
                " | ".join(cell.get_text(strip=True) for cell in row.find_all(["td", "th"]))
                for row in tag.find_all("tr")
            ]
            rendered = "\n".join(r for r in rows if r)
            if rendered:
                elements.append(StructuralElement(kind=StructureType.TABLE, text=rendered, chapter=current_chapter))
        elif tag.name == "figcaption":
            elements.append(StructuralElement(kind=StructureType.FIGURE_CAPTION, text=text, chapter=current_chapter))
        else:
            elements.append(classify_plain_text_block(text, chapter=current_chapter))

    if len([e for e in elements if e.kind == StructureType.PARAGRAPH]) < 3:
        extracted = trafilatura.extract(raw_html)
        if extracted:
            elements.extend(segment_plain_text(extracted))

    return LoadedDocument(title=title, author="Unknown", total_pages=None, elements=elements)


_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
_MD_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def load_markdown(path: Path) -> LoadedDocument:
    """Line-scanner: '#'-depth headings, '|'-delimited table rows grouped
    into TABLE blocks, fenced code blocks kept verbatim as paragraph text
    (not tagged FORMULA -- a code block isn't necessarily a mathematical
    formula), everything else through the plain-text heuristics."""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    elements: list[StructuralElement] = []
    current_chapter: str | None = None
    table_buffer: list[str] = []
    paragraph_buffer: list[str] = []
    in_code_block = False

    def flush_table() -> None:
        if table_buffer:
            elements.append(StructuralElement(kind=StructureType.TABLE, text="\n".join(table_buffer), chapter=current_chapter))
            table_buffer.clear()

    def flush_paragraph() -> None:
        if paragraph_buffer:
            joined = " ".join(paragraph_buffer).strip()
            if joined:
                elements.append(classify_plain_text_block(joined, chapter=current_chapter))
            paragraph_buffer.clear()

    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            flush_paragraph()
            continue
        if in_code_block:
            paragraph_buffer.append(line)
            continue

        heading_match = _MD_HEADING_RE.match(line)
        if heading_match:
            flush_table()
            flush_paragraph()
            depth, text = len(heading_match.group(1)), heading_match.group(2).strip()
            if depth == 1:
                current_chapter = text
                elements.append(StructuralElement(kind=StructureType.CHAPTER, text=text, level=1, chapter=text))
            else:
                elements.append(StructuralElement(kind=StructureType.HEADING, text=text, level=depth, chapter=current_chapter))
            continue

        if _MD_TABLE_ROW_RE.match(line):
            flush_paragraph()
            table_buffer.append(line.strip())
            continue
        flush_table()

        if not line.strip():
            flush_paragraph()
        else:
            paragraph_buffer.append(line.strip())

    flush_table()
    flush_paragraph()
    return LoadedDocument(title=path.stem, author="Unknown", total_pages=None, elements=elements)


LOADERS = {
    "pdf": load_pdf,
    "epub": load_epub,
    "docx": load_docx,
    "txt": load_txt,
    "html": load_html,
    "htm": load_html,
    "md": load_markdown,
    "markdown": load_markdown,
}


def load_document(path: Path, start_page: int = 0, end_page: int | None = None) -> LoadedDocument:
    """Dispatch to the correct loader by file extension. start_page/end_page
    (added 2026-08-01) only apply to PDFs -- see load_pdf's own docstring --
    since EPUB/DOCX/TXT/HTML have no fixed pagination to slice by; callers
    passing a range for any other format get the whole document, unsliced,
    same as before this parameter existed."""
    ext = path.suffix.lower().lstrip(".")
    loader = LOADERS.get(ext)
    if loader is None:
        raise ValueError(f"Unsupported document format: {path.suffix} ({path})")
    if ext == "pdf":
        return loader(path, start_page=start_page, end_page=end_page)
    return loader(path)

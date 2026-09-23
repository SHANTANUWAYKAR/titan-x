"""
Module: structure.py
Description: Format-agnostic structural heuristics shared by every loader
    in loaders.py -- heading detection from plain text, and best-effort
    formula/figure-caption detection.

    These are heuristics, not a real document-layout model: formula
    detection in particular is a regex/symbol-density guess, not LaTeX-
    grade math OCR. Documented honestly rather than oversold, since this
    project's owner has repeatedly stressed that overclaiming accuracy on
    data the system then acts on is the one mistake not to make.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import re

from project_titan_x.engines.e01_knowledge.models import StructuralElement, StructureType

_CHAPTER_RE = re.compile(r"^(chapter|part|section)\s+([0-9]+|[ivxlcdm]+)\b", re.IGNORECASE)
_FIGURE_CAPTION_RE = re.compile(r"^(figure|fig\.?|chart|table)\s*\d+[:.]", re.IGNORECASE)
_TABLE_CAPTION_RE = re.compile(r"^table\s*\d+[:.]", re.IGNORECASE)
_MATH_SYMBOLS = set("=+±×÷∑∫√≈≤≥≠∞∂∇πσμλαβγθΣΠ^")
_FORMULA_DELIMS_RE = re.compile(r"(\$[^$]+\$|\\\[[^\]]+\\\]|\\begin\{equation\})")

_MAX_HEADING_CHARS = 90


def is_probable_heading(line: str) -> bool:
    """A line with no terminal punctuation, short, and not itself a full
    sentence is treated as a probable heading -- the same convention most
    plain-text/markdown structure detectors use absent real style info."""
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_CHARS:
        return False
    if stripped.endswith((".", "?", "!", ",", ";")):
        return False
    word_count = len(stripped.split())
    if word_count == 0 or word_count > 12:
        return False
    return stripped[0].isupper() or stripped.isupper() or bool(_CHAPTER_RE.match(stripped))


def is_probable_chapter(line: str) -> bool:
    return bool(_CHAPTER_RE.match(line.strip()))


def is_probable_figure_caption(line: str) -> bool:
    return bool(_FIGURE_CAPTION_RE.match(line.strip()))


def is_probable_table_caption(line: str) -> bool:
    return bool(_TABLE_CAPTION_RE.match(line.strip()))


def is_probable_formula(line: str) -> bool:
    """Best-effort: explicit LaTeX-style delimiters, or a line whose
    mathematical-symbol density is high relative to its length (catches
    plain-text renderings like 'E = m * c^2' that never used LaTeX)."""
    stripped = line.strip()
    if not stripped:
        return False
    if _FORMULA_DELIMS_RE.search(stripped):
        return True
    symbol_count = sum(1 for ch in stripped if ch in _MATH_SYMBOLS)
    return symbol_count >= 2 and symbol_count / max(len(stripped), 1) > 0.04


def classify_plain_text_block(text: str, page: int | None = None, chapter: str | None = None) -> StructuralElement:
    """Classify a single already-segmented block of text (one line/
    paragraph) into a StructuralElement using the heuristics above, for
    formats with no native structural markup (plain .txt, and as a
    fallback within other loaders)."""
    stripped = text.strip()
    if is_probable_chapter(stripped):
        return StructuralElement(kind=StructureType.CHAPTER, text=stripped, page=page, level=1, chapter=stripped)
    if is_probable_table_caption(stripped):
        return StructuralElement(kind=StructureType.TABLE, text=stripped, page=page, chapter=chapter)
    if is_probable_figure_caption(stripped):
        return StructuralElement(kind=StructureType.FIGURE_CAPTION, text=stripped, page=page, chapter=chapter)
    if is_probable_formula(stripped):
        return StructuralElement(kind=StructureType.FORMULA, text=stripped, page=page, chapter=chapter)
    if is_probable_heading(stripped):
        return StructuralElement(kind=StructureType.HEADING, text=stripped, page=page, level=2, chapter=chapter)
    return StructuralElement(kind=StructureType.PARAGRAPH, text=stripped, page=page, chapter=chapter)


def segment_plain_text(raw_text: str, page: int | None = None) -> list[StructuralElement]:
    """Split raw text into paragraph-level blocks (blank-line-separated)
    and classify each one. Tracks the most recent CHAPTER heading seen so
    later paragraphs/tables/formulas record which chapter they belong to."""
    blocks = re.split(r"\n\s*\n", raw_text)
    elements: list[StructuralElement] = []
    current_chapter: str | None = None
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # A block may itself contain multiple lines; only single, short
        # lines are heading/chapter candidates -- multi-line blocks are
        # treated as paragraph text even if their first line looks like one.
        lines = block.splitlines()
        if len(lines) == 1:
            element = classify_plain_text_block(lines[0], page=page, chapter=current_chapter)
            if element.kind == StructureType.CHAPTER:
                current_chapter = element.text
            elements.append(element)
        else:
            elements.append(StructuralElement(kind=StructureType.PARAGRAPH, text=block, page=page, chapter=current_chapter))
    return elements

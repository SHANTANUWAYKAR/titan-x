"""
Module: chunking.py
Description: Structure-aware chunking for Engine 01's ingestion pipeline.

    Rules:
      - A TABLE or FORMULA element always becomes its own dedicated chunk
        (never split or merged with surrounding prose -- splitting a table
        mid-row destroys its meaning).
      - A FIGURE_CAPTION becomes its own small chunk (no source image is
        ingested, only the caption text -- see loaders.py).
      - A CHAPTER/HEADING starts a new chunk rather than being buried
        mid-buffer, so every chunk's leading line is informative on its own.
      - Plain paragraphs accumulate into a chunk up to CHUNK_TARGET_CHARS,
        with the tail of one chunk carried into the next as overlap so a
        concept split across a chunk boundary isn't lost entirely.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from project_titan_x.engines.e01_knowledge.models import Chunk, DocumentMetadata, StructuralElement, StructureType

CHUNK_TARGET_CHARS = 1000
CHUNK_OVERLAP_CHARS = 150
MIN_CHUNK_CHARS = 40


def chunk_document(elements: list[StructuralElement], doc_meta: DocumentMetadata) -> list[Chunk]:
    chunks: list[Chunk] = []
    buffer: list[StructuralElement] = []
    buffer_chars = 0
    overlap_seed: str = ""

    def make_chunk(text: str, page: int | None, chapter: str | None, **kwargs) -> Chunk:
        chunk = Chunk(
            chunk_id=f"{doc_meta.doc_id}::chunk::{len(chunks)}",
            doc_id=doc_meta.doc_id,
            text=text,
            title=doc_meta.title,
            author=doc_meta.author,
            source=doc_meta.source,
            document_type=doc_meta.document_type,
            page=page,
            chapter=chapter,
            **kwargs,
        )
        chunks.append(chunk)
        return chunk

    def flush() -> None:
        nonlocal buffer, buffer_chars, overlap_seed
        if not buffer:
            return
        text = "\n".join(e.text for e in buffer)
        if len(text.strip()) >= MIN_CHUNK_CHARS:
            make_chunk(text, page=buffer[0].page, chapter=buffer[0].chapter)
            overlap_seed = text[-CHUNK_OVERLAP_CHARS:]
        buffer = []
        buffer_chars = 0

    for element in elements:
        if element.kind == StructureType.TABLE:
            flush()
            make_chunk(element.text, page=element.page, chapter=element.chapter, contains_table=True)
            continue

        if element.kind == StructureType.FORMULA:
            flush()
            make_chunk(element.text, page=element.page, chapter=element.chapter, contains_formula=True)
            continue

        if element.kind == StructureType.FIGURE_CAPTION:
            flush()
            make_chunk(element.text, page=element.page, chapter=element.chapter, figure_captions=[element.text])
            continue

        if element.kind in (StructureType.CHAPTER, StructureType.HEADING):
            flush()
            if overlap_seed:
                buffer.append(StructuralElement(kind=StructureType.PARAGRAPH, text=overlap_seed, page=element.page, chapter=element.chapter))
                buffer_chars += len(overlap_seed)
                overlap_seed = ""
            buffer.append(element)
            buffer_chars += len(element.text)
            continue

        # Plain paragraph.
        if not buffer and overlap_seed:
            buffer.append(StructuralElement(kind=StructureType.PARAGRAPH, text=overlap_seed, page=element.page, chapter=element.chapter))
            buffer_chars += len(overlap_seed)
            overlap_seed = ""
        buffer.append(element)
        buffer_chars += len(element.text)
        if buffer_chars >= CHUNK_TARGET_CHARS:
            flush()

    flush()
    return chunks

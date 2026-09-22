"""Turn a PDF into clean text for a retrieval system.

The value is in what gets removed: running headers, footers and page numbers
repeated on every page, which otherwise end up in every chunk of a RAG index.

    read_pdf(path)          -> RawDocument   pages, with OCR fallback
    clean_pages(pages)      -> pages, report furniture removed statistically
    convert(path)           -> Conversion    the whole pipeline
    chunk_text(text)        -> [Chunk]       retrieval chunks with metadata
"""

from .chunk import Chunk, chunk_sections, chunk_text, write_jsonl
from .clean import (
    CleaningReport,
    clean_pages,
    find_repeated_lines,
    flatten_paragraphs,
    join_pages,
    rejoin_hyphenation,
)
from .convert import Conversion, convert, write
from .extract import ExtractionError, Page, RawDocument, read_pdf

__version__ = "1.1.0"

__all__ = [
    "Chunk",
    "CleaningReport",
    "Conversion",
    "ExtractionError",
    "Page",
    "RawDocument",
    "chunk_sections",
    "chunk_text",
    "clean_pages",
    "convert",
    "find_repeated_lines",
    "flatten_paragraphs",
    "join_pages",
    "read_pdf",
    "rejoin_hyphenation",
    "write",
    "write_jsonl",
    "__version__",
]

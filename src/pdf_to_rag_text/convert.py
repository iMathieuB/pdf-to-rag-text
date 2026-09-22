"""The pipeline: PDF in, clean text or chunks out."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .chunk import Chunk, chunk_text, write_jsonl
from .clean import CleaningReport, clean_pages, flatten_paragraphs, join_pages, rejoin_hyphenation
from .extract import RawDocument, read_pdf

log = logging.getLogger(__name__)

#: Lines that look like a heading, used to build a Markdown outline.
_HEADING_PATTERNS = (
    (1, r"^\s*(part|partie|book|livre)\s+([0-9]+|[ivxlcdm]+)\b"),
    (2, r"^\s*(chapter|chapitre)\s+([0-9]+|[ivxlcdm]+)\b"),
    (2, r"^\s*([0-9]{1,2})\.\s+\S.{0,70}$"),
    (3, r"^\s*([0-9]{1,2}\.[0-9]{1,2})\s+\S.{0,70}$"),
)


@dataclass
class Conversion:
    """The result of converting one PDF."""

    source: Path
    text: str
    report: CleaningReport
    used_ocr: bool = False
    pages: int = 0
    chunks: list[Chunk] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return len(self.text)

    def describe(self) -> str:
        lines = [
            f"Source        {self.source.name}" + ("  (read by OCR)" if self.used_ocr else ""),
            f"Pages         {self.pages}",
            f"Characters    {self.chars:,}",
        ]
        if self.chunks:
            sizes = [c.chars for c in self.chunks]
            lines.append(
                f"Chunks        {len(self.chunks)} "
                f"(min {min(sizes):,}, median {sorted(sizes)[len(sizes) // 2]:,}, max {max(sizes):,})"
            )
        lines.append("")
        lines.append(self.report.describe())
        return "\n".join(lines)


def convert(
    source: str | Path,
    *,
    ocr_language: str | None = None,
    min_repeats: int = 6,
    extra_headers: list[str] | None = None,
    keep_page_numbers: bool = False,
    keep_line_breaks: bool = False,
    markdown: bool = False,
    chunk: bool = False,
    chunk_chars: int = 1200,
    overlap_chars: int = 150,
    first_page: int | None = None,
    last_page: int | None = None,
) -> Conversion:
    """Read a PDF and return clean text, optionally chunked for retrieval.

    Args:
        min_repeats: how many pages a line must appear on to be treated as a
            running header. Lower it for a short document, raise it if real
            content is being removed.
        extra_headers: exact lines to strip as well.
        keep_line_breaks: keep the PDF's own line wrapping. Off by default,
            because those breaks come from the column width, not the sentences.
        markdown: emit ``#`` headings and a table of contents.
        chunk: also produce retrieval chunks.
    """
    raw: RawDocument = read_pdf(
        source, ocr_language=ocr_language, first_page=first_page, last_page=last_page
    )

    cleaned_pages, report = clean_pages(
        raw.pages,
        min_repeats=min_repeats,
        extra_headers=extra_headers,
        drop_page_numbers=not keep_page_numbers,
    )

    text = join_pages(cleaned_pages)
    text, joined = rejoin_hyphenation(text)
    report.hyphenations_joined = joined

    if not keep_line_breaks:
        # Headings are isolated before the reflow, not after. Flattening joins
        # every line of a block into one, and a heading sits directly above its
        # first paragraph with no blank line between them, so reflowing first
        # glues "2. Method" onto the sentence that follows and the heading stops
        # being recognisable. Marking it as its own block first is what lets
        # --markdown and paragraph reflow both work on the same run.
        if markdown:
            text = _isolate_headings(text)
        text = flatten_paragraphs(text)

    if markdown:
        text = _to_markdown(text, raw.title)

    result = Conversion(
        source=raw.path,
        text=text,
        report=report,
        used_ocr=raw.used_ocr,
        pages=len(raw.pages),
    )

    if chunk:
        result.chunks = chunk_text(
            text,
            source=raw.title,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
        )

    return result


def write(conversion: Conversion, output: str | Path, *, jsonl: bool = False) -> list[Path]:
    """Write the text, and the chunks when there are any."""
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    written = [output]
    output.write_text(conversion.text, encoding="utf-8")

    if jsonl and conversion.chunks:
        written.append(write_jsonl(conversion.chunks, output.with_suffix(".jsonl")))

    return written


def _to_markdown(text: str, title: str) -> str:
    """Add Markdown headings and a table of contents.

    Retrieval tools increasingly split on heading level, so marking the
    structure explicitly is worth more than it looks.
    """
    lines = text.split("\n")
    out: list[str] = []
    toc: list[tuple[int, str]] = []

    for line in lines:
        stripped = line.strip()
        level = _heading_level(stripped) if stripped else None
        if level:
            toc.append((level, stripped))
            out.append(f"{'#' * (level + 1)} {stripped}")
        else:
            out.append(line)

    header = [f"# {title}", ""]
    if len(toc) >= 3:
        header.append("## Contents")
        header.append("")
        for level, heading in toc:
            header.append(f"{'  ' * (level - 1)}- {heading}")
        header.append("")

    return "\n".join(header + out)


def _isolate_headings(text: str) -> str:
    """Put a blank line either side of every heading.

    ``flatten_paragraphs`` treats a blank line as the only paragraph boundary,
    so this is what keeps a heading on a line of its own through the reflow.
    """
    out: list[str] = []
    for line in text.split("\n"):
        if _heading_level(line.strip()):
            if out and out[-1].strip():
                out.append("")
            out.append(line.strip())
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def _heading_level(line: str) -> int | None:
    if len(line) > 90:  # a heading is short
        return None
    for level, pattern in _HEADING_PATTERNS:
        if re.match(pattern, line, flags=re.IGNORECASE):
            return level
    return None

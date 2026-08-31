"""Removing everything that is page furniture rather than content.

This module is the reason the project exists. Text pulled straight out of a PDF
carries the book's running headers, its footers and its page numbers, repeated
on every single page. Feed that to a retrieval system and the damage compounds:
every chunk is padded with the same boilerplate, so the embeddings of unrelated
passages drift toward each other, and a search for the book's own title matches
everything equally.

The headers cannot be removed with a fixed rule, because every book puts
something different up there. They are found statistically instead: a line that
appears near the top or bottom of many pages is furniture, whatever it says.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

from .extract import Page

log = logging.getLogger(__name__)

#: A line has to appear on at least this many pages to count as furniture. Six
#: is deliberately cautious: a real sentence repeated five times in a book is
#: unusual but possible, whereas a header appears on hundreds of pages.
DEFAULT_MIN_REPEATS = 6

#: How many lines from each edge of a page can be furniture. Headers and footers
#: sometimes run to two or three lines with a rule and a page number.
EDGE_LINES = 4

_PAGE_NUMBER = re.compile(
    r"""^\s*(
        \d{1,4}                     # 42
      | [ivxlcdm]{1,7}              # xiv
      | [-–—|\[(]*\s*\d{1,4}\s*[-–—|\])]*   # - 42 -   |42|   [42]
      | (?:page|p\.?)\s*\d{1,4}     # page 42
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class CleaningReport:
    """What was removed, so the result can be checked rather than trusted."""

    repeated_lines: list[str] = field(default_factory=list)
    page_numbers_removed: int = 0
    header_lines_removed: int = 0
    hyphenations_joined: int = 0
    garbage_lines_removed: int = 0

    def describe(self) -> str:
        lines = [
            f"Running headers found   {len(self.repeated_lines)}",
            f"Header lines removed    {self.header_lines_removed}",
            f"Page numbers removed    {self.page_numbers_removed}",
            f"Hyphenations rejoined   {self.hyphenations_joined}",
            f"Garbage lines removed   {self.garbage_lines_removed}",
        ]
        if self.repeated_lines:
            lines.append("")
            lines.append("Treated as page furniture:")
            for item in self.repeated_lines[:15]:
                lines.append(f"  {item[:76]}")
            if len(self.repeated_lines) > 15:
                lines.append(f"  ... and {len(self.repeated_lines) - 15} more")
        return "\n".join(lines)


def find_repeated_lines(
    pages: list[Page],
    *,
    min_repeats: int = DEFAULT_MIN_REPEATS,
    edge_lines: int = EDGE_LINES,
) -> set[str]:
    """Find lines that recur near the top or bottom of many pages.

    Only the edges of each page are considered. Searching the whole page would
    flag any sentence a book happens to repeat, and body text is not furniture
    however often it appears.

    A line is counted once per page, so a header that also appears twice in the
    body of one page does not inflate its own score.
    """
    if len(pages) < min_repeats:
        return set()

    counts: Counter[str] = Counter()
    for page in pages:
        lines = [line.strip() for line in page.text.splitlines() if line.strip()]
        edges = set(lines[:edge_lines]) | set(lines[-edge_lines:])
        for line in edges:
            normalised = _normalise(line)
            # Very short lines are usually page numbers, handled separately, and
            # matching them here would strip legitimate one-word headings.
            if len(normalised) > 3:
                counts[normalised] += 1

    repeated = {line for line, count in counts.items() if count >= min_repeats}
    if repeated:
        log.info("Found %d line(s) repeated on %d+ pages", len(repeated), min_repeats)
    return repeated


def clean_pages(
    pages: list[Page],
    *,
    min_repeats: int = DEFAULT_MIN_REPEATS,
    extra_headers: list[str] | None = None,
    drop_page_numbers: bool = True,
    drop_garbage: bool = True,
) -> tuple[list[Page], CleaningReport]:
    """Strip furniture from every page.

    Args:
        extra_headers: exact lines to remove as well, for the cases statistics
            miss, such as a title that only appears on chapter openers.
    """
    report = CleaningReport()
    repeated = find_repeated_lines(pages, min_repeats=min_repeats)
    report.repeated_lines = sorted(repeated)

    manual = {_normalise(h) for h in (extra_headers or [])}
    cleaned: list[Page] = []

    for page in pages:
        kept: list[str] = []
        for line in page.text.splitlines():
            stripped = line.strip()
            if not stripped:
                kept.append("")
                continue

            if drop_page_numbers and _PAGE_NUMBER.match(stripped):
                report.page_numbers_removed += 1
                continue

            normalised = _normalise(stripped)
            if normalised in repeated or normalised in manual:
                report.header_lines_removed += 1
                continue

            if drop_garbage and _is_garbage(stripped):
                report.garbage_lines_removed += 1
                continue

            kept.append(line)

        cleaned.append(Page(number=page.number, text="\n".join(kept).strip()))

    return cleaned, report


def join_pages(pages: list[Page]) -> str:
    """Join cleaned pages into one document, dropping any that became empty."""
    return "\n\n".join(p.text for p in pages if p.text.strip())


def rejoin_hyphenation(text: str) -> tuple[str, int]:
    """Rejoin words split across a line break by a hyphen.

    Justified typesetting breaks words at the right margin. Left alone, the two
    halves become separate tokens, so "auto-\\nmation" never matches a search
    for "automation".

    Only lowercase-to-lowercase joins are made. A capital after the hyphen
    usually means a real compound such as "Franco-\\nAmerican", where the hyphen
    belongs to the word.
    """
    joined, count = re.subn(r"([a-zà-öø-ÿ])-\n([a-zà-öø-ÿ])", r"\1\2", text)
    return joined, count


def flatten_paragraphs(text: str) -> str:
    """Turn each paragraph into one line, keeping blank lines as separators.

    A PDF breaks lines wherever the column ended, which has nothing to do with
    the sentences. Leaving those breaks in makes chunking cut at arbitrary
    places and makes the text unpleasant to read.

    Blocks are split first and flattened one at a time: doing it with a single
    regex over the whole string backtracks onto the second newline of a pair and
    silently eats the paragraph break.
    """
    blocks = re.split(r"\n[ \t]*\n", text)
    flattened = [re.sub(r"\s+", " ", block).strip() for block in blocks]
    return "\n\n".join(b for b in flattened if b).strip()


def _normalise(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _is_garbage(line: str) -> bool:
    """True for lines that are mostly not letters.

    OCR produces runs of stray punctuation from rules, borders and scanning
    artefacts. A line of five or more characters that is under a third letters
    carries no meaning worth indexing.
    """
    if len(line) < 5:
        return False
    letters = sum(1 for char in line if char.isalpha())
    return (letters / len(line)) < 0.34

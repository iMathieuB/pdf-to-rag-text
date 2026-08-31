"""Splitting cleaned text into retrievable chunks.

A chunk is the unit a retrieval system embeds and returns. Two properties decide
whether retrieval works at all.

It has to be semantically whole. A chunk that starts halfway through an argument
and stops halfway through the next one embeds as a blur of both and answers
neither question well. So splits are made at paragraph boundaries wherever
possible, and at sentence boundaries when a paragraph is too long.

It has to carry enough context to stand alone. A passage that begins "This is
why it fails" is useless once separated from what "it" was. Two things address
that: an overlap, so the end of one chunk repeats at the start of the next, and
a heading path stored with each chunk, so the retrieved text arrives labelled
with the section it came from.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_CHUNK_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 150

_SENTENCE_END = re.compile(
    r"(?<![A-Z])(?<!\bM)(?<!\bMr)(?<!\bMrs)(?<!\bDr)(?<!\bSt)(?<!\betc)"
    r"([.!?…][\"'»”’\)\]]?)\s+(?=[\"'«“\(\[]?[A-Z0-9À-ÖØ-Þ])"
)


@dataclass
class Chunk:
    """One retrievable passage, with the metadata a retrieval system wants."""

    id: str
    text: str
    index: int
    source: str
    section: str = ""
    chars: int = 0

    def __post_init__(self) -> None:
        self.chars = len(self.text)

    def to_dict(self) -> dict:
        return asdict(self)


def chunk_text(
    text: str,
    *,
    source: str,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    section: str = "",
) -> list[Chunk]:
    """Split ``text`` into overlapping chunks of at most ``chunk_chars``.

    Raises:
        ValueError: if the overlap is not smaller than the chunk size, which
            would make the splitter loop forever or never advance.
    """
    if chunk_chars < 100:
        raise ValueError("chunk_chars below 100 produces chunks too small to retrieve.")
    if overlap_chars >= chunk_chars:
        raise ValueError("overlap_chars must be smaller than chunk_chars.")

    text = text.strip()
    if not text:
        return []

    pieces = _pack(_split_units(text, chunk_chars), chunk_chars)
    if overlap_chars:
        pieces = _add_overlap(pieces, overlap_chars)

    return [
        Chunk(id=f"{_slug(source)}-{i:05d}", text=piece, index=i, source=source, section=section)
        for i, piece in enumerate(pieces)
    ]


def chunk_sections(
    sections: list[tuple[str, str]],
    *,
    source: str,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """Chunk several titled sections, never letting a chunk span two of them.

    Keeping the boundary means a retrieved chunk always belongs to exactly one
    section, so the heading stored beside it is always accurate.
    """
    out: list[Chunk] = []
    for title, body in sections:
        for chunk in chunk_text(
            body,
            source=source,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
            section=title,
        ):
            chunk.index = len(out)
            chunk.id = f"{_slug(source)}-{chunk.index:05d}"
            out.append(chunk)
    return out


def write_jsonl(chunks: list[Chunk], path: str | Path) -> Path:
    """Write chunks as JSON Lines, one object per line.

    JSONL rather than one JSON array: a large corpus can be streamed line by
    line without holding it all in memory, and most ingestion tools expect it.
    """
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False))
            handle.write("\n")
    return path


# --------------------------------------------------------------------- private


def _split_units(text: str, limit: int) -> list[str]:
    """Break into the largest pieces that still fit: paragraphs, then sentences."""
    units: list[str] = []
    for paragraph in (p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()):
        if len(paragraph) <= limit:
            units.append(paragraph)
        else:
            units.extend(_split_sentences(paragraph, limit))
    return units


def _split_sentences(paragraph: str, limit: int) -> list[str]:
    parts = _SENTENCE_END.split(paragraph)
    sentences: list[str] = []
    index = 0
    while index < len(parts):
        body = parts[index]
        punctuation = parts[index + 1] if index + 1 < len(parts) else ""
        sentence = (body + punctuation).strip()
        if sentence:
            sentences.append(sentence)
        index += 2

    out: list[str] = []
    for sentence in sentences or [paragraph]:
        if len(sentence) <= limit:
            out.append(sentence)
        else:
            out.extend(_hard_split(sentence, limit))
    return out


def _hard_split(text: str, limit: int) -> list[str]:
    """Last resort for a sentence with no usable boundary. Splits on whitespace."""
    words = text.split()
    if not words:
        return [text[i : i + limit] for i in range(0, len(text), limit)]

    out: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                out.append(current)
            current = word if len(word) <= limit else ""
            if len(word) > limit:
                out.extend(word[i : i + limit] for i in range(0, len(word), limit))
    if current:
        out.append(current)
    return out


def _pack(units: list[str], limit: int) -> list[str]:
    """Combine consecutive units up to the limit, so chunks are near full size."""
    packed: list[str] = []
    for unit in units:
        if packed and len(packed[-1]) + len(unit) + 2 <= limit:
            packed[-1] = f"{packed[-1]}\n\n{unit}"
        else:
            packed.append(unit)
    return packed


def _add_overlap(pieces: list[str], overlap: int) -> list[str]:
    """Prefix each chunk with the tail of the one before it.

    The tail is cut back to a word boundary, so a chunk never opens on half a
    word, which reads as noise to both a human and an embedding model.
    """
    if len(pieces) < 2:
        return pieces

    out = [pieces[0]]
    for previous, current in zip(pieces, pieces[1:]):
        tail = previous[-overlap:]
        space = tail.find(" ")
        if space != -1:
            tail = tail[space + 1 :]
        out.append(f"{tail.strip()} {current}".strip() if tail.strip() else current)
    return out


def _slug(text: str) -> str:
    import unicodedata

    normalised = unicodedata.normalize("NFKD", text)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-") or "doc"

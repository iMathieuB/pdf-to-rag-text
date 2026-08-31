"""Tests for the cleaning and chunking logic, which needs no PDF."""

from __future__ import annotations

import json

import pytest

from pdf_to_rag_text.chunk import chunk_sections, chunk_text, write_jsonl
from pdf_to_rag_text.clean import (
    clean_pages,
    find_repeated_lines,
    flatten_paragraphs,
    join_pages,
    rejoin_hyphenation,
)
from pdf_to_rag_text.extract import Page


def book(pages: int = 12, header: str = "The Art of Testing") -> list[Page]:
    """A book with a running header, a footer and a page number on every page."""
    return [
        Page(
            number=n,
            text=(
                f"{header}\n"
                f"Body sentence one on page {n}. Body sentence two on page {n}.\n"
                f"Chapter Three\n"
                f"{n}"
            ),
        )
        for n in range(1, pages + 1)
    ]


# ------------------------------------------------------------------ furniture


def test_a_running_header_is_detected():
    repeated = find_repeated_lines(book())
    assert "The Art of Testing" in repeated


def test_body_text_is_not_detected_as_furniture():
    repeated = find_repeated_lines(book())
    assert not any("Body sentence" in line for line in repeated)


def test_a_short_document_yields_no_furniture():
    """Below the repeat threshold there is no evidence, so nothing is removed."""
    assert find_repeated_lines(book(pages=3)) == set()


def test_headers_and_page_numbers_are_removed():
    cleaned, report = clean_pages(book())
    text = join_pages(cleaned)
    assert "The Art of Testing" not in text
    assert "Body sentence one on page 1." in text
    assert report.header_lines_removed > 0
    assert report.page_numbers_removed > 0


def test_page_numbers_in_various_shapes_are_removed():
    pages = [
        Page(1, "Real content here that is long enough.\n- 12 -"),
        Page(2, "More real content here to keep.\nxiv"),
        Page(3, "Further real content to keep here.\n[ 34 ]"),
        Page(4, "Yet more real content kept here.\npage 5"),
    ]
    text = join_pages(clean_pages(pages)[0])
    for artefact in ("- 12 -", "xiv", "[ 34 ]", "page 5"):
        assert artefact not in text
    assert text.lower().count("real content") == 4


def test_page_numbers_can_be_kept():
    cleaned, report = clean_pages(book(), drop_page_numbers=False)
    assert report.page_numbers_removed == 0


def test_an_extra_header_can_be_named_explicitly():
    pages = [Page(n, f"Sponsored Insert\nContent on page {n}.") for n in range(1, 4)]
    text = join_pages(clean_pages(pages, extra_headers=["Sponsored Insert"])[0])
    assert "Sponsored Insert" not in text
    assert "Content on page 1." in text


def test_the_threshold_can_be_lowered_for_a_short_document():
    pages = book(pages=4)
    assert "The Art of Testing" not in find_repeated_lines(pages)
    assert "The Art of Testing" in find_repeated_lines(pages, min_repeats=3)


def test_ocr_noise_lines_are_dropped():
    pages = [Page(n, f"Good sentence on page {n}.\n|||---|||~~~^^^") for n in range(1, 8)]
    text = join_pages(clean_pages(pages)[0])
    assert "|||---|||" not in text
    assert "Good sentence" in text


def test_the_report_names_what_was_removed():
    _, report = clean_pages(book())
    assert "The Art of Testing" in report.describe()


# ----------------------------------------------------------------- hyphenation


def test_hyphenated_line_breaks_are_rejoined():
    text, count = rejoin_hyphenation("This is auto-\nmation at work.")
    assert "automation" in text
    assert count == 1


def test_a_real_compound_keeps_its_hyphen():
    """A capital after the hyphen means the hyphen belongs to the word."""
    text, count = rejoin_hyphenation("He is Franco-\nAmerican.")
    assert "Franco-\nAmerican" in text
    assert count == 0


# ------------------------------------------------------------------ reflowing


def test_paragraphs_are_flattened_but_breaks_survive():
    out = flatten_paragraphs("line one\nline two\n\nsecond paragraph")
    assert "line one line two" in out
    assert "\n\n" in out


# -------------------------------------------------------------------- chunking


def text_of(n: int) -> str:
    return "\n\n".join(
        " ".join(f"Sentence {i} of paragraph {p}." for i in range(12)) for p in range(n)
    )


def test_chunks_respect_the_size_limit():
    chunks = chunk_text(text_of(30), source="doc", chunk_chars=600, overlap_chars=0)
    assert all(c.chars <= 600 for c in chunks)
    assert len(chunks) > 1


def test_chunks_carry_ids_and_source():
    chunks = chunk_text(text_of(10), source="My Book", chunk_chars=500, overlap_chars=0)
    assert chunks[0].id.startswith("my-book-")
    assert all(c.source == "My Book" for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_overlap_repeats_the_end_of_the_previous_chunk():
    chunks = chunk_text(text_of(20), source="doc", chunk_chars=600, overlap_chars=120)
    assert len(chunks) > 1
    tail_word = chunks[0].split()[-1] if hasattr(chunks[0], "split") else chunks[0].text.split()[-1]
    assert tail_word in chunks[1].text


def test_overlap_never_starts_mid_word():
    for chunk in chunk_text(text_of(20), source="doc", chunk_chars=600, overlap_chars=120)[1:]:
        first = chunk.text.split()[0]
        assert first[0].isalnum() or first[0] in "\"'«“(["


def test_no_content_is_lost():
    source = text_of(15)
    joined = " ".join(c.text for c in chunk_text(source, source="doc", chunk_chars=700, overlap_chars=0))
    assert set(source.split()) == set(joined.split())


def test_sections_never_share_a_chunk():
    """A chunk must belong to exactly one section, or its label would be wrong."""
    chunks = chunk_sections(
        [("Chapter 1", text_of(3)), ("Chapter 2", text_of(3))],
        source="doc",
        chunk_chars=5000,
        overlap_chars=0,
    )
    assert {c.section for c in chunks} == {"Chapter 1", "Chapter 2"}
    for chunk in chunks:
        assert not ("Chapter 1" in chunk.section and "Chapter 2" in chunk.section)


def test_indexes_stay_sequential_across_sections():
    chunks = chunk_sections(
        [("A", text_of(6)), ("B", text_of(6))], source="doc", chunk_chars=500, overlap_chars=0
    )
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_an_overlap_as_large_as_the_chunk_is_refused():
    with pytest.raises(ValueError):
        chunk_text("text", source="doc", chunk_chars=500, overlap_chars=500)


def test_a_tiny_chunk_size_is_refused():
    with pytest.raises(ValueError):
        chunk_text("text", source="doc", chunk_chars=50)


def test_empty_text_produces_no_chunks():
    assert chunk_text("   ", source="doc") == []


def test_jsonl_is_one_object_per_line(tmp_path):
    chunks = chunk_text(text_of(10), source="doc", chunk_chars=500, overlap_chars=0)
    path = write_jsonl(chunks, tmp_path / "out.jsonl")

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == len(chunks)

    first = json.loads(lines[0])
    assert {"id", "text", "index", "source", "chars"} <= set(first)
    assert first["chars"] == len(first["text"])

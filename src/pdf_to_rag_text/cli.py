"""Command line interface."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .convert import convert, write
from .extract import ExtractionError

log = logging.getLogger("pdf_to_rag_text")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf2rag",
        description=(
            "Turn a PDF into clean text for a retrieval system: running headers, "
            "footers and page numbers removed, hyphenation rejoined."
        ),
        epilog=(
            "Run --inspect first on a long document. It reports what would be "
            "treated as page furniture without writing anything."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("source", nargs="+", help="One or more PDF files.")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output file, or a directory when converting several PDFs. "
        "Defaults to the .txt beside each source.",
    )

    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Report what would be removed, write nothing.",
    )

    parser.add_argument(
        "--min-repeats",
        type=int,
        default=6,
        help="Pages a line must appear on to count as a running header.",
    )
    parser.add_argument(
        "--strip",
        action="append",
        default=None,
        metavar="LINE",
        help="An exact line to remove as well. Repeatable.",
    )
    parser.add_argument("--keep-page-numbers", action="store_true")
    parser.add_argument(
        "--keep-line-breaks",
        action="store_true",
        help="Keep the PDF's own line wrapping instead of reflowing paragraphs.",
    )

    parser.add_argument("--markdown", action="store_true", help="Emit headings and a table of contents.")
    parser.add_argument("--chunk", action="store_true", help="Also produce retrieval chunks.")
    parser.add_argument("--chunk-chars", type=int, default=1200, help="Target chunk size.")
    parser.add_argument("--overlap", type=int, default=150, help="Characters repeated between chunks.")
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="Write chunks as JSON Lines beside the text. Implies --chunk.",
    )

    parser.add_argument("--ocr-language", default=None, help="Tesseract code for scans, e.g. eng, fra.")
    parser.add_argument("--first-page", type=int, default=None)
    parser.add_argument("--last-page", type=int, default=None)
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    level = logging.WARNING if args.quiet else (logging.DEBUG if args.verbose else logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)-7s %(message)s")

    sources = [Path(s).expanduser() for s in args.source]
    missing = [s for s in sources if not s.is_file()]
    if missing:
        for path in missing:
            print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    if args.output and len(sources) > 1 and Path(args.output).suffix:
        print(
            "error: --output must be a directory when converting several files.",
            file=sys.stderr,
        )
        return 2

    failures = 0
    for source in sources:
        try:
            result = convert(
                source,
                ocr_language=args.ocr_language,
                min_repeats=args.min_repeats,
                extra_headers=args.strip,
                keep_page_numbers=args.keep_page_numbers,
                keep_line_breaks=args.keep_line_breaks,
                markdown=args.markdown,
                chunk=args.chunk or args.jsonl,
                chunk_chars=args.chunk_chars,
                overlap_chars=args.overlap,
                first_page=args.first_page,
                last_page=args.last_page,
            )
        except ExtractionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failures += 1
            continue

        if not args.quiet:
            print()
            print(result.describe())
            print()

        if args.inspect:
            continue

        suffix = ".md" if args.markdown else ".txt"
        if args.output is None:
            destination = source.with_suffix(suffix)
        elif len(sources) > 1 or not Path(args.output).suffix:
            destination = Path(args.output) / (source.stem + suffix)
        else:
            destination = Path(args.output)

        for path in write(result, destination, jsonl=args.jsonl):
            print(f"Wrote {path}")

    if args.inspect:
        print("Inspection only, nothing was written.")

    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Getting text out of a PDF, one page at a time.

Pages are kept separate all the way through the pipeline rather than being
joined immediately, because almost every useful cleaning step needs to compare
pages against each other. Running headers can only be found by noticing that the
same line appears on page after page, and once the pages are concatenated that
signal is gone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


class ExtractionError(RuntimeError):
    """The PDF could not be read."""


@dataclass
class Page:
    number: int  # 1-based, as printed
    text: str

    @property
    def is_empty(self) -> bool:
        return len(self.text.strip()) < 20


@dataclass
class RawDocument:
    path: Path
    pages: list[Page] = field(default_factory=list)
    used_ocr: bool = False

    @property
    def title(self) -> str:
        return self.path.stem


def read_pdf(
    path: str | Path,
    *,
    ocr_language: str | None = None,
    ocr_dpi: int = 200,
    first_page: int | None = None,
    last_page: int | None = None,
) -> RawDocument:
    """Read a PDF into pages of text, falling back to OCR when there is no text layer.

    Args:
        path: the PDF.
        ocr_language: Tesseract language code, e.g. ``eng`` or ``fra``. Without
            it, a scanned PDF raises rather than returning an empty document.
        ocr_dpi: rendering resolution for OCR. 200 is the point where Tesseract
            accuracy stops improving much and speed starts to hurt.
        first_page, last_page: 1-based inclusive range, for testing a setting on
            part of a long book before committing to the whole thing.
    """
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ExtractionError(f"File not found: {path}")

    try:
        import pymupdf as fitz  # PyMuPDF 1.24+
    except ImportError:  # pragma: no cover - older PyMuPDF
        try:
            import fitz
        except ImportError as exc:
            raise ExtractionError(
                "Reading PDFs needs PyMuPDF. Run: pip install pymupdf"
            ) from exc

    with fitz.open(path) as doc:
        start = (first_page - 1) if first_page else 0
        end = last_page if last_page else len(doc)
        indices = range(max(0, start), min(len(doc), end))
        pages = [Page(number=i + 1, text=doc[i].get_text("text")) for i in indices]

        if not _looks_scanned(pages):
            return RawDocument(path=path, pages=pages)

        if not ocr_language:
            raise ExtractionError(
                f"{path.name} has no usable text layer, so it is probably a scan. "
                f"Pass --ocr-language (eng, fra, deu...) to run OCR. "
                f"That also needs Tesseract installed."
            )

        log.info("No text layer found, running OCR on %d page(s)", len(indices))
        ocr_pages = [
            Page(number=i + 1, text=_ocr_page(doc[i], ocr_language, ocr_dpi)) for i in indices
        ]

    return RawDocument(path=path, pages=ocr_pages, used_ocr=True)


def _looks_scanned(pages: list[Page], sample: int = 10, threshold: float = 0.8) -> bool:
    """True when most sampled pages carry almost no text.

    Sampling spreads across the document instead of reading the first few pages.
    A scanned book often has a typeset title page, and a born-digital PDF often
    opens with a full-page image; either would fool a check that only looks at
    the front.
    """
    if not pages:
        return True
    step = max(1, len(pages) // sample)
    sampled = pages[::step][:sample]
    return sum(1 for p in sampled if p.is_empty) / len(sampled) >= threshold


def _ocr_page(page, language: str, dpi: int) -> str:
    try:
        import io

        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise ExtractionError(
            "OCR needs pytesseract and Pillow, plus the Tesseract binary. "
            "Run: pip install pytesseract pillow"
        ) from exc

    pixmap = page.get_pixmap(dpi=dpi)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    return pytesseract.image_to_string(image, lang=language)

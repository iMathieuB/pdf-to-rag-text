# pdf-to-rag-text

Turn a PDF into clean text for a retrieval system, with the page furniture removed.

Extract a book with a standard library and every chunk of the result carries the running header, the footer and the page number that appeared on that page. Feed that to a RAG index and the damage compounds: identical boilerplate in every chunk pulls unrelated passages toward each other in embedding space, and a search for the book's own title matches everything equally well.

This removes it, and shows you what it removed.

```bash
pip install pdf-to-rag-text
pdf2rag book.pdf --inspect
```

```
Source        book.pdf
Pages         412
Characters    684,203

Running headers found   3
Header lines removed    806
Page numbers removed    409
Hyphenations rejoined   1,204
Garbage lines removed   17

Treated as page furniture:
  Designing Data-Intensive Applications
  Chapter 5: Replication
  www.example-publisher.com
```

Nothing is written by `--inspect`. Read the list, decide whether it is right, then run it for real.

## Why statistics rather than rules

Every book puts something different in its header. There is no pattern that catches "Chapter 5: Replication" on one book and "PART TWO" on the next without also eating real content.

So headers are found by evidence instead. A line that appears near the top or bottom of many pages is furniture, whatever it says. Only the edges of each page are examined, because body text is not furniture however often it repeats, and each line counts once per page, so a header that also appears mid-page does not inflate its own score.

`--min-repeats` is the dial. The default of six is cautious. Lower it for a short document, raise it if the report shows real content being removed.

### The one thing to watch

A chapter title on a long chapter is genuinely ambiguous. If "Chapter 5: Replication" heads sixty consecutive pages, it looks exactly like a running header, and it is one. Whether you want it removed depends on what you are building: for retrieval you usually do, since the heading belongs in chunk metadata rather than repeated in the text.

That is why `--inspect` exists and why the report lists every line it treated as furniture. Do not skip it on a document that matters.

## What else it fixes

**Page numbers**, in the shapes they actually appear: `42`, `- 42 -`, `[42]`, `xiv`, `page 42`.

**Hyphenation across line breaks.** Justified typesetting splits words at the right margin, and left alone `auto-\nmation` stays two tokens that never match a search for `automation`. Only lowercase-to-lowercase joins are made, so a real compound like `Franco-\nAmerican` keeps its hyphen.

**Line breaks inside paragraphs.** A PDF breaks lines wherever the column ended, which has nothing to do with the sentences. Paragraphs are reflowed so chunking can cut at meaningful boundaries. `--keep-line-breaks` turns this off.

**OCR noise.** Lines that are mostly punctuation, from rules, borders and scan artefacts.

**Scanned PDFs.** Pages are sampled across the whole document and measured. Sampling matters: a scanned book often has a typeset title page, and a born-digital PDF often opens with a full-page image, so a check that only reads the front is fooled either way. When there is no text layer, pass `--ocr-language` to run OCR, or the tool tells you rather than writing an empty file.

## Chunking

```bash
pdf2rag book.pdf --jsonl --chunk-chars 1200 --overlap 150
```

Produces `book.txt` and `book.jsonl`, one JSON object per line:

```json
{"id": "book-00042", "text": "...", "index": 42, "source": "book", "section": "", "chars": 1187}
```

Two properties decide whether retrieval works.

**Chunks are semantically whole.** Splits are made at paragraph boundaries where possible and sentence boundaries when a paragraph is too long. A chunk that starts halfway through an argument and stops halfway through the next embeds as a blur of both and answers neither question well.

**Chunks carry context.** `--overlap` repeats the end of one chunk at the start of the next, cut back to a word boundary so a chunk never opens mid-word. A passage beginning "This is why it fails" is useless once separated from what "it" was.

`chunk_sections()` in the library keeps a chunk from ever spanning two sections, so the heading stored beside it is always accurate.

## Markdown

```bash
pdf2rag book.pdf --markdown
```

Detects `Part II`, `Chapter 7`, `3. Method` and `3.2 Results`, emits them as `#` headings, and prepends a table of contents. Useful because retrieval tools increasingly split on heading level.

## Options

```
source                  One or more PDF files
-o, --output PATH       Output file, or a directory for several inputs

--inspect               Report what would be removed, write nothing
--min-repeats N         Pages a line must appear on to count as furniture (default 6)
--strip LINE            An exact line to remove as well. Repeatable
--keep-page-numbers     Leave page numbers in
--keep-line-breaks      Keep the PDF's own line wrapping

--markdown              Emit headings and a table of contents
--chunk                 Produce retrieval chunks
--chunk-chars N         Target chunk size (default 1200)
--overlap N             Characters repeated between chunks (default 150)
--jsonl                 Write chunks as JSON Lines. Implies --chunk

--ocr-language CODE     Tesseract code for scans, e.g. eng, fra
--first-page N          1-based, inclusive
--last-page N           Try a setting on part of a long book first
```

## As a library

```python
from pdf_to_rag_text import convert, write

result = convert("book.pdf", chunk=True, chunk_chars=1000)
print(result.report.describe())

for chunk in result.chunks[:3]:
    print(chunk.id, chunk.chars, chunk.text[:80])

write(result, "book.txt", jsonl=True)
```

The pieces work on their own: `read_pdf` for pages with OCR fallback, `find_repeated_lines` to detect furniture without removing it, `chunk_text` to split any text with overlap.

## Install

```bash
pip install pdf-to-rag-text            # PDF reading included
pip install "pdf-to-rag-text[ocr]"     # plus OCR for scans
```

OCR also needs the [Tesseract](https://github.com/tesseract-ocr/tesseract) binary.

## Development

```bash
pip install -e ".[dev]"
pytest
```

24 tests, none needing a PDF: the cleaner and the chunker work on page objects, so their behaviour is asserted directly. The tests cover the cases worth getting right, including that a real compound word keeps its hyphen, that a chunk never spans two sections, and that an overlap never begins mid-word.

## Licence

MIT. See [LICENSE](LICENSE).

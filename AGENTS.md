# Instructions for an AI agent

You are converting PDFs to clean Markdown or plain text with `pdf2rag`. Read this once, then work from the recipe.

## Install

Not on PyPI. Install from the repository, into the project's own environment:

```bash
pip install "git+https://github.com/iMathieuB/pdf-to-rag-text.git"
```

Check it landed: `pdf2rag --help`. Python 3.10 or newer. PyMuPDF is the only required dependency and ships as a wheel, so there is no compiler step. Scanned PDFs additionally need the Tesseract binary and the `[ocr]` extra; without both, a scan is refused with a clear message rather than silently producing an empty file.

## The one rule that matters

**Run `--inspect` before converting anything you have not converted before, and read what it prints.**

```bash
pdf2rag report.pdf --inspect
```

It writes nothing. It reports how many characters came out, and lists every line it intends to treat as page furniture. That list is the output you must actually check, because it is where this tool can be wrong.

Headers are detected statistically, not by pattern: a line appearing near the top or bottom of many pages is furniture whatever it says. That is what makes it work across publishers, and it is also what makes one case ambiguous — a chapter title running on sixty consecutive pages looks exactly like a running header. If `--inspect` lists something that is real content, raise `--min-repeats`. If it misses the header on a short document, lower it. The default is 6.

Do not skip this step on a document batch that matters, and do not present converted text to the user as correct without having read the furniture list at least once for that document's layout.

## Converting to Markdown

```bash
pdf2rag report.pdf --markdown -o out/
```

Writes `out/report.md`. With `--markdown` the output gets `#` headings and, when there are three or more of them, a table of contents. Without it the output is `.txt`.

Headings are recognised in these shapes: `Part II` / `Partie II`, `Chapter 7` / `Chapitre 7`, `3. Method`, `3.2 Results`. A document that numbers its sections differently produces no headings; that is a limit of the detector, not an error, and the body text is still cleaned correctly.

Several files at once, with `-o` as a directory:

```bash
pdf2rag *.pdf --markdown -o out/
```

## What it does to the text

Running headers, footers and page numbers removed. Hyphenation rejoined across line breaks, lowercase to lowercase only, so `Franco-American` keeps its hyphen. Paragraphs reflowed onto single lines, because a PDF breaks lines where the column ended rather than where the sentence did. OCR noise, lines that are mostly punctuation, dropped.

Pass `--keep-line-breaks` only if the caller specifically wants the PDF's own wrapping. It makes the Markdown harder to read and worse to chunk.

## Retrieval chunks

Only when the caller asked for a RAG index, not by default:

```bash
pdf2rag report.pdf --jsonl --chunk-chars 1200 --overlap 150
```

Writes the text plus a `.jsonl`, one object per line: `{"id", "text", "index", "source", "section", "chars"}`. Splits land on paragraph boundaries, falling back to sentences; `--overlap` repeats the tail of one chunk at the head of the next, cut back to a word boundary.

## Scanned PDFs

If a PDF has no text layer the tool says so and stops. Do not work around it by returning an empty file. Either install Tesseract and pass the language, or report back that the document is a scan:

```bash
pdf2rag scan.pdf --ocr-language fra --markdown -o out/
```

Language codes are Tesseract's: `eng`, `fra`, `deu`, `spa`.

## Trying a setting cheaply

On a long document, test on a slice before committing:

```bash
pdf2rag book.pdf --first-page 40 --last-page 60 --inspect
```

## Exit codes and failures

`0` success, `1` at least one file failed to convert, `2` bad arguments or a missing file. Errors go to stderr with a message naming the file. A failure on one file in a batch does not stop the others.

## What to report back

The conversion summary (pages, characters, what was removed), where the files were written, and anything in the furniture list that looked like real content. If you raised or lowered `--min-repeats`, say so and why — the next run on that document should use the same value.

# PDF OCR Unified Recognition Design

Date: 2026-07-28

## Goal

Replace both existing PDF text-extraction points with the iFlytek PDF OCR service, and extend recognition to all supported formats through a single pipeline:

1. Every supported document (PDF, PPT, PPTX, DOCX, TXT, MD) is converted to PDF when it is not one already.
2. The PDF is sent to the iFlytek PDF OCR API, which returns structured Markdown (text, formulas, tables).
3. The Markdown text flows into the existing chunk → embed → index pipeline unchanged.
4. Scanned/image-only PDFs and PPT courseware — currently invisible to PyMuPDF — become fully indexable.

This reverses the 2026-07-20 ingestion design, which declared PPT/PPTX and OCR out of scope. The arrival of `knowledge/新增书本与PPT/` (3 PPT + 2 PPTX + scanned courseware) motivates the change.

## Strategy (user-directed)

**All formats go through PDF OCR.** Local extraction (PyMuPDF / python-docx / plain read) is demoted to a failure fallback so the pipeline never dead-ends when conversion or OCR is unavailable — it is no longer the primary path.

Trade-off accepted by the user: TXT/MD are already plain text, so routing them through render → OCR adds latency and per-page cost with no quality gain. The code path stays uniform anyway; the fallback preserves correctness if OCR fails.

## Current State

Two extraction points are replaced:

| Location | Function | Current behavior |
|---|---|---|
| `app/ingest/reader.py` | `_read_pdf` | PyMuPDF text layer only; `""` on failure |
| `chat_ui.py` | `read_pdf` | Same, duplicated inline |

Reference implementation: root `pdf_ocr.py` (standalone batch script). Official API reference: `docs/官网文档/讯飞_PDF_OCR_API.md`.

Environment facts verified on the dev machine:

- `soffice` (LibreOffice) at `/opt/homebrew/bin/soffice` — used for →PDF conversion.
- All 25 existing PDFs are ≤ 100 pages (max 97), within the API limit.
- `.env` already contains `XF_PDFOCR_APP_ID` and `XF_PDFOCR_API_SECRET`.

## Data Flow

```text
source file (.pdf/.ppt/.pptx/.docx/.txt/.md)
  → converter.to_pdf()            # .pdf passes through; others via soffice --headless --convert-to pdf
  → OCR cache lookup by source SHA-256     # hit → return cached Markdown
  → IflytekPdfOcrClient.ocr_pdf()
        POST /ocrzdq/v1/pdfOcr/start  (multipart, exportFormat=markdown)
        GET  /ocrzdq/v1/pdfOcr/status (poll every 5s until FINISH/FAILED)
        GET  downUrl                  (double-UTF-8 fix, strip base64 images)
  → write cache → return Markdown text

Any failure at any step → local fallback extraction + warning log
```

## Components

### `app/clients/iflytek_pdf_ocr.py` (new)

`IflytekPdfOcrClient` — synchronous `requests`-based client (matches `pdf_ocr.py`; the ingestion CLI and the threaded demo server are both sync call sites).

- `ocr_pdf(pdf_path: Path) -> str` — full start → poll → download → decode-fix → clean cycle; returns Markdown text.
- Auth: `appId` / `timestamp` / `signature` headers, `Base64(HmacSHA1(MD5(appId+timestamp), secret))` — the project's third distinct iFlytek auth scheme, do not merge with the Embedding HMAC-SHA256 scheme.
- Download quirk: response is double-UTF-8 encoded; fix via `.decode("utf-8").encode("latin-1").decode("utf-8")` with plain-decode fallback.
- `clean_markdown`: strip `![img](data:image/...)` blobs and ≥200-char base64 runs, compress blank lines.
- Typed errors: `PdfOcrError` with subtypes for upload failure, task failure (`FAILED`/`ANY_FAILED`/`STOP`), poll timeout, and download failure.
- Config: `poll_interval_seconds=5` (API minimum), `max_polls` (default 60 → 5 min ceiling), request timeouts.

### `app/ingest/converter.py` (new)

`to_pdf(path: Path, work_dir: Path) -> Path`

- `.pdf` → returned as-is.
- Other supported formats → `soffice --headless --convert-to pdf --outdir work_dir`, with subprocess timeout (default 120 s) and non-zero-exit / missing-output detection.
- `.md` converts as plain text (LibreOffice does not render Markdown syntax; raw markers are acceptable for knowledge extraction).
- Raises `ConversionError` on missing soffice, timeout, or failed conversion → caller falls back.

### OCR result cache

- Directory `ocr_cache/` at repo root (gitignored), shared by both call sites.
- Key: SHA-256 of the **source** file → `ocr_cache/<sha256>.md`.
- Only successful OCR results are cached; fallback results are never cached (a later run may restore OCR availability).
- Purpose: rebuilding a vector store from scratch (the current base store is empty) must not re-bill OCR for unchanged files.

### `app/ingest/reader.py` (modified)

- `SUPPORTED_EXTENSIONS` gains `.ppt`, `.pptx`; `app/ingest/scanner.py` imports the constant, so scanning extends automatically.
- `read_file` becomes: `to_pdf` → cache lookup → OCR → cache store → return text; on `ConversionError`/`PdfOcrError` → legacy local extraction (existing `_read_pdf`/`_read_docx`/`_read_text_file`, kept as private fallbacks) with a warning log.
- Local fallback for PPT/PPTX is `""` (no local parser) — the file is skipped, same as any unreadable document today.

### `app/core/config.py` (modified)

New Settings fields, following the existing `xf_*` pattern:

- `xf_pdfocr_app_id: str` — read from `XF_PDFOCR_APP_ID`; when unset, falls back to the `XF_APP_ID` value (same iFlytek app)
- `xf_pdfocr_api_secret: SecretStr`
- `pdf_ocr_poll_interval_seconds: float = 5.0`, `pdf_ocr_max_polls: int = 60`, `pdf_ocr_enabled: bool = True`

When `pdf_ocr_enabled` is false, `read_file` skips conversion/OCR entirely and uses local extraction directly (kill switch for quota exhaustion or API outages).

`.env` already provides the two credential values. `docs/官网文档/项目凭据与配置.md` gains a PDF OCR section.

### `ingest_knowledge.py` (modified)

- Builds one `IflytekPdfOcrClient` from env at ingestion start and passes it into the read step (env-driven, same style as the embedding credentials block).
- `PARSER_VERSION` bumped to `2026-07-28`: extraction output changes for the same file hash, so manifest reuse keyed on the old parser version must not carry PyMuPDF-era embeddings forward.

### `chat_ui.py` (modified)

Stays a single self-contained file (per its design intent):

- Inline compact `_to_pdf()` (subprocess soffice) and `_ocr_pdf()` (same API flow as the client, `requests`-based), sharing `ocr_cache/`.
- `read_document` routes every upload through the OCR pipeline with local fallback.
- Upload `<input>` accepts `.ppt`/`.pptx` in addition to current formats.
- Upload endpoint already runs on `ThreadingMixIn` worker threads, so multi-minute OCR of one file does not block the server; the browser toast already covers the wait.

## Error Handling

| Failure | Behavior |
|---|---|
| soffice missing / timeout / non-zero exit | `ConversionError` → local fallback + warning |
| OCR upload HTTP/API error | `PdfOcrError` → local fallback + warning |
| Task `FAILED` / `ANY_FAILED` / `STOP` | `PdfOcrError` → local fallback + warning |
| Poll exceeds `max_polls` | `PdfOcrError` → local fallback + warning |
| PDF > 100 pages or encrypted (API rejection) | `PdfOcrError` → local fallback + warning (PyMuPDF often still reads the text layer) |
| Download/decode failure | `PdfOcrError` → local fallback + warning |
| Local fallback also fails | `""` → file skipped, counted in `files_skipped` (existing behavior) |

Splitting >100-page PDFs into sub-documents for OCR is explicitly out of scope for v1 (no current file needs it).

## Testing

Per project convention (README: ingestion behavior changes get tests first):

- `tests/unit/test_pdf_ocr_client.py` — mocked `requests`: signature construction, poll state machine (CREATE→DOING→FINISH / FAILED / timeout), double-UTF-8 fix, `clean_markdown`, every error subtype.
- `tests/unit/test_converter.py` — mocked `subprocess`: passthrough for `.pdf`, command construction, timeout, missing soffice, missing output file.
- `tests/unit/test_reader.py` (extend) — OCR success path, cache hit (no API call), OCR failure → fallback, unsupported extension, PPT/PPTX routing.
- `tests/online/test_pdf_ocr_online.py` — `online`-marked, one small real PDF through the live API.
- `chat_ui.py` — manual verification (upload PPT + scanned PDF, confirm answers cite them).

## Out of Scope

- >100-page PDF splitting for OCR.
- Async OCR client (no async call site exists today).
- OCR for images embedded inside already-textual PDFs beyond what the API returns inline.
- Repairing the separately-broken `app/domain` import in `app/main.py` and the empty base vector store (tracked as follow-up work; this design's ingestion run will regenerate the store).

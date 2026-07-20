# RAG Project Knowledge Ingestion Design

Date: 2026-07-20

## Goal

Build a development-stage ingestion loop for project-scoped RAG knowledge:

1. The product keeps a built-in grain-storage knowledge base.
2. A user can add files to a project-local knowledge space.
3. The ingestion script parses, chunks, embeds, and publishes the new project vector store.
4. Retrieval for a project uses the built-in base knowledge plus that project only.
5. Other projects' uploaded documents are not visible during retrieval.

This design covers PDF, DOCX, TXT, and Markdown. PPTX, legacy binary PPT, and OCR for scanned/image-only files are out of scope for v1.

## Design Philosophy

The ingestion pipeline follows a thin-local, heavy-model principle:

- **Local code does format routing and lightweight text extraction only.** It opens a file, pulls out whatever text is trivially available, and hands it to the embedding model. It does not attempt semantic cleaning, table reconstruction, layout analysis, or OCR.
- **The iFlytek Embedding model is the core intelligence.** It handles varying text quality, mixed formatting, fragmented bullet points, and noise — capabilities that local heuristic code cannot match. Chunking exists only to stay within the model's token window, not to "improve" the text.
- **Don't fix bad input locally — let the model handle it.** If extracted text is messy, the embedding model still produces a valid 2560-dim vector that participates in cosine search. Bad text yields low-relevance scores at query time, which is the correct failure mode.
- **No local NLP, no hand-crafted cleaning rules.** The pipeline avoids introducing bias or information loss through well-intentioned but brittle local transformations.

## Open-Source Cases Reviewed

The design follows patterns found in current open-source or open RAG products:

- Dify separates knowledge bases, uploaded documents, asynchronous indexing, document metadata, and indexing status. Its document upload returns a batch ID and indexing advances through stages such as waiting, parsing, cleaning, splitting, indexing, and completed. Source: https://docs.dify.ai/en/api-reference/guides/knowledge and https://docs.dify.ai/en/api-reference/documents/get-document-indexing-status
- AnythingLLM treats a workspace as the visibility boundary: the LLM only sees documents embedded into that workspace. Uploading a document first turns it into text; moving it into a workspace chunks, embeds, and stores vectors. Source: https://docs.anythingllm.com/chatting-with-documents/rag-in-anythingllm
- AnythingLLM's user model confirms the product direction: normal users can only chat with workspaces they are explicitly added to. In this repository we do not implement login yet, but the retrieval boundary should be shaped the same way. Source: https://docs.anythingllm.com/features/security-and-access
- AnythingLLM's live document sync is useful as a warning: automatic re-embedding can increase embedder cost and should be observable and limited. Our v1 uses explicit script runs, file hashes, and clear status output instead of an always-on watcher. Source: https://docs.anythingllm.com/beta-preview/active-features/live-document-sync
- LlamaIndex and Qdrant show two viable multi-tenant patterns: metadata-filtered shared indexes and payload partitioning. Pinecone's Namespace Notes demonstrates workspace isolation with vector namespaces. Since this codebase currently uses local sklearn artifacts, v1 should use separate on-disk stores per project, while keeping metadata fields ready for a future shared vector DB. Sources: https://developers.llamaindex.ai/python/examples/multi_tenancy/multi_tenancy_rag/, https://qdrant.tech/documentation/examples/llama-index-multitenancy/, and https://docs.pinecone.io/examples/sample-apps/namespace-notes

## Product Model

The product has two library scopes:

- `base`: built-in grain-storage knowledge shipped by the product.
- `project:<project_id>`: documents uploaded into one project.

During development there is no login module. `project_id` is therefore a logical isolation key supplied by the caller, not a production authorization guarantee. The design still avoids cross-project leakage by making the retriever load only:

- `vector_store/base`
- `vector_store/projects/<project_id>`

When login exists later, auth should validate that the signed-in user may access the requested `project_id` before the request reaches retrieval.

## Directory Layout

Keep the existing base documents in `knowledge/` to avoid a migration. Reserve `knowledge/projects/` for project uploads.

```text
knowledge/
  *.pdf
  *.docx
  other-base-folders/
  projects/
    <project_id>/
      uploaded-file.pdf
      uploaded-report.docx

vector_store/
  base/
    vectors.npy
    chunks_metadata.json
    manifest.json
    ingest_report.json
  projects/
    <project_id>/
      vectors.npy
      chunks_metadata.json
      manifest.json
      ingest_report.json
```

Base ingestion scans `knowledge/` but excludes `knowledge/projects/`.

Project ingestion scans only `knowledge/projects/<project_id>/`.

## Script Entry Points

Add a script that corresponds to the future upload-to-knowledge-base feature:

```bash
python ingest_knowledge.py --project-id demo --source /path/to/file.pdf
```

The script validates the project ID, validates the file type, copies the source file into `knowledge/projects/<project_id>/`, then continues the vectorization process for that project.

Additional script modes:

```bash
python ingest_knowledge.py --project-id demo
python ingest_knowledge.py --scope base
python ingest_knowledge.py --scope all-projects
```

Behavior:

- `--project-id demo --source file`: import or replace one project file, then rebuild only `vector_store/projects/demo`.
- `--project-id demo`: rescan `knowledge/projects/demo` and rebuild changed project chunks.
- `--scope base`: rebuild `vector_store/base` from built-in files under `knowledge/`, excluding `knowledge/projects/`.
- `--scope all-projects`: rebuild every existing project directory. This is for maintenance, not the normal upload path.

For same-name uploads, the relative path is the document identity. A new file with the same name replaces the old content for that project. If the content hash is unchanged, ingestion skips embedding and republishes nothing.

## Ingestion Pipeline

The existing `build_vector_store.py` owns the mature parts of the pipeline: file walking, cleaning, semantic chunking, iFlytek embeddings, sklearn index creation, artifact saving, and atomic publishing. The implementation should keep that logic and split it into reusable units instead of duplicating it.

Pipeline stages:

1. Resolve scope.
2. Validate filesystem boundary and skip symlinks.
3. Parse supported formats with lightweight extraction only:
   - PDF: PyMuPDF text extraction.
   - DOCX: `python-docx` paragraphs and tables.
   - TXT and Markdown: UTF-8 text reader with `errors="ignore"` matching current behavior.
   - Unsupported extensions (`.ppt`, `.pptx`, images): skip with report entry.
   - Supported format but extracted zero text (e.g. scanned PDF): skip with report entry.
   - No local text cleaning, layout reconstruction, or semantic preprocessing.
4. Clean and chunk text with the existing chunking rules.
5. Calculate SHA-256 for every source file.
6. Reuse previous embeddings for unchanged documents whose parser version, chunking config, and embedding model config still match the manifest.
7. Embed only new or changed chunks.
8. Rebuild a complete sklearn index for that scope from reused and newly embedded vectors.
9. Write vectors.npy and chunks_metadata.json to a staging directory, then atomically swap into the active store path. The Embedding model either returns valid 2560-dim vectors or errors — no additional local validation of the written artifacts is needed.
10. Write `manifest.json` and `ingest_report.json` into the published store.

## Incremental State

Each published vector store contains a `manifest.json`:

```json
{
  "schema_version": 1,
  "scope": "project",
  "project_id": "demo",
  "source_root": "knowledge/projects/demo",
  "embedding_dimension": 2560,
  "embedding_provider": "iflytek",
  "embedding_url": "https://emb-cn-huabei-1.xf-yun.com/",
  "chunk_size": 600,
  "chunk_overlap": 100,
  "parser_version": "2026-07-20",
  "documents": {
    "uploaded-file.pdf": {
      "sha256": "hex",
      "mtime_ns": 0,
      "size_bytes": 0,
      "status": "indexed",
      "chunk_count": 8
    }
  }
}
```

The manifest is not trusted blindly. A document is reusable only when all of these match:

- current relative path exists under the expected source root;
- SHA-256 is unchanged;
- parser version is unchanged;
- chunk size and overlap are unchanged;
- embedding provider, endpoint, and vector dimension are unchanged.

Deleted files are removed from the new store because the rebuilt full index contains only currently present documents. Bad files are recorded in `ingest_report.json` and do not poison the active store. If all files in a scope fail or yield no text, publishing stops and the previous store remains active.

## Runtime Retrieval

Introduce a small project-aware layer above the existing `VectorStore` and `Retriever`.

Conceptual components:

- `VectorStoreRegistry`: loads `base` and project stores by path, caches loaded stores, and can reload after process restart.
- `CompositeVectorStore`: searches multiple loaded stores and merges scored hits.
- `ProjectRetriever`: embeds the query once, searches base plus the requested project, sorts by score, applies existing filters, and returns the top results.

Public and tool schemas gain optional `project_id`:

- `ChatRequest.project_id`
- `CaseAnalyzeRequest.project_id`
- `RetrieveRequest.project_id`

Development default:

- Missing `project_id` means base-only retrieval.
- Provided `project_id` means base plus `project_id`.

The workflow gateway should pass `project_id` into the retrieve tool call so the tool layer keeps the isolation decision near retrieval. Existing citation validation can remain unchanged because it validates the evidence list already returned by retrieval.

## Visibility Rules

For request `project_id = demo`:

- Search `vector_store/base` if available.
- Search `vector_store/projects/demo` if available.
- Never search `vector_store/projects/other`.
- Evidence metadata includes `scope` and `project_id` so logs and tests can prove where each chunk came from.

If the project store is missing, retrieval still uses base knowledge and marks response quality from base hits. Missing project store is not a service-wide readiness failure during development, because users can create a new empty project before uploading documents.

If the base store is missing but the project store exists, retrieval may run with project-only knowledge. `/ready` should report partial readiness instead of the current single-store binary state.

## Error Handling And Observability

The ingestion script exits non-zero when:

- credentials are missing;
- project ID is invalid;
- the source file is outside an allowed path after resolution;
- the file extension is unsupported;
- every candidate file fails parsing or produces empty text;
- embedding fails after retries;
- failed to write final vector artifacts to disk.

The script exits zero with warnings when at least one document publishes successfully and some files are skipped. `ingest_report.json` records:

- scope and project ID;
- started and completed timestamps;
- files scanned, indexed, reused, replaced, deleted, skipped, and failed;
- chunk count and embedding count;
- published vector path;
- warnings without secrets or raw provider payloads.

Logs must never print iFlytek credentials, auth headers, `.env` values, or raw provider responses.

## Testing Strategy

Unit tests:

- project ID validation rejects path traversal, slashes, absolute paths, blank IDs, and hidden names;
- scanner excludes `knowledge/projects/` when building base;
- scanner includes only the selected project for project ingestion;
- parser routes `.pdf`, `.docx`, `.txt`, and `.md`;
- unsupported `.ppt`, `.pptx`, and image-only/empty files are skipped with report entries;
- unchanged file hashes reuse embeddings;
- changed files re-embed only changed documents;
- deleted files disappear from the new metadata;
- manifest mismatch forces re-embedding;
- delete all files for a scope and rebuild produces a fresh store (no stale chunks);
- retriever for project A never returns project B chunks.

Contract and integration tests:

- `/tools/v1/retrieve` accepts `project_id` and returns base plus that project;
- `/v1/chat` and `/v1/cases/analyze` pass `project_id` through the gateway;
- `/ready` reports base/project readiness without leaking local paths;
- service restart sees a newly published project store.

Online tests:

- with `RUN_ONLINE=1`, build a tiny fixture project with one TXT/MD file and verify iFlytek embedding, publish, restart load, and retrieval.
- full knowledge rebuild remains manual because it may consume paid embedding quota.

## Non-Goals

- No PPTX parsing in this iteration.
- No legacy binary `.ppt` parsing in this iteration.
- No OCR for scanned/image-only documents in this iteration.
- No login or production authorization module in this iteration.
- No browser upload UI in this iteration.
- No vector database migration in this iteration.
- No hot reload requirement. Newly published stores become visible after service restart in v1; a later iteration can add safe reload endpoints or file watchers.
- No local NLP-based text cleaning, table reconstruction, or semantic preprocessing. The embedding model handles text quality.

## Implementation Boundary

This spec does not authorize implementation yet. After review, the next step is an implementation plan that uses TDD and an isolated worktree. The plan should preserve unrelated local changes, especially `.env.example`, and must not commit vector artifacts or credentials.

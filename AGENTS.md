# AGENTS.md

## Project

Grain-storage vertical-domain assistant using iFlytek ChatDoc as the managed RAG backend. Knowledge files live under `knowledge/` and cover pest control, low-temperature storage, CO2 monitoring, smart granary management, and food-security law.

## Environment

- Always use the conda `LLM` environment (Python 3.11.11).
- In this macOS workspace call `/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python` directly.
- Install packages with `python -m pip`; never use the system Python or plain base-environment `pip`.

## Key commands

```bash
python ingest_chatdoc.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
python -m pytest -m "not online" -q
```

## Active RAG architecture

```text
knowledge/
    -> ingest_chatdoc.py
    -> iFlytek ChatDoc AUTO parse/OCR/chunk/vectorize
    -> artifacts/chatdoc/base.json
    -> app/rag/chatdoc_retriever.py
    -> FastAPI and Xingchen workflow
```

Do not add local document parsing, OCR, chunking, Embedding, sklearn/FAISS indexes, or local vector-store fallbacks. The former local RAG implementation was intentionally deleted. `vector_store/` and `ocr_cache/` may contain legacy data but are not runtime inputs.

## ChatDoc behavior

- Authentication: `MD5(appId + timestamp)` -> `HmacSHA1` with APISecret -> Base64.
- Upload parsing mode: `AUTO` with ChatDoc-managed OCR, splitting, vectorization, hybrid search, and reranking.
- Files over 20 MiB are skipped; the user will split them manually.
- The upload process publishes `artifacts/chatdoc/base.json` and updates `XF_CHATDOC_REPO_ID` only after every accepted file is vectorized and added to the repository.
- Provider errors must be mapped to safe application codes; never expose credentials, auth headers, or raw provider error bodies.

## Credentials

Credentials are loaded from `.env`. ChatDoc currently reads the shared APISecret from `XF_EMBEDDING_API_SECRET`; this name is retained for compatibility only and does not mean the legacy Embedding API is used.

## Current external blocker

The last ChatDoc upload attempt returned provider code `66001` (account quota/balance unavailable). Do not switch the local manifest or repo configuration after a partial upload.

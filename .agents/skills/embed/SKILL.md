---
name: embed
description: Re-run the full vectorization pipeline. Use when documents are added/updated in knowledge/, or the vector store needs rebuilding.
---

## Run the pipeline

```bash
python build_vector_store.py
```

This executes all 6 steps: read docs → clean → chunk → vectorize (via iFlytek Embedding API) → build sklearn index → interactive search test.

## Before running

- Confirm the conda env `ican` is active
- Verify API connectivity: `python test_embedding_api.py`
- Ensure documents are in `knowledge/` (supports .pdf, .docx, .txt, .md)

## After running

- `vector_store/vectors.npy` — 1023+ × 2560 float32 vectors
- `vector_store/chunks_metadata.json` — text and source metadata

Use `/search-kb` to query the rebuilt store.

## Tuning

Edit `build_vector_store.py` lines 47-48 to adjust chunk parameters:
- `CHUNK_SIZE` — max characters per chunk (default 600)
- `CHUNK_OVERLAP` — overlap between adjacent chunks (default 100)

---
name: search-kb
description: Search the existing vector store interactively. Use to test retrieval quality or find relevant chunks.
---

## Search the knowledge base

```bash
python search_kb.py
```

Loads the pre-built `vector_store/` (vectors + metadata), then opens an interactive query loop. Type queries in Chinese to search the grain storage knowledge base.

## Requirements

- `vector_store/vectors.npy` and `vector_store/chunks_metadata.json` must exist
- If missing, run `/embed` first to build the vector store

## What it does

1. Loads vectors → L2-normalizes → builds sklearn NearestNeighbors index
2. For each query: vectorizes via iFlytek Embedding API (query mode) → cosine similarity search → prints top-3 chunks with scores and sources

Type `quit` to exit.

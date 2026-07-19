# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project

Building a grain storage (粮食储藏) vertical-domain LLM RAG pipeline on iFlytek platform. Knowledge base: 17 documents (PDFs + DOCX, ~475K chars) covering pest control, low-temp storage, CO2 monitoring, smart granary management, and food security law.

## Environment

- Conda env: `LLM` (Python 3.11.11) — always use this environment for every command run in this repository
- Activate with `conda activate LLM`, or call `A:\Anaconda_envs\envs\LLM\python.exe` directly in non-interactive shells
- **CRITICAL**: Use `python -m pip install <pkg>` from the `LLM` environment — plain `pip` points to base conda (Python 3.13), which installs cp313-incompatible wheels
- GPU: RTX 4050 Laptop 8GB (CUDA available, not currently used by the pipeline)

## Key commands

```bash
python test_embedding_api.py      # Verify iFlytek Embedding API connectivity
python build_vector_store.py       # Full pipeline: read docs → chunk → vectorize → index → search
python search_kb.py                # Load existing vector store, interactive search only
```

## Architecture

```
knowledge/ (17 PDFs/DOCX)
    │  build_vector_store.py
    ▼
vector_store/
    vectors.npy          (1023 × 2560 float32)
    chunks_metadata.json (text + source per chunk)
    │  search_kb.py
    ▼
sklearn NearestNeighbors (cosine metric) → ranked chunks → prompt → LLM (TBD)
```

## API authentication gotchas

iFlytek uses **two different** HMAC schemes — do not confuse them:

| API | Host | Auth |
|-----|------|------|
| **Embedding** | `emb-cn-huabei-1.xf-yun.com` | HMAC-SHA256, digest MUST include `SHA-256=` prefix |
| **ChatDoc** | `chatdoc.xfyun.cn` | MD5(appId+timestamp) → HmacSHA1 → Base64 |

Omitting the `SHA-256=` prefix on the Embedding API digest causes `401 HMAC signature does not match`.

Full API references at `@docs/官网文档/`. Project plans at `@docs/`.

## Dependencies

Core: `requests`, `numpy`, `scikit-learn`, `tqdm`
Document parsing: `PyMuPDF` (PDF), `python-docx` (Word)
FAISS does NOT work on this Windows machine — sklearn NearestNeighbors is the replacement.

## Credentials

iFlytek APPID/APIKey/APISecret are hardcoded in `build_vector_store.py`, `search_kb.py`, and `test_embedding_api.py`. See `@docs/官网文档/项目凭据与配置.md` for values.

## Known limitations

- FAISS DLL fails on Windows (missing VC++ runtime) — use sklearn only
- No test framework; `test_embedding_api.py` is a manual connectivity check
- No `requirements.txt` or `pyproject.toml` yet
- Knowledge base PDFs with image-only pages (scanned docs) fail PyMuPDF — may need OCR

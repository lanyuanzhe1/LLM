# -*- coding: utf-8 -*-
"""
Knowledge Base Vectorization Pipeline
iFlytek Embedding API + sklearn NearestNeighbors

Full pipeline:
  Raw docs -> Text extraction -> Cleaning -> Chunking -> Embedding -> Vector index -> Search test
"""

import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

import numpy as np
import requests
from tqdm import tqdm

# Force UTF-8 on Windows
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ============================================================
# CONFIG - Fill in your values
# ============================================================
APP_ID = "5c75015a"
API_KEY = "d29f3016bcfa0ac8a46fcce888d7c0fb"
API_SECRET = "YTQxNzQ1MjhkNzljODMxYTQ1OTRiMWZh"

# Document directory (your knowledge base files)
DOC_DIR = Path("./knowledge")

# Output directory (vector store)
OUTPUT_DIR = Path("./vector_store")
OUTPUT_DIR.mkdir(exist_ok=True)

# Chunking parameters
CHUNK_SIZE = 600  # characters per chunk
CHUNK_OVERLAP = 100  # overlap between chunks

# API rate control
SLEEP_INTERVAL = 0.3  # seconds between API calls

# API settings
EMBEDDING_HOST = "emb-cn-huabei-1.xf-yun.com"
EMBEDDING_URL = f"https://{EMBEDDING_HOST}/"
# ============================================================

# ---- Step 1: Document Reading ----


def read_text_file(file_path: Path) -> str:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def read_pdf_file(file_path: Path) -> str:
    try:
        import fitz

        doc = fitz.open(file_path)
        text_parts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(text_parts)
    except ImportError:
        print("  [WARN] PyMuPDF not installed, trying pdfplumber...")
        try:
            import pdfplumber

            with pdfplumber.open(file_path) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except ImportError:
            print(
                "  [ERROR] No PDF reader available. Install PyMuPDF: pip install PyMuPDF"
            )
            return ""


def read_docx_file(file_path: Path) -> str:
    try:
        from docx import Document

        doc = Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        print("  [WARN] python-docx not installed: pip install python-docx")
        return ""


def load_documents(doc_dir: Path) -> List[dict]:
    """Walk directory, read all supported documents."""
    documents = []
    supported = {".txt", ".md", ".pdf", ".docx"}

    all_files = list(doc_dir.rglob("*"))
    print(f"  Scanning {doc_dir.absolute()}")
    print(f"  Found {len(all_files)} files total")

    for file_path in all_files:
        if file_path.suffix.lower() not in supported:
            continue
        if file_path.name.startswith("~") or file_path.name.startswith("."):
            continue

        try:
            ext = file_path.suffix.lower()
            if ext == ".pdf":
                text = read_pdf_file(file_path)
            elif ext == ".docx":
                text = read_docx_file(file_path)
            else:
                text = read_text_file(file_path)

            if text.strip():
                rel_path = str(file_path.relative_to(doc_dir))
                documents.append(
                    {"file": rel_path, "text": text, "char_count": len(text)}
                )
                print(f"  [OK] {rel_path} ({len(text)} chars)")
        except Exception as e:
            print(f"  [SKIP] {file_path.relative_to(doc_dir)} - {e}")

    return documents


# ---- Step 2: Text Cleaning ----


def clean_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"([，。！？；：、])\s+", r"\1", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


# ---- Step 3: Chunking ----


def chunk_text(
    text: str, source_file: str, chunk_size: int = 600, overlap: int = 100
) -> List[dict]:
    """Split text into semantic chunks by paragraph, with overlap."""
    chunks = []
    paragraphs = text.split("\n\n")

    current_chunk = ""
    current_start = 0
    position = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) <= chunk_size:
            current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
            if not current_chunk:
                current_start = position
        else:
            if current_chunk.strip():
                chunks.append(
                    {
                        "text": current_chunk.strip(),
                        "source": source_file,
                        "start_pos": current_start,
                        "char_count": len(current_chunk),
                    }
                )

            if len(para) > chunk_size:
                for sub in split_long_paragraph(para, chunk_size):
                    chunks.append(
                        {
                            "text": sub,
                            "source": source_file,
                            "start_pos": position,
                            "char_count": len(sub),
                        }
                    )
                current_chunk = ""
            else:
                current_chunk = para
                current_start = position

        position += len(para) + 2

    if current_chunk.strip():
        chunks.append(
            {
                "text": current_chunk.strip(),
                "source": source_file,
                "start_pos": current_start,
                "char_count": len(current_chunk),
            }
        )

    # Add overlap from previous chunk tail
    for i in range(1, len(chunks)):
        if overlap > 0 and len(chunks[i - 1]["text"]) > overlap:
            tail = chunks[i - 1]["text"][-overlap:]
            chunks[i]["text"] = tail + "\n" + chunks[i]["text"]

    return chunks


def split_long_paragraph(para: str, max_len: int) -> List[str]:
    """Split oversized paragraph by sentences."""
    sentences = re.split(r"(?<=[。！？.!?])\s*", para)
    result = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) <= max_len:
            current += sent
        else:
            if current:
                result.append(current.strip())
            current = sent
    if current:
        result.append(current.strip())
    return result


# ---- Step 4: Embedding API ----


class EmbeddingClient:
    """iFlytek Embedding API client with HMAC-SHA256 signature."""

    def __init__(self, app_id, api_key, api_secret, host=EMBEDDING_HOST):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.host = host
        self.url = f"https://{host}/"

    def _make_signature(self, body_str: str) -> dict:
        """Generate HMAC-SHA256 signature and return headers."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%a, %d %b %Y %H:%M:%S GMT")

        body_digest_sha = base64.b64encode(
            hashlib.sha256(body_str.encode("utf-8")).digest()
        ).decode("utf-8")
        body_digest_full = f"SHA-256={body_digest_sha}"

        signature_origin = (
            f"host: {self.host}\n"
            f"date: {date_str}\n"
            f"POST / HTTP/1.1\n"
            f"digest: {body_digest_full}"
        )

        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature = base64.b64encode(signature_sha).decode("utf-8")

        authorization = (
            f'api_key="{self.api_key}", '
            f'algorithm="hmac-sha256", '
            f'headers="host date request-line digest", '
            f'signature="{signature}"'
        )

        return {
            "Host": self.host,
            "Date": date_str,
            "Digest": body_digest_full,
            "Authorization": authorization,
            "Content-Type": "application/json",
        }

    def embed(
        self, text: str, domain: str = "para", max_retries: int = 3
    ) -> np.ndarray:
        """Convert single text to 2560-dim vector (with retry on transient errors)."""
        messages_text = json.dumps({"messages": [{"content": text, "role": "user"}]})
        text_base64 = base64.b64encode(messages_text.encode("utf-8")).decode("utf-8")

        request_body = {
            "header": {"app_id": self.app_id, "uid": str(uuid.uuid4()), "status": 3},
            "parameter": {
                "emb": {
                    "domain": domain,
                    "feature": {
                        "encoding": "utf8",
                        "compress": "raw",
                        "format": "plain",
                    },
                }
            },
            "payload": {
                "messages": {
                    "encoding": "utf8",
                    "compress": "raw",
                    "format": "json",
                    "status": 3,
                    "text": text_base64,
                }
            },
        }

        body_str = json.dumps(request_body)
        headers = self._make_signature(body_str)

        last_error = None
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    self.url, headers=headers, data=body_str, timeout=30
                )
                if resp.status_code == 200:
                    result = resp.json()
                    if result["header"]["code"] == 0:
                        feature_b64 = result["payload"]["feature"]["text"]
                        vector_bytes = base64.b64decode(feature_b64)
                        return np.frombuffer(
                            vector_bytes, dtype=np.dtype(np.float32).newbyteorder("<")
                        )
                    else:
                        last_error = f"API code={result['header']['code']}, msg={result['header']['message']}"
                elif resp.status_code == 500 or resp.status_code == 503:
                    last_error = f"HTTP {resp.status_code} (server error)"
                    time.sleep(1.0 * (attempt + 1))  # backoff
                    continue
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except requests.exceptions.Timeout:
                last_error = "Timeout"
                time.sleep(1.0 * (attempt + 1))
                continue
            except Exception as e:
                last_error = str(e)

        raise Exception(f"Embedding failed after {max_retries} retries: {last_error}")


def embed_all_chunks(chunks: List[dict], client: EmbeddingClient) -> List[dict]:
    """Vectorize all chunks using the Embedding API."""
    failed_count = 0

    for i, chunk in enumerate(tqdm(chunks, desc="Vectorizing")):
        try:
            chunk["embedding"] = client.embed(chunk["text"], domain="para")
        except Exception as e:
            print(f"\n  [FAIL] chunk {i}: {str(e)[:100]}")
            chunk["embedding"] = np.zeros(2560, dtype=np.float32)
            failed_count += 1

        if (i + 1) % 50 == 0:
            time.sleep(0.5)  # Rate limiting every 50 chunks

    if failed_count > 0:
        print(
            f"\n  [WARN] {failed_count}/{len(chunks)} chunks failed, using zero vectors"
        )

    return chunks


# ---- Step 5: Vector Index (sklearn) ----


def build_index(chunks: List[dict]) -> Tuple:
    """Build nearest-neighbor index from embedding vectors using sklearn."""
    from sklearn.neighbors import NearestNeighbors

    vectors = np.array([c["embedding"] for c in chunks]).astype("float32")

    # L2 normalize for cosine similarity
    from sklearn.preprocessing import normalize

    vectors = normalize(vectors, norm="l2")

    # Brute-force NN with cosine metric (uses normalized vectors internally)
    nbrs = NearestNeighbors(n_neighbors=10, metric="cosine", algorithm="brute")
    nbrs.fit(vectors)

    print(f"  Vectors: {len(chunks)}, Dim: {vectors.shape[1]}, Metric: cosine")
    return nbrs, chunks


def save_index(nbrs, chunks: List[dict], output_dir: Path):
    """Save vectors and chunk metadata."""
    vectors = nbrs._fit_X
    np.save(str(output_dir / "vectors.npy"), vectors)

    metadata = []
    for c in chunks:
        metadata.append(
            {
                "text": c["text"],
                "source": c["source"],
                "start_pos": c.get("start_pos", 0),
                "char_count": c.get("char_count", len(c["text"])),
            }
        )

    with open(output_dir / "chunks_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    vec_size = os.path.getsize(output_dir / "vectors.npy") / 1024 / 1024
    meta_size = os.path.getsize(output_dir / "chunks_metadata.json") / 1024
    print(f"  vectors.npy ({vec_size:.1f} MB)")
    print(f"  chunks_metadata.json ({meta_size:.1f} KB)")


# ---- Step 6: Search Verification ----


def search_test(
    client: EmbeddingClient,
    nbrs,
    chunks: List[dict],
    queries: List[str],
    top_k: int = 5,
):
    """Run test queries to verify retrieval quality."""

    for q in queries:
        print(f"\n  Query: {q}")
        try:
            query_vec = client.embed(q, domain="query")
            query_vec = query_vec.reshape(1, -1).astype("float32")

            distances, indices = nbrs.kneighbors(query_vec, n_neighbors=top_k)

            for rank, (dist, idx) in enumerate(zip(distances[0], indices[0])):
                if idx < len(chunks):
                    score = 1.0 - float(dist)  # cosine distance -> similarity
                    text_preview = chunks[idx]["text"][:120].replace("\n", " ")
                    source = chunks[idx]["source"]
                    print(f"    [{rank + 1}] score={score:.4f} | {source}")
                    print(f"         {text_preview}...")
        except Exception as e:
            print(f"    [ERROR] {e}")


# ============================================================
# Main Pipeline
# ============================================================


def main():
    print("=" * 60)
    print("  Knowledge Base Vectorization Pipeline")
    print("=" * 60)

    # Step 1: Load documents
    print("\n[Step 1] Loading documents...")
    documents = load_documents(DOC_DIR)
    if not documents:
        print("\n[ERROR] No documents found!")
        print(f"  Please put your files in: {DOC_DIR.absolute()}")
        print("  Supported formats: .txt, .md, .pdf, .docx")
        return
    total_chars = sum(d["char_count"] for d in documents)
    print(f"  Total: {len(documents)} docs, {total_chars:,} chars")

    # Step 2: Clean
    print("\n[Step 2] Cleaning text...")
    for doc in documents:
        doc["text"] = clean_text(doc["text"])

    # Step 3: Chunk
    print(f"\n[Step 3] Chunking (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})...")
    all_chunks = []
    for doc in documents:
        chunks = chunk_text(doc["text"], doc["file"], CHUNK_SIZE, CHUNK_OVERLAP)
        all_chunks.extend(chunks)
    print(f"  Generated {len(all_chunks)} chunks")

    # Show chunk quality check
    if all_chunks:
        print("\n  --- Chunk quality sample ---")
        for i in [0, len(all_chunks) // 2, len(all_chunks) - 1]:
            if i < len(all_chunks):
                preview = all_chunks[i]["text"][:100].replace("\n", "|")
                print(f"  [{i}] {all_chunks[i]['source']}: {preview}...")

    # Step 4: Vectorize
    print(f"\n[Step 4] Vectorizing {len(all_chunks)} chunks...")
    print(f"  API: {EMBEDDING_URL}")
    print(f"  Estimated time: ~{len(all_chunks) * 0.5 / 60:.1f} min")

    client = EmbeddingClient(APP_ID, API_KEY, API_SECRET)
    all_chunks = embed_all_chunks(all_chunks, client)

    # Step 5: Build index
    print("\n[Step 5] Building vector index (sklearn)...")
    nbrs, chunks = build_index(all_chunks)
    save_index(nbrs, chunks, OUTPUT_DIR)
    print(f"  Saved to: {OUTPUT_DIR.absolute()}")

    # Step 6: Search verification
    print("\n[Step 6] Search verification...")
    print("  Enter test queries (type 'quit' to exit)")

    while True:
        try:
            query = input("\n  Query> ").strip()
            if not query:
                continue
            if query.lower() == "quit":
                break
            search_test(client, nbrs, chunks, [query], top_k=3)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"  [ERROR] {e}")

    print("\n" + "=" * 60)
    print("  Pipeline complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()

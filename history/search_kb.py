# -*- coding: utf-8 -*-


"""
Knowledge Base Search (load-only, no re-vectorization)
Quick search against a previously built vector store.
"""

import base64
import hashlib
import hmac
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ============================================================
APP_ID = "5c75015a"
API_KEY = "d29f3016bcfa0ac8a46fcce888d7c0fb"
API_SECRET = "YTQxNzQ1MjhkNzljODMxYTQ1OTRiMWZh"
EMBEDDING_HOST = "emb-cn-huabei-1.xf-yun.com"
VECTOR_DIR = Path("./vector_store")
# ============================================================


class EmbeddingClient:
    def __init__(self, app_id, api_key, api_secret, host=EMBEDDING_HOST):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.host = host
        self.url = f"https://{host}/"

    def _make_signature(self, body_str):
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

    def embed(self, text, domain="query"):
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
        resp = requests.post(self.url, headers=headers, data=body_str, timeout=30)
        result = resp.json()
        if result["header"]["code"] == 0:
            feature_b64 = result["payload"]["feature"]["text"]
            vector_bytes = base64.b64decode(feature_b64)
            return np.frombuffer(
                vector_bytes, dtype=np.dtype(np.float32).newbyteorder("<")
            )
        else:
            raise Exception(
                f"API error: {result['header']['code']} {result['header']['message']}"
            )


def load_index(vector_dir: Path):
    """Load previously saved vectors and metadata."""
    vectors_path = vector_dir / "vectors.npy"
    metadata_path = vector_dir / "chunks_metadata.json"

    if not vectors_path.exists() or not metadata_path.exists():
        print(f"[ERROR] Vector store not found in {vector_dir}")
        print("  Run build_vector_store.py first!")
        return None, None

    from sklearn.neighbors import NearestNeighbors
    from sklearn.preprocessing import normalize

    vectors = np.load(str(vectors_path))
    vectors = normalize(vectors, norm="l2")
    nbrs = NearestNeighbors(n_neighbors=10, metric="cosine", algorithm="brute")
    nbrs.fit(vectors)

    with open(metadata_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    print(f"Loaded: {vectors.shape[0]} vectors, {vectors.shape[1]} dims")
    return nbrs, chunks


def search(query, client, nbrs, chunks, top_k=5):
    """Search knowledge base and return results."""
    print(f"\n  Searching for: {query}")
    query_vec = client.embed(query, domain="query")
    query_vec = query_vec.reshape(1, -1).astype("float32")

    distances, indices = nbrs.kneighbors(query_vec, n_neighbors=top_k)

    results = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx < len(chunks):
            results.append(
                {
                    "score": round(1.0 - float(dist), 4),
                    "text": chunks[idx]["text"],
                    "source": chunks[idx]["source"],
                }
            )

    for rank, r in enumerate(results):
        print(f"  [{rank + 1}] score={r['score']:.4f} | {r['source']}")
        print(f"       {r['text'][:150]}...")
        print()

    return results


if __name__ == "__main__":
    print("=" * 50)
    print("  Knowledge Base Search")
    print("=" * 50)

    nbrs, chunks = load_index(VECTOR_DIR)
    if nbrs is None:
        sys.exit(1)

    client = EmbeddingClient(APP_ID, API_KEY, API_SECRET)

    print("\n  Enter queries (type 'quit' to exit)")
    while True:
        try:
            q = input("\n  Query> ").strip()
            if not q:
                continue
            if q.lower() == "quit":
                break
            search(q, client, nbrs, chunks, top_k=3)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"  [ERROR] {e}")

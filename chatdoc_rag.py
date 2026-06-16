# -*- coding: utf-8 -*-
"""
ChatDoc RAG Pipeline
iFlytek official API: https://www.xfyun.cn/doc/spark/ChatDoc-API.html

Full flow: upload docs -> wait vectorization -> create repo -> add files -> Q&A
"""

import hashlib
import hmac
import base64
import json
import os
import sys
import time
from pathlib import Path

import requests
import websocket

if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ============================================================
APP_ID = "5c75015a"
API_SECRET = "YTQxNzQ1MjhkNzljODMxYTQ1OTRiMWZh"
# ============================================================

BASE_URL = "https://chatdoc.xfyun.cn"
WS_URL = "wss://chatdoc.xfyun.cn/openapi/chat"
DOC_DIR = Path("./knowledge")


# ---- Auth ----
def get_auth_headers():
    ts = str(int(time.time()))
    auth_str = hashlib.md5((APP_ID + ts).encode()).hexdigest()
    sig_raw = hmac.new(API_SECRET.encode(), auth_str.encode(), hashlib.sha1).digest()
    signature = base64.b64encode(sig_raw).decode()
    return {"appId": APP_ID, "timestamp": ts, "signature": signature}


def get_ws_url():
    ts = str(int(time.time()))
    auth_str = hashlib.md5((APP_ID + ts).encode()).hexdigest()
    sig_raw = hmac.new(API_SECRET.encode(), auth_str.encode(), hashlib.sha1).digest()
    signature = base64.b64encode(sig_raw).decode()
    return f"{WS_URL}?appId={APP_ID}&timestamp={ts}&signature={signature}"


# ---- Step 1: Upload ----
def upload_file(file_path: Path) -> str:
    url = f"{BASE_URL}/openapi/v1/file/upload"
    with open(file_path, "rb") as f:
        resp = requests.post(
            url,
            headers=get_auth_headers(),
            files={"file": f},
            data={"fileType": "wiki", "parseType": "AUTO", "stepByStep": "false"},
            timeout=120,
        )
    result = resp.json()
    if result["code"] != 0:
        raise Exception(f"Upload failed: {result}")
    return result["data"]["fileId"]


# ---- Step 2: Wait vectorization ----
def wait_vectored(file_ids: list, max_attempts=100, interval=3):
    url = f"{BASE_URL}/openapi/v1/file/status"
    for attempt in range(max_attempts):
        resp = requests.post(
            url, headers=get_auth_headers(), data={"fileIds": ",".join(file_ids)}
        )
        statuses = resp.json()["data"]
        all_done = all(s["fileStatus"] == "vectored" for s in statuses)
        any_failed = any(s["fileStatus"] == "failed" for s in statuses)
        if any_failed:
            raise Exception(f"Vectorization failed: {statuses}")
        if all_done:
            return
        print(f"  Poll #{attempt+1}: {[(s['fileId'][:8], s['fileStatus']) for s in statuses]}")
        time.sleep(interval)
    raise TimeoutError("Vectorization timed out")


# ---- Step 3: Create repo ----
def create_repo(name: str, desc: str = "") -> str:
    url = f"{BASE_URL}/openapi/v1/repo/create"
    resp = requests.post(
        url,
        headers=get_auth_headers(),
        json={"repoName": name, "repoDesc": desc, "repoTags": ""},
    )
    result = resp.json()
    if result["code"] != 0:
        raise Exception(f"Create repo failed: {result}")
    return result["data"]


# ---- Step 4: Add files to repo ----
def add_files_to_repo(repo_id: str, file_ids: list):
    url = f"{BASE_URL}/openapi/v1/repo/file/add"
    resp = requests.post(
        url,
        headers=get_auth_headers(),
        json={"repoId": repo_id, "fileIds": file_ids},
    )
    result = resp.json()
    if result["code"] != 0:
        raise Exception(f"Add files failed: {result}")


# ---- Step 5: WebSocket Q&A ----
def ask_question(question: str, repo_id: str = None, file_ids: list = None):
    full_answer = []
    references = []

    def on_open(ws):
        payload = {
            "messages": [{"role": "user", "content": question}],
            "chatExtends": {
                "spark": True,
                "temperature": 0.5,
                "retrievalFilterPolicy": "REGULAR",
                "qaMode": "MIX",
            },
        }
        if repo_id:
            payload["repoId"] = repo_id
        if file_ids:
            payload["fileIds"] = file_ids
        ws.send(json.dumps(payload))

    def on_message(ws, message):
        data = json.loads(message)
        if data.get("content"):
            full_answer.append(data["content"])
            print(data["content"], end="", flush=True)
        if data.get("status") == 99:
            ref = data.get("fileRefer", {})
            references.append(ref)
        if data.get("status") == 2:
            ws.close()

    def on_error(ws, error):
        print(f"\n  [WS Error] {error}")

    ws = websocket.WebSocketApp(
        get_ws_url(), on_open=on_open, on_message=on_message, on_error=on_error
    )
    ws.run_forever()

    if references:
        print(f"\n  [References: {len(references)} sources]")

    return "".join(full_answer)


# ---- Main ----
def main():
    print("=" * 55)
    print("  ChatDoc RAG Pipeline")
    print("=" * 55)

    # Step 1: Upload
    print("\n[1/5] Uploading documents...")
    file_ids = []
    for root, dirs, files in os.walk(DOC_DIR):
        for fname in files:
            ext = fname.lower().rsplit(".", 1)[-1] if "." in fname else ""
            if ext in ("pdf", "docx", "txt", "md", "doc"):
                fpath = Path(root) / fname
                try:
                    fid = upload_file(fpath)
                    file_ids.append(fid)
                    print(f"  [OK] {fpath.relative_to(DOC_DIR)} -> {fid[:12]}...")
                except Exception as e:
                    print(f"  [FAIL] {fpath.relative_to(DOC_DIR)}: {e}")

    if not file_ids:
        print("[ABORT] No files uploaded successfully")
        return

    print(f"  Uploaded: {len(file_ids)} files")

    # Step 2: Wait
    print(f"\n[2/5] Waiting for vectorization...")
    wait_vectored(file_ids)
    print("  All vectored!")

    # Step 3: Create repo
    print("\n[3/5] Creating knowledge base...")
    repo_id = create_repo("粮食储藏知识库", "储粮害虫防治、低温储粮、CO2监测、粮食安全保障法")
    print(f"  repoId: {repo_id[:12]}...")

    # Step 4: Add files
    print("\n[4/5] Adding files to knowledge base...")
    add_files_to_repo(repo_id, file_ids)
    print(f"  {len(file_ids)} files added")

    # Step 5: Q&A
    print(f"\n[5/5] Q&A test (repoId={repo_id[:12]}...)")
    print("=" * 55)

    queries = [
        "储粮害虫有哪些防治方法？",
        "低温储粮技术的主要原理是什么？",
        "粮食安全保障法对政府储备有什么要求？",
        "CO2监测在储粮安全中起什么作用？",
    ]
    for q in queries:
        print(f"\n  Q: {q}")
        print(f"  A: ", end="")
        try:
            ask_question(q, repo_id=repo_id)
        except Exception as e:
            print(f"\n  [ERROR] {e}")
        print()

    print("=" * 55)
    print(f"  Done! repoId: {repo_id}")
    print("=" * 55)


if __name__ == "__main__":
    main()

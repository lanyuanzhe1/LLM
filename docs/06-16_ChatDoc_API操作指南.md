# 讯飞 ChatDoc API — RAG 搭建操作指南

> 不走网页 UI，直接 Python 调 API 完成知识库上传 → 向量化 → 检索 → 问答
>
> 官方文档：https://www.xfyun.cn/doc/spark/ChatDoc-API.html
> 接口域名：`chatdoc.xfyun.cn`

---

## 一、鉴权机制（与 Embedding API 不同！）

ChatDoc API 用的是 **MD5 + HmacSHA1**，不是 Embedding API 的 HMAC-SHA256。

```
Step 1: auth = MD5(appId + timestamp)           # 32位小写十六进制
Step 2: signature = Base64( HmacSHA1(auth, apiSecret) )
```

每个请求的 HTTP Header 都要带：
- `appId` — 你已持有：`5c75015a`
- `timestamp` — 秒级时间戳（与服务器差不超过 5 分钟）
- `signature` — 上述算法生成

---

## 二、完整流程（5 步，全自动）

```
① file/upload   → 上传文档，拿到 fileId
② file/status   → 轮询等待向量化完成（vectored）
③ repo/create   → 创建知识库，拿到 repoId
④ repo/file/add → 把文件加入知识库
⑤ openapi/chat  → WebSocket 流式问答
```

---

## 三、可运行代码

```python
# -*- coding: utf-8 -*-
"""
讯飞 ChatDoc API — 知识库 RAG 完整流程
上传文档 → 向量化 → 创建知识库 → 问答
"""

import hashlib
import hmac
import base64
import time
import json
import requests
import websocket

# ============================================================
APP_ID = "5c75015a"
API_SECRET = "YTQxNzQ1MjhkNzljODMxYTQ1OTRiMWZh"
API_KEY = "d29f3016bcfa0ac8a46fcce888d7c0fb"
# ============================================================

BASE_URL = "https://chatdoc.xfyun.cn"
WS_URL = "wss://chatdoc.xfyun.cn/openapi/chat"


# ── 鉴权 ──────────────────────────────────────────────────

def get_auth_headers():
    """生成 ChatDoc API 鉴权 header"""
    ts = str(int(time.time()))
    auth_str = hashlib.md5((APP_ID + ts).encode()).hexdigest()
    sig_raw = hmac.new(
        API_SECRET.encode(), auth_str.encode(), hashlib.sha1
    ).digest()
    signature = base64.b64encode(sig_raw).decode()
    return {
        "appId": APP_ID,
        "timestamp": ts,
        "signature": signature,
    }


def get_ws_url():
    """生成 WebSocket 鉴权 URL"""
    ts = str(int(time.time()))
    auth_str = hashlib.md5((APP_ID + ts).encode()).hexdigest()
    sig_raw = hmac.new(
        API_SECRET.encode(), auth_str.encode(), hashlib.sha1
    ).digest()
    signature = base64.b64encode(sig_raw).decode()
    return f"{WS_URL}?appId={APP_ID}&timestamp={ts}&signature={signature}"


# ── ① 上传文档 ────────────────────────────────────────────

def upload_file(file_path: str) -> str:
    """上传单个文档，返回 fileId"""
    url = f"{BASE_URL}/openapi/v1/file/upload"
    with open(file_path, "rb") as f:
        resp = requests.post(
            url,
            headers=get_auth_headers(),
            files={"file": f},
            data={
                "fileType": "wiki",
                "parseType": "AUTO",       # 自动判断 TEXT/OCR
                "stepByStep": "false",     # 一步到位（上传+分块+向量化全自动）
            },
            timeout=120,
        )
    result = resp.json()
    if result["code"] != 0:
        raise Exception(f"上传失败: {result}")
    file_id = result["data"]["fileId"]
    print(f"  ✓ 上传成功: {file_path} → fileId={file_id[:12]}...")
    return file_id


# ── ② 等待向量化 ──────────────────────────────────────────

def wait_vectored(file_ids: list, max_attempts=100, interval=3):
    """轮询直到所有文档状态变为 vectored"""
    url = f"{BASE_URL}/openapi/v1/file/status"
    for attempt in range(max_attempts):
        resp = requests.post(
            url,
            headers=get_auth_headers(),
            data={"fileIds": ",".join(file_ids)},
        )
        statuses = resp.json()["data"]

        all_done = True
        for s in statuses:
            st = s["fileStatus"]
            if st == "failed":
                raise Exception(f"文档 {s['fileId']} 处理失败")
            if st != "vectored":
                all_done = False

        if all_done:
            print(f"  ✓ 全部向量化完成 ({attempt+1}轮)")
            return
        print(f"  轮询 {attempt+1}: {[(s['fileId'][:8], s['fileStatus']) for s in statuses]}")
        time.sleep(interval)
    raise TimeoutError("向量化超时")


# ── ③ 创建知识库 ──────────────────────────────────────────

def create_repo(name: str, desc: str = "") -> str:
    """创建知识库，返回 repoId"""
    url = f"{BASE_URL}/openapi/v1/repo/create"
    resp = requests.post(
        url,
        headers=get_auth_headers(),
        json={"repoName": name, "repoDesc": desc, "repoTags": ""},
    )
    result = resp.json()
    if result["code"] != 0:
        raise Exception(f"创建知识库失败: {result}")
    repo_id = result["data"]
    print(f"  ✓ 知识库创建: {name} → repoId={repo_id[:12]}...")
    return repo_id


# ── ④ 添加文件到知识库 ─────────────────────────────────────

def add_files_to_repo(repo_id: str, file_ids: list):
    """把文件加入知识库"""
    url = f"{BASE_URL}/openapi/v1/repo/file/add"
    resp = requests.post(
        url,
        headers=get_auth_headers(),
        json={"repoId": repo_id, "fileIds": file_ids},
    )
    result = resp.json()
    if result["code"] != 0:
        raise Exception(f"添加文件失败: {result}")
    print(f"  ✓ {len(file_ids)} 个文件已加入知识库")


# ── ⑤ WebSocket 问答 ──────────────────────────────────────

def ask(question: str, repo_id: str = None, file_ids: list = None) -> str:
    """
    WebSocket 流式问答。
    参数 repo_id 和 file_ids 二选一。
    """
    full_answer = []

    def on_open(ws):
        payload = {
            "messages": [{"role": "user", "content": question}],
            "chatExtends": {
                "spark": True,                    # 无匹配时大模型兜底
                "temperature": 0.5,
                "retrievalFilterPolicy": "REGULAR",
                "qaMode": "MIX",                  # QA对+原文混合检索
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
            # 文档引用
            ref = data.get("fileRefer", {})
            print(f"\n  [引用: {ref.get('fileName', '未知')}]")
        if data.get("status") == 2:
            ws.close()

    def on_error(ws, error):
        print(f"\n  [WS错误] {error}")

    ws = websocket.WebSocketApp(
        get_ws_url(),
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
    )
    ws.run_forever()
    return "".join(full_answer)


# ── 快捷函数：一键上传整个目录 ─────────────────────────────

def upload_directory(dir_path: str) -> list:
    """上传目录下所有支持的文件"""
    import os
    file_ids = []
    for root, dirs, files in os.walk(dir_path):
        for fname in files:
            ext = fname.lower().rsplit(".", 1)[-1] if "." in fname else ""
            if ext in ("pdf", "doc", "docx", "txt", "md"):
                fpath = os.path.join(root, fname)
                try:
                    fid = upload_file(fpath)
                    file_ids.append(fid)
                except Exception as e:
                    print(f"  ✗ {fname}: {e}")
    return file_ids


# ============================================================
# 主流程
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  ChatDoc API — RAG 知识库搭建")
    print("=" * 50)

    # ① 上传所有文档
    print("\n[1/4] 上传文档...")
    file_ids = upload_directory("./knowledge")
    print(f"  共上传 {len(file_ids)} 个文件")

    if not file_ids:
        print("[FAIL] 没有成功上传的文件")
        exit(1)

    # ② 等待向量化
    print("\n[2/4] 等待向量化...")
    wait_vectored(file_ids)

    # ③ 创建知识库
    print("\n[3/4] 创建知识库...")
    repo_id = create_repo("粮食储藏知识库", "储粮害虫防治、低温储粮、粮食安全保障法")

    # ④ 添加文件
    add_files_to_repo(repo_id, file_ids)

    # ⑤ 问答测试
    print("\n[4/4] 问答测试")
    print("=" * 50)
    test_questions = [
        "储粮害虫有哪些防治方法？",
        "低温储粮技术的主要原理是什么？",
    ]
    for q in test_questions:
        print(f"\n  Q: {q}")
        print(f"  A: ", end="")
        ask(q, repo_id=repo_id)
        print()

    print("\n" + "=" * 50)
    print("  知识库搭建完成！repoId:", repo_id)
    print("=" * 50)
```

---

## 四、两种使用路径对比

你现在有两条路可以实现 RAG：

| | 路径 A：ChatDoc API | 路径 B：本地向量库 + DeepSeek |
|---|---|---|
| **文档上传** | 调 API 自动分块+向量化 | 已用 build_vector_store.py 完成 |
| **检索** | 讯飞内部（不可见） | sklearn 余弦相似度（可控） |
| **生成** | 讯飞 Spark 模型 | DeepSeek V4 Flash |
| **引用** | API 自动返回 | 自己拼接 |
| **工作量** | 极小（调 API 就行） | 中等（写 Prompt + 调 DeepSeek） |
| **灵活性** | 低（黑盒） | 高（所有环节可控） |

### 如果你想同时用 DeepSeek + 讯飞 ChatDoc

ChatDoc API 支持通过 `file/status` 获取向量化后的分块内容吗？不——ChatDoc 向量化是黑盒的，你只能用它的 WebSocket 问答接口。

**所以如果坚持用 DeepSeek，推荐路径 B**：

```
我们的向量库(vector_store/) → sklearn 检索 Top-K chunk
                                    ↓
                          拼到 Prompt 里 → DeepSeek V4 Flash 生成答案
```

---

## 五、按你的需求：ChatDoc 上传 + DeepSeek 生成

既然你已经有 `vector_store/`，可以**只用 ChatDoc 做文档管理**，生成部分用 DeepSeek：

```
方案：本地检索（sklearn + 讯飞 Embedding）+ DeepSeek 生成
                                               
  user query → 讯飞 Embedding API(query模式) → 2560维向量
           → sklearn 检索 vector_store → Top K chunk
           → 拼入 Prompt → DeepSeek V4 Flash → 带引用回答
```

这个方案代码量很小，你已经有了向量库，只需要加 DeepSeek 调用。要我直接写这个脚本吗？

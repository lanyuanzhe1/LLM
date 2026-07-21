#!/usr/bin/env python3
"""
RAG 测试对话窗口 — Flask + 纯 HTML 前端

功能：
  1. 上传 PDF/DOCX/TXT/MD 文件 → 自动分块、嵌入、加入知识库
  2. 流式对话（SSE）：问题 → 检索 → MaaS 生成答案（打字机效果）
  3. 每次回答附检索来源和相似度分数

启动：
  python chat_ui.py
  浏览器打开 http://127.0.0.1:7860
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from urllib.parse import urlencode, urlparse

import numpy as np
import requests
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import normalize as l2_normalize

# ═══════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════

APP_ID = os.environ.get("XF_APP_ID", "5c75015a")
EMBEDDING_API_KEY = os.environ.get("XF_EMBEDDING_API_KEY", "d29f3016bcfa0ac8a46fcce888d7c0fb")
EMBEDDING_API_SECRET = os.environ.get("XF_EMBEDDING_API_SECRET", "YTQxNzQ1MjhkNzljODMxYTQ1OTRiMWZh")
EMBEDDING_HOST = "emb-cn-huabei-1.xf-yun.com"
EMBEDDING_URL = f"https://{EMBEDDING_HOST}/"

MAAS_API_KEY = os.environ.get("XF_MAAS_API_KEY", "d29f3016bcfa0ac8a46fcce888d7c0fb")
MAAS_API_SECRET = os.environ.get("XF_MAAS_API_SECRET", "YTQxNzQ1MjhkNzljODMxYTQ1OTRiMWZh")
MAAS_RESOURCE_ID = os.environ.get("XF_MAAS_RESOURCE_ID", "2066745321636515840")
MAAS_SERVICE_ID = os.environ.get("XF_MAAS_SERVICE_ID", "xop3qwen32b")
MAAS_URL = "wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat"

CHUNK_SIZE = 600
CHUNK_OVERLAP = 100
TOP_K = 5


# ═══════════════════════════════════════════════════════
# 嵌入客户端
# ═══════════════════════════════════════════════════════

class EmbeddingClient:
    """同步 HTTP 客户端，调用 iFlytek Embedding API。"""

    def __init__(self) -> None:
        self.app_id = APP_ID
        self.api_key = EMBEDDING_API_KEY
        self.api_secret = EMBEDDING_API_SECRET

    def _make_signature(self, body_str: str) -> dict[str, str]:
        date_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        body_digest_sha = base64.b64encode(
            hashlib.sha256(body_str.encode("utf-8")).digest()
        ).decode("utf-8")
        body_digest_full = f"SHA-256={body_digest_sha}"
        signature_origin = (
            f"host: {EMBEDDING_HOST}\n"
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
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line digest", '
            f'signature="{signature}"'
        )
        return {
            "Host": EMBEDDING_HOST,
            "Date": date_str,
            "Digest": body_digest_full,
            "Authorization": authorization,
            "Content-Type": "application/json",
        }

    def embed(self, texts: list[str], domain: str = "para") -> np.ndarray | None:
        vectors = []
        for i, text in enumerate(texts):
            text_base64 = base64.b64encode(
                json.dumps({"messages": [{"content": text, "role": "user"}]}).encode("utf-8")
            ).decode("utf-8")
            body = {
                "header": {"app_id": self.app_id, "uid": uuid.uuid4().hex[:16], "status": 3},
                "parameter": {"emb": {"domain": domain, "feature": {"encoding": "utf8"}}},
                "payload": {"messages": {"text": text_base64}},
            }
            body_str = json.dumps(body, ensure_ascii=False)
            last_err = "unknown"
            for attempt in range(3):
                try:
                    resp = requests.post(
                        EMBEDDING_URL,
                        headers=self._make_signature(body_str),
                        data=body_str.encode("utf-8"),
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result = resp.json()
                        if result["header"]["code"] == 0:
                            feature_b64 = result["payload"]["feature"]["text"]
                            vec_bytes = base64.b64decode(feature_b64)
                            vectors.append(
                                np.frombuffer(vec_bytes, dtype=np.dtype(np.float32).newbyteorder("<"))
                            )
                            break
                    last_err = f"HTTP {resp.status_code}"
                    if resp.status_code in (500, 502, 503):
                        time.sleep(1.0 * (attempt + 1))
                        continue
                except requests.RequestException as exc:
                    last_err = str(exc)
                    if attempt < 2:
                        time.sleep(1.0 * (attempt + 1))
                        continue
                break
            else:
                print(f"[Embed] 第{i+1}条失败: {last_err}")
                return None
            if (i + 1) % 50 == 0:
                time.sleep(0.3)
        if not vectors:
            return None
        return np.stack(vectors, axis=0)


# ═══════════════════════════════════════════════════════
# 文档读取
# ═══════════════════════════════════════════════════════

def read_pdf(file_path: str) -> str:
    try:
        import fitz
        doc = fitz.open(file_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    except ImportError:
        return ""


def read_docx(file_path: str) -> str:
    try:
        from docx import Document
        doc = Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        return ""


def read_text(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def read_document(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return read_pdf(file_path)
    elif ext == ".docx":
        return read_docx(file_path)
    else:
        return read_text(file_path)


# ═══════════════════════════════════════════════════════
# 分块
# ═══════════════════════════════════════════════════════

_PARA_BREAK = re.compile(r"\n\s*\n")


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    paragraphs = [p.strip() for p in _PARA_BREAK.split(text) if p.strip()]
    chunks: list[str] = []
    for para in paragraphs:
        start = 0
        while start < len(para):
            end = min(start + chunk_size, len(para))
            chunks.append(para[start:end].strip())
            if end >= len(para):
                break
            start = end - overlap
    if len(chunks) == 1 and len(chunks[0]) < 10:
        return []
    return chunks


# ═══════════════════════════════════════════════════════
# 向量存储
# ═══════════════════════════════════════════════════════

class VectorStore:
    def __init__(self) -> None:
        self.chunks: list[dict] = []
        self.vectors: np.ndarray | None = None
        self.nbrs: NearestNeighbors | None = None
        self._lock = threading.Lock()

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def file_count(self) -> int:
        return len(set(c.get("source", "") for c in self.chunks))

    def add(self, chunks: list[dict], vectors: np.ndarray) -> None:
        with self._lock:
            start_idx = len(self.chunks)
            for i, ch in enumerate(chunks):
                ch["index"] = start_idx + i
            self.chunks.extend(chunks)
            if self.vectors is None:
                self.vectors = vectors
            else:
                self.vectors = np.vstack([self.vectors, vectors])
            self._rebuild_index()

    def _rebuild_index(self) -> None:
        if self.vectors is None or len(self.vectors) == 0:
            self.nbrs = None
            return
        normalized = l2_normalize(self.vectors, norm="l2")
        self.nbrs = NearestNeighbors(
            n_neighbors=min(TOP_K, len(self.vectors)),
            metric="cosine",
            algorithm="brute",
        )
        self.nbrs.fit(normalized)

    def search(self, query_vec: np.ndarray) -> list[dict]:
        with self._lock:
            if self.nbrs is None or len(self.chunks) == 0:
                return []
            query_vec = query_vec.reshape(1, -1).astype(np.float32)
            query_vec = l2_normalize(query_vec, norm="l2")
            distances, indices = self.nbrs.kneighbors(query_vec)
            results: list[dict] = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx < len(self.chunks):
                    results.append({
                        "score": round(1.0 - float(dist), 4),
                        "text": self.chunks[idx]["text"][:2000],
                        "source": self.chunks[idx].get("source", "未知"),
                        "index": idx,
                    })
            return results

    def clear(self) -> None:
        with self._lock:
            self.chunks = []
            self.vectors = None
            self.nbrs = None

    def get_stats(self) -> dict:
        with self._lock:
            sources = sorted(set(c.get("source", "未知") for c in self.chunks))
            return {
                "file_count": len(sources),
                "chunk_count": len(self.chunks),
                "files": sources,
            }


# ═══════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════

embed_client = EmbeddingClient()
vector_store = VectorStore()


# ═══════════════════════════════════════════════════════
# MaaS 流式生成
# ═══════════════════════════════════════════════════════

SYSTEM_PROMPT = (
    "你是一个专业的粮食储藏知识助手。请严格基于以下提供的知识库内容回答用户问题。\n"
    "回答规则：\n"
    "1. 如果知识库中有相关信息，请详细、准确地回答，并在回答末尾标注引用的来源文件名\n"
    "2. 如果知识库中信息不充分，请明确告知用户，不要编造\n"
    "3. 使用中文回答，语言专业但易懂"
)


def build_messages(question: str, search_results: list[dict]) -> list[dict]:
    context_parts = ["以下是从知识库中检索到的相关内容：\n"]
    for i, r in enumerate(search_results, 1):
        context_parts.append(f"[来源{i}] {r['source']} (相似度: {r['score']:.2f})\n{r['text']}\n")
    context = "\n".join(context_parts)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{context}\n\n用户问题：{question}\n\n请基于上述知识库内容回答问题："},
    ]


def _build_maas_auth_url() -> str:
    parsed = urlparse(MAAS_URL)
    date = format_datetime(datetime.now(timezone.utc), usegmt=True)
    origin = f"host: {parsed.netloc}\ndate: {date}\nGET {parsed.path} HTTP/1.1"
    signature = base64.b64encode(
        hmac.new(MAAS_API_SECRET.encode(), origin.encode(), hashlib.sha256).digest()
    ).decode()
    authorization_origin = (
        f'api_key="{MAAS_API_KEY}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(authorization_origin.encode()).decode()
    query = urlencode({
        "authorization": authorization,
        "date": date,
        "host": parsed.netloc,
    })
    return f"{MAAS_URL}?{query}"


async def generate_stream(messages: list[dict]):
    """流式生成，逐 token yield。"""
    from websockets.asyncio.client import connect as ws_connect

    payload = {
        "header": {
            "app_id": APP_ID,
            "uid": uuid.uuid4().hex[:32],
            "patch_id": [MAAS_RESOURCE_ID],
        },
        "parameter": {
            "chat": {
                "domain": MAAS_SERVICE_ID,
                "temperature": 0.3,
                "top_k": 4,
                "max_tokens": 2048,
                "auditing": "default",
            }
        },
        "payload": {"message": {"text": messages}},
    }

    url = _build_maas_auth_url()

    async with ws_connect(url, open_timeout=30, close_timeout=10) as ws:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=60)
            frame = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
            header = frame.get("header", {})
            if header.get("code") != 0:
                yield f"[错误: code={header.get('code')}]"
                return
            pl = frame.get("payload", {})
            choices = pl.get("choices", {})
            for item in choices.get("text", []):
                yield item.get("content", "")
            status = header.get("status") or choices.get("status")
            if status == 2:
                break


# ═══════════════════════════════════════════════════════
# HTTP 服务器 + API 路由
# ═══════════════════════════════════════════════════════

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>粮储智研助手 - RAG 测试</title>
<style>
:root {
  --bg: #1a1a2e; --surface: #16213e; --card: #0f3460;
  --text: #e8e8e8; --sub: #a0a0b0; --accent: #e94560;
  --msg-user: #2d4a7a; --msg-ai: #1a3038; --border: #2a3a5c;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, "Segoe UI", sans-serif; background:var(--bg); color:var(--text); height:100vh; display:flex; }
/* 侧边栏 */
.sidebar { width:280px; background:var(--surface); display:flex; flex-direction:column; border-right:1px solid var(--border); }
.sidebar-header { padding:20px 16px; border-bottom:1px solid var(--border); }
.sidebar-header h1 { font-size:18px; margin-bottom:4px; }
.sidebar-header p { font-size:12px; color:var(--sub); }
.upload-area { padding:16px; border-bottom:1px solid var(--border); }
.upload-area label { display:block; padding:20px; border:2px dashed var(--border); border-radius:8px; text-align:center; cursor:pointer; transition:border-color .2s; }
.upload-area label:hover { border-color:var(--accent); }
.upload-area input { display:none; }
.kb-stats { padding:16px; flex:1; overflow-y:auto; font-size:13px; color:var(--sub); }
.kb-stats h3 { font-size:14px; color:var(--text); margin-bottom:8px; }
.kb-stats ul { list-style:none; }
.kb-stats li { padding:3px 0; font-size:12px; word-break:break-all; }
.clear-btn { margin:0 16px 16px; padding:8px; background:var(--accent); color:#fff; border:none; border-radius:6px; cursor:pointer; font-size:13px; }
/* 主区 */
.main { flex:1; display:flex; flex-direction:column; max-width:calc(100% - 280px); }
.chat-area { flex:1; overflow-y:auto; padding:20px; display:flex; flex-direction:column; gap:16px; }
.msg { max-width:80%; padding:12px 16px; border-radius:12px; line-height:1.6; font-size:14px; animation:fadeIn .3s; }
.msg.user { align-self:flex-end; background:var(--msg-user); border-bottom-right-radius:4px; }
.msg.ai { align-self:flex-start; background:var(--msg-ai); border-bottom-left-radius:4px; white-space:pre-wrap; }
.msg .sources { margin-top:12px; padding-top:8px; border-top:1px solid var(--border); font-size:12px; color:var(--sub); }
.msg .sources div { margin:2px 0; }
.input-area { padding:16px 20px; border-top:1px solid var(--border); display:flex; gap:12px; }
.input-area textarea { flex:1; padding:12px; background:var(--surface); border:1px solid var(--border); border-radius:8px; color:var(--text); font-size:14px; resize:none; rows:2; outline:none; }
.input-area textarea:focus { border-color:var(--accent); }
.input-area button { padding:12px 24px; background:var(--accent); color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:14px; }
.input-area button:disabled { opacity:.5; cursor:not-allowed; }
.spinner { display:inline-block; width:14px; height:14px; border:2px solid var(--sub); border-top-color:var(--accent); border-radius:50%; animation:spin .8s linear infinite; margin-right:8px; }
@keyframes spin { to { transform:rotate(360deg); } }
@keyframes fadeIn { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
.thinking { align-self:flex-start; padding:8px 16px; color:var(--sub); font-size:13px; }
.status-toast { position:fixed; top:16px; right:16px; padding:10px 20px; border-radius:8px; font-size:13px; z-index:100; animation:fadeIn .3s; }
.status-toast.ok { background:#1a4a1a; color:#8f8; }
.status-toast.err { background:#4a1a1a; color:#f88; }
</style>
</head>
<body>
<div class="sidebar">
  <div class="sidebar-header">
    <h1>🏭 粮储智研助手</h1>
    <p>RAG 测试对话窗口</p>
  </div>
  <div class="upload-area">
    <label for="fileInput">📁 点击上传文档<br><small>PDF / DOCX / TXT / MD</small></label>
    <input type="file" id="fileInput" accept=".pdf,.docx,.txt,.md">
  </div>
  <div class="kb-stats" id="kbStats">
    <h3>📊 知识库状态</h3>
    <p>加载中...</p>
  </div>
  <button class="clear-btn" onclick="clearKB()">🗑️ 清空知识库</button>
</div>
<div class="main">
  <div class="chat-area" id="chatArea">
    <div class="msg ai">👋 你好！上传粮食储藏相关文档后，即可开始对话。</div>
  </div>
  <div class="input-area">
    <textarea id="msgInput" placeholder="输入问题，例如：什么是低温储粮技术？" rows="2"
      onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMsg();}"></textarea>
    <button id="sendBtn" onclick="sendMsg()">发送</button>
  </div>
</div>
<div id="toast" class="status-toast" style="display:none"></div>

<script>
let isGenerating = false;

async function loadStats() {
  const r = await fetch('/api/stats');
  const s = await r.json();
  const el = document.getElementById('kbStats');
  el.innerHTML = '';
  const h3 = document.createElement('h3');
  h3.textContent = '📊 知识库状态';
  el.appendChild(h3);
  if (s.file_count === 0) {
    const p = document.createElement('p');
    p.textContent = '知识库为空，请上传文档';
    el.appendChild(p);
  } else {
    const p = document.createElement('p');
    p.textContent = '📄 ' + s.file_count + ' 个文件 | 🧩 ' + s.chunk_count + ' 个文本块';
    el.appendChild(p);
    const ul = document.createElement('ul');
    s.files.forEach(f => {
      const li = document.createElement('li');
      li.textContent = '📄 ' + f;
      ul.appendChild(li);
    });
    el.appendChild(ul);
  }
}

async function uploadFile(f) {
  showToast('正在处理文件...', '');
  const fd = new FormData();
  fd.append('file', f);
  try {
    const r = await fetch('/api/upload', {method:'POST', body:fd});
    const j = await r.json();
    if (j.ok) showToast(`✅ ${f.name} 已加入知识库`, 'ok');
    else showToast(`❌ ${j.error}`, 'err');
  } catch(e) {
    showToast(`❌ 上传失败: ${e}`, 'err');
  }
  loadStats();
}

async function clearKB() {
  if (!confirm('确定清空知识库中的所有文件？')) return;
  await fetch('/api/clear', {method:'POST'});
  loadStats();
  document.getElementById('chatArea').innerHTML =
    '<div class="msg ai">👋 知识库已清空。上传新文档后即可对话。</div>';
}

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'status-toast ' + type; t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3000);
}

function appendMsg(role, content, sources) {
  const area = document.getElementById('chatArea');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = content;
  if (sources && sources.length) {
    const src = document.createElement('div');
    src.className = 'sources';
    src.appendChild(document.createTextNode('📚 '));
    const hdr = document.createElement('b');
    hdr.textContent = '参考来源：';
    src.appendChild(hdr);
    src.appendChild(document.createElement('br'));
    sources.forEach(s => {
      src.appendChild(document.createTextNode(
        '• ' + s.source + ' (相似度: ' + (s.score*100).toFixed(0) + '%)'
      ));
      src.appendChild(document.createElement('br'));
    });
    div.appendChild(src);
  }
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
  return div;
}

async function sendMsg() {
  const input = document.getElementById('msgInput');
  const btn = document.getElementById('sendBtn');
  const msg = input.value.trim();
  if (!msg || isGenerating) return;
  input.value = '';
  isGenerating = true;
  btn.disabled = true;

  appendMsg('user', msg);

  // 显示"思考中"
  const area = document.getElementById('chatArea');
  const thinking = document.createElement('div');
  thinking.className = 'thinking';
  thinking.innerHTML = '<span class="spinner"></span>思考中...';
  area.appendChild(thinking);
  area.scrollTop = area.scrollHeight;

  try {
    const r = await fetch('/api/chat', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({question: msg})
    });

    if (!r.ok) {
      const err = await r.json();
      thinking.remove();
      appendMsg('ai', `❌ ${err.error || '请求失败'}`);
      return;
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let aiDiv = null;
    let sources = null;

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      // 解析 SSE 事件
      const lines = buffer.split('\n');
      buffer = lines.pop(); // 保留不完整的行

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.token) {
              if (!aiDiv) {
                thinking.remove();
                aiDiv = appendMsg('ai', '');
              }
              aiDiv.textContent += data.token;
              area.scrollTop = area.scrollHeight;
            }
            if (data.sources) {
              sources = data.sources;
            }
            if (data.done && aiDiv && sources) {
              const src = document.createElement('div');
              src.className = 'sources';
              src.appendChild(document.createTextNode('📚 '));
              const hdr = document.createElement('b');
              hdr.textContent = '参考来源：';
              src.appendChild(hdr);
              src.appendChild(document.createElement('br'));
              sources.forEach(s => {
                src.appendChild(document.createTextNode(
                  '• ' + s.source + ' (相似度: ' + (s.score*100).toFixed(0) + '%)'
                ));
                src.appendChild(document.createElement('br'));
              });
              aiDiv.appendChild(src);
            }
          } catch(e) {}
        }
        if (line.startsWith('event: done')) {
          // 流结束
        }
      }
    }

    if (!aiDiv) {
      thinking.remove();
      appendMsg('ai', '⚠️ 未收到回答，请重试。');
    }
  } catch(e) {
    thinking.remove();
    appendMsg('ai', `❌ 网络错误: ${e}`);
  } finally {
    isGenerating = false;
    btn.disabled = false;
    input.focus();
  }
}

document.getElementById('fileInput').addEventListener('change', function(e) {
  if (e.target.files[0]) {
    uploadFile(e.target.files[0]);
    e.target.value = '';
  }
});

loadStats();
</script>
</body>
</html>"""


class APIHandler(SimpleHTTPRequestHandler):
    """自定义 HTTP 请求处理器：静态页面 + API 端点。"""

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self._send_html()
        elif self.path == "/api/stats":
            self._json_response(vector_store.get_stats())
        else:
            self._send_html()

    def do_POST(self) -> None:
        if self.path == "/api/upload":
            self._handle_upload()
        elif self.path == "/api/chat":
            self._handle_chat()
        elif self.path == "/api/clear":
            vector_store.clear()
            self._json_response({"ok": True})
        else:
            self._json_response({"error": "not found"}, status=404)

    def _send_html(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))

    def _json_response(self, data: dict, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def _handle_upload(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._json_response({"ok": False, "error": "需要 multipart/form-data"}, status=400)
            return

        # 简易 multipart 解析
        body = self._read_body()
        boundary = content_type.split("boundary=")[1].encode()
        parts = body.split(b"--" + boundary)
        for part in parts:
            if b"Content-Disposition" not in part:
                continue
            # 找文件内容
            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                continue
            headers_str = part[:header_end].decode("utf-8", errors="ignore")
            file_content = part[header_end + 4:]
            # 去掉末尾 \r\n
            if file_content.endswith(b"\r\n"):
                file_content = file_content[:-2]

            # 提取并清洗文件名（防路径穿越）
            name_match = re.search(r'filename="([^"]*)"', headers_str)
            if not name_match:
                continue
            raw_name = name_match.group(1)
            safe_name = Path(raw_name).name  # 剥离目录部分，只保留文件名
            if not safe_name or safe_name != raw_name:
                self._json_response({"ok": False, "error": f"文件名包含非法路径: {raw_name}"})
                return

            # 检查重复
            existing = set(c.get("source", "") for c in vector_store.chunks)
            if safe_name in existing:
                self._json_response({"ok": False, "error": f"文件 \"{safe_name}\" 已在知识库中"})
                return

            # 写临时文件（safe_name 已通过 Path().name 清洗，不对 /tmp 外的路径生效）
            tmp_path = f"/tmp/rag_upload_{uuid.uuid4().hex[:8]}_{safe_name}"
            with open(tmp_path, "wb") as f:
                f.write(file_content)

            try:
                text = read_document(tmp_path)
            except Exception as e:
                os.unlink(tmp_path)
                print(f"[Upload] read error: {e}")  # 服务端记录
                self._json_response({"ok": False, "error": "文件读取失败，请检查文件格式"})
                return

            os.unlink(tmp_path)

            if not text or len(text.strip()) < 10:
                self._json_response({"ok": False, "error": "文件内容为空或过短"})
                return

            chunks = chunk_text(text)
            if not chunks:
                self._json_response({"ok": False, "error": "分块后无有效内容"})
                return

            print(f"[Upload] {safe_name}: {len(chunks)} chunks, embedding...")
            vectors = embed_client.embed(chunks, domain="para")
            if vectors is None:
                self._json_response({"ok": False, "error": "嵌入失败，请检查 API 配置"})
                return

            chunk_dicts = [{"text": c, "source": safe_name, "index": -1} for c in chunks]
            vector_store.add(chunk_dicts, vectors)
            print(f"[Upload] ✓ {safe_name} added")
            self._json_response({"ok": True, "file": safe_name, "chunks": len(chunks)})
            return

        self._json_response({"ok": False, "error": "未找到文件"})

    def _handle_chat(self) -> None:
        body = self._read_body()
        try:
            data = json.loads(body)
            question = data.get("question", "").strip()
        except json.JSONDecodeError:
            self._json_response({"error": "无效的 JSON"}, status=400)
            return

        if not question:
            self._json_response({"error": "问题不能为空"}, status=400)
            return

        # 嵌入问题
        query_vec = embed_client.embed([question], domain="query")
        if query_vec is None:
            self._json_response({"error": "问题嵌入失败"}, status=500)
            return

        # 检索
        results = vector_store.search(query_vec)

        if not results:
            self._json_response({
                "error": "知识库中未找到相关信息，请先上传文档",
                "stats": vector_store.get_stats(),
            }, status=404)
            return

        # 构建消息
        messages = build_messages(question, results)

        # SSE 流式响应
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        # 先在 SSE 的第一个事件中发送来源信息
        sources_data = [{"source": r["source"], "score": r["score"]} for r in results]
        self.wfile.write(f"data: {json.dumps({'sources': sources_data}, ensure_ascii=False)}\n\n".encode())

        # 在新线程中运行 asyncio 流式生成，主线程写 SSE
        loop = asyncio.new_event_loop()
        done = threading.Event()
        answer_chunks: list[str] = []
        error_msg: str | None = None

        def run_stream():
            nonlocal error_msg
            try:
                async def collect():
                    async for token in generate_stream(messages):
                        answer_chunks.append(token)
                loop.run_until_complete(collect())
            except Exception as e:
                print(f"[Chat] MaaS stream error: {e}")  # 服务端记录真实异常
                error_msg = "回答生成失败，请稍后重试"       # 客户端只收通用提示
            finally:
                loop.close()
                done.set()

        stream_thread = threading.Thread(target=run_stream, daemon=True)
        stream_thread.start()

        # 逐 token 发送 SSE（超时 120 秒）
        last_idx = 0
        start_time = time.time()
        timeout = 120.0
        while not done.is_set() or last_idx < len(answer_chunks):
            while last_idx < len(answer_chunks):
                chunk = answer_chunks[last_idx]
                last_idx += 1
                event_data = json.dumps({"token": chunk}, ensure_ascii=False)
                try:
                    self.wfile.write(f"data: {event_data}\n\n".encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
            if done.is_set():
                break
            if time.time() - start_time > timeout:
                error_msg = error_msg or "回答生成超时"
                break
            done.wait(0.05)

        # 发送完成事件（确保总是发送，让前端 isGenerating 复位）
        try:
            if error_msg:
                err_token = "\n\n[⚠️ 错误: " + error_msg + "]"
                self.wfile.write(f"data: {json.dumps({'token': err_token}, ensure_ascii=False)}\n\n".encode())
            self.wfile.write("event: done\ndata: {}\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """支持多线程的 HTTP 服务器，允许并发请求。"""
    daemon_threads = True


def main():
    port = 7860
    server = ThreadingHTTPServer(("127.0.0.1", port), APIHandler)
    print("=" * 60)
    print("  🏭 粮储智研助手 - RAG 测试对话窗口")
    print(f"  浏览器打开 → http://127.0.0.1:{port}")
    print("=" * 60)
    print(f"  Embedding API: {EMBEDDING_HOST}")
    print(f"  MaaS 模型: {MAAS_SERVICE_ID}")
    print(f"  按 Ctrl+C 退出")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
        server.shutdown()


if __name__ == "__main__":
    main()

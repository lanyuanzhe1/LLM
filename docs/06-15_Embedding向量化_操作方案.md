# Embedding 向量化 — 具体操作方案

> **目标**：从零开始，完成知识库文档的向量化，搭建可检索的向量库。
>
> 预计时间：3-5 天（含平台注册等待时间）

---

## 一、平台账号打通（约 1-2 小时）

这是所有后续工作的前提，做完这一步你才有 API 权限。

### 1.1 注册讯飞开放平台账号

```
浏览器打开：https://www.xfyun.cn/
点击右上角「登录/注册」
→ 支持微信扫码登录（最快）
→ 或手机号注册
```

> ⚠️ 建议做**实名认证**（个人即可），否则某些服务可能受限。

### 1.2 创建应用 + 获取 API 凭据

```
步骤：
1. 登录后 → 右上角进入「控制台」
2. 左侧菜单 →「我的应用」
3. 点击「创建新应用」按钮
4. 填写：
   - 应用名称：例如 "知识库向量化"
   - 应用分类：随便选一个
   - 功能描述：例如 "对领域知识库文档进行文本向量化处理"
5. 点击「提交」
```

创建成功后，点击应用名称进入**应用详情页**，你会看到：

| 凭据                | 说明               | 操作                                     |
| ------------------- | ------------------ | ---------------------------------------- |
| **APPID**     | 应用唯一标识       | 记下来                                   |
| **APIKey**    | API 访问密钥       | 记下来                                   |
| **APISecret** | API 密钥（签名用） | ⚠️**立刻复制保存！只显示一次！** |

> `★ Insight ─────────────────────────────────────`
> **为什么有三个凭据？** APPID 标识"你是谁"，APIKey 和 APISecret 一起证明"你有权限调用"。新版 Embedding API 兼容 OpenAI 格式，只需要 APIKey（放在 HTTP Header 里），不需要 APISecret 做 HMAC 签名。但旧版 API 和老服务仍然需要三件套。建议三个都保存好。
> `─────────────────────────────────────────────────`

### 1.3 开通 Embedding 服务

这是很多人卡住的环节——Embedding API 和星火大模型 API 是**分开授权**的：

```
路径 A（推荐 — 新版 OpenAI 兼容接口）：
控制台 → 左侧「服务管理」→ 搜索「星辰MaaS」或「Embedding」
→ 找到「文本向量化 Embedding」
→ 点击「开通服务」/「领取免费额度」

路径 B（旧版接口）：
控制台 → 产品服务 → 搜索「Embedding」
→ https://www.xfyun.cn/services/embedding
→ 点击「免费试用」或「立即购买」
```

> **开通后你会拿到**：一个用于 Embedding 的 API Key 和 Base URL。

### 1.4 确认你的可用信息

做完以上步骤，你应该拿到这些：

```
✅ APPID:        xxxxxxxx
✅ APIKey:       xxxxxxxxxxxxxxxxxxxxxxxx
✅ APISecret:    xxxxxxxxxxxxxxxxxxxxxxxx
✅ Embedding API 地址: https://maas-api.cn-huabei-1.xf-yun.com/v1
✅ Embedding 模型 ID: sde0a5839（或平台分配的其他ID）
✅ 大模型 API：如果需要，也一并开通
https://www.xfyun.cn/doc/spark/Embedding_api.html#_2-%E6%8E%A5%E5%8F%A3%E8%AF%B4%E6%98%8E
```

---

## 二、本地开发环境搭建（约 30 分钟）

### 2.1 安装 Python 依赖

打开终端（PowerShell 或 Git Bash），执行：

```bash
pip install openai numpy faiss-cpu python-docx PyMuPDF tqdm
```

如果你用 GPU 加速 FAISS：

```bash
pip install faiss-gpu  # 替代 faiss-cpu
```

### 2.2 验证 API 连通性

创建一个测试脚本 `test_api.py`：

```python
import openai

# ====== 把你从平台拿到的信息填在这里 ======
API_KEY = "你的APIKey"
BASE_URL = "https://maas-api.cn-huabei-1.xf-yun.com/v1"
MODEL_ID = "sde0a5839"  # 平台分配的模型ID
# ==========================================

client = openai.OpenAI(api_key=API_KEY, base_url=BASE_URL)

# 单条文本测试
response = client.embeddings.create(
    model=MODEL_ID,
    input="你好，这是一条测试文本",
)

embedding = response.data[0].embedding
print(f"✅ API 连通成功！")
print(f"   向量维度: {len(embedding)}")
print(f"   前5个值: {embedding[:5]}")
print(f"   Token 消耗: {response.usage.total_tokens}")
```

运行：

```bash
python test_api.py
```

看到 `✅ API 连通成功！向量维度: 2560` 就说明一切正常。

---

## 三、知识库文档 → 向量化（核心流程）

### 3.1 整体流程概览

```
原始文档（PDF/Word/TXT）
    │
    ├── Step 1: 读取文档，提取纯文本
    ├── Step 2: 文本清洗（去噪、去重、格式统一）
    ├── Step 3: 智能分块（Chunking）
    ├── Step 4: 批量调用 Embedding API 向量化
    ├── Step 5: 存入 FAISS 索引
    └── Step 6: 检索验证（问几个问题看看能不能找到答案）
```

### 3.2 完整代码：从文档到可检索向量库

创建文件 `build_vector_store.py`，把以下代码**整体复制**进去：

```python
"""
知识库向量化完整脚本
从原始文档 → 文本提取 → 分块 → 向量化 → FAISS 索引 → 检索验证
"""

import os
import json
import hashlib
import time
from pathlib import Path
from typing import List, Tuple
import numpy as np
import openai
import faiss
from tqdm import tqdm

# ============================================================
# 🔧 配置区 — 把你在讯飞平台拿到的信息填在这里
# ============================================================
API_KEY = "你的APIKey"
BASE_URL = "https://maas-api.cn-huabei-1.xf-yun.com/v1"
MODEL_ID = "sde0a5839"

# 文档路径（你的知识库存放目录）
DOC_DIR = Path("./knowledge_base")   # ← 改成你的知识库路径

# 输出路径（向量库保存位置）
OUTPUT_DIR = Path("./vector_store")
OUTPUT_DIR.mkdir(exist_ok=True)

# 分块参数
CHUNK_SIZE = 600    # 每个 chunk 的字符数
CHUNK_OVERLAP = 100  # chunk 之间的重叠字符数

# API 调用控制
BATCH_SIZE = 10      # 每次请求发送的文本条数（减少 API 调用次数）
SLEEP_INTERVAL = 0.5 # 请求间隔（秒），避免触发限流
# ============================================================

client = openai.OpenAI(api_key=API_KEY, base_url=BASE_URL)


# ── Step 1: 读取文档 ──────────────────────────────────────

def read_text_file(file_path: Path) -> str:
    """读取纯文本文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def read_pdf_file(file_path: Path) -> str:
    """读取 PDF 文件，提取文本"""
    import fitz  # PyMuPDF
    doc = fitz.open(file_path)
    text_parts = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return "\n".join(text_parts)


def read_docx_file(file_path: Path) -> str:
    """读取 Word 文件，提取文本"""
    from docx import Document
    doc = Document(file_path)
    text_parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            text_parts.append(para.text)
    return "\n".join(text_parts)


def load_documents(doc_dir: Path) -> List[dict]:
    """
    遍历目录，读取所有支持的文档
    返回: [{"file": "xxx.pdf", "text": "文档纯文本内容"}, ...]
    """
    documents = []
    supported = {".txt", ".md", ".pdf", ".docx"}

    for file_path in doc_dir.rglob("*"):
        if file_path.suffix.lower() not in supported:
            continue
        if file_path.name.startswith("~"):  # 跳过临时文件
            continue

        try:
            if file_path.suffix.lower() == ".pdf":
                text = read_pdf_file(file_path)
            elif file_path.suffix.lower() == ".docx":
                text = read_docx_file(file_path)
            else:
                text = read_text_file(file_path)

            if text.strip():
                documents.append({
                    "file": str(file_path.relative_to(doc_dir)),
                    "text": text,
                    "char_count": len(text)
                })
                print(f"  ✓ 已读取: {file_path.relative_to(doc_dir)} ({len(text)} 字符)")
        except Exception as e:
            print(f"  ✗ 读取失败: {file_path.relative_to(doc_dir)} — {e}")

    return documents


# ── Step 2: 文本清洗 ──────────────────────────────────────

def clean_text(text: str) -> str:
    """基础文本清洗"""
    import re
  
    # 去除多余空行（保留单个空行作为段落分隔）
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 去除行首行尾空格
    text = '\n'.join(line.strip() for line in text.split('\n'))
    # 统一中文标点附近的空格
    text = re.sub(r'([，。！？；：])\s+', r'\1', text)
    # 去除控制字符
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
  
    return text.strip()


# ── Step 3: 智能分块 ──────────────────────────────────────

def chunk_text(text: str, source_file: str,
               chunk_size: int = 600, overlap: int = 100) -> List[dict]:
    """
    将长文本切分为语义块。
  
    策略：优先按段落（\n\n）切分，段落过长时按句子切分。
    每个 chunk 保留来源文件和位置信息。
    """
    chunks = []
    paragraphs = text.split('\n\n')
  
    current_chunk = ""
    current_start = 0
    position = 0
  
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
          
        para_len = len(para)
      
        # 如果当前 chunk + 新段落 不超限，直接追加
        if len(current_chunk) + para_len <= chunk_size:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para
                current_start = position
        else:
            # 先保存当前 chunk
            if current_chunk.strip():
                chunks.append({
                    "text": current_chunk.strip(),
                    "source": source_file,
                    "start_pos": current_start,
                    "char_count": len(current_chunk)
                })
          
            # 处理长段落：按句子切分
            if para_len > chunk_size:
                sub_chunks = split_long_paragraph(para, chunk_size, overlap)
                for sc in sub_chunks:
                    chunks.append({
                        "text": sc,
                        "source": source_file,
                        "start_pos": position,
                        "char_count": len(sc)
                    })
                current_chunk = ""
            else:
                current_chunk = para
                current_start = position
      
        position += para_len + 2  # +2 for \n\n
  
    # 保存最后一个 chunk
    if current_chunk.strip():
        chunks.append({
            "text": current_chunk.strip(),
            "source": source_file,
            "start_pos": current_start,
            "char_count": len(current_chunk)
        })
  
    # 添加重叠：每个 chunk 末尾与前一个 chunk 开头有 overlap 字符交集
    # 这里通过复制前一个 chunk 的尾部来实现
    overlapped_chunks = []
    for i, chunk in enumerate(chunks):
        if i > 0 and overlap > 0:
            prev_tail = chunks[i-1]["text"][-overlap:] if len(chunks[i-1]["text"]) > overlap else chunks[i-1]["text"]
            chunk["text"] = prev_tail + "\n" + chunk["text"]
        overlapped_chunks.append(chunk)
  
    return overlapped_chunks


def split_long_paragraph(para: str, max_len: int, overlap: int) -> List[str]:
    """将超长段落按句子切分"""
    import re
    sentences = re.split(r'(?<=[。！？.!?])\s*', para)
  
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


# ── Step 4: 批量向量化 ──────────────────────────────────────

def embed_batch(texts: List[str], model: str = MODEL_ID) -> List[List[float]]:
    """
    批量调用 Embedding API。
    input 参数直接传入字符串列表，一次请求处理多条。
    """
    try:
        response = client.embeddings.create(
            model=model,
            input=texts,
        )
        # 按 index 排序确保顺序正确
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [d.embedding for d in sorted_data]
    except Exception as e:
        print(f"  ✗ API 调用失败: {e}")
        # 失败时重试单条
        print("  → 尝试逐条重试...")
        results = []
        for text in texts:
            try:
                time.sleep(0.2)
                resp = client.embeddings.create(model=model, input=text)
                results.append(resp.data[0].embedding)
            except Exception as e2:
                print(f"    ✗ 单条也失败了: {e2}")
                results.append(None)
        return results


def embed_all_chunks(chunks: List[dict], batch_size: int = BATCH_SIZE) -> List[dict]:
    """
    对所有 chunk 进行批量向量化。
    返回带 embedding 字段的 chunks 列表。
    """
    texts = [c["text"] for c in chunks]
    all_embeddings = []
  
    total_batches = (len(texts) + batch_size - 1) // batch_size
  
    for i in tqdm(range(0, len(texts), batch_size), desc="向量化进度", total=total_batches):
        batch_texts = texts[i:i + batch_size]
        batch_embeddings = embed_batch(batch_texts)
      
        for emb in batch_embeddings:
            if emb is not None:
                all_embeddings.append(emb)
            else:
                all_embeddings.append([0.0] * 2560)  # 失败用零向量占位
      
        if i + batch_size < len(texts):
            time.sleep(SLEEP_INTERVAL)  # 避免触发限流
  
    # 将 embedding 附加到 chunk
    for j, chunk in enumerate(chunks):
        chunk["embedding"] = all_embeddings[j]
  
    return chunks


# ── Step 5: 构建 FAISS 索引 ────────────────────────────────

def build_faiss_index(chunks: List[dict]) -> Tuple[faiss.Index, List[dict]]:
    """
    构建 FAISS HNSW 向量索引（适合 10万-100万级向量）。
    """
    vectors = np.array([c["embedding"] for c in chunks]).astype('float32')
    dimension = vectors.shape[1]
  
    # L2 归一化，使内积等价于余弦相似度
    faiss.normalize_L2(vectors)
  
    # HNSW 索引：快速近似最近邻搜索
    # M=32 表示每个节点连接32个邻居（越高精度越好但内存越大）
    index = faiss.IndexHNSWFlat(dimension, 32)
    index.add(vectors)
  
    print(f"✅ FAISS 索引构建完成")
    print(f"   向量数量: {index.ntotal}")
    print(f"   向量维度: {dimension}")
    print(f"   索引类型: HNSW Flat")
  
    return index, chunks


def save_index(index: faiss.Index, chunks: List[dict], output_dir: Path):
    """保存索引和 chunk 元数据"""
    # 保存 FAISS 索引
    faiss.write_index(index, str(output_dir / "vector.index"))
  
    # 保存 chunk 元数据（不含向量，向量在索引里）
    metadata = []
    for c in chunks:
        metadata.append({
            "text": c["text"],
            "source": c["source"],
            "start_pos": c["start_pos"],
            "char_count": c["char_count"],
        })
  
    with open(output_dir / "chunks_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
  
    print(f"✅ 索引已保存到: {output_dir}")
    print(f"   vector.index ({os.path.getsize(output_dir / 'vector.index') / 1024 / 1024:.1f} MB)")
    print(f"   chunks_metadata.json ({os.path.getsize(output_dir / 'chunks_metadata.json') / 1024:.1f} KB)")


# ── Step 6: 检索验证 ──────────────────────────────────────

def search(query: str, index: faiss.Index, chunks: List[dict], top_k: int = 5):
    """
    检索最相关的 chunk。
    """
    # 向量化查询
    response = client.embeddings.create(model=MODEL_ID, input=query)
    query_vec = np.array([response.data[0].embedding]).astype('float32')
    faiss.normalize_L2(query_vec)
  
    # 检索
    distances, indices = index.search(query_vec, top_k)
  
    results = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx >= 0 and idx < len(chunks):
            results.append({
                "score": float(dist),
                "text": chunks[idx]["text"][:300] + "...",
                "source": chunks[idx]["source"],
            })
  
    return results


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("  知识库向量化 Pipeline")
    print("=" * 60)
  
    # Step 1: 读取文档
    print("\n📄 Step 1: 读取文档...")
    documents = load_documents(DOC_DIR)
    if not documents:
        print("❌ 没有找到任何文档！请检查 DOC_DIR 路径。")
        return
    print(f"   共读取 {len(documents)} 个文档")
    total_chars = sum(d["char_count"] for d in documents)
    print(f"   总字符数: {total_chars:,}")
  
    # Step 2: 清洗
    print("\n🧹 Step 2: 文本清洗...")
    for doc in documents:
        doc["text"] = clean_text(doc["text"])
  
    # Step 3: 分块
    print(f"\n✂️  Step 3: 文档分块 (chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})...")
    all_chunks = []
    for doc in documents:
        chunks = chunk_text(doc["text"], doc["file"], CHUNK_SIZE, CHUNK_OVERLAP)
        all_chunks.extend(chunks)
    print(f"   共生成 {len(all_chunks)} 个 chunk")
  
    # Step 4: 向量化
    print(f"\n🧮 Step 4: 批量向量化 (batch_size={BATCH_SIZE})...")
    all_chunks = embed_all_chunks(all_chunks, BATCH_SIZE)
  
    # Step 5: 构建索引
    print("\n🔍 Step 5: 构建 FAISS 索引...")
    index, chunks = build_faiss_index(all_chunks)
  
    # 保存
    save_index(index, chunks, OUTPUT_DIR)
  
    # Step 6: 检索验证
    print("\n🧪 Step 6: 检索验证测试...")
    test_queries = [
        "你的第一个测试问题",
        "你的第二个测试问题",
        "你的第三个测试问题",
    ]
    for q in test_queries:
        print(f"\n  问题: {q}")
        results = search(q, index, chunks, top_k=3)
        for i, r in enumerate(results):
            print(f"    [{i+1}] 相似度={r['score']:.4f} | 来源={r['source']}")
            print(f"        内容: {r['text'][:100]}...")
  
    print("\n" + "=" * 60)
    print("  ✅ 全部完成！向量库已就绪")
    print(f"  向量库路径: {OUTPUT_DIR.absolute()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

---

## 四、一步一步执行指南

### 第一天：平台 + 环境

```
☐ 1. 注册讯飞开放平台 (xfyun.cn)
☐ 2. 创建应用，保存 APPID / APIKey / APISecret
☐ 3. 开通 Embedding 服务（在服务管理里搜索"Embedding"）
☐ 4. 拿到 Embedding API Key 和模型 ID
☐ 5. pip install openai numpy faiss-cpu PyMuPDF python-docx tqdm
☐ 6. 运行 test_api.py 验证连通性
```

### 第二天：数据准备

```
☐ 7. 把所有知识库文档放到一个文件夹（例如 ./knowledge_base/）
☐ 8. 运行 build_vector_store.py（先不调用API，只测试读取+分块逻辑）
     → 修改代码，注释掉 Step 4-6，先跑 Step 1-3
     → 检查分块效果：每个 chunk 是否语义完整？
☐ 9. 根据结果调整 CHUNK_SIZE 和 CHUNK_OVERLAP
```

### 第三天：向量化

```
☐ 10. 取消注释，跑完整流程
☐ 11. 观察 API 调用是否正常（有无报错/限流）
☐ 12. 如果数据量大（> 1万 chunk），适当调大 SLEEP_INTERVAL
☐ 13. 等待向量化完成（几千条大概 10-30 分钟）
```

### 第四天：验证

```
☐ 14. 修改 test_queries 列表，用真实问题测试检索效果
☐ 15. 人工判断：检索回来的 chunk 是否包含正确答案？
     → 如果命中率低 → 回到 Step 3 调整分块策略
     → 如果命中率高 → 向量库就绪 ✅
☐ 16. 备份 vector.index 和 chunks_metadata.json
```

---

## 五、常见问题排查

| 问题                 | 可能原因                            | 解决办法                                       |
| -------------------- | ----------------------------------- | ---------------------------------------------- |
| `401 Unauthorized` | API Key 错误或未开通 Embedding 服务 | 检查 API Key；确认在服务管理里开通了 Embedding |
| `404 Not Found`    | Base URL 或 Model ID 错误           | 核对平台给的地址和模型 ID                      |
| `429 Rate Limit`   | 请求太频繁                          | 增大 SLEEP_INTERVAL 到 1-2 秒                  |
| 向量维度不是 2560    | 模型 ID 不对                        | 讯飞标准 Embedding 是 2560 维，检查模型 ID     |
| 检索结果不相关       | 分块策略不合适                      | 减小 CHUNK_SIZE 或调整重叠量                   |
| PDF 读出来是空/乱码  | 扫描件 PDF                          | 需要先用 OCR（讯飞 OCR API 或 tesseract）      |

---

## 六、关键决策点

两个你需要根据自己的知识库情况做的判断：

### 决策1：Chunk Size 设多大？

```
FAQ 式知识库（一问一答）→ CHUNK_SIZE = 400, OVERLAP = 50
技术文档/教科书       → CHUNK_SIZE = 600, OVERLAP = 100
长篇报告/论文         → CHUNK_SIZE = 1000, OVERLAP = 200

不知道选哪个？从 600 开始，跑完 Step 3 后人工看 20 个 chunk，
如果每个 chunk 读起来都"语义完整、能独立理解" → 合格 ✅
```

> `★ Insight ─────────────────────────────────────`
> **判断 Chunk 质量的土办法**：随机抽 10 个 chunk，遮住来源文档，只读 chunk 内容，问自己"这段文字在讲什么？"如果能回答出来，chunk 合格。如果读不懂（因为上下文被切断了），需要加大 chunk_size 或 overlap。
> `─────────────────────────────────────────────────`

### 决策2：要不要用 query/para 双模式？

讯飞 Embedding 支持两种向量化模式：

```
para 模式  → 向量化知识库文档（离线处理，只跑一次）
query 模式 → 向量化用户问题（每次检索时实时调用）

双模式 = 文档用 para 向量化，查询用 query 向量化 → 匹配精度更高
单模式 = 都用默认模式 → 更简单，但可能损失 5-10% 精度
```

如果使用新版 OpenAI 兼容接口（`/v1/embeddings`），默认就是单模式。如果需要双模式，需要切换到旧版接口。**建议先用新版单模式跑通，效果不够再切换。**

---

## 七、做完这一步之后

向量库就绪后，下一步的自然衔接：

```
当前阶段 ✅
知识库 → 分块 → Embedding 向量化 → FAISS 索引

下一阶段 →
1. 用微调模型（或基础模型）作为生成引擎
2. 用户提问 → 向量检索（查 FAISS）→ 取 Top 5 chunk
3. 拼接到 Prompt → 发给 LLM → 生成带引用的回答
4. 这就是最简版 RAG 了！

下下阶段 →
5. 加入 BM25 关键词检索（多路召回）
6. 加入 Rerank 精排
7. 用 Agent 平台编排完整工作流
```

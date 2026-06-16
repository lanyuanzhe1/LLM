# AstronAgent RAG 架构分析

> 开源仓库：https://github.com/iflytek/astron-agent
>
> AstronAgent 是讯飞星辰 Agent 平台的开源版（Apache 2.0），ChatDoc API 是其商业化托管版。

## 核心架构

```
用户请求
   │
   ▼
API 层 (FastAPI, core/knowledge/api/v1/api.py)
   │
   ▼
策略工厂 (rag_strategy_factory.py) ── 运行时切换后端
   ├── RagFlow 策略 (ragflow_strategy.py)
   ├── 星火/CBG 策略 (cbg_strategy.py)    ← ChatDoc API 用的这个
   └── AIUI 策略 (aiui_strategy.py)
```

## 关键源码路径

| 模块 | 文件 | 功能 |
|------|------|------|
| 文档上传+分块 | `core/knowledge/infra/xinghuo/xinghuo.py:23-107` | `upload()` → `split()` → `get_chunks()` 轮询 |
| 混合检索 | `core/knowledge/infra/xinghuo/xinghuo.py:217-233` | `new_topk_search()` 向量+关键词融合 |
| 星火策略 | `core/knowledge/service/impl/cbg_strategy.py:120-150` | overlap chunks 按 dataIndex 排序重建上下文 |
| Query 改写 | `core/knowledge/service/rq/rewrite_query.py` | LLM 驱动的查询改写 |
| LLM 封装 | `core/knowledge/llm/openai_llm.py` | OpenAI 兼容接口封装（可接 DeepSeek） |
| HMAC 签名 | `core/knowledge/infra/xinghuo/xinghuo.py` | HMAC-SHA256，与我们的 Embedding API 鉴权一致 |

## RAG 流程细节

### 文档分块（Chunking）

```
星火后端：
  upload(file) → 获得 fileId
  split(fileId, separator=Base64编码分隔符) → 异步分块
  get_chunks(fileId) → 轮询直到 status='splitting' 完成

RagFlow 后端：
  _process_document_upload() → 上传文档
  _handle_document_parsing() → 轮询解析（300秒超时）
```

### 向量化（Embedding）

- **星火后端**：调用讯飞 Embedding API 自动完成（domain=para）
- **RagFlow 后端**：在 RagFlow Web 界面配置 Embedding 模型
- 混合搜索权重：`vector_similarity_weight: 0.2`（向量占20%，BM25占80%）

### 检索（Retrieval）

```
new_topk_search(query):
  1. Query 向量化 (Embedding API, domain=query)
  2. 向量检索 (cosine similarity)
  3. 关键词检索 (BM25)
  4. 混合融合 → Top-K chunks (top_k 可配)
  5. overlap chunks 按 dataIndex 排序 → 重建上下文
```

RagFlow 默认参数：`top_k=6`, `vector_similarity_weight=0.2`

### 生成

chunks + 用户问题 → i18n 模板包裹 → Spark LLM → 流式返回
引用来源通过 WebSocket status=99 返回 fileRefer

## 与我们的本地实现对照

| 环节 | 本地实现 | AstronAgent/ChatDoc |
|------|---------|-------------------|
| 文档解析 | PyMuPDF/pdfplumber/python-docx | 同，封装在 xinghuo.py |
| 分块 | 语义段落切分 (600 chars, 100 overlap) | separator参数控制的自动化切分 |
| 向量化 | 讯飞 Embedding API (para domain) | **完全相同** |
| 向量存储 | sklearn NearestNeighbors (1023×2560) | Milvus/pgvector（不可见） |
| 检索 | cosine similarity (sklearn) | 向量+BM25混合 |
| 生成 | TBD (计划 DeepSeek V4 Flash) | Spark LLM 内置 |

## 设计模式

1. **策略模式**：RAGStrategyFactory 运行时切换后端
2. **双重检查锁**：asyncio.Lock 防并发创建竞态
3. **蓝绿更新**：先上传新版 → 解析成功 → 删除旧版
4. **Fail-closed**：分页查询部分失败时不返回不完整结果

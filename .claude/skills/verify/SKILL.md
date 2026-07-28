---
name: verify
description: 本仓库的运行验证配方（入库 CLI / chat_ui 服务）——凭据加载、代理与限流注意事项、值得驱动的流程
---

# 本仓库验证配方

## 凭据

`ingest_knowledge.py` 只读 `os.environ`（不加载 .env）。运行前必须：

```bash
set -a && source .env && set +a
```

Python 一律用 `/opt/homebrew/Caskroom/miniconda/base/bin/python`（本机 miniconda base，py3.13；CLAUDE.md 里的 Windows 路径已过时）。

## 环境陷阱（2026-07 实测）

- 本机有 macOS 系统代理 127.0.0.1:7897；requests/httpx 都会走它，讯飞 API 可正常访问。**不要**设 `NO_PROXY='*'`——直连会被拒。
- 讯飞 Embedding API 有低并发配额：请求间隔 <1s 会返回 HTTP 500 code 11202 "licc failed"。入库脚本已内置 `INGEST_SLEEP_INTERVAL`（默认 1.1s）。
- `import fitz` 在本机 `-W error` 下段错误（SIGSEGV）；全套件有大量既有失败（缺 pytest-asyncio、app/domain 已删、用户把旧脚本移入 history/ 和 scripts/）。跑测试只跑聚焦文件，不要 `-W error` 全套。
- OCR 结果缓存在 `ocr_cache/<sha256>.md`，重建向量库不会重复计费；该目录已被 gitignore。

## 值得驱动的流程

1. **项目入库（真实 API，耗额度）**：
   `python ingest_knowledge.py --project-id demo --source <小文件>`
   观察 scan → 转换(soffice) → OCR → 缓存 → 分块 → 嵌入 → `Published: vector_store/projects/<id>`，检查产物四件套（vectors.npy/chunks_metadata.json/manifest.json/ingest_report.json）。
   重跑同文件：第一次 files_reused（manifest 增量）；删掉 vector_store 再跑：OCR 缓存命中（秒级，无 OCR 调用）。
2. **本地回退**：`PDF_OCR_ENABLED=0 python ingest_knowledge.py ...` 走本地提取（PPT/PPTX 无本地解析器会得到空文本被跳过）。
3. **chat_ui 演示服务**：`python chat_ui.py` → http://127.0.0.1:7860，上传 PPT/PDF 后提问，观察 SSE 流式回答与来源标注。
4. **嵌入连通性（不费 OCR 额度）**：`python scripts/test_embedding_api.py`。

验证后清理：`rm -rf knowledge/projects/<id> vector_store/projects/<id>`。

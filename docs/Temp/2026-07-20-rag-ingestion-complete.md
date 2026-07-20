# RAG 项目知识入库完成交接

## 当前状态

RAG 项目知识入库功能已全部实现、测试、合并入 `main` 并推送。

- **最新提交**：`b54b28b docs: add ingestion handoff document from design phase`
- **上游**：`origin/main` 已同步
- **测试**：741 passed, 5 deselected（5 个 online 测试需 `RUN_ONLINE=1`），0 failed
- **向量库**：待重建（`vector_store/` 目录当前不存在，需运行 `ingest_knowledge.py --scope base`）

## 已交付功能

### 入库管线
- `python ingest_knowledge.py --scope base` — 重建内置知识库
- `python ingest_knowledge.py --project-id demo` — 重建单项目向量库
- `python ingest_knowledge.py --project-id demo --source file.pdf` — 导入文件并入库
- `python ingest_knowledge.py --scope all-projects` — 批量重建所有项目
- 增量缓存：基于 SHA-256 + parser version + chunk config 的 manifest，未变化文件跳过 embedding
- 原子发布：staging → target `os.replace`，失败回滚
- 输出 `ingest_report.json`（扫描/索引/复用/跳过统计）和 `manifest.json`

### 运行时检索
- `VectorStoreRegistry`：按 `vector_store/base/` 和 `vector_store/projects/<id>/` 加载缓存
- `ProjectRetriever`：一次 Embedding 查询，搜索 base + project 两个库，合并排序，跨项目永不泄漏
- 每个 chunk metadata 包含 `scope` 和 `project_id`，日志和测试可追溯证据来源
- `project_id` 从 public API → workflow gateway → tools → retriever 全链路贯通

### v1 范围
- 支持格式：PDF（PyMuPDF）、DOCX（python-docx）、TXT、Markdown
- 不支持：PPTX、旧二进制 PPT、扫描件 OCR
- 设计原则：本地只做轻量文本提取 + 格式路由，Embedding 模型处理文本质量

## 文件结构

```
app/ingest/          # 入库管线模块
  reader.py          # 格式路由 + 文本提取
  scanner.py         # 作用域感知文件发现 + project_id 校验
  manifest.py        # 增量缓存状态管理
  builder.py         # sklearn 索引 + 原子发布
ingest_knowledge.py  # CLI 入口（~500 行）
app/rag/
  registry.py        # VectorStoreRegistry（多库加载/缓存）
  project_retriever.py  # ProjectRetriever（合并检索 + 跨项目隔离）
app/schemas/
  api.py             # ChatRequest / CaseAnalyzeRequest + project_id
  tools.py           # RetrieveRequest + project_id
workflow/
  tool_contracts.json # 含 PROJECT_ID 参数 + 完整 Pydantic JSON Schema
  README.md          # 7 个开始节点参数
```

## 设计文档

- Spec：`docs/superpowers/specs/2026-07-20-rag-project-ingestion-design.md`
- Plan：`docs/superpowers/plans/2026-07-20-rag-project-ingestion.md`
- 交接（设计前）：`docs/Temp/2026-07-20-rag-ingestion-handoff.md`

## 已知限制

1. **无用户鉴权**：`project_id` 是逻辑隔离键不是权限隔离键。Spec 明确待登录模块实现后，在 retrieval 前增加用户→项目鉴权。
2. **无热加载**：新发布的向量库需服务重启后才可见。后续可加 reload 端点或文件监听。
3. **单进程**：request context 和 vector state 在内存中，因此只能单 worker。
4. **向量库待重建**：当前 `vector_store/` 为空，需运行 `python ingest_knowledge.py --scope base` 消耗 embedding 配额重建。

## 下一步建议

1. **重建向量库**：加载 `.env` 后运行 `python ingest_knowledge.py --scope base`，约 8-10 分钟，消耗讯飞 Embedding 配额
2. **启动服务验证**：`uvicorn app.main:app`，确认 `/ready` 返回 200，`/v1/chat` 可用
3. **在线联调**：`RUN_ONLINE=1 python -m pytest tests/online/ -v`（需 MaaS、Workflow Flow ID、工具公网地址均已就绪）
4. **星辰工作流更新**：在星辰平台将开始节点参数从 6 个更新为 7 个（增加 `PROJECT_ID`），重新发布并更新 `XF_WORKFLOW_FLOW_ID`

## Suggested skills

- `superpowers:brainstorming` — 设计下一功能前确认范围
- `superpowers:writing-plans` — 将设计转化为实施计划
- `superpowers:using-git-worktrees` — 创建隔离开发环境
- `superpowers:subagent-driven-development` — 子代理驱动 TDD 执行

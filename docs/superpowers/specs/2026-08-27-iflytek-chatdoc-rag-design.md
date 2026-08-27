# 讯飞 ChatDoc 全托管 RAG 迁移设计

## 目标

将正式 RAG 链路从本地 `OCR cache -> chunk_text -> Embedding -> sklearn`
迁移到讯飞 ChatDoc：由平台负责文档智能解析、OCR 判断、自动切分、向量化和
检索。保留现有 MaaS 生成、引用校验、星辰工作流和 HTTP API，不改变前端协议。

## 范围

正式链路变为：

```text
knowledge/*
  -> ChatDoc file/upload(parseType=AUTO, stepByStep=false)
  -> ChatDoc 自动解析/切分/向量化
  -> ChatDoc repo
  -> ChatDoc vector/search
  -> 现有 Evidence / GenerationService / CitationValidator
```

本次不删除 `ocr_cache/`、`vector_store/base/` 或
`vector_store/bailian-base/`。它们只作为回滚产物，不再是正式运行时依赖。

## 组件

### ChatDoc 客户端

新增异步客户端，负责：

- MD5(appId + timestamp) 后 HmacSHA1、Base64 的 ChatDoc 鉴权；
- 创建知识库；
- 上传文件，固定使用 `parseType=AUTO`、`fileType=wiki`、
  `stepByStep=false`；
- 批量查询文件状态，直到全部为 `vectored`；
- 分批将文件加入知识库，每批最多 20 个；
- 调用 `vector/search`，启用向量检索、全文检索和 rerank；
- 校验 HTTP 状态、业务 code、JSON 结构和响应大小；
- 将认证、限流、服务端和协议错误转换为不泄露上游响应正文的应用错误。

ChatDoc 与 Embedding 使用同一应用的 appId/APISecret，但鉴权算法不同。运行时
复用现有 `XF_APP_ID` 和 `XF_EMBEDDING_API_SECRET` 配置值，不新增明文凭据。

### 全量导入器

新增 `ingest_chatdoc.py`：

1. 扫描 `knowledge/` 中 ChatDoc 当前支持的 PDF、Word、PPT、文本和表格文件；
2. 对不超过 20 MB 的文件直接上传；
3. 对超过 20 MB 的文件先跳过，在 manifest 中记录
   `oversized_skipped`，由用户后续手动拆分后补充；
4. 创建带时间戳的新知识库，避免覆盖当前可用远端库；
5. 上传全部文件并等待全部 `vectored`；
6. 每批最多 20 个 fileId 加入知识库；
7. 原子写入 `artifacts/chatdoc/base.json`，记录 repoId、原始来源、上传文件名、
   fileId、SHA-256 和拆分部件；
8. 只有上述步骤全部成功后，才更新 `.env` 中的 `XF_CHATDOC_REPO_ID`。

失败时不切换本地正式配置。已上传的远端文件和新建知识库不自动删除，以免误删
用户资源；导入日志给出 repoId 和 fileId，便于后续清理或续跑。

### 运行时检索器

新增 `ChatDocRetriever`，保持现有 `retrieve(RetrieveRequest) -> RetrieveResponse`
接口。它调用 `vector/search`，把结果映射为现有 `Evidence`：

- `content` -> `text`；
- `fileId` 通过 `artifacts/chatdoc/base.json` 映射回 `knowledge/` 相对路径；
- `index` -> 稳定的 `start_pos`/分块标识；
- 平台分数若为 0-100 则除以 100，若为 0-1 则保持原值；
- `source_type` 从来源路径首级目录得到；
- 页码、章节和权威级别未知时保持为空或 `unknown`，不得伪造。

检索器在进程内缓存最近返回的 Evidence，供 `/v1/sources/{evidence_id}` 解析。
请求包含过滤条件时，先请求最多 20 个候选，再本地执行兼容过滤。

### 应用装配与健康检查

`build_container` 在配置了 `XF_CHATDOC_REPO_ID` 和 ChatDoc manifest 时只创建
ChatDoc 客户端/检索器，不加载本地向量库，也不创建查询 Embedding 客户端。
`/ready` 返回 `backend=chatdoc` 和 repoId 的非敏感短标识；`/health` 保持不变。

若 ChatDoc 配置或 manifest 缺失，应用启动失败并报告通用配置错误，不静默回退
到旧本地库，避免两个向量空间在生产中混用。

## 安全与限制

- 单文件上传上限按 20 MB 执行，超限文件不自动拆分或上传；
- 上传路径必须来自 `knowledge/` 内，拒绝符号链接和路径穿越；
- 日志不得打印 appId、APISecret、完整签名或完整上游错误正文；
- 本地 manifest 原子发布，权限保持为当前用户可读写；
- 不自动删除任何现有本地或远端知识库；
- 项目级知识库暂不迁移，本次只迁移 base 知识库。

## 验证

- 单元测试验证鉴权、协议校验、分数归一化、来源映射和超限文件跳过；
- 契约测试验证容器不再加载本地 VectorStore、来源接口仍可解析 Evidence；
- 全量导入后逐文件确认状态为 `vectored`，并核对 manifest 覆盖所有源文件；
- 最终执行一次 `vector/search` 冒烟，仅验证官方库可检索，不进行先导样本对比。

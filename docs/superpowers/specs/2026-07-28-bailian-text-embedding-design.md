# 百炼文本 Embedding 节点设计

## 目标

在不改变现有讯飞导入、OCR、文件解析、切块、缓存或运行时查询逻辑的前提下，新增一个可独立执行的百炼文本 Embedding 构建路径。

该路径使用阿里云百炼 `text-embedding-v4`，为现有 `knowledge/` 中已经抽取出的文本生成新的向量索引，供后续质量验证和运行时迁移使用。

## 范围

本阶段新增以下两个文件：

- `app/clients/bailian_embedding.py`：百炼 OpenAI 兼容 Embedding API 的异步客户端。
- `build_bailian_vector_store.py`：独立的基线构建脚本。

本阶段不修改下列行为或模块：

- `ingest_knowledge.py` 与现有讯飞 Embedding 调用。
- OCR、`ocr_cache/`、PDF/Office 文件转换与文本读取逻辑。
- 现有切块参数与切块规则。
- `app/main.py`、检索器和线上查询供应商选择。
- 现有 `vector_store/base/` 内容。

## 百炼客户端

`BailianEmbeddingClient` 使用 `httpx.AsyncClient` 调用百炼的 OpenAI 兼容接口：

`POST {BAILIAN_BASE_URL}/embeddings`

请求使用 `Authorization: Bearer {DASHSCOPE_API_KEY}`，模型固定为
`text-embedding-v4`。客户端实现与现有讯飞客户端相同的最小接口：

```python
async def embed(self, text: str, domain: str) -> np.ndarray:
    ...

async def close(self) -> None:
    ...
```

`domain` 仅为兼容现有调用方保留，百炼请求不传递该参数。客户端验证 HTTP
状态、响应中向量存在性、向量为有限的 `float32` 数值，并将网络、认证、限流和
格式异常统一转换为现有的 `ProviderUnavailable` 错误。

运行所需环境变量：

- `DASHSCOPE_API_KEY`：百炼 API Key。
- `BAILIAN_BASE_URL`：百炼业务空间的 OpenAI 兼容 Base URL，不含 `/embeddings`。

`BAILIAN_BASE_URL` 只从环境变量读取，不将业务空间 ID 或密钥写入仓库。

## 独立构建脚本

`build_bailian_vector_store.py` 只替换“文本块到向量”这一个节点。它复用当前项目
的文本读取、清洗、切块、索引构建和安全发布方式，保持当前的 600 字符块大小与
100 字符重叠。

脚本的输入为 `knowledge/`，输出固定为：

```text
vector_store/bailian-base/
  vectors.npy
  chunks_metadata.json
  manifest.json
```

向量维度固定为 1024。生成过程中先写入同级暂存目录；仅在所有文本块都得到有效
向量、索引成功构建后，才原子发布到 `vector_store/bailian-base/`。构建失败时，
之前已发布的百炼索引不被覆盖。

manifest 必须记录：

- `embedding_provider: "bailian"`
- `embedding_model: "text-embedding-v4"`
- `embedding_dimension: 1024`
- 实际使用的 Base URL（不含密钥）
- 当前 parser 版本、块大小和重叠量

百炼与讯飞的向量空间不同；即使未来调整为相同维度，也不得复用或混合两个供应商
生成的向量。当前阶段的新输出使用独立目录，避免覆盖 `vector_store/base/`。

## 错误处理

- 缺少任一百炼环境变量时，脚本在读取文件前退出并说明缺少的变量名。
- 单次请求可重试的网络错误、429 和 5xx 错误使用有限次数的指数退避。
- 非可重试认证错误、模型错误或无效响应立即失败，并且不发布暂存索引。
- 脚本必须在同一事件循环中关闭 HTTP 客户端。

本阶段不新增 Embedding 断点缓存。token 耗尽时会使本次独立构建失败，但不会影响
现有讯飞索引或 OCR 缓存；断点续跑作为后续单独变更处理。

## 验证

- 为客户端添加单元测试：成功响应、401、429 后重试、5xx 后重试、无效 JSON 和
  非法向量。
- 为构建脚本添加单元测试：缺少配置、使用假客户端构建 1024 维索引、manifest
  供应商/模型/维度写入正确、失败时不发布产物。
- 在线冒烟测试仅调用一段固定文本，确认返回 1024 维向量；全量知识库构建在确认
  API Key、配额与费用预算后人工执行。

## 后续迁移边界

本阶段完成后，仍需一个独立变更才能让线上查询使用百炼：将运行时 Embedding
客户端改为可配置供应商，并把 `vector_store_dir` 切换到经过验收的
`vector_store/bailian-base/`。该迁移不属于本设计。

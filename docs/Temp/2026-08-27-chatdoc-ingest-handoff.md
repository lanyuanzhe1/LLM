# 讯飞 ChatDoc PDF 入库交接

## 下一会话目标

直接使用讯飞 ChatDoc 官方服务，把 `knowledge/` 中的 PDF 等知识文件完成云端解析、OCR、自动切分、向量化和入库，并将成功发布的基础知识库接入当前应用。

用户口中的 `vector_store/base` 应优先理解为“基础知识库”。ChatDoc 的向量保存在讯飞远端，不会生成本地 `vector_store/base/vectors.npy`。当前代码已明确删除本地切分、Embedding 和向量库实现；除非用户再次明确要求改变架构，否则不要恢复本地向量文件。成功后的本地指针是 `artifacts/chatdoc/base.json`，远端实体是 ChatDoc repo。

## 已完成状态

- ChatDoc-only 迁移已提交：`ff4e63b`（`功能：迁移 RAG 后端至讯飞 ChatDoc`）。直接查看该提交和以下设计资料，不在本交接重复代码细节：
  - `docs/superpowers/specs/2026-08-27-iflytek-chatdoc-rag-design.md`
  - `docs/superpowers/plans/2026-08-27-iflytek-chatdoc-rag.md`
- 工作树当前干净。
- 当前入口：`ingest_chatdoc.py`。
- 上传实现：`app/ingest/chatdoc_upload.py`；ChatDoc 客户端：`app/clients/iflytek_chatdoc.py`。
- 本地 `artifacts/chatdoc/base.json` 尚不存在，`.env` 尚未切换到新 repo。
- 最新离线验证使用 `/opt/homebrew/Caskroom/miniconda/base/bin/python`：`626 passed, 4 deselected`。
- base 环境已安装 `requirements-dev.txt`，包括兼容版本的 pytest 与 pytest-asyncio。

## 当前外部阻塞与远端残留

- 上一次实际上传在第二个文件处收到 ChatDoc 业务码 `66001`，含义是账号余量/额度不足。
- 当时已创建远端 repo：
  - 名称：`粮食储藏知识库-20260827-153358`
  - repo ID：`683c9987a16a470bb1b460f4efc911a2`
- 已上传一个文件：`其他论文/低温储粮技术应用进展研究_胡坤.pdf`。上传器只会在全部文件向量化后统一加入 repo，因此该 repo 可能仍为空，文件可能只存在于账号文件列表。
- 不要擅自删除这个远端 repo 或文件。当前 CLI 不支持续传；额度恢复后重新运行会创建一个新 repo，旧的部分资源留待用户以后决定是否清理。
- `.env` 中已有凭据，但不得打印、复制到文档或提交。不要记录鉴权头、APISecret 或原始含敏感信息的响应。

## 超限文件

以下文件为 `39,931,279` bytes，超过 ChatDoc 单文件 20 MiB 限制，现有上传器会按用户要求直接跳过：

`knowledge/河南工业大学论文/储粮中粮食自身呼吸与霉菌活动产生CO_2的特点_张燕燕.pdf`

不要自动拆分。用户会之后手动切开，再单独补传。

## 建议执行顺序

1. 先确认当前分支位于 `ff4e63b` 之后、工作树无意外改动，并阅读 `AGENTS.md`。本机 Python 使用：

   ```bash
   /opt/homebrew/Caskroom/miniconda/base/bin/python
   ```

2. 账号额度已恢复时，直接运行完整入库：

   ```bash
   /opt/homebrew/Caskroom/miniconda/base/bin/python ingest_chatdoc.py
   ```

3. 如果仍返回 `CHATDOC_UNAVAILABLE_66001`，不要修改 `.env`、不要伪造 manifest，也不要回退本地切分；明确告诉用户需要补充 ChatDoc 额度后再继续。

4. 成功后核验：
   - `artifacts/chatdoc/base.json` 已原子生成；
   - `backend == "iflytek_chatdoc"`；
   - 每个已接受文件都有 `vectored` 状态和远端 `file_id`；
   - `skipped_sources` 只包含预期超限文件；
   - `.env` 中 `XF_CHATDOC_REPO_ID` 与 manifest 一致；
   - 不要在终端输出 manifest 之外的凭据。

5. 使用 `IflytekChatDocClient.search()` 对新 repo 做一次真实检索冒烟，例如查询“低温储粮如何抑制害虫”，确认返回内容、分数和 `file_id` 能被 `ChatDocRetriever` 映射到原始 PDF 来源。

6. 启动应用并检查 `/ready` 报告 `backend: chatdoc`，再运行：

   ```bash
   /opt/homebrew/Caskroom/miniconda/base/bin/python -m pytest -m 'not online' -q
   ```

7. 报告远端 repo 名称/ID、成功文件数、跳过文件数、冒烟查询结果和测试结果。不要声称生成了本地向量文件；讯飞 ChatDoc 的向量库是远端托管的。

## 重要边界

- 不恢复 PyMuPDF、python-docx、本地 OCR、字符切分、讯飞旧 Embedding API、numpy/sklearn 索引或 `VectorStore` 回退。
- 不删除 `vector_store/`、`ocr_cache/` 或任何远端资源，除非用户明确授权。
- 不自动拆分超过 20 MiB 的 PDF。
- 只有全部已接受文件向量化并加入 repo 后，才允许发布 manifest 和切换 `.env`。
- 若用户确实要求物理生成 `vector_store/base`，先解释这与 ChatDoc-only 架构冲突并取得明确确认，不要自行推断。

## Suggested skills

- `superpowers:verification-before-completion`：远端入库、检索冒烟和本地测试都有新证据后再宣布完成。
- `diagnose` 或 `superpowers:systematic-debugging`：仅当额度恢复后仍出现非 `66001` 的上传、解析或检索异常时使用。
- `browser:control-in-app-browser`：只有必须进入讯飞控制台查看额度或资源状态且用户已登录时使用；不要用浏览器绕过 API 的错误处理。

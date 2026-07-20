# RAG 自动入库与云端联调交接

## 下一会话目标

完成设计并实现“将知识文件放入 `knowledge/` 后，可通过一个脚本完成解析、向量化、发布本地 RAG 向量库；运行时服务自动检索该库”的可维护入库闭环。随后在具备本地云端配置时完成真实云端验证。

## 当前仓库状态

- 当前分支：`main`，与 `origin/main` 同步；最新提交：`0ea4787 feat: add grain-storage hybrid technical core`。
- 本轮技术核心已合并进主目录，旧 `codex/hybrid-technical-core` worktree 与功能分支已删除。后续功能开发应新建隔离 worktree。
- 曾存在的合并前本地改动保留在 `stash@{0}`，不要随意 `stash pop`。
- 当前 `git status` 显示 `.env.example` 有未提交改动。不要读取、输出或提交其内容；若其中写入过真实凭据，应在服务商侧轮换后恢复为占位模板。真实配置只应位于被忽略的 `.env`。

## 已验证的能力

- 讯飞 Embedding 已用本机 `.env` 中的新配置完成一次真实最小请求，成功返回一条 **2560 维 float32** 向量。
- 测试只调用了 `build_vector_store.py` 的 `EmbeddingClient.embed()`，未打印密钥、鉴权头或原始响应。
- 技术核心的最近离线验证记录：`python -m pytest -m 'not online' -W error -q` 输出 `682 passed, 5 deselected`；`compileall` 和 Git diff 检查均通过。
- 本地服务已做过 smoke：`/health` 与 `/openapi.json` 可用；尚无 vector store 时 `/ready` 正确返回 `VECTOR_STORE_NOT_READY`。

## 当前 RAG 实现与缺口

- 现有全量构建脚本：[build_vector_store.py](../../build_vector_store.py)；流程是文档读取 → 清洗 → 分块 → 讯飞 Embedding → sklearn 索引/元数据发布。
- 当前支持：`.pdf`、`.docx`、`.txt`、`.md`。当前知识目录共有 18 个文件（17 PDF、1 DOCX）。
- 当前不支持：`.ppt`、`.pptx`；没有 OCR 处理扫描型 PDF；没有基于文件指纹的增量构建/删除同步；没有可重复执行的一键“导入并发布”命令。
- 运行时已有 RAG 挂载点：应用启动时 `app/main.py` 加载 `vector_store/`，成功后创建 `Retriever`；星辰工作流经受认证的 `/tools/v1/retrieve` 查询证据，`/tools/v1/citations/validate` 校验回答引用，再由 `/v1/chat` 与 `/v1/cases/analyze` 的工作流网关流式返回。请参考既有设计与工具契约，不要重建该链路：
  - [技术核心设计](../superpowers/specs/2026-07-19-hybrid-technical-core-design.md)
  - [技术核心计划](../superpowers/plans/2026-07-19-hybrid-technical-core.md)
  - [星辰工作流联调指南](../星辰工作流联调指南.md)
  - [工作流工具说明](../../workflow/README.md)

## 用户意图与约束

- 用户要的是：把上传的知识文件放进 `knowledge/`，通过一个串联子服务的脚本入库；模型回答时自动使用已发布的 RAG 库扩展知识。
- 用户明确提到 PDF、PPT 和“各种形式”。建议 v1 明确覆盖 PDF、PPTX、DOCX、TXT、Markdown；旧二进制 `.ppt` 与扫描件 OCR 需在设计阶段确认是否纳入本期，避免无声跳过。
- 用户允许开发阶段直接使用本机 `.env` 做付费云端调用，不需要为调用次数/费用反复确认。
- 即使开发阶段放宽流程，仍不得把密钥写进 Git、文档、日志或聊天；不要使用截图中已暴露的历史密钥。

## 下一代理建议步骤

1. 先使用 `superpowers:brainstorming`：当前只完成了上下文勘察与云端连通性验证，尚未提出并获得用户批准的自动入库设计。一次只问一个关键范围问题；先说明 PPT/PPTX、旧 PPT、扫描 OCR 的取舍。
2. 设计获批后，写入新的设计文档；不要重复技术核心设计中已经描述的运行时工作流和安全边界。
3. 使用 `superpowers:writing-plans` 写出分任务计划，并让用户确认采用既定的子代理驱动执行。
4. 新建 worktree 后执行。实现必须测试先行：覆盖格式路由、坏文件隔离、文件哈希增量、删除同步、原子发布、旧库回滚以及服务重启后的检索可见性。
5. 真实构建可使用本机 `.env`：通过 `set -a; source .env; set +a` 加载环境后运行脚本；先做小样本验证，再处理完整知识目录。不得把环境变量回显到输出中。
6. 完成后以 `RUN_ONLINE=1` 运行云端 Embedding/端到端测试，前提是 MaaS、工作流 Flow ID、工具公网 HTTPS 地址和向量库均已就绪；不要将“在线套件跳过”报告为真实联调成功。

## Suggested skills

- `superpowers:brainstorming`：自动入库属于新增功能，必须先完成设计并获得用户批准。
- `superpowers:writing-plans`：将获批设计拆成可独立审查的 TDD 任务。
- `superpowers:using-git-worktrees`：用户要求未来开发使用 worktree，先为该功能创建隔离目录。
- `superpowers:subagent-driven-development`：用户已选定此执行方式；每任务实现、审查、修复后再进入下一任务。
- `superpowers:test-driven-development`：入库、增量发布和运行时可见性全部先写 RED 测试。
- `superpowers:systematic-debugging`：云端 API 或格式解析异常先复现并定位，再修复。
- `superpowers:verification-before-completion` 与 `superpowers:finishing-a-development-branch`：完成前跑全量验证并按用户选择处理分支。

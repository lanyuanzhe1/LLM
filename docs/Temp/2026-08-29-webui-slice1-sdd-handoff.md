# `webui` 分支 Slice 1 SDD 执行交接

> 日期：2026-08-29
> 下一会话焦点：完成 Slice 1（登录→聊天→历史端到端）的剩余任务：Task 10+12 fix round 1 收尾、Task 13 验证、Phase C 前端（Tasks 14-16）、全分支终审与收尾。
> 执行方式：superpowers:subagent-driven-development（控制器 + 每任务实现者/审查者），已有进度全部记录在 ledger。

## 1. 仓库与执行状态

- 工作区：worktree `/Users/lanyuanzhe/Documents/GitHub/LLM/.claude/worktrees/webui-product`，分支 `worktree-webui-product`（基于 `webui` tip `31765ec` 快进）。**产品开发提交落在该分支；完成后需推送并由用户合并回 `webui`。**
- 架构设计（已提交）：`docs/superpowers/specs/2026-08-27-webui-product-architecture-design.md`（D1-D15 决策表是权威）。
- 实施计划（已提交）：`docs/superpowers/plans/2026-08-28-webui-slice1-chat-e2e.md`（Tasks 1-16，含逐步 TDD 与真实代码）。
- SDD 工作区（gitignored）：`.superpowers/sdd/2026-08-28-webui-slice1-chat-e2e/`
  - `progress.md` = **ledger（恢复执行的第一读物）**，含 pre-flight 扫描、逐任务完成行、全部 Ruling。
  - `task-N-brief.md` / `task-N-report.md` / `review-*.diff` 齐备。

## 2. 已完成（审查均通过，详见 ledger）

| 任务 | commit | 内容 |
|---|---|---|
| Phase A 1-5 | 708fc7b..5782c4e | app OpenAI 兼容层：config 字段、schemas、services（含 `build_workflow_message` 历史打包）、api + main.py 装配、契约测试 14 用例。app 侧离线回归 661 passed |
| Task 6 | 4f1dd4d | services/webui 骨架（settings/events stub/极简 db.py） |
| Task 7 | fb3ea78 | models 提取（config/users/auths/chats/chat_messages；`upsert_message_to_history` 逐字） |
| Task 8 | fd34523 | utils/auth + misc.parse_duration（删 api-key/加密 token/redis 吊销） |
| Task 9 | 6ac096c | auths 路由 + 最小 create_app（三处显式偏离：开放注册不关闭、无群组装配、permissions={}/头像=""） |
| Task 11 | 9ac30b5 | main 补全（/api/version、/api/config、/api/models 代理、SPA 托管）+ upstream.py |
| Task 10+12 | bf5e25d, a5d64df | chats 路由（404 属主语义）+ slim /api/chat/completions（chat_id 首帧、字节透传、消息图落库、失败整轮回滚）。15 passed |

## 3. 当前中断点：Task 10+12 fix round 1（未完成）

审查发现 1 个 Important：旁路 SSE 缓冲按块 `decode(errors='replace')` 会腐蚀跨 chunk 的中文（落库文本出 U+FFFD）。实现者修复到一半时因 API 额度 403 中断。

**工作区现状（未提交，3 个文件，+93/-28）：**
- `webui/routers/completions.py`：增量解码修复（`codecs.getincrementaldecoder('utf-8')`）已应用。
- `tests/conftest.py`：新增 `split_chunk_upstream` fixture —— **问题在这里**：`httpx.Response(200, content=[bytes1, bytes2])`（list 内容）导致 `client.stream()` 在发送时抛异常（httpx 0.28.1 MockTransport 对 iterable content 的 async stream 支持问题），于是该路径整轮回滚、chat 被删，测试 GET 拿到 404 体 → `KeyError: 'chat'`。
- `tests/test_completions.py`：新增回归测试 `test_completion_multibyte_delta_split_across_chunks`（断言落库文本无 U+FFFD 且完整）。

**修复方向**：把 mock 改为 `httpx.Response(200, headers=..., stream=<AsyncByteStream>)`——手写一个最小 `httpx.AsyncByteStream` 子类（`async def __aiter__` 逐块 yield），不要传 list content。

**收尾步骤**：修 mock → `cd services/webui && python -m pytest -q` 全绿（应 16 passed）→ commit（`fix(webui-service): incremental utf-8 decode for SSE side-buffer`）→ 生成 fix 审查包（FIX_BASE=a5d64df）→ 派发 scoped re-review（模板在 superpowers subagent-driven-development 技能的 re-review-prompt.md；findings 清单见 task-10-12-report.md 与 progress.md）→ 全绿后 ledger 记 `Task 10+12: fix round 1/5 (1 addressed, 0 open)` 与 `complete`。

## 4. 剩余任务

- **Task 13**：Phase B 全量验证（services/webui 套件 + 仓库根 `python -m pytest -m "not online" -q`）。
- **Phase C（Task 14-16）**：`frontend/webui` SvelteKit 骨架 + /auth 页 + 守卫 layout → 聊天页（SSE 解析 `src/lib/utils/sse.ts` 完整代码在计划里）→ 占位路由 + 联调。计划中有完整规格。
- **终审**：`scripts/review-package PLAN_FILE 31765ec HEAD` 生成全分支包，用最强模型按 requesting-code-review/code-reviewer.md 终审；ledger 中的 deferred minors 交给它分诊。
- **收尾**：superpowers:finishing-a-development-branch；推送分支并请用户合并回 `webui`；汇总所有 Ruling 给用户。

## 5. 关键裁决（Ruling）速查（详见 ledger）

1. T10 与 T12 合并派发（测试构成一个绿单元）。
2. T3 简报 SSE 测试两处缺陷已修正（helper 切片 off-by-one、status 位序断言），计划文件已同步修订（dfde131）。
3. chat_id 语义：提供但未存在→以该 id 新建；存在但他主→404；未提供→新 uuid4。
4. 许可事宜完全忽略（用户决定；example/openwebui/ 原样不动，提取文件不增删文件内声明）。

## 6. 环境要点（踩过的坑）

- Python：`/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python`；**pytest 必须在 `services/webui/` 目录下跑**（仓库根会拾错 pytest.ini → no tests ran）。
- worktree 会话对复杂 Bash（heredoc、重定向到仓库外）有限制；文件用 Write/Edit；临时脚本放 `/Users/lanyuanzhe/.claude/jobs/8121059f/tmp/`。
- **worktree 不含 .env**（gitignored）：真实 E2E 需回主检出或复制 .env；`.env` 还需补 `OPENAI_COMPAT_API_KEY`（app 新增必填项）。
- ChatDoc 基础库入库已由另一会话完成（30 文件 vectored，repo `d8689a0`，见记忆 chatdoc-base-ingest-state）；但记忆同时提示 "webui 缺 FLOW_ID"——app 真实启动前需核对 .env 的 `XF_WORKFLOW_FLOW_ID`。
- `.env.example` 类文件被根 .gitignore 全局规则拦截，需 `git add -f`。

## 7. Suggested skills

- `superpowers:subagent-driven-development`：继续按 ledger 执行（先读 `.superpowers/sdd/2026-08-28-webui-slice1-chat-e2e/progress.md` 恢复位置）。
- `superpowers:verification-before-completion`：每个里程碑的真实测试/构建证据。
- `superpowers:requesting-code-review`：终审。
- `superpowers:finishing-a-development-branch`：收尾。
- `superpowers:systematic-debugging`：仅在 mock 修复方向不成立时使用。

## 8. 下一位智能体启动提示词

```text
继续执行 LLM 仓库 webui 产品 Slice 1 的 SDD 流程。工作区是 worktree /Users/lanyuanzhe/Documents/GitHub/LLM/.claude/worktrees/webui-product（分支 worktree-webui-product），不要切回主检出。

开始前依次阅读：
1. docs/Temp/2026-08-29-webui-slice1-sdd-handoff.md（本交接，含当前中断点与修复方向）
2. .superpowers/sdd/2026-08-28-webui-slice1-chat-e2e/progress.md（ledger，恢复执行位置）
3. docs/superpowers/plans/2026-08-28-webui-slice1-chat-e2e.md（计划全文）

当前最优先事项：Task 10+12 fix round 1 收尾——工作区有 3 个未提交文件（增量 UTF-8 解码修复 + 回归测试），回归测试因 conftest 的 split_chunk_upstream mock 用 list content 触发 httpx client.stream 异常而红；按交接 §3 的方向把 mock 改为 AsyncByteStream，跑绿 services/webui 全套件后提交，再做 scoped re-review。随后按 ledger 继续 Task 13、Phase C（Tasks 14-16）、终审与分支收尾。

约束：Python 用 /opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python；pytest 在 services/webui/ 下运行；禁止 Mock 运行模式；不动 example/openwebui/；提交落在 worktree-webui-product 分支。
```

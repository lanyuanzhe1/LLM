# `webui` 分支 Slice 1 SDD 执行交接

> 日期：2026-08-29（第二次更新：Task 10+12 fix round 已闭环，Phase B 全绿，Task 14 已实现待审）
> 下一会话焦点：Task 14 审查 → Task 15 聊天页 → Task 16 占位路由与联调 → 全分支终审 → 收尾合并。
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
| Task 10+12 | bf5e25d, a5d64df, 166642a | chats 路由（404 属主语义）+ slim /api/chat/completions（chat_id 首帧、字节透传、消息图落库、失败整轮回滚）+ fix round 1（增量 UTF-8 解码修复，re-review 全 ADDRESSED）。16 passed |
| Task 13 | — | Phase B 全量验证（控制器直接执行）：services/webui 16 passed；app 离线 661 passed, 4 deselected |
| Task 14 | 2cc487d | frontend/webui 骨架：SvelteKit 2 SPA + Tailwind 4、/auth 双模式页、(app) 守卫 layout + 侧边栏、占位路由、auths API 6 单测；npm build 通过。**审查尚未派发——下一会话第一件事**（BASE=166642a，报告在 task-14-report.md） |

## 3. 当前位置：Phase C 进行中

fix round 已闭环（上版交接的 §3 中断点已解决，含 mock 改 `_ByteChunks` AsyncByteStream 子类的实际修法）。剩余：

- **Task 14 审查**（紧迫）：生成审查包（`scripts/review-package PLAN_FILE 166642a 2cc487d`）派发任务审查员。注意实现者自报疑虑：Svelte 5 下用了旧式 `on:click` 语法、登录成功固定回 `/`。
- **Task 15**：聊天页（发送→流式渲染→历史恢复）。计划中 `src/lib/utils/sse.ts` 有完整代码；后端 chat_id 首帧契约、source/status/error 扩展事件已在 services/webui 落地（16 passed 钉住）。
- **Task 16**：knowledge/agents/settings 占位路由 + 离线联调验证 + 全量测试与构建。
- **终审**：`scripts/review-package PLAN_FILE 31765ec HEAD` 生成全分支包，用最强模型按 requesting-code-review/code-reviewer.md 终审；ledger 中的 deferred minors 交给它分诊（含：preflight 时序用例 flake 风险、task_type 忽略契约用例、owned_by 命名残留、JWT 无吊销、cookie-only 正向用例、登录无限流等）。
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
1. docs/Temp/2026-08-29-webui-slice1-sdd-handoff.md（本交接）
2. .superpowers/sdd/2026-08-28-webui-slice1-chat-e2e/progress.md（ledger，恢复执行位置）
3. docs/superpowers/plans/2026-08-28-webui-slice1-chat-e2e.md（计划全文，Phase C 部分）

当前最优先事项：Task 14（frontend/webui 骨架，commit 2cc487d）已实现但审查未派发——先生成审查包（review-package PLAN_FILE 166642a 2cc487d）并派发任务审查员。随后按 ledger 继续 Task 15（聊天页+SSE）、Task 16（占位路由+联调）、全分支终审与分支收尾（finishing-a-development-branch）。

约束：Python 用 /opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python；pytest 在 services/webui/ 下运行；前端用 node v26/npm 11；禁止 Mock 运行模式；不动 example/openwebui/；提交落在 worktree-webui-product 分支。
```

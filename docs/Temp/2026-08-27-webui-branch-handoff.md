# `webui` 分支开发交接

> 日期：2026-08-27
> 下一会话焦点：基于 Open WebUI 参考源码，设计并开始搭建粮食储藏领域的正式 Web 产品。

## 1. 当前 Git 状态

- 仓库：`/Users/lanyuanzhe/Documents/GitHub/LLM`
- 当前分支：`webui`
- `main` 基线：`ff4e63b`（迁移 RAG 后端至讯飞 ChatDoc）
- 当前 HEAD：`c1154b4`（将 Open WebUI 参考源码放入 `example/`）
- `webui` 是从当前 `main` 分出的二次开发分支，后续 Web 产品开发提交应落在该分支。
- Open WebUI `v0.11.1` 完整参考源码已进入 `example/openwebui/`，共 5,059 个文件，没有嵌套 `.git`。
- 原克隆目录 `/Users/lanyuanzhe/Documents/GitHub/open-webui` 已移入 `~/.Trash/open-webui`，需要时可恢复。

## 2. 产品开发目标

这个分支不是把 Open WebUI 整套直接换品牌后上线，也不是从零重写一个大型前端。目标是：

1. 以 `example/openwebui/` 作为完整、只读的成熟参考实现。
2. 从中提取登录、用户、会话、聊天、历史记录、应用外壳等核心能力。
3. 在正式产品目录中按粮食储藏项目的需要逐步二次开发。
4. 不先运行 Open WebUI 全部功能再慢慢删减；从必要核心开始，一步步加入本项目的产品功能。

建议的正式代码边界：

```text
LLM/
├── example/openwebui/     # Open WebUI v0.11.1 完整参考，不直接作为产品修改
├── frontend/webui/        # 正式 SvelteKit 前端（待创建）
├── services/webui/        # 可选：提取的 Open WebUI 应用后端核心（目录待设计确认）
└── app/                   # 现有粮储领域 FastAPI/ChatDoc 服务
```

## 3. 已确认的架构边界

采用“应用服务 + 粮储领域服务”，部署时是两个后端进程，但不是两套重复业务：

```text
浏览器
  └── 正式 WebUI
        ├── Open WebUI 应用服务
        │     └── 登录、用户、权限、会话、聊天历史
        └── LLM 粮储领域服务
              └── ChatDoc RAG、引用、案例分析、领域工具与 Agent 工作流
```

- 登录、用户权限和会话保存必须使用 Open WebUI 已有成熟能力，不重造。
- 未来必须有教师端和学生端，但教师/学生的注册、授权、群组和权限模型本次未决定，不得自行假设。
- Open WebUI 原生只有 `admin/user/pending` 系统角色，它们不应直接被替换为教师/学生。这是后续设计输入，不是已确认实施方案。

## 4. 第一阶段功能面

第一阶段不只是登录和聊天，必须同时包含基础知识库展示与智能体广场。

### 4.1 必须实现

- 用户注册/登录与基础权限校验。
- 新建对话、流式粮储问答、历史会话保存与恢复。
- 基础知识库文件列表。
- 点击基础知识库文件后，展示 ChatDoc 实际切分的知识块。
- 智能体广场页面与卡片。
- 为智能体跳转预留稳定接口；卡片最终可跳到另一个页面/已发布智能体地址。
- 基础粮储品牌与精简导航。
- 个人设置；管理员保留用户管理入口。

### 4.2 首版不启用/不展示

Open WebUI 参考实现中的以下功能首版不启用，导航和普通用户路由不应显示：

- Channels
- Workspace
- Models
- Prompts
- Tools / Functions
- Notes
- Calendar
- Automations
- Playground
- Open WebUI 自带知识库

这些参考代码不要在 `example/openwebui/` 删除；以后可按需移植。

## 5. 聊天主链路

当前 `app/api/chat.py` 的 `POST /v1/chat` 已返回 SSE 流，但它不是 Open WebUI 默认期待的 OpenAI 协议。

旧 `develop-openwebUI` 分支中已存在完整的 OpenAI 兼容层与测试：

- `app/api/openai_compat.py`
- `app/schemas/openai_compat.py`
- `app/services/openai_compat.py`
- `tests/contract/test_openai_compat_api.py`

不要整体合并 `develop-openwebUI`：该分支包含基于旧本地 RAG/阿里百炼时期的大量提交。应审查后选择性移植 OpenAI 协议适配器，并改为调用当前 ChatDoc/工作流主链。

目标至少包含：

```text
GET  /v1/models
POST /v1/chat/completions
```

`/v1/chat/completions` 需要支持 Open WebUI 使用的流式事件协议，同时保留现有引用与工作流事件语义。

## 6. 基础知识库展示

只展示讯飞 ChatDoc 中的真实基础知识库数据。浏览器不能直接调用讯飞，必须由 `LLM/app` 代理，避免暴露凭据并隔离供应商协议。

讯飞官方接口已支持：

- `POST /openapi/v1/repo/file/list`
- `POST /openapi/v1/file/chunks`

项目应向前端提供稳定的只读接口，建议为：

```text
GET /v1/knowledge/files
GET /v1/knowledge/files/{file_id}/chunks
```

第一阶段只做公共基础知识库：

- 文件列表、处理状态与块数摘要（以讯飞真实返回为准）。
- 单文件的真实分块列表。
- 只读；不在本页做上传、编辑、删除、重新切分或向量展示。

个人知识库和项目知识库后续再在同一前端接口模型上扩展。

`docs/08-27_知识库文件展示与智能体广场技术方案.md` 的页面交互可作为参考，但其数据源仍是已删除的本地 `manifest.json/chunks_metadata.json`，实施时必须改为 ChatDoc API，不得恢复旧本地向量库。

## 7. 智能体广场

首版目标是展示智能体卡片，并可跳转到另一页面/已发布的智能体地址。不在本页重建智能体聊天系统。

建议预留：

```text
GET /v1/agents
```

返回卡片元数据和 `launch_url`。首版可从受控 JSON 配置读取，无需数据库；点击行为建议为新标签页打开受信任 HTTPS 链接。

已确认的只是“预留稳定接口并能外部跳转”。具体智能体列表、页面视觉和权限后续再讨论。

## 8. 真实数据与错误处理

- 用户明确拒绝 Mock 模式。
- 不准备假文件、假分块、假聊天流或运行时自动降级。
- ChatDoc 成功时展示真实数据；ChatDoc 失败时显示清晰、安全的服务错误。
- 不得恢复本地解析、OCR、Embedding、sklearn/FAISS 或本地向量库 fallback。
- 当前 ChatDoc 外部阻塞为供应商错误码 `66001`（账户额度/余额不可用）。详见 `docs/Temp/2026-08-27-chatdoc-ingest-handoff.md`。不要因此更换本地 manifest 或 repo 配置。

## 9. 建议实施顺序

1. 先基于本交接和现有文档写一份新的 `webui` 架构设计/实施计划，并明确哪些 Open WebUI 模块被提取。
2. 在 `frontend/webui/` 搭建最小可运行 SvelteKit 应用外壳，从参考源码移植必要配置、路由、存储、组件和样式。
3. 提取 Open WebUI 的身份、用户、会话与历史记录核心；先保持其成熟协议，不急于改教师/学生模型。
4. 审查并选择性移植旧 `develop-openwebUI` 的 OpenAI 兼容层，接入当前 `LLM/app` 工作流。
5. 完成登录—对话—流式回答—会话恢复主链。
6. 在 ChatDoc 客户端新增文件列表和分块读取，对外暴露只读基础知识库 API，实现对应页面。
7. 实现智能体广场卡片与跳转接口。
8. 精简导航、隐藏首版不启用模块，完成品牌、错误态、响应式和可访问性。
9. 运行前端单测/构建、应用服务测试、当前 Python 离线测试和真实端到端联调。

## 10. 第一阶段验收结果

- 用户能注册/登录，未登录用户不能进入受保护页面。
- 用户能新建粮储对话，看到流式回答，刷新后恢复历史会话。
- 用户能打开“基础知识库”，查看 ChatDoc 中的真实文件，并查看任一文件的真实分块。
- ChatDoc 失败时，页面显示可理解的错误，不伪造数据，不暴露凭据或供应商原始错误体。
- 用户能打开“智能体广场”，并通过预留的跳转契约前往另一页面。
- 普通用户看不到未启用的 Open WebUI 通用模块入口。
- 无本地 RAG fallback，无 Mock 运行模式，无敏感信息进入前端或版本库。

## 11. 明确暂缓/未决事项

这些事项不应阻塞第一阶段，也不得在未确认时自行扩展：

- 教师与学生的业务角色数据模型、注册和审批流程。
- 班级、课程、项目与群组权限。
- 个人知识库和项目知识库。
- 智能体的具体列表、跳转地址、卡片文案与详细视觉。
- 正式产品名称、Logo 和品牌规范。
- 生产部署拓扑、域名、SSO/OAuth 与外部身份源。
- Open WebUI 应用后端的正式目录与最小模块清单。

## 12. 现有文档和代码导航

- 当前 ChatDoc 架构决策：`docs/superpowers/specs/2026-08-27-iflytek-chatdoc-rag-design.md`
- 当前 ChatDoc 实施计划：`docs/superpowers/plans/2026-08-27-iflytek-chatdoc-rag.md`
- ChatDoc 导入现状与外部阻塞：`docs/Temp/2026-08-27-chatdoc-ingest-handoff.md`
- 讯飞 ChatDoc 官方接口整理：`docs/官网文档/讯飞_ChatDoc_API.md`
- 课程学习 Agent 产品与页面参考：`docs/07-29_课程学习Agent_MVP产品与前端方案.md`
- 知识库/智能体广场交互参考：`docs/08-27_知识库文件展示与智能体广场技术方案.md`（数据源部分已过时）
- Open WebUI 参考版本：`example/openwebui/package.json`
- 当前 ChatDoc 客户端：`app/clients/iflytek_chatdoc.py`
- 当前 ChatDoc 检索适配器：`app/rag/chatdoc_retriever.py`
- 当前流式聊天入口：`app/api/chat.py`

## 13. 开发约束

- 遵循仓库根目录 `AGENTS.md`。
- Python 命令使用 `/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python`。
- 包安装使用该 Python 的 `python -m pip`，不用系统 Python 或 base `pip`。
- 凭据只从 `.env` 读取，不得进入源码、前端包或日志。
- 供应商错误必须转换为安全应用错误，不返回原始错误体或认证头。
- 修改参考源码时先考虑 Open WebUI 的当前许可证、商标和 `LICENSE_NOTICE`，不删除依法必须保留的声明。

## 14. Suggested skills

下一会话建议按任务选用：

- `superpowers:brainstorming`：在确定正式目录和提取模块前完成架构设计。
- `superpowers:writing-plans`：将双服务、前端提取、ChatDoc 展示与智能体广场分成可验证实施步骤。
- `superpowers:test-driven-development`：实现协议适配、权限、ChatDoc 文件/分块 API 时先写契约测试。
- `minimax-skills:frontend-dev`：搭建和打磨正式 SvelteKit 前端。
- `diagnose` 或 `superpowers:systematic-debugging`：只在出现可复现故障时使用。
- `superpowers:verification-before-completion`：每个里程碑完成前运行测试、构建和 Git 状态验证。

## 15. 下一位智能体启动提示词

```text
请接手 `/Users/lanyuanzhe/Documents/GitHub/LLM` 仓库 `webui` 分支的 Open WebUI 二次开发。

开始前：
1. 完整阅读仓库根目录 `AGENTS.md`。
2. 完整阅读 `docs/Temp/2026-08-27-webui-branch-handoff.md`。
3. 核对当前分支、Git 状态和最近提交，保留用户已有改动。
4. 按 handoff 中的 Suggested skills 选择并遵循适用技能。

本次工作目标：先为 `webui` 分支产出可执行的架构设计和分阶段实施计划，然后从第一个最小端到端切片开始实现。完整 Open WebUI `v0.11.1` 仅作为 `example/openwebui/` 下的只读参考；正式产品从必要核心模块开始提取，不直接启用全部 Open WebUI 再逐步删减。

第一阶段必须覆盖：注册/登录与基础权限、聊天与历史会话、当前 ChatDoc 粮储问答链路、公共基础知识库的真实文件/分块展示，以及可跳转的智能体广场。首版隐藏 handoff 列出的 Open WebUI 通用模块。

强制约束：
- 禁止 Mock 数据或 Mock 运行模式。ChatDoc 失败就返回安全、明确的错误。
- 禁止恢复本地解析、OCR、Embedding、sklearn/FAISS 或本地向量库 fallback。
- 不整体合并旧 `develop-openwebUI` 分支；只审查并选择性移植已验证的 OpenAI 兼容层。
- 不把讯飞凭据、原始错误体或认证头暴露给前端。
- 教师/学生权限模型、个人/项目知识库和智能体详细配置仍属未决事项，未经用户确认不要自行扩展。

如果能从代码和现有文档得到答案，直接调研，不要把纯技术问题反问用户。对确实会改变产品方向的未决项，每次只问一个问题，并给出推荐答案。实现后运行与风险相称的测试和构建，报告真实结果。
```

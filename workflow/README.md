# 粮储智研助手星辰工作流 v1

`tool_contracts.json` 是四个星辰工具节点的唯一离线契约：其中每个
`request_schema` 和 `response_schema` 都是服务端 Pydantic 模型的完整 JSON
Schema（含 `$defs`、`required`、enum、范围、默认值和
`additionalProperties`）。它不是星辰可直接导入的 Flow export；完整 Flow
export 尚未发布，须按以下映射在平台创建并在线发布后取得 Flow ID。

## 开始节点

按字符串类型创建七个输入：

1. `AGENT_USER_INPUT`
2. `REQUEST_ID`
3. `SESSION_ID`
4. `USER_ROLE`
5. `TASK_TYPE`
6. `CASE_JSON`
7. `PROJECT_ID`

## 节点与分支

1. 开始节点。
2. `TASK_TYPE == "case_analysis"` 进入案例分支，否则进入知识问答分支。
3. 案例分支调用 `grain_case_evaluate`，传入 `REQUEST_ID` 和解析后的 `CASE_JSON`。
4. `needs_input == true` 时，消息节点输出工具返回的 `question`，然后结束。
5. 问答分支和完整案例分支调用 `grain_retrieve`：
   - `request_id = REQUEST_ID`
   - `query = AGENT_USER_INPUT`；案例分支把 `CASE_JSON` 与分析目标拼接为查询
   - `top_k = 5`
   - `filters = {}`
6. `quality.sufficient == false` 时输出“当前知识库没有找到足够证据，暂时无法给出可靠结论。”，然后结束。
7. 调用 `grain_generate`，传入问题、角色、任务类型和 `evidences`。
8. 调用 `grain_citation_validate`，传入 `answer` 和相同的 `evidences`。
9. `valid == false` 时只重试一次 `grain_generate`，并把 `errors` 和 `unsupported_sentences` 传入 `validation_feedback`。
10. 第二次验证仍失败时，只输出固定安全拒答；`citations` 事件仅携带服务器 evidence ID。任何公开消费者不得直接消费未验证的星辰输出。
11. 验证成功时输出 `answer`。
12. 所有工具节点配置超时异常分支，输出统一的依赖暂不可用提示。

生成节点与引用验证节点共用以下输出文法：章节必须严格按
`结论 → 依据 → 适用条件 → 不确定性 → 来源` 排序。
“结论”“依据”“适用条件”“不确定性”章节只能使用纯文本、正常标点和合法 `[E#]` 行内引用；不得输出 HTML、HTML 实体、Markdown 格式、链接、图片或反斜杠转义，不得使用 Markdown block、引用后链接或定义、裸 URL、任意 scheme:// 链接或危险 scheme。
“来源”章节每个非空行必须完整写为 `[E#] description`；允许不加列表标记，或仅在行首使用 `- `、`* `、`+ `、`1. ` 形式的正整数有序标记；`description` 必须精确等于证据的 title、source 或 `title — source`，不得追加其他文本。

## 工具与嵌套对象映射

为每个 HTTP 工具节点选择 `POST`、`tool_contracts.json` 中的精确路径，并把
请求体设为 JSON。星辰的嵌套对象/数组字段必须整体映射为 JSON 值，不能展平
为字符串或省略子字段：

| 工具 | 请求映射 | 供后续节点使用的响应映射 |
| --- | --- | --- |
| `grain_retrieve` | `request_id`、`query`、`top_k`、`project_id`，以及对象 `filters` | 数组 `evidences` 原样传给生成和验证节点；对象 `quality.sufficient` 用于证据不足分支。 |
| `grain_generate` | `request_id`、`question`、`role`、`task_type`、数组 `evidences`、数组 `validation_feedback` | `answer` 传给验证节点；保留 `cited_evidence_ids` 与对象 `usage`。 |
| `grain_case_evaluate` | `request_id` 与对象 `case`（将 `CASE_JSON` 解析为对象） | 使用 `needs_input`、`missing_fields`、`question`；数组 `rules` 中每项保留 `conditions` 对象。 |
| `grain_citation_validate` | `request_id`、`answer`、数组 `evidences` | 使用 `valid`、`errors`、`unsupported_sentences`、`citation_ids`，并记录对象 `coverage.total_sentences`、`coverage.cited_sentences`、`coverage.ratio`。 |

服务拒绝多余的请求字段；请以每个节点的 `request_schema` 约束输入。响应 schema
中的嵌套 `$defs` 是自包含定义，映射时保留 null、默认值和数组边界。`coverage`
是结构性引文检查的统计，不表示语义蕴含或风险结论。

## 工具配置

- 基础 URL 使用测试 HTTPS 地址。
- 路径、字段和完整 schema 读取 `tool_contracts.json`。
- Header 固定为 `Authorization: Bearer ${TOOLS_SERVICE_TOKEN}`。
- `TOOLS_SERVICE_TOKEN` 仅允许可见 ASCII 字符（`!` 至 `~`），确保 Bearer 认证兼容。
- 不在工作流提示词或固定变量中保存任何讯飞 API 密钥。

## 调用边界与公网暴露

- 调用方向固定为：面向用户的本地或另行授权的公开 `/v1/*` 调用星辰工作流，星辰只允许调用经过认证的 `/tools/v1/*`，`/tools/v1/*` 绝不调用星辰工作流，避免形成递归调用。
- 上述 `/v1/*` 工作流入口具体是 `/v1/chat` 和 `/v1/cases/analyze`；`/v1/sources/{evidence_id}` 是本地证据查询，不发起工作流。
- 给星辰使用的公网 HTTPS 隧道或反向代理必须采用路径白名单，仅允许 `/tools/v1/*`。同一入口上的 `/v1/*`、`/health`、`/ready`、`/openapi.json`、文档和管理路径均不对星辰公网暴露，除非另行授权并配置相应访问控制。
- 这是隧道或反向代理的暴露策略，不是删除或停用应用路由；这些路由仍可按本地或其他已授权入口的用途保留。

## 发布

1. 在星辰平台按本文件和离线契约完成调试。
2. 发布为 API。
3. 绑定用于本项目的讯飞应用。
4. 记录 API Flow ID 到本地 `XF_WORKFLOW_FLOW_ID`。
5. 每次工作流变更后点击“更新绑定”，再执行在线回归。

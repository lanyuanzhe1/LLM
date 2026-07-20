现在阶段为基于讯飞开放平台开发，用作河工大的储粮知识型垂类大模型

## 技术实体 v1

技术实体采用“本地 FastAPI + 讯飞星辰工作流 + 讯飞 Embedding + 本地向量库 + 讯飞 MaaS 微调模型”的混合架构。

安装、配置、工作流创建和在线验证见：

- `docs/superpowers/specs/2026-07-19-hybrid-technical-core-design.md`
- `docs/superpowers/plans/2026-07-19-hybrid-technical-core.md`
- `docs/星辰工作流联调指南.md`
- `workflow/README.md`

本地启动前先按联调指南完成配置；激活环境后使用环境中性的 `python`：

```bash
conda activate LLM
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

工具与公开 API 的领域数值使用严格 JSON 类型：数值字符串和布尔值不能代替
number/integer，布尔字段也不接受 `0`/`1`。数学上适用于浮点字段的 JSON 整数
可以使用，例如 `13` 可作为 `moisture_percent` 的值。

MaaS 和星辰工作流的 `*_TIMEOUT_SECONDS` 是一次请求从连接到流结束的总时限，
不是每帧可重新开始的时限。`*_MAX_FRAMES`、`*_MAX_PAYLOAD_BYTES` 和
`*_MAX_ANSWER_CHARS` 分别限制云端帧数、累计响应字节和回答字符数；
`GATEWAY_MAX_BUFFER_CHARS` 独立限制公开网关在安全校验前的缓冲量。所有值必须为
正数，超限会关闭流并返回该层既有的安全错误，不会释放尚未验证的回答。

本机已验证过的绝对解释器路径为
`/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python`，但它只适用于该 macOS
机器；其他平台请在 `conda activate LLM` 后使用 `python`。

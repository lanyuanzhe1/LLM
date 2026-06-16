# DeepSeek V4 API

> 官方文档：https://api-docs.deepseek.com/
>
> API 平台：https://platform.deepseek.com

## 核心信息

| 项目 | 值 |
|------|-----|
| **Base URL** | `https://api.deepseek.com` |
| **端点** | `/chat/completions` (OpenAI 兼容) |
| **认证** | `Authorization: Bearer <API_KEY>` |
| **模型 ID** | `deepseek-v4-flash` / `deepseek-v4-pro` |
| **上下文** | 1M tokens |
| **最大输出** | 384K tokens |

## 定价

| | V4 Flash | V4 Pro |
|---|---|---|
| 输入 (cache miss) | $0.14/M | $0.435/M |
| 输入 (cache hit) | $0.0028/M | $0.003625/M |
| 输出 | $0.28/M | $0.87/M |

最低充值 $2。

## Python 调用（OpenAI SDK）

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-api-key",
    base_url="https://api.deepseek.com",
)

response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "system", "content": "你是一个有帮助的助手"},
        {"role": "user", "content": "解释什么是 MoE 架构"},
    ],
    temperature=1.0,   # 官方推荐
    top_p=1.0,         # 官方推荐
    max_tokens=2048,
    stream=False,
)

print(response.choices[0].message.content)
```

## Python 调用（requests 无 SDK）

```python
import requests

resp = requests.post(
    "https://api.deepseek.com/chat/completions",
    headers={
        "Authorization": f"Bearer YOUR_API_KEY",
        "Content-Type": "application/json",
    },
    json={
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "你好"}],
        "temperature": 1.0,
        "max_tokens": 200,
    },
    timeout=120,
)
print(resp.json()["choices"][0]["message"]["content"])
```

## 思考模式 (Thinking Mode)

```python
response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "问题"}],
    reasoning_effort="high",   # low / medium / high / max
    extra_body={"thinking": {"type": "enabled"}},
)
```

## 重要提醒

- 旧模型名 `deepseek-chat` 和 `deepseek-reasoner` 于 **2026年7月24日** 弃用
- 推荐参数：`temperature=1.0`, `top_p=1.0`
- 支持 Function Calling 和 JSON Mode
- 并发限制：Flash 2500, Pro 500

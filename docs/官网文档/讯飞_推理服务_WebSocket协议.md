# 推理服务_WebSocket协议（官方原文）

> 来源：https://www.xfyun.cn/doc/spark/推理服务-websocket.html
>
> 接口地址：`wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat`

## 1. 接口说明

### 1.1 请求方法和URL

```
wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat
```

部分模型因部署配置不同，请求地址可能略有差异，具体参考服务管控→模型服务列表右侧的调用信息。

### 1.2 接口要求

- 接口类型：流式 WebSocket 接口
- 鉴权：签名机制，参见通用URL鉴权文档

### 1.3 接口Demo

Python demo: https://openres.xfyun.cn/xfyundoc/2025-02-25/2440a0cc-11f3-46e7-920b-f49714f54003/1740484845579/python_ws_demo.zip

Java demo: https://openres.xfyun.cn/xfyundoc/2025-02-09/d8c9a423-5c0d-40e3-8480-a51045bb8e43/1739115838803/Java_demo.zip

使用前请替换 `app_id`、`key`、`secret` 和 `patch_id`（精调模型必传）。

## 2. 接口请求

### 2.1 请求示例

```json
{
    "header": {
        "app_id": "123456",
        "uid": "39769795890",
        "patch_id": ["xxx"]
    },
    "parameter": {
        "chat": {
            "domain": "<YOUR_MODEL_ID>",
            "temperature": 0.5,
            "top_k": 4,
            "max_tokens": 2048,
            "auditing": "default",
            "chat_id": "xxx"
        }
    },
    "payload": {
        "message": {
            "text": [
                {"role": "system", "content": "你是星火认知大模型"},
                {"role": "user", "content": "今天的天气"}
            ]
        }
    }
}
```

### 2.2 请求参数

#### 2.2.1 Header 参数

| 字段 | 类型 | 必传 | 说明 |
|------|------|------|------|
| `app_id` | string | 是 | 应用app_id |
| `uid` | string | 否 | 用户ID |
| `patch_id` | array | 否 | **调用微调大模型时必传**，对应resourceId |

#### 2.2.2 parameter.chat 参数

| 字段 | 类型 | 必传 | 说明 | 默认值 |
|------|------|------|------|--------|
| `domain` | string | 是 | 模型modelId | — |
| `temperature` | float | 否 | 核采样阈值 | 0.5 |
| `top_k` | int | 否 | 从k个候选中随机选择 | 4 |
| `max_tokens` | int | 否 | 回答最大token数 | 2048 |
| `chat_id` | string | 否 | 关联用户会话 | — |
| `search_disable` | boolean | 否 | 关闭联网搜索 | true |
| `show_ref_label` | boolean | 否 | 返回信源信息 | false |
| `response_format` | object | 否 | JSON输出 `{"type":"json_object"}` | — |
| `enable_thinking` | boolean | 否 | 深度思考模式(Qwen3) | true |
| `extra_body` | string | 否 | JSON扩展参数 | — |

#### extra_body 子参数

| 参数 | 说明 |
|------|------|
| `reasoning_effort` | low/medium/high (OpenAI OSS模型) |
| `stop` | 停止字符串数组 (DeepSeek V3&R1) |
| `continue_final_message` | 对话前缀续写 (DeepSeek V3&R1) |

#### 2.2.3 payload.message.text

| 字段 | 类型 | 必传 | 说明 |
|------|------|------|------|
| `role` | string | 是 | system/user/assistant |
| `content` | string | 是 | 对话内容 |

有效内容不超过 8192 tokens。多轮交互按 user→assistant→user→assistant 顺序。

## 3. 接口响应

### 3.1 成功响应（最终帧）

```json
{
    "header": {
        "code": 0,
        "message": "Success",
        "sid": "cht000704fa@dx16ade44e4d87a1c802",
        "status": 2
    },
    "payload": {
        "choices": {
            "status": 2,
            "seq": 0,
            "text": [
                {"content": "xxxxs", "index": 0, "role": "assistant"}
            ]
        },
        "usage": {
            "text": {
                "completion_tokens": 0,
                "question_tokens": 0,
                "prompt_tokens": 0,
                "total_tokens": 0
            }
        }
    }
}
```

### 3.2 响应字段

**header:**

| 字段 | 说明 |
|------|------|
| `code` | 0=成功，非0=出错 |
| `sid` | 会话sid |
| `status` | 0=首结果，1=中间，2=最终 |

**choices.text:**

| 字段 | 说明 |
|------|------|
| `content` | AI回复文本 |
| `reasoning_content` | 思考内容（深度思考模型） |
| `role` | assistant |

**usage.text（仅最终帧）:**

| 字段 | 说明 |
|------|------|
| `completion_tokens` | 回答tokens |
| `question_tokens` | 问题tokens（不含历史） |
| `prompt_tokens` | 总提示tokens |
| `total_tokens` | 总tokens |

## 4. 连接管理

- 长连接接口，交互完成后必须主动关闭
- 60秒无数据交互，服务端主动断开
- 同一用户不能多处同时连接
- 必须等大模型完全回复后才能发送下一个问题

## 5. 错误码

| 码 | 说明 |
|----|------|
| 0 | 成功 |
| 10000 | 升级为ws出错 |
| 10003 | 用户消息格式错误 |
| 10006 | 同一用户多处同时连接 |
| 10007 | 需等当前回复完再发新请求 |
| 10008 | 服务容量不足 |
| 10013 | 用户问题涉敏，拒绝处理 |
| 10014 | 回复涉敏，不展示 |
| 10016 | appid授权错误 |
| 10110 | 服务忙 |
| 10163 | 引擎参数异常 |
| 10907 | token超上限 |
| 11200 | 功能未授权或业务量超限 |
| 11201 | 日流控超限 |
| 11202 | 秒级流控超限 |
| 11203 | 并发流控超限 |

# 讯飞 MaaS 推理服务 WebSocket API

> 官方文档：https://www.xfyun.cn/doc/spark/推理服务-websocket.html
>
> 接口地址：`wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat`

## 鉴权

HMAC-SHA256 签名，同 Embedding API。每个请求需签名 URL。

## 请求格式

```json
{
  "header": {
    "app_id": "5c75015a",
    "patch_id": ["resourceId"],    // ← 精调模型必传，普通模型不传
    "uid": "用户ID"
  },
  "parameter": {
    "chat": {
      "domain": "modelId",          // 模型ID（从服务列表获取）
      "temperature": 0.5,
      "top_k": 4,
      "max_tokens": 2048
    }
  },
  "payload": {
    "message": {
      "text": [
        {"role": "user", "content": "问题"}
      ]
    }
  }
}
```

## 关键参数

| 参数 | 说明 |
|------|------|
| `patch_id` | 精调模型 resourceId，**必传** |
| `domain` | 模型 serviceId（网页获取） |
| `temperature` | 0-1（DeepSeek 系列 0-2） |
| `max_tokens` | 默认 2048 |

## 流式响应

status：0=首包, 1=中间, 2=结束
content 在 `payload.choices.text[].content`
最终帧含 `payload.usage.text` (token 统计)

## 错误码

| 码 | 说明 |
|----|------|
| 0 | 成功 |
| 10013 | 问题涉敏，拒绝处理 |
| 10016 | 授权错误（未开通/余额不足/并发超限） |
| 11200 | 功能未授权或业务量超限 |
| 11201 | 日流控超限 |
| 11202 | 秒级流控超限 |

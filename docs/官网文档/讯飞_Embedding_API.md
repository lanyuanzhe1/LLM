# 讯飞 LLM Embedding API

> **官方文档**：https://www.xfyun.cn/doc/spark/Embedding_api.html
>
> 服务页面（开通）：https://www.xfyun.cn/services/embedding
>
> 接口类型：HTTP POST，非流式，HMAC-SHA256 签名鉴权
>
> 接口地址：`POST https://emb-cn-huabei-1.xf-yun.com/`

## 接口地址

```
POST https://emb-cn-huabei-1.xf-yun.com/
```

全链路请求会话时长不超过 1 分钟。

## 鉴权方式

使用 HMAC-SHA256 签名机制。每个请求需要在 Header 中携带：

| Header | 说明 |
|--------|------|
| `Host` | `emb-cn-huabei-1.xf-yun.com` |
| `Date` | RFC1123 格式 UTC 时间 |
| `Digest` | `SHA-256=` + Base64(SHA256(请求Body)) |
| `Authorization` | `api_key="xxx", algorithm="hmac-sha256", headers="host date request-line digest", signature="xxx"` |

### 签名原文格式

```
host: emb-cn-huabei-1.xf-yun.com
date: Sun, 14 Jun 2026 16:07:17 GMT
POST / HTTP/1.1
digest: SHA-256=xxxxx
```

### 签名生成

```python
signature_sha = hmac.new(
    api_secret.encode('utf-8'),
    signature_origin.encode('utf-8'),
    digestmod=hashlib.sha256
).digest()
signature = base64.b64encode(signature_sha).decode('utf-8')
```

## 请求格式

```json
{
    "header": {
        "app_id": "5c75015a",
        "uid": "随机UUID",
        "status": 3
    },
    "parameter": {
        "emb": {
            "domain": "query",          // "query" 或 "para"
            "feature": {
                "encoding": "utf8",
                "compress": "raw",
                "format": "plain"
            }
        }
    },
    "payload": {
        "messages": {
            "encoding": "utf8",
            "compress": "raw",
            "format": "json",
            "status": 3,
            "text": "<base64编码的文本>"
        }
    }
}
```

### domain 参数

| 值 | 用途 |
|----|------|
| `query` | 用户问题向量化 |
| `para` | 知识库文档向量化 |

### text 编码

`payload.messages.text` 需要 Base64 编码，原始格式为：
```json
{"messages":[{"content":"文本内容","role":"user"}]}
```

## 响应格式

```json
{
    "header": {
        "code": 0,
        "message": "success",
        "sid": "ase000704fa@dx16ade44e4d87a1c802"
    },
    "payload": {
        "feature": {
            "encoding": "utf8",
            "compress": "raw",
            "format": "plain",
            "text": "<base64编码的2560维浮点向量>"
        }
    }
}
```

## 向量解析

```python
import base64, numpy as np
feature_b64 = result["payload"]["feature"]["text"]
vector_bytes = base64.b64decode(feature_b64)
vector = np.frombuffer(vector_bytes, dtype=np.dtype(np.float32).newbyteorder("<"))
# 2560 维 float32 向量
```

## 错误码

| 码 | 说明 |
|----|------|
| 0 | 成功 |
| 10009 | 输入数据非法 |
| 10010 | 授权许可不足或已满 |
| 10139 | 参数错误 |
| 10163 | 参数校验失败 |
| 10200 | 读取数据超时（累计10s未发送且未关闭连接） |
| 10313 | appid 与 apikey 不匹配 |
| 11200 | 功能未授权 |
| 11201 | 当日交互次数超限 |

## 限制

- 输入：0-2048 Token，文本 Base64 编码后 ≤2KB
- 输出：2560 维 float32 向量（Base64 编码二进制）
- 超时：全链路不超过 1 分钟
- 会话：单次连接累计 10s 未发送数据则断开

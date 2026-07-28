# 讯飞 PDF OCR（文档识别）API

> 官方文档：https://www.xfyun.cn/doc/words/pdfOcr/API.html
> 控制台：https://console.xfyun.cn/services/pdfOcr

## 概述

基于讯飞星火大模型底座的 PDF 文档识别服务，直接上传 PDF 文件即可提取文字、公式、表格等内容。支持输出 Word / Markdown / JSON 三种格式（含公式的课件推荐 Markdown）。

## 认证信息

| 字段 | 值 |
|------|-----|
| APP_ID | `5c75015a` |
| APISecret | `YTQxNzQ1MjhkNzljODMxYTQ1OTRiMWZh` |

## 鉴权方式

在 HTTP Header 中携带三个字段：

```python
import hashlib, hmac, base64, time

app_id = "5c75015a"
secret = "YTQxNzQ1MjhkNzljODMxYTQ1OTRiMWZh"
timestamp = str(int(time.time()))

md5_hash = hashlib.md5((app_id + timestamp).encode()).hexdigest()
hmac_sha1 = hmac.new(secret.encode(), md5_hash.encode(), hashlib.sha1).digest()
signature = base64.b64encode(hmac_sha1).decode()

headers = {
    "appId": app_id,
    "timestamp": timestamp,
    "signature": signature,
}
```

## 接口

### 1. 创建任务

```
POST https://iocr.xfyun.cn/ocrzdq/v1/pdfOcr/start
Content-Type: multipart/form-data
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 二选一 | 上传 PDF 文件 |
| `pdfUrl` | String | 二选一 | PDF 公网可访问 URL |
| `exportFormat` | String | 否 | `word`(默认) / `markdown` / `json` |

**成功响应：**
```json
{
    "flag": true,
    "code": 0,
    "desc": "成功",
    "data": {
        "taskNo": "26072336446997",
        "status": "CREATE",
        "tip": "任务创建成功"
    }
}
```

### 2. 查询状态

```
GET https://iocr.xfyun.cn/ocrzdq/v1/pdfOcr/status?taskNo={taskNo}
```

轮询间隔 ≥ 5 秒。状态值：`CREATE` → `WAITING` → `DOING` → `FINISH`（完成）/ `FAILED`（失败）

**成功响应：**
```json
{
    "flag": true,
    "code": 0,
    "data": {
        "taskNo": "26072336446997",
        "status": "FINISH",
        "downUrl": "http://bjcdn.openstorage.cn/ocrzdq/ocr/.../file.md",
        "tip": "已完成",
        "pageList": [
            {"pageNum": 1, "status": "FINISH", "downUrl": "http://..."},
            {"pageNum": 2, "status": "FINISH", "downUrl": "http://..."}
        ]
    }
}
```

### 3. 下载结果

直接 GET `downUrl` 获得识别后的 Markdown/Word/JSON 文件。

## 限制

- 单个 PDF 最大 100 页
- 不支持带密码/加密的 PDF
- 按页计费
- 含公式的课件建议 `exportFormat=markdown`

## 使用脚本

见项目根目录 `pdf_ocr.py`

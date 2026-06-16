# 讯飞 ChatDoc API（星火知识库）

> **官方文档**：https://www.xfyun.cn/doc/spark/ChatDoc-API.html
>
> 接口域名：`chatdoc.xfyun.cn`
>
> 完整知识库 RAG 方案：文档上传 → 自动分块 → 自动向量化 → 知识库管理 → WebSocket 流式问答

## 鉴权方式

与 Embedding API 不同，ChatDoc 使用 **MD5 + HmacSHA1**：

```
Step 1: auth = MD5(appId + timestamp)        # 32位小写十六进制
Step 2: signature = Base64(HmacSHA1(auth, apiSecret))
```

每个请求 HTTP Header：
- `appId` + `timestamp`（秒级，与服务器差≤5分钟）+ `signature`

```python
import hashlib, hmac, base64, time
def get_headers(app_id, api_secret):
    ts = str(int(time.time()))
    a = hashlib.md5((app_id + ts).encode()).hexdigest()
    s = hmac.new(api_secret.encode(), a.encode(), hashlib.sha1).digest()
    return {"appId":app_id, "timestamp":ts, "signature":base64.b64encode(s).decode()}
```

---

## 完整接口索引（26 个）

### 一、文档生命周期

| # | 接口 | 方法 | URL |
|---|------|------|-----|
| 1 | 上传 | POST | `/openapi/v1/file/upload` |
| 2 | 状态查询 | POST | `/openapi/v1/file/status` |
| 3 | 切分 | POST | `/openapi/v1/file/split` |
| 4 | 向量化 | POST | `/openapi/v1/file/embedding` |
| 5 | 详情 | POST | `/openapi/v1/file/info` |
| 6 | 列表 | POST | `/openapi/v1/file/list` |
| 7 | 删除 | POST | `/openapi/v1/file/del` |
| 8 | 分块内容 | POST | `/openapi/v1/file/chunks` |
| 9 | 总结 | POST | `/openapi/v1/file/summary/start` + `/query` |

### 二、知识库管理

| # | 接口 | 方法 | URL |
|---|------|------|-----|
| 10 | 创建 | POST | `/openapi/v1/repo/create` |
| 11 | 添加文件 | POST | `/openapi/v1/repo/file/add` |
| 12 | 移除文件 | POST | `/openapi/v1/repo/file/remove` |
| 13 | 文件列表 | POST | `/openapi/v1/repo/file/list` |
| 14 | 知识库列表 | POST | `/openapi/v1/repo/list` |
| 15 | 知识库详情 | POST | `/openapi/v1/repo/info` |
| 16 | 删除知识库 | POST | `/openapi/v1/repo/del` |

### 三、检索与问答

| # | 接口 | 方法 | URL |
|---|------|------|-----|
| 17 | WebSocket 问答 | WSS | `/openapi/chat` |
| 18 | 向量相似度检索 | POST | `/openapi/v1/vector/search` |

### 四、QA 萃取

| # | 接口 | 方法 | URL |
|---|------|------|-----|
| 19 | 提交萃取 | POST | `/openapi/v1/qa/extract` |
| 20 | 萃取状态 | GET | `/openapi/v1/qa/extract/status?fileId=xxx` |
| 21 | 萃取结果 | GET | `/openapi/v1/qa/extract/result?taskId=xxx` |
| 22 | 应用 QA | POST | `/openapi/v1/qa/apply` |
| 23 | 更新 QA | POST | `/openapi/v1/qa/apply/update` |
| 24 | 删除 QA | POST | `/openapi/v1/qa/apply/delete` |
| 25 | 查询 QA | POST | `/openapi/v1/qa/apply/page` |

---

## 核心接口详解

### 1. 文档上传 `file/upload`

```
POST multipart/form-data
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `file` | 与url二选一 | 文件流 |
| `fileType` | ✅ | 固定 `"wiki"` |
| `parseType` | ✅ | `AUTO`/`TEXT`/`OCR` |
| `stepByStep` | 否 | `false`=上传+分块+向量化一气呵成 |
| `extend.wikiSplitExtends.chunkSize` | 否 | 分段最大长度，默认 2000 |
| `extend.wikiSplitExtends.minChunkSize` | 否 | 分段最小长度，默认 256 |
| `extend.wikiSplitExtends.chunkSeparators` | 否 | 分隔符列表（Base64编码），默认 `["DQo="]` |

支持：pdf/doc/docx/md/txt，≤20MB，≤100万字符

响应：`data.fileId`、`data.quantity`（消耗页数）、`data.parseType`

### 2. 状态查询 `file/status`

状态流转：`uploaded → texted → ocring → spliting → splited → vectoring → vectored`（或 `failed`）

只有 `vectored` 可问答和萃取。

### 8. 分块内容 `file/chunks`

```
POST form-data: fileId=xxx
```
响应：`data[].dataType`(`wiki`)、`data[].dataIndex`、`data[].content`

### 18. 向量相似度检索 `vector/search`

```
POST JSON: {"fileIds":[], "topN":5, "content":"查询文本",
            "chatExtends":{"wikiFilterScore":0.82, "esFilterScore":10}}
```

直接检索文档内容，不经过大模型。返回 `data[].content`、`data[].score`、`data[].type`。

### 17. WebSocket 问答 `openapi/chat`

```
WSS: wss://chatdoc.xfyun.cn/openapi/chat?appId=xxx&timestamp=xxx&signature=xxx
```

> ⚠️ signature 不要 URL 编码

请求：
```json
{
  "repoId": "xxx",       // repoId/repoIds/fileIds 三选一
  "fileIds": ["xxx"],    // repo单次≤100文档，fileIds单次≤200
  "topN": 5,
  "messages": [{"role":"user","content":"问题"}],
  "chatExtends": {
    "wikiPromptTpl": "自定义Prompt，<wikiquestion>和<wikicontent>为占位符",
    "wikiFilterScore": 0.82,
    "temperature": 0.5,
    "retrievalFilterPolicy": "REGULAR",   // STRICT/REGULAR/LENIENT/OFF
    "qaMode": "MIX",                      // QA_FIRST/QA_SUMMARY/MIX/WIKI_ONLY
    "spark": true                         // 无匹配时大模型兜底
  }
}
```

流式响应 status：`0`=首包、`1`=中间、`2`=结束、`99`=引用（`fileRefer` 字段含文件ID→文段索引映射）

### 文档总结 `file/summary`

仅 `splited`/`vectoring`/`vectored` 状态可用。`start` 发起 → `query` 查询，状态 `done` 后获取 `data.summary`。

### QA 萃取流程

`extract` → 轮询 `extract/status`（`EXTRACTED`）→ `extract/result` → `apply` 写入知识库。支持分页查询（`qa/apply/page`）、更新（`update`）、删除（`delete`）。

---

## 关键约束

| 项目 | 限制 |
|------|------|
| 文档格式 | pdf/doc/docx/md/txt |
| 文档大小 | ≤20MB，≤100万字符 |
| QA 问答条件 | 文件状态必须 `vectored` |
| WebSocket signature | 不要 URL 编码 |
| 时间戳偏差 | ≤5 分钟 |
| stepByStep=true | 上传后仅分片，需手动调 embedding 接口 |
| 同一文件 | 最多存在于 10 个知识库中 |
| 添加文件到知识库 | 单次 ≤20 个 fileId |

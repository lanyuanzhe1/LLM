# ChatDoc RAG 实现方案

> 基于讯飞官方 ChatDoc API：https://www.xfyun.cn/doc/spark/ChatDoc-API.html
>
> 目标：知识库上传 → 自动向量化 → WebSocket 流式问答

## 一、已完成

- [x] Embedding API 连通验证
- [x] 知识库文档就绪（`knowledge/`，17 个文档）
- [x] API 鉴权代码就绪（MD5 + HmacSHA1）

## 二、ChatDoc 全流程（5 步）

```
① file/upload    POST  上传文档 → 拿到 fileId
② file/status    POST  轮询等待 → 直到 vectored
③ repo/create    POST  创建知识库 → 拿到 repoId
④ repo/file/add  POST  文件加入知识库
⑤ openapi/chat   WSS   流式问答 → 实时返回答案
```

## 三、执行脚本

`chatdoc_rag.py` — 一键执行全部 5 步，见同目录下脚本文件。

```bash
python chatdoc_rag.py
```

## 四、关键参数配置

### 文档上传

| 参数 | 值 | 说明 |
|------|-----|------|
| fileType | `wiki` | 固定值 |
| parseType | `AUTO` | 自动判断 TEXT/OCR |
| stepByStep | `false` | 一步到位 |

### WebSocket 问答

| 参数 | 值 | 说明 |
|------|-----|------|
| qaMode | `MIX` | QA对 + 原文混合检索 |
| retrievalFilterPolicy | `REGULAR` | 常规过滤策略 |
| temperature | `0.5` | 回答稳定性 |
| spark | `true` | 无匹配时大模型兜底 |

### 轮询向量化

- 间隔：3 秒
- 最大次数：100 次（约 5 分钟）
- 完成状态：`vectored`

## 五、与你现有向量库的关系

| | 本地 vector_store | ChatDoc API |
|---|---|---|
| 向量化方式 | 自己调 Embedding API | 平台自动完成 |
| 存储位置 | 本地 .npy 文件 | 讯飞服务器 |
| 检索方式 | sklearn 余弦相似度 | 平台内置检索引擎 |
| 生成方式 | 需要自己接 LLM | 内置 Spark / 可选其他模型 |
| 用途 | 验证 chunk 质量、本地测试 | 生产 RAG 服务 |

两者互补——本地库用于调试和验证，ChatDoc 用于正式服务。

## 六、下一步

ChatDoc RAG 跑通后：
1. 接入 DeepSeek V4 Flash（如需替代 Spark 生成）
2. 或直接使用讯飞 Agent 平台发布（支持 DeepSeek 预置模型）
3. 收集 Bad Case → 构造微调数据集 → MaaS 平台微调

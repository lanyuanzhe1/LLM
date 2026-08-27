# 粮食储藏垂直领域智能助手

本项目使用讯飞官方 ChatDoc 服务完成知识文档的解析、OCR、自动切分、向量化和检索。本地服务负责业务 API、证据映射、引用校验、MaaS 生成与星辰工作流接入，不再运行本地 OCR、切分、Embedding 或向量索引。

## 当前链路

```text
knowledge/ 中的 PDF、DOCX、PPT、TXT、Markdown
    -> ingest_chatdoc.py
    -> 讯飞 ChatDoc：AUTO 解析/OCR、自动切分、向量化
    -> ChatDoc 知识库
    -> app/rag/chatdoc_retriever.py
    -> FastAPI / 星辰工作流
```

`vector_store/` 和 `ocr_cache/` 可能仍保存以前生成的数据，但当前代码不会加载它们。旧的本地解析、OCR、切分、Embedding、索引构建和本地检索代码已经删除。

## 环境准备

```bash
conda activate LLM
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

项目使用 `.env` 保存讯飞配置，至少需要：

```dotenv
XF_APP_ID=...
XF_EMBEDDING_API_SECRET=...
XF_CHATDOC_REPO_ID=...
XF_MAAS_API_KEY=...
XF_MAAS_API_SECRET=...
XF_MAAS_RESOURCE_ID=...
XF_MAAS_SERVICE_ID=...
XF_WORKFLOW_API_KEY=...
XF_WORKFLOW_API_SECRET=...
XF_WORKFLOW_FLOW_ID=...
TOOLS_SERVICE_TOKEN=...
```

目前 ChatDoc 与原讯飞应用共用 APISecret，因此仍从 `XF_EMBEDDING_API_SECRET` 读取该值；代码不会调用旧 Embedding API。

## 上传知识库

```bash
python ingest_chatdoc.py
```

上传程序会：

1. 扫描 `knowledge/` 下支持的文档；
2. 跳过超过 20 MiB 的文件，等待人工拆分后再次上传；
3. 创建 ChatDoc 知识库并上传文件；
4. 等待讯飞完成解析、切分和向量化；
5. 将文件加入知识库；
6. 成功后写入 `artifacts/chatdoc/base.json`，并更新 `.env` 中的 `XF_CHATDOC_REPO_ID`。

如果讯飞返回额度不足，程序不会发布新清单，也不会切换当前知识库配置。

## 启动服务

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

检查状态：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

`/ready` 只有在 ChatDoc 清单与 `XF_CHATDOC_REPO_ID` 一致且云端配置有效时才返回就绪。

## 测试

```bash
python -m pytest -m "not online" -q
```

需要真实讯飞账号和网络的测试必须显式启用：

```bash
RUN_ONLINE=1 python -m pytest -m online -q
```

## 主要目录

```text
app/
  clients/iflytek_chatdoc.py   # ChatDoc API 客户端
  ingest/chatdoc_upload.py     # 文件扫描、上传和知识库发布
  rag/chatdoc_retriever.py     # ChatDoc 检索结果与证据映射
  api/                         # FastAPI 公共接口
  services/                    # 生成、引用校验与工作流服务
artifacts/chatdoc/             # 已发布的 ChatDoc 本地清单
knowledge/                     # 待上传的知识文件
ingest_chatdoc.py              # 官方 ChatDoc 入库入口
tests/                         # 自动化测试
```

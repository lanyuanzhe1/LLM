# 粮食储藏垂类大模型 RAG 项目

本项目用于构建河工大粮食储藏领域知识型垂类大模型。当前架构是：

```text
知识文件 knowledge/
  -> ingest_knowledge.py 入库
  -> vector_store/ 本地向量库
  -> FastAPI 服务 app/
  -> 讯飞星辰工作流 + 讯飞 Embedding + 讯飞 MaaS
  -> 面向用户的知识问答 / 案例分析
```

团队成员从 GitHub clone 后，建议先阅读本 README，再按需进入 `docs/`、`workflow/` 和 `tests/`。

## 快速开始

### 1. 创建并激活环境

项目使用 Python 3.11。当前开发环境名为 `LLM`：

```bash
conda activate LLM
python -m pip install -r requirements-dev.txt
```

不要使用裸 `pip`，请始终使用当前环境中的 `python -m pip`。

### 2. 准备本地配置

本地运行需要 `.env` 中提供讯飞相关配置。`.env` 只保存在本机，不提交到 Git。

关键配置包括：

- `XF_APP_ID`
- `XF_EMBEDDING_API_KEY`
- `XF_EMBEDDING_API_SECRET`
- `XF_MAAS_API_KEY`
- `XF_MAAS_API_SECRET`
- `XF_WORKFLOW_API_KEY`
- `XF_WORKFLOW_API_SECRET`
- `XF_WORKFLOW_FLOW_ID`
- `TOOLS_SERVICE_TOKEN`

更多云端和工作流配置说明见 [docs/星辰工作流联调指南.md](docs/星辰工作流联调指南.md)。

### 3. 构建基础知识向量库

```bash
python ingest_knowledge.py --scope base
```

该命令会扫描 `knowledge/` 下的内置知识文档，生成或更新 `vector_store/base/`。

### 4. 启动本地服务

服务启动时读取 `VECTOR_STORE_DIR` 指向的向量库目录。只验证基础知识库时，可让它指向 `vector_store/base`：

```bash
VECTOR_STORE_DIR=vector_store/base python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

启动后可检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

注意：当前服务状态、request context 和向量库缓存都在进程内，启动时使用 `--workers 1`。

## RAG 入库流程

### 基础知识库

基础知识库是产品自带知识，来源位于 `knowledge/`：

```bash
python ingest_knowledge.py --scope base
```

输出位置：

```text
vector_store/base/
  vectors.npy
  chunks_metadata.json
  manifest.json
  ingest_report.json
```

### 项目知识库

项目知识库用于隔离用户或项目新增资料。文件进入：

```text
knowledge/projects/<project_id>/
```

导入单个文件并入库：

```bash
python ingest_knowledge.py --project-id demo --source /path/to/file.pdf
```

重建某个项目：

```bash
python ingest_knowledge.py --project-id demo
```

批量重建全部项目：

```bash
python ingest_knowledge.py --scope all-projects
```

项目向量库输出位置：

```text
vector_store/projects/<project_id>/
  vectors.npy
  chunks_metadata.json
  manifest.json
  ingest_report.json
```

入库管线会基于文件 SHA-256、chunk 配置和 parser version 做增量缓存，未变化文件会复用已有 embedding，避免重复消耗接口额度。

## 项目目录结构

```text
.
├── app/                    # FastAPI 应用和核心业务代码
├── docs/                   # 设计、计划、联调指南和历史研究文档
├── knowledge/              # 原始知识文件；产品内置知识库来源
├── training_data/          # 指令微调数据集
├── vector_store/           # 本地向量库产物；由入库脚本生成
├── workflow/               # 星辰工作流离线契约和配置说明
├── tests/                  # 单元、契约、集成和在线测试
├── ingest_knowledge.py     # 当前主入库脚本
├── build_vector_store.py   # 早期全量向量化脚本，保留作兼容和参考
├── search_kb.py            # 本地向量库交互式检索脚本
├── test_embedding_api.py   # 讯飞 Embedding 连通性测试
├── test_finetuned_model.py # 微调模型调用测试脚本
├── gen_training_data.py    # 生成/整理 SFT 训练数据
├── chatdoc_rag.py          # 早期 ChatDoc RAG 方案脚本
├── requirements.txt        # 运行依赖
├── requirements-dev.txt    # 开发和测试依赖
└── pytest.ini              # pytest 配置
```

## `app/` 目录说明

```text
app/
├── api/          # 面向用户的公开 API：聊天、案例分析、健康检查、证据源查询
├── clients/      # 讯飞 Embedding、MaaS、星辰工作流客户端
├── core/         # 配置、错误模型、请求 ID、请求上下文缓存
├── domain/       # 领域规则；当前包含粮食储藏案例分析规则
├── ingest/       # RAG 入库模块：读取、扫描、manifest、索引发布
├── rag/          # 向量库加载、证据构造、检索器和项目隔离检索
├── schemas/      # Pydantic 请求/响应模型
├── services/     # 生成服务、引用校验、工作流网关
├── tools/        # 给星辰工作流调用的受保护工具 API
├── dependencies.py
└── main.py       # FastAPI app 创建和服务容器装配入口
```

关键模块：

- `app/ingest/reader.py`：根据文件后缀路由到对应文本提取器。
- `app/ingest/scanner.py`：扫描基础库或项目库，校验 `project_id`，跳过不安全路径。
- `app/ingest/manifest.py`：记录增量入库状态，用于判断文件是否可复用 embedding。
- `app/ingest/builder.py`：构建 sklearn 向量索引，保存产物并原子发布。
- `app/rag/vector_store.py`：加载 `vectors.npy` 和 `chunks_metadata.json`，执行向量检索。
- `app/rag/registry.py`：按 base/project 路径加载并缓存向量库。
- `app/rag/project_retriever.py`：合并基础库和指定项目库的检索结果。
- `app/rag/evidence.py`：把 chunk metadata 转成可引用证据。
- `app/services/workflow_gateway.py`：连接公开 `/v1/*` API 与星辰工作流流式输出。
- `app/services/citation_validation.py`：校验回答引用是否来自已检索证据。

## `knowledge/` 与 `vector_store/`

`knowledge/` 保存原始资料，推荐按来源分类：

```text
knowledge/
├── 河南工业大学论文/
├── 政策文件类/
├── 其他论文/
└── projects/
    └── <project_id>/
```

`vector_store/` 是本地构建产物，不应手工编辑。它由 `ingest_knowledge.py` 生成：

```text
vector_store/
├── base/
└── projects/
    └── <project_id>/
```

每个向量库目录中的文件：

- `vectors.npy`：归一化后的向量矩阵。
- `chunks_metadata.json`：每个 chunk 的文本、来源、位置和作用域信息。
- `manifest.json`：增量构建状态。
- `ingest_report.json`：本次入库报告。

## 主要脚本说明

| 脚本                            | 作用                                                                       |
| ------------------------------- | -------------------------------------------------------------------------- |
| `ingest_knowledge.py`         | 当前主入库入口；支持基础库、单项目、导入文件、全部项目重建。               |
| `build_vector_store.py`       | 早期全量 RAG 构建脚本；包含清洗、分块、Embedding、sklearn 索引和发布逻辑。 |
| `search_kb.py`                | 从本地向量库加载索引，做命令行交互式检索验证。                             |
| `test_embedding_api.py`       | 最小化测试讯飞 Embedding API 是否可用。                                    |
| `test_finetuned_model.py`     | 测试讯飞 MaaS 微调模型调用。                                               |
| `gen_training_data.py`        | 根据领域资料生成或整理指令微调数据。                                       |
| `chatdoc_rag.py`              | 早期 ChatDoc 接入方案脚本，当前主线以本地向量库为准。                      |
| `Embedding_demo/Embedding.py` | 讯飞 Embedding 示例代码。                                                  |

## API 与工作流

本地 FastAPI 提供两类入口：

- 公开入口：`/v1/chat`、`/v1/cases/analyze`、`/v1/sources/{evidence_id}`。
- 星辰工具入口：`/tools/v1/retrieve`、`/tools/v1/generate`、`/tools/v1/cases/evaluate`、`/tools/v1/citations/validate`。

`workflow/tool_contracts.json` 是星辰工具节点的离线契约，包含服务端 Pydantic JSON Schema。

`workflow/README.md` 说明星辰平台需要创建的开始节点参数、工具映射、引用验证和公网暴露边界。

## 测试

安装开发依赖后运行离线测试：

```bash
python -m pytest -m "not online" -W error -q
```

在线测试需要真实讯飞配置和网络：

```bash
RUN_ONLINE=1 python -m pytest tests/online/ -v
```

`pytest.ini` 中定义了 `online` marker，默认离线测试不会访问云端服务。

## 文档索引

重要文档：

- [docs/星辰工作流联调指南.md](docs/星辰工作流联调指南.md)：本地服务、星辰工作流、公网工具调用联调。
- [workflow/README.md](workflow/README.md)：星辰工具节点和参数映射。
- [docs/superpowers/specs/2026-07-19-hybrid-technical-core-design.md](docs/superpowers/specs/2026-07-19-hybrid-technical-core-design.md)：混合技术核心设计。
- [docs/superpowers/specs/2026-07-20-rag-project-ingestion-design.md](docs/superpowers/specs/2026-07-20-rag-project-ingestion-design.md)：项目知识库入库设计。
- [docs/superpowers/plans/2026-07-20-rag-project-ingestion.md](docs/superpowers/plans/2026-07-20-rag-project-ingestion.md)：项目知识库入库实施计划。
- [docs/Temp/2026-07-20-rag-ingestion-complete.md](docs/Temp/2026-07-20-rag-ingestion-complete.md)：RAG 入库完成交接。

历史研究和方案文档位于 `docs/` 根目录，可用于理解项目从 ChatDoc、Embedding 到当前混合架构的演进。

## 开发注意事项

- 不要提交 `.env`、API 密钥、鉴权 header、原始云端响应或本机隐私路径。
- `vector_store/` 是构建产物，体积可能较大；除非团队明确要求，不建议纳入 Git。
- 修改公开 API 或星辰工具 schema 后，需要同步更新 `workflow/tool_contracts.json` 和 `workflow/README.md`。
- 新增 RAG 入库行为时(就是说更改RAG入库这个代码功能时，先在test/下写测试)，优先补充 `tests/unit/test_ingest_cli.py`、`tests/unit/test_scanner.py`、`tests/unit/test_manifest.py`、`tests/unit/test_registry.py` 和 `tests/unit/test_project_retriever.py`。
- 运行真实云端测试前确认 `.env` 已配置，且知道会消耗讯飞接口额度。

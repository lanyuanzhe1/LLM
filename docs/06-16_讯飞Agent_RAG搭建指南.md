# 讯飞 Agent 平台 RAG 搭建操作指南

> 每一步都在浏览器网页上完成，不需要写代码。
>
> 平台地址：https://agent.xfyun.cn

---

## 前置准备

打开浏览器前，确认你有：
- [x] 讯飞开放平台账号（已注册）
- [x] 知识库文档（`knowledge/` 目录下的 17 个 PDF + DOCX）
- [x] DeepSeek API Key（去 platform.deepseek.com 注册充值，最低 $2）

---

## 第一步：登录 Agent 平台

```
浏览器打开：https://agent.xfyun.cn
右上角「登录」→ 微信扫码 / 手机号登录
```

登录后进入**工作台**，能看到：
- 我的智能体
- 知识库管理
- 工具市场
- 模型服务

---

## 第二步：上传知识库文档

这是最核心的一步——把你的 17 个文档传上去。

### 2.1 创建知识库

```
左侧菜单 →「知识库管理」→ 点击「新建知识库」
```

弹出表单，填写：
```
名称：粮食储藏知识库
描述：包含储粮害虫防治、低温储粮技术、粮食安全保障法、
       CO2监测、智能粮库管理等领域的学术论文和政策文件
```

点击「确定」，知识库创建完成。

### 2.2 上传文档

```
进入刚创建的知识库 → 点击「上传文档」
```

把你 `knowledge/` 目录下的文件全部拖进去：
```
✅ 河南工业大学论文/（6 个 PDF）
✅ 其他论文/（9 个 PDF）
✅ 政策文件类/（1 DOCX + 2 PDF）
```

> ⚠️ 单个文件不超过 20MB，单个知识库不超过 100 万字符。你的 17 个文档约 47 万字符，没问题。

### 2.3 设置分段策略

上传完成后，平台会让你选择分段方式：

```
推荐选「自定义分段」：
  - 分段长度：600-800 字符
  - 重叠长度：100-150 字符
```

或者直接选「默认分段」，平台会自动处理。

### 2.4 等待处理 + 命中测试

```
点击「保存并处理」→ 等待向量化完成（几分钟）
完成后 → 点击「命中测试」
输入几个测试问题，检查检索效果
```

测试问题：
```
- "储粮害虫怎么防治" → 应该命中 GB/T 29890 国标
- "低温储粮技术" → 应该命中 胡坤 论文
- "CO2监测储粮" → 应该命中 张燕燕 论文
```

---

## 第三步：创建 RAG 智能体

### 3.1 新建工作流智能体

```
左侧菜单 →「我的智能体」→「创建智能体」
选择「工作流智能体」（低代码拖拽方式）
填写：
  - 名称：粮食储藏知识助手
  - 分类：农业/科研
  - 描述：专业的粮食储藏技术知识问答助手
点击「创建」→ 进入可视化画布
```

画布上默认有两个节点：**开始** 和 **结束**。

### 3.2 搭建工作流

目标架构：

```
开始节点
   │
   ▼
知识库节点（检索相关知识）
   │
   ▼
大模型节点（基于知识生成答案）
   │
   ▼
结束节点（返回回答）
```

#### 步骤 A：拖入知识库节点

```
左侧组件库 →「知识库」→ 拖到画布上
点击知识库节点 → 右侧配置面板：
  - 选择知识库：粮食储藏知识库
  - 检索模式：Agentic RAG（复杂问题自动拆解子问题）
  - Top K：5
  - Score 阈值：0.6
  - 输入 query：引用「开始节点」的 AGENT_USER_INPUT
```

#### 步骤 B：拖入大模型节点 → 选择 DeepSeek

```
左侧组件库 →「大模型」→ 拖到画布上
点击大模型节点 → 右侧配置面板：
  - 模型选择：点击「自定义模型」或「第三方模型」
  - 搜索/选择：DeepSeek-V3 或 DeepSeek-R1（平台已预置）
  - 或者点击「新建模型」填入你自己的 DeepSeek API
```

**如果用平台预置的 DeepSeek（推荐）**：

```
直接在下拉列表选 DeepSeek-V3，无需额外配置。
平台已内置 DeepSeek 模型，开箱即用。
```

**如果你想用自己的 DeepSeek V4 Flash API Key**：

```
点击「新建模型」→ 填写：
  - 模型名称：DeepSeek V4 Flash
  - API地址：https://api.deepseek.com/v1
  - API密钥：你的 DeepSeek API Key
  - 模型标识：deepseek-v4-flash
```

> 平台支持所有 OpenAI-Like API 协议的外部模型，包括 DeepSeek、Qwen、GLM、Kimi 等。

配置完成后：
```
  - 输入 question：引用「开始」的 AGENT_USER_INPUT
  - 输入 knowledge：引用「知识库节点」的 result.content
  - 提示词（Prompt）见下方
```

**大模型节点 Prompt 模板：**

```
你是一位粮食储藏领域的资深专家。请**仅基于**以下知识库内容回答用户问题。

## 回答规则
1. 如果知识库中有相关信息，必须**引用具体来源**
2. 如果知识库中没有相关信息，明确说"当前知识库缺少这方面资料"
3. 回答要专业、准确、简洁
4. 涉及国家标准或法律法规时，注明具体条款编号

## 知识库内容
{{knowledge}}

## 用户问题
{{question}}
```

> `★ Insight ─────────────────────────────────────`
> **为什么知识库节点在 LLM 节点之前？** RAG 的核心流程是"先检索，再生成"。知识库节点从向量库中找到相关的 chunk，把它们的文本拼到 Prompt 里，LLM 再基于这些文本生成答案。如果顺序反过来，LLM 就只能凭自己记忆瞎编了（幻觉）。
> `─────────────────────────────────────────────────`

#### 步骤 C：连线 + 配置输出

```
知识库节点 → 大模型节点 → 结束节点

点击结束节点 → 输出变量设为「大模型节点」的 output
```

### 3.3 调试

```
点击右上角「调试」按钮
在弹窗中输入测试问题：

  "储粮害虫有哪些防治方法？"
  "低温储粮技术的主要原理是什么？"
  "粮食安全保障法对政府储备有什么要求？"

观察每个节点的输入/输出，确认：
  ✅ 知识库节点检索到了相关文档
  ✅ 大模型节点生成了带引用的回答
```

---

## 第四步：关于 DeepSeek V4 Flash

### 4.1 平台现状

讯飞 Agent 平台的大模型节点**默认只支持讯飞自家的 Spark 系列模型**（Spark Lite / Max / Ultra / 4.0 等）。暂时不支持在平台的"大模型节点"里直接切换为 DeepSeek。

### 4.2 两种使用 DeepSeek 的方式

**方式一：代码节点调用 DeepSeek API（在平台内）**

```
左侧组件库 →「代码」→ 拖到画布上
替换「大模型节点」→ 代码节点中写 Python 调 DeepSeek API
```

具体做法——在代码节点里填入：

```python
import requests, json

def main(knowledge, question):
    """在讯飞Agent平台的代码节点中调用 DeepSeek V4 Flash"""
    resp = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": "Bearer 你的DeepSeek_API_Key",
            "Content-Type": "application/json"
        },
        json={
            "model": "deepseek-v4-flash",
            "messages": [{
                "role": "user",
                "content": f"你是一个粮食储藏专家。基于以下知识回答：\n\n知识库：{knowledge}\n\n问题：{question}\n\n如果知识库没有相关信息请明确说明。"
            }],
            "temperature": 1.0,
            "max_tokens": 2048
        },
        timeout=120
    )
    result = resp.json()
    return {"output": result["choices"][0]["message"]["content"]}
```

> 输入变量 `knowledge` 引用知识库节点输出，`question` 引用开始节点输入。

**方式二：本地代码搭建 RAG（不依赖平台）**

这是最灵活的方式——直接写 Python 脚本：
- 检索用我们已建好的 `vector_store/`（讯飞 Embedding API）
- 生成用 DeepSeek V4 Flash API
- 完全自己控制整个 Pipeline

---

## 第五步：发布上线

调试通过后：

```
点击右上角「发布」
  → 填写基本信息
  → 选择发布渠道：
      ☑ API（推荐：后面可以接任何前端）
      ☑ H5 页面（生成一个链接，直接分享）
      ☑ 微信公众号（需配置开发者ID）
      ☑ 星火 APP
  → 提交审核 → 审核通过 → 上线
```

> 每个智能体免费提供 **1000 万 token** 额度（讯飞 Spark 模型）。

---

## 快速参考：关键平台 URL

| 功能 | 地址 |
|------|------|
| Agent 平台首页 | https://agent.xfyun.cn |
| 知识库管理 | https://agent.xfyun.cn/knowledge |
| 创建智能体 | https://agent.xfyun.cn/agent/create |
| 官方文档 | https://xinghuo.xfyun.cn/botdoc |
| 客服助手案例 | https://doc.aidaxue.com/llm-agent/case1.html |
| 新手教程 | https://doc.aidaxue.com/llm-agent/guide.html |
| DeepSeek API 平台 | https://platform.deepseek.com |
| DeepSeek API 文档 | https://api-docs.deepseek.com |

---

## 现在你该做的事（按顺序）

```
☐ 1. 打开 https://agent.xfyun.cn 登录
☐ 2. 创建知识库 → 上传 17 个文档 → 等待向量化完成
☐ 3. 命中测试 → 确认检索效果
☐ 4. 创建工作流智能体 → 拖入知识库节点 + 大模型节点
☐ 5. 调试 → 测试 5-10 个真实问题
☐ 6. 如需用 DeepSeek → 用"代码节点"替代"大模型节点"
☐ 7. 发布 → 分享链接 / API 调用
```

# 讯飞 MaaS 平台 — 数据集格式规范

> 官方文档：https://www.xfyun.cn/doc/spark/数据集格式说明.html
>
> w3cschool 镜像：https://www.w3cschool.cn/xfyunmaasdoc/xfyun-maas-dataset-format-description.html
>
> 平台入口：https://training.xfyun.cn

## 一、两种微调数据格式

### Alpaca 格式（单轮指令任务 — 推荐用于垂类微调）

```json
[
  {
    "instruction": "人类指令（必填）",
    "input": "人类输入（选填）",
    "output": "模型回答（必填）",
    "system": "系统提示词（选填）",
    "history": [
      ["第一轮指令（选填）", "第一轮回答（选填）"]
    ]
  }
]
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `instruction` | ✅ | 任务指令，最终 = `instruction` + `input` 拼接 |
| `input` | 选填 | 具体输入，开放式任务可为 `""` |
| `output` | ✅ | 期望的正确回答 |
| `system` | 选填 | 系统角色提示词 |
| `history` | 选填 | 多轮历史，结构 `[[Q1, A1], [Q2, A2]]` |

**完整的粮食储藏领域实例**：
```json
{
  "instruction": "你是一位粮食储藏技术专家。请基于专业知识回答以下问题，涉及国家标准时注明条款编号。",
  "input": "储粮害虫的物理防治方法有哪些？",
  "output": "储粮害虫的物理防治方法主要包括：\n\n1. **高温杀虫**：将粮温升至50℃以上保持一定时间...\n2. **低温控制**：按GB/T 29890-2013规定，将粮温控制在15℃以下...\n3. **过筛除虫**：利用害虫与粮粒的粒度差异进行筛分...\n4. **压盖防治**：用干燥无虫材料覆盖粮面，防止蛾类害虫羽化...",
  "system": "你是一位资深的粮食储藏技术专家，在储粮害虫防治领域有20年经验。",
  "history": []
}
```

### ShareGPT 格式（多轮对话 + 工具调用）

```json
[
  {
    "conversations": [
      {"from": "human", "value": "用户问题"},
      {"from": "gpt", "value": "模型回答"},
      {"from": "human", "value": "追问"},
      {"from": "gpt", "value": "进一步回答"}
    ],
    "system": "系统提示词（选填）",
    "tools": "工具描述 JSON（选填）"
  }
]
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `conversations` | ✅ | 消息列表 |
| `conversations[].from` | ✅ | `human`/`gpt`/`function_call`/`observation` |
| `conversations[].value` | ✅ | 消息内容 |
| `system` | 选填 | 系统提示词 |
| `tools` | 选填 | 可用工具 JSON |

> ⚠️ `human`/`observation` 奇数位置，`gpt`/`function_call` 偶数位置。

---

## 二、推理集（评测集）格式 — JSONL

```jsonl
{"input":"买房银行贷款贷多少年","target":"个人住房贷款最长为30年；商业贷款最长为10年"}
{"input":"储粮害虫的化学防治方法","target":"主要使用磷化铝熏蒸..."}
```

| 项目 | 要求 |
|------|------|
| 结构 | `{"input":"问题","target":"答案"}` |
| 字符限制 | `input` + `target` ≤ 4000 字符 |
| 编码 | UTF-8 |
| 文件类型 | `.jsonl` |
| 训练集最低量 | Spark Pro ≥ 1500条 / Spark Lite ≥ 100条 |
| 文件大小 | < 500M |

---

## 三、数据量要求

| 模型 | 最低训练量 | 推荐训练量 |
|------|-----------|-----------|
| Spark Pro / Qwen-7B+ | ≥ 1500 条 | 2000-5000 条 |
| Spark Lite | ≥ 100 条 | 500-2000 条 |
| 效果阈值 | < 500 条效果不明显 | — |

---

## 四、平台内置数据工具

| 工具 | 功能 |
|------|------|
| **问答对抽取** | 上传 TXT/网页链接 → 自动切分 QA 对（正确率 90%） |
| **数据增强** | 1 条种子 → 泛化 1~5 倍 |
| **Prompt 模板** | 50+ 预设模板快速构造数据 |

## 五、核心规则

1. `instruction` + `input` 自动拼接为完整用户指令
2. `history` 中的回答**也会参与模型训练**
3. 所有文件必须 UTF-8 编码
4. JSON 字段名必须准确（`instruction` 不是 `prompt`）
5. 单条 JSON 数据中 `input` 为空字符串 `""` 而非 `null`

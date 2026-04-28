# 🧠 LifeBook Memory Agent

**LifeBook Memory Agent** 是一个专为增强大型语言模型（LLM）长期记忆能力而设计的智能代理系统。它作为 OpenAI 兼容的反向代理服务器运行，通过独特的**双模型架构**、**分层存储机制**、**自动会话生命周期管理**以及**消息编排器**，为 AI 赋予了类似人类的记忆与反思能力。

[![架构](https://img.shields.io/badge/Architecture-Dual--Model%20Agent-brightgreen)](ARCHITECTURE.md)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 🎯 这个项目能做什么？

想象一下：你和 AI 聊天时，它不仅记得你昨天说过的话，还能回忆起你三个月前提到的那个项目进展。这就是 LifeBook Memory Agent 要解决的问题。

**传统 LLM 的痛点**：
- 对话结束，记忆清零
- 上下文窗口有限
- 无法建立长期人物/项目档案

**LifeBook 的解决方案**：
- 📝 自动将对话转化为结构化日记
- 🔍 智能检索相关历史记忆
- 📊 分层压缩（日→周→月→季度总结）
- 🗂️ 人物/概念知识图谱
- 🎭 消息编排器（伪造对话历史，塑造 AI 行为模式）

---

## ✨ 核心特性

### 🤖 双模型代理架构
*   **记忆代理 (Memory Agent)**：通常使用具备强推理能力的小模型（如 `deepseek-reasoner`），在主模型响应前，通过多轮思维链（CoT）主动检索、筛选并整合相关背景信息。
*   **主模型 (Main Model)**：您选择的强大模型（如 Claude, GPT, Gemini），它不再直接面对海量碎片化历史，而是接收到一个由 Agent 深度定制的"记忆增强上下文"。

### 📚 模拟人类的分层记忆系统 (Layered Memory)
系统根据时间维度和重要程度，自动将记忆分为四个层级，以保持上下文的高效与精准：
*   **短期记忆 (Short-term)**：最近 7 天的完整日记或对话摘要，保留所有细节。
*   **中短期记忆 (Mid-short)**：本月内超过 7 天的周总结（Weekly Summaries），提炼近期要点。
*   **中期记忆 (Mid-term)**：上个月的月度总结（Monthly Summaries），回顾过去一个月的成长与变化。
*   **长期记忆 (Long-term)**：回溯至半年前的季度总结（Quarterly Summaries），形成宏观认知。

### 🔍 强大的混合检索能力
*   **关键词倒排索引**：基于 `jieba` 分词，对日记、总结和节点进行全文索引，精准匹配实体词。
*   **RAG 语义搜索**：集成向量嵌入 API（如 SiliconFlow），支持模糊语义检索，即使没有相同关键词也能找到相关记忆。
*   **结构化知识图谱 (Nodes)**：支持创建**人物、地点、事物、概念**节点，通过 `[[双链]]` 建立实体间的关联，构建个人知识网络。

### ✍️ 智能会话管理
*   **对话后自动总结 (Post-Conversation)**：会话结束后，系统异步调用模型判断当前对话的记录价值。有价值的对话将生成 100-300 字的精炼摘要。
*   **睡眠间隔分割机制**：智能检测对话间的"静默时间"。若超过设定的"睡眠间隔"（如 6 小时），系统会自动将此前的摘要归档为一篇独立的日记，符合人类的清醒/睡眠周期。
*   **XML 工具拦截器**：专为流式输出设计，能够隐藏复杂的工具调用源码（如 `<<<tool_call>>>`），取而代之的是优雅的 UI 提示，提升用户体验。

### 🎭 消息编排器 (Message Orchestrator) - 新功能！

消息编排器允许你完全控制发送给模型的消息结构，通过**伪造对话历史**来塑造 AI 的行为模式。

**核心原理**：
> AI 模型的行为很大程度上受到"对话历史"的影响。如果模型看到自己"之前已经"以某种方式回复过，它会倾向于保持一致性。

**功能特性**：
- 🎨 **可视化拖拽排序**：在 Web 管理面板中直观编辑消息序列
- 👤 **伪造 User/Assistant 消息**：注入预设对话，让 AI "认为"它已经接受了某个角色设定
- 📦 **预设管理**：保存多套配置，按需切换
- 🔗 **模型绑定**：不同模型自动使用不同的编排规则（支持通配符）
- ⏪ **历史回滚**：操作失误可快速恢复
- 📤 **导入/导出**：分享或备份你的编排配置

**典型应用场景**：
- 角色扮演：让 AI 扮演特定角色并保持一致性
- 行为塑造：通过伪造"已确认"的对话来跳过重复确认
- 上下文优化：精确控制记忆注入的位置和格式

---

## 🏛️ 系统架构流程

```mermaid
graph TD
    A[用户请求 model-memory / model-record / model-log] --> B[Proxy Server (8003)];
    B --> C{Memory Router};
    C -- 1. 激活检索 --> D[Memory Agent];
    D -- 多轮工具调用 --> E[LifeBook 存储库];
    E -- 返回 Markdown 记录 --> D;
    D -- 整合记忆简报 --> F[Context Builder];
    F -- 注入分层记忆 + 简报 --> G[Message Orchestrator];
    G -- 编排消息结构 --> H[主模型 Claude/GPT/etc.];
    H -- 生成最终回复 --> I[用户];
    
    I -- 异步触发 --> J[Post-Conv Manager];
    J -- 判断价值 & 总结 --> K[Pending Store (暂存区)];
    K -- 到达睡眠间隔 --> L[Auto Consolidate];
    L -- 合并摘要为日记 --> E;
```

---

## 🛠️ 记忆工具手册 (Memory Tools)

系统为 Agent 提供了 **20+** 个专业记忆工具，支持对记忆库的增删改查：

### 🔍 搜索工具
| 工具名 | 说明 | 关键参数 |
| :--- | :--- | :--- |
| `search_memories` | 基于关键词和元数据的综合搜索 | `query`, `tags`, `date_start` |
| `rag_search` | 基于向量相似度的语义搜索 | `query`, `top_k`, `filter_type` |

### 📖 只读工具
| 工具名 | 说明 | 关键参数 |
| :--- | :--- | :--- |
| `read_diary` | 读取指定日期的日记全文 | `date (YYYY-MM-DD)` |
| `read_summary` | 读取周/月/季/年总结 | `type`, `identifier` |
| `get_node` | 获取特定人物/概念节点的详细信息 | `name` |
| `list_recent` | 列出最近 N 天的日记列表及预览 | `days` |
| `get_current_context` | 获取当前时间上下文（日期、周数、本月等） | - |
| `list_all_tags` | 列出所有标签及使用次数 | `limit` |
| `list_all_people` | 列出所有人物及出现次数 | `limit` |
| `list_nodes` | 列出所有节点（可按类型过滤） | `type` |
| `get_memory_overview` | 获取记忆系统概览（一次调用了解全貌） | - |
| `read_graph` | 读取整个知识图谱（节点+关系） | - |
| `read_all_nodes` | 一键读取所有节点的完整内容 | `type`, `max_content_length` |
| `add_to_pending` | 手动添加摘要到暂存区 | `topic`, `summary` |

### ✍️ 写入工具（需启用）
| 工具名 | 说明 | 核心逻辑 |
| :--- | :--- | :--- |
| `add_to_diary` | 向指定日记追加新内容 | 写入模式 |
| `create_node` | 创建新的人物/地点/概念节点 | 写入模式 |
| `update_node` | 更新已有节点内容 | append/replace 模式 |
| `create_summary` | 创建周/月/季/年总结 | 写入模式 |
| `add_observations` | 向节点添加离散的事实观察 | 写入模式 |
| `create_relations` | 在两个节点之间建立双向链接关系 | 写入模式 |

### ✂️ 精准编辑工具（类似 apply_diff）
| 工具名 | 说明 | 核心逻辑 |
| :--- | :--- | :--- |
| `edit_diary` | 在日记中搜索并替换特定段落 | 仅替换第一个匹配 |
| `edit_node` | 对实体节点执行局部更新 | 支持删除特定内容 |
| `edit_summary` | 对已生成的总结执行局部修正 | 适用于微小偏差修正 |
| `rewrite_diary` | 完全重写日记正文（保留 frontmatter） | 替换模式 |

### 🗑️ 删除工具
| 工具名 | 说明 | 核心逻辑 |
| :--- | :--- | :--- |
| `delete_node` | 永久删除指定的节点文件 | 需 `confirm=true` |
| `delete_summary` | 永久删除指定的总结文件 | 需 `confirm=true` |

---

## ⚙️ 配置详解 (`config.jsonc`)

配置文件支持标准的 JSONC 格式，核心配置段如下：

### 1. 代理设置
*   `host` / `port`: 服务器监听地址与端口（默认 `8003`）。
*   `api_key`: 用于转发请求的主 API Key。
*   `model_routes`: 定义虚拟模型 ID 到真实 API 端点的映射。

### 2. 记忆代理 (`memory_agent`)
*   `model`: 建议使用 `deepseek-reasoner`。
*   `max_iterations`: Agent 检索记忆的最大迭代轮数（建议 `20-30`）。
*   `system_prompt`: 约束 Agent 如何判断是否需要检索以及如何输出简报。

### 3. 分层记忆策略 (`context.layered_memory`)
*   `short_term.days`: 保持完整日记细节的天数（默认 `7`）。
*   `weekly/monthly/quarterly`: 是否开启各级总结的自动注入。
*   `max_chars_per_entry`: 每条记忆注入的最大字符数，防止上下文溢出。

### 4. 自动总结 (`post_conversation`)
*   `auto_summarize`: 是否开启对话后自动生成摘要。
*   `min_messages`: 触发总结所需的最小用户消息数（防止记录无意义的打招呼）。
*   `summarize_prompt`: 引导模型如何提取关键信息（人名、时间、重要决定）。

### 5. 消息编排器 (`message_orchestrator`) - 新增！
*   `enabled`: 是否启用消息编排器（默认 `false`）。
*   `default_preset`: 默认使用的预设名称。
*   `model_bindings`: 模型名称匹配规则 → 预设名称（支持通配符）。

### 6. Pending 暂存 (`pending`)
*   `sleep_gap_hours`: 睡眠间隔小时数（默认 `6.0`），超过此时间无对话视为"睡眠"。
*   `consolidate_prompt`: 汇总摘要为日记的提示词模板。
*   `merge_prompt`: 追加到现有日记时的合并提示词模板。

---

## 🚀 快速上手

### 1. 环境要求
- Python 3.9+
- Windows / Linux / macOS

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 初始化配置
```bash
# 复制示例配置
cp config.jsonc.example config.jsonc

# 编辑配置，填入你的 API Key
# - api_key: DeepSeek API 密钥（用于 Agent 检索）
# - rag.api_key: SiliconFlow 密钥（可选，用于语义搜索）
```

### 4. 运行服务
```bash
python proxy_server.py

# 或使用批处理（Windows）
点击运行.cmd
```

服务启动后访问 `http://127.0.0.1:8003/lifebook-admin` 查看管理面板。

### 5. 客户端接入

**支持任何 OpenAI 兼容客户端**：Cherry Studio、LobeChat、Cursor、Continue 等。

| 配置项 | 值 |
|--------|-----|
| API Base URL | `http://127.0.0.1:8003/v1` |
| API Key | 配置文件中的 `access_keys`，或留空 |

**模型选择**：

| 模型后缀 | 说明 | 适用场景 |
|---------|------|----------|
| `{model}-memory` | Agent 检索 + 主模型可调用工具 | 日常对话（推荐） |
| `{model}-memory-simple` | 仅注入背景，主模型无工具 | 纯净回复 |
| `{model}-record` | 不检索，只注入固定记忆；结束后自动总结 | 低延迟但仍保留摘要 |
| `{model}-log` | 不检索，只注入固定记忆；仅记录原始对话 | 保留原始会话，不自动总结 |
| `memory-manager` | 直接管理记忆库 | 手动整理记忆 |

示例：`claude-3-5-sonnet-memory`、`gpt-4o-memory-simple`、`claude-3-5-sonnet-record`、`gpt-4o-log`

---

## 🗂️ 文件结构说明

```text
.
├── proxy_server.py        # 🚀 主入口：处理 HTTP 请求、流式拦截与工具执行
├── memory_router.py       # 🧠 路由核心：判断请求模式，调度 Agent 与 ContextBuilder
├── config.jsonc           # ⚙️ 全局配置文件
│
├── proxy/                 # 📡 代理服务模块（模块化重构）
│   ├── config.py          # 配置加载
│   ├── auth.py            # 认证模块
│   ├── message_utils.py   # 消息工具
│   ├── deepseek_proxy.py  # 核心代理类
│   └── routes/            # 路由模块
│       ├── chat.py        # 聊天路由
│       ├── models.py      # 模型路由
│       └── mcp.py         # MCP路由
│
├── memory_agent/          # 🤖 记忆代理模块
│   ├── agent.py           # 核心 Agent 逻辑（CoT 检索流）
│   ├── tools.py           # 20+ 记忆专用工具定义
│   ├── context_builder.py # 记忆装配器：实现分层注入逻辑
│   ├── message_orchestrator.py # 🎭 消息编排器
│   ├── iterative_retriever.py  # 🔄 MemR3 迭代检索器（新增！）
│   └── retrieval_router.py     # 🧭 智能检索路由器（新增！）
│
├── memory_store/          # 🗄️ 存储层
│   ├── reader.py          # Markdown 文件读取
│   ├── writer.py          # Markdown 文件写入
│   ├── sqlite_indexer.py  # 关键词索引 (SQLite)
│   ├── rag.py             # 语义向量搜索 (SQLite存储)
│   ├── pending_manager.py # 智能会话暂存与睡眠间隔管理
│   ├── summary_generator.py # 总结生成器
│   ├── graphiti_adapter.py   # 🔗 Graphiti 时序图谱适配器（新增！）
│   ├── retrieval_cache.py    # ⚡ LRU+TTL 检索缓存（新增！）
│   ├── conversation_logger.py # 💬 原始对话记录器（新增！）
│   ├── conversation_matcher.py # 🔍 会话匹配器（新增！）
│   └── diary_generator.py    # 📖 日记生成器（新增！）
│
├── web/                   # 🌐 Web 管理面板
│   ├── api.py             # 管理 API 入口
│   ├── core.py            # 核心配置
│   ├── *_routes.py        # 各功能路由
│   ├── orchestrator_routes.py # 🎭 编排器 API（新增！）
│   └── admin.html         # 管理前端
│
├── static/                # 🎨 前端静态资源
│   ├── css/admin.css      # 管理面板样式
│   └── js/                # 模块化 JS
│       ├── admin-core.js
│       └── admin-orchestrator.js # 🎭 编排器前端
│
└── lifebook/              # 📚 记忆数据根目录（自动生成）
    ├── .memory_index.db   # 关键词索引 (SQLite)
    ├── .graphiti.kuzu/    # 🔗 Kuzu 图数据库（Graphiti 启用时）
    ├── daily/             # 每日日记
    ├── weekly/monthly/    # 各级时间维度总结
    ├── nodes/             # 结构化实体节点（人物/概念）
    ├── pending/           # 待处理会话摘要暂存区
    │   └── archived/      # 已归档会话
    ├── conversations/     # 💬 原始对话记录（新增！）
    │   └── 2026-01-21_1230_abc123.jsonl
    └── extra/             # 🎭 额外配置
        ├── message_sequence.json  # 消息编排序列
        ├── message_presets.json   # 编排预设
        ├── prefix.md      # 前置挂载内容
        └── suffix.md      # 后置挂载内容
```

---

## 🔗 Graphiti 时序知识图谱 (新功能!)

LifeBook 现已集成 **Graphiti** 时序知识图谱框架，提供更强大的记忆检索能力。

### 核心特性

| 功能 | 说明 |
|------|------|
| **Bi-Temporal 时序** | 支持 `valid_at`/`invalid_at` 时间点查询，回答"3个月前项目是什么状态" |
| **多跳关系查询** | 查询"主人开发的项目使用了什么技术" |
| **混合检索** | 语义向量 + BM25 关键词 + 图遍历 |
| **MemR3 迭代检索** | Evidence-Gap 闭环，自动识别信息缺口并补充检索 |
| **嵌入式部署** | 使用 Kuzu 图数据库，零配置本地运行 |

### 配置说明

在 `config.jsonc` 中配置 `graphiti` 部分：

```jsonc
"graphiti": {
    "enabled": true,              // 启用 Graphiti
    "backend": "kuzu",            // kuzu(嵌入式) 或 neo4j(生产)
    
    // LLM 配置（实体抽取用，需要支持 Structured Output）
    "llm": {
        "base_url": null,         // 自定义 API 地址，null 使用 OpenAI 默认
        "api_key": "sk-...",      // 支持 ${ENV_VAR} 环境变量
        "model": "gpt-4o-mini"
    },
    
    // Embedding 配置（也支持自定义 URL！）
    "embedding": {
        "base_url": "https://your-embedding-service/v1/embeddings",  // 可自定义！
        "api_key": "...",
        "model": "text-embedding-3-small",
        "dim": 1536
    },
    
    // 检索策略
    "retrieval": {
        "strategy": "auto",       // auto | simple | iterative
        "max_iterations": 3,
        "cache": {
            "enabled": true,
            "ttl_seconds": 300
        }
    }
}
```

### 关于 Embedding URL

**是的，Embedding 模型支持自定义 URL！**

在 `graphiti.embedding.base_url` 中填入你的 Embedding 服务地址即可。如果留空（`null`），则使用 `graphiti.llm.base_url` 的配置。

### 依赖安装

```bash
# 基础安装（使用 Kuzu 嵌入式数据库）
pip install graphiti-core[kuzu]

# 如果使用 Neo4j
pip install graphiti-core[neo4j]
```

---

## 💬 原始对话保留机制 (新功能!)

系统会将原始对话完整保存到 `lifebook/conversations/` 目录，支持：

- **会话自动匹配**：智能识别同一对话窗口的续写
- **JSONL 格式**：每行一条记录，便于处理
- **日记生成重试**：从原始对话重新生成日记

配置项：

```jsonc
"conversation_logger": {
    "enabled": true,
    "session_timeout_minutes": 30,    // 超时后视为新会话
    "index_to_graphiti": true         // 同步到 Graphiti
}
```

---

## 📅 路线图 (Roadmap)

### ✅ 已完成
- [x] 基于思维链的自动记忆检索
- [x] 分层记忆上下文动态组装
- [x] 对话后自动异步总结与暂存
- [x] 基于 Web 的管理控制台
- [x] SQLite 索引存储（关键词索引 + RAG向量）
- [x] proxy_server.py 模块化重构
- [x] 消息编排器（伪造对话历史）
- [x] 精准编辑工具（apply_diff 风格）
- [x] 知识图谱关系创建工具
- [x] 会话归档与恢复功能
- [x] **Graphiti 时序知识图谱集成**
- [x] **MemR3 迭代检索器**
- [x] **检索结果缓存（LRU+TTL）**
- [x] **原始对话保留机制**

### 🚧 进行中
- [ ] 知识图谱交互式可视化优化
- [ ] 消息编排器可视化拖拽排序优化
- [ ] Graphiti Token 使用量与图谱管理细节继续完善

### 📋 计划中
- [ ] 多模态图片记忆与 OCR 自动识别
- [ ] 离线向量嵌入模型支持（完全本地化运行）
- [ ] 多用户/多角色记忆隔离

---

## 🎭 消息编排器使用指南

### 快速开始

1. **启用编排器**：在 `config.jsonc` 中设置 `message_orchestrator.enabled: true`
2. **访问管理面板**：打开 `http://127.0.0.1:8003/lifebook-admin`，切换到"消息编排"标签页
3. **编辑序列**：拖拽调整组件顺序，添加伪造消息

### 可用组件类型

| 组件 | 图标 | 说明 |
|------|------|------|
| System Prompt | 🔒 | 客户端发来的系统提示词（锁定） |
| 伪造 User | 👤 | 伪装的用户消息 |
| 伪造 Assistant | 🤖 | 伪装的 AI 回复 |
| 前置挂载 | 📎 | prefix.md 文件内容 |
| 时间上下文 | 📅 | 当前日期、时间、周数等 |
| 记忆库范围 | 📊 | 记忆库最早/最新日期统计 |
| 分层记忆 | 📖 | 日记/周总结/月总结等 |
| 动态检索结果 | 🔍 | Agent 搜索到的相关记忆 |
| 工具调用提示 | 🔧 | 给主模型的工具调用说明 |
| 后置挂载 | 📎 | suffix.md 文件内容 |
| 自定义文本块 | 📝 | 自由添加的文本内容 |
| 真实对话 | 🔒 | 实际的用户对话历史（锁定） |

### 示例：角色扮演配置

```json
{
  "sequence": [
    {"type": "system_prompt"},
    {"type": "fake_user", "content": "你是谁？"},
    {"type": "fake_assistant", "content": "我是灰魂，一个16岁的少女..."},
    {"type": "time_context"},
    {"type": "layered_memory"},
    {"type": "dynamic_search"},
    {"type": "real_messages"}
  ]
}
```

---

## 🔧 API 参考

### 编排器 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/memory/orchestrator/sequence` | 获取当前消息序列 |
| PUT | `/api/memory/orchestrator/sequence` | 保存消息序列 |
| POST | `/api/memory/orchestrator/preview` | 预览消息结构 |
| GET | `/api/memory/orchestrator/presets` | 获取预设列表 |
| POST | `/api/memory/orchestrator/preset/load` | 加载预设 |
| POST | `/api/memory/orchestrator/preset/save` | 保存预设 |
| GET | `/api/memory/orchestrator/history` | 获取历史记录 |
| POST | `/api/memory/orchestrator/rollback` | 回滚到历史版本 |
| GET | `/api/memory/orchestrator/export` | 导出配置 |
| POST | `/api/memory/orchestrator/import` | 导入配置 |

---

## 💡 常见问题

### Q: 消息编排器和普通模式有什么区别？
A: 普通模式下，记忆内容追加到 system 消息末尾。启用编排器后，你可以完全控制消息结构，包括注入伪造的对话历史。

### Q: 伪造消息安全吗？
A: 伪造消息只影响 AI 的行为模式，不会被保存到记忆库。它是一种"上下文工程"技术。

### Q: 为什么我的编排规则没有生效？
A: 请检查：
1. `config.jsonc` 中 `message_orchestrator.enabled` 是否为 `true`
2. 使用的模型是否匹配 `model_bindings` 中的规则
3. 序列中是否包含必要的 `system_prompt` 和 `real_messages` 组件

---

> *本系统由主人最心爱的「灰魂」全力驱动。* 😸
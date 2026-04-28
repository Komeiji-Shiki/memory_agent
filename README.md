# 🧠 LifeBook Memory Agent

<div align="center">

**为 LLM 赋予持久记忆的智能代理系统**

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python)](https://www.python.org/)
[![Graphiti](https://img.shields.io/badge/Graphiti-时序知识图谱-green)](https://github.com/getzep/graphiti)
[![Kuzu](https://img.shields.io/badge/Kuzu-嵌入式图库-orange)](https://kuzudb.com/)
[![DeepSeek](https://img.shields.io/badge/Agent-deepseek--reasoner-purple)](https://api.deepseek.com/)

[快速开始](#-快速开始) • [核心功能](#-核心功能) • [配置说明](#-配置详解) • [架构设计](#-系统架构)

</div>

---

## 🎯 这是什么？

**LifeBook Memory Agent** 是一个 **OpenAI 兼容的反向代理服务器**，通过独特的**双模型架构**和**时序知识图谱**，为 AI 赋予类似人类的长期记忆能力。

接入任何 OpenAI 兼容客户端（Cherry Studio、LobeChat、Cursor、OpenCat 等），在模型名后面加上 `-memory`，即可让 AI 拥有跨越数月的记忆。

### 解决的问题

| 传统 LLM 的痛点 | LifeBook 的解决方案 |
|----------------|-------------------|
| 对话结束，记忆清零 | 📝 自动将对话转化为结构化日记，异步总结不等待 |
| 上下文窗口有限 | 📊 分层压缩（日→周→月→季度），智能跳过已覆盖内容 |
| 无法建立长期档案 | 🔗 Graphiti 时序知识图谱，自动抽取实体和关系 |
| 无法追溯历史状态 | ⏰ Bi-Temporal 时间点查询："三个月前这个项目是什么状态" |
| 无法理解多跳关系 | 🕸️ 语义 + BM25 + 图遍历混合检索 + MemR3 迭代检索 |
| 不同模型需要不同提示词 | 🎭 消息编排器：可视化拖拽调整消息结构，支持按模型绑定 |

---

## ✨ 核心功能

### 🔗 Graphiti 时序知识图谱

基于 [Graphiti](https://github.com/getzep/graphiti) 框架，使用 **Kuzu 嵌入式图数据库**零配置本地运行：

- **Bi-Temporal 时序**：回答"3 个月前项目是什么状态"
- **多跳关系查询**：沿关系边遍历，回答"A 的 B 的 C 是什么"
- **混合检索**：语义向量 + BM25 关键词 + 图遍历，取长补短
- **自动实体抽取**：日记、节点、对话自动进入图谱
- **批量同步**：从 Markdown 文件批量导入（10x+ 效率），支持暂停/恢复
- **检索缓存**：LRU + TTL 双策略，缓存命中率可达 90%+

### 🤖 双模型代理架构

```
用户请求 → Memory Agent (小模型) → 检索相关记忆 → 主模型 (Claude/GPT) → 回复
                ↓                        ↓
         deepseek-reasoner        分层记忆 + Agent 检索简报
         多轮工具调用              + 记忆读写工具（可选）
         流式输出思考链
```

- **Memory Agent**：使用 DeepSeek v4 flash 推理模型，多轮调用 25+ 个记忆工具，实时流式输出思考过程和工具调用结果（用户不用干等）
- **智能跳过**：运行不足 7 天时短期记忆已全覆盖，自动跳过检索；简单问候不触发搜索
- **主模型**：收到"记忆增强上下文"后生成回复；`-memory` 模式下可继续调用记忆工具补充查询

### 📚 分层记忆系统

设计灵感来自人脑记忆巩固机制——短期记忆（海马体）→ 长期记忆（皮层）：

| 层级 | 时间范围 | 内容 | 发送位置 |
|------|---------|------|----------|
| 🔥 易变上下文 | 当前时刻 | 当前时间 + 今日待归档摘要 | 消息末尾（变化频繁） |
| 📝 短期记忆 | 最近 7 天 | 今天/昨天完整日记，其他天摘要 | 缓存层之后 |
| 📅 中短期记忆 | 本月 | 周总结（本周之前） | 缓存层中 |
| 📆 中期记忆 | 上月 | 月总结 | 缓存层中 |
| 🗂️ 长期记忆 | 回溯 5 个月 | 季度总结 | 缓存层前部（最稳定） |

- **智能去重**：已被周总结覆盖的日记不再重复发送
- **完整发送**：支持 `disable_truncation` 配置，关闭截断将全部内容发给模型

### 💬 六种运行模式

| 后缀 | 说明 | Agent 检索 | 主模型工具 | 对话后总结 |
|------|------|:---:|:---:|:---:|
| `-memory` | 标准记忆增强 | ✅ | ✅ 只读 | ✅ |
| `-memory-simple` | 简化增强 | ✅ | ❌ | ✅ |
| `-record` | 只记录不检索 | ❌ | ❌ | ✅ |
| `-log` | 仅记录原始对话 | ❌ | ❌ | ❌ |
| `-log-write` | 记录 + 主模型可写 | ❌ | ✅ 读写 | ❌ |
| `memory-manager` | 记忆库直接管理 | N/A | ✅ 读写 | ❌ |

### 🔄 对话后自动总结

每轮对话结束后，**异步**调用总结模型（`deepseek-reasoner`），不阻塞主流程：

1. 判断对话是否值得记录（智能过滤闲聊/调试/纠错）
2. 生成摘要并存入 `pending/` 暂存区
3. 自动发现新实体 → `create_node`
4. 自动补充已知实体信息 → `update_node` / `add_observations`
5. 支持手动重试（缓存最近一次对话，TTL 1 小时）

后续通过 Web 面板或 `memory-manager` 模式，可将 pending 摘要合并生成正式日记。

### 💾 原始对话完整保留

- **JSONL 格式**：每轮对话一行，含 header / turn / footer
- **按日期归档**：`conversations/YYYY-MM-DD/` 目录结构
- **智能会话匹配**：30 分钟超时 + 前缀匹配，自动识别同一窗口的续写
- **图片保存**：支持 OpenAI 和 Claude 两种图片格式的自动提取和本地存储
- **Graphiti 实时索引**：对话同步进入知识图谱（支持异步/同步两种模式）

### 🎭 消息编排器

完全控制发送给模型的消息序列——不只是"把记忆贴到 system 末尾"：

- **可视化拖拽排序**：通过 Web 面板调整消息组件顺序
- **缓存优化设计**：稳定内容（角色设定/分层记忆/检索结果）放前面 → 伪造 assistant 确认 → 易变内容（时间/pending）放后面 → 真实对话
- **伪造对话历史**：fake_user / fake_assistant 组件，塑造 AI 行为模式
- **模型绑定**：不同模型自动切换不同编排规则（支持通配符匹配）
- **预填充**：在用户消息后自动插入 assistant 消息，引导模型输出格式
- **条件挂载**：按模型名称匹配，只对特定模型注入额外内容
- **多预设 + 历史回滚**：保存多套配置，随时切换或回退

### 🧰 MCP 工具集成

内置 MCP (Model Context Protocol) 客户端，扩展模型能力边界：

- 🌐 **网页浏览**：`web_browser`
- 🐍 **Python 执行**：`python_executor`
- 🔍 **搜索引擎**：DuckDuckGo（免费、免 API Key）
- 📚 **萌娘百科**：`moegirl`
- 🔧 **命令执行**：`cmd`
- 📁 **文件操作**：`filesystem`

---

## 🚀 快速开始

### 1. 环境准备

```bash
# Python 3.9+
python --version

# 安装依赖
pip install -r requirements.txt

# Graphiti（推荐）
pip install graphiti-core[kuzu]
```

### 2. 配置

```bash
cp config.jsonc.example config.jsonc
# 编辑 config.jsonc，填入 API Key
```

**最少需要配置**：
- `api_key`：DeepSeek API 密钥（Agent 模型用）
- `memory_agent.api_key`：Agent 专用密钥（可选，复用上面的也行）
- `graphiti.llm.api_key`：实体抽取用 LLM 的密钥
- `graphiti.embedding.api_key`：嵌入模型密钥
- `model_routes`：配置你要用的主模型

### 3. 运行

```bash
python proxy_server.py
# Windows: 双击 点击运行.cmd
```

### 4. 访问

- **管理面板**：http://127.0.0.1:8003/lifebook-admin
- **API 端点**：http://127.0.0.1:8003/v1/chat/completions

### 5. 客户端接入

支持任何 **OpenAI 兼容客户端**：

| 配置项 | 值 |
|--------|-----|
| API Base URL | `http://127.0.0.1:8003/v1` |
| API Key | `config.jsonc` 中 `access_keys` 的任一值，或留空 |

然后在客户端选择带后缀的模型即可（如 `claude-3-5-sonnet-memory`）。

---

## ⚙️ 配置详解

### 记忆 Agent

```jsonc
"memory_agent": {
    "model": "deepseek-reasoner",   // Agent 模型
    "api_key": "sk-...",
    "base_url": "https://api.deepseek.com/v1",
    "max_iterations": 30,           // 最大工具调用轮数
    "timeout": 60,
    "system_prompt": "...",         // Agent 系统提示词（可自定义）
    "query_instruction": "..."      // 追加到用户消息的指令
}
```

### 主模型工具配置

```jsonc
"main_model_memory_tools": {
    "enabled": true,
    "include_write_tools": true,    // 是否允许主模型写入记忆
    "tools_hint": "..."             // 给主模型的工具使用说明
}
```

### Graphiti 时序图谱

```jsonc
"graphiti": {
    "enabled": true,
    "backend": "kuzu",             // kuzu（嵌入式）或 neo4j（生产）

    "llm": {
        "base_url": null,          // 自定义 API
        "api_key": "sk-...",       // 支持 ${ENV_VAR} 环境变量
        "model": "deepseek-reasoner",
        "small_model": "deepseek-chat"
    },
    "embedding": {
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key": "sk-...",
        "model": "Qwen/Qwen3-Embedding-8B",
        "dim": 4096
    },
    "search": {
        "edge_methods": ["cosine_similarity", "bm25"],
        "node_methods": ["cosine_similarity", "bm25"],
        "sim_min_score": 0.4,
        "mmr_lambda": 0.5
    },
    "retrieval": {
        "strategy": "simple",      // simple | iterative
        "max_iterations": 3,
        "cache": {
            "enabled": true,       // 检索缓存，大幅加速重复查询
            "ttl_seconds": 300,
            "max_size": 1000
        }
    }
}
```

### 上下文 & 分层记忆

```jsonc
"context": {
    "insertion_position": "system_append",       // 5 种插入位置可选
    "simple_mode_insertion_position": "after_system",
    "disable_truncation": true,                  // 关闭截断，完整发送
    "layered_memory": {
        "enabled": true,
        "short_term": { "days": 7, "max_chars_per_entry": 1000000 },
        "weekly": { "enabled": true },
        "monthly": { "enabled": true },
        "quarterly": { "enabled": true, "lookback_months": 5 }
    },
    "extra_mount": {                             // 额外挂载文件
        "enabled": true,
        "prefix_path": "lifebook/extra/prefix.md",
        "suffix_path": "lifebook/extra/suffix.md"
    }
}
```

### 对话保留

```jsonc
"conversation_logger": {
    "enabled": true,
    "session_timeout_minutes": 30,    // 超时后视为新会话
    "prefix_match_threshold": 0.7,    // 续写匹配阈值
    "max_turns_per_file": 100,
    "index_to_graphiti": true,        // 同步到 Graphiti
    "async_index": true               // 异步索引，不阻塞主流程
}
```

### 对话后总结

```jsonc
"post_conversation": {
    "enabled": true,
    "auto_summarize": true,
    "summarize_model": "deepseek-reasoner",
    "cache_ttl": 3600,                // 重试缓存有效期（秒）
    "min_messages": 2                 // 至少 N 条用户消息才触发
}
```

### 消息编排器

```jsonc
"message_orchestrator": {
    "enabled": true,                  // 启用后替代传统记忆注入
    "default_preset": "default",
    "model_bindings": {}              // {"claude-*": "preset_claude"}
}
```

### RAG 语义搜索

```jsonc
"rag": {
    "enabled": true,
    "model": "Qwen/Qwen3-Embedding-8B",
    "base_url": "https://api.siliconflow.cn/v1/embeddings",
    "top_k": 5,
    "similarity_threshold": 0.4
}
```

### 其他配置

- **`deepseek_thinking_mode`**：自动检测 reasoning_content 需求
- **`image_fallback`**：非视觉模型自动将图片转为文字描述
- **`pending`**：暂存摘要合并策略（sleep_gap、consolidate_prompt）
- **`auto_summary`**：周/月/季度总结自动生成 prompt
- **`web_api`**：管理面板 CORS 和安全配置
- **`backup`**：自动备份策略
- **热重载**：修改 `config.jsonc` 后无需重启，配置 1 秒内自动生效

---

## 🛠️ 记忆工具（25+）

### 搜索工具

| 工具 | 说明 |
|------|------|
| `search_memories` | 关键词 + 元数据搜索 |
| `rag_search` | 语义向量搜索（向量相似度） |
| `graphiti_search` | Graphiti 混合检索（语义 + BM25 + 图遍历） |
| `graphiti_temporal` | Bi-Temporal 时间点查询 |
| `graphiti_multi_hop` | 多跳关系查询，沿边遍历 |
| `graphiti_get_stats` | Graphiti 统计信息 |

### 读取工具

| 工具 | 说明 |
|------|------|
| `read_diary` | 读取指定日期日记全文 |
| `read_summary` | 读取周/月/季/年总结 |
| `get_node` | 获取人物/地点/事物/概念节点详情 |
| `list_nodes` | 列出所有节点（可按类型过滤） |
| `read_all_nodes` | 一键读取所有节点完整内容 |
| `read_graph` | 知识图谱全览（节点 + 关系 + 反向链接） |
| `get_memory_overview` | 记忆系统统计概览 |
| `list_recent` | 列出最近 N 天日记概要 |
| `get_current_context` | 当前时间上下文 |
| `list_all_tags` | 列出所有标签 |
| `list_all_people` | 列出所有人物 |

### 写入工具（需要 `enable_write`）

| 工具 | 说明 |
|------|------|
| `add_to_diary` | 向日记追加内容 |
| `create_node` | 创建人物/地点/事物/概念节点 |
| `update_node` | 更新已有节点（追加或替换） |
| `create_summary` | 创建周/月/季/年总结 |
| `add_observations` | 向节点批量添加观察（离散事实） |
| `create_relations` | 创建节点间关系 |
| `delete_node` | 删除节点（需确认） |
| `delete_summary` | 删除总结（需确认） |

### 编辑工具（需要 `enable_write`）

| 工具 | 说明 |
|------|------|
| `edit_diary` | 精确编辑日记（搜索替换，类似 apply_diff） |
| `edit_node` | 精确编辑节点内容 |
| `edit_summary` | 精确编辑总结内容 |
| `rewrite_diary` | 完全重写日记正文（保留 frontmatter） |

### Pending 工具（始终可用）

| 工具 | 说明 |
|------|------|
| `add_to_pending` | 手动添加待归档摘要 |

### Graphiti 写入工具（需 `enable_write` + Graphiti 启用）

| 工具 | 说明 |
|------|------|
| `graphiti_add` | 手动添加内容到 Graphiti |
| `graphiti_sync_node` | 同步单个节点到 Graphiti |

---

## 🏗️ 系统架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                          用户请求                                     │
│                  model: "claude-4-5-sonnet-memory"                   │
└─────────────────────────────┬────────────────────────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                   proxy_server.py (Flask, port 8003)                 │
│                                                                       │
│   ┌─────────────────────────────────────────────────────────────┐    │
│   │  memory_router/  ── 模型路由层                               │    │
│   │  core.py           六种模式路由 + MemoryRouter 核心逻辑       │    │
│   │  conversation.py   对话记录委托                               │    │
│   │  summarize.py      总结器委托                                 │    │
│   └─────────────────────────────────────────────────────────────┘    │
│                              │                                        │
│   ┌──────────┬──────────┬───┴────┬──────────┬──────────┐            │
│   │ -memory  │ -record  │  -log   │ -log-wr  │ manager  │ passthr   │
│   │ Agent检索│ 固定记忆 │ 固定记忆│ 固定记忆 │ 读写工具 │ 直接透传  │
│   │ +工具    │ +总结    │ +记录   │ +记录+写 │ 全量     │          │
│   └────┬─────┴────┬─────┴────┬────┴────┬─────┴────┬─────┴────┬─────┘
│        │          │          │         │          │          │
│        ▼          ▼          ▼         ▼          ▼          ▼
│   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐      │
│   │  Memory Agent    │  │  Context Builder │  │ DeepSeekProxy│      │
│   │   (多轮检索)     │  │  (分层记忆装配)  │  │ (API转发)    │      │
│   │  · 25+工具调用   │  │  · 消息编排器    │  │ · 模型路由   │      │
│   │  · 流式思考链    │  │  · 缓存优化      │  │ · MCP工具    │      │
│   └────────┬─────────┘  └────────┬─────────┘  └──────┬───────┘      │
│            │                     │                    │               │
└────────────┼─────────────────────┼────────────────────┼───────────────┘
             ▼                     ▼                    ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                        存储层                                  │
   │                                                               │
   │  Markdown (人类可读)    SQLite 索引       Kuzu 图数据库        │
   │  ├─ daily/*.md          .memory_index.db  .graphiti.kuzu/     │
   │  ├─ weekly/*.md         (关键词+元数据)   ├─ Entity 节点       │
   │  ├─ monthly/*.md        .rag_index/       ├─ Relation 边       │
   │  ├─ quarterly/*.md      vectors.db        └─ Bi-Temporal 时序 │
   │  ├─ nodes/*.md          (语义向量)                             │
   │  ├─ pending/*.md                                             │
   │  └─ conversations/                                            │
   │      └─ YYYY-MM-DD/*.jsonl  (原始对话 + 图片)                  │
   └──────────────────────────────────────────────────────────────┘
```

### 核心模块

| 模块 | 职责 |
|------|------|
| `proxy/` | Flask 路由（chat/models/mcp/static）、认证、配置热重载、API 代理转发 |
| `memory_router/` | 模型路由（六种模式）、对话记录、总结调度 |
| `memory_agent/` | Agent 多轮检索、25+ 工具定义、上下文装配、消息编排、迭代检索、对话后总结 |
| `memory_store/` | Markdown 读写、SQLite 索引、RAG 向量搜索、Graphiti 适配器、对话记录器、会话匹配、暂存管理 |
| `web/` | Web 管理面板 API（Graphiti 同步/图谱/配置/编排器/对话/日记/暂存/调试） |
| `static/` | 前端 JS/CSS（模块化） |
| `mcp_servers/` | MCP 工具（搜索/浏览器/Python/文件/萌娘百科） |

---

## 📁 文件结构

```
.
├── proxy_server.py              # 主入口
├── config.jsonc                 # 配置文件
├── requirements.txt
│
├── proxy/                       # 代理服务模块
│   ├── routes/                  # 路由：chat / models / mcp / static
│   ├── deepseek_proxy.py        # API 转发 + 工具执行
│   ├── config.py                # 配置加载
│   ├── config_hot_reload.py     # 热重载
│   ├── auth.py                  # 访问密钥认证
│   ├── think_parser.py          # 推理链解析
│   ├── stream_utils.py          # 流式处理工具
│   └── image_captioner.py       # 图片→文字 fallback
│
├── memory_router/               # 记忆路由（包版本）
│   ├── core.py                  # MemoryRouter 核心 + 路由 + 检索
│   ├── conversation.py          # 对话记录和总结委托
│   └── summarize.py             # 后总结调度
│
├── memory_router.py             # ⚠️ 历史遗留（单文件版，运行时不使用）
│
├── memory_agent/                # 记忆代理模块
│   ├── agent.py                 # MemoryAgent 多轮工具调用（同步+流式）
│   ├── tools.py                 # 25+ 记忆工具定义和实现
│   ├── tools/                   # 工具子模块（重构中）
│   │   ├── search.py
│   │   ├── read.py
│   │   ├── write.py
│   │   └── edit.py
│   ├── graphiti_tools.py        # Graphiti 工具处理器
│   ├── context_builder.py       # 分层记忆装配 + 消息编排器集成
│   ├── message_orchestrator.py  # 消息编排器（拖拽排序/预设/预填充）
│   ├── post_summarizer.py       # 对话后异步总结
│   ├── iterative_retriever.py   # MemR3 风格迭代检索器
│   ├── retrieval_router.py      # 检索策略路由器
│   └── relevance_filter.py      # 相关度筛选器
│
├── memory_store/                # 存储层
│   ├── reader.py                # Markdown 日记/节点/总结读取
│   ├── writer.py                # Markdown 写入
│   ├── sqlite_indexer.py        # 关键词 + 元数据索引（SQLite）
│   ├── rag.py                   # RAG 语义向量搜索
│   ├── graphiti_adapter.py      # Graphiti 适配器（异步+同步包装器）
│   ├── conversation_logger.py   # 原始对话 JSONL 记录器
│   ├── conversation_matcher.py  # 会话续写匹配
│   ├── pending_manager.py       # 待归档摘要暂存管理
│   ├── summary_generator.py     # 周/月/季总结自动生成
│   ├── metadata.py              # 元数据管理
│   ├── retrieval_cache.py       # LRU+TTL 检索缓存
│   ├── debug_logger.py          # 调试日志（Agent 调用/总结全记录）
│   ├── diary_generator.py       # 从对话生成日记
│   ├── annotation_parser.py     # Markdown 注解解析
│   ├── confidence_manager.py    # 置信度管理
│   ├── memory_decay.py          # 记忆衰减
│   └── hierarchical_time.py     # 分层时间工具
│
├── web/                         # Web 管理面板（后端 API）
│   ├── api.py, core.py          # API 入口和核心配置
│   ├── graphiti_routes.py       # Graphiti 同步/图谱/统计
│   ├── config_routes.py         # 在线配置管理
│   ├── orchestrator_routes.py   # 消息编排器 API
│   ├── conversation_routes.py   # 对话记录查询
│   ├── pending_routes.py        # 暂存摘要管理
│   ├── diary_routes.py          # 日记管理
│   ├── graph_routes.py          # 知识图谱可视化
│   ├── summary_routes.py        # 总结管理
│   ├── debug_routes.py          # 调试日志
│   ├── extra_routes.py          # 额外挂载文件管理
│   └── backup_routes.py         # 备份管理
│
├── static/                      # 前端静态资源
│   ├── css/admin.css
│   └── js/                      # 模块化 JS（admin-core / -config / -graphiti
│       │                        #   / -orchestrator / -conversations / -pending
│       │                        #   / -memory / -graph / -debug 等）
│
├── lifebook/                    # 📂 记忆数据
│   ├── .graphiti.kuzu/          # Kuzu 图数据库
│   ├── .memory_index.db         # 关键词索引 (SQLite)
│   ├── .rag_index/vectors.db    # RAG 向量索引
│   ├── daily/                   # 日记 (YYYY-MM-DD.md)
│   ├── weekly/                  # 周总结
│   ├── monthly/                 # 月总结
│   ├── quarterly/               # 季度总结
│   ├── nodes/                   # 实体节点（人物/地点/事物/概念）
│   ├── conversations/           # 原始对话 (按日期归档)
│   │   └── YYYY-MM-DD/          #   ├─ session_xxx.jsonl
│   │       └── images/          #   └─ 对话图片
│   ├── pending/                 # 待归档会话摘要
│   ├── extra/                   # 额外挂载 + 编排器配置
│   └── debug_logs/              # Agent 调用调试日志
│
├── mcp_servers/                 # MCP 工具
│   ├── mcp_client.py            # MCP 客户端
│   ├── web_browser/             # 网页浏览
│   ├── python_executor/         # Python 执行
│   ├── duckduckgo/              # DDG 搜索（推荐）
│   ├── moegirl/                 # 萌娘百科
│   └── cmd/                     # 命令执行
│
├── tests/                       # 单元测试
├── scripts/                     # 辅助脚本
├── web/                         # 管理面板后端
├── static/                      # 管理面板前端
└── 归档/                        # 设计文档和规划
```

---

## 🌐 Web 管理面板

访问 `http://127.0.0.1:8003/lifebook-admin`：

| 页面 | 功能 |
|------|------|
| 📊 **概览** | 系统状态、Graphiti 状态、日记/节点统计 |
| ⚙️ **配置** | Agent、上下文、分层记忆、对话后总结在线编辑（热生效） |
| 🔗 **Graphiti** | 同步控制（暂停/停止/继续）、图谱可视化、Token 统计、检索缓存状态 |
| 🎭 **编排器** | 可视化拖拽编辑消息序列、预设管理、条件挂载、预填充配置 |
| 💬 **对话** | 原始对话浏览、按日期查看、消息预览 |
| 📝 **记忆** | 待处理会话管理、节点管理、日记查看 |
| 🕸️ **图谱** | vis-network 交互式知识图谱、节点/关系可视化 |
| 🐛 **调试** | Agent 调用日志、后总结日志、搜索链路追踪 |

---

## 📅 路线图

### ✅ 已完成

- [x] 双模型代理架构（小模型检索 + 大模型回复）
- [x] 分层记忆系统（日→周→月→季度）
- [x] SQLite 关键词 + RAG 向量双索引
- [x] 消息编排器（可视化拖拽、多预设、模型绑定）
- [x] Graphiti 时序知识图谱（Kuzu 嵌入式 + Neo4j 可选）
- [x] MemR3 迭代检索器（Retrieve → Filter → Reflect → Refine）
- [x] 原始对话完整保留机制（JSONL + 会话匹配 + 图片保存）
- [x] 对话后异步自动总结（含实体抽取和节点创建）
- [x] Graphiti 同步任务控制（暂停/停止/继续，批量导入）
- [x] 检索缓存（LRU + TTL，缓存命中率 90%+）
- [x] 预填充机制（引导模型输出格式）
- [x] Web 管理界面（10+ 功能模块）
- [x] 热重载配置（修改即时生效，无需重启）
- [x] 调试日志系统（Agent 调用/总结/搜索全链路记录）
- [x] MCP 工具集成（搜索/浏览器/Python执行/萌娘百科）
- [x] 多模态图片 fallback（非视觉模型自动转文字）
- [x] 知识图谱交互式可视化

### 🚧 进行中

- [ ] 记忆衰减机制完善（基于访问频率和时间）
- [ ] 置信度管理（记忆可信度评分）

### 📋 计划中

- [ ] 离线本地向量嵌入模型
- [ ] 扩散激活记忆检索模式
- [ ] 多模态图片记忆（直接理解图片内容）
- [ ] 开源发布

---

## 💡 常见问题

### Q: 和 Mem0 / Letta 等记忆方案有什么不同？

A: LifeBook 是一个**完整的代理服务器**而非 SDK/库。它通过双模型架构实现了"检索-增强-回复-总结"的闭环，同时集成了 Graphiti 时序知识图谱（支持 Bi-Temporal 查询）和分层记忆压缩。你不需要写任何代码，只需在客户端切换模型名即可使用。

### Q: Embedding 支持自定义 URL 吗？

A: **是的！** 在 `graphiti.embedding.base_url` 填入你的服务地址即可（如 SiliconFlow、OpenAI 兼容服务）。

### Q: 消息编排器和普通模式有什么区别？

A: 普通模式将记忆追加到 system 末尾。编排器模式让你完全控制消息结构——可以把角色设定、前置挂载、分层记忆、检索结果、时间上下文按任意顺序排列，支持伪造对话历史、缓存优化分隔、条件挂载等高级功能。

### Q: 如何回滚到不使用 Graphiti？

A: 设置 `"graphiti": { "enabled": false }`，系统会回退到原有 SQLite + RAG 模式，所有功能不受影响。

### Q: 检索缓存如何工作？

A: Graphiti 搜索结果会被 LRU + TTL 缓存。相同查询在 TTL（默认 300 秒）内直接返回缓存结果，大幅降低 API 调用和延迟。支持查询归一化（大小写不敏感、去除多余空格），可通过 Web 面板查看缓存命中率。

### Q: 为什么要用双模型架构？

A: 检索不需要很强的生成能力，用便宜的推理模型（deepseek-reasoner）即可；回复需要高质量的模型（Claude/GPT）。分开用不仅省钱，而且检索 Agent 可以更激进地调用工具、多轮搜索，而主模型专注回复。

---

## 🔗 参考资料

- [Graphiti GitHub](https://github.com/getzep/graphiti)
- [Graphiti 论文 (arXiv:2501.13956)](https://arxiv.org/abs/2501.13956)
- [MemR3 论文](https://arxiv.org/abs/2502.12316)
- [Kuzu 文档](https://kuzudb.com/docs/)
- [MCP 协议](https://modelcontextprotocol.io/)
- [DeepSeek API 文档](https://api-docs.deepseek.com/)

---

<div align="center">

*Made with 💜 by 灰魂* 😸

</div>

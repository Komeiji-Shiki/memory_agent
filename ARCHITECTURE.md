# LifeBook Memory Agent 架构说明 🐱

## 系统概览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           用户请求                                       │
│                   model: "claude-3-5-sonnet-memory"                     │
└──────────────────────────────┬──────────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    proxy_server.py (端口8003)                           │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │  model_routes 路由:                                                 ││
│  │  • xxx-memory → 记忆增强模式（主模型可继续调用记忆工具）             ││
│  │  • xxx-memory-simple → 记忆增强简化模式（主模型无记忆工具）          ││
│  │  • xxx-record → 固定记忆注入 + 对话后总结                           ││
│  │  • xxx-log → 固定记忆注入 + 仅记录原始对话                          ││
│  │  • xxx-log-write → 固定记忆注入 + 主模型记忆读写工具 + 仅记录原始对话 ││
│  │  • memory-manager → 记忆管理模式                                    ││
│  │  • xxx → 直接透传                                                   ││
│  └─────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────┬──────────────────────────────────────────┘
                               ▼
        ┌──────────────────────┴──────────────────────┐
        ▼                                             ▼
┌───────────────────────┐                   ┌───────────────────────┐
│  记忆增强模式         │                   │  直接透传模式         │
│  (xxx-memory)         │                   │  (xxx)                │
└───────────┬───────────┘                   └───────────┬───────────┘
            ▼                                           ▼
┌───────────────────────────────┐           ┌───────────────────────────────┐
│  1. 小模型Agent检索记忆       │           │  直接转发到后端API            │
│     (deepseek-reasoner)       │           │  + MCP工具                    │
│     调用12个记忆专用工具      │           └───────────────────────────────┘
│                               │
│  2. 组装分层记忆上下文        │
│     • 短期：最近7天日记       │
│     • 中短期：本月周总结      │
│     • 中/长期：月/季总结      │
│     • Agent 检索简报          │
│                               │
│  3. 注入到消息中              │
│                               │
│  4. 转发到主模型              │
│     (claude/gpt等)            │
│     + MCP工具 + 记忆工具      │
└───────────────────────────────┘
```

---

## 记忆Agent工具（12个）

这些工具只有**记忆Agent**和**主模型**（当启用`main_model_memory_tools`时）可以调用。

### 只读工具（任何模式）

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `search_memories` | 搜索记忆 | query, tags?, people?, date_start?, date_end?, limit? |
| `read_diary` | 读取指定日期日记 | date (YYYY-MM-DD) |
| `read_summary` | 读取周/月/季/年总结 | type, identifier |
| `get_node` | 获取人物/地点节点 | name |
| `list_recent` | 列出最近N天日记 | days? |
| `get_current_context` | 获取当前时间上下文 | - |
| `list_all_tags` | 列出所有标签 | limit? |
| `list_all_people` | 列出所有人物 | limit? |

### 写入工具（仅记忆管理模式）

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `add_to_diary` | 向日记添加内容 | content, date?, section? |
| `create_node` | 创建新节点 | name, type, content, tags? |
| `update_node` | 更新节点 | name, content, mode? |
| `create_summary` | 创建总结 | type, identifier, content, title? |

---

## MCP工具（需要清理）

### 🗑️ 建议删除（与LifeBook功能重复）

| 目录 | 原因 |
|------|------|
| `mcp_servers/memory/` | 与LifeBook记忆系统重复 |
| `mcp_servers/memory2/` | 与LifeBook记忆系统重复 |
| `mcp_servers/memory_enhanced/` | 与LifeBook记忆系统重复 |

### ✅ 建议保留

| 目录 | 功能 | 说明 |
|------|------|------|
| `web_browser/` | 网页浏览 | 实用工具，保留 |
| `python_executor/` | Python执行 | 实用工具，保留 |
| `moegirl/` | 萌娘百科 | 特殊用途，可保留 |

### 🔄 搜索类（保留一个即可）

| 目录 | 说明 |
|------|------|
| `duckduckgo2/` | ✅ 推荐保留（免费，不需要API Key） |
| `baidu_browser_search/` | 可选 |
| `google_search/` | 需要API Key |
| `bing_search/` | 需要API Key |
| 其他搜索 | 可删除 |

---

## 使用方式

### 1. 记忆增强对话

#### 标准模式
```
模型ID: claude-3-5-sonnet-memory
```

流程：
1. 小模型 Agent 自动检索相关记忆
2. 记忆注入到消息中
3. 主模型基于记忆回复
4. 主模型也可直接调用记忆工具补充查询

#### 简化模式
```
模型ID: claude-3-5-sonnet-memory-simple
```

流程：
1. 小模型 Agent 自动检索相关记忆
2. 记忆注入到消息中
3. 主模型基于增强上下文直接回复
4. **主模型不可再调用记忆工具**

### 2. 记录模式（无检索，有总结）

```
模型ID: claude-3-5-sonnet-record
```

流程：
1. 不调用 Agent 检索
2. 注入固定记忆（最近日记、总结等）
3. 主模型直接回复
4. 对话结束后自动生成摘要并写入 pending

### 3. 日志模式（无检索，仅保留原始对话）

```
模型ID: claude-3-5-sonnet-log
```

流程：
1. 不调用 Agent 检索
2. 注入固定记忆（最近日记、总结等）
3. 主模型直接回复
4. 仅记录原始对话到 JSONL，不触发对话后总结

### 4. 日志写入模式（固定记忆 + 主模型记忆读写工具）

```
模型ID: claude-3-5-sonnet-log-write
```

流程：
1. 不调用 Agent 检索
2. 注入固定记忆（最近日记、总结等）
3. 主模型可直接调用记忆读写工具
4. 仅记录原始对话到 JSONL，不触发对话后总结

### 5. 记忆管理

```
模型ID: memory-manager
```

流程：
1. 直接对话，可以查询和**写入**记忆
2. "帮我记录今天发生的事情..."
3. "创建一个关于小明的人物节点"

### 6. 普通对话（无记忆）

```
模型ID: claude-3-5-sonnet
```

流程：
1. 直接转发到后端API
2. 只有MCP工具可用

---

## 文件结构

```
i:/api聚合/记忆/
├── proxy_server.py        # 主服务器入口 (精简版，170行)
├── config.jsonc           # 配置文件
├── memory_router.py       # 记忆路由器
│
├── proxy/                 # 代理服务模块 (重构后) ✨
│   ├── __init__.py        # 模块入口
│   ├── config.py          # 配置加载
│   ├── auth.py            # 认证模块
│   ├── message_utils.py   # 消息工具
│   ├── deepseek_proxy.py  # 核心代理类
│   └── routes/            # 路由模块
│       ├── chat.py        # 聊天路由
│       ├── models.py      # 模型路由
│       ├── mcp.py         # MCP路由
│       └── static.py      # 静态页面
│
├── memory_agent/          # 记忆Agent模块
│   ├── agent.py           # Agent多轮调用
│   ├── tools.py           # 20+记忆工具定义
│   └── context_builder.py # 上下文组装
│
├── memory_store/          # 记忆存储模块
│   ├── reader.py          # 读取日记/节点
│   ├── writer.py          # 写入日记/节点
│   ├── sqlite_indexer.py  # 关键词索引 (SQLite) ✨
│   ├── rag.py             # 向量检索 (SQLite存储) ✨
│   ├── metadata.py        # 元数据管理
│   ├── pending_manager.py # 智能会话暂存管理
│   └── summary_generator.py # 总结生成器
│
├── web/                   # Web管理 (模块化)
│   ├── api.py             # API入口
│   ├── core.py            # 核心配置
│   ├── *_routes.py        # 各功能路由
│   └── backup.py          # 备份工具
│
├── static/                # 前端静态资源
│   ├── css/admin.css      # 管理面板样式
│   └── js/admin-*.js      # 模块化JS
│
├── lifebook/              # 记忆数据
│   ├── .memory_index.db   # 关键词索引 (SQLite) ✨
│   ├── .rag_index/        # RAG向量索引
│   │   └── vectors.db     # 向量数据库 (SQLite) ✨
│   ├── daily/             # 日记 (YYYY-MM-DD.md)
│   ├── weekly/            # 周总结
│   ├── monthly/           # 月总结
│   ├── nodes/             # 人物/地点/事物节点
│   └── pending/           # 待处理会话摘要
│
├── tests/                 # 测试模块 ✨
│   └── test_*.py          # 单元测试
│
└── mcp_servers/           # MCP工具
    ├── web_browser/       # 网页浏览
    ├── python_executor/   # Python执行
    └── moegirl/           # 萌娘百科
```

---

## 存储方案说明

### 索引存储 (已完成迁移)

| 组件 | 存储方式 | 文件位置 |
|------|---------|---------|
| 关键词索引 | SQLite | `lifebook/.memory_index.db` |
| RAG向量索引 | SQLite | `lifebook/.rag_index/vectors.db` |

旧的JSON索引文件（如有）会自动迁移到SQLite，原文件备份到 `json_backup/` 目录。

### 记忆工具列表

| 类别 | 工具名 | 说明 |
|------|-------|------|
| 搜索 | search_memories | 关键词搜索 |
| 搜索 | rag_search | 语义向量搜索 |
| 读取 | read_diary, read_summary | 读取日记/总结 |
| 读取 | get_node, list_nodes | 节点操作 |
| 读取 | get_memory_overview | 记忆概览 |
| 读取 | read_graph, read_all_nodes | 知识图谱 |
| 写入 | add_to_diary, create_node | 创建内容 |
| 写入 | update_node, add_observations | 更新节点 |
| 写入 | create_relations | 创建关系 |
| 编辑 | edit_diary, edit_node, edit_summary | 精准编辑 |
| 删除 | delete_node, delete_summary | 删除操作 |

---

## 后续规划

- [ ] 知识图谱交互式可视化（见 `规划三-知识图谱可视化.md`）
- [ ] 多模态图片记忆
- [ ] 离线向量嵌入模型

---

*Made with 💜 by 灰魂* 😸
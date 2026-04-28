# 🚀 LifeBook v2.0 - Graphiti 时序知识图谱改造总规划

> ⚠️ 本文档是归档的总规划/设计文档，不应视为当前仓库实现现状的唯一依据。
> 当前实际支持的模式、入口路径、运行方式与管理界面，请优先以 [`README.md`](README.md) 和 [`MemoryRouter.route()`](memory_router.py:384) 对应的实际实现为准。

## 📋 概述

本规划将现有的 **Markdown 节点知识图谱** 改造为基于 **Kuzu + Graphiti** 的 **时序知识图谱**，使其支持多跳查询、时序追溯、混合检索等高级功能。

### 核心目标

1. **时序知识图谱**：从静态节点 → Bi-Temporal 动态图
2. **保留 Markdown**：Markdown 仍是人类可读的"事实源"
3. **Kuzu 嵌入式图库**：零部署，数据在本地文件夹
4. **Graphiti 框架**：自动实体抽取、混合检索、时序管理

---

## 📊 现状分析

### 当前知识图谱架构

```
lifebook/nodes/
├── 人物-主人.md          ← 实体存储（Markdown 文件）
├── 人物-灰魂.md
├── 事物-LifeBook系统.md
└── 概念-记忆管理.md

文件内容示例（人物-主人.md）：
┌─────────────────────────────────────────────────────────────┐
│ LifeBook记忆系统的使用者...（实体描述）                      │
│                                                             │
│ ### 关联：开发                                               │
│ - [[LifeBook Memory Agent]]（开发）                         │
│                                                             │
│ ### 关联：有                                                 │
│ - [[二氧化碳浓度问题]]（有）                                 │
└─────────────────────────────────────────────────────────────┘

关系表达：通过 [[双链]] + 分组标题
查询方式：遍历所有文件 → 正则提取链接 (O(n))
```

### 当前痛点

| 问题 | 说明 | 影响 |
|------|------|------|
| **关系查询 O(n)** | 每次查询都要遍历所有 Markdown 文件 | 慢，无法扩展 |
| **无多跳查询** | 无法查"主人的朋友认识的人" | 功能缺失 |
| **无时序版本** | 无法追溯"3个月前项目是什么状态" | 信息丢失 |
| **关系无有效期** | 无法表达"2025年1-3月使用某工具" | 语义不完整 |
| **无图算法** | 无法做 PageRank、社区发现 | 无法分析 |

---

## 🎯 改造目标

### 改造前 vs 改造后

```
改造前：                              改造后：
┌─────────────────────┐              ┌─────────────────────────────────────┐
│  lifebook/nodes/    │              │  lifebook/                           │
│  ├── 人物-主人.md   │ ──────────►  │  ├── nodes/*.md （保留，人类可读）   │
│  ├── 人物-灰魂.md   │   迁移       │  ├── .graphiti.kuzu/ （Kuzu 图库）   │
│  └── ...            │              │  └── daily/*.md                      │
│                     │              │                                      │
│  查询：遍历文件     │              │  查询：Graphiti 混合检索             │
│  关系：[[双链]]     │              │  关系：图边 + Bi-Temporal            │
│  时序：无           │              │  时序：valid_at, invalid_at          │
└─────────────────────┘              └─────────────────────────────────────┘
```

### 改造收益

| 能力 | 改造前 | 改造后 |
|------|--------|--------|
| 关系查询 | O(n) 遍历 | **O(1) 图遍历** |
| 多跳查询 | ❌ | ✅ "主人开发的项目用了什么技术" |
| 时间点查询 | ❌ | ✅ "2025年3月时项目状态" |
| 混合检索 | 关键词 OR 语义 | **语义 + BM25 + 图遍历** |
| 图分析 | ❌ | ✅ PageRank、社区发现 |
| 部署复杂度 | 无 | **无（Kuzu 嵌入式）** |

---

## 🔄 双模式记忆系统

### 设计理念

保留现有的**结构化节点**（人物、地点、事物），同时引入 Graphiti 的**普通记忆检索**，两者相辅相成：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          LifeBook 双模式记忆系统                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                    结构化节点 (nodes/*.md)                             │ │
│   │                                                                        │ │
│   │   适合：                                                               │ │
│   │   ✅ 长期稳定的实体（人物、项目、概念）                                │ │
│   │   ✅ 需要人类可读/可编辑的信息                                         │ │
│   │   ✅ 核心知识的"事实源"                                               │ │
│   │                                                                        │ │
│   │   例子：                                                               │ │
│   │   - 人物-主人.md：主人的基本信息、技能、健康状况                       │ │
│   │   - 事物-LifeBook.md：项目描述、功能列表                               │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
│                                     ▲                                        │
│                                     │ 同步                                   │
│                                     ▼                                        │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                    Graphiti 时序记忆图                                  │ │
│   │                                                                        │ │
│   │   适合：                                                               │ │
│   │   ✅ 动态变化的事实（今天做了什么、最近学了什么）                       │ │
│   │   ✅ 需要时序追溯的信息（3个月前项目状态）                             │ │
│   │   ✅ 多跳关系查询（主人→开发→项目→使用→技术）                         │ │
│   │   ✅ 对话记忆的实时索引                                                │ │
│   │                                                                        │ │
│   │   例子：                                                               │ │
│   │   - Episode: "2026-01-21 主人讨论了LifeBook改进方案"                   │ │
│   │   - Edge: "主人 --[开发,2025-01至今]--> LifeBook"                      │ │
│   │   - Edge: "LifeBook --[使用,2025-06至今]--> DeepSeek"                  │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 两种记忆的分工

| 记忆类型 | 存储位置 | 适用场景 | 更新频率 |
|----------|---------|---------|---------|
| **结构化节点** | `nodes/*.md` | 长期实体信息 | 低（手动/重大更新） |
| **对话记忆** | Graphiti Episodes | 每日对话内容 | 高（每轮对话） |
| **日记记忆** | Graphiti Episodes + `daily/*.md` | 每日总结 | 中（每日） |
| **关系记忆** | Graphiti Edges | 实体间关系 | 中（自动抽取） |
| **时序事实** | Graphiti Edges (Bi-Temporal) | 状态变化 | 中（自动追踪） |

### 查询路由示例

```
用户问题                         →  路由到                    →  数据源
─────────────────────────────────────────────────────────────────────────
"灰魂是谁？"                     →  结构化节点查询            →  人物-灰魂.md
"主人最近在做什么？"             →  Graphiti 记忆检索         →  对话/日记 Episodes
"LifeBook 用了什么技术？"        →  Graphiti 关系查询         →  边: LifeBook→使用→技术
"3个月前项目是什么状态？"        →  Graphiti 时序查询         →  历史快照 Edges
"主人开发的项目的用户是谁？"     →  Graphiti 多跳查询         →  图遍历
```

### 同步机制

```
Markdown 节点                    Graphiti 图
────────────                     ────────────
人物-主人.md  ──────同步─────►  Entity: 主人
    │                               │
    │ [[开发]]                      │ Edge: 开发
    ▼                               ▼
事物-LifeBook.md ────同步────►  Entity: LifeBook

同步规则：
1. 节点创建/更新 → 自动同步到 Graphiti
2. Graphiti 发现新实体 → 提示创建节点（可选）
3. 冲突时以 Markdown 为准
```

---

## 🏗️ 改造后架构

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                              LifeBook v2.0                                     │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  用户请求 ──► Memory Agent ──► 检索策略选择 ──► 上下文注入 ──► 主模型回复      │
│                                    │                                           │
│                    ┌───────────────┴───────────────┐                          │
│                    ▼                               ▼                          │
│              Graphiti 检索                   deepseek-reasoner                │
│              (推荐，快速)                    (复杂推理)                        │
│                    │                               │                          │
│                    └───────────────┬───────────────┘                          │
│                                    ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────┐  │
│  │                         Graphiti 框架层                                  │  │
│  │                                                                          │  │
│  │   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐  │  │
│  │   │   Episode 管理    │  │   实体/边 抽取   │  │   混合检索引擎        │  │  │
│  │   │   (对话→知识)     │  │   (LLM 自动)     │  │   语义+BM25+图遍历    │  │  │
│  │   └──────────────────┘  └──────────────────┘  └──────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────────────────┘  │
│                                    │                                          │
│  ┌─────────────────────────────────┴───────────────────────────────────────┐  │
│  │                         存储层                                           │  │
│  │                                                                          │  │
│  │   ┌─────────────┐   ┌─────────────────────┐   ┌───────────────────────┐ │  │
│  │   │  Markdown   │   │  Kuzu 图数据库       │   │   Conversation JSONL  │ │  │
│  │   │  (人类可读) │◄──│  .graphiti.kuzu/     │──►│   conversations/      │ │  │
│  │   │  nodes/*.md │   │  - 节点 (Entity)     │   │   (原始对话保留)      │ │  │
│  │   │  daily/*.md │   │  - 边 (Relation)     │   │                       │ │  │
│  │   │             │   │  - 时序 (Bi-Temporal)│   │                       │ │  │
│  │   └─────────────┘   └─────────────────────┘   └───────────────────────┘ │  │
│  │         ▲                      │                                         │  │
│  │         │                      ▼                                         │  │
│  │         └──────── 双向同步（Markdown ↔ Kuzu）────────────────────────────│  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Phase 1: Graphiti 存储层整合 (5-7天)

### 1.1 为什么选择 Graphiti

| 对比项 | 自己实现 Neo4j (规划五) | 使用 Graphiti |
|--------|------------------------|---------------|
| 开发工作量 | 大（需实现全部功能） | 小（开箱即用） |
| Bi-Temporal | 需自己设计 | **原生支持** |
| 混合检索 | 需自己实现 | **语义+BM25+图遍历** |
| 多后端支持 | 仅 Neo4j | **Kuzu/Neo4j/FalkorDB/Neptune** |
| 维护成本 | 高 | 低（社区维护） |
| MCP Server | 需自己开发 | **自带** |
| 论文支持 | 无 | **arXiv:2501.13956** |

### 1.2 安装配置

```bash
# requirements.txt 新增
graphiti-core>=0.17.0
graphiti-core[kuzu]          # 本地轻量方案，推荐开发
# graphiti-core[neo4j]       # 生产环境可选
# graphiti-core[google-genai] # 使用 Gemini
```

### 1.3 配置文件

```jsonc
// config.jsonc 新增
{
    "graphiti": {
        "enabled": true,
        "backend": "kuzu",  // kuzu | neo4j | falkordb
        
        // Kuzu 本地图数据库（推荐开发环境）
        "kuzu": {
            "db_path": "./lifebook/.graphiti.kuzu"
        },
        
        // Neo4j（可选，生产环境）
        "neo4j": {
            "uri": "bolt://localhost:7687",
            "username": "neo4j",
            "password": "",
            "database": "lifebook"
        },
        
        // LLM 配置（支持 OpenAI 兼容格式）
        // ⚠️ 重要：Graphiti 需要支持 Structured Output 的 LLM
        // 因为实体/关系抽取使用 Pydantic 模型定义输出格式
        "llm": {
            "base_url": null,  // 自定义API地址，null则使用默认OpenAI
            "api_key": "${OPENAI_API_KEY}",  // 支持环境变量
            "model": "gpt-4o-mini",
            "small_model": "gpt-4o-mini",  // 用于简单任务
            "embedding_model": "text-embedding-3-small",
            "embedding_dim": 1536
        },
        
        // Reranker 配置（提升检索精度）
        // 使用 logprobs 进行 True/False 相关性判断
        "reranker": {
            "enabled": true,
            "model": "gpt-4o-mini"
        },
        
        // 搜索配置 - 对应 SearchConfig
        "search": {
            "edge_methods": ["cosine_similarity", "bm25"],  // 边搜索方法
            "node_methods": ["cosine_similarity", "bm25"],  // 节点搜索方法
            "edge_reranker": "cross_encoder",  // rrf | cross_encoder | mmr | node_distance
            "node_reranker": "rrf",
            "sim_min_score": 0.4,      // 语义相似度最低分
            "mmr_lambda": 0.5,         // MMR 多样性参数
            "reranker_min_score": 0.3  // 重排序后最低分
        },
        
        // Group ID 策略（用户/项目隔离）
        "group_id": {
            "strategy": "single",  // single | user | project
            "default": "lifebook",
            "user_template": "user_{user_id}",
            "project_template": "project_{project_id}"
        },
        
        // Episode 类型配置
        "episode_types": {
            "diary": {
                "priority": "high",
                "extract_entities": true
            },
            "node": {
                "priority": "medium",
                "extract_entities": true
            },
            "conversation": {
                "priority": "low",
                "extract_entities": true,
                "min_value_threshold": 0.3
            }
        },
        
        // 同步设置
        "sync": {
            "mode": "dual_write",
            "index_conversations": true
        },
        
        // 检索配置
        "retrieval": {
            "strategy": "iterative",  // simple | iterative (MemR3风格)
            "max_iterations": 3,
            "default_limit": 10,
            "include_edges": true,
            "include_nodes": true
        },
        
        // 性能配置
        "performance": {
            "semaphore_limit": 10,     // 并发限制，防止 LLM 429 错误
            "retry_on_rate_limit": true,
            "max_retries": 3
        },
        
        // 可观测性（OpenTelemetry）
        "telemetry": {
            "enabled": false,          // 生产环境建议开启
            "exporter": "stdout",      // stdout | otlp | jaeger
            "otlp_endpoint": "http://localhost:4317"
        }
    }
}
```

### 1.3.1 为什么需要 Structured Output？

Graphiti 在实体抽取和关系抽取时使用 **Pydantic 模型**定义 LLM 输出格式：

```python
# 来自 graphiti_core/prompts/extract_nodes.py
class ExtractedEntity(BaseModel):
    name: str = Field(..., description='Name of the extracted entity')
    entity_type_id: int = Field(description='ID of the classified entity type')

# 来自 graphiti_core/prompts/extract_edges.py
class Edge(BaseModel):
    relation_type: str = Field(..., description='FACT_PREDICATE_IN_SCREAMING_SNAKE_CASE')
    source_entity_id: int = Field(...)
    target_entity_id: int = Field(...)
    fact: str = Field(...)
    valid_at: str | None = Field(None)  # ISO 8601 格式
    invalid_at: str | None = Field(None)
```

**Structured Output 保证**：
- `entity_type_id` 一定是整数，不是字符串 `"1"`
- `valid_at` 一定是 ISO 8601 格式或 null，不是 `"last week"`
- 必填字段一定存在
- 解析后直接可用，无需复杂后处理

**兼容性**：主人的 API 聚合服务如果支持 OpenAI 的 `response_format: { type: "json_schema" }` 参数即可。

### 1.4 Graphiti 适配器实现

```python
# memory_store/graphiti_adapter.py

from graphiti_core import Graphiti
from graphiti_core.driver.kuzu_driver import KuzuDriver
from graphiti_core.driver.neo4j_driver import Neo4jDriver
# 使用 OpenAIGenericClient 支持自定义 base_url（兼容各种 OpenAI API 聚合服务）
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
# 引入 Reranker 支持
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
# 引入 SearchConfig 进行精细配置
from graphiti_core.search.search_config import SearchConfig
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum
import asyncio
import logging
import os

logger = logging.getLogger(__name__)


class EpisodeType(Enum):
    """Episode 类型枚举"""
    DIARY = "diary"        # 日记：高信息密度，必定提取
    NODE = "node"          # 节点：结构化实体描述
    CONVERSATION = "conv"  # 对话：可能有闲聊，需要筛选


class GroupIdStrategy:
    """Group ID 策略管理器"""
    
    def __init__(self, config: dict):
        self.strategy = config.get("strategy", "single")
        self.default = config.get("default", "lifebook")
        self.user_template = config.get("user_template", "user_{user_id}")
        self.project_template = config.get("project_template", "project_{project_id}")
    
    def get_group_id(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> str:
        """根据策略获取 group_id"""
        if self.strategy == "user" and user_id:
            return self.user_template.format(user_id=user_id)
        elif self.strategy == "project" and project_id:
            return self.project_template.format(project_id=project_id)
        else:
            return self.default


class GraphitiAdapter:
    """
    Graphiti 适配器 - 桥接 LifeBook 与 Graphiti
    
    特性：
    - 支持 OpenAI 兼容 API（自定义 base_url）
    - 支持 Reranker 提升检索精度
    - 支持 SearchConfig 精细控制
    - 支持 Group ID 策略（用户/项目隔离）
    - 支持 Episode 类型区分（diary/node/conversation）
    """
    
    def __init__(self, config: dict, lifebook_path: str):
        self.config = config
        self.lifebook_path = Path(lifebook_path)
        self.graphiti: Optional[Graphiti] = None
        self._initialized = False
        
        # Group ID 策略
        self.group_id_strategy = GroupIdStrategy(
            config.get("group_id", {})
        )
        
        # Episode 类型配置
        self.episode_type_config = config.get("episode_types", {})
        
        # 检索配置
        self.retrieval_config = config.get("retrieval", {})
    
    async def initialize(self):
        """异步初始化 Graphiti"""
        if self._initialized:
            return
        
        # 1. 创建图数据库驱动
        backend = self.config.get("backend", "kuzu")
        
        if backend == "kuzu":
            db_path = self.config.get("kuzu", {}).get(
                "db_path",
                str(self.lifebook_path / ".graphiti.kuzu")
            )
            driver = KuzuDriver(db=db_path)
            
        elif backend == "neo4j":
            neo4j_config = self.config.get("neo4j", {})
            driver = Neo4jDriver(
                uri=neo4j_config.get("uri", "bolt://localhost:7687"),
                user=neo4j_config.get("username", "neo4j"),
                password=neo4j_config.get("password", ""),
                database=neo4j_config.get("database", "lifebook")
            )
        else:
            raise ValueError(f"Unsupported backend: {backend}")
        
        # 2. 创建 LLM 客户端（支持自定义 base_url）
        llm_config = self.config.get("llm", {})
        
        # 解析环境变量
        api_key = llm_config.get("api_key", "${OPENAI_API_KEY}")
        if api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            api_key = os.environ.get(env_var, "")
        
        llm_client_config = LLMConfig(
            api_key=api_key,
            model=llm_config.get("model", "gpt-4o-mini"),
            small_model=llm_config.get("small_model", "gpt-4o-mini"),
            base_url=llm_config.get("base_url"),  # 支持自定义 API 地址
        )
        
        # 使用 OpenAIGenericClient 支持各种 OpenAI 兼容 API
        llm_client = OpenAIGenericClient(config=llm_client_config)
        
        # 3. 创建 Embedder（也支持自定义 base_url）
        embedder = OpenAIEmbedder(
            config=OpenAIEmbedderConfig(
                api_key=api_key,
                embedding_model=llm_config.get("embedding_model", "text-embedding-3-small"),
                embedding_dim=llm_config.get("embedding_dim", 1536),
                base_url=llm_config.get("base_url"),  # 同样支持自定义
            )
        )
        
        # 4. 创建 Reranker（可选，提升检索精度）
        # 注意：OpenAIRerankerClient 使用 logprobs 进行相关性评分
        # 它会让 LLM 回答 "True/False"，然后用对数概率作为分数
        reranker = None
        reranker_config = self.config.get("reranker", {})
        if reranker_config.get("enabled", False):
            # 正确的初始化方式：只传 config，或传入 AsyncOpenAI 实例
            reranker_llm_config = LLMConfig(
                api_key=api_key,
                model=reranker_config.get("model", "gpt-4o-mini"),
                base_url=llm_config.get("base_url"),
            )
            reranker = OpenAIRerankerClient(config=reranker_llm_config)
            logger.info("Reranker enabled with model: " + reranker_llm_config.model)
        
        # 5. 初始化 Graphiti
        self.graphiti = Graphiti(
            graph_driver=driver,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=reranker  # 添加 Reranker
        )
        
        # 6. 初始化索引和约束
        await self.graphiti.build_indices_and_constraints()
        
        self._initialized = True
        logger.info(f"Graphiti initialized with {backend} backend")
    
    def _should_index_episode(
        self,
        content: str,
        episode_type: EpisodeType
    ) -> bool:
        """
        判断是否应该索引该 Episode
        
        对于对话类型，会评估内容价值
        """
        type_config = self.episode_type_config.get(episode_type.value, {})
        
        # diary 和 node 总是索引
        if episode_type in (EpisodeType.DIARY, EpisodeType.NODE):
            return True
        
        # conversation 需要评估价值
        if episode_type == EpisodeType.CONVERSATION:
            min_threshold = type_config.get("min_value_threshold", 0.3)
            
            # 简单启发式：内容长度、是否包含实体等
            value_score = self._estimate_content_value(content)
            
            if value_score < min_threshold:
                logger.debug(f"Skipping low-value conversation (score={value_score:.2f})")
                return False
        
        return True
    
    def _estimate_content_value(self, content: str) -> float:
        """
        估算内容价值（0-1）
        
        简单启发式：
        - 长度加分
        - 包含实体词加分
        - 纯闲聊减分
        """
        score = 0.5
        
        # 长度因素
        if len(content) > 200:
            score += 0.2
        elif len(content) < 50:
            score -= 0.2
        
        # 实体词检测（简单关键词）
        entity_keywords = ["项目", "技术", "学习", "开发", "计划", "目标", "完成", "问题"]
        entity_count = sum(1 for kw in entity_keywords if kw in content)
        score += min(entity_count * 0.1, 0.3)
        
        # 闲聊检测
        casual_patterns = ["哈哈", "嗯嗯", "好的", "知道了", "谢谢"]
        if any(p in content for p in casual_patterns) and len(content) < 100:
            score -= 0.3
        
        return max(0, min(1, score))
    
    async def add_episode(
        self,
        content: str,
        source: str,
        episode_type: EpisodeType = EpisodeType.CONVERSATION,
        timestamp: Optional[datetime] = None,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> Optional[str]:
        """
        将内容添加为 Graphiti Episode
        
        Args:
            content: 内容文本
            source: 来源标识 (如 "diary:2025-01-21", "conv:session_123:5")
            episode_type: Episode 类型
            timestamp: 事件发生时间
            user_id: 用户ID（用于 group_id 策略）
            project_id: 项目ID（用于 group_id 策略）
        
        Returns:
            Episode UUID，如果被过滤则返回 None
        """
        if not self._initialized:
            await self.initialize()
        
        # 检查是否应该索引
        if not self._should_index_episode(content, episode_type):
            return None
        
        # 获取 group_id
        group_id = self.group_id_strategy.get_group_id(user_id, project_id)
        
        reference_time = timestamp or datetime.now()
        
        episode = await self.graphiti.add_episode(
            name=source,
            episode_body=content,
            source_description=f"LifeBook {episode_type.value}: {source}",
            reference_time=reference_time,
            group_id=group_id
        )
        
        logger.debug(f"Added episode: {source} (type={episode_type.value}, group={group_id})")
        return episode.uuid
    
    async def search(
        self,
        query: str,
        num_results: int = 10,
        group_ids: Optional[List[str]] = None,
        include_edges: Optional[bool] = None,
        include_nodes: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """
        混合搜索（语义 + 关键词 + 图遍历）
        
        使用 SearchConfig 进行精细配置
        
        Args:
            query: 查询文本
            num_results: 返回结果数量
            group_ids: 限定搜索的分组
            include_edges: 是否包含边（关系），None 使用配置默认值
            include_nodes: 是否包含节点，None 使用配置默认值
        
        Returns:
            搜索结果列表
        """
        if not self._initialized:
            await self.initialize()
        
        # 使用配置默认值
        if include_edges is None:
            include_edges = self.retrieval_config.get("include_edges", True)
        if include_nodes is None:
            include_nodes = self.retrieval_config.get("include_nodes", True)
        
        # 构建 SearchConfig（Graphiti 的精细检索配置）
        # 完整参数参考 graphiti_core/search/search_config.py
        from graphiti_core.search.search_config import (
            EdgeSearchConfig, EdgeSearchMethod, EdgeReranker,
            NodeSearchConfig, NodeSearchMethod, NodeReranker,
        )
        
        search_cfg = self.config.get("search", {})
        
        # 边搜索配置
        edge_config = EdgeSearchConfig(
            search_methods=[
                EdgeSearchMethod.cosine_similarity,  # 语义向量
                EdgeSearchMethod.bm25,               # 关键词
            ],
            reranker=EdgeReranker.cross_encoder if self.config.get("reranker", {}).get("enabled") else EdgeReranker.rrf,
            sim_min_score=search_cfg.get("sim_min_score", 0.4),
            mmr_lambda=search_cfg.get("mmr_lambda", 0.5),
        )
        
        # 节点搜索配置
        node_config = NodeSearchConfig(
            search_methods=[
                NodeSearchMethod.cosine_similarity,
                NodeSearchMethod.bm25,
            ],
            reranker=NodeReranker.rrf,  # 节点用 RRF 融合即可
            sim_min_score=search_cfg.get("sim_min_score", 0.4),
        )
        
        search_config = SearchConfig(
            edge_config=edge_config if include_edges else None,
            node_config=node_config if include_nodes else None,
            limit=num_results,
            reranker_min_score=search_cfg.get("reranker_min_score", 0.3),
        )
        
        # 执行搜索
        results = await self.graphiti.search(
            query=query,
            num_results=num_results,
            group_ids=group_ids or [self.group_id_strategy.default]
        )
        
        # 转换为统一格式
        formatted = []
        for r in results:
            result_type = "edge" if hasattr(r, 'fact') else "node"
            
            # 根据配置过滤
            if result_type == "edge" and not include_edges:
                continue
            if result_type == "node" and not include_nodes:
                continue
            
            formatted.append({
                "uuid": r.uuid,
                "content": r.fact if hasattr(r, 'fact') else str(r),
                "score": getattr(r, 'score', 1.0),
                "source": getattr(r, 'source_description', ''),
                "valid_at": getattr(r, 'valid_at', None),
                "invalid_at": getattr(r, 'invalid_at', None),
                "type": result_type
            })
        
        return formatted
    
    def _setup_telemetry(self, config: dict):
        """
        初始化 OpenTelemetry 追踪
        
        参考: graphiti-main/examples/opentelemetry/
        """
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
            from opentelemetry.sdk.resources import Resource
            
            resource = Resource.create({"service.name": "lifebook-graphiti"})
            provider = TracerProvider(resource=resource)
            
            exporter_type = config.get("exporter", "stdout")
            if exporter_type == "stdout":
                exporter = ConsoleSpanExporter()
            elif exporter_type == "otlp":
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter(
                    endpoint=config.get("otlp_endpoint", "http://localhost:4317")
                )
            else:
                logger.warning(f"Unknown telemetry exporter: {exporter_type}")
                return
            
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer("graphiti-adapter")
            logger.info(f"Telemetry enabled with {exporter_type} exporter")
        except ImportError as e:
            logger.warning(f"Telemetry dependencies not installed: {e}")
        except Exception as e:
            logger.error(f"Failed to setup telemetry: {e}")
    
    async def temporal_query(
        self,
        entity_name: str,
        time_point: datetime,
        num_results: int = 30
    ) -> Dict[str, Any]:
        """
        时间点查询优化版：查询某实体在特定时间的状态
        
        基于 Graphiti 的 Bi-Temporal 模型：
        - valid_at: 事实生效时间
        - invalid_at: 事实失效时间
        
        优化策略：
        1. 分批检索，提前终止
        2. 缓存热门实体（未来可扩展）
        """
        if not self._initialized:
            await self.initialize()
        
        # 分批检索优化：每批 20 条，最多 5 批
        valid_facts = []
        batch_size = 20
        max_batches = 5
        
        for batch_idx in range(max_batches):
            if len(valid_facts) >= num_results:
                break
            
            # 搜索实体相关的边
            results = await self.graphiti.search(
                query=entity_name,
                num_results=batch_size
            )
            
            if not results:
                break
            
            # Bi-Temporal 过滤
            for r in results:
                valid_at = getattr(r, 'valid_at', None)
                invalid_at = getattr(r, 'invalid_at', None)
                
                # 事实必须在 time_point 之前生效
                if valid_at is None or valid_at > time_point:
                    continue
                # 事实在 time_point 时未失效
                if invalid_at is not None and invalid_at <= time_point:
                    continue
                
                valid_facts.append({
                    "fact": r.fact if hasattr(r, 'fact') else str(r),
                    "valid_from": valid_at.isoformat() if valid_at else None,
                    "valid_to": invalid_at.isoformat() if invalid_at else None,
                    "source": getattr(r, 'source_description', '')
                })
                
                if len(valid_facts) >= num_results:
                    break
        
        return {
            "entity": entity_name,
            "time_point": time_point.isoformat(),
            "facts_count": len(valid_facts),
            "facts": valid_facts
        }
    
    async def sync_from_markdown(self):
        """从 Markdown 文件全量同步到 Graphiti"""
        if not self._initialized:
            await self.initialize()
        
        synced_count = {"diary": 0, "node": 0}
        
        # 同步日记（高优先级）
        daily_dir = self.lifebook_path / "daily"
        if daily_dir.exists():
            for md_file in sorted(daily_dir.glob("*.md")):
                date_str = md_file.stem  # "2025-01-21"
                content = md_file.read_text(encoding="utf-8")
                
                try:
                    timestamp = datetime.strptime(date_str, "%Y-%m-%d")
                    await self.add_episode(
                        content=content,
                        source=f"diary:{date_str}",
                        episode_type=EpisodeType.DIARY,
                        timestamp=timestamp
                    )
                    synced_count["diary"] += 1
                except Exception as e:
                    logger.error(f"Failed to sync diary {md_file}: {e}")
        
        # 同步节点（中优先级）
        nodes_dir = self.lifebook_path / "nodes"
        if nodes_dir.exists():
            for md_file in nodes_dir.glob("*.md"):
                content = md_file.read_text(encoding="utf-8")
                try:
                    await self.add_episode(
                        content=content,
                        source=f"node:{md_file.stem}",
                        episode_type=EpisodeType.NODE
                    )
                    synced_count["node"] += 1
                except Exception as e:
                    logger.error(f"Failed to sync node {md_file}: {e}")
        
        logger.info(f"Synced {synced_count['diary']} diaries, {synced_count['node']} nodes")
        return synced_count
    
    async def close(self):
        """关闭连接"""
        if self.graphiti:
            await self.graphiti.close()


# 同步包装器（用于非异步上下文）
class GraphitiSyncAdapter:
    """同步版本的 Graphiti 适配器"""
    
    def __init__(self, config: dict, lifebook_path: str):
        self._async_adapter = GraphitiAdapter(config, lifebook_path)
        self._loop = None
    
    def _get_loop(self):
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop
    
    def initialize(self):
        return self._get_loop().run_until_complete(
            self._async_adapter.initialize()
        )
    
    def add_episode(
        self,
        content: str,
        source: str,
        episode_type: EpisodeType = EpisodeType.CONVERSATION,
        timestamp=None,
        user_id=None,
        project_id=None
    ):
        return self._get_loop().run_until_complete(
            self._async_adapter.add_episode(
                content, source, episode_type, timestamp, user_id, project_id
            )
        )
    
    def search(
        self,
        query: str,
        num_results: int = 10,
        group_ids=None,
        include_edges=None,
        include_nodes=None
    ):
        return self._get_loop().run_until_complete(
            self._async_adapter.search(
                query, num_results, group_ids, include_edges, include_nodes
            )
        )
    
    def temporal_query(self, entity_name: str, time_point: datetime, num_results: int = 30):
        return self._get_loop().run_until_complete(
            self._async_adapter.temporal_query(entity_name, time_point, num_results)
        )
    
    def sync_from_markdown(self):
        return self._get_loop().run_until_complete(
            self._async_adapter.sync_from_markdown()
        )
    
    def close(self):
        return self._get_loop().run_until_complete(
            self._async_adapter.close()
        )
```

### 1.5 新增工具

```python
# memory_agent/graphiti_tools.py

GRAPHITI_TOOLS = {
    "graphiti_search": {
        "name": "graphiti_search",
        "description": """使用 Graphiti 进行混合搜索（语义 + BM25 + 图遍历）。
        适合：
        - 查找相关记忆和事实
        - 探索实体之间的关系
        - 回答需要综合多条信息的问题""",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询"
                },
                "num_results": {
                    "type": "integer",
                    "default": 10,
                    "description": "返回结果数量"
                }
            },
            "required": ["query"]
        }
    },
    
    "graphiti_temporal": {
        "name": "graphiti_temporal",
        "description": """查询某个时间点的知识状态。
        利用 Graphiti 的 Bi-Temporal 模型，可以回答：
        - "2025年3月时，项目是什么状态？"
        - "那时候主人在学什么？" """,
        "parameters": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "实体名称"
                },
                "time_point": {
                    "type": "string",
                    "description": "时间点 (YYYY-MM-DD 或 YYYY-MM)"
                }
            },
            "required": ["entity", "time_point"]
        }
    },
    
    "graphiti_add": {
        "name": "graphiti_add",
        "description": "添加新的知识片段到图谱",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "知识内容"
                },
                "source": {
                    "type": "string",
                    "description": "来源标识"
                }
            },
            "required": ["content"]
        }
    }
}
```

---

## 📝 Phase 2: 原始对话保留机制 (3-5天)

### 2.1 设计原则

1. **完整保留**：原始对话一字不落保存
2. **可靠匹配**：准确识别同一对话窗口的续写
3. **按需生成**：日记由原始对话生成，可重试
4. **实时索引**：对话同时进入 Graphiti 供检索

### 2.2 会话匹配机制（务实版）

**核心问题**：OpenAI API 标准中**没有 session_id 字段**，Cherry Studio、LobeChat 等客户端发送的都是标准格式，我们无法依赖客户端传递会话ID。

**可用信息分析**：

| 信息源 | 可靠性 | 说明 |
|--------|-------|------|
| 请求时间 | ✅ 高 | 服务端可获取 |
| 消息内容/结构 | ⚠️ 中 | 用户可能编辑历史消息 |
| HTTP Headers | ⚠️ 中 | 不同客户端差异大 |
| 用户 API Key | ✅ 高 | 可区分不同用户 |

**务实匹配策略**：采用「时间窗口 + 消息前缀」双重验证

```python
# memory_store/conversation_matcher.py

import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """匹配结果"""
    file_path: Path
    is_new: bool
    confidence: float  # 匹配置信度 0-1
    match_method: str  # 匹配方法
    

class ConversationMatcher:
    """
    务实的对话匹配器
    
    核心策略：时间窗口 + 消息前缀匹配
    
    工作原理：
    1. 检查最近 N 分钟内是否有活跃会话
    2. 如果有，验证新消息是否是旧消息的延续（前缀匹配）
    3. 匹配成功则追加，否则创建新会话
    
    为什么不用 client_session_id：
    - OpenAI API 标准没有这个字段
    - Cherry Studio、LobeChat 等客户端不传递
    - 即使自定义扩展，也不能保证所有客户端都支持
    """
    
    def __init__(
        self,
        conversations_dir: Path,
        session_timeout_minutes: int = 30,  # 会话超时时间
        prefix_match_threshold: float = 0.7  # 前缀匹配阈值
    ):
        self.dir = conversations_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        self.prefix_threshold = prefix_match_threshold
        
        # 内存缓存：记住最近活跃的会话
        # key: 用户标识（API Key hash 或 "default"）
        # value: (file_path, last_messages_hash, last_update_time)
        self._active_sessions: Dict[str, tuple] = {}
    
    def match(
        self,
        messages: List[Dict],
        user_key: str = "default"
    ) -> MatchResult:
        """
        匹配对话文件
        
        Args:
            messages: 消息列表
            user_key: 用户标识（API Key 或其他唯一标识）
        
        Returns:
            MatchResult
        """
        user_hash = hashlib.md5(user_key.encode()).hexdigest()[:8]
        
        # 策略1：检查内存中的活跃会话
        if user_hash in self._active_sessions:
            file_path, last_hash, last_time = self._active_sessions[user_hash]
            
            # 检查是否超时
            if datetime.now() - last_time < self.session_timeout:
                # 检查是否是续写（新消息包含旧消息作为前缀）
                if file_path.exists():
                    if self._is_continuation(file_path, messages):
                        self._update_active_session(user_hash, file_path, messages)
                        return MatchResult(
                            file_path=file_path,
                            is_new=False,
                            confidence=0.9,
                            match_method="active_session_continuation"
                        )
        
        # 策略2：扫描最近的文件，查找可能的续写
        result = self._find_recent_continuation(messages, user_hash)
        if result:
            self._update_active_session(user_hash, result.file_path, messages)
            return result
        
        # 策略3：创建新会话
        new_session = self._create_new_session(user_hash)
        self._update_active_session(user_hash, new_session.file_path, messages)
        return new_session
    
    def _is_continuation(self, conv_file: Path, new_messages: List[Dict]) -> bool:
        """
        判断新消息是否是已有对话的延续
        
        判断条件：
        1. 新消息数量 > 已有轮次数量
        2. 前 N 条消息内容高度相似
        """
        try:
            existing_turns = self._read_turns(conv_file)
            if not existing_turns:
                return False
            
            # 提取用户消息进行比较
            new_user_msgs = [
                m.get("content", "")[:200]  # 只比较前200字符
                for m in new_messages
                if m.get("role") == "user"
            ]
            
            existing_user_msgs = [
                t.get("user", "")[:200]
                for t in existing_turns
            ]
            
            if not existing_user_msgs or not new_user_msgs:
                return False
            
            # 新消息数量必须 >= 已有数量（续写逻辑）
            if len(new_user_msgs) < len(existing_user_msgs):
                return False
            
            # 检查前缀匹配：已有消息是否都能在新消息中找到
            match_count = 0
            for i, existing in enumerate(existing_user_msgs):
                if i < len(new_user_msgs):
                    similarity = self._compute_similarity(existing, new_user_msgs[i])
                    if similarity >= self.prefix_threshold:
                        match_count += 1
            
            # 80% 以上的已有消息都匹配，认为是续写
            match_ratio = match_count / len(existing_user_msgs)
            return match_ratio >= 0.8
            
        except Exception as e:
            logger.warning(f"检查续写时出错: {e}")
            return False
    
    def _compute_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的相似度（基于字符级 Jaccard）"""
        if not text1 or not text2:
            return 0.0
        
        # 去除空白符后比较
        text1 = text1.strip()
        text2 = text2.strip()
        
        # 完全相同
        if text1 == text2:
            return 1.0
        
        # 一个是另一个的前缀
        if text1.startswith(text2) or text2.startswith(text1):
            return 0.95
        
        # 字符级 Jaccard 相似度
        set1 = set(text1)
        set2 = set(text2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
    
    def _find_recent_continuation(
        self,
        messages: List[Dict],
        user_hash: str
    ) -> Optional[MatchResult]:
        """在最近的文件中查找可能的续写"""
        # 只查找最近2小时内、属于该用户的文件
        cutoff = datetime.now() - timedelta(hours=2)
        
        for f in sorted(self.dir.glob(f"*_{user_hash}.jsonl"),
                        key=lambda x: x.stat().st_mtime,
                        reverse=True):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    break  # 文件太旧了
                
                if self._is_continuation(f, messages):
                    return MatchResult(
                        file_path=f,
                        is_new=False,
                        confidence=0.85,
                        match_method="file_scan_continuation"
                    )
            except Exception:
                continue
        
        return None
    
    def _create_new_session(self, user_hash: str) -> MatchResult:
        """创建新会话文件"""
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H%M%S")
        file_path = self.dir / f"{timestamp}_{user_hash}.jsonl"
        
        # 避免文件名冲突
        counter = 1
        while file_path.exists():
            file_path = self.dir / f"{timestamp}_{counter}_{user_hash}.jsonl"
            counter += 1
        
        return MatchResult(
            file_path=file_path,
            is_new=True,
            confidence=1.0,
            match_method="new"
        )
    
    def _update_active_session(
        self,
        user_hash: str,
        file_path: Path,
        messages: List[Dict]
    ):
        """更新活跃会话缓存"""
        # 计算消息哈希（用于快速比较）
        msg_summary = "|".join([
            f"{m.get('role', '')}:{len(m.get('content', ''))}"
            for m in messages[:10]
        ])
        msg_hash = hashlib.md5(msg_summary.encode()).hexdigest()[:16]
        
        self._active_sessions[user_hash] = (file_path, msg_hash, datetime.now())
    
    def _read_turns(self, conv_file: Path) -> List[Dict]:
        """读取所有对话轮次"""
        turns = []
        try:
            with open(conv_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data.get("type") == "turn":
                            turns.append(data)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return turns
    
    def cleanup_expired_cache(self):
        """清理过期的内存缓存（可定期调用）"""
        now = datetime.now()
        expired = []
        
        for user_hash, (_, _, last_time) in self._active_sessions.items():
            if now - last_time > self.session_timeout * 2:
                expired.append(user_hash)
        
        for key in expired:
            del self._active_sessions[key]
```

### 2.2.1 匹配策略详解

**为什么这个方案可靠**：

| 场景 | 行为 | 结果 |
|------|------|------|
| 用户在同一窗口续写 | 新消息包含旧消息前缀 | ✅ 正确追加 |
| 用户开新窗口 | 消息不匹配 | ✅ 创建新会话 |
| 用户编辑历史消息 | 相似度下降但仍在阈值内 | ⚠️ 可能仍追加（可接受） |
| 用户完全重写消息 | 相似度低于阈值 | ✅ 创建新会话 |
| 超时后再续写 | 超过30分钟 | ✅ 创建新会话 |
| 不同用户同时对话 | API Key 不同 | ✅ 隔离记录 |

**配置参数**：

```jsonc
// config.jsonc 中新增
{
    "conversation_logger": {
        "enabled": true,
        "session_timeout_minutes": 30,     // 会话超时时间
        "prefix_match_threshold": 0.7,     // 前缀匹配阈值
        "max_turns_per_file": 100,         // 单文件最大轮次
        "index_to_graphiti": true          // 是否同步到 Graphiti
    }
}
```

### 2.3 对话记录器

```python
# memory_store/conversation_logger.py

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from .conversation_matcher import ConversationMatcher, MatchResult
import logging

logger = logging.getLogger(__name__)


class ConversationLogger:
    """原始对话记录器"""
    
    def __init__(
        self,
        lifebook_path: str,
        graphiti_adapter: Optional[Any] = None
    ):
        self.lifebook_path = Path(lifebook_path)
        self.conv_dir = self.lifebook_path / "conversations"
        self.conv_dir.mkdir(parents=True, exist_ok=True)
        
        self.matcher = ConversationMatcher(self.conv_dir)
        self.graphiti = graphiti_adapter
        
        # 当前会话状态
        self._current_file: Optional[Path] = None
        self._current_turn: int = 0
    
    def log_turn(
        self,
        messages: List[Dict],
        model: str,
        response: str,
        client_session_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Path:
        """
        记录一轮对话
        
        Args:
            messages: 完整消息历史
            model: 使用的模型
            response: AI回复
            client_session_id: 客户端会话ID（如果提供）
            metadata: 额外元数据
        
        Returns:
            对话文件路径
        """
        # 1. 匹配或创建会话
        match_result = self.matcher.match(messages, client_session_id)
        conv_file = match_result.file_path
        
        if match_result.is_new:
            self._init_new_file(conv_file, messages, model, client_session_id)
            self._current_turn = 0
        
        logger.debug(
            f"Session matched: {conv_file.name} "
            f"(method={match_result.match_method}, "
            f"confidence={match_result.confidence:.2f})"
        )
        
        # 2. 提取当前轮的用户消息
        current_user = self._extract_last_user_message(messages)
        
        if not current_user:
            return conv_file
        
        # 3. 追加对话记录
        self._current_turn += 1
        turn_record = {
            "type": "turn",
            "turn_id": self._current_turn,
            "timestamp": datetime.now().isoformat(),
            "user": current_user,
            "assistant": response,
            "model": model
        }
        
        if metadata:
            turn_record["metadata"] = metadata
        
        with open(conv_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn_record, ensure_ascii=False) + "\n")
        
        # 4. 更新 footer
        self._update_footer(conv_file)
        
        # 5. 异步索引到 Graphiti（如果启用）
        if self.graphiti:
            self._index_to_graphiti(current_user, response, conv_file)
        
        self._current_file = conv_file
        return conv_file
    
    def _init_new_file(
        self,
        conv_file: Path,
        messages: List[Dict],
        model: str,
        client_session_id: Optional[str] = None
    ):
        """初始化新的对话文件"""
        struct_fingerprint = self.matcher._compute_structure_fingerprint(messages)
        
        header = {
            "type": "header",
            "session_id": conv_file.stem,
            "start_time": datetime.now().isoformat(),
            "model": model,
            "structure_fingerprint": struct_fingerprint
        }
        
        if client_session_id:
            header["client_session_id"] = client_session_id
        
        # 提取 system prompt 预览（如果有）
        for msg in messages:
            if msg.get("role") == "system":
                header["system_prompt_preview"] = msg.get("content", "")[:200]
                break
        
        with open(conv_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(header, ensure_ascii=False) + "\n")
    
    def _extract_last_user_message(self, messages: List[Dict]) -> Optional[str]:
        """提取最后一条用户消息"""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return msg.get("content")
        return None
    
    def _update_footer(self, conv_file: Path):
        """更新文件尾部元数据"""
        try:
            with open(conv_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # 移除旧的 footer
            if lines and '"type": "footer"' in lines[-1]:
                lines = lines[:-1]
            
            # 统计
            turn_count = sum(1 for l in lines if '"type": "turn"' in l)
            
            footer = {
                "type": "footer",
                "end_time": datetime.now().isoformat(),
                "turn_count": turn_count,
                "updated_at": datetime.now().isoformat()
            }
            
            lines.append(json.dumps(footer, ensure_ascii=False) + "\n")
            
            with open(conv_file, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            logger.error(f"Failed to update footer: {e}")
    
    def _index_to_graphiti(self, user_msg: str, assistant_msg: str, conv_file: Path):
        """将对话索引到 Graphiti"""
        try:
            episode_content = f"用户: {user_msg}\n灰魂: {assistant_msg}"
            source = f"conv:{conv_file.stem}:{self._current_turn}"
            
            # 同步调用（如果是同步适配器）
            if hasattr(self.graphiti, 'add_episode'):
                self.graphiti.add_episode(
                    content=episode_content,
                    source=source,
                    timestamp=datetime.now()
                )
        except Exception as e:
            logger.error(f"Failed to index to Graphiti: {e}")
    
    def get_conversation(self, session_id: str) -> Optional[Dict]:
        """读取完整对话"""
        conv_file = self.conv_dir / f"{session_id}.jsonl"
        
        if not conv_file.exists():
            # 尝试模糊匹配
            for f in self.conv_dir.glob(f"{session_id}*.jsonl"):
                conv_file = f
                break
            else:
                return None
        
        result = {
            "header": None,
            "turns": [],
            "footer": None
        }
        
        with open(conv_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    record_type = record.get("type")
                    
                    if record_type == "header":
                        result["header"] = record
                    elif record_type == "turn":
                        result["turns"].append(record)
                    elif record_type == "footer":
                        result["footer"] = record
                except json.JSONDecodeError:
                    continue
        
        return result
    
    def list_conversations(self, days: int = 7) -> List[Dict]:
        """列出最近的对话"""
        from datetime import timedelta
        
        cutoff = datetime.now() - timedelta(days=days)
        conversations = []
        
        for f in sorted(self.conv_dir.glob("*.jsonl"), reverse=True):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime.date() < cutoff.date():
                    continue
                
                conv = self.get_conversation(f.stem)
                if conv and conv["header"]:
                    info = {
                        "session_id": f.stem,
                        "start_time": conv["header"].get("start_time"),
                        "end_time": conv["footer"].get("end_time") if conv["footer"] else None,
                        "turn_count": len(conv["turns"]),
                        "model": conv["header"].get("model")
                    }
                    
                    if conv["turns"]:
                        info["first_message"] = conv["turns"][0]["user"][:100]
                    
                    conversations.append(info)
            except Exception:
                continue
        
        return conversations
```

### 2.4 存储占用估算

```
假设：
- 日均对话轮次：50轮
- 每轮用户消息：200字符
- 每轮AI回复：500字符
- JSON开销：~100字符/轮

每日存储：50 × (200 + 500 + 100) = 40KB
每年存储：40KB × 365 = 14.6MB

结论：即使保留5年原始对话，也只需约73MB，完全可接受。
```

---

## 🔍 Phase 3: 检索策略选择 (3-4天)

### 3.1 MemR3 核心思想

**传统检索的问题**：
```
用户问题: "主人领养 Buddy 多久了？"

传统 Retrieve-then-Answer:
1. 检索: 找到 "2024年12月领养了Buddy"
2. 回答: "主人在2024年12月领养了Buddy" ← 没有回答"多久"！

MemR3 迭代检索:
1. 检索: 找到 "2024年12月领养了Buddy"
2. 反思: 知道领养日期，但缺少"现在时间"来计算时长
3. 再检索: 查询当前日期相关信息
4. 回答: "主人领养Buddy已经3个月了" ✓
```

### 3.2 Evidence-Gap 迭代检索器

```python
# memory_agent/iterative_retriever.py

"""
借鉴 MemR3 的 Evidence-Gap 闭环检索机制

核心思想：
1. Retrieve - 基于当前查询检索
2. Reflect - 评估证据是否充分，识别信息缺口 (Gap)
3. Refine - 根据 Gap 生成新的检索查询
4. 重复直到证据充分或达到最大迭代次数

参考: MemR3 Pipeline (https://github.com/...)
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)


class RetrievalAction(Enum):
    """检索动作"""
    RETRIEVE = "retrieve"   # 继续检索
    ANSWER = "answer"       # 可以回答了
    ABORT = "abort"         # 放弃（无法获取更多信息）


@dataclass
class EvidenceGapState:
    """Evidence-Gap 状态追踪器"""
    query: str                              # 原始查询
    evidence: List[Dict] = field(default_factory=list)  # 已收集的证据
    gaps: List[str] = field(default_factory=list)       # 信息缺口
    refined_queries: List[str] = field(default_factory=list)  # 优化后的查询
    iteration: int = 0                      # 当前迭代次数
    
    def add_evidence(self, results: List[Dict]):
        """添加新证据，去重"""
        existing_uuids = {e.get("uuid") for e in self.evidence}
        for r in results:
            if r.get("uuid") not in existing_uuids:
                self.evidence.append(r)
    
    def get_evidence_summary(self) -> str:
        """获取证据摘要"""
        if not self.evidence:
            return "暂无相关记忆"
        
        summary = []
        for e in self.evidence[:10]:  # 限制长度
            content = e.get("content", "")[:200]
            source = e.get("source", "unknown")
            summary.append(f"- [{source}] {content}")
        
        return "\n".join(summary)


class IterativeRetriever:
    """
    MemR3 风格的迭代检索器
    
    实现 Retrieve → Reflect → Refine 闭环
    """
    
    def __init__(
        self,
        graphiti_adapter,
        llm_client=None,
        max_iterations: int = 3,
        min_evidence_count: int = 2
    ):
        self.graphiti = graphiti_adapter
        self.llm = llm_client
        self.max_iterations = max_iterations
        self.min_evidence_count = min_evidence_count
    
    async def retrieve(
        self,
        query: str,
        context: str = ""
    ) -> Dict[str, Any]:
        """
        迭代检索主入口
        
        Args:
            query: 用户查询
            context: 额外上下文（如对话历史）
        
        Returns:
            {
                "evidence": [...],      # 收集的证据
                "iterations": int,      # 迭代次数
                "gaps_resolved": [...], # 已解决的缺口
                "final_action": str     # 最终动作
            }
        """
        state = EvidenceGapState(query=query)
        
        while state.iteration < self.max_iterations:
            state.iteration += 1
            logger.info(f"Iteration {state.iteration}: query='{query}'")
            
            # 1. Retrieve - 执行检索
            current_query = state.refined_queries[-1] if state.refined_queries else query
            results = await self._retrieve_step(current_query)
            state.add_evidence(results)
            
            # 2. Reflect - 评估证据是否充分
            action, gaps = await self._reflect_step(state, context)
            
            if action == RetrievalAction.ANSWER:
                logger.info(f"Evidence sufficient after {state.iteration} iterations")
                break
            
            if action == RetrievalAction.ABORT:
                logger.warning("Retrieval aborted - no more information available")
                break
            
            # 3. Refine - 根据 Gap 生成新查询
            if gaps:
                state.gaps.extend(gaps)
                refined = await self._refine_step(query, gaps, state.evidence)
                if refined and refined not in state.refined_queries:
                    state.refined_queries.append(refined)
                else:
                    # 无法生成新查询，停止
                    break
        
        return {
            "evidence": state.evidence,
            "evidence_summary": state.get_evidence_summary(),
            "iterations": state.iteration,
            "gaps": state.gaps,
            "refined_queries": state.refined_queries,
            "final_action": action.value if action else "complete"
        }
    
    async def _retrieve_step(self, query: str, num_results: int = 10) -> List[Dict]:
        """检索步骤"""
        try:
            results = await self.graphiti.search(query, num_results=num_results)
            return results
        except Exception as e:
            logger.error(f"Retrieve failed: {e}")
            return []
    
    async def _reflect_step(
        self,
        state: EvidenceGapState,
        context: str
    ) -> tuple[RetrievalAction, List[str]]:
        """
        反思步骤：评估证据是否充分，识别信息缺口
        
        如果没有 LLM，使用启发式规则
        如果有 LLM，让 LLM 判断
        """
        # 基本检查：证据数量
        if len(state.evidence) < self.min_evidence_count:
            return RetrievalAction.RETRIEVE, ["需要更多相关信息"]
        
        # 如果有 LLM，使用 LLM 判断
        if self.llm:
            return await self._reflect_with_llm(state, context)
        
        # 没有 LLM，使用启发式规则
        return self._reflect_heuristic(state)
    
    def _reflect_heuristic(self, state: EvidenceGapState) -> tuple[RetrievalAction, List[str]]:
        """启发式反思（无 LLM 时使用）"""
        query = state.query.lower()
        evidence_text = " ".join([e.get("content", "") for e in state.evidence]).lower()
        
        gaps = []
        
        # 检查时间相关问题
        time_patterns = ["多久", "多长时间", "什么时候开始", "持续"]
        if any(p in query for p in time_patterns):
            # 需要有时间信息
            time_found = bool(re.search(r"\d{4}[-年/]\d{1,2}", evidence_text))
            if not time_found:
                gaps.append("缺少时间信息")
        
        # 检查比较问题
        compare_patterns = ["比较", "对比", "区别", "和.*哪个"]
        if any(re.search(p, query) for p in compare_patterns):
            # 需要有多个实体的信息
            if len(state.evidence) < 4:
                gaps.append("需要更多对比信息")
        
        # 检查因果问题
        causal_patterns = ["为什么", "原因", "怎么会"]
        if any(p in query for p in causal_patterns):
            # 检查是否有解释性内容
            explanation_words = ["因为", "由于", "所以", "导致", "原因"]
            if not any(w in evidence_text for w in explanation_words):
                gaps.append("缺少原因解释")
        
        if gaps and state.iteration < self.max_iterations:
            return RetrievalAction.RETRIEVE, gaps
        
        return RetrievalAction.ANSWER, []
    
    async def _reflect_with_llm(
        self,
        state: EvidenceGapState,
        context: str
    ) -> tuple[RetrievalAction, List[str]]:
        """使用 LLM 进行反思"""
        prompt = f"""你是一个检索评估助手。请判断当前收集的证据是否足以回答用户问题。

用户问题: {state.query}

已收集的证据:
{state.get_evidence_summary()}

请分析:
1. 这些证据是否足以完整回答问题？
2. 如果不足，还缺少什么信息？

请用以下格式回答:
SUFFICIENT: yes/no
GAPS: [如果不足，列出缺少的信息，用分号分隔]"""
        
        try:
            response = await self.llm.generate(prompt)
            
            # 解析响应
            if "SUFFICIENT: yes" in response.lower():
                return RetrievalAction.ANSWER, []
            
            gaps = []
            if "GAPS:" in response:
                gaps_part = response.split("GAPS:")[-1].strip()
                gaps = [g.strip() for g in gaps_part.split(";") if g.strip()]
            
            return RetrievalAction.RETRIEVE, gaps
        except Exception as e:
            logger.error(f"LLM reflect failed: {e}")
            return self._reflect_heuristic(state)
    
    async def _refine_step(
        self,
        original_query: str,
        gaps: List[str],
        evidence: List[Dict]
    ) -> Optional[str]:
        """
        优化步骤：根据 Gap 生成新的检索查询
        """
        if not gaps:
            return None
        
        # 如果有 LLM，使用 LLM 生成
        if self.llm:
            return await self._refine_with_llm(original_query, gaps, evidence)
        
        # 没有 LLM，简单拼接
        gap = gaps[0]
        
        # 提取原查询中的关键实体
        # 简单实现：取前15个字符作为实体
        entity = original_query[:15].strip()
        
        return f"{entity} {gap}"
    
    async def _refine_with_llm(
        self,
        original_query: str,
        gaps: List[str],
        evidence: List[Dict]
    ) -> Optional[str]:
        """使用 LLM 生成优化查询"""
        prompt = f"""你是一个查询优化助手。用户的原始问题无法完全回答，因为缺少一些信息。

原始问题: {original_query}
缺少的信息: {', '.join(gaps)}

请生成一个新的检索查询，帮助找到缺少的信息。
只输出查询文本，不要其他内容。"""
        
        try:
            response = await self.llm.generate(prompt)
            return response.strip()
        except Exception as e:
            logger.error(f"LLM refine failed: {e}")
            return None


class RetrievalRouter:
    """
    检索路由器（升级版）
    
    结合：
    1. 复杂度分类 - 决定使用简单检索还是迭代检索
    2. MemR3 迭代检索 - 处理需要多步推理的查询
    3. deepseek-reasoner - 极复杂查询的后备
    """
    
    def __init__(
        self,
        graphiti_adapter,
        llm_client=None,
        deepseek_agent=None,
        config: dict = None
    ):
        self.graphiti = graphiti_adapter
        self.llm = llm_client
        self.agent = deepseek_agent
        self.config = config or {}
        
        # 创建迭代检索器
        self.iterative_retriever = IterativeRetriever(
            graphiti_adapter=graphiti_adapter,
            llm_client=llm_client,
            max_iterations=self.config.get("max_iterations", 3)
        )
    
    async def retrieve(
        self,
        query: str,
        context: str = "",
        force_strategy: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        智能检索入口
        
        Args:
            query: 用户查询
            context: 上下文
            force_strategy: 强制策略 ("simple" | "iterative" | "agent")
        
        Returns:
            检索结果字典
        """
        # 强制策略
        if force_strategy == "simple":
            return await self._simple_retrieve(query)
        elif force_strategy == "iterative":
            return await self.iterative_retriever.retrieve(query, context)
        elif force_strategy == "agent" and self.agent:
            return {"evidence_summary": self.agent.retrieve(query, context)}
        
        # 自动判断复杂度
        complexity = self._classify_complexity(query)
        
        if complexity == "simple":
            return await self._simple_retrieve(query)
        
        elif complexity == "medium":
            # 中等复杂度：使用迭代检索
            result = await self.iterative_retriever.retrieve(query, context)
            
            # 如果迭代检索不充分且有 agent，使用 agent
            if len(result.get("evidence", [])) < 2 and self.agent:
                agent_result = self.agent.retrieve(query, context)
                result["agent_supplement"] = agent_result
            
            return result
        
        else:  # complex
            # 复杂查询：优先使用迭代检索
            result = await self.iterative_retriever.retrieve(query, context)
            
            # 如果仍有未解决的 gaps，考虑使用 agent
            if result.get("gaps") and self.agent:
                agent_result = self.agent.retrieve(query, context)
                result["agent_supplement"] = agent_result
            
            return result
    
    async def _simple_retrieve(self, query: str, num_results: int = 10) -> Dict[str, Any]:
        """简单检索（单次）"""
        try:
            results = await self.graphiti.search(query, num_results=num_results)
            
            summary = "## 📚 相关记忆\n\n"
            for r in results:
                content = r.get("content", "")
                source = r.get("source", "")
                if content:
                    summary += f"- [{source}] {content[:300]}\n"
            
            return {
                "evidence": results,
                "evidence_summary": summary,
                "iterations": 1,
                "strategy": "simple"
            }
        except Exception as e:
            logger.error(f"Simple retrieve failed: {e}")
            return {
                "evidence": [],
                "evidence_summary": f"检索失败: {e}",
                "iterations": 0,
                "strategy": "simple"
            }
    
    def _classify_complexity(self, query: str) -> str:
        """分类查询复杂度"""
        # 复杂指标
        complex_patterns = [
            r"(为什么|怎么|如何)",           # 因果/方法
            r"(比较|对比|区别)",             # 比较
            r"(和|以及|还有).*什么",         # 多部分
            r"(变化|发展|演化|历史)",        # 时序演化
            r"(关系|联系|相关)",             # 深层关系
            r"(总结|分析|评价)",             # 综合分析
            r"(多久|多长时间)",              # 时间计算
        ]
        
        # 简单指标
        simple_patterns = [
            r"^.{0,15}是(谁|什么)",          # "xxx是谁/什么"
            r"^\d{4}[-年]?\d{0,2}",          # 日期开头
            r"^(有没有|是否|能不能)",        # 是非问题
            r"^(查|搜|找).{0,10}$",          # 短查询
        ]
        
        # 检查复杂模式
        for pattern in complex_patterns:
            if re.search(pattern, query):
                return "complex"
        
        # 检查简单模式
        for pattern in simple_patterns:
            if re.search(pattern, query):
                return "simple"
        
        # 按长度判断
        if len(query) < 15:
            return "simple"
        elif len(query) > 50:
            return "complex"
        
        return "medium"
    
    def format_result(self, result: Dict[str, Any]) -> str:
        """格式化结果为字符串（用于注入到上下文）"""
        output = result.get("evidence_summary", "")
        
        if result.get("iterations", 1) > 1:
            output += f"\n\n*（经过 {result['iterations']} 轮迭代检索）*"
        
        if result.get("agent_supplement"):
            output += f"\n\n### 深度分析\n{result['agent_supplement']}"
        
        return output
```

### 3.3 配置选项

```jsonc
// config.jsonc 中的检索配置
{
    "graphiti": {
        "retrieval": {
            "strategy": "iterative",  // "simple" | "iterative" | "auto"
            "max_iterations": 3,      // 迭代检索最大轮次
            "min_evidence_count": 2,  // 最少证据数量
            "default_limit": 10,      // 每次检索结果数
            "include_edges": true,    // 包含关系边
            "include_nodes": true,    // 包含实体节点
            
            // 复杂度分类阈值
            "complexity": {
                "simple_max_length": 15,
                "complex_min_length": 50,
                "complex_patterns": ["为什么", "怎么", "比较", "多久"]
            },
            
            // Agent 后备（极复杂查询）
            "agent_fallback": {
                "enabled": true,
                "model": "deepseek-reasoner",
                "trigger_on_gaps": true  // 当有未解决的 gaps 时触发
            }
        }
    }
}
```

### 3.4 使用示例

```python
# 初始化
router = RetrievalRouter(
    graphiti_adapter=graphiti,
    llm_client=llm,  # 可选，用于更智能的反思
    config=config["graphiti"]["retrieval"]
)

# 简单查询 - 单次检索
result = await router.retrieve("灰魂是谁？")
# → iterations: 1, strategy: simple

# 中等查询 - 可能迭代
result = await router.retrieve("主人最近在学什么技术？")
# → iterations: 2, 先找"主人学习"，发现需要"最近时间"，再检索

# 复杂查询 - 多轮迭代
result = await router.retrieve("主人领养 Buddy 多久了？")
# → iterations: 3
#   1. 检索"主人 Buddy 领养" → 找到领养日期
#   2. 反思：缺少当前日期计算时长 → 检索日期相关
#   3. 综合计算时长
```

---

## ⚡ Phase 4: 性能优化 (1-2天)

### 4.1 缓存机制

```python
# memory_store/retrieval_cache.py

from functools import lru_cache
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict
import json


class RetrievalCache:
    """检索结果缓存"""
    
    def __init__(self, ttl_seconds: int = 300):  # 5分钟过期
        self.ttl = timedelta(seconds=ttl_seconds)
        self._cache: Dict[str, tuple] = {}  # key -> (result, timestamp)
    
    def _make_key(self, query: str) -> str:
        """生成缓存键"""
        normalized = query.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def get(self, query: str) -> Optional[str]:
        """获取缓存结果"""
        key = self._make_key(query)
        
        if key in self._cache:
            result, timestamp = self._cache[key]
            if datetime.now() - timestamp < self.ttl:
                return result
            else:
                del self._cache[key]
        
        return None
    
    def set(self, query: str, result: str):
        """设置缓存"""
        key = self._make_key(query)
        self._cache[key] = (result, datetime.now())
    
    def clear(self):
        """清空缓存"""
        self._cache.clear()
```

### 4.2 异步预热

```python
# 启动时预热常见查询
async def warmup_cache(graphiti: GraphitiAdapter, cache: RetrievalCache):
    common_queries = [
        "主人",
        "灰魂",
        "LifeBook",
        "最近的项目"
    ]
    
    for query in common_queries:
        try:
            results = await graphiti.search(query, num_results=5)
            if results:
                cache.set(query, json.dumps(results))
        except Exception:
            pass
```

### 4.3 日记生成器

日记生成器复用现有配置文件中的提示词（`pending.consolidate_prompt`、`pending.merge_prompt`）：

```python
# memory_store/diary_generator.py

"""
日记生成器 - 从原始对话生成每日日记
复用 config.jsonc 中已有的提示词配置
"""

from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any
import json
import logging

logger = logging.getLogger(__name__)


class DiaryGenerator:
    """
    从原始对话生成每日日记
    
    使用现有配置：
    - pending.consolidate_prompt: 整合摘要为日记
    - pending.merge_prompt: 追加新内容到现有日记
    """
    
    def __init__(
        self,
        lifebook_path: str,
        config: dict,
        llm_client: Any = None,
        graphiti_adapter: Any = None
    ):
        self.lifebook_path = Path(lifebook_path)
        self.conv_dir = self.lifebook_path / "conversations"
        self.daily_dir = self.lifebook_path / "daily"
        self.pending_dir = self.lifebook_path / "pending"
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        
        # 从 config.jsonc 读取现有提示词
        pending_config = config.get("pending", {})
        self.consolidate_prompt = pending_config.get("consolidate_prompt", "")
        self.merge_prompt = pending_config.get("merge_prompt", "")
        
        self.llm = llm_client
        self.graphiti = graphiti_adapter
    
    async def generate_for_date(
        self,
        target_date: date,
        force_regenerate: bool = False
    ) -> Optional[Path]:
        """
        为指定日期生成日记
        
        优先使用 pending 目录下的摘要，如果没有则从 conversations 提取
        """
        date_str = target_date.strftime("%Y-%m-%d")
        diary_path = self.daily_dir / f"{date_str}.md"
        
        # 检查是否已存在
        if diary_path.exists() and not force_regenerate:
            logger.info(f"Diary already exists: {diary_path}")
            return diary_path
        
        # 1. 优先检查 pending 目录的摘要
        pending_content = self._collect_pending_summaries(target_date)
        
        # 2. 如果没有 pending 摘要，从 conversations 提取
        if not pending_content:
            conversations = self._collect_conversations(target_date)
            if not conversations:
                logger.info(f"No content found for {date_str}")
                return None
            pending_content = self._format_conversations_as_summary(conversations)
        
        # 3. 检查是否已有日记需要追加
        existing_diary = None
        if diary_path.exists():
            existing_diary = diary_path.read_text(encoding="utf-8")
        
        # 4. 使用 LLM 生成/追加日记
        if self.llm:
            diary_content = await self._generate_with_llm(
                pending_content, existing_diary, date_str
            )
        else:
            diary_content = self._generate_simple(pending_content, date_str)
        
        if not diary_content:
            return None
        
        # 5. 保存
        with open(diary_path, "w", encoding="utf-8") as f:
            f.write(diary_content)
        
        logger.info(f"Generated diary: {diary_path}")
        
        # 6. 同步到 Graphiti
        if self.graphiti:
            await self._sync_to_graphiti(diary_content, date_str, target_date)
        
        return diary_path
    
    def _collect_pending_summaries(self, target_date: date) -> str:
        """收集 pending 目录下的摘要"""
        date_str = target_date.strftime("%Y-%m-%d")
        summaries = []
        
        # 查找该日期的 session 文件
        for f in self.pending_dir.glob(f"session_{date_str}*.md"):
            try:
                content = f.read_text(encoding="utf-8")
                summaries.append(content)
            except Exception as e:
                logger.error(f"Error reading {f}: {e}")
        
        return "\n\n---\n\n".join(summaries) if summaries else ""
    
    def _collect_conversations(self, target_date: date) -> List[Dict]:
        """收集 conversations 目录下的原始对话"""
        date_str = target_date.strftime("%Y-%m-%d")
        conversations = []
        
        for conv_file in self.conv_dir.glob(f"{date_str}*.jsonl"):
            try:
                with open(conv_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            record = json.loads(line)
                            if record.get("type") == "turn":
                                conversations.append({
                                    "time": record.get("timestamp", ""),
                                    "user": record.get("user", ""),
                                    "assistant": record.get("assistant", ""),
                                })
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.error(f"Error reading {conv_file}: {e}")
        
        conversations.sort(key=lambda x: x.get("time", ""))
        return conversations
    
    def _format_conversations_as_summary(self, conversations: List[Dict]) -> str:
        """将对话格式化为摘要文本"""
        lines = []
        for conv in conversations:
            time = conv.get("time", "")[:16]
            user = conv.get("user", "")[:300]
            assistant = conv.get("assistant", "")[:300]
            
            if user:
                lines.append(f"[{time}] 主人: {user}")
            if assistant:
                lines.append(f"[{time}] 灰魂: {assistant}")
        
        return "\n".join(lines)
    
    async def _generate_with_llm(
        self,
        content: str,
        existing_diary: Optional[str],
        date_str: str
    ) -> Optional[str]:
        """使用 LLM 和现有提示词生成日记"""
        try:
            if existing_diary:
                # 追加模式：使用 merge_prompt
                prompt = self.merge_prompt.format(
                    existing_content=existing_diary,
                    content=content
                )
            else:
                # 新建模式：使用 consolidate_prompt
                prompt = self.consolidate_prompt.format(content=content)
            
            response = await self.llm.generate(prompt)
            return response.strip()
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return self._generate_simple(content, date_str)
    
    def _generate_simple(self, content: str, date_str: str) -> str:
        """无 LLM 时的简单模板"""
        return f"# {date_str} 日记\n\n{content}"
    
    async def _sync_to_graphiti(
        self,
        content: str,
        date_str: str,
        target_date: date
    ):
        """将日记同步到 Graphiti"""
        try:
            from .graphiti_adapter import EpisodeType
            
            await self.graphiti.add_episode(
                content=content,
                source=f"diary:{date_str}",
                episode_type=EpisodeType.DIARY,
                timestamp=datetime.combine(target_date, datetime.min.time())
            )
            logger.info(f"Diary synced to Graphiti: {date_str}")
        except Exception as e:
            logger.error(f"Failed to sync to Graphiti: {e}")
    
    async def generate_missing_diaries(self, days_back: int = 7) -> List[Path]:
        """生成最近缺失的日记"""
        generated = []
        today = date.today()
        
        for i in range(1, days_back + 1):  # 跳过今天
            target_date = today - timedelta(days=i)
            result = await self.generate_for_date(target_date)
            if result:
                generated.append(result)
        
        return generated
```

---

## 🖥️ Phase 5: Web 管理界面扩展 (2-3天)

### 5.1 现有界面分析

当前 admin.html 已有的功能模块：
- 📊 概览 - 系统状态
- ⚙️ 配置设置 - 基本设置、Agent、上下文、对话后总结
- 🤖 模型路由
- 🧠 记忆管理 - 待处理会话、节点管理
- 💾 备份恢复
- 📝 总结生成
- 🔮 RAG 语义搜索
- 🕸️ 知识图谱可视化
- 📎 额外挂载
- 📝 消息编排
- 🔧 调试日志

### 5.2 新增功能界面

#### 5.2.1 Graphiti 设置页面（新增导航项）

```html
<!-- admin.html 新增导航项 -->
<li class="nav-item" data-page="graphiti">
    <i>🔗</i> Graphiti 图谱
</li>
```

**页面内容**：

```html
<div id="graphiti" class="page">
    <div class="page-header">
        <h2>🔗 Graphiti 时序知识图谱</h2>
        <p>配置 Graphiti 后端、LLM、检索策略</p>
    </div>

    <!-- 启用开关 -->
    <div class="card">
        <div class="card-header">
            <h3>⚙️ 基本设置</h3>
        </div>
        <div class="form-group">
            <label class="form-label">
                <input type="checkbox" id="cfg-graphiti-enabled" style="margin-right: 8px;">
                启用 Graphiti 时序知识图谱
            </label>
            <div class="form-hint">启用后，对话记忆会同时索引到 Graphiti，支持时序查询和多跳关系检索</div>
        </div>
        
        <div class="form-group">
            <label class="form-label">图数据库后端</label>
            <select id="cfg-graphiti-backend" class="form-select">
                <option value="kuzu" selected>Kuzu（嵌入式，推荐开发）</option>
                <option value="neo4j">Neo4j（生产环境）</option>
            </select>
        </div>
        
        <div id="kuzu-settings">
            <div class="form-group">
                <label class="form-label">Kuzu 数据库路径</label>
                <input type="text" id="cfg-kuzu-path" class="form-input" value="./lifebook/.graphiti.kuzu">
            </div>
        </div>
        
        <div id="neo4j-settings" style="display: none;">
            <div style="display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 15px;">
                <div class="form-group">
                    <label class="form-label">Neo4j URI</label>
                    <input type="text" id="cfg-neo4j-uri" class="form-input" value="bolt://localhost:7687">
                </div>
                <div class="form-group">
                    <label class="form-label">用户名</label>
                    <input type="text" id="cfg-neo4j-user" class="form-input" value="neo4j">
                </div>
                <div class="form-group">
                    <label class="form-label">密码</label>
                    <input type="password" id="cfg-neo4j-pass" class="form-input">
                </div>
            </div>
        </div>
    </div>

    <!-- LLM 配置 -->
    <div class="card">
        <div class="card-header">
            <h3>🤖 LLM 配置（实体抽取用）</h3>
        </div>
        <div class="alert alert-warning" style="margin-bottom: 15px;">
            <span>⚠️</span>
            <div>
                Graphiti 需要支持 <strong>Structured Output</strong> 的 LLM。<br>
                推荐：OpenAI GPT-4o、GPT-4o-mini、Gemini 2.0
            </div>
        </div>
        
        <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 15px;">
            <div class="form-group">
                <label class="form-label">API Base URL（留空使用 OpenAI 默认）</label>
                <input type="text" id="cfg-graphiti-llm-url" class="form-input" placeholder="https://api.openai.com/v1">
            </div>
            <div class="form-group">
                <label class="form-label">API Key</label>
                <div style="display: flex; gap: 10px;">
                    <input type="password" id="cfg-graphiti-llm-key" class="form-input" placeholder="sk-...">
                    <button class="btn btn-sm" onclick="togglePassword('cfg-graphiti-llm-key')">👁️</button>
                </div>
            </div>
        </div>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px;">
            <div class="form-group">
                <label class="form-label">主模型</label>
                <input type="text" id="cfg-graphiti-model" class="form-input" value="gpt-4o-mini">
            </div>
            <div class="form-group">
                <label class="form-label">Embedding 模型</label>
                <input type="text" id="cfg-graphiti-embed-model" class="form-input" value="text-embedding-3-small">
            </div>
            <div class="form-group">
                <label class="form-label">Embedding 维度</label>
                <input type="number" id="cfg-graphiti-embed-dim" class="form-input" value="1536">
            </div>
        </div>
        
        <div class="form-group">
            <label class="form-label">
                <input type="checkbox" id="cfg-graphiti-reranker" style="margin-right: 8px;">
                启用 Reranker（提升检索精度）
            </label>
        </div>
    </div>

    <!-- 检索策略 -->
    <div class="card">
        <div class="card-header">
            <h3>🔍 检索策略</h3>
        </div>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px;">
            <div class="form-group">
                <label class="form-label">检索策略</label>
                <select id="cfg-graphiti-strategy" class="form-select">
                    <option value="auto">自动判断（推荐）</option>
                    <option value="simple">简单检索（单次）</option>
                    <option value="iterative">迭代检索（MemR3 风格）</option>
                </select>
                <div class="form-hint">自动模式根据问题复杂度选择策略</div>
            </div>
            <div class="form-group">
                <label class="form-label">最大迭代次数</label>
                <input type="number" id="cfg-graphiti-max-iter" class="form-input" value="3" min="1" max="10">
            </div>
            <div class="form-group">
                <label class="form-label">最少证据数量</label>
                <input type="number" id="cfg-graphiti-min-evidence" class="form-input" value="2" min="1" max="10">
            </div>
        </div>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 15px;">
            <div class="form-group">
                <label class="form-label">语义相似度阈值</label>
                <input type="number" id="cfg-graphiti-sim-score" class="form-input" value="0.4" step="0.1" min="0" max="1">
            </div>
            <div class="form-group">
                <label class="form-label">MMR 多样性参数</label>
                <input type="number" id="cfg-graphiti-mmr" class="form-input" value="0.5" step="0.1" min="0" max="1">
            </div>
            <div class="form-group">
                <label class="form-label">默认结果数</label>
                <input type="number" id="cfg-graphiti-limit" class="form-input" value="10" min="1" max="50">
            </div>
            <div class="form-group">
                <label class="form-label">
                    <input type="checkbox" id="cfg-graphiti-include-edges" checked style="margin-right: 8px;">
                    包含关系边
                </label>
            </div>
        </div>
    </div>

    <!-- 成本控制 -->
    <div class="card">
        <div class="card-header">
            <h3>💰 成本控制</h3>
        </div>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px;">
            <div class="form-group">
                <label class="form-label">每日 Token 限额</label>
                <input type="number" id="cfg-graphiti-daily-limit" class="form-input" value="100000">
                <div class="form-hint">超过 80% 时会警告</div>
            </div>
            <div class="form-group">
                <label class="form-label">并发限制</label>
                <input type="number" id="cfg-graphiti-semaphore" class="form-input" value="10" min="1" max="50">
                <div class="form-hint">防止 LLM 429 错误</div>
            </div>
            <div class="form-group">
                <label class="form-label">复杂查询阈值（字符数）</label>
                <input type="number" id="cfg-graphiti-complex-threshold" class="form-input" value="50">
                <div class="form-hint">超过此长度才可能用迭代检索</div>
            </div>
        </div>
        
        <!-- Token 使用量统计 -->
        <div style="margin-top: 15px; padding: 12px; background: var(--surface-2); border-radius: 8px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: var(--text-dim);">📊 今日 Token 使用量</span>
                <button class="btn btn-sm" onclick="refreshGraphitiStats()">🔄 刷新</button>
            </div>
            <div id="graphiti-token-usage" style="margin-top: 10px;">
                <div style="display: flex; gap: 20px;">
                    <span>已用: <strong id="graphiti-used-tokens">--</strong></span>
                    <span>限额: <strong id="graphiti-limit-tokens">100,000</strong></span>
                    <span>剩余: <strong id="graphiti-remain-tokens">--</strong></span>
                </div>
                <div style="margin-top: 8px; height: 6px; background: var(--surface-3); border-radius: 3px; overflow: hidden;">
                    <div id="graphiti-usage-bar" style="height: 100%; width: 0%; background: var(--success); transition: width 0.3s;"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- 同步设置 -->
    <div class="card">
        <div class="card-header">
            <h3>🔄 同步设置</h3>
        </div>
        
        <div class="form-group">
            <label class="form-label">
                <input type="checkbox" id="cfg-graphiti-sync-conv" checked style="margin-right: 8px;">
                索引对话记录到 Graphiti
            </label>
            <div class="form-hint">每轮对话自动提取实体和关系</div>
        </div>
        
        <div style="display: flex; gap: 15px; margin-top: 15px;">
            <button class="btn btn-primary" onclick="syncMarkdownToGraphiti()">📤 同步 Markdown → Graphiti</button>
            <button class="btn btn-warning" onclick="rebuildGraphitiIndex()">🔄 重建 Graphiti 索引</button>
            <span id="graphiti-sync-status" style="color: var(--text-dim); line-height: 36px;"></span>
        </div>
    </div>

    <div style="display: flex; gap: 10px; margin-bottom: 40px;">
        <button class="btn btn-primary" onclick="loadGraphitiConfig()">🔄 重新加载</button>
        <button class="btn btn-success" onclick="saveGraphitiConfig()">💾 保存配置</button>
    </div>
</div>
```

#### 5.2.2 对话记录设置（整合到"配置设置"页面）

在现有 config 页面的"对话后总结"卡片后添加：

```html
<div class="card">
    <div class="card-header">
        <h3>💬 对话保留机制</h3>
    </div>
    
    <div class="alert alert-info" style="margin-bottom: 15px;">
        <span>💡</span>
        <div>
            对话保留机制会将原始对话完整保存到 <code>lifebook/conversations/</code> 目录，<br>
            用于日记生成重试、对话历史查阅。
        </div>
    </div>
    
    <div class="form-group">
        <label class="form-label">
            <input type="checkbox" id="cfg-conv-enabled" checked style="margin-right: 8px;">
            启用原始对话保留
        </label>
    </div>
    
    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px;">
        <div class="form-group">
            <label class="form-label">会话超时（分钟）</label>
            <input type="number" id="cfg-conv-timeout" class="form-input" value="30" min="5" max="120">
            <div class="form-hint">超过此时间无新消息则视为新会话</div>
        </div>
        <div class="form-group">
            <label class="form-label">前缀匹配阈值</label>
            <input type="number" id="cfg-conv-threshold" class="form-input" value="0.7" step="0.1" min="0.5" max="1">
            <div class="form-hint">用于判断是否是续写</div>
        </div>
        <div class="form-group">
            <label class="form-label">单文件最大轮次</label>
            <input type="number" id="cfg-conv-max-turns" class="form-input" value="100" min="10" max="500">
        </div>
    </div>
</div>
```

#### 5.2.3 概览页面扩展

在概览页面的统计卡片中新增 Graphiti 状态：

```html
<div class="stat-card">
    <div class="stat-card-label">🔗 Graphiti 状态</div>
    <div class="stat-card-value" id="stat-graphiti">--</div>
    <div class="stat-card-detail" id="stat-graphiti-detail">未启用</div>
</div>
```

### 5.3 后端 API 扩展

新增 `web/graphiti_routes.py`：

```python
# web/graphiti_routes.py

from flask import Blueprint, jsonify, request
import logging

graphiti_bp = Blueprint('graphiti', __name__)
logger = logging.getLogger(__name__)


@graphiti_bp.route('/graphiti/config', methods=['GET'])
def get_graphiti_config():
    """获取 Graphiti 配置"""
    from .core import load_config
    config = load_config()
    graphiti_config = config.get("graphiti", {})
    
    # 隐藏敏感信息
    if "llm" in graphiti_config:
        llm = graphiti_config["llm"].copy()
        if "api_key" in llm:
            llm["api_key"] = "***" if llm["api_key"] else ""
        graphiti_config["llm"] = llm
    
    return jsonify(graphiti_config)


@graphiti_bp.route('/graphiti/config', methods=['POST'])
def save_graphiti_config():
    """保存 Graphiti 配置"""
    from .core import load_config, save_config, invalidate_config_cache
    
    data = request.get_json()
    config = load_config()
    
    # 合并配置
    if "graphiti" not in config:
        config["graphiti"] = {}
    
    config["graphiti"].update(data)
    
    save_config(config)
    invalidate_config_cache()
    
    return jsonify({"success": True})


@graphiti_bp.route('/graphiti/stats', methods=['GET'])
def get_graphiti_stats():
    """获取 Graphiti 状态和统计"""
    try:
        # 检查是否启用
        from .core import load_config
        config = load_config()
        
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({
                "enabled": False,
                "status": "disabled"
            })
        
        # 获取统计
        # TODO: 实际实现需要调用 GraphitiAdapter
        return jsonify({
            "enabled": True,
            "status": "running",
            "backend": config.get("graphiti", {}).get("backend", "kuzu"),
            "entity_count": 0,  # TODO
            "edge_count": 0,    # TODO
            "episode_count": 0  # TODO
        })
    except Exception as e:
        logger.error(f"获取 Graphiti 状态失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/token-usage', methods=['GET'])
def get_token_usage():
    """获取今日 Token 使用量"""
    # TODO: 从 TokenUsageTracker 获取
    return jsonify({
        "used": 0,
        "limit": 100000,
        "remaining": 100000
    })


@graphiti_bp.route('/graphiti/sync', methods=['POST'])
def sync_to_graphiti():
    """从 Markdown 同步到 Graphiti"""
    # TODO: 调用 GraphitiAdapter.sync_from_markdown()
    return jsonify({"success": True, "message": "同步已开始（后台执行）"})


@graphiti_bp.route('/graphiti/rebuild', methods=['POST'])
def rebuild_graphiti_index():
    """重建 Graphiti 索引"""
    # TODO: 清空并重建
    return jsonify({"success": True, "message": "重建已开始（后台执行）"})
```

### 5.4 前端 JS 模块

新增 `static/js/admin-graphiti.js`：

```javascript
// static/js/admin-graphiti.js

// 加载 Graphiti 配置
async function loadGraphitiConfig() {
    try {
        const res = await fetch('/api/memory/graphiti/config');
        const config = await res.json();
        
        // 填充表单
        document.getElementById('cfg-graphiti-enabled').checked = config.enabled || false;
        document.getElementById('cfg-graphiti-backend').value = config.backend || 'kuzu';
        
        // 根据后端切换显示
        toggleGraphitiBackend(config.backend || 'kuzu');
        
        // LLM 配置
        if (config.llm) {
            document.getElementById('cfg-graphiti-llm-url').value = config.llm.base_url || '';
            document.getElementById('cfg-graphiti-model').value = config.llm.model || 'gpt-4o-mini';
            document.getElementById('cfg-graphiti-embed-model').value = config.llm.embedding_model || 'text-embedding-3-small';
        }
        
        // 检索策略
        if (config.retrieval) {
            document.getElementById('cfg-graphiti-strategy').value = config.retrieval.strategy || 'auto';
            document.getElementById('cfg-graphiti-max-iter').value = config.retrieval.max_iterations || 3;
        }
        
        showToast('配置加载成功', 'success');
    } catch (e) {
        showToast('加载配置失败: ' + e.message, 'error');
    }
}

// 保存 Graphiti 配置
async function saveGraphitiConfig() {
    const config = {
        enabled: document.getElementById('cfg-graphiti-enabled').checked,
        backend: document.getElementById('cfg-graphiti-backend').value,
        llm: {
            base_url: document.getElementById('cfg-graphiti-llm-url').value || null,
            model: document.getElementById('cfg-graphiti-model').value,
            embedding_model: document.getElementById('cfg-graphiti-embed-model').value,
            embedding_dim: parseInt(document.getElementById('cfg-graphiti-embed-dim').value)
        },
        retrieval: {
            strategy: document.getElementById('cfg-graphiti-strategy').value,
            max_iterations: parseInt(document.getElementById('cfg-graphiti-max-iter').value),
            min_evidence_count: parseInt(document.getElementById('cfg-graphiti-min-evidence').value),
            default_limit: parseInt(document.getElementById('cfg-graphiti-limit').value)
        },
        performance: {
            semaphore_limit: parseInt(document.getElementById('cfg-graphiti-semaphore').value),
            daily_token_limit: parseInt(document.getElementById('cfg-graphiti-daily-limit').value)
        }
    };
    
    try {
        const res = await fetch('/api/memory/graphiti/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        if (res.ok) {
            showToast('配置已保存', 'success');
        } else {
            throw new Error('保存失败');
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

// 刷新 Token 使用统计
async function refreshGraphitiStats() {
    try {
        const res = await fetch('/api/memory/graphiti/token-usage');
        const data = await res.json();
        
        document.getElementById('graphiti-used-tokens').textContent = data.used.toLocaleString();
        document.getElementById('graphiti-limit-tokens').textContent = data.limit.toLocaleString();
        document.getElementById('graphiti-remain-tokens').textContent = data.remaining.toLocaleString();
        
        const percent = (data.used / data.limit * 100).toFixed(1);
        const bar = document.getElementById('graphiti-usage-bar');
        bar.style.width = percent + '%';
        bar.style.background = percent > 80 ? 'var(--danger)' : percent > 50 ? 'var(--warning)' : 'var(--success)';
        
    } catch (e) {
        console.error('刷新统计失败:', e);
    }
}

// 切换后端显示
function toggleGraphitiBackend(backend) {
    document.getElementById('kuzu-settings').style.display = backend === 'kuzu' ? 'block' : 'none';
    document.getElementById('neo4j-settings').style.display = backend === 'neo4j' ? 'block' : 'none';
}

// 同步到 Graphiti
async function syncMarkdownToGraphiti() {
    if (!confirm('确定要将所有 Markdown 同步到 Graphiti 吗？这可能需要几分钟。')) return;
    
    try {
        const res = await fetch('/api/memory/graphiti/sync', { method: 'POST' });
        const data = await res.json();
        showToast(data.message, 'success');
    } catch (e) {
        showToast('同步失败: ' + e.message, 'error');
    }
}

// 重建索引
async function rebuildGraphitiIndex() {
    if (!confirm('⚠️ 确定要重建 Graphiti 索引吗？这将清空现有数据并重新构建。')) return;
    
    try {
        const res = await fetch('/api/memory/graphiti/rebuild', { method: 'POST' });
        const data = await res.json();
        showToast(data.message, 'warning');
    } catch (e) {
        showToast('重建失败: ' + e.message, 'error');
    }
}
```

### 5.5 实施清单

| 任务 | 文件 | 工作量 |
|------|------|--------|
| Graphiti 页面 HTML | `web/admin.html` | 0.5天 |
| Graphiti 后端 API | `web/graphiti_routes.py` | 0.5天 |
| Graphiti 前端 JS | `static/js/admin-graphiti.js` | 0.5天 |
| 对话保留配置 | `web/admin.html` + `config_routes.py` | 0.3天 |
| 概览页面扩展 | `web/admin.html` + `diary_routes.py` | 0.2天 |
| 测试验证 | - | 0.5天 |
| **总计** | - | **2.5天** |

---

## 📁 文件结构变更

```
memory_store/
├── reader.py                    # 现有
├── writer.py                    # 现有
├── sqlite_indexer.py            # 现有
├── rag.py                       # 现有
│
├── graphiti_adapter.py          # 【新增】Graphiti 适配器
│   ├── EpisodeType              #   - Episode 类型枚举
│   ├── GroupIdStrategy          #   - Group ID 策略管理器
│   ├── GraphitiAdapter          #   - 异步适配器（核心）
│   └── GraphitiSyncAdapter      #   - 同步包装器
│
├── conversation_matcher.py      # 【新增】会话匹配器
├── conversation_logger.py       # 【新增】对话记录器
├── retrieval_cache.py           # 【新增】检索缓存
└── diary_generator.py           # 【新增】日记生成器

memory_agent/
├── agent.py                     # 现有（保留）
├── tools.py                     # 修改：添加 Graphiti 工具
├── graphiti_tools.py            # 【新增】Graphiti 工具定义
│
├── iterative_retriever.py       # 【新增】MemR3 风格迭代检索器
│   ├── RetrievalAction          #   - 检索动作枚举
│   ├── EvidenceGapState         #   - Evidence-Gap 状态追踪
│   └── IterativeRetriever       #   - 迭代检索器（核心）
│
└── retrieval_router.py          # 【新增】检索路由器
    └── RetrievalRouter          #   - 智能路由（整合迭代检索）

lifebook/
├── conversations/               # 【新增】原始对话目录
│   └── 2026-01-21_1224.jsonl
├── .graphiti.kuzu/              # 【新增】Kuzu 数据库目录
│   └── *.kuzudb                 #   - Kuzu 数据文件
├── daily/
├── nodes/
└── ...
```

### 新增模块依赖关系

```
                    ┌─────────────────────────────────────────┐
                    │           RetrievalRouter               │
                    │  (智能路由 + 复杂度分类)                  │
                    └─────────────────┬───────────────────────┘
                                      │
                    ┌─────────────────┴───────────────────┐
                    │                                      │
                    ▼                                      ▼
    ┌───────────────────────────┐        ┌───────────────────────────┐
    │   IterativeRetriever      │        │   deepseek-reasoner       │
    │  (MemR3 Evidence-Gap)     │        │   (极复杂查询后备)         │
    │                           │        │                           │
    │  Retrieve → Reflect →     │        │                           │
    │  Refine → Loop            │        │                           │
    └─────────────┬─────────────┘        └───────────────────────────┘
                  │
                  ▼
    ┌───────────────────────────┐
    │     GraphitiAdapter       │
    │  - OpenAIGenericClient    │
    │  - Reranker               │
    │  - SearchConfig           │
    │  - Group ID 策略           │
    │  - Episode 类型过滤        │
    └─────────────┬─────────────┘
                  │
                  ▼
    ┌───────────────────────────┐
    │        Kuzu / Neo4j       │
    │    (图数据库存储)          │
    └───────────────────────────┘
```

---

## 📅 实施计划

| Phase | 任务 | 天数 | 依赖 | 说明 |
|-------|------|------|------|------|
| **1.1** | Graphiti 安装配置 | 0.5 | - | 安装依赖，配置环境变量 |
| **1.2** | GraphitiAdapter 实现 | 2.5 | 1.1 | 含 Reranker、GroupId、EpisodeType |
| **1.3** | 工具集成 | 1 | 1.2 | graphiti_tools.py |
| **1.4** | 同步机制 | 1 | 1.2 | Markdown → Graph 同步 |
| **1.5** | 测试验证 | 1 | 1.3, 1.4 | 单元测试 + 集成测试 |
| **2.1** | ConversationMatcher 实现 | 1 | - | 多层匹配策略 |
| **2.2** | ConversationLogger 实现 | 1 | 2.1 | JSONL 记录 + Graphiti 索引 |
| **2.3** | 集成到 Proxy | 0.5 | 2.2 | 修改 chat.py |
| **2.4** | DiaryGenerator 实现 | 1 | 2.2 | 从对话生成日记 |
| **3.1** | IterativeRetriever 实现 | 1.5 | 1.3 | **MemR3 Evidence-Gap 机制** |
| **3.2** | RetrievalRouter 实现 | 1 | 3.1 | 复杂度分类 + 路由 |
| **3.3** | LLM Reflect/Refine | 0.5 | 3.1 | 可选的 LLM 增强 |
| **4.1** | 缓存机制 | 0.5 | 3.2 | 检索结果缓存 |
| **4.2** | 性能测试 | 0.5 | 4.1 | 延迟 + 准确率测试 |
| | **总计** | **~14天** | | |

### 并行可能性

```
Week 1:
├── Phase 1.1-1.2 (GraphitiAdapter) ──────────────────────►
│   含: Reranker, GroupId, EpisodeType,
│        OpenAIGenericClient, SearchConfig
│
└── Phase 2.1-2.2 (对话记录) ─────────────────────────────►

Week 2:
├── Phase 1.3-1.5 (Graphiti 工具+测试) ────────►
├── Phase 2.3-2.4 (对话集成+日记) ─────────────►
└── Phase 3.1-3.2 (迭代检索+路由) ─────────────────────────►
    含: IterativeRetriever (MemR3),
        RetrievalRouter, LLM 增强

Week 3:
└── Phase 3.3-4.2 (优化+测试) ───►
```

### 关键里程碑

| 里程碑 | 完成标志 | 预计时间 |
|--------|---------|---------|
| M1: Graphiti 可用 | 能添加/检索 Episode | Day 3 |
| M2: 对话保留 | JSONL 正确记录续写 | Day 5 |
| M3: 迭代检索 | Evidence-Gap 正常工作 | Day 10 |
| M4: 完整集成 | 端到端测试通过 | Day 14 |

---

## 🧪 验收标准

### Phase 1: Graphiti 整合

| 测试项 | 预期结果 | 验证方法 |
|--------|---------|---------|
| 初始化成功 | Kuzu 数据库创建 | 检查 `.graphiti.kuzu/` 目录 |
| Episode 添加 | 无错误 | 添加100条测试数据 |
| 混合搜索 | 返回相关结果 | 搜索已知实体 |
| 时间点查询 | 返回历史状态 | 构造时序测试数据 |
| 同步 | Markdown → Graph | 对比节点数量 |

### Phase 2: 对话保留

| 测试项 | 预期结果 | 验证方法 |
|--------|---------|---------|
| 新会话创建 | 生成 JSONL 文件 | 检查文件存在 |
| 会话续写 | 追加到同一文件 | 对比文件内容 |
| 指纹匹配 | 正确识别续写 | 发送相同前缀的消息 |
| 编辑消息后匹配 | 仍能正确匹配 | 修改历史消息内容 |
| 日记生成 | 从原始对话生成 | 手动触发生成 |

### Phase 3: 检索路由

| 测试项 | 预期结果 | 验证方法 |
|--------|---------|---------|
| 简单查询 | < 500ms | 计时 "灰魂是谁" |
| 中等查询 | < 2s | 计时 "最近在做什么" |
| 复杂查询 | 使用 Agent | 日志确认路由 |
| 强制策略 | 按指定执行 | 配置 force_strategy |

---

## ⚠️ 注意事项与风险应对

### 风险1：Kuzu 驱动成熟度

Kuzu 支持是 Graphiti v0.11.2 才加入的，Neo4j 是主要测试后端。

**应对措施**：
- 先用小规模数据（50条日记）验证
- 准备 Neo4j 配置作为备选（已在配置中预留）
- 监控 Kuzu 相关错误日志

### 风险2：Structured Output 兼容性 🔴

Graphiti 实体抽取使用 Pydantic 模型，需要 LLM 支持 `response_format: { type: "json_schema" }`。

**应对措施**：

```python
# 在 GraphitiAdapter 中添加降级机制
async def _extract_with_fallback(self, prompt: str, expected_schema: type):
    """带降级的实体抽取"""
    try:
        # 优先尝试 Structured Output
        return await self.llm.generate_structured(prompt, expected_schema)
    except StructuredOutputNotSupported:
        # 降级为普通生成 + JSON 解析修复
        raw = await self.llm.generate(
            prompt + "\n请严格用 JSON 格式输出，不要添加任何解释。"
        )
        return self._parse_json_with_repair(raw, expected_schema)
    
def _parse_json_with_repair(self, raw: str, schema: type) -> Any:
    """尝试修复并解析 JSON"""
    import re
    
    # 提取 JSON 块
    json_match = re.search(r'```json?\s*([\s\S]*?)\s*```', raw)
    if json_match:
        raw = json_match.group(1)
    
    # 尝试直接解析
    try:
        data = json.loads(raw)
        return schema(**data)
    except (json.JSONDecodeError, ValidationError) as e:
        # 常见修复：去除尾部逗号、修复引号等
        fixed = re.sub(r',\s*}', '}', raw)
        fixed = re.sub(r',\s*]', ']', fixed)
        data = json.loads(fixed)
        return schema(**data)
```

### 风险3：中文实体抽取效果

Graphiti 的 prompt 主要针对英文设计。

**应对措施**：

```python
# 中文 Prompt 适配层
CHINESE_ENTITY_EXTRACTION_SUFFIX = """

【中文处理规则】
1. 人名保持完整：如"张三"、"主人"是一个实体
2. 项目名保持完整：如"LifeBook记忆系统"是一个实体
3. 关系类型用中文：如"开发"、"使用"、"属于"、"学习"
4. 日期格式：优先使用 ISO 8601 (2025-01-21)，无具体日期时用 null
5. 如果无法确定实体边界，宁可合并也不要拆分
"""
```

### 风险4：迭代检索成本隐患 💰

MemR3 风格的迭代检索每次查询可能消耗 6+ 次 LLM 调用。

**应对措施**：

```python
# 成本监控中间件
class TokenUsageTracker:
    """Token 使用量追踪"""
    
    def __init__(self, daily_limit: int = 100000):
        self.daily_limit = daily_limit
        self._usage: Dict[str, int] = {}  # date -> tokens
    
    def record(self, tokens: int, operation: str = "unknown"):
        today = datetime.now().strftime("%Y-%m-%d")
        self._usage[today] = self._usage.get(today, 0) + tokens
        
        # 日志记录
        logger.debug(f"[Token] {operation}: +{tokens}, 今日累计: {self._usage[today]}")
        
        # 超限警告
        if self._usage[today] > self.daily_limit * 0.8:
            logger.warning(f"[Token] 今日用量已达 {self._usage[today]}/{self.daily_limit} (80%)")
    
    def can_proceed(self) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        return self._usage.get(today, 0) < self.daily_limit
```

**配置限制**：

```jsonc
{
    "graphiti": {
        "retrieval": {
            "strategy": "auto",  // 默认自动判断，不是总用迭代
            "max_iterations": 3,
            "daily_token_limit": 100000,  // 每日限额
            "complex_query_threshold": 50  // 字符数超过此值才可能用迭代
        }
    }
}
```

### 数据一致性

### 数据一致性原则

1. **主存储**：Markdown 文件仍是"单一事实源"
2. **Graphiti**：作为索引层，可从 Markdown 重建
3. **对话记录**：JSONL 是原始数据，不可丢失
4. **冲突处理**：以 Markdown 为准，Graphiti 仅索引

### 回滚方案（保持不变）

如果 Graphiti 出问题：
1. 删除 `.graphiti.kuzu/` 目录
2. 禁用配置 `"graphiti": { "enabled": false }`
3. 系统回退到原有 SQLite + RAG 模式

### 分阶段验证计划（新增）

| 阶段 | 验证内容 | 预期时间 | 通过标准 |
|------|---------|---------|---------|
| **MVP** | Kuzu 初始化 + 添加3条日记 + 搜索 | 2天 | 无错误返回结果 |
| **中文测试** | 添加50条中文日记，验证实体抽取 | 3天 | 实体抽取准确率 > 70% |
| **迭代检索** | MemR3 机制 + 成本监控 | 3天 | 复杂问题回答准确率提升 |
| **对话保留** | 会话匹配准确率测试 | 2天 | 续写正确识别率 > 90% |
| **全量集成** | 与现有系统对接 | 5天 | 端到端测试通过 |

### 依赖版本（更新）

```txt
# 核心依赖
graphiti-core>=0.17.0
kuzu>=0.11.2  # 注意：跟进 Graphiti 最新版本要求

# LLM 提供商（按需）
openai>=1.0.0
# anthropic>=0.18.0
# google-generativeai>=0.4.0

# 其他
python-dateutil>=2.8
pydantic>=2.0  # Structured Output 解析

# 可选：成本监控
# tiktoken>=0.5.0  # OpenAI token 计数
```

### 时间估算修正

原规划预计 14 天，考虑到以下因素：
- 调试 Structured Output 问题：+2-3天
- 中文实体抽取优化：+2天
- 与现有 `memory_agent/` 模块集成：+2天
- Web 管理界面开发：+2.5天
- 端到端测试：+2天

**更现实的估计：24-28 天**

| Phase | 原预计 | 修正后 | 说明 |
|-------|-------|-------|------|
| Phase 1 (Graphiti) | 5-7天 | 7-9天 | 含 Structured Output 降级 |
| Phase 2 (对话保留) | 3-5天 | 4-6天 | 含会话匹配机制 |
| Phase 3 (迭代检索) | 3-4天 | 4-5天 | 含 MemR3 Evidence-Gap |
| Phase 4 (性能优化) | 1-2天 | 2-3天 | 含成本监控 |
| **Phase 5 (Web界面)** | 0天 | **2.5天** | 🆕 Graphiti 配置页面 |
| 缓冲时间 | 0天 | 3天 | 意外问题处理 |
| **总计** | ~14天 | **~25天** | |

---

## 🔗 参考资料

- [Graphiti GitHub](https://github.com/getzep/graphiti)
- [Graphiti 论文 (arXiv:2501.13956)](https://arxiv.org/abs/2501.13956)
- [Graphiti 文档](https://help.getzep.com/graphiti)
- [MemR3 GitHub](https://github.com/zep-research/memr3) - 迭代检索参考实现
- [Kuzu 文档](https://kuzudb.com/docs/)
- [OpenAI Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)

---

*规划创建时间：2026-01-22*
*规划修订时间：2026-01-22（整合风险应对措施）*
*作者：灰魂* 😸
# 🕸️ Neo4j + 时序知识图谱 (TKG) 改造规划

## 📊 现状分析

### 当前知识图谱架构

```
lifebook/nodes/
├── 人物-主人.md          ← 实体存储
├── 人物-灰魂.md
├── 事物-LifeBook系统.md
└── 概念-记忆管理.md

关系表达：通过 [[双链]] 在 Markdown 中
查询方式：遍历所有文件解析链接 (O(n))
```

**痛点**：
1. 关系查询需遍历所有文件，无法高效多跳查询
2. 实体没有时间版本，无法追溯"三个月前这个项目是什么状态"
3. 无法表达"临时关系"（如：2025年1月~3月使用某工具）
4. 缺乏图算法支持（路径分析、社区发现、中心性计算）

---

## 🎯 改造目标

### 1. Neo4j 图数据库集成
- 原生 Cypher 查询，O(1) 关系遍历
- 多跳查询："主人的朋友认识的人"
- 路径分析："灰魂和DeepSeek之间有什么联系？"

### 2. 时序知识图谱 (TKG)
- **实体版本化**：追踪属性随时间变化
- **时序关系**：关系带有效期 `[start_time, end_time]`
- **时间点查询**："2025年3月时，我在做什么项目？"
- **演化分析**："这个概念在过去一年是如何发展的？"

### 3. 保持 Markdown 人类可读性
- Markdown 仍是"单一事实源"
- Neo4j 作为查询加速层
- 双向同步机制

---

## 🏗️ 架构设计

### 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户请求                                │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Memory Agent                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ 传统工具    │  │ 图查询工具  │  │ 时序查询工具       │  │
│  │ search_*    │  │ graph_*     │  │ temporal_*          │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼────────────────┼─────────────────────┼────────────┘
          ▼                ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    存储适配器层                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │               GraphStorageAdapter                        ││
│  │  - read_* / write_* → Markdown + Neo4j 双写             ││
│  │  - graph_query → Neo4j Cypher                           ││
│  │  - temporal_query → Neo4j + 时间索引                    ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
          │                          │
          ▼                          ▼
┌──────────────────────┐   ┌──────────────────────────────────┐
│   Markdown 文件系统   │   │         Neo4j 图数据库           │
│   (单一事实源)        │   │   (查询加速 + 图算法)            │
│                      │   │                                  │
│   lifebook/          │   │   (:Entity)-[:RELATES]->(:Entity)│
│   ├── nodes/*.md     │◀──┼── 同步                           │
│   ├── daily/*.md     │   │   (:Diary)-[:MENTIONS]->(:Entity)│
│   └── ...            │   │                                  │
└──────────────────────┘   └──────────────────────────────────┘
```

### Neo4j 数据模型

```cypher
// =============== 核心实体 ===============

// 实体节点（人物/地点/事物/概念）
CREATE (:Entity {
  name: "灰魂",
  type: "人物",           // 人物 | 地点 | 事物 | 概念
  created_at: datetime(),
  updated_at: datetime(),
  file_path: "nodes/人物-灰魂.md",
  
  // 当前属性快照
  current_description: "...",
  current_tags: ["AI", "助手"]
})

// =============== 时序版本 ===============

// 属性快照（追踪变化）
CREATE (:EntitySnapshot {
  entity_name: "LifeBook系统",
  valid_from: datetime("2025-01-01T00:00:00"),
  valid_to: datetime("2025-03-15T00:00:00"),  // null = 当前有效
  
  // 该时间段内的属性
  properties: {
    status: "开发中",
    version: "0.1.0",
    features: ["基础记忆", "日记生成"]
  },
  
  source_diary: "2025-01-01"  // 变更来源
})

// =============== 关系 ===============

// 时序关系（带有效期）
CREATE (a:Entity)-[:RELATES_TO {
  relation_type: "创建",      // 创建/使用/朋友/属于/...
  start_time: datetime("2025-01-01"),
  end_time: null,             // null = 持续中
  confidence: 1.0,            // 置信度
  source: "日记:2025-01-01",  // 信息来源
  context: "主人开始开发这个项目"
}]->(b:Entity)

// =============== 日记关联 ===============

// 日记节点
CREATE (:Diary {
  date: date("2025-01-21"),
  title: "2025-01-21 日记",
  file_path: "daily/2025-01-21.md",
  content_hash: "sha256:...",  // 用于检测变化
  word_count: 1500,
  created_at: datetime(),
  updated_at: datetime()
})

// 日记提及关系
CREATE (d:Diary)-[:MENTIONS {
  mention_type: "主题",  // 主题 | 提及 | 操作对象
  sentiment: "positive",
  context: "今天继续开发这个项目...",
  position: 150  // 在日记中的位置
}]->(e:Entity)

// =============== 索引 ===============

CREATE INDEX entity_name FOR (e:Entity) ON (e.name);
CREATE INDEX entity_type FOR (e:Entity) ON (e.type);
CREATE INDEX diary_date FOR (d:Diary) ON (d.date);
CREATE INDEX snapshot_time FOR (s:EntitySnapshot) ON (s.valid_from, s.valid_to);
```

---

## 🔧 新增记忆工具

### 图查询工具

```python
# 1. 自然语言图查询
"graph_query": {
    "name": "graph_query",
    "description": """
    使用知识图谱进行高级查询。支持：
    - 关系查询："谁与主人有合作关系？"
    - 多跳查询："主人的朋友认识的人"
    - 路径分析："灰魂和DeepSeek之间的联系"
    """,
    "parameters": {
        "query": {
            "type": "string",
            "description": "自然语言查询描述"
        },
        "max_hops": {
            "type": "integer",
            "default": 3,
            "description": "最大关系跳数"
        }
    }
}

# 2. Cypher 直接查询（高级用户）
"cypher_query": {
    "name": "cypher_query",
    "description": "直接执行 Cypher 查询语句",
    "parameters": {
        "cypher": {
            "type": "string",
            "description": "Cypher 查询语句"
        }
    }
}

# 3. 路径查找
"find_path": {
    "name": "find_path",
    "description": "查找两个实体之间的所有连接路径",
    "parameters": {
        "from_entity": {"type": "string"},
        "to_entity": {"type": "string"},
        "max_hops": {"type": "integer", "default": 4},
        "relation_types": {
            "type": "array",
            "items": {"type": "string"},
            "description": "限定关系类型（可选）"
        }
    }
}
```

### 时序查询工具

```python
# 4. 时间点查询
"temporal_snapshot": {
    "name": "temporal_snapshot",
    "description": "查询某个时间点的知识状态",
    "parameters": {
        "entity": {
            "type": "string",
            "description": "实体名称"
        },
        "time_point": {
            "type": "string",
            "description": "时间点（YYYY-MM-DD 或 YYYY-MM）"
        },
        "include": {
            "type": "array",
            "items": {"type": "string", "enum": ["properties", "relations", "mentions"]},
            "default": ["properties", "relations"]
        }
    }
}

# 5. 时间演化查询
"temporal_evolution": {
    "name": "temporal_evolution",
    "description": "查询实体或关系随时间的变化历史",
    "parameters": {
        "entity": {"type": "string"},
        "time_range": {
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "end": {"type": "string"}
            }
        },
        "aspect": {
            "type": "string",
            "enum": ["all", "properties", "relations", "activity"],
            "description": "查询维度"
        }
    }
}

# 6. 时间线查询
"timeline_query": {
    "name": "timeline_query",
    "description": "获取与某实体相关的事件时间线",
    "parameters": {
        "entity": {"type": "string"},
        "event_types": {
            "type": "array",
            "items": {"type": "string", "enum": ["创建", "更新", "关系变化", "提及"]}
        },
        "limit": {"type": "integer", "default": 20}
    }
}
```

### 图分析工具

```python
# 7. 中心性分析
"centrality_analysis": {
    "name": "centrality_analysis",
    "description": "找出知识图谱中最重要/最核心的实体",
    "parameters": {
        "algorithm": {
            "type": "string",
            "enum": ["pagerank", "betweenness", "degree"],
            "default": "pagerank"
        },
        "entity_type": {
            "type": "string",
            "description": "限定实体类型（可选）"
        },
        "top_k": {"type": "integer", "default": 10}
    }
}

# 8. 社区发现
"community_detection": {
    "name": "community_detection",
    "description": "自动发现知识图谱中的实体群组/社区",
    "parameters": {
        "algorithm": {
            "type": "string",
            "enum": ["louvain", "label_propagation"],
            "default": "louvain"
        },
        "min_community_size": {"type": "integer", "default": 2}
    }
}

# 9. 相似实体推荐
"similar_entities": {
    "name": "similar_entities",
    "description": "基于图结构找出与某实体最相似的其他实体",
    "parameters": {
        "entity": {"type": "string"},
        "similarity_metric": {
            "type": "string",
            "enum": ["jaccard", "cosine", "common_neighbors"],
            "default": "jaccard"
        },
        "top_k": {"type": "integer", "default": 5}
    }
}
```

---

## 📁 文件结构变更

```text
memory_store/
├── reader.py              # 现有
├── writer.py              # 现有
├── sqlite_indexer.py      # 现有
├── rag.py                 # 现有
│
├── neo4j_store.py         # 新增：Neo4j 存储层
│   ├── Neo4jConnection    # 连接管理
│   ├── EntityRepository   # 实体 CRUD
│   ├── RelationRepository # 关系 CRUD
│   └── TemporalRepository # 时序查询
│
├── graph_sync.py          # 新增：Markdown ↔ Neo4j 同步
│   ├── full_sync()        # 全量同步
│   ├── incremental_sync() # 增量同步（监听文件变化）
│   └── rebuild_from_md()  # 从 Markdown 重建 Neo4j
│
├── temporal_index.py      # 新增：时序索引管理
│   ├── create_snapshot()  # 创建属性快照
│   ├── query_at_time()    # 时间点查询
│   └── get_evolution()    # 演化历史
│
└── graph_algorithms.py    # 新增：图算法封装
    ├── find_paths()
    ├── centrality()
    ├── community_detection()
    └── similarity()

memory_agent/
├── tools.py               # 修改：添加图查询工具
└── graph_tools.py         # 新增：图专用工具实现

config.jsonc
├── neo4j                  # 新增配置段
│   ├── enabled: true
│   ├── uri: "bolt://localhost:7687"
│   ├── username: "neo4j"
│   ├── password: "..."
│   ├── database: "lifebook"
│   └── sync_mode: "dual_write"  # dual_write | read_only | disabled
│
└── temporal_kg            # 新增配置段
    ├── enabled: true
    ├── snapshot_on_change: true
    └── evolution_tracking: true
```

---

## 🚀 实施计划

### Phase 1: Neo4j 基础集成（3-4天）

**目标**：建立 Neo4j 索引层，保持 Markdown 为主存储

1. **Day 1: 环境搭建**
   - Docker 部署 Neo4j（`docker-compose.yml`）
   - Python `neo4j` 驱动集成
   - 配置文件添加 Neo4j 配置段

2. **Day 2: 数据模型实现**
   - `neo4j_store.py` 核心类
   - Entity / Relation CRUD 操作
   - 基础 Cypher 封装

3. **Day 3: 同步机制**
   - `graph_sync.py` 实现
   - 启动时全量同步
   - 写操作时双写

4. **Day 4: 基础工具集成**
   - `graph_query` 自然语言→Cypher
   - `find_path` 路径查找
   - Web 管理面板添加 Neo4j 状态

### Phase 2: 时序知识图谱（4-5天）

**目标**：实现实体版本化和时序查询

1. **Day 5-6: 时序模型**
   - EntitySnapshot 节点设计
   - 时序关系属性
   - `temporal_index.py` 实现

2. **Day 7-8: 时序工具**
   - `temporal_snapshot` 时间点查询
   - `temporal_evolution` 演化查询
   - `timeline_query` 时间线

3. **Day 9: 自动快照**
   - 监听节点变化，自动创建快照
   - 日记解析，提取提及关系
   - 关系变化追踪

### Phase 3: 图分析能力（3天）

1. **Day 10: 中心性分析**
   - PageRank 实现
   - 度中心性
   - 介数中心性

2. **Day 11: 社区发现**
   - Louvain 算法
   - 自动分组可视化

3. **Day 12: 相似度推荐**
   - 基于图结构的相似实体
   - "你可能感兴趣的..."

### Phase 4: 可视化（4-5天）

1. **Day 13-14: 图可视化**
   - D3.js / vis.js 力导向图
   - 节点类型着色
   - 关系标签

2. **Day 15-16: 时间线视图**
   - 实体演化时间线
   - 关系变化动画
   - 时间滑块过滤

3. **Day 17: 交互优化**
   - 点击节点查看详情
   - 拖拽编辑关系
   - 搜索高亮

---

## 💡 使用场景示例

### 场景 1：多跳关系查询

```
用户：谁创建了LifeBook系统？这个人还创建过什么项目？

Agent 调用 graph_query：
→ Cypher: MATCH (p:Entity)-[:RELATES_TO {relation_type:"创建"}]->
          (lb:Entity {name:"LifeBook系统"})
          MATCH (p)-[:RELATES_TO {relation_type:"创建"}]->(other)
          RETURN p, other

结果：主人创建了 LifeBook系统、LMArenaBridge、GreySoul Art Workshop...
```

### 场景 2：时间点查询

```
用户：2025年3月的时候，LifeBook系统是什么状态？

Agent 调用 temporal_snapshot：
→ entity: "LifeBook系统", time_point: "2025-03"

结果：
- 状态：开发中
- 版本：0.3.0
- 当时的功能：基础记忆、日记生成、关键词搜索
- 尚未实现：RAG语义搜索、消息编排器
```

### 场景 3：演化分析

```
用户：主人的技能栈在过去一年是怎么发展的？

Agent 调用 temporal_evolution：
→ entity: "主人", time_range: {start: "2025-01", end: "2026-01"}, aspect: "relations"

结果：
2025-01: 开始使用 DeepSeek
2025-03: 开始学习 Neo4j
2025-06: 掌握 RAG 技术
2025-09: 开始研究时序知识图谱
...
```

### 场景 4：中心性分析

```
用户：在我的知识图谱中，哪些概念最核心？

Agent 调用 centrality_analysis：
→ algorithm: "pagerank", entity_type: "概念", top_k: 5

结果：
1. 记忆管理 (PR: 0.85)
2. 知识图谱 (PR: 0.72)
3. AI对话 (PR: 0.68)
4. 项目开发 (PR: 0.55)
5. 时序数据 (PR: 0.42)
```

---

## ⚠️ 注意事项

### 数据一致性

- **主存储**：Markdown 文件是"单一事实源"
- **Neo4j**：作为索引/缓存，可从 Markdown 重建
- **同步策略**：写操作先写 Markdown，再同步到 Neo4j
- **冲突处理**：以 Markdown 为准

### 性能考虑

- Neo4j 社区版足够（单机 10M+ 节点）
- 大型图查询设置超时
- 时序快照按需创建（避免过多版本）

### 部署选项

1. **开发环境**：Docker 单容器
2. **生产环境**：独立 Neo4j 服务器
3. **轻量模式**：SQLite + 内存图（无需 Neo4j）

---

## 📦 依赖添加

```txt
# requirements.txt 新增
neo4j>=5.0.0          # Neo4j Python 驱动
networkx>=3.0         # 图算法（备用）
python-dateutil>=2.8  # 时间解析
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"  # Web UI
      - "7687:7687"  # Bolt
    environment:
      - NEO4J_AUTH=neo4j/lifebook123
      - NEO4J_PLUGINS=["apoc", "graph-data-science"]
    volumes:
      - neo4j_data:/data
      
volumes:
  neo4j_data:
```

---

## 🎯 预期收益

| 指标 | 当前 | 改造后 |
|------|------|--------|
| 关系查询复杂度 | O(n) 遍历文件 | O(1) 图遍历 |
| 多跳查询 | 不支持 | 原生支持 |
| 时间点查询 | 不支持 | 毫秒级 |
| 演化分析 | 不支持 | 支持 |
| 图可视化 | 静态 | 交互式 |
| 中心性分析 | 无 | PageRank 等 |
| 社区发现 | 无 | 自动聚类 |

---

*规划完成时间：2026-01-22*
*作者：灰魂* 😸
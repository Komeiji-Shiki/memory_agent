# 🗺️ LifeBook Memory Agent 开发路线图

> 本文档主要用于记录阶段性规划、设计思路与上下文恢复信息。
>
> ⚠️ 注意：本文档**不是当前实现的权威说明**，其中部分内容可能落后于实际代码。
> 当前运行方式、模型模式、管理页路径等，请优先以 [`README.md`](README.md) 和 [`MemoryRouter.route()`](memory_router.py:384) 对应的实际实现为准。

> 本文档包含完整的开发规划信息，用于上下文压缩后恢复工作状态

---

## 📋 项目当前状态 (2026-01-22)

### 已完成功能

| 模块 | 功能 | 状态 |
|------|------|------|
| **代理架构** | 双模型架构（Agent + 主模型） | ✅ 完成 |
| **分层记忆** | 短期/中短期/中期/长期记忆 | ✅ 完成 |
| **存储层** | Markdown 文件 + SQLite 索引 | ✅ 完成 |
| **检索** | 关键词搜索 + RAG 语义搜索 | ✅ 完成 |
| **会话管理** | 自动总结 + 睡眠间隔分割 | ✅ 完成 |
| **消息编排器** | 伪造对话历史 + 可视化编辑 | ✅ 完成 |
| **记忆工具** | 20+ 工具（读写编辑删除） | ✅ 完成 |
| **Web 管理** | 管理面板 + API | ✅ 完成 |

### 当前文件结构

```
i:/api聚合/记忆/
├── proxy_server.py        # 主入口
├── memory_router.py       # 记忆路由
├── config.jsonc           # 配置文件
│
├── proxy/                 # 代理服务模块
│   ├── config.py
│   ├── auth.py
│   ├── deepseek_proxy.py
│   └── routes/
│       ├── chat.py
│       ├── models.py
│       └── mcp.py
│
├── memory_agent/          # 记忆代理模块
│   ├── agent.py           # Agent 核心逻辑
│   ├── tools.py           # 20+ 记忆工具
│   ├── context_builder.py # 上下文组装
│   └── message_orchestrator.py # 消息编排器
│
├── memory_store/          # 存储层
│   ├── reader.py
│   ├── writer.py
│   ├── sqlite_indexer.py
│   ├── rag.py
│   ├── pending_manager.py
│   └── summary_generator.py
│
├── web/                   # Web 管理
│   ├── api.py
│   ├── core.py
│   ├── orchestrator_routes.py
│   └── admin.html
│
├── static/                # 前端资源
│   ├── css/admin.css
│   └── js/admin-*.js
│
└── lifebook/              # 记忆数据
    ├── .memory_index.db   # SQLite 索引
    ├── daily/             # 日记 (24篇)
    ├── nodes/             # 节点 (80+)
    ├── pending/           # 待处理暂存
    └── extra/             # 编排器配置
```

---

## 🎯 开发规划概览

### 三大改造方向

```
                    ┌─────────────────────────┐
                    │   LifeBook v2.0 升级    │
                    └────────────┬────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  方向1: 图存储   │   │  方向2: 检索策略  │   │  方向3: 可视化   │
│  Neo4j/Graphiti │   │  MemR3 整合      │   │  知识图谱展示   │
└─────────────────┘   └─────────────────┘   └─────────────────┘
```

---

## 📌 方向1: Neo4j + 时序知识图谱

### 目标
将知识图谱从 Markdown 解析升级为原生图数据库，支持时序查询

### 技术选型

| 方案 | 优势 | 劣势 | 推荐场景 |
|------|------|------|----------|
| **Graphiti + Kuzu** | 本地、无需服务、有论文支持 | 社区较小 | 开发/个人使用 |
| **Neo4j** | 成熟、生态完善 | 需要部署服务 | 生产环境 |
| **FalkorDB** | Redis 协议、快速 | 内存占用大 | 高性能需求 |

### Graphiti 关键概念

```python
# Graphiti 核心 API
from graphiti_core import Graphiti
from graphiti_core.driver.kuzu_driver import KuzuDriver

# 初始化（Kuzu 本地模式）
driver = KuzuDriver(db="./lifebook/.graphiti.kuzu")
graphiti = Graphiti(graph_driver=driver)

# 添加 episode（对话/日记片段）
await graphiti.add_episode(
    name="diary:2025-01-21",
    episode_body="今天继续开发LifeBook...",
    reference_time=datetime(2025, 1, 21, 10, 30)
)

# 混合搜索（语义+关键词+图遍历）
results = await graphiti.search("LifeBook开发进展", num_results=10)

# 时序查询（利用 bi-temporal 模型）
# valid_time: 事件发生时间
# transaction_time: 数据入库时间
```

### 数据模型设计

```cypher
// 实体节点
(:Entity {
  name: "灰魂",
  type: "人物",
  created_at: datetime(),
  file_path: "nodes/人物-灰魂.md"
})

// 时序属性快照
(:EntitySnapshot {
  entity_name: "LifeBook系统",
  valid_from: datetime("2025-01-01"),
  valid_to: null,  // 当前有效
  properties: {status: "开发中", version: "0.5.0"}
})

// 时序关系
(a)-[:RELATES_TO {
  relation_type: "创建",
  start_time: datetime("2025-01-01"),
  end_time: null,
  source: "diary:2025-01-01"
}]->(b)

// 日记提及
(:Diary)-[:MENTIONS {sentiment: "positive"}]->(:Entity)
```

### 新增文件

```
memory_store/
├── graphiti_adapter.py    # Graphiti 适配器
├── graph_sync.py          # Markdown ↔ Graphiti 同步
├── temporal_index.py      # 时序索引
└── graph_algorithms.py    # 图算法（PageRank等）
```

### 新增工具

```python
# 图查询工具
"graphiti_search"      # 混合搜索
"graph_query"          # 自然语言→Cypher
"find_path"            # 多跳路径
"cypher_query"         # 直接 Cypher

# 时序工具
"temporal_snapshot"    # 时间点查询
"temporal_evolution"   # 演化历史
"timeline_query"       # 事件时间线

# 图分析工具
"centrality_analysis"  # 中心性分析
"community_detection"  # 社区发现
"similar_entities"     # 相似推荐
```

### 配置新增

```jsonc
// config.jsonc
{
  "graphiti": {
    "enabled": true,
    "backend": "kuzu",  // kuzu | neo4j | falkordb
    "kuzu": {
      "db_path": "./lifebook/.graphiti.kuzu"
    },
    "neo4j": {
      "uri": "bolt://localhost:7687",
      "username": "neo4j",
      "password": ""
    },
    "sync": {
      "mode": "dual_write"  // dual_write | batch | manual
    }
  }
}
```

### 实施步骤 (5-7天)

1. **Day 1**: 安装 Graphiti，初始化 Kuzu
2. **Day 2-3**: 实现 `graphiti_adapter.py`
3. **Day 4**: 实现 `graph_sync.py` 同步机制
4. **Day 5**: 集成图查询工具到 `tools.py`
5. **Day 6-7**: 测试 + 时序工具

---

## 📌 方向2: MemR3 检索策略整合

### 目标
将单次检索升级为闭环迭代检索，引入 Evidence-Gap Tracker

### MemR3 核心机制

```
┌────────────────────────────────────────────────────┐
│                  MemR3 Pipeline                     │
│                                                    │
│   用户问题 → Router ──┬── Retrieve → 检索记忆      │
│                      │                             │
│                      ├── Reflect → 分析缺失        │
│                      │                             │
│                      └── Answer → 生成回复         │
│                                                    │
│   ┌─────────────────────────────────────────────┐  │
│   │         Evidence-Gap Tracker                │  │
│   │  Known: [已找到的证据]                      │  │
│   │  Missing: [仍需查找的信息]                  │  │
│   │  Query History: [查询历史]                  │  │
│   └─────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

### Evidence-Gap Tracker 实现

```python
# memory_agent/evidence_tracker.py

from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Evidence:
    """一条证据"""
    content: str
    source: str      # "diary:2025-01-21"
    confidence: float = 1.0
    timestamp: Optional[str] = None

@dataclass
class EvidenceGapTracker:
    """证据-缺口追踪器"""
    
    known: List[Evidence] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    query_history: List[str] = field(default_factory=list)
    
    def add_evidence(self, evidence: Evidence):
        self.known.append(evidence)
        self._check_gaps_filled(evidence)
    
    def add_gap(self, gap: str):
        if gap not in self.missing:
            self.missing.append(gap)
    
    def is_sufficient(self) -> bool:
        return len(self.missing) == 0
    
    def get_refined_query(self) -> str:
        if not self.missing:
            return ""
        return f"搜索: {', '.join(self.missing[:3])}"
    
    def to_prompt_context(self) -> str:
        ctx = "## 已知信息\n"
        for e in self.known:
            ctx += f"- [{e.source}] {e.content[:100]}...\n"
        if self.missing:
            ctx += "\n## 仍需查找\n"
            for m in self.missing:
                ctx += f"- {m}\n"
        return ctx
```

### MemR3 Agent 实现

```python
# memory_agent/memr3_agent.py

from enum import Enum

class AgentState(Enum):
    RETRIEVE = "retrieve"
    REFLECT = "reflect"
    ANSWER = "answer"

class MemR3Agent:
    def __init__(self, ...):
        self.tracker = EvidenceGapTracker()
        self.max_iterations = 5
    
    async def run(self, query: str) -> str:
        self.tracker.add_gap(query)
        
        for i in range(self.max_iterations):
            state = self._route()
            
            if state == AgentState.RETRIEVE:
                await self._retrieve()
            elif state == AgentState.REFLECT:
                await self._reflect()
            elif state == AgentState.ANSWER:
                break
        
        return self._generate_briefing()
    
    def _route(self) -> AgentState:
        if self.tracker.is_sufficient():
            return AgentState.ANSWER
        if len(self.tracker.query_history) > 0:
            return AgentState.REFLECT
        return AgentState.RETRIEVE
    
    async def _retrieve(self):
        query = self.tracker.get_refined_query()
        results = await self.search(query)
        for r in results:
            self.tracker.add_evidence(Evidence(
                content=r.content,
                source=r.source
            ))
        self.tracker.query_history.append(query)
    
    async def _reflect(self):
        # 让 LLM 分析还缺什么信息
        prompt = f"已知: {self.tracker.known}\n分析还需要什么信息?"
        response = await self.llm.generate(prompt)
        for gap in parse_gaps(response):
            self.tracker.add_gap(gap)
```

### 新增文件

```
memory_agent/
├── evidence_tracker.py    # Evidence-Gap Tracker
├── memr3_agent.py         # MemR3 风格 Agent
└── router.py              # 动态路由决策
```

### 配置新增

```jsonc
{
  "memr3": {
    "enabled": true,
    "max_iterations": 5,
    "min_confidence": 0.7,
    "early_stop": true,
    "reflect_threshold": 2
  },
  "evidence_tracker": {
    "enabled": true,
    "similarity_threshold": 0.8,
    "max_gaps": 5
  }
}
```

### 实施步骤 (4-5天)

1. **Day 1**: 实现 `evidence_tracker.py`
2. **Day 2-3**: 实现 `memr3_agent.py`
3. **Day 4**: 集成到现有 Agent 流程
4. **Day 5**: 测试 + 调优

---

## 📌 方向3: 知识图谱可视化

### 目标
在 Web 管理面板中展示交互式知识图谱

### 技术选型

| 库 | 特点 | 适用场景 |
|---|------|---------|
| **D3.js** | 灵活、可定制 | 复杂定制需求 |
| **vis.js** | 开箱即用 | 快速实现 |
| **Cytoscape.js** | 专业图可视化 | 学术/专业 |

### 前端组件

```javascript
// static/js/admin-graph.js

class GraphVisualization {
    constructor(container) {
        this.container = container;
        this.network = null;
    }
    
    async loadGraph() {
        const response = await fetch('/api/memory/graph');
        const data = await response.json();
        this.render(data);
    }
    
    render(data) {
        const nodes = data.entities.map(e => ({
            id: e.name,
            label: e.name,
            group: e.type  // 按类型着色
        }));
        
        const edges = data.relations.map(r => ({
            from: r.from,
            to: r.to,
            label: r.type
        }));
        
        this.network = new vis.Network(
            this.container,
            { nodes, edges },
            this.getOptions()
        );
    }
    
    getOptions() {
        return {
            groups: {
                '人物': { color: '#ff6b6b' },
                '事物': { color: '#4dabf7' },
                '概念': { color: '#69db7c' },
                '地点': { color: '#ffd43b' }
            },
            physics: {
                stabilization: { iterations: 100 }
            }
        };
    }
}
```

### 时间线视图

```javascript
// 使用 vis-timeline 展示实体演化
class TimelineView {
    async showEntityHistory(entityName) {
        const response = await fetch(
            `/api/memory/timeline/${entityName}`
        );
        const events = await response.json();
        
        const items = events.map(e => ({
            id: e.id,
            content: e.description,
            start: e.timestamp,
            type: 'point'
        }));
        
        new vis.Timeline(
            this.container,
            new vis.DataSet(items)
        );
    }
}
```

### 后端 API

```python
# web/graph_routes.py

@graph_bp.route('/graph', methods=['GET'])
def get_graph():
    """获取完整知识图谱"""
    entities = get_all_entities()
    relations = get_all_relations()
    return jsonify({
        'entities': entities,
        'relations': relations
    })

@graph_bp.route('/timeline/<entity>', methods=['GET'])
def get_timeline(entity: str):
    """获取实体时间线"""
    events = get_entity_history(entity)
    return jsonify(events)

@graph_bp.route('/path', methods=['POST'])
def find_path():
    """查找两节点间路径"""
    data = request.json
    paths = find_all_paths(
        data['from'],
        data['to'],
        data.get('max_hops', 4)
    )
    return jsonify(paths)
```

### 实施步骤 (4-5天)

1. **Day 1**: 添加 vis.js 依赖，基础图渲染
2. **Day 2**: 实现节点着色、交互
3. **Day 3**: 实现时间线视图
4. **Day 4**: 集成到管理面板
5. **Day 5**: 优化性能 + 样式

---

## 📅 完整时间线

```
2026-01-22 ──┬── 规划文档完成
             │
Week 1 ──────┼── Phase 1: Graphiti 集成
             │   ├── Day 1: 环境搭建
             │   ├── Day 2-3: 适配器实现
             │   ├── Day 4: 同步机制
             │   └── Day 5-7: 工具集成
             │
Week 2 ──────┼── Phase 2: MemR3 检索策略
             │   ├── Day 8-9: Evidence Tracker
             │   └── Day 10-12: Agent 重构
             │
Week 3 ──────┼── Phase 3: 可视化
             │   ├── Day 13-14: 图渲染
             │   └── Day 15-17: 时间线 + 优化
             │
2026-02-10 ──┴── v2.0 完成
```

---

## 🔧 快速恢复指南

### 如果上下文丢失，请按以下顺序阅读：

1. **本文档** - 了解整体规划
2. **规划五-Neo4j时序知识图谱改造.md** - Neo4j 详细设计
3. **规划六-MemR3与Graphiti整合分析.md** - MemR3/Graphiti 整合
4. **README.md** - 项目功能概览
5. **ARCHITECTURE.md** - 代码架构

### 关键依赖

```bash
# 核心依赖
pip install flask flask-cors jieba pyyaml requests openai httpx

# 新增依赖（规划中）
pip install graphiti-core[kuzu]  # 图存储
pip install neo4j                # 可选 Neo4j
pip install networkx             # 图算法备用
```

### 启动命令

```bash
# 启动服务
python proxy_server.py

# 或 Windows
点击运行.cmd

# 访问管理面板
http://127.0.0.1:8003/lifebook-admin
```

---

## 📝 待办清单

- [ ] **Phase 1**: Graphiti 集成
  - [ ] 安装 graphiti-core[kuzu]
  - [ ] 实现 graphiti_adapter.py
  - [ ] 实现 graph_sync.py
  - [ ] 添加图查询工具
  - [ ] 添加时序工具
  
- [ ] **Phase 2**: MemR3 整合
  - [ ] 实现 evidence_tracker.py
  - [ ] 实现 memr3_agent.py
  - [ ] 重构 agent.py
  
- [ ] **Phase 3**: 可视化
  - [ ] 添加 vis.js
  - [ ] 实现图渲染
  - [ ] 实现时间线
  - [ ] 集成到管理面板

---

*文档创建时间：2026-01-22 13:44*
*作者：灰魂* 😸
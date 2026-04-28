# 🔗 MemR3 + Graphiti 整合分析

## 📋 项目概览

### MemR3 - 记忆推理与检索代理

> 一个用于长对话问答的**闭环检索**系统

**核心创新点**：
```
┌─────────────────────────────────────────────────────────┐
│                    MemR3 Pipeline                       │
│                                                         │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐           │
│   │ Retrieve │◄──│  Router  │──►│  Answer  │           │
│   └────┬─────┘   └────▲─────┘   └──────────┘           │
│        │              │                                 │
│        ▼              │                                 │
│   ┌──────────┐        │                                 │
│   │ Reflect  │────────┘                                 │
│   └──────────┘                                          │
│                                                         │
│   📊 Evidence-Gap Tracker                               │
│   ├── Known: [已知信息列表]                             │
│   └── Missing: [待查信息列表]                           │
└─────────────────────────────────────────────────────────┘
```

**关键机制**：
1. **Router 动态路由**：根据当前状态决定下一步是检索、反思还是回答
2. **Evidence-Gap Tracker**：维护"已知"和"缺失"信息列表
3. **迭代查询细化**：根据反思结果优化检索查询
4. **早停机制**：证据足够时停止检索

---

### Graphiti - 实时时序知识图谱

> Zep 团队开源的时序知识图谱框架（有论文 arXiv:2501.13956）

**核心特性**：
- **Bi-Temporal 双时间模型**：事件发生时间 + 入库时间
- **增量更新**：无需批量重算
- **混合检索**：语义嵌入 + BM25 + 图遍历
- **自定义实体**：Pydantic 定义节点类型
- **多后端支持**：Neo4j / FalkorDB / Kuzu / Neptune

**数据模型**：
```
Episode (对话片段)
    │
    ▼
┌─────────────────────────────────────────────┐
│           Graphiti Knowledge Graph           │
│                                             │
│   (Entity)───[:RELATES_TO]───(Entity)       │
│      │                          │           │
│      │ valid_from: datetime     │           │
│      │ valid_to: datetime       │           │
│      │                          │           │
│   (Node)───[:MENTIONS]───(Diary)            │
│                                             │
└─────────────────────────────────────────────┘
```

---

## 🎯 整合方案

### 方案对比

| 方案 | 描述 | 优势 | 劣势 |
|------|------|------|------|
| **A. 直接使用 Graphiti** | 用 Graphiti 替换当前存储层 | 成熟、有论文支持、MCP Server | 需要适配现有 Markdown 格式 |
| **B. 借鉴 MemR3 改进 Agent** | 引入 Evidence-Gap Tracker | 提升检索精度 | 仅改进检索，不涉及存储 |
| **C. 混合整合** | Graphiti 做图存储 + MemR3 做检索策略 | 最佳组合 | 工作量较大 |

**推荐：方案 C - 混合整合**

---

## 🏗️ 混合整合架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         LifeBook v2.0                                │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                     Memory Agent (MemR3-Enhanced)              │  │
│  │                                                                │  │
│  │   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   │  │
│  │   │ Retrieve │◄──│  Router  │──►│  Answer  │   │ Reflect  │   │  │
│  │   └────┬─────┘   └────▲─────┘   └──────────┘   └────┬─────┘   │  │
│  │        │              │                             │         │  │
│  │        │         ┌────┴────┐                        │         │  │
│  │        └────────►│ Tracker │◄───────────────────────┘         │  │
│  │                  │ (已知/缺失) │                               │  │
│  │                  └─────────┘                                   │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                   Storage Adapter Layer                        │  │
│  │                                                                │  │
│  │   ┌─────────────┐   ┌─────────────┐   ┌─────────────────────┐ │  │
│  │   │  Markdown   │   │  Graphiti   │   │  SQLite Indexer     │ │  │
│  │   │  (主存储)   │◄──│  (图索引)   │   │  (关键词/RAG)       │ │  │
│  │   └─────────────┘   └─────────────┘   └─────────────────────┘ │  │
│  │         ▲                  │                    ▲              │  │
│  │         │                  ▼                    │              │  │
│  │         │           ┌─────────────┐             │              │  │
│  │         └───────────│  双向同步   │─────────────┘              │  │
│  │                     └─────────────┘                            │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                      Graph Database                            │  │
│  │                                                                │  │
│  │   Neo4j │ FalkorDB │ Kuzu (本地轻量)                          │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📦 整合步骤

### Phase 1: 引入 Graphiti 作为图存储层 (5-7天)

#### 1.1 安装与配置

```bash
# requirements.txt 新增
graphiti-core>=0.17.0
graphiti-core[kuzu]      # 或 [neo4j] / [falkordb]
```

```python
# config.jsonc 新增
"graphiti": {
    "enabled": true,
    "backend": "kuzu",  // kuzu(本地) | neo4j | falkordb
    "kuzu_path": "./lifebook/.graphiti.kuzu",
    "neo4j": {
        "uri": "bolt://localhost:7687",
        "username": "neo4j",
        "password": "..."
    }
}
```

#### 1.2 适配器实现

```python
# memory_store/graphiti_adapter.py

from graphiti_core import Graphiti
from graphiti_core.driver.kuzu_driver import KuzuDriver
from pathlib import Path

class GraphitiAdapter:
    """Graphiti 适配器 - 桥接 LifeBook 与 Graphiti"""
    
    def __init__(self, config: dict, lifebook_path: str):
        self.lifebook_path = Path(lifebook_path)
        
        # 初始化 Graphiti
        if config.get("backend") == "kuzu":
            driver = KuzuDriver(db=config.get("kuzu_path"))
        else:
            # Neo4j 等其他后端
            driver = ...
        
        self.graphiti = Graphiti(graph_driver=driver)
    
    async def add_episode(
        self,
        content: str,
        source: str,  # "diary:2025-01-21" | "node:人物-灰魂"
        timestamp: datetime
    ):
        """将内容添加为 Graphiti episode"""
        await self.graphiti.add_episode(
            name=source,
            episode_body=content,
            source_description=f"LifeBook {source}",
            reference_time=timestamp
        )
    
    async def search(
        self,
        query: str,
        num_results: int = 10
    ) -> list:
        """混合搜索（语义+关键词+图遍历）"""
        return await self.graphiti.search(query, num_results=num_results)
    
    async def temporal_query(
        self,
        entity: str,
        time_point: datetime
    ) -> dict:
        """时间点查询"""
        # 利用 Graphiti 的双时间模型
        ...
    
    async def sync_from_markdown(self):
        """从 Markdown 文件同步到 Graphiti"""
        # 遍历 daily/, nodes/ 目录
        # 解析文件并添加为 episode
        ...
```

#### 1.3 新增工具

```python
# memory_agent/tools.py 新增

"graphiti_search": {
    "name": "graphiti_search",
    "description": "使用 Graphiti 进行混合搜索（语义+图遍历）",
    "parameters": {
        "query": {"type": "string"},
        "num_results": {"type": "integer", "default": 10}
    }
}

"graphiti_temporal": {
    "name": "graphiti_temporal",
    "description": "查询某时间点的知识状态",
    "parameters": {
        "entity": {"type": "string"},
        "time_point": {"type": "string"}
    }
}
```

---

### Phase 2: 引入 MemR3 检索策略 (4-5天)

#### 2.1 Evidence-Gap Tracker

```python
# memory_agent/evidence_tracker.py

from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Evidence:
    """一条证据"""
    content: str
    source: str  # "diary:2025-01-21", "node:灰魂"
    confidence: float = 1.0
    timestamp: Optional[str] = None

@dataclass
class EvidenceGapTracker:
    """证据-缺口追踪器"""
    
    known: List[Evidence] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    query_history: List[str] = field(default_factory=list)
    
    def add_evidence(self, evidence: Evidence):
        """添加已知证据"""
        self.known.append(evidence)
        # 检查是否填补了某个缺口
        self._check_gaps_filled(evidence)
    
    def add_gap(self, gap: str):
        """添加缺失信息"""
        if gap not in self.missing:
            self.missing.append(gap)
    
    def _check_gaps_filled(self, evidence: Evidence):
        """检查新证据是否填补了缺口"""
        # 使用语义相似度判断
        ...
    
    def is_sufficient(self) -> bool:
        """判断证据是否足够回答问题"""
        return len(self.missing) == 0
    
    def get_refined_query(self) -> str:
        """生成细化的查询"""
        if not self.missing:
            return ""
        # 基于缺失信息生成新查询
        return f"搜索关于: {', '.join(self.missing[:3])}"
    
    def to_prompt_context(self) -> str:
        """转换为提示词上下文"""
        context = "## 已知信息\n"
        for e in self.known:
            context += f"- [{e.source}] {e.content[:100]}...\n"
        
        if self.missing:
            context += "\n## 仍需查找\n"
            for m in self.missing:
                context += f"- {m}\n"
        
        return context
```

#### 2.2 MemR3 风格的 Agent 重构

```python
# memory_agent/memr3_agent.py

from enum import Enum

class AgentState(Enum):
    RETRIEVE = "retrieve"
    REFLECT = "reflect"
    ANSWER = "answer"

class MemR3Agent:
    """MemR3 风格的记忆代理"""
    
    def __init__(self, ...):
        self.tracker = EvidenceGapTracker()
        self.max_iterations = 5
    
    async def run(self, query: str, context: List[dict]) -> str:
        """主运行循环"""
        
        # 初始化缺口
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
        """路由决策"""
        if self.tracker.is_sufficient():
            return AgentState.ANSWER
        
        # 检查是否需要反思（已检索但信息不完整）
        if len(self.tracker.query_history) > 0 and not self.tracker.is_sufficient():
            return AgentState.REFLECT
        
        return AgentState.RETRIEVE
    
    async def _retrieve(self):
        """检索阶段"""
        query = self.tracker.get_refined_query() or self.original_query
        
        # 使用 Graphiti 混合搜索
        results = await self.graphiti.search(query)
        
        for r in results:
            self.tracker.add_evidence(Evidence(
                content=r.content,
                source=r.source
            ))
        
        self.tracker.query_history.append(query)
    
    async def _reflect(self):
        """反思阶段 - 分析缺失信息"""
        prompt = f"""
分析当前检索结果，判断还缺少什么信息：

用户问题：{self.original_query}

{self.tracker.to_prompt_context()}

请列出还需要查找的信息（每行一条）：
"""
        response = await self.llm.generate(prompt)
        
        # 解析缺失信息
        for line in response.strip().split('\n'):
            if line.startswith('- '):
                self.tracker.add_gap(line[2:])
    
    def _generate_briefing(self) -> str:
        """生成最终简报"""
        return self.tracker.to_prompt_context()
```

---

### Phase 3: MCP Server 集成 (2-3天)

Graphiti 自带 MCP Server，可以直接让 Claude/Cursor 使用！

```yaml
# mcp_config.json
{
  "mcpServers": {
    "graphiti": {
      "command": "python",
      "args": ["-m", "graphiti_core.mcp_server"],
      "env": {
        "GRAPHITI_DB_PATH": "./lifebook/.graphiti.kuzu",
        "OPENAI_API_KEY": "..."
      }
    },
    "lifebook": {
      "command": "python", 
      "args": ["./mcp_server.py"],
      "env": {}
    }
  }
}
```

---

## 🔧 配置示例

```jsonc
// config.jsonc 完整新增配置
{
    // ... 现有配置 ...
    
    // Graphiti 图存储
    "graphiti": {
        "enabled": true,
        "backend": "kuzu",  // kuzu | neo4j | falkordb
        
        // Kuzu 本地图数据库（推荐开发环境）
        "kuzu": {
            "db_path": "./lifebook/.graphiti.kuzu"
        },
        
        // Neo4j（推荐生产环境）
        "neo4j": {
            "uri": "bolt://localhost:7687",
            "username": "neo4j",
            "password": "",
            "database": "lifebook"
        },
        
        // 同步设置
        "sync": {
            "mode": "dual_write",  // dual_write | batch | manual
            "batch_interval_hours": 1
        }
    },
    
    // MemR3 检索策略
    "memr3": {
        "enabled": true,
        "max_iterations": 5,      // 最大检索-反思循环次数
        "min_confidence": 0.7,    // 证据置信度阈值
        "early_stop": true,       // 证据足够时提前停止
        "reflect_threshold": 2    // 多少次检索后触发反思
    },
    
    // Evidence-Gap Tracker
    "evidence_tracker": {
        "enabled": true,
        "similarity_threshold": 0.8,  // 判断缺口是否被填补的相似度阈值
        "max_gaps": 5                 // 最多追踪的缺口数
    }
}
```

---

## 📊 预期收益

| 能力 | 当前 | Graphiti 整合后 | MemR3 整合后 |
|------|------|-----------------|--------------|
| 关系查询 | O(n) 遍历 | O(1) 图遍历 | - |
| 时序查询 | 不支持 | 原生支持 | - |
| 检索精度 | 单次查询 | 混合检索 | 迭代细化 |
| 缺失信息感知 | 无 | 无 | Evidence-Gap |
| 早停机制 | 固定轮数 | - | 证据足够即停 |
| 图可视化 | 无 | 有 | - |

### 使用场景示例

**场景：复杂时序问题**

```
用户：去年我做LifeBook项目时，最大的技术难题是什么？后来怎么解决的？

MemR3 Agent 行为：
├── Act 0: 初始化
│   └── Gap: ["去年LifeBook技术难题", "解决方案"]
│
├── Act 1: Retrieve
│   └── Query: "LifeBook 技术难题"
│   └── Found: [日记:2025-03-15 提到工具调用问题]
│   └── Known: ["工具调用兼容性问题"]
│   └── Gap: ["解决方案"]
│
├── Act 2: Reflect
│   └── 分析：已知难题，但缺少解决过程
│   └── Refined Query: "LifeBook 工具调用 解决方案"
│
├── Act 3: Retrieve (Graphiti temporal)
│   └── 查询 2025-04 时间段的变更
│   └── Found: [节点更新历史显示添加了 XML 解析器]
│   └── Known: ["工具调用问题", "XML解析器解决方案"]
│   └── Gap: [] ← 已填补
│
├── Act 4: Answer
│   └── 生成简报给主模型
```

---

## ⚠️ 注意事项

### 兼容性
- Graphiti 需要 Python 3.10+
- Kuzu 是纯本地方案，无需外部服务
- 现有 Markdown 文件保持不变

### 性能
- 首次同步需要遍历所有文件
- 增量同步延迟约 100-500ms
- Kuzu 单机可处理百万节点

### 迁移策略
- 先以只读模式集成 Graphiti
- 验证搜索结果正确性
- 再开启双写模式

---

## 📅 实施时间线

| 阶段 | 任务 | 天数 |
|------|------|------|
| Phase 1.1 | Graphiti 安装配置 | 1 |
| Phase 1.2 | 适配器实现 | 2-3 |
| Phase 1.3 | 同步机制 | 2 |
| Phase 1.4 | 工具集成 | 1-2 |
| Phase 2.1 | Evidence-Gap Tracker | 2 |
| Phase 2.2 | MemR3 Agent 重构 | 2-3 |
| Phase 3 | MCP Server 集成 | 2-3 |
| **总计** | | **12-16天** |

---

## 🔗 参考资料

- [MemR3 GitHub](https://github.com/...)
- [Graphiti GitHub](https://github.com/getzep/graphiti)
- [Graphiti 论文](https://arxiv.org/abs/2501.13956)
- [Zep Documentation](https://help.getzep.com/graphiti)

---

*分析完成时间：2026-01-22*
*作者：灰魂* 😸
# 🔧 分规划二：Graphiti 工具集成

## 📋 概述

本分规划对应总规划的 **Phase 1.3**，负责将 Graphiti 适配器暴露为 Memory Agent 可调用的工具。

**目标**：
1. 创建 Graphiti 工具定义（`graphiti_tools.py`）
2. 将工具注册到 `MemoryTools` 类
3. 支持检索小模型和主模型都能调用 Graphiti
4. 实现与现有工具的无缝切换（可配置启用/禁用）

**依赖**：分规划一（`GraphitiAdapter` 已实现）

**预计工期**：2-3 天

---

## 🏗️ 现有架构分析

### 当前工具体系

```
memory_agent/
├── tools.py              ← MemoryTools 类（核心工具管理器）
│   ├── ToolDefinition    # 工具定义 dataclass
│   ├── ToolCategory      # 工具类别枚举
│   ├── _register_tools() # 工具注册
│   ├── call_tool()       # 工具调用
│   └── get_openai_tools() # 转为 OpenAI 格式
│
├── agent.py              ← MemoryAgent（检索小模型）
│   ├── retrieve()        # 同步检索
│   ├── retrieve_stream() # 流式检索
│   └── _run_agent_loop() # Agent 循环
│
└── context_builder.py    ← ContextBuilder（上下文组装）
    ├── build()           # 组装上下文
    └── _build_fixed_context() # 固定记忆
```

### 现有工具列表

| 类别 | 工具名 | 功能 |
|------|--------|------|
| SEARCH | `search_memories` | 关键词搜索 |
| SEARCH | `rag_search` | 语义搜索（可选） |
| READ | `read_diary` | 读日记 |
| READ | `read_summary` | 读总结 |
| READ | `get_node` | 获取节点 |
| READ | `list_recent` | 最近日记 |
| READ | `get_memory_overview` | 记忆概览 |
| READ | `read_all_nodes` | 读所有节点 |
| READ | `read_graph` | 读知识图谱 |
| WRITE | `add_to_diary` | 写日记 |
| WRITE | `create_node` | 创建节点 |
| WRITE | `create_relations` | 创建关系 |
| ... | ... | ... |

### 集成策略

采用 **扩展注册** 模式：在 `MemoryTools._register_tools()` 中**条件注册** Graphiti 工具。

```python
# memory_agent/tools.py (新增)
if self.graphiti_enabled:
    self._register_graphiti_tools()
```

**优点**：
- 复用现有的工具管理机制
- 无需修改 Agent 调用逻辑
- 配置驱动，易于开关

---

## ✅ 任务清单

### 1. 创建 Graphiti 工具定义 (1天)

- [x] **1.1 创建 `memory_agent/graphiti_tools.py`**

```python
"""
Graphiti 工具定义
提供时序知识图谱的搜索、时间点查询、添加等工具
"""

from typing import Dict, Any

# 工具定义常量
GRAPHITI_TOOLS_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "graphiti_search": {
        "name": "graphiti_search",
        "description": """使用 Graphiti 进行混合搜索（语义 + BM25 + 图遍历）。
适用场景：
- 查找相关记忆和事实
- 探索实体之间的关系
- 需要多跳推理的问题（如"主人开发的项目用了什么技术"）

与 search_memories 的区别：
- search_memories: 基于 SQLite 关键词索引，速度快，适合精确匹配
- graphiti_search: 基于图数据库 + 向量索引，支持语义相似和关系遍历""",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询（自然语言描述）"
                },
                "num_results": {
                    "type": "integer",
                    "description": "返回结果数量，默认10",
                    "default": 10
                },
                "include_edges": {
                    "type": "boolean",
                    "description": "是否包含关系边（默认true）",
                    "default": True
                },
                "include_nodes": {
                    "type": "boolean",
                    "description": "是否包含实体节点（默认true）",
                    "default": True
                }
            },
            "required": ["query"]
        }
    },
    
    "graphiti_temporal": {
        "name": "graphiti_temporal",
        "description": """查询某个时间点的知识状态（时序查询）。
利用 Graphiti 的 Bi-Temporal 模型，可以回答：
- "2025年3月时，这个项目是什么状态？"
- "那时候主人在学什么技术？"
- "去年12月主人和小明是什么关系？"

⚠️ 注意：只能查询记忆库范围内的时间点，更早的时间没有记录。""",
        "parameters": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "要查询的实体名称（如'主人'、'LifeBook项目'）"
                },
                "time_point": {
                    "type": "string",
                    "description": "时间点，格式 YYYY-MM-DD 或 YYYY-MM（如'2025-03-15'或'2025-03'）"
                },
                "num_results": {
                    "type": "integer",
                    "description": "返回结果数量，默认30",
                    "default": 30
                }
            },
            "required": ["entity", "time_point"]
        }
    },
    
    "graphiti_add": {
        "name": "graphiti_add",
        "description": """添加新的知识片段到 Graphiti 时序图谱。
Graphiti 会自动：
1. 从内容中提取实体和关系
2. 与已有知识去重/合并
3. 添加时间戳（Bi-Temporal）

适用场景：
- 手动添加重要事实（如"主人学会了 Rust"）
- 索引对话中发现的新信息
- 补充 Markdown 节点外的知识""",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要添加的知识内容（自然语言描述）"
                },
                "source": {
                    "type": "string",
                    "description": "来源标识（如'conversation'、'manual'）",
                    "default": "tool_call"
                }
            },
            "required": ["content"]
        }
    },
    
    "graphiti_multi_hop": {
        "name": "graphiti_multi_hop",
        "description": """多跳关系查询。
从指定实体出发，沿着关系边遍历，找到N跳之内的相关实体。

适用场景：
- "主人开发的项目用了什么技术？"（主人→开发→项目→使用→技术，2跳）
- "和主人一起工作的人都负责什么？"（主人→同事→负责→项目，2跳）
- "这个概念相关的其他概念有哪些？"（概念→关联→概念，1跳）

⚠️ 跳数越多，结果越多但相关性可能降低。""",
        "parameters": {
            "type": "object",
            "properties": {
                "start_entity": {
                    "type": "string",
                    "description": "起始实体名称"
                },
                "max_hops": {
                    "type": "integer",
                    "description": "最大跳数（1-3），默认2",
                    "default": 2,
                    "minimum": 1,
                    "maximum": 3
                },
                "relation_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定关系类型（可选，如['开发', '使用']）"
                },
                "num_results": {
                    "type": "integer",
                    "description": "每跳最大结果数，默认10",
                    "default": 10
                }
            },
            "required": ["start_entity"]
        }
    },
    
    "graphiti_sync_node": {
        "name": "graphiti_sync_node",
        "description": """将指定的 Markdown 节点同步到 Graphiti。
用于手动触发节点同步，适合：
- 刚创建/更新的节点
- 确保 Graphiti 中有最新版本

正常情况下节点会自动同步，只有需要立即更新时才调用此工具。""",
        "parameters": {
            "type": "object",
            "properties": {
                "node_name": {
                    "type": "string",
                    "description": "节点名称（不含类型前缀）"
                }
            },
            "required": ["node_name"]
        }
    }
}
```

- [x] **1.2 创建工具处理函数骨架**

```python
# graphiti_tools.py (续)

from typing import Optional, List
from datetime import datetime
from dataclasses import dataclass

@dataclass
class GraphitiToolResult:
    """Graphiti 工具执行结果"""
    success: bool
    content: str
    source_count: int = 0
    iteration_count: int = 1  # 用于迭代检索时
    

class GraphitiToolHandlers:
    """
    Graphiti 工具处理函数集合
    
    设计为可独立测试的类，由 MemoryTools 实例化并注入 adapter
    """
    
    def __init__(self, graphiti_adapter):
        """
        Args:
            graphiti_adapter: GraphitiAdapter 或 GraphitiSyncAdapter 实例
        """
        self.adapter = graphiti_adapter
        self._initialized = False
    
    async def _ensure_initialized(self):
        """确保 adapter 已初始化"""
        if not self._initialized:
            if hasattr(self.adapter, 'initialize'):
                await self.adapter.initialize()
            self._initialized = True
    
    def graphiti_search(
        self,
        query: str,
        num_results: int = 10,
        include_edges: bool = True,
        include_nodes: bool = True
    ) -> str:
        """
        Graphiti 混合搜索
        
        返回格式化的搜索结果字符串
        """
        try:
            results = self.adapter.search(
                query=query,
                num_results=num_results,
                include_edges=include_edges,
                include_nodes=include_nodes
            )
            
            if not results:
                return f"未找到与 '{query}' 相关的记忆。"
            
            output = f"🔍 Graphiti 搜索结果（共 {len(results)} 条）：\n\n"
            
            for i, r in enumerate(results, 1):
                result_type = r.get("type", "unknown")
                icon = "🔗" if result_type == "edge" else "📌"
                
                content = r.get("content", "")
                score = r.get("score", 0)
                source = r.get("source", "")
                
                # 时序信息
                valid_at = r.get("valid_at")
                invalid_at = r.get("invalid_at")
                time_info = ""
                if valid_at:
                    time_info = f" [生效: {valid_at[:10]}"
                    if invalid_at:
                        time_info += f" → 失效: {invalid_at[:10]}"
                    time_info += "]"
                
                output += f"{i}. {icon} {content[:200]}\n"
                output += f"   来源: {source} | 相关度: {score:.2f}{time_info}\n\n"
            
            return output
            
        except Exception as e:
            return f"❌ Graphiti 搜索失败: {str(e)}"
    
    def graphiti_temporal(
        self,
        entity: str,
        time_point: str,
        num_results: int = 30
    ) -> str:
        """
        时间点查询
        
        返回该实体在指定时间点的状态
        """
        try:
            # 解析时间点
            if len(time_point) == 7:  # YYYY-MM
                dt = datetime.strptime(time_point + "-15", "%Y-%m-%d")
            else:  # YYYY-MM-DD
                dt = datetime.strptime(time_point, "%Y-%m-%d")
            
            result = self.adapter.temporal_query(
                entity_name=entity,
                time_point=dt,
                num_results=num_results
            )
            
            facts = result.get("facts", [])
            if not facts:
                return f"未找到 '{entity}' 在 {time_point} 的相关记录。"
            
            output = f"📅 时间点查询：{entity} @ {time_point}\n\n"
            output += f"找到 {len(facts)} 条在该时间有效的事实：\n\n"
            
            for fact in facts:
                content = fact.get("fact", "")
                valid_from = fact.get("valid_from", "")
                valid_to = fact.get("valid_to", "持续中")
                source = fact.get("source", "")
                
                output += f"- {content}\n"
                output += f"  有效期: {valid_from or '未知'} → {valid_to}\n"
                output += f"  来源: {source}\n\n"
            
            return output
            
        except ValueError as e:
            return f"❌ 时间格式错误: {str(e)}。请使用 YYYY-MM-DD 或 YYYY-MM 格式。"
        except Exception as e:
            return f"❌ 时间点查询失败: {str(e)}"
    
    def graphiti_add(
        self,
        content: str,
        source: str = "tool_call"
    ) -> str:
        """
        添加知识片段到 Graphiti
        """
        try:
            from memory_store.graphiti_adapter import EpisodeType
            
            episode_id = self.adapter.add_episode(
                content=content,
                source=source,
                episode_type=EpisodeType.CONVERSATION
            )
            
            if episode_id:
                return f"✓ 知识已添加到 Graphiti（ID: {episode_id[:8]}...）\n内容将自动提取实体和关系。"
            else:
                return "⚠️ 内容已接收但未索引（可能被价值过滤器过滤）"
                
        except Exception as e:
            return f"❌ 添加失败: {str(e)}"
    
    def graphiti_multi_hop(
        self,
        start_entity: str,
        max_hops: int = 2,
        relation_types: Optional[List[str]] = None,
        num_results: int = 10
    ) -> str:
        """
        多跳关系查询
        
        TODO: 需要在 GraphitiAdapter 中实现 multi_hop_query 方法
        """
        try:
            # 暂时用搜索模拟
            query = f"{start_entity} 相关"
            results = self.adapter.search(query, num_results=num_results)
            
            if not results:
                return f"未找到从 '{start_entity}' 出发的关系路径。"
            
            output = f"🕸️ 多跳查询：{start_entity}（最大 {max_hops} 跳）\n\n"
            output += f"找到 {len(results)} 条相关路径：\n\n"
            
            for i, r in enumerate(results, 1):
                content = r.get("content", "")
                output += f"{i}. {content[:150]}\n"
            
            return output
            
        except Exception as e:
            return f"❌ 多跳查询失败: {str(e)}"
    
    def graphiti_sync_node(
        self,
        node_name: str
    ) -> str:
        """
        手动同步指定节点到 Graphiti
        """
        try:
            from memory_store.graphiti_adapter import EpisodeType
            from memory_store.reader import LifeBookReader
            
            # 读取节点内容
            # 注意：需要从配置获取 lifebook_path
            # 这里假设 adapter 有 lifebook_path 属性
            lifebook_path = getattr(self.adapter, 'lifebook_path', None)
            if not lifebook_path:
                return "❌ 无法获取 lifebook 路径"
            
            reader = LifeBookReader(str(lifebook_path))
            node = reader.read_node(node_name)
            
            if not node:
                return f"❌ 未找到节点 [[{node_name}]]"
            
            # 同步到 Graphiti
            episode_id = self.adapter.add_episode(
                content=node.content,
                source=f"node:{node.type}-{node_name}",
                episode_type=EpisodeType.NODE
            )
            
            if episode_id:
                return f"✓ 节点 [[{node_name}]] 已同步到 Graphiti（ID: {episode_id[:8]}...）"
            else:
                return f"⚠️ 节点 [[{node_name}]] 同步完成（可能未产生新内容）"
                
        except Exception as e:
            return f"❌ 同步失败: {str(e)}"
```

### 2. 集成到 MemoryTools (0.5天)

- [x] **2.1 修改 `memory_agent/tools.py`**

在 `MemoryTools.__init__` 中添加 Graphiti 初始化：

```python
# memory_agent/tools.py 修改

class MemoryTools:
    def __init__(
        self,
        lifebook_path: str,
        enable_write: bool = False,
        encoding: str = "utf-8",
        rag_config: Optional[RAGConfig] = None,
        graphiti_config: Optional[dict] = None  # 新增
    ):
        # ... 现有代码 ...
        
        # 初始化 Graphiti（如果配置启用）
        self.graphiti_config = graphiti_config
        self.graphiti_enabled = False
        self.graphiti_handlers = None
        
        if graphiti_config and graphiti_config.get("enabled", False):
            try:
                from memory_store.graphiti_adapter import GraphitiSyncAdapter
                from .graphiti_tools import GraphitiToolHandlers
                
                adapter = GraphitiSyncAdapter(graphiti_config, lifebook_path)
                adapter.initialize()  # 同步初始化
                
                self.graphiti_handlers = GraphitiToolHandlers(adapter)
                self.graphiti_enabled = True
                print(f"[Graphiti] 工具已启用")
            except Exception as e:
                print(f"[Graphiti] 初始化失败: {e}")
        
        # 注册工具
        self._register_tools()
```

- [x] **2.2 添加 Graphiti 工具注册逻辑**

```python
# memory_agent/tools.py 修改 _register_tools()

def _register_tools(self):
    """注册所有工具"""
    # ... 现有工具注册 ...
    
    # ==================== Graphiti 工具（如果启用） ====================
    if self.graphiti_enabled and self.graphiti_handlers:
        self._register_graphiti_tools()

def _register_graphiti_tools(self):
    """注册 Graphiti 相关工具"""
    from .graphiti_tools import GRAPHITI_TOOLS_DEFINITIONS
    
    # graphiti_search
    self.tools["graphiti_search"] = ToolDefinition(
        name="graphiti_search",
        description=GRAPHITI_TOOLS_DEFINITIONS["graphiti_search"]["description"],
        parameters=GRAPHITI_TOOLS_DEFINITIONS["graphiti_search"]["parameters"],
        category=ToolCategory.SEARCH,
        handler=self.graphiti_handlers.graphiti_search
    )
    
    # graphiti_temporal
    self.tools["graphiti_temporal"] = ToolDefinition(
        name="graphiti_temporal",
        description=GRAPHITI_TOOLS_DEFINITIONS["graphiti_temporal"]["description"],
        parameters=GRAPHITI_TOOLS_DEFINITIONS["graphiti_temporal"]["parameters"],
        category=ToolCategory.SEARCH,
        handler=self.graphiti_handlers.graphiti_temporal
    )
    
    # graphiti_add（归类为 WRITE）
    if self.enable_write:
        self.tools["graphiti_add"] = ToolDefinition(
            name="graphiti_add",
            description=GRAPHITI_TOOLS_DEFINITIONS["graphiti_add"]["description"],
            parameters=GRAPHITI_TOOLS_DEFINITIONS["graphiti_add"]["parameters"],
            category=ToolCategory.WRITE,
            handler=self.graphiti_handlers.graphiti_add
        )
    
    # graphiti_multi_hop
    self.tools["graphiti_multi_hop"] = ToolDefinition(
        name="graphiti_multi_hop",
        description=GRAPHITI_TOOLS_DEFINITIONS["graphiti_multi_hop"]["description"],
        parameters=GRAPHITI_TOOLS_DEFINITIONS["graphiti_multi_hop"]["parameters"],
        category=ToolCategory.SEARCH,
        handler=self.graphiti_handlers.graphiti_multi_hop
    )
    
    # graphiti_sync_node（归类为 WRITE）
    if self.enable_write:
        self.tools["graphiti_sync_node"] = ToolDefinition(
            name="graphiti_sync_node",
            description=GRAPHITI_TOOLS_DEFINITIONS["graphiti_sync_node"]["description"],
            parameters=GRAPHITI_TOOLS_DEFINITIONS["graphiti_sync_node"]["parameters"],
            category=ToolCategory.WRITE,
            handler=self.graphiti_handlers.graphiti_sync_node
        )
    
    print(f"[Graphiti] 已注册 {self._count_graphiti_tools()} 个工具")

def _count_graphiti_tools(self) -> int:
    """统计 Graphiti 工具数量"""
    return sum(1 for name in self.tools if name.startswith("graphiti_"))
```

### 3. 更新 Agent System Prompt (0.5天)

- [x] **3.1 修改 Agent 配置**

在 `AgentConfig` 中更新 `system_prompt`，让小模型知道有 Graphiti 工具：

```python
# memory_agent/agent.py 修改

@dataclass 
class AgentConfig:
    # ... 现有字段 ...
    
    # Graphiti 专用说明（可选追加）
    graphiti_prompt_addition: str = """

## 🔗 Graphiti 时序图谱工具（如果可用）

如果工具列表中包含 `graphiti_` 前缀的工具，说明 Graphiti 已启用：

### graphiti_search
- **功能**：语义 + 关键词 + 图遍历混合搜索
- **优势**：能找到语义相关但不含关键词的内容；支持多跳关系
- **何时用**：复杂问题、需要关系推理的问题

### graphiti_temporal  
- **功能**：查询某个时间点的知识状态
- **优势**：能回答"那时候是什么情况"
- **何时用**：用户问过去某个时间的状态

### 选择策略
| 问题类型 | 推荐工具 |
|---------|---------|
| 精确关键词查找 | search_memories |
| 语义相关/模糊查找 | graphiti_search 或 rag_search |
| 多跳关系推理 | graphiti_search / graphiti_multi_hop |
| 时间点状态 | graphiti_temporal |
| 读具体日期日记 | read_diary |
"""
```

- [x] **3.2 动态拼接 Prompt**

```python
# memory_agent/agent.py 修改 retrieve() 方法

def retrieve(self, query: str, context: Optional[str] = None, ...) -> AgentResult:
    # 构建消息时，检查是否有 Graphiti 工具
    system_prompt = self.config.system_prompt
    
    # 检查 tools 中是否包含 graphiti 工具
    tools = self.memory_tools.get_openai_tools(include_write=include_write_tools)
    has_graphiti = any(t["function"]["name"].startswith("graphiti_") for t in tools)
    
    if has_graphiti:
        system_prompt += self.config.graphiti_prompt_addition
    
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    # ... 后续不变 ...
```

### 4. 更新主模型工具提示 (0.3天)

- [x] **4.1 修改 ContextBuilder**

在 `get_memory_tools_prompt()` 中添加 Graphiti 工具说明：

```python
# memory_agent/context_builder.py 修改

def get_memory_tools_prompt(self, enable_write: bool = False, custom_hint: str = "", include_graphiti: bool = False) -> str:
    # ... 现有代码 ...
    
    if include_graphiti:
        prompt += """

### 🔗 Graphiti 时序图谱工具
```
<<<tool_call>>>
name: graphiti_search
arguments: {"query": "主人开发的项目"}
<<</tool_call>>>
```
> 混合搜索：语义 + 关键词 + 图遍历，适合复杂问题

```
<<<tool_call>>>
name: graphiti_temporal
arguments: {"entity": "LifeBook项目", "time_point": "2025-03"}
<<</tool_call>>>
```
> 时间点查询：该实体在指定时间的状态

```
<<<tool_call>>>
name: graphiti_multi_hop
arguments: {"start_entity": "主人", "max_hops": 2}
<<</tool_call>>>
```
> 多跳查询：沿关系边遍历

⚠️ Graphiti 工具与传统工具选择：
- 精确关键词 → search_memories
- 语义/多跳 → graphiti_search
- 历史状态 → graphiti_temporal"""
    
    return prompt
```

### 5. 配置集成 (0.3天)

- [x] **5.1 确保配置传递**（通过 memory_router.py 实现）

在 `proxy/routes/chat.py` 中传递 graphiti_config：

```python
# proxy/routes/chat.py 修改

def init_memory_tools():
    config = load_config()
    graphiti_config = config.get("graphiti", {})
    
    memory_tools = MemoryTools(
        lifebook_path=config["lifebook_path"],
        enable_write=...,
        graphiti_config=graphiti_config  # 新增
    )
    return memory_tools
```

### 6. 测试验证 (0.5天)

- [x] **6.1 创建测试脚本**

```python
# tests/test_graphiti_tools.py

import pytest
from memory_agent.tools import MemoryTools
from memory_agent.graphiti_tools import GRAPHITI_TOOLS_DEFINITIONS

class TestGraphitiToolDefinitions:
    """测试工具定义"""
    
    def test_definitions_complete(self):
        """所有必需字段都存在"""
        for name, defn in GRAPHITI_TOOLS_DEFINITIONS.items():
            assert "name" in defn
            assert "description" in defn
            assert "parameters" in defn
            assert defn["parameters"].get("type") == "object"

class TestGraphitiToolsIntegration:
    """测试工具集成"""
    
    @pytest.fixture
    def tools_with_graphiti(self, tmp_path):
        """创建启用 Graphiti 的 MemoryTools"""
        # 创建测试 lifebook 结构
        (tmp_path / "nodes").mkdir()
        (tmp_path / "daily").mkdir()
        
        graphiti_config = {
            "enabled": True,
            "backend": "kuzu",
            "kuzu": {"db_path": str(tmp_path / ".graphiti.kuzu")},
            "llm": {
                "api_key": "test-key",
                "model": "gpt-4o-mini"
            }
        }
        
        # 注意：实际测试需要 mock adapter
        return MemoryTools(
            lifebook_path=str(tmp_path),
            graphiti_config=graphiti_config
        )
    
    def test_graphiti_tools_registered(self, tools_with_graphiti):
        """Graphiti 工具正确注册"""
        tool_names = [t.name for t in tools_with_graphiti.tools.values()]
        assert "graphiti_search" in tool_names
        assert "graphiti_temporal" in tool_names
    
    def test_openai_format(self, tools_with_graphiti):
        """工具能转换为 OpenAI 格式"""
        openai_tools = tools_with_graphiti.get_openai_tools()
        graphiti_tools = [t for t in openai_tools if t["function"]["name"].startswith("graphiti_")]
        assert len(graphiti_tools) >= 2
```

---

## 📁 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `memory_agent/graphiti_tools.py` | **新增** | Graphiti 工具定义和处理函数 |
| `memory_agent/tools.py` | **修改** | 添加 Graphiti 初始化和注册 |
| `memory_agent/agent.py` | **修改** | 更新 system prompt |
| `memory_agent/context_builder.py` | **修改** | 更新工具提示 |
| `proxy/routes/chat.py` | **修改** | 传递 graphiti_config |
| `tests/test_graphiti_tools.py` | **新增** | 测试脚本 |

---

## 🎯 验收标准

### 基础验收

| 测试项 | 预期结果 | 验证方法 |
|--------|---------|---------|
| 工具注册 | 启用时有 `graphiti_*` 工具 | 检查 `get_openai_tools()` |
| 工具禁用 | 配置关闭时无 Graphiti 工具 | 修改配置验证 |
| 搜索调用 | 返回格式化结果 | 手动调用 `graphiti_search` |
| 时间查询 | 返回历史状态 | 手动调用 `graphiti_temporal` |

### 集成验收

| 测试项 | 预期结果 | 验证方法 |
|--------|---------|---------|
| 小模型调用 | Agent 能调用 Graphiti 工具 | 发送需要多跳推理的问题 |
| 主模型调用 | 主模型能调用 Graphiti 工具 | 在 -memory 模式测试 |
| 工具切换 | 能在传统/Graphiti 工具间切换 | 对比两种工具结果 |

---

## ⚠️ 注意事项

### 同步 vs 异步

`GraphitiAdapter` 是异步的，而 `MemoryTools.call_tool()` 是同步的。解决方案：

1. 使用 `GraphitiSyncAdapter` 包装器（总规划已定义）
2. 或在工具处理函数中使用 `asyncio.run()`

推荐方案1，更清晰。

### 配置热加载

如果需要支持配置热加载（不重启更新 Graphiti 启用状态），需要：

```python
def _check_graphiti_enabled(self) -> bool:
    """动态检查 Graphiti 是否启用"""
    try:
        config = load_config()
        return config.get("graphiti", {}).get("enabled", False)
    except:
        return self.graphiti_enabled
```

### 降级策略

如果 Graphiti 初始化失败，工具仍可用但返回友好错误：

```python
def graphiti_search(self, query: str, ...) -> str:
    if not self.adapter:
        return "❌ Graphiti 未正确初始化。请检查配置或使用 search_memories 工具。"
    # ...
```

---

## 📅 时间安排

| 日期 | 任务 | 产出 |
|------|------|------|
| Day 1 上午 | 1.1 工具定义 | `graphiti_tools.py` 基础版 |
| Day 1 下午 | 1.2 处理函数 | 5 个工具处理函数 |
| Day 2 上午 | 2.1-2.2 集成 | `tools.py` 修改完成 |
| Day 2 下午 | 3-4 Prompt 更新 | Agent 和主模型提示更新 |
| Day 3 上午 | 5-6 配置和测试 | 测试通过 |
| Day 3 下午 | 缓冲 + 文档 | 完成分规划二 |

---

## 🔗 后续规划

完成本分规划后，将进入：

1. **分规划三：原始对话保留机制**
   - ConversationMatcher
   - ConversationLogger
   - 与 `proxy/routes/chat.py` 集成

2. **分规划四：迭代检索器（MemR3 风格）**
   - IterativeRetriever
   - RetrievalRouter
   - Evidence-Gap 机制

---

*创建时间：2026-01-22*
*作者：灰魂* 😸
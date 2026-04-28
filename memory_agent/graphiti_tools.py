"""
Graphiti 工具定义

提供时序知识图谱的搜索、时间点查询、添加等工具。
这些工具可以被 MemoryAgent（检索小模型）和主模型调用。

使用方式：
    from memory_agent.graphiti_tools import GRAPHITI_TOOLS_DEFINITIONS, GraphitiToolHandlers
    
    # 创建处理器
    handlers = GraphitiToolHandlers(graphiti_adapter)
    
    # 调用工具
    result = handlers.graphiti_search(query="主人最近做了什么")
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, field


# ============================================================
# 工具定义常量
# ============================================================

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
    },
    
    "graphiti_get_stats": {
        "name": "graphiti_get_stats",
        "description": """获取 Graphiti 知识图谱的统计信息。
包括：后端类型、初始化状态、LLM模型、向量模型等配置。""",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}


# ============================================================
# 结果数据类
# ============================================================

@dataclass
class GraphitiToolResult:
    """Graphiti 工具执行结果"""
    success: bool
    content: str
    source_count: int = 0
    iteration_count: int = 1  # 用于迭代检索时
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 工具处理函数类
# ============================================================

class GraphitiToolHandlers:
    """
    Graphiti 工具处理函数集合
    
    设计为可独立测试的类，由 MemoryTools 实例化并注入 adapter。
    使用同步接口（GraphitiSyncAdapter），适配 MemoryTools.call_tool() 的同步调用。
    """
    
    def __init__(self, graphiti_adapter, lifebook_path: Optional[str] = None):
        """
        Args:
            graphiti_adapter: GraphitiSyncAdapter 实例
            lifebook_path: LifeBook 根目录路径（用于读取节点）
        """
        self.adapter = graphiti_adapter
        self.lifebook_path = lifebook_path
        self._initialized = False
    
    def _ensure_initialized(self) -> bool:
        """
        确保 adapter 已初始化
        
        Returns:
            是否初始化成功
        """
        if self._initialized:
            return True
        
        if self.adapter is None:
            return False
        
        try:
            if hasattr(self.adapter, 'initialize'):
                self.adapter.initialize()
            self._initialized = True
            return True
        except Exception as e:
            print(f"[Graphiti] 初始化失败: {e}")
            return False
    
    def graphiti_search(
        self,
        query: str,
        num_results: int = 10,
        include_edges: bool = True,
        include_nodes: bool = True
    ) -> str:
        """
        Graphiti 混合搜索
        
        Args:
            query: 搜索查询
            num_results: 返回结果数量
            include_edges: 是否包含关系边
            include_nodes: 是否包含实体节点
        
        Returns:
            格式化的搜索结果字符串
        """
        if not self._ensure_initialized():
            return "❌ Graphiti 未正确初始化。请检查配置或使用 search_memories 工具。"
        
        try:
            results = self.adapter.search(
                query=query,
                num_results=num_results,
            )
            
            if not results:
                return f"未找到与 '{query}' 相关的记忆。"
            
            output = f"🔍 Graphiti 搜索结果（共 {len(results)} 条）：\n\n"
            
            for i, r in enumerate(results, 1):
                result_type = getattr(r, 'result_type', 'unknown')
                icon = "🔗" if result_type == "edge" else "📌"
                
                content = getattr(r, 'content', str(r))
                score = getattr(r, 'score', 0)
                source = getattr(r, 'source', '')
                
                # 时序信息
                valid_at = getattr(r, 'valid_at', None)
                invalid_at = getattr(r, 'invalid_at', None)
                time_info = ""
                if valid_at:
                    valid_str = valid_at.strftime('%Y-%m-%d') if hasattr(valid_at, 'strftime') else str(valid_at)[:10]
                    time_info = f" [生效: {valid_str}"
                    if invalid_at:
                        invalid_str = invalid_at.strftime('%Y-%m-%d') if hasattr(invalid_at, 'strftime') else str(invalid_at)[:10]
                        time_info += f" → 失效: {invalid_str}"
                    time_info += "]"
                
                # 截断过长内容
                content_display = content[:200] + "..." if len(content) > 200 else content
                
                output += f"{i}. {icon} {content_display}\n"
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
        
        Args:
            entity: 实体名称
            time_point: 时间点字符串 (YYYY-MM-DD 或 YYYY-MM)
            num_results: 返回结果数量
        
        Returns:
            该实体在指定时间点的状态
        """
        if not self._ensure_initialized():
            return "❌ Graphiti 未正确初始化。请检查配置。"
        
        try:
            # 解析时间点
            if len(time_point) == 7:  # YYYY-MM
                dt = datetime.strptime(time_point + "-15", "%Y-%m-%d")
            elif len(time_point) == 10:  # YYYY-MM-DD
                dt = datetime.strptime(time_point, "%Y-%m-%d")
            else:
                return f"❌ 时间格式错误。请使用 YYYY-MM-DD 或 YYYY-MM 格式。"
            
            result = self.adapter.temporal_query(
                entity_name=entity,
                time_point=dt,
                num_results=num_results
            )
            
            facts = getattr(result, 'facts', [])
            if not facts:
                return f"未找到 '{entity}' 在 {time_point} 的相关记录。"
            
            output = f"📅 时间点查询：{entity} @ {time_point}\n\n"
            output += f"找到 {len(facts)} 条在该时间有效的事实：\n\n"
            
            for fact in facts:
                if isinstance(fact, dict):
                    content = fact.get("fact", "")
                    valid_from = fact.get("valid_from", "")
                    valid_to = fact.get("valid_to", "持续中")
                    relation = fact.get("relation", "")
                else:
                    content = str(fact)
                    valid_from = ""
                    valid_to = "持续中"
                    relation = ""
                
                output += f"- {content}\n"
                if valid_from:
                    output += f"  有效期: {valid_from} → {valid_to}\n"
                if relation:
                    output += f"  关系类型: {relation}\n"
                output += "\n"
            
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
        
        Args:
            content: 要添加的知识内容
            source: 来源标识
        
        Returns:
            添加结果
        """
        if not self._ensure_initialized():
            return "❌ Graphiti 未正确初始化。请检查配置。"
        
        try:
            # 导入 EpisodeType
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
        
        Args:
            start_entity: 起始实体名称
            max_hops: 最大跳数
            relation_types: 限定关系类型
            num_results: 每跳最大结果数
        
        Returns:
            多跳查询结果
        """
        if not self._ensure_initialized():
            return "❌ Graphiti 未正确初始化。请检查配置。"
        
        try:
            # 限制跳数
            max_hops = max(1, min(3, max_hops))
            
            # 当前使用搜索模拟多跳查询
            # TODO: 未来可以实现真正的图遍历
            query = f"{start_entity} 相关"
            results = self.adapter.search(query, num_results=num_results * max_hops)
            
            if not results:
                return f"未找到从 '{start_entity}' 出发的关系路径。"
            
            output = f"🕸️ 多跳查询：{start_entity}（最大 {max_hops} 跳）\n\n"
            
            # 按关系类型过滤（如果指定）
            filtered_results = results
            if relation_types:
                filtered_results = []
                for r in results:
                    rel_type = getattr(r, 'metadata', {}).get('relation_type', '')
                    if rel_type in relation_types or not rel_type:
                        filtered_results.append(r)
            
            if not filtered_results:
                return f"未找到从 '{start_entity}' 出发的 {relation_types} 类型关系。"
            
            output += f"找到 {len(filtered_results)} 条相关路径：\n\n"
            
            for i, r in enumerate(filtered_results[:num_results], 1):
                content = getattr(r, 'content', str(r))
                content_display = content[:150] + "..." if len(content) > 150 else content
                output += f"{i}. {content_display}\n"
            
            if len(filtered_results) > num_results:
                output += f"\n... 还有 {len(filtered_results) - num_results} 条结果未显示"
            
            return output
            
        except Exception as e:
            return f"❌ 多跳查询失败: {str(e)}"
    
    def graphiti_sync_node(
        self,
        node_name: str
    ) -> str:
        """
        手动同步指定节点到 Graphiti
        
        Args:
            node_name: 节点名称（不含类型前缀）
        
        Returns:
            同步结果
        """
        if not self._ensure_initialized():
            return "❌ Graphiti 未正确初始化。请检查配置。"
        
        if not self.lifebook_path:
            return "❌ 无法获取 lifebook 路径"
        
        try:
            from memory_store.graphiti_adapter import EpisodeType
            from memory_store.reader import LifeBookReader
            
            # 读取节点内容
            reader = LifeBookReader(str(self.lifebook_path))
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
                
        except ImportError as e:
            return f"❌ 导入失败: {str(e)}"
        except Exception as e:
            return f"❌ 同步失败: {str(e)}"
    
    def graphiti_get_stats(self) -> str:
        """
        获取 Graphiti 统计信息
        
        Returns:
            统计信息字符串
        """
        if not self._ensure_initialized():
            return "❌ Graphiti 未正确初始化。请检查配置。"
        
        try:
            stats = self.adapter.get_stats()
            
            output = "📊 Graphiti 统计信息\n\n"
            output += f"- 启用状态: {'✓ 已启用' if stats.get('enabled') else '✗ 未启用'}\n"
            output += f"- 初始化: {'✓ 已完成' if stats.get('initialized') else '✗ 未完成'}\n"
            output += f"- 后端类型: {stats.get('backend', 'unknown')}\n"
            output += f"- 数据库路径: {stats.get('db_path', 'N/A')}\n"
            output += f"- LLM 模型: {stats.get('llm_model', 'N/A')}\n"
            output += f"- 向量模型: {stats.get('embedding_model', 'N/A')}\n"
            output += f"- Reranker: {'✓ 已启用' if stats.get('reranker_enabled') else '✗ 未启用'}\n"
            
            return output
            
        except Exception as e:
            return f"❌ 获取统计信息失败: {str(e)}"


# ============================================================
# 便捷函数
# ============================================================

def get_graphiti_tools_list() -> List[str]:
    """获取所有 Graphiti 工具名称列表"""
    return list(GRAPHITI_TOOLS_DEFINITIONS.keys())


def is_graphiti_tool(tool_name: str) -> bool:
    """检查是否是 Graphiti 工具"""
    return tool_name.startswith("graphiti_")
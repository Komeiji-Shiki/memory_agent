"""
Search Tools - 搜索工具模块
"""

from typing import List, Dict, Any
from .base import ToolCategory, ToolDefinition


class SearchToolsMixin:
    """搜索工具 Mixin"""
    
    def _register_search_tools(self):
        """注册搜索工具"""
        # 关键词搜索
        self.tools["search_memories"] = ToolDefinition(
            name="search_memories",
            description="搜索相关记忆。根据关键词、标签、人物、日期范围搜索日记和节点。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "筛选标签列表（可选）"
                    },
                    "people": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "筛选相关人物（可选）"
                    },
                    "date_start": {
                        "type": "string",
                        "description": "开始日期 YYYY-MM-DD（可选）"
                    },
                    "date_end": {
                        "type": "string",
                        "description": "结束日期 YYYY-MM-DD（可选）"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制，默认10",
                        "default": 10
                    }
                },
                "required": ["query"]
            },
            category=ToolCategory.SEARCH,
            handler=self._search_memories
        )
        
        # RAG 语义搜索
        if self.rag_searcher:
            self.tools["rag_search"] = ToolDefinition(
                name="rag_search",
                description="语义搜索记忆（基于向量相似度）。当关键词搜索效果不佳时使用。",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询（描述你想找的内容）"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "返回结果数量，默认5",
                            "default": 5
                        },
                        "filter_type": {
                            "type": "string",
                            "enum": ["diary", "node", "summary", "all"],
                            "description": "筛选类型",
                            "default": "all"
                        }
                    },
                    "required": ["query"]
                },
                category=ToolCategory.SEARCH,
                handler=self._rag_search
            )
        
        # Graphiti 搜索（如果启用）
        if self.graphiti_enabled and self.graphiti_handlers:
            self._register_graphiti_tools()
    
    def _register_graphiti_tools(self):
        """注册 Graphiti 相关工具"""
        self.tools["graphiti_search"] = ToolDefinition(
            name="graphiti_search",
            description="Graphiti 时序知识图谱搜索。支持语义+关键词+图遍历混合检索。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量",
                        "default": 10
                    }
                },
                "required": ["query"]
            },
            category=ToolCategory.SEARCH,
            handler=self._graphiti_search
        )
        
        self.tools["graphiti_temporal"] = ToolDefinition(
            name="graphiti_temporal",
            description="Graphiti 时间点查询。查询特定时间点的知识图谱状态。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "查询内容"
                    },
                    "reference_time": {
                        "type": "string",
                        "description": "参考时间，格式：YYYY-MM-DD 或相对时间如'3个月前'"
                    }
                },
                "required": ["query", "reference_time"]
            },
            category=ToolCategory.SEARCH,
            handler=self._graphiti_temporal
        )
        
        self.tools["graphiti_multi_hop"] = ToolDefinition(
            name="graphiti_multi_hop",
            description="Graphiti 多跳关系查询。用于查找多跳关系，如'A的朋友的朋友'。",
            parameters={
                "type": "object",
                "properties": {
                    "start_entity": {
                        "type": "string",
                        "description": "起始实体名称"
                    },
                    "relation_path": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关系路径，如 ['朋友', '同事']"
                    }
                },
                "required": ["start_entity", "relation_path"]
            },
            category=ToolCategory.SEARCH,
            handler=self._graphiti_multi_hop
        )
    
    def _search_memories(
        self,
        query: str,
        tags: List[str] = None,
        people: List[str] = None,
        date_start: str = None,
        date_end: str = None,
        limit: int = 10
    ) -> str:
        """关键词搜索记忆"""
        try:
            results = self.indexer.search(
                query=query,
                tags=tags or [],
                people=people or [],
                date_start=date_start,
                date_end=date_end,
                limit=limit
            )
            
            if not results:
                return "未找到相关记忆。"
            
            output = f"找到 {len(results)} 条相关记忆：\\n\\n"
            for i, r in enumerate(results, 1):
                output += f"{i}. [{r.get('type', 'unknown')}] "
                if r.get('date'):
                    output += f"{r['date']} "
                if r.get('title'):
                    output += f"《{r['title']}》"
                output += "\\n"
                if r.get('tags'):
                    output += f"   标签: {', '.join(r['tags'])}\\n"
                snippet = r.get('snippet', '')
                output += f"   摘要: {snippet[:100]}...\\n\\n"
            
            return output
            
        except Exception as e:
            return f"搜索出错: {str(e)}"
    
    def _rag_search(
        self,
        query: str,
        top_k: int = 5,
        filter_type: str = "all"
    ) -> str:
        """RAG语义搜索"""
        if not self.rag_searcher:
            return "❌ RAG语义搜索未启用。请在配置中设置 rag.enabled=true 和 API Key。"
        
        try:
            type_filter = None if filter_type == "all" else filter_type
            return self.rag_searcher.semantic_search(query, top_k=top_k, filter_type=type_filter)
        except Exception as e:
            return f"❌ RAG搜索出错: {str(e)}"
    
    def _graphiti_search(self, query: str, limit: int = 10) -> str:
        """Graphiti 搜索"""
        if not self.graphiti_handlers:
            return "❌ Graphiti 未启用"
        try:
            return self.graphiti_handlers.search(query, limit)
        except Exception as e:
            return f"Graphiti 搜索出错: {str(e)}"
    
    def _graphiti_temporal(self, query: str, reference_time: str) -> str:
        """Graphiti 时间点查询"""
        if not self.graphiti_handlers:
            return "❌ Graphiti 未启用"
        try:
            return self.graphiti_handlers.temporal_search(query, reference_time)
        except Exception as e:
            return f"Graphiti 时间点查询出错: {str(e)}"
    
    def _graphiti_multi_hop(self, start_entity: str, relation_path: List[str]) -> str:
        """Graphiti 多跳查询"""
        if not self.graphiti_handlers:
            return "❌ Graphiti 未启用"
        try:
            return self.graphiti_handlers.multi_hop_search(start_entity, relation_path)
        except Exception as e:
            return f"Graphiti 多跳查询出错: {str(e)}"
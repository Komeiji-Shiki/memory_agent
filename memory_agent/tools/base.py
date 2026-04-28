"""
Memory Tools Base - 基础类和工具定义
"""

import os
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum

try:
    from memory_store.reader import LifeBookReader
    from memory_store.writer import LifeBookWriter
    from memory_store.sqlite_indexer import SqliteIndexer
    from memory_store.rag import RAGIndex, RAGConfig, RAGSearcher
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from memory_store.reader import LifeBookReader
    from memory_store.writer import LifeBookWriter
    from memory_store.sqlite_indexer import SqliteIndexer
    from memory_store.rag import RAGIndex, RAGConfig, RAGSearcher


class ToolCategory(Enum):
    """工具类别"""
    READ = "read"
    WRITE = "write"
    SEARCH = "search"


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: Dict[str, Any]
    category: ToolCategory
    handler: Callable


class MemoryToolsBase:
    """记忆工具基础类"""
    
    def __init__(
        self,
        lifebook_path: str,
        enable_write: bool = False,
        encoding: str = "utf-8",
        rag_config: Optional[RAGConfig] = None,
        graphiti_config: Optional[Dict[str, Any]] = None
    ):
        self.lifebook_path = lifebook_path
        self.enable_write = enable_write
        self.encoding = encoding
        
        # 初始化存储层
        self.reader = LifeBookReader(lifebook_path, encoding)
        self.writer = LifeBookWriter(lifebook_path, encoding) if enable_write else None
        self.indexer = SqliteIndexer(lifebook_path, encoding=encoding)
        
        # RAG
        self.rag_config = rag_config
        self.rag_index: Optional[RAGIndex] = None
        self.rag_searcher: Optional[RAGSearcher] = None
        self._init_rag()
        
        # Graphiti
        self.graphiti_config = graphiti_config
        self.graphiti_enabled = False
        self.graphiti_handlers = None
        self._init_graphiti()
        
        # 注册工具
        self.tools: Dict[str, ToolDefinition] = {}
        self._register_all_tools()
    
    def _init_rag(self):
        """初始化RAG"""
        if self.rag_config and self.rag_config.enabled and self.rag_config.api_key:
            try:
                self.rag_index = RAGIndex(self.lifebook_path, self.rag_config, self.encoding)
                self.rag_searcher = RAGSearcher(self.rag_index)
                print(f"[RAG] 已启用，模型: {self.rag_config.model}")
            except Exception as e:
                print(f"[RAG] 初始化失败: {e}")
    
    def _init_graphiti(self):
        """初始化Graphiti"""
        if self.graphiti_config and self.graphiti_config.get("enabled", False):
            try:
                from memory_store.graphiti_adapter import GraphitiSyncAdapter
                from ..graphiti_tools import GraphitiToolHandlers
                
                adapter = GraphitiSyncAdapter(self.graphiti_config, self.lifebook_path)
                adapter.initialize()
                
                self.graphiti_handlers = GraphitiToolHandlers(adapter, self.lifebook_path)
                self.graphiti_enabled = True
                print(f"[Graphiti] 工具已启用")
            except Exception as e:
                print(f"[Graphiti] 初始化失败: {e}")
    
    def _register_all_tools(self):
        """注册所有工具 - 调用各 Mixin 的注册方法"""
        # 搜索工具
        self._register_search_tools()
        # 只读工具
        self._register_read_tools()
        # 写入工具
        self._register_write_tools()
        # 编辑工具
        self._register_edit_tools()
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        调用工具
        
        Args:
            tool_name: 工具名称
            arguments: 参数字典
            
        Returns:
            工具执行结果
        """
        if tool_name not in self.tools:
            return f"错误：未知工具 '{tool_name}'"
        
        tool = self.tools[tool_name]
        
        try:
            # 过滤参数
            defined_params = tool.parameters.get("properties", {}).keys()
            filtered_args = {k: v for k, v in arguments.items() if k in defined_params}
            
            result = tool.handler(**filtered_args)
            return result
        except Exception as e:
            return f"错误：工具执行失败 - {str(e)}"
    
    def get_available_tools(self, include_write: bool = False) -> List[ToolDefinition]:
        """获取可用工具列表"""
        tools = []
        for tool in self.tools.values():
            if tool.category == ToolCategory.WRITE and not include_write:
                continue
            tools.append(tool)
        return tools
    
    def get_openai_tools(self, include_write: bool = False) -> List[Dict[str, Any]]:
        """获取 OpenAI function calling 格式的工具列表"""
        tools = []
        for tool in self.get_available_tools(include_write):
            tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            })
        return tools
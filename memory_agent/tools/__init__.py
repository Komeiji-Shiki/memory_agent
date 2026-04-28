"""
Memory Tools - 记忆工具包

模块化结构：
- base.py: 基础类和工具定义
- search.py: 搜索工具（关键词、RAG、Graphiti）
- read.py: 只读工具（读取日记、节点等）
- write.py: 写入工具（创建、更新、删除）
- edit.py: 编辑工具（精确编辑、apply_diff风格）
"""

from typing import Optional, List, Dict, Any

from .base import ToolCategory, ToolDefinition, MemoryToolsBase
from .search import SearchToolsMixin
from .read import ReadToolsMixin
from .write import WriteToolsMixin
from .edit import EditToolsMixin

# 主类
class MemoryTools(SearchToolsMixin, ReadToolsMixin, WriteToolsMixin, EditToolsMixin, MemoryToolsBase):
    """
    完整的记忆工具集合
    
    通过 Mixin 模式组合各功能模块
    """
    pass


# 便捷函数
_global_tools: Optional[MemoryTools] = None


def init_memory_tools(
    lifebook_path: str,
    enable_write: bool = False,
    encoding: str = "utf-8"
) -> MemoryTools:
    """初始化全局记忆工具"""
    global _global_tools
    _global_tools = MemoryTools(lifebook_path, enable_write, encoding)
    return _global_tools


def get_memory_tools() -> Optional[MemoryTools]:
    """获取全局记忆工具实例"""
    return _global_tools


def get_openai_tools(include_write: bool = False) -> List[Dict[str, Any]]:
    """获取 OpenAI 格式的工具列表"""
    if _global_tools is None:
        return []
    return _global_tools.get_openai_tools(include_write)


__all__ = [
    'ToolCategory',
    'ToolDefinition',
    'MemoryTools',
    'init_memory_tools',
    'get_memory_tools',
    'get_openai_tools'
]
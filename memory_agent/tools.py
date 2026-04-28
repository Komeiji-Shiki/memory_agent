"""
Memory Tools - 记忆工具定义

提供给小模型Agent和大模型使用的记忆操作工具：
- 只读工具：search_memories, rag_search, read_diary, read_summary, get_node, list_recent
- 写入工具：add_to_diary, create_node, update_node (仅记忆管理模式)

支持 OpenAI function calling 格式
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum

# 使用相对导入 - 需要从项目根目录运行或设置 PYTHONPATH
# 例如: PYTHONPATH=. python -m memory_agent.tools
try:
    from memory_store.reader import LifeBookReader
except ImportError:
    # 兼容直接运行的情况
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from memory_store.reader import LifeBookReader
from memory_store.writer import LifeBookWriter
from memory_store.sqlite_indexer import SqliteIndexer
from memory_store.rag import RAGIndex, RAGConfig, RAGSearcher


class ToolCategory(Enum):
    """工具类别"""
    READ = "read"       # 只读工具
    WRITE = "write"     # 写入工具
    SEARCH = "search"   # 搜索工具


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: Dict[str, Any]
    category: ToolCategory
    handler: Callable


class MemoryTools:
    """记忆工具集合"""
    
    def __init__(
        self,
        lifebook_path: str,
        enable_write: bool = False,
        encoding: str = "utf-8",
        rag_config: Optional[RAGConfig] = None,
        graphiti_config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化记忆工具
        
        Args:
            lifebook_path: LifeBook根目录路径
            enable_write: 是否启用写入工具
            encoding: 文件编码
            rag_config: RAG配置（可选）
            graphiti_config: Graphiti配置（可选）
        """
        self.lifebook_path = lifebook_path
        self.enable_write = enable_write
        self.encoding = encoding
        
        # 初始化存储层
        self.reader = LifeBookReader(lifebook_path, encoding)
        self.writer = LifeBookWriter(lifebook_path, encoding) if enable_write else None
        self.indexer = SqliteIndexer(lifebook_path, encoding=encoding)
        
        # 初始化 RAG（如果提供了配置）
        self.rag_config = rag_config
        self.rag_index: Optional[RAGIndex] = None
        self.rag_searcher: Optional[RAGSearcher] = None
        if rag_config and rag_config.enabled and rag_config.api_key:
            try:
                self.rag_index = RAGIndex(lifebook_path, rag_config, encoding)
                self.rag_searcher = RAGSearcher(self.rag_index)
                print(f"[RAG] 已启用，模型: {rag_config.model}")
            except Exception as e:
                print(f"[RAG] 初始化失败: {e}")
        
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
                
                self.graphiti_handlers = GraphitiToolHandlers(adapter, lifebook_path)
                self.graphiti_enabled = True
                print(f"[Graphiti] 工具已启用 (backend: {graphiti_config.get('backend', 'kuzu')})")
            except ImportError as e:
                print(f"[Graphiti] 依赖未安装: {e}")
            except Exception as e:
                print(f"[Graphiti] 初始化失败: {e}")
        
        # 注册工具
        self.tools: Dict[str, ToolDefinition] = {}
        self._register_tools()
    
    def _register_tools(self):
        """注册所有工具"""
        # ==================== 搜索工具 ====================
        
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
        
        # RAG 语义搜索工具（如果启用）
        if self.rag_searcher:
            self.tools["rag_search"] = ToolDefinition(
                name="rag_search",
                description="语义搜索记忆（基于向量相似度）。当关键词搜索效果不佳时使用，可以找到语义相关但不含关键词的内容。",
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
                            "description": "筛选类型：diary日记、node节点、summary总结、all全部",
                            "default": "all"
                        }
                    },
                    "required": ["query"]
                },
                category=ToolCategory.SEARCH,
                handler=self._rag_search
            )
        
        # ==================== 只读工具 ====================
        
        self.tools["read_diary"] = ToolDefinition(
            name="read_diary",
            description="读取指定日期的日记完整内容。",
            parameters={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期，格式 YYYY-MM-DD"
                    }
                },
                "required": ["date"]
            },
            category=ToolCategory.READ,
            handler=self._read_diary
        )
        
        self.tools["read_summary"] = ToolDefinition(
            name="read_summary",
            description="读取总结（周/月/季/年）。",
            parameters={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["weekly", "monthly", "quarterly", "yearly"],
                        "description": "总结类型"
                    },
                    "identifier": {
                        "type": "string",
                        "description": "标识符，如 2025-W52、2025-12、2025-Q4、2025"
                    }
                },
                "required": ["type", "identifier"]
            },
            category=ToolCategory.READ,
            handler=self._read_summary
        )
        
        self.tools["get_node"] = ToolDefinition(
            name="get_node",
            description="获取人物/地点/事物节点的详细信息。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "节点名称"
                    }
                },
                "required": ["name"]
            },
            category=ToolCategory.READ,
            handler=self._get_node
        )
        
        self.tools["list_recent"] = ToolDefinition(
            name="list_recent",
            description="列出最近N天的日记概要。",
            parameters={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "天数，默认7",
                        "default": 7
                    }
                },
                "required": []
            },
            category=ToolCategory.READ,
            handler=self._list_recent
        )
        
        self.tools["get_current_context"] = ToolDefinition(
            name="get_current_context",
            description="获取当前时间上下文（今天日期、本周、本月等）。",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            category=ToolCategory.READ,
            handler=self._get_current_context
        )
        
        self.tools["list_all_tags"] = ToolDefinition(
            name="list_all_tags",
            description="列出所有标签及其使用次数。",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制，默认20",
                        "default": 20
                    }
                },
                "required": []
            },
            category=ToolCategory.READ,
            handler=self._list_all_tags
        )
        
        self.tools["list_all_people"] = ToolDefinition(
            name="list_all_people",
            description="列出所有人物及其出现次数。",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制，默认20",
                        "default": 20
                    }
                },
                "required": []
            },
            category=ToolCategory.READ,
            handler=self._list_all_people
        )
        
        self.tools["list_nodes"] = ToolDefinition(
            name="list_nodes",
            description="列出所有节点。可按类型过滤（人物/地点/事物/概念）。",
            parameters={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["人物", "地点", "事物", "概念", "all"],
                        "description": "节点类型，'all'表示所有类型",
                        "default": "all"
                    }
                },
                "required": []
            },
            category=ToolCategory.READ,
            handler=self._list_nodes
        )
        
        self.tools["get_memory_overview"] = ToolDefinition(
            name="get_memory_overview",
            description="获取记忆系统概览：所有节点列表、最近日记摘要、统计信息。一次调用即可了解记忆全貌。",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            category=ToolCategory.READ,
            handler=self._get_memory_overview
        )
        
        self.tools["read_graph"] = ToolDefinition(
            name="read_graph",
            description="读取整个知识图谱（所有节点及其关系）。",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            category=ToolCategory.READ,
            handler=self._read_graph
        )
        
        self.tools["read_all_nodes"] = ToolDefinition(
            name="read_all_nodes",
            description="一键读取所有节点的完整内容。适合需要全面了解记忆库中所有人物/地点/事物/概念的场景。",
            parameters={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["人物", "地点", "事物", "概念", "all"],
                        "description": "筛选节点类型，'all'表示所有类型",
                        "default": "all"
                    },
                    "max_content_length": {
                        "type": "integer",
                        "description": "每个节点内容的最大字符数（0表示不限制）",
                        "default": 0
                    }
                },
                "required": []
            },
            category=ToolCategory.READ,
            handler=self._read_all_nodes
        )
        
        # ==================== Pending 暂存工具（始终可用） ====================
        # 注意：add_to_pending 放在 enable_write 块外面，因为它用的是 PendingManager，不需要 writer
        # 这样普通 -memory 模式的主模型也能使用
        
        self.tools["add_to_pending"] = ToolDefinition(
            name="add_to_pending",
            description="添加摘要到待处理暂存区（pending）。用于手动记录值得保存的对话内容，等待每日汇总时合并成日记。",
            parameters={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "主题标题（20字以内）"
                    },
                    "summary": {
                        "type": "string",
                        "description": "摘要内容（1000字以内）"
                    }
                },
                "required": ["topic", "summary"]
            },
            category=ToolCategory.READ,  # 用 READ 类别，这样 include_write=False 时也能获取
            handler=self._add_to_pending
        )
        
        self.tools["get_current_time"] = ToolDefinition(
            name="get_current_time",
            description="获取当前时间上下文（今天日期、本周、本月等）。这是 get_current_context 的别名。",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            category=ToolCategory.READ,
            handler=self._get_current_context
        )
        
        # ==================== 写入工具（需要启用） ====================
        
        if self.enable_write:
            self.tools["add_to_diary"] = ToolDefinition(
                name="add_to_diary",
                description="向日记添加内容。如果日记不存在会自动创建。",
                parameters={
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "日期 YYYY-MM-DD，默认今天"
                        },
                        "content": {
                            "type": "string",
                            "description": "要添加的内容"
                        },
                        "section": {
                            "type": "string",
                            "description": "添加到哪个章节（可选，如 '## 今日事件'）"
                        }
                    },
                    "required": ["content"]
                },
                category=ToolCategory.WRITE,
                handler=self._add_to_diary
            )
            
            self.tools["create_node"] = ToolDefinition(
                name="create_node",
                description="创建新的人物/地点/事物节点。",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "节点名称"
                        },
                        "type": {
                            "type": "string",
                            "enum": ["人物", "地点", "事物", "概念"],
                            "description": "节点类型"
                        },
                        "content": {
                            "type": "string",
                            "description": "节点内容描述"
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "标签列表（可选）"
                        }
                    },
                    "required": ["name", "type", "content"]
                },
                category=ToolCategory.WRITE,
                handler=self._create_node
            )
            
            self.tools["update_node"] = ToolDefinition(
                name="update_node",
                description="更新已有节点的内容。",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "节点名称"
                        },
                        "content": {
                            "type": "string",
                            "description": "要添加或替换的内容"
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["append", "replace"],
                            "description": "更新模式：append追加，replace替换",
                            "default": "append"
                        }
                    },
                    "required": ["name", "content"]
                },
                category=ToolCategory.WRITE,
                handler=self._update_node
            )
            
            self.tools["create_summary"] = ToolDefinition(
                name="create_summary",
                description="创建周/月/季/年总结。",
                parameters={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["weekly", "monthly", "quarterly", "yearly"],
                            "description": "总结类型"
                        },
                        "identifier": {
                            "type": "string",
                            "description": "标识符，如 2025-W52"
                        },
                        "content": {
                            "type": "string",
                            "description": "总结内容"
                        },
                        "title": {
                            "type": "string",
                            "description": "标题（可选）"
                        }
                    },
                    "required": ["type", "identifier", "content"]
                },
                category=ToolCategory.WRITE,
                handler=self._create_summary
            )
            
            self.tools["delete_node"] = ToolDefinition(
                name="delete_node",
                description="删除一个节点（永久删除文件）。",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "节点名称"
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "确认删除（必须为true才会执行）",
                            "default": False
                        }
                    },
                    "required": ["name", "confirm"]
                },
                category=ToolCategory.WRITE,
                handler=self._delete_node
            )

            self.tools["delete_summary"] = ToolDefinition(
                name="delete_summary",
                description="删除一个总结（周/月/季/年）。这将永久删除文件。",
                parameters={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["weekly", "monthly", "quarterly", "yearly"],
                            "description": "总结类型"
                        },
                        "identifier": {
                            "type": "string",
                            "description": "标识符，如 2025-W02、2025-12、2025-Q4、2025"
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "确认删除（必须为true才会执行）",
                            "default": False
                        }
                    },
                    "required": ["type", "identifier", "confirm"]
                },
                category=ToolCategory.WRITE,
                handler=self._delete_summary
            )

            # ==================== 知识图谱工具（参考 MCP memory 设计） ====================
            
            self.tools["add_observations"] = ToolDefinition(
                name="add_observations",
                description="向一个或多个节点添加观察（离散事实）。每个观察是一条独立的信息。",
                parameters={
                    "type": "object",
                    "properties": {
                        "observations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "节点名称"},
                                    "contents": {"type": "array", "items": {"type": "string"}, "description": "要添加的观察内容列表"}
                                },
                                "required": ["name", "contents"]
                            },
                            "description": "要添加观察的节点列表"
                        }
                    },
                    "required": ["observations"]
                },
                category=ToolCategory.WRITE,
                handler=self._add_observations
            )
            
            self.tools["create_relations"] = ToolDefinition(
                name="create_relations",
                description="""创建节点之间的关系（在两个节点中互相添加链接）。

**何时使用**：
- 人物与项目：主人 --创建--> 某项目
- 人物与人物：小明 --朋友--> 小红
- 事物与概念：LifeBook系统 --属于--> 记忆管理
- 人物与事物：主人 --使用--> VSCode

**常用关系类型**：创建、使用、属于、包含、朋友、同事、喜欢、开发、维护

**注意**：两个节点都必须已存在，建议先 create_node 再 create_relations。""",
                parameters={
                    "type": "object",
                    "properties": {
                        "relations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "from": {"type": "string", "description": "源节点名称"},
                                    "to": {"type": "string", "description": "目标节点名称"},
                                    "relation_type": {"type": "string", "description": "关系类型（如'朋友'、'同事'、'属于'）"}
                                },
                                "required": ["from", "to", "relation_type"]
                            },
                            "description": "要创建的关系列表"
                        }
                    },
                    "required": ["relations"]
                },
                category=ToolCategory.WRITE,
                handler=self._create_relations
            )
            
            # ==================== 精确编辑工具（类似 apply_diff） ====================
            
            self.tools["edit_diary"] = ToolDefinition(
                name="edit_diary",
                description="精确编辑日记内容。可以搜索并替换指定文本，或在指定位置插入/删除内容。类似代码编辑器的 apply_diff 功能。",
                parameters={
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "日期，格式 YYYY-MM-DD"
                        },
                        "search": {
                            "type": "string",
                            "description": "要查找的原始内容（精确匹配）"
                        },
                        "replace": {
                            "type": "string",
                            "description": "替换为的新内容（留空表示删除）"
                        },
                        "replace_all": {
                            "type": "boolean",
                            "description": "是否替换所有匹配（默认只替换第一个）",
                            "default": False
                        }
                    },
                    "required": ["date", "search", "replace"]
                },
                category=ToolCategory.WRITE,
                handler=self._edit_diary
            )
            
            self.tools["rewrite_diary"] = ToolDefinition(
                name="rewrite_diary",
                description="完全重写日记正文。保留 frontmatter（日期、心情、标签等元数据），只替换正文内容。适用于需要大规模修改或清理日记的场景。",
                parameters={
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "日期，格式 YYYY-MM-DD"
                        },
                        "content": {
                            "type": "string",
                            "description": "新的日记正文内容（不需要包含 frontmatter，会自动保留原有的）"
                        },
                        "title": {
                            "type": "string",
                            "description": "新标题（可选，不填则保留原标题）"
                        }
                    },
                    "required": ["date", "content"]
                },
                category=ToolCategory.WRITE,
                handler=self._rewrite_diary
            )
            
            self.tools["edit_node"] = ToolDefinition(
                name="edit_node",
                description="精确编辑节点内容。可以搜索并替换指定文本，或在指定位置插入/删除内容。类似代码编辑器的 apply_diff 功能。",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "节点名称"
                        },
                        "search": {
                            "type": "string",
                            "description": "要查找的原始内容（精确匹配）"
                        },
                        "replace": {
                            "type": "string",
                            "description": "替换为的新内容（留空表示删除）"
                        }
                    },
                    "required": ["name", "search", "replace"]
                },
                category=ToolCategory.WRITE,
                handler=self._edit_node
            )
            
            self.tools["edit_summary"] = ToolDefinition(
                name="edit_summary",
                description="精确编辑总结内容。可以搜索并替换指定文本。",
                parameters={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["weekly", "monthly", "quarterly", "yearly"],
                            "description": "总结类型"
                        },
                        "identifier": {
                            "type": "string",
                            "description": "标识符，如 2025-W52、2025-12"
                        },
                        "search": {
                            "type": "string",
                            "description": "要查找的原始内容（精确匹配）"
                        },
                        "replace": {
                            "type": "string",
                            "description": "替换为的新内容（留空表示删除）"
                        }
                    },
                    "required": ["type", "identifier", "search", "replace"]
                },
                category=ToolCategory.WRITE,
                handler=self._edit_summary
            )
            
            # read_graph 已移到外面（只读工具）
        
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
        
        # graphiti_multi_hop
        self.tools["graphiti_multi_hop"] = ToolDefinition(
            name="graphiti_multi_hop",
            description=GRAPHITI_TOOLS_DEFINITIONS["graphiti_multi_hop"]["description"],
            parameters=GRAPHITI_TOOLS_DEFINITIONS["graphiti_multi_hop"]["parameters"],
            category=ToolCategory.SEARCH,
            handler=self.graphiti_handlers.graphiti_multi_hop
        )
        
        # graphiti_get_stats
        self.tools["graphiti_get_stats"] = ToolDefinition(
            name="graphiti_get_stats",
            description=GRAPHITI_TOOLS_DEFINITIONS["graphiti_get_stats"]["description"],
            parameters=GRAPHITI_TOOLS_DEFINITIONS["graphiti_get_stats"]["parameters"],
            category=ToolCategory.READ,
            handler=self.graphiti_handlers.graphiti_get_stats
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
            
            # graphiti_sync_node（归类为 WRITE）
            self.tools["graphiti_sync_node"] = ToolDefinition(
                name="graphiti_sync_node",
                description=GRAPHITI_TOOLS_DEFINITIONS["graphiti_sync_node"]["description"],
                parameters=GRAPHITI_TOOLS_DEFINITIONS["graphiti_sync_node"]["parameters"],
                category=ToolCategory.WRITE,
                handler=self.graphiti_handlers.graphiti_sync_node
            )
        
        graphiti_count = self._count_graphiti_tools()
        print(f"[Graphiti] 已注册 {graphiti_count} 个工具")
    
    def _count_graphiti_tools(self) -> int:
        """统计 Graphiti 工具数量"""
        return sum(1 for name in self.tools if name.startswith("graphiti_"))
    
    # ==================== 工具处理函数 ====================
    
    def _search_memories(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        people: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        limit: int = 10
    ) -> str:
        """搜索记忆"""
        results = self.indexer.search(
            query=query,
            tags=tags,
            people=people,
            date_start=date_start,
            date_end=date_end,
            limit=limit
        )
        
        if not results:
            return "未找到相关记忆。"
        
        output = f"找到 {len(results)} 条相关记忆：\n\n"
        for i, r in enumerate(results, 1):
            output += f"{i}. [{r['type']}] "
            if r.get('date'):
                output += f"{r['date']} "
            if r.get('title'):
                output += f"《{r['title']}》"
            output += "\n"
            if r.get('tags'):
                output += f"   标签: {', '.join(r['tags'])}\n"
            output += f"   摘要: {r['snippet'][:100]}...\n\n"
        
        return output
    
    def _rag_search(
        self,
        query: str,
        top_k: int = 5,
        filter_type: str = "all"
    ) -> str:
        """RAG语义搜索记忆"""
        if not self.rag_searcher:
            return "❌ RAG语义搜索未启用。请在配置中设置 rag.enabled=true 和 API Key。"
        
        # 处理类型过滤
        type_filter = None if filter_type == "all" else filter_type
        
        try:
            return self.rag_searcher.semantic_search(query, top_k=top_k, filter_type=type_filter)
        except Exception as e:
            return f"❌ RAG搜索出错: {str(e)}"
    
    def _read_diary(self, date: str) -> str:
        """读取日记"""
        diary = self.reader.read_diary(date)
        
        if not diary:
            return f"未找到 {date} 的日记。"
        
        output = f"📅 {date} 日记"
        if diary.title:
            output += f" - {diary.title}"
        output += "\n"
        output += "=" * 40 + "\n\n"
        output += diary.content
        
        if diary.tags:
            output += f"\n\n标签: {', '.join('#' + t for t in diary.tags)}"
        if diary.links:
            output += f"\n链接: {', '.join('[[' + l + ']]' for l in diary.links)}"
        
        return output
    
    def _read_summary(self, type: str, identifier: str) -> str:
        """读取总结"""
        summary = self.reader.read_summary(type, identifier)
        
        if not summary:
            return f"未找到 {type} 总结 {identifier}。"
        
        type_names = {
            "weekly": "周",
            "monthly": "月",
            "quarterly": "季度",
            "yearly": "年度"
        }
        
        output = f"📊 {identifier} {type_names.get(type, '')}总结\n"
        output += "=" * 40 + "\n\n"
        output += summary.content
        
        return output
    
    def _get_node(self, name: str) -> str:
        """获取节点"""
        node = self.reader.read_node(name)
        
        if not node:
            # 尝试搜索
            results = self.reader.search_nodes_by_name(name)
            if results:
                output = f"未找到名为 '{name}' 的节点，但找到以下相似节点：\n"
                for r in results[:5]:
                    output += f"  - {r.name} ({r.type})\n"
                return output
            return f"未找到名为 '{name}' 的节点。"
        
        output = f"📌 {node.name}\n"
        output += f"类型: {node.type}\n"
        output += "=" * 40 + "\n\n"
        output += node.content
        
        if node.tags:
            output += f"\n\n标签: {', '.join('#' + t for t in node.tags)}"
        if node.links:
            output += f"\n关联: {', '.join('[[' + l + ']]' for l in node.links)}"
        
        return output
    
    def _list_recent(self, days: int = 7) -> str:
        """列出最近日记"""
        diaries = self.reader.read_recent_diaries(days)
        
        if not diaries:
            return f"最近 {days} 天没有日记记录。"
        
        output = f"📅 最近 {days} 天的日记：\n\n"
        for diary in diaries:
            output += f"• {diary.date}"
            if diary.title:
                output += f" - {diary.title}"
            output += "\n"
            # 显示前100字作为预览
            preview = diary.content.replace("\n", " ")[:100]
            output += f"  {preview}...\n\n"
        
        return output
    
    def _get_current_context(self) -> str:
        """获取当前时间上下文"""
        now = datetime.now()
        iso_cal = now.isocalendar()
        
        # ISO 周历年份可能与日历年份不同
        # 例如：2025-12-29 属于 2026-W01（因为该周的周四在2026年）
        iso_year = iso_cal[0]  # ISO 周历年份
        iso_week = iso_cal[1]  # ISO 周数
        
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        
        output = "📆 当前时间上下文：\n\n"
        output += f"今天: {now.strftime('%Y-%m-%d')} ({weekday_names[now.weekday()]})\n"
        
        # 显示ISO周，并在年份不同时特别说明
        week_str = f"{iso_year}-W{iso_week:02d}"
        if iso_year != now.year:
            output += f"本周: {week_str}（注：按ISO周历属于{iso_year}年）\n"
        else:
            output += f"本周: {week_str}\n"
        
        output += f"本月: {now.strftime('%Y-%m')}\n"
        output += f"本季度: {now.year}-Q{(now.month - 1) // 3 + 1}\n"
        output += f"本年: {now.year}\n"
        
        # 检查是否有今天的日记
        today_diary = self.reader.read_diary(now.strftime("%Y-%m-%d"))
        if today_diary:
            output += f"\n✓ 今天已有日记记录"
        else:
            output += f"\n✗ 今天尚无日记记录"
        
        return output
    
    def _list_all_tags(self, limit: int = 20) -> str:
        """列出所有标签"""
        tags = self.indexer.get_all_tags()[:limit]
        
        if not tags:
            return "暂无标签记录。"
        
        output = f"🏷️ 标签列表（共 {len(self.indexer.index.tags)} 个）：\n\n"
        for tag, count in tags:
            output += f"  #{tag}: {count}次\n"
        
        return output
    
    def _list_all_people(self, limit: int = 20) -> str:
        """列出所有人物"""
        people = self.indexer.get_all_people()[:limit]
        
        if not people:
            return "暂无人物记录。"
        
        output = f"👥 人物列表（共 {len(self.indexer.index.people)} 人）：\n\n"
        for person, count in people:
            output += f"  [[{person}]]: 出现{count}次\n"
        
        return output
    
    def _list_nodes(self, type: str = "all") -> str:
        """列出所有节点"""
        from pathlib import Path
        
        nodes_dir = Path(self.lifebook_path) / "nodes"
        if not nodes_dir.exists():
            return "节点目录不存在。"
        
        # 收集节点
        nodes_by_type = {"人物": [], "地点": [], "事物": [], "概念": []}
        
        for file in nodes_dir.glob("*.md"):
            name = file.stem
            # 解析类型
            for t in ["人物", "地点", "事物", "概念"]:
                if name.startswith(f"{t}-"):
                    node_name = name[len(t)+1:]
                    nodes_by_type[t].append(node_name)
                    break
        
        # 过滤类型
        if type != "all":
            if type in nodes_by_type:
                nodes_by_type = {type: nodes_by_type[type]}
            else:
                return f"未知类型：{type}"
        
        # 生成输出
        total = sum(len(v) for v in nodes_by_type.values())
        if total == 0:
            return "暂无节点。"
        
        output = f"📋 节点列表（共 {total} 个）：\n\n"
        for t, nodes in nodes_by_type.items():
            if nodes:
                output += f"### {t}（{len(nodes)}个）\n"
                for n in sorted(nodes):
                    output += f"  - [[{n}]]\n"
                output += "\n"
        
        return output
    
    def _get_memory_overview(self) -> str:
        """获取记忆系统概览"""
        from pathlib import Path
        
        output = "# 📚 记忆系统概览\n\n"
        
        # 1. 节点统计
        nodes_dir = Path(self.lifebook_path) / "nodes"
        nodes_count = {"人物": 0, "地点": 0, "事物": 0, "概念": 0}
        all_nodes = []
        
        if nodes_dir.exists():
            for file in nodes_dir.glob("*.md"):
                name = file.stem
                for t in ["人物", "地点", "事物", "概念"]:
                    if name.startswith(f"{t}-"):
                        nodes_count[t] += 1
                        all_nodes.append((t, name[len(t)+1:]))
                        break
        
        output += "## 节点概览\n\n"
        for t, count in nodes_count.items():
            if count > 0:
                output += f"- **{t}**: {count}个\n"
        
        if all_nodes:
            output += "\n### 完整节点列表\n"
            for t, name in sorted(all_nodes):
                output += f"- [{t}] [[{name}]]\n"
        else:
            output += "\n*暂无节点*\n"
        
        # 2. 日记统计
        daily_dir = Path(self.lifebook_path) / "daily"
        diary_count = 0
        recent_diaries = []
        
        if daily_dir.exists():
            diary_files = sorted(daily_dir.glob("*.md"), reverse=True)
            diary_count = len(diary_files)
            for f in diary_files[:5]:
                recent_diaries.append(f.stem)
        
        output += f"\n## 日记概览\n\n"
        output += f"- **总日记数**: {diary_count}篇\n"
        if recent_diaries:
            output += f"- **最近日记**: {', '.join(recent_diaries)}\n"
        
        # 3. 标签统计
        tags = self.indexer.get_all_tags()[:10]
        if tags:
            output += f"\n## 热门标签（前10）\n\n"
            for tag, count in tags:
                output += f"- #{tag}: {count}次\n"
        
        # 4. 人物统计
        people = self.indexer.get_all_people()[:10]
        if people:
            output += f"\n## 常提及人物（前10）\n\n"
            for person, count in people:
                output += f"- [[{person}]]: {count}次\n"
        
        return output
    
    def _add_to_diary(
        self,
        content: str,
        date: Optional[str] = None,
        section: Optional[str] = None
    ) -> str:
        """添加日记内容"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        try:
            success = self.writer.append_to_diary(date, content, section)
            
            if success:
                # 更新索引 - 使用 os.path.join 避免 Path 对象问题
                file_path = os.path.join(self.lifebook_path, "daily", f"{date}.md")
                self.indexer.index_file(file_path)
                return f"✓ 已成功添加内容到 {date} 的日记。"
            else:
                return f"✗ 添加内容失败。"
        except Exception as e:
            return f"✗ 添加日记出错：{str(e)}"
    
    def _create_node(
        self,
        name: str,
        type: str,
        content: str,
        tags: Optional[List[str]] = None
    ) -> str:
        """创建节点"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        try:
            success = self.writer.create_node(name, type, content, tags)
            
            if success:
                # 更新索引 - 使用 os.path.join 避免 Path 对象问题
                file_path = os.path.join(self.lifebook_path, "nodes", f"{type}-{name}.md")
                self.indexer.index_file(file_path)
                
                # 新增人物节点会影响人物识别缓存（[[小明]] 这种无前缀链接识别）
                if type == "人物":
                    self.indexer.invalidate_people_cache()
                
                return f"✓ 已成功创建 {type} 节点 [[{name}]]。"
            else:
                return f"✗ 创建节点失败，可能已存在同名节点。"
        except Exception as e:
            return f"✗ 创建节点出错：{str(e)}"
    
    def _update_node(
        self,
        name: str,
        content: str,
        mode: str = "append"
    ) -> str:
        """更新节点"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        success = self.writer.update_node(name, content, mode)
        
        if success:
            # 更新索引：用 reader 解析出实际文件路径（支持 name 带/不带类型前缀）
            try:
                node = self.reader.read_node(name)
                if node and node.file_path:
                    self.indexer.index_file(node.file_path)
            except Exception:
                # 索引失败不影响写入结果
                pass
            
            return f"✓ 已成功更新节点 [[{name}]]。"
        else:
            return f"✗ 更新节点失败，节点可能不存在。"
    
    def _create_summary(
        self,
        type: str,
        identifier: str,
        content: str,
        title: Optional[str] = None
    ) -> str:
        """创建总结"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        success = self.writer.create_summary(type, identifier, content, title)
        
        if success:
            # 更新索引：让 search_memories 立即可检索到新总结
            try:
                file_path = os.path.join(self.lifebook_path, type, f"{identifier}.md")
                self.indexer.index_file(file_path)
            except Exception:
                pass
            
            return f"✓ 已成功创建 {type} 总结 {identifier}。"
        else:
            return f"✗ 创建总结失败，可能已存在。"
    
    def _delete_node(self, name: str, confirm: bool = False) -> str:
        """删除节点"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        if not confirm:
            return f"⚠️ 删除操作需要确认。请设置 confirm=true 来确认删除节点 [[{name}]]。"
        
        from pathlib import Path
        
        # 查找节点文件
        nodes_dir = Path(self.lifebook_path) / "nodes"
        found_file = None
        node_type = None
        actual_name = name
        
        # 尝试不同的名称格式（模型可能传入带前缀或不带前缀的名称）
        names_to_try = [name]
        
        # 如果名称以类型前缀开头，也尝试去掉前缀
        for t in ["人物", "地点", "事物", "概念"]:
            if name.startswith(f"{t}-"):
                stripped_name = name[len(t)+1:]
                if stripped_name not in names_to_try:
                    names_to_try.append(stripped_name)
                break
        
        for try_name in names_to_try:
            for t in ["人物", "地点", "事物", "概念"]:
                file_path = nodes_dir / f"{t}-{try_name}.md"
                if file_path.exists():
                    found_file = file_path
                    node_type = t
                    actual_name = try_name
                    break
            if found_file:
                break
        
        if not found_file:
            return f"✗ 未找到节点 [[{name}]]。尝试过的文件名: {[f'{t}-{n}.md' for n in names_to_try for t in ['人物','地点','事物','概念']][:4]}..."
        
        try:
            # 删除文件
            found_file.unlink()
            # 从索引中移除（重建索引）
            self.indexer.rebuild_index()
            return f"✓ 已永久删除 {node_type} 节点 [[{actual_name}]]。"
        except Exception as e:
            return f"✗ 删除节点失败：{str(e)}"
    
    def _delete_summary(self, type: str, identifier: str, confirm: bool = False) -> str:
        """删除总结"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        if not confirm:
            return f"⚠️ 删除操作需要确认。请设置 confirm=true 来确认删除 {type} 总结 {identifier}。"
            
        from pathlib import Path
        
        # 构造文件路径
        summary_dir = Path(self.lifebook_path) / type
        summary_file = summary_dir / f"{identifier}.md"

        if not summary_file.exists():
            return f"✗ 未找到 {type} 总结 {identifier}。"
            
        try:
            # 删除文件
            summary_file.unlink()
            # 从索引中移除（重建索引）
            self.indexer.rebuild_index()
            return f"✓ 已永久删除 {type} 总结 {identifier}。"
        except Exception as e:
            return f"✗ 删除总结失败：{str(e)}"

    def _add_observations(self, observations: List[Dict[str, Any]]) -> str:
        """向节点添加观察（离散事实）"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        results = []
        for obs in observations:
            name = obs.get("name", "")
            contents = obs.get("contents", [])
            
            if not name or not contents:
                continue
            
            # 检查节点是否存在
            node = self.reader.read_node(name)
            if not node:
                results.append(f"✗ 节点 [[{name}]] 不存在")
                continue
            
            # 格式化观察内容
            obs_content = "\n\n## 观察记录\n\n"
            for i, content in enumerate(contents, 1):
                obs_content += f"- {content}\n"
            
            # 追加到节点
            success = self.writer.update_node(name, obs_content, mode="append")
            if success:
                # 更新索引：新增观察可能包含关键词/标签/链接
                try:
                    node_after = self.reader.read_node(name)
                    if node_after and node_after.file_path:
                        self.indexer.index_file(node_after.file_path)
                except Exception:
                    pass
                
                results.append(f"✓ 向 [[{name}]] 添加了 {len(contents)} 条观察")
            else:
                results.append(f"✗ 更新 [[{name}]] 失败")
        
        return "\n".join(results) if results else "没有添加任何观察"
    
    def _create_relations(self, relations: List[Dict[str, Any]]) -> str:
        """创建节点之间的关系"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        results = []
        for rel in relations:
            from_node = rel.get("from", "")
            to_node = rel.get("to", "")
            relation_type = rel.get("relation_type", "关联")
            
            if not from_node or not to_node:
                continue
            
            # 检查两个节点是否存在
            node_from = self.reader.read_node(from_node)
            node_to = self.reader.read_node(to_node)
            
            errors = []
            if not node_from:
                errors.append(f"[[{from_node}]]")
            if not node_to:
                errors.append(f"[[{to_node}]]")
            
            if errors:
                results.append(f"✗ 节点不存在: {', '.join(errors)}")
                continue
            
            # 在 from_node 中添加 to_node 的链接
            link_content = f"\n\n### 关联：{relation_type}\n\n- [[{to_node}]]（{relation_type}）\n"
            success_from = self.writer.update_node(from_node, link_content, mode="append")
            
            # 在 to_node 中添加 from_node 的反向链接
            reverse_content = f"\n\n### 被关联\n\n- [[{from_node}]]（{relation_type} 的对象）\n"
            success_to = self.writer.update_node(to_node, reverse_content, mode="append")
            
            # 更新索引：关系变化会影响 links/people 识别
            try:
                if success_from:
                    node_from_after = self.reader.read_node(from_node)
                    if node_from_after and node_from_after.file_path:
                        self.indexer.index_file(node_from_after.file_path)
                if success_to:
                    node_to_after = self.reader.read_node(to_node)
                    if node_to_after and node_to_after.file_path:
                        self.indexer.index_file(node_to_after.file_path)
            except Exception:
                pass
            
            results.append(f"✓ 创建关系: [[{from_node}]] --{relation_type}--> [[{to_node}]]")
        
        return "\n".join(results) if results else "没有创建任何关系"
    
    def _edit_diary(self, date: str, search: str, replace: str, replace_all: bool = False) -> str:
        """精确编辑日记内容"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        from pathlib import Path
        
        diary_file = Path(self.lifebook_path) / "daily" / f"{date}.md"
        if not diary_file.exists():
            return f"✗ 未找到 {date} 的日记"
        
        try:
            # 读取当前内容
            content = diary_file.read_text(encoding=self.encoding)
            
            # 检查是否包含要查找的内容
            if search not in content:
                # 尝试模糊匹配（忽略首尾空白）
                search_stripped = search.strip()
                found = False
                for line in content.split('\n'):
                    if search_stripped in line:
                        found = True
                        break
                
                if not found:
                    # 显示当前内容的一部分帮助调试
                    preview = content[:500] + "..." if len(content) > 500 else content
                    return f"✗ 未找到要替换的内容。\n\n当前日记内容预览:\n```\n{preview}\n```"
            
            # 执行替换
            match_count = content.count(search)
            if replace_all:
                new_content = content.replace(search, replace)  # 替换所有匹配
            else:
                new_content = content.replace(search, replace, 1)  # 只替换第一个匹配
            
            if new_content == content:
                return f"✗ 替换未生效（内容相同）"
            
            # 写回文件
            diary_file.write_text(new_content, encoding=self.encoding)
            
            # 更新索引
            self.indexer.index_file(str(diary_file))
            
            # 计算变化
            replaced_count = match_count if replace_all else 1
            if replace == "":
                action = "删除"
                detail = f"已从日记中移除 {replaced_count} 处匹配（共 {len(search) * replaced_count} 个字符）"
            elif search == "":
                action = "插入"
                detail = f"已在日记中插入 {len(replace)} 个字符"
            else:
                action = "替换"
                if replace_all and match_count > 1:
                    detail = f"已替换全部 {match_count} 处匹配"
                else:
                    detail = f"已将匹配的 {len(search)} 个字符替换为 {len(replace)} 个字符"
            
            return f"✓ {date} 日记编辑成功：{detail}。其余内容保持不变。"
            
        except Exception as e:
            return f"✗ 编辑日记失败: {str(e)}"
    
    def _rewrite_diary(self, date: str, content: str, title: Optional[str] = None) -> str:
        """完全重写日记正文，保留 frontmatter"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        from pathlib import Path
        import re
        
        diary_file = Path(self.lifebook_path) / "daily" / f"{date}.md"
        if not diary_file.exists():
            return f"✗ 未找到 {date} 的日记"
        
        try:
            # 读取当前内容
            old_content = diary_file.read_text(encoding=self.encoding)
            
            # 解析 frontmatter
            frontmatter = ""
            body_start = 0
            
            if old_content.startswith("---"):
                # 找到第二个 ---
                end_match = re.search(r'\n---\s*\n', old_content[3:])
                if end_match:
                    frontmatter_end = 3 + end_match.end()
                    frontmatter = old_content[:frontmatter_end]
                    body_start = frontmatter_end
            
            # 如果没有 frontmatter，创建一个基本的
            if not frontmatter:
                frontmatter = f"""---
date: {date}
---

"""
            
            # 如果提供了新标题，更新 frontmatter 中的 title
            if title:
                if 'title:' in frontmatter:
                    frontmatter = re.sub(r'title:.*\n', f'title: {title}\n', frontmatter)
                else:
                    # 在 date: 后面添加 title
                    frontmatter = re.sub(r'(date:.*\n)', f'\\1title: {title}\n', frontmatter)
            
            # 组装新内容
            new_content = frontmatter + content
            
            # 确保内容以换行结尾
            if not new_content.endswith('\n'):
                new_content += '\n'
            
            # 写回文件
            diary_file.write_text(new_content, encoding=self.encoding)
            
            # 更新索引
            self.indexer.index_file(str(diary_file))
            
            old_body = old_content[body_start:]
            old_len = len(old_body.strip())
            new_len = len(content.strip())
            
            return f"✓ {date} 日记已重写完成！\n  - 原正文: {old_len} 字符\n  - 新正文: {new_len} 字符\n  - frontmatter 已保留"
            
        except Exception as e:
            return f"✗ 重写日记失败: {str(e)}"
    
    def _edit_node(self, name: str, search: str, replace: str) -> str:
        """精确编辑节点内容"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        from pathlib import Path
        
        # 查找节点文件
        nodes_dir = Path(self.lifebook_path) / "nodes"
        found_file = None
        
        for t in ["人物", "地点", "事物", "概念"]:
            file_path = nodes_dir / f"{t}-{name}.md"
            if file_path.exists():
                found_file = file_path
                break
        
        if not found_file:
            return f"✗ 未找到节点 [[{name}]]"
        
        try:
            # 读取当前内容
            content = found_file.read_text(encoding=self.encoding)
            
            # 检查是否包含要查找的内容
            if search not in content:
                preview = content[:500] + "..." if len(content) > 500 else content
                return f"✗ 未找到要替换的内容。\n\n当前节点内容预览:\n```\n{preview}\n```"
            
            # 执行替换
            new_content = content.replace(search, replace, 1)
            
            if new_content == content:
                return f"✗ 替换未生效（内容相同）"
            
            # 写回文件
            found_file.write_text(new_content, encoding=self.encoding)
            
            # 更新索引
            self.indexer.index_file(str(found_file))
            
            # 计算变化
            if replace == "":
                action = "删除"
                detail = f"已从节点中移除匹配的 {len(search)} 个字符"
            elif search == "":
                action = "插入"
                detail = f"已在节点中插入 {len(replace)} 个字符"
            else:
                action = "替换"
                detail = f"已将匹配的 {len(search)} 个字符替换为 {len(replace)} 个字符"
            
            return f"✓ 节点 [[{name}]] 编辑成功：{detail}。其余内容保持不变。"
            
        except Exception as e:
            return f"✗ 编辑节点失败: {str(e)}"
    
    def _edit_summary(self, type: str, identifier: str, search: str, replace: str) -> str:
        """精确编辑总结内容"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        from pathlib import Path
        
        summary_file = Path(self.lifebook_path) / type / f"{identifier}.md"
        if not summary_file.exists():
            return f"✗ 未找到 {type} 总结 {identifier}"
        
        try:
            # 读取当前内容
            content = summary_file.read_text(encoding=self.encoding)
            
            # 检查是否包含要查找的内容
            if search not in content:
                preview = content[:500] + "..." if len(content) > 500 else content
                return f"✗ 未找到要替换的内容。\n\n当前总结内容预览:\n```\n{preview}\n```"
            
            # 执行替换
            new_content = content.replace(search, replace, 1)
            
            if new_content == content:
                return f"✗ 替换未生效（内容相同）"
            
            # 写回文件
            summary_file.write_text(new_content, encoding=self.encoding)
            
            # 更新索引
            self.indexer.index_file(str(summary_file))
            
            # 计算变化
            if replace == "":
                action = "删除"
                detail = f"已从总结中移除匹配的 {len(search)} 个字符"
            elif search == "":
                action = "插入"
                detail = f"已在总结中插入 {len(replace)} 个字符"
            else:
                action = "替换"
                detail = f"已将匹配的 {len(search)} 个字符替换为 {len(replace)} 个字符"
            
            return f"✓ {type} 总结 {identifier} 编辑成功：{detail}。其余内容保持不变。"
            
        except Exception as e:
            return f"✗ 编辑总结失败: {str(e)}"
    
    def _add_to_pending(self, topic: str, summary: str) -> str:
        """添加摘要到待处理暂存区"""
        # 注意：不需要检查 self.writer，因为 PendingManager 直接写文件，不依赖 writer
        try:
            from memory_store.pending_manager import PendingManager, create_pending_summary
            
            # 创建 PendingSummary
            pending_summary = create_pending_summary(
                summary=summary,
                topic=topic,
                tool_calls=[],  # 手动添加的不涉及工具调用
                raw_turns=0     # 手动添加的不计算轮数
            )
            
            # 添加到暂存区
            pending_mgr = PendingManager(self.lifebook_path, self.encoding)
            success = pending_mgr.add_pending(pending_summary)
            
            if success:
                return f"✓ 已将摘要暂存到 pending 目录\n  📌 主题: {topic}\n  📝 内容: {summary[:100]}..."
            else:
                return "✗ 暂存失败"
                
        except Exception as e:
            return f"✗ 添加到 pending 失败: {str(e)}"
    
    def _read_all_nodes(self, type: str = "all", max_content_length: int = 0) -> str:
        """一键读取所有节点的完整内容"""
        from pathlib import Path
        
        nodes_dir = Path(self.lifebook_path) / "nodes"
        if not nodes_dir.exists():
            return "节点目录不存在。"
        
        # 收集节点
        nodes_by_type = {"人物": [], "地点": [], "事物": [], "概念": []}
        
        for file in nodes_dir.glob("*.md"):
            name = file.stem
            for t in ["人物", "地点", "事物", "概念"]:
                if name.startswith(f"{t}-"):
                    node_name = name[len(t)+1:]
                    nodes_by_type[t].append(node_name)
                    break
        
        # 过滤类型
        if type != "all":
            if type in nodes_by_type:
                nodes_by_type = {type: nodes_by_type[type]}
            else:
                return f"未知类型：{type}"
        
        # 计算总数
        total = sum(len(v) for v in nodes_by_type.values())
        if total == 0:
            return "暂无节点。"
        
        output = f"# 📖 所有节点内容（共 {total} 个）\n\n"
        
        for node_type, node_names in nodes_by_type.items():
            if not node_names:
                continue
            
            output += f"## {node_type}（{len(node_names)}个）\n\n"
            
            for node_name in sorted(node_names):
                node = self.reader.read_node(node_name)
                if node:
                    output += f"### 📌 {node_name}\n\n"
                    
                    content = node.content
                    if max_content_length > 0 and len(content) > max_content_length:
                        content = content[:max_content_length] + f"\n... (已截断，原文 {len(node.content)} 字符)"
                    
                    output += content + "\n"
                    
                    if node.tags:
                        output += f"\n标签: {', '.join('#' + t for t in node.tags)}\n"
                    if node.links:
                        output += f"关联: {', '.join('[[' + l + ']]' for l in node.links)}\n"
                    
                    output += "\n---\n\n"
        
        return output
    
    def _read_graph(self) -> str:
        """读取整个知识图谱（包含反向链接）"""
        from pathlib import Path
        
        output = "# 🕸️ 知识图谱\n\n"
        
        nodes_dir = Path(self.lifebook_path) / "nodes"
        if not nodes_dir.exists():
            return "知识图谱为空。"
        
        # 第一遍：收集所有节点和正向链接
        entities = []
        relations = []
        node_name_map = {}  # node_name -> entity index
        
        for file in nodes_dir.glob("*.md"):
            name = file.stem
            node_type = None
            node_name = None
            
            for t in ["人物", "地点", "事物", "概念"]:
                if name.startswith(f"{t}-"):
                    node_type = t
                    node_name = name[len(t)+1:]
                    break
            
            if not node_type or not node_name:
                continue
            
            # 读取节点内容
            node = self.reader.read_node(node_name)
            if node:
                # 提取观察（简化处理）
                observations = []
                for line in node.content.split("\n"):
                    line = line.strip()
                    if line.startswith("- ") and not line.startswith("- [["):
                        observations.append(line[2:])
                
                entity = {
                    "name": node_name,
                    "type": node_type,
                    "observations": observations[:5],  # 最多5条
                    "links": node.links,
                    "backlinks": []  # 反向链接：谁链接了我
                }
                node_name_map[node_name] = len(entities)
                entities.append(entity)
                
                # 提取关系（正向）
                for link in node.links:
                    relations.append({
                        "from": node_name,
                        "to": link,
                        "type": "关联"
                    })
        
        # 第二遍：计算反向链接
        for entity in entities:
            for link in entity["links"]:
                # 查找被链接的节点
                if link in node_name_map:
                    target_idx = node_name_map[link]
                    if entity["name"] not in entities[target_idx]["backlinks"]:
                        entities[target_idx]["backlinks"].append(entity["name"])
        
        # 格式化输出
        output += f"## 实体（{len(entities)}个）\n\n"
        for e in entities:
            output += f"### [{e['type']}] {e['name']}\n"
            if e['observations']:
                output += "观察:\n"
                for obs in e['observations']:
                    output += f"  - {obs}\n"
            if e['links']:
                output += f"链接（指向）: {', '.join('[[' + l + ']]' for l in e['links'])}\n"
            if e['backlinks']:
                output += f"被链接（来自）: {', '.join('[[' + l + ']]' for l in e['backlinks'])}\n"
            output += "\n"
        
        # 去重关系
        seen = set()
        unique_relations = []
        for r in relations:
            key = (r['from'], r['to'])
            if key not in seen and (r['to'], r['from']) not in seen:
                seen.add(key)
                unique_relations.append(r)
        
        output += f"## 关系（{len(unique_relations)}个）\n\n"
        for r in unique_relations:
            output += f"- [[{r['from']}]] --{r['type']}--> [[{r['to']}]]\n"
        
        return output
    
    # ==================== 工具调用接口 ====================
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        调用工具
        
        Args:
            tool_name: 工具名称
            arguments: 参数字典
            
        Returns:
            工具执行结果（字符串）
        """
        if tool_name not in self.tools:
            return f"错误：未知工具 '{tool_name}'"
        
        tool = self.tools[tool_name]
        
        try:
            # 过滤参数：只传递工具定义中声明的参数，忽略多余参数
            # 这样可以容忍模型传入未定义的参数（如 reason）
            defined_params = tool.parameters.get("properties", {}).keys()
            filtered_args = {k: v for k, v in arguments.items() if k in defined_params}
            
            result = tool.handler(**filtered_args)
            return result
        except Exception as e:
            return f"错误：工具执行失败 - {str(e)}"
    
    def get_available_tools(
        self,
        include_write: bool = False
    ) -> List[ToolDefinition]:
        """获取可用工具列表"""
        tools = []
        for tool in self.tools.values():
            if tool.category == ToolCategory.WRITE and not include_write:
                continue
            tools.append(tool)
        return tools
    
    def get_openai_tools(
        self,
        include_write: bool = False
    ) -> List[Dict[str, Any]]:
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


# ==================== 便捷函数 ====================

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


# 测试代码已移至 tests/test_tools.py
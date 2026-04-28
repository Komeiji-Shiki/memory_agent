"""
常量定义模块

集中管理项目中所有的硬编码字符串和常量，避免魔法值分散在代码中。
"""

from enum import Enum


class ModelSuffixes:
    """模型后缀常量"""
    MEMORY = "-memory"
    MEMORY_SIMPLE = "-memory-simple"
    RECORD = "-record"
    LOG = "-log"
    LOG_WRITE = "-log-write"
    
    @classmethod
    def all_suffixes(cls) -> list:
        return [cls.MEMORY, cls.MEMORY_SIMPLE, cls.RECORD, cls.LOG, cls.LOG_WRITE]


class RouteModes:
    """路由模式常量"""
    MEMORY = "memory"
    MANAGER = "manager"
    RECORD = "record"
    LOG = "log"
    LOG_WRITE = "log-write"
    PASSTHROUGH = "passthrough"


class ToolCategories:
    """工具类别常量"""
    READ = "read"
    WRITE = "write"
    SEARCH = "search"


class MemoryToolNames:
    """记忆工具名称常量"""
    # 搜索工具
    SEARCH_MEMORIES = "search_memories"
    RAG_SEARCH = "rag_search"
    
    # 只读工具
    READ_DIARY = "read_diary"
    READ_SUMMARY = "read_summary"
    GET_NODE = "get_node"
    LIST_RECENT = "list_recent"
    GET_CURRENT_CONTEXT = "get_current_context"
    GET_CURRENT_TIME = "get_current_time"
    LIST_ALL_TAGS = "list_all_tags"
    LIST_ALL_PEOPLE = "list_all_people"
    LIST_NODES = "list_nodes"
    GET_MEMORY_OVERVIEW = "get_memory_overview"
    READ_GRAPH = "read_graph"
    READ_ALL_NODES = "read_all_nodes"
    
    # 写入工具
    ADD_TO_DIARY = "add_to_diary"
    CREATE_NODE = "create_node"
    UPDATE_NODE = "update_node"
    CREATE_SUMMARY = "create_summary"
    DELETE_NODE = "delete_node"
    DELETE_SUMMARY = "delete_summary"
    ADD_OBSERVATIONS = "add_observations"
    CREATE_RELATIONS = "create_relations"
    
    # 编辑工具
    EDIT_DIARY = "edit_diary"
    EDIT_NODE = "edit_node"
    EDIT_SUMMARY = "edit_summary"
    REWRITE_DIARY = "rewrite_diary"
    
    # 暂存工具
    ADD_TO_PENDING = "add_to_pending"
    
    # Graphiti 工具
    GRAPHITI_SEARCH = "graphiti_search"
    GRAPHITI_TEMPORAL = "graphiti_temporal"
    GRAPHITI_MULTI_HOP = "graphiti_multi_hop"
    GRAPHITI_GET_STATS = "graphiti_get_stats"
    GRAPHITI_ADD = "graphiti_add"
    GRAPHITI_SYNC_NODE = "graphiti_sync_node"
    
    @classmethod
    def all_read_tools(cls) -> set:
        """所有只读工具"""
        return {
            cls.SEARCH_MEMORIES, cls.RAG_SEARCH,
            cls.READ_DIARY, cls.READ_SUMMARY,
            cls.GET_NODE, cls.LIST_RECENT,
            cls.GET_CURRENT_CONTEXT, cls.GET_CURRENT_TIME,
            cls.LIST_ALL_TAGS, cls.LIST_ALL_PEOPLE,
            cls.LIST_NODES, cls.GET_MEMORY_OVERVIEW,
            cls.READ_GRAPH, cls.READ_ALL_NODES,
            cls.ADD_TO_PENDING,  # 虽然是写入操作，但不需要 enable_write
            cls.GRAPHITI_SEARCH, cls.GRAPHITI_TEMPORAL,
            cls.GRAPHITI_MULTI_HOP, cls.GRAPHITI_GET_STATS,
        }
    
    @classmethod
    def all_write_tools(cls) -> set:
        """所有写入工具"""
        return {
            cls.ADD_TO_DIARY, cls.CREATE_NODE,
            cls.UPDATE_NODE, cls.CREATE_SUMMARY,
            cls.DELETE_NODE, cls.DELETE_SUMMARY,
            cls.ADD_OBSERVATIONS, cls.CREATE_RELATIONS,
            cls.EDIT_DIARY, cls.EDIT_NODE,
            cls.EDIT_SUMMARY, cls.REWRITE_DIARY,
            cls.GRAPHITI_ADD, cls.GRAPHITI_SYNC_NODE,
        }
    
    @classmethod
    def is_memory_tool(cls, name: str) -> bool:
        """检查是否是记忆工具"""
        return name in cls.all_read_tools() or name in cls.all_write_tools()
    
    @classmethod
    def is_write_tool(cls, name: str) -> bool:
        """检查是否是写入工具"""
        return name in cls.all_write_tools()


class NodeTypes:
    """节点类型常量"""
    PERSON = "人物"
    LOCATION = "地点"
    THING = "事物"
    CONCEPT = "概念"
    
    ALL_TYPES = [PERSON, LOCATION, THING, CONCEPT]
    
    @classmethod
    def validate(cls, node_type: str) -> bool:
        return node_type in cls.ALL_TYPES


class SummaryTypes:
    """总结类型常量"""
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    
    ALL_TYPES = [WEEKLY, MONTHLY, QUARTERLY, YEARLY]
    
    TYPE_NAMES = {
        WEEKLY: "周",
        MONTHLY: "月",
        QUARTERLY: "季度",
        YEARLY: "年度"
    }
    
    @classmethod
    def get_display_name(cls, type_name: str) -> str:
        return cls.TYPE_NAMES.get(type_name, type_name)


class InsertionPositions:
    """插入位置常量"""
    SYSTEM_APPEND = "system_append"
    AFTER_SYSTEM = "after_system"
    SYSTEM_PREPEND = "system_prepend"
    USER_PREFIX = "user_prefix"


class FileExtensions:
    """文件扩展名常量"""
    MARKDOWN = ".md"
    JSONL = ".jsonl"
    JSON = ".json"


class DateFormats:
    """日期格式常量"""
    ISO_DATE = "%Y-%m-%d"
    ISO_DATETIME = "%Y-%m-%d %H:%M:%S"
    ISO_WEEK = "%Y-W%W"
    ISO_MONTH = "%Y-%m"
    ISO_QUARTER = "%Y-Q%q"


class Defaults:
    """默认值常量"""
    ENCODING = "utf-8"
    MAX_CONTEXT_TOKENS = 80000
    SHORT_TERM_DAYS = 7
    MAX_ITERATIONS = 100
    TIMEOUT = 60


class ErrorMessages:
    """错误消息常量"""
    WRITE_DISABLED = "错误：写入功能未启用"
    NODE_NOT_FOUND = "未找到节点 [[{}]]"
    DIARY_NOT_FOUND = "未找到 {} 的日记"
    SUMMARY_NOT_FOUND = "未找到 {} 总结 {}"
    TOOL_NOT_FOUND = "错误：未知工具 '{}'"
    TOOL_EXECUTION_FAILED = "错误：工具执行失败 - {}"
    JSON_PARSE_FAILED = "JSON 解析失败: {}"


class LogMessages:
    """日志消息模板常量"""
    TOOL_CALL = "[工具调用] {} - {}"
    TOOL_RESULT = "[工具结果] {} - {}"
    MEMORY_RETRIEVAL_START = "[记忆检索] 开始检索相关记忆..."
    MEMORY_RETRIEVAL_COMPLETE = "[记忆检索] 完成，找到 {} 次工具调用"
    ROUTE_MATCHED = "[路由] 模型 {} 匹配到 {} 模式"
    STREAM_STARTED = "[流式请求] Chat ID: {}, 模型: {}, 消息数: {}"
    STREAM_FINISHED = "[请求结束] 原因: {}, 总消耗: {}"
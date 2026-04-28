"""
LifeBook Memory Store - 记忆存储层

提供对LifeBook日记、总结、节点的读写操作

核心模块:
- LifeBookReader/Writer: 日记、总结、节点的读写
- SqliteIndexer: SQLite 版关键词索引
- MetadataManager: 元数据管理

Phase 2 新增（原始对话保留）:
- ConversationMatcher: 会话匹配器
- ConversationLogger: 对话记录器
- DiaryGenerator: 日记生成器

Phase 3 新增（借鉴 LingYi 改进）:
- AnnotationParser: 快捷标注语法解析器
- ConfidenceManager: 置信度累积机制
- MemoryDecayManager: 记忆衰减（遗忘机制）
- HierarchicalTimeIndex: 层级时间索引

已废弃:
- MemoryIndexer: JSON 版关键词索引（已废弃，仅保留兼容性）
"""

import warnings
from .reader import LifeBookReader
from .writer import LifeBookWriter
from .sqlite_indexer import SqliteIndexer
from .metadata import MetadataManager

# Phase 2: 原始对话保留机制
from .conversation_matcher import (
    ConversationMatcher,
    MatchConfig,
    MatchResult,
)
from .conversation_logger import (
    ConversationLogger,
    LoggerConfig,
    TurnRecord,
    ConversationData,
)
from .diary_generator import (
    DiaryGenerator,
    DiaryGeneratorConfig,
    DiaryGenerationResult,
)

# Phase 3: 借鉴 LingYi 改进
from .annotation_parser import (
    AnnotationParser,
    ParsedAnnotation,
    ParsedTime,
    ParsedEntity,
    EntityType,
    ChineseTimeParser,
    parse_annotation,
    has_annotations,
    to_quintuple,
)
from .confidence_manager import (
    ConfidenceManager,
    ConfidenceInfo,
    ConfidenceLevel,
    SourceType,
    EvidenceRecord,
    EdgeConfidence,
    create_confidence,
    accumulate_confidence,
)
from .memory_decay import (
    MemoryDecayManager,
    MemoryState,
    MemoryStatus,
    DecayConfig,
    DecayResult,
    DecayScheduler,
    calculate_significance,
    reinforce_memory,
)
from .hierarchical_time import (
    HierarchicalTimeIndex,
    TimeInfo,
    TimeType,
    RecurrencePattern,
    ChineseTimeExtractor,
    TimeIndexSynchronizer,
    index_edge_time,
    query_by_date,
)

# Phase 3: 五元组写入
from .quintuple_writer import (
    QuintupleWriter,
    Quintuple,
    WriteResult,
    WriteMode,
    write_quintuple,
    write_from_annotation,
)


def _get_deprecated_indexer():
    """延迟导入并发出废弃警告"""
    warnings.warn(
        "MemoryIndexer 已废弃，请使用 SqliteIndexer 替代。"
        "SqliteIndexer 提供更好的性能和更可靠的并发支持。",
        DeprecationWarning,
        stacklevel=3
    )
    from .indexer import MemoryIndexer
    return MemoryIndexer


# 为兼容性保留，但使用时会发出警告
class _DeprecatedMemoryIndexer:
    """MemoryIndexer 的包装器，使用时发出废弃警告"""
    _real_class = None
    
    def __new__(cls, *args, **kwargs):
        if cls._real_class is None:
            cls._real_class = _get_deprecated_indexer()
        return cls._real_class(*args, **kwargs)


# 导出时使用包装器
MemoryIndexer = _DeprecatedMemoryIndexer

__all__ = [
    # 核心读写
    'LifeBookReader',
    'LifeBookWriter',
    'SqliteIndexer',
    'MetadataManager',
    
    # Phase 2: 原始对话保留
    'ConversationMatcher',
    'MatchConfig',
    'MatchResult',
    'ConversationLogger',
    'LoggerConfig',
    'TurnRecord',
    'ConversationData',
    'DiaryGenerator',
    'DiaryGeneratorConfig',
    'DiaryGenerationResult',
    
    # Phase 3: 标注解析器
    'AnnotationParser',
    'ParsedAnnotation',
    'ParsedTime',
    'ParsedEntity',
    'EntityType',
    'ChineseTimeParser',
    'parse_annotation',
    'has_annotations',
    'to_quintuple',
    
    # Phase 3: 置信度管理
    'ConfidenceManager',
    'ConfidenceInfo',
    'ConfidenceLevel',
    'SourceType',
    'EvidenceRecord',
    'EdgeConfidence',
    'create_confidence',
    'accumulate_confidence',
    
    # Phase 3: 记忆衰减
    'MemoryDecayManager',
    'MemoryState',
    'MemoryStatus',
    'DecayConfig',
    'DecayResult',
    'DecayScheduler',
    'calculate_significance',
    'reinforce_memory',
    
    # Phase 3: 时间索引
    'HierarchicalTimeIndex',
    'TimeInfo',
    'TimeType',
    'RecurrencePattern',
    'ChineseTimeExtractor',
    'TimeIndexSynchronizer',
    'index_edge_time',
    'query_by_date',
    
    # Phase 3: 五元组写入
    'QuintupleWriter',
    'Quintuple',
    'WriteResult',
    'WriteMode',
    'write_quintuple',
    'write_from_annotation',
    
    # 已废弃
    'MemoryIndexer',
]
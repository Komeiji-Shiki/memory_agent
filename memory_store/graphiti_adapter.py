"""
Graphiti 时序知识图谱适配器

桥接 LifeBook 与 Graphiti 框架，提供：
- 嵌入式 Kuzu 图数据库支持
- OpenAI 兼容 API 支持（自定义 base_url）
- Episode 类型区分（日记/节点/对话）
- 混合搜索（语义 + BM25）
- Bi-Temporal 时序查询
- Group ID 数据隔离

使用示例：
    async with GraphitiAdapter.from_config(config, lifebook_path) as adapter:
        await adapter.add_episode(content, source, EpisodeType.DIARY)
        results = await adapter.search("主人最近做了什么")
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Tuple,
    TypeVar,
    Union,
)

logger = logging.getLogger(__name__)

# ============================================================
# 类型定义
# ============================================================

T = TypeVar('T')


class EpisodeType(Enum):
    """LifeBook Episode 类型枚举"""
    DIARY = "diary"           # 日记：高信息密度，总是索引
    NODE = "node"             # 节点：结构化实体描述
    CONVERSATION = "conv"     # 对话：需要价值评估过滤
    
    def to_graphiti_type(self) -> str:
        """转换为 Graphiti 的 EpisodeType"""
        # Graphiti 使用 message/text（Markdown 节点内容应该用 text 而不是 json）
        mapping = {
            EpisodeType.DIARY: "text",
            EpisodeType.NODE: "text",  # 节点内容是 Markdown 格式，用 text
            EpisodeType.CONVERSATION: "message",
        }
        return mapping.get(self, "text")


@dataclass
class SearchResult:
    """统一的搜索结果"""
    uuid: str
    content: str
    score: float
    source: str
    result_type: str  # "edge" | "node" | "episode"
    valid_at: Optional[datetime] = None
    invalid_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass  
class TemporalQueryResult:
    """时间点查询结果"""
    entity: str
    time_point: datetime
    facts: List[Dict[str, Any]]
    facts_count: int


# ============================================================
# 配置数据类
# ============================================================

@dataclass
class LLMConfig:
    """LLM 配置"""
    base_url: Optional[str] = None
    api_key: str = ""
    model: str = "gpt-4o-mini"
    small_model: str = "gpt-4o-mini"
    temperature: float = 1.0
    max_tokens: int = 16384
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'LLMConfig':
        return cls(
            base_url=d.get("base_url"),
            api_key=cls._resolve_env_var(d.get("api_key", "")),
            model=d.get("model", "gpt-4o-mini"),
            small_model=d.get("small_model", "gpt-4o-mini"),
            temperature=d.get("temperature", 1.0),
            max_tokens=d.get("max_tokens", 16384),
        )
    
    @staticmethod
    def _resolve_env_var(value: str) -> str:
        """解析环境变量引用 ${VAR_NAME}"""
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.environ.get(env_var, "")
        return value


@dataclass
class EmbeddingConfig:
    """Embedding 配置"""
    base_url: Optional[str] = None
    api_key: str = ""
    model: str = "text-embedding-3-small"
    dim: int = 1536
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'EmbeddingConfig':
        return cls(
            base_url=d.get("base_url"),
            api_key=LLMConfig._resolve_env_var(d.get("api_key", "")),
            model=d.get("model", "text-embedding-3-small"),
            dim=d.get("dim", 1536),
        )


@dataclass
class SearchConfig:
    """搜索配置"""
    edge_methods: List[str] = field(default_factory=lambda: ["cosine_similarity", "bm25"])
    node_methods: List[str] = field(default_factory=lambda: ["cosine_similarity", "bm25"])
    sim_min_score: float = 0.4
    mmr_lambda: float = 0.5
    reranker_min_score: float = 0.3
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'SearchConfig':
        return cls(
            edge_methods=d.get("edge_methods", ["cosine_similarity", "bm25"]),
            node_methods=d.get("node_methods", ["cosine_similarity", "bm25"]),
            sim_min_score=d.get("sim_min_score", 0.4),
            mmr_lambda=d.get("mmr_lambda", 0.5),
            reranker_min_score=d.get("reranker_min_score", 0.3),
        )


@dataclass
class GroupIdStrategy:
    """Group ID 策略"""
    strategy: str = "single"  # single | user | project
    default: str = "lifebook"
    user_template: str = "user_{user_id}"
    project_template: str = "project_{project_id}"
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'GroupIdStrategy':
        return cls(
            strategy=d.get("strategy", "single"),
            default=d.get("default", "lifebook"),
            user_template=d.get("user_template", "user_{user_id}"),
            project_template=d.get("project_template", "project_{project_id}"),
        )
    
    def get_group_id(
        self,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> str:
        """根据策略获取 group_id"""
        if self.strategy == "user" and user_id:
            return self.user_template.format(user_id=user_id)
        elif self.strategy == "project" and project_id:
            return self.project_template.format(project_id=project_id)
        return self.default


@dataclass
class EpisodeTypeConfig:
    """Episode 类型配置"""
    priority: str = "medium"
    extract_entities: bool = True
    min_value_threshold: float = 0.3
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'EpisodeTypeConfig':
        return cls(
            priority=d.get("priority", "medium"),
            extract_entities=d.get("extract_entities", True),
            min_value_threshold=d.get("min_value_threshold", 0.3),
        )


@dataclass
class RetrievalConfig:
    """检索配置"""
    strategy: str = "simple"  # simple | iterative
    max_iterations: int = 3
    default_limit: int = 10
    include_edges: bool = True
    include_nodes: bool = True
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'RetrievalConfig':
        return cls(
            strategy=d.get("strategy", "simple"),
            max_iterations=d.get("max_iterations", 3),
            default_limit=d.get("default_limit", 10),
            include_edges=d.get("include_edges", True),
            include_nodes=d.get("include_nodes", True),
        )


@dataclass
class GraphitiConfig:
    """Graphiti 完整配置"""
    enabled: bool = False
    backend: str = "kuzu"
    kuzu_db_path: str = "./lifebook/.graphiti.kuzu"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "lifebook"
    
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    group_id: GroupIdStrategy = field(default_factory=GroupIdStrategy)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    episode_types: Dict[str, EpisodeTypeConfig] = field(default_factory=dict)
    
    reranker_enabled: bool = False
    reranker_model: str = "gpt-4o-mini"
    
    max_concurrent_queries: int = 1
    semaphore_limit: int = 10
    index_conversations: bool = True
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any], lifebook_path: str = "./lifebook") -> 'GraphitiConfig':
        """从配置字典创建"""
        graphiti_cfg = config.get("graphiti", {})
        
        # Kuzu 路径处理
        kuzu_path = graphiti_cfg.get("kuzu", {}).get("db_path", "./.graphiti.kuzu")
        if not os.path.isabs(kuzu_path):
            kuzu_path = os.path.join(lifebook_path, os.path.basename(kuzu_path))
        
        # 解析 episode types
        episode_types = {}
        for ep_type, ep_cfg in graphiti_cfg.get("episode_types", {}).items():
            episode_types[ep_type] = EpisodeTypeConfig.from_dict(ep_cfg)
        
        neo4j_cfg = graphiti_cfg.get("neo4j", {})
        reranker_cfg = graphiti_cfg.get("reranker", {})
        perf_cfg = graphiti_cfg.get("performance", {})
        sync_cfg = graphiti_cfg.get("sync", {})
        
        return cls(
            enabled=graphiti_cfg.get("enabled", False),
            backend=graphiti_cfg.get("backend", "kuzu"),
            kuzu_db_path=kuzu_path,
            neo4j_uri=neo4j_cfg.get("uri", "bolt://localhost:7687"),
            neo4j_username=neo4j_cfg.get("username", "neo4j"),
            neo4j_password=neo4j_cfg.get("password", ""),
            neo4j_database=neo4j_cfg.get("database", "lifebook"),
            llm=LLMConfig.from_dict(graphiti_cfg.get("llm", {})),
            embedding=EmbeddingConfig.from_dict(graphiti_cfg.get("embedding", {})),
            search=SearchConfig.from_dict(graphiti_cfg.get("search", {})),
            group_id=GroupIdStrategy.from_dict(graphiti_cfg.get("group_id", {})),
            retrieval=RetrievalConfig.from_dict(graphiti_cfg.get("retrieval", {})),
            episode_types=episode_types,
            reranker_enabled=reranker_cfg.get("enabled", False),
            reranker_model=reranker_cfg.get("model", "gpt-4o-mini"),
            max_concurrent_queries=perf_cfg.get("max_concurrent_queries", 1),
            semaphore_limit=perf_cfg.get("semaphore_limit", 10),
            index_conversations=sync_cfg.get("index_conversations", True),
        )


# ============================================================
# 内容价值评估器
# ============================================================

class ContentValueEstimator:
    """
    内容价值评估器
    
    用于判断对话内容是否值得索引到知识图谱。
    使用启发式规则，避免 LLM 调用开销。
    """
    
    # 实体关键词（中文）
    ENTITY_KEYWORDS = [
        "项目", "技术", "学习", "开发", "计划", "目标", "完成", "问题",
        "工作", "会议", "设计", "架构", "功能", "模块", "系统", "服务",
        "数据", "算法", "模型", "训练", "部署", "测试", "上线", "发布",
    ]
    
    # 闲聊模式
    CASUAL_PATTERNS = [
        r"^(哈哈|嗯嗯|好的|知道了|谢谢|ok|OK|好|嗯|哦|噢|啊|呃)[\s!！。.]*$",
        r"^.{0,10}(早|晚安|你好|再见)[\s!！。.]*$",
    ]
    
    def __init__(self, min_threshold: float = 0.3):
        self.min_threshold = min_threshold
        self._casual_patterns = [re.compile(p) for p in self.CASUAL_PATTERNS]
    
    def estimate(self, content: str) -> float:
        """
        估算内容价值（0-1）
        
        启发式规则：
        - 长度加分
        - 实体词加分
        - 纯闲聊减分
        """
        if not content:
            return 0.0
        
        score = 0.5
        
        # 长度因素
        length = len(content)
        if length > 200:
            score += 0.2
        elif length < 50:
            score -= 0.2
        
        # 实体词检测
        content_lower = content.lower()
        entity_count = sum(1 for kw in self.ENTITY_KEYWORDS if kw in content_lower)
        score += min(entity_count * 0.1, 0.3)
        
        # 闲聊检测
        if any(p.match(content.strip()) for p in self._casual_patterns):
            score -= 0.4
        
        return max(0.0, min(1.0, score))
    
    def should_index(self, content: str, episode_type: EpisodeType) -> bool:
        """判断是否应该索引"""
        # 日记和节点总是索引
        if episode_type in (EpisodeType.DIARY, EpisodeType.NODE):
            return True
        
        # 对话需要评估价值
        return self.estimate(content) >= self.min_threshold


# ============================================================
# Graphiti 适配器
# ============================================================

class GraphitiAdapter:
    """
    Graphiti 适配器 - 桥接 LifeBook 与 Graphiti
    
    特性：
    - 支持 Kuzu（嵌入式）和 Neo4j（生产）后端
    - 支持 OpenAI 兼容 API（自定义 base_url）
    - Episode 类型区分和价值评估
    - 混合搜索（语义 + BM25）
    - Bi-Temporal 时序查询
    - Group ID 数据隔离
    - 异步优先设计
    
    使用方式：
        # 推荐：使用异步上下文管理器
        async with GraphitiAdapter.from_config(config, lifebook_path) as adapter:
            await adapter.add_episode(...)
            
        # 或手动管理生命周期
        adapter = GraphitiAdapter(config, lifebook_path)
        await adapter.initialize()
        try:
            ...
        finally:
            await adapter.close()
    """
    
    def __init__(self, config: GraphitiConfig, lifebook_path: str):
        """
        初始化适配器
        
        Args:
            config: Graphiti 配置
            lifebook_path: LifeBook 根目录路径
        """
        self.config = config
        self.lifebook_path = Path(lifebook_path)
        
        # Graphiti 核心实例（延迟初始化）
        self._graphiti = None
        self._driver = None
        self._llm_client = None
        self._embedder = None
        self._reranker = None
        
        # 状态
        self._initialized = False
        
        # 工具类
        self._value_estimator = ContentValueEstimator(
            min_threshold=config.episode_types.get(
                "conversation", EpisodeTypeConfig()
            ).min_value_threshold
        )
    
    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        lifebook_path: str
    ) -> 'GraphitiAdapter':
        """从配置字典创建适配器"""
        graphiti_config = GraphitiConfig.from_dict(config, lifebook_path)
        return cls(graphiti_config, lifebook_path)
    
    @classmethod
    @asynccontextmanager
    async def create(
        cls,
        config: Dict[str, Any],
        lifebook_path: str
    ) -> AsyncIterator['GraphitiAdapter']:
        """异步上下文管理器工厂方法"""
        adapter = cls.from_config(config, lifebook_path)
        try:
            await adapter.initialize()
            yield adapter
        finally:
            await adapter.close()
    
    async def __aenter__(self) -> 'GraphitiAdapter':
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    @property
    def is_enabled(self) -> bool:
        """检查 Graphiti 是否启用"""
        return self.config.enabled
    
    @property
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized
    
    async def initialize(self) -> None:
        """
        异步初始化 Graphiti
        
        创建：
        1. 图数据库驱动（Kuzu 或 Neo4j）
        2. LLM 客户端
        3. Embedding 客户端
        4. Reranker（可选）
        5. Graphiti 核心实例
        """
        if self._initialized:
            return
        
        if not self.config.enabled:
            logger.info("[Graphiti] Graphiti 未启用，跳过初始化")
            return
        
        try:
            # 动态导入 Graphiti（允许未安装时优雅降级）
            from graphiti_core import Graphiti
            from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
            from graphiti_core.llm_client.config import LLMConfig as GraphitiLLMConfig
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
            
            # 1. 创建图数据库驱动
            self._driver = await self._create_driver()
            
            # 2. 创建 LLM 客户端
            llm_config = GraphitiLLMConfig(
                api_key=self.config.llm.api_key,
                model=self.config.llm.model,
                base_url=self.config.llm.base_url,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
                small_model=self.config.llm.small_model,
            )
            self._llm_client = OpenAIGenericClient(
                config=llm_config,
                max_tokens=self.config.llm.max_tokens,
            )
            
            # 3. 创建 Embedder
            # 获取 embedding api_key，优先使用 embedding 配置，否则回退到 llm 配置
            embedding_api_key = self.config.embedding.api_key or self.config.llm.api_key
            embedding_base_url = self.config.embedding.base_url or self.config.llm.base_url
            
            logger.debug(
                f"[Graphiti] Embedder 配置: "
                f"api_key={'*' * 8 + embedding_api_key[-4:] if embedding_api_key else 'None'}, "
                f"base_url={embedding_base_url}, "
                f"model={self.config.embedding.model}"
            )
            
            if not embedding_api_key:
                raise ValueError(
                    "[Graphiti] Embedding API key 未配置！"
                    "请在 config.jsonc 中设置 graphiti.embedding.api_key 或 graphiti.llm.api_key"
                )
            
            embedder_config = OpenAIEmbedderConfig(
                api_key=embedding_api_key,
                embedding_model=self.config.embedding.model,
                embedding_dim=self.config.embedding.dim,
                base_url=embedding_base_url,
            )
            self._embedder = OpenAIEmbedder(config=embedder_config)
            
            # 4. 创建 Reranker
            # 注意：即使禁用 reranker，也必须创建实例，否则 Graphiti 会自动创建默认的（会报 API key 错误）
            from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
            reranker_llm_config = GraphitiLLMConfig(
                api_key=self.config.llm.api_key,
                model=self.config.reranker_model or self.config.llm.model,
                base_url=self.config.llm.base_url,
            )
            self._reranker = OpenAIRerankerClient(config=reranker_llm_config)
            if self.config.reranker_enabled:
                logger.info(f"[Graphiti] Reranker 已启用: {self.config.reranker_model}")
            else:
                logger.debug("[Graphiti] Reranker 已创建（配置中禁用，但需要提供给 Graphiti）")
            
            # 5. 创建 Graphiti 实例
            self._graphiti = Graphiti(
                graph_driver=self._driver,
                llm_client=self._llm_client,
                embedder=self._embedder,
                cross_encoder=self._reranker,
            )
            
            # 6. 初始化索引和约束
            await self._graphiti.build_indices_and_constraints()
            
            self._initialized = True
            logger.info(
                f"[Graphiti] 初始化完成 "
                f"(backend={self.config.backend}, "
                f"model={self.config.llm.model})"
            )
            
        except ImportError as e:
            logger.warning(f"[Graphiti] Graphiti 未安装，功能不可用: {e}")
            raise RuntimeError(
                "Graphiti 未安装。请运行: pip install graphiti-core[kuzu]"
            ) from e
        except Exception as e:
            logger.error(f"[Graphiti] 初始化失败: {e}")
            raise
    
    async def _create_driver(self):
        """创建图数据库驱动"""
        if self.config.backend == "kuzu":
            from graphiti_core.driver.kuzu_driver import KuzuDriver
            
            # 只确保父目录存在，让 Kuzu 自己创建数据库目录
            db_path = Path(self.config.kuzu_db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"[Graphiti] Kuzu 数据库路径: {db_path}")
            
            driver = KuzuDriver(
                db=str(db_path),
                max_concurrent_queries=self.config.max_concurrent_queries,
            )
            logger.info(f"[Graphiti] Kuzu 驱动已创建: {db_path}")
            return driver
            
        elif self.config.backend == "neo4j":
            from graphiti_core.driver.neo4j_driver import Neo4jDriver
            
            driver = Neo4jDriver(
                uri=self.config.neo4j_uri,
                user=self.config.neo4j_username,
                password=self.config.neo4j_password,
                database=self.config.neo4j_database,
            )
            logger.info(f"[Graphiti] Neo4j 驱动已创建: {self.config.neo4j_uri}")
            return driver
        
        else:
            raise ValueError(f"不支持的后端: {self.config.backend}")
    
    async def close(self) -> None:
        """关闭连接"""
        if self._graphiti:
            await self._graphiti.close()
            self._graphiti = None
            self._driver = None
            self._initialized = False
            logger.info("[Graphiti] 连接已关闭")
    
    # ============================================================
    # Episode 管理
    # ============================================================
    
    async def add_episode(
        self,
        content: str,
        source: str,
        episode_type: EpisodeType = EpisodeType.CONVERSATION,
        timestamp: Optional[datetime] = None,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        将内容添加为 Graphiti Episode
        
        Args:
            content: 内容文本
            source: 来源标识 (如 "diary:2025-01-21", "conv:session_123:5")
            episode_type: Episode 类型
            timestamp: 事件发生时间（默认当前时间）
            user_id: 用户ID（用于 group_id 策略）
            project_id: 项目ID（用于 group_id 策略）
            metadata: 额外元数据
        
        Returns:
            Episode UUID，如果被过滤则返回 None
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._graphiti:
            logger.warning("[Graphiti] Graphiti 未初始化，跳过添加 Episode")
            return None
        
        # 价值评估（对话类型需要过滤）
        if not self._value_estimator.should_index(content, episode_type):
            logger.debug(
                f"[Graphiti] 跳过低价值内容 "
                f"(type={episode_type.value}, length={len(content)})"
            )
            return None
        
        # 获取 group_id
        group_id = self.config.group_id.get_group_id(user_id, project_id)
        
        # 时间戳
        reference_time = timestamp or datetime.now()
        
        # 获取 Graphiti 的 EpisodeType
        from graphiti_core.nodes import EpisodeType as GraphitiEpisodeType
        
        # 注意：节点内容是 Markdown 格式，应该用 text 而不是 json
        graphiti_source = {
            EpisodeType.DIARY: GraphitiEpisodeType.text,
            EpisodeType.NODE: GraphitiEpisodeType.text,  # Markdown 节点用 text
            EpisodeType.CONVERSATION: GraphitiEpisodeType.message,
        }.get(episode_type, GraphitiEpisodeType.text)
        
        try:
            result = await self._graphiti.add_episode(
                name=source,
                episode_body=content,
                source_description=f"LifeBook {episode_type.value}: {source}",
                reference_time=reference_time,
                source=graphiti_source,
                group_id=group_id,
            )
            
            episode_uuid = result.episode.uuid
            logger.debug(
                f"[Graphiti] Episode 已添加: {source} "
                f"(uuid={episode_uuid[:8]}..., "
                f"nodes={len(result.nodes)}, "
                f"edges={len(result.edges)})"
            )
            return episode_uuid
            
        except Exception as e:
            logger.error(f"[Graphiti] 添加 Episode 失败: {e}")
            raise
    
    async def add_diary(
        self,
        date: str,
        content: str,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        添加日记 Episode（便捷方法）
        
        Args:
            date: 日期字符串 YYYY-MM-DD
            content: 日记内容
            user_id: 用户ID
        """
        try:
            timestamp = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            timestamp = datetime.now()
        
        return await self.add_episode(
            content=content,
            source=f"diary:{date}",
            episode_type=EpisodeType.DIARY,
            timestamp=timestamp,
            user_id=user_id,
        )
    
    async def add_node_content(
        self,
        node_name: str,
        content: str,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        添加节点内容 Episode（便捷方法）
        
        Args:
            node_name: 节点名称
            content: 节点内容
            user_id: 用户ID
        """
        return await self.add_episode(
            content=content,
            source=f"node:{node_name}",
            episode_type=EpisodeType.NODE,
            user_id=user_id,
        )
    
    async def add_conversation(
        self,
        session_id: str,
        turn_id: int,
        user_message: str,
        assistant_message: str,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        添加对话 Episode（便捷方法）
        
        Args:
            session_id: 会话ID
            turn_id: 轮次ID
            user_message: 用户消息
            assistant_message: AI回复
            user_id: 用户ID
        """
        content = f"用户: {user_message}\n灰魂: {assistant_message}"
        
        return await self.add_episode(
            content=content,
            source=f"conv:{session_id}:{turn_id}",
            episode_type=EpisodeType.CONVERSATION,
            user_id=user_id,
        )
    
    # ============================================================
    # 搜索
    # ============================================================
    
    async def search(
        self,
        query: str,
        num_results: int = 10,
        group_ids: Optional[List[str]] = None,
        include_edges: Optional[bool] = None,
        include_nodes: Optional[bool] = None,
    ) -> List[SearchResult]:
        """
        混合搜索（语义 + BM25）
        
        使用 search_() 方法获取完整的搜索结果，包含正确的评分信息。
        
        Args:
            query: 查询文本
            num_results: 返回结果数量
            group_ids: 限定搜索的分组
            include_edges: 是否包含边（关系），None 使用配置默认值
            include_nodes: 是否包含节点，None 使用配置默认值
        
        Returns:
            搜索结果列表（带正确评分）
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._graphiti:
            return []
        
        # 使用配置默认值
        if include_edges is None:
            include_edges = self.config.retrieval.include_edges
        if include_nodes is None:
            include_nodes = self.config.retrieval.include_nodes
        
        # 默认 group_ids
        if group_ids is None:
            group_ids = [self.config.group_id.default]
        
        try:
            # 使用 search_() 方法获取完整结果（包含评分）
            from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF
            from graphiti_core.search.search_config import (
                SearchConfig,
                EdgeSearchConfig,
                NodeSearchConfig,
                EdgeSearchMethod,
                NodeSearchMethod,
                EdgeReranker,
                NodeReranker,
            )
            
            # 根据配置构建搜索配置
            edge_config = EdgeSearchConfig(
                search_methods=[EdgeSearchMethod.cosine_similarity, EdgeSearchMethod.bm25],
                reranker=EdgeReranker.rrf,
                sim_min_score=self.config.search.sim_min_score,
                mmr_lambda=self.config.search.mmr_lambda,
            ) if include_edges else None
            
            node_config = NodeSearchConfig(
                search_methods=[NodeSearchMethod.cosine_similarity, NodeSearchMethod.bm25],
                reranker=NodeReranker.rrf,
                sim_min_score=self.config.search.sim_min_score,
                mmr_lambda=self.config.search.mmr_lambda,
            ) if include_nodes else None
            
            config = SearchConfig(
                edge_config=edge_config,
                node_config=node_config,
                limit=num_results,
                reranker_min_score=self.config.search.reranker_min_score,
            )
            
            # 使用 search_() 获取完整结果
            search_results = await self._graphiti.search_(
                query=query,
                config=config,
                group_ids=group_ids,
            )
            
            # 转换为统一格式（正确使用 reranker_scores）
            results = []
            
            # 处理边（关系）
            for i, edge in enumerate(search_results.edges):
                score = search_results.edge_reranker_scores[i] if i < len(search_results.edge_reranker_scores) else 1.0
                result = SearchResult(
                    uuid=edge.uuid,
                    content=edge.fact if hasattr(edge, 'fact') else str(edge),
                    score=score,
                    source=getattr(edge, 'source_description', ''),
                    result_type="edge",
                    valid_at=getattr(edge, 'valid_at', None),
                    invalid_at=getattr(edge, 'invalid_at', None),
                    metadata={
                        "relation_type": getattr(edge, 'name', ''),
                        "source_node": getattr(edge, 'source_node_uuid', ''),
                        "target_node": getattr(edge, 'target_node_uuid', ''),
                    }
                )
                results.append(result)
            
            # 处理节点
            for i, node in enumerate(search_results.nodes):
                score = search_results.node_reranker_scores[i] if i < len(search_results.node_reranker_scores) else 1.0
                result = SearchResult(
                    uuid=node.uuid,
                    content=node.summary or node.name,
                    score=score,
                    source="entity",
                    result_type="node",
                    valid_at=getattr(node, 'created_at', None),
                    invalid_at=None,
                    metadata={
                        "name": node.name,
                        "labels": getattr(node, 'labels', []),
                        "group_id": getattr(node, 'group_id', ''),
                    }
                )
                results.append(result)
            
            # 按评分排序
            results.sort(key=lambda r: r.score, reverse=True)
            
            logger.debug(f"[Graphiti] 搜索完成: query='{query[:30]}...', edges={len(search_results.edges)}, nodes={len(search_results.nodes)}")
            return results[:num_results]
            
        except Exception as e:
            logger.error(f"[Graphiti] 搜索失败: {e}")
            return []
    
    async def search_advanced(
        self,
        query: str,
        num_results: int = 10,
        group_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        高级搜索（返回完整的 SearchResults）
        
        使用 search_ 方法，返回包含 edges, nodes, episodes, communities 的完整结果
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._graphiti:
            return {"edges": [], "nodes": [], "episodes": [], "communities": []}
        
        if group_ids is None:
            group_ids = [self.config.group_id.default]
        
        try:
            from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_CROSS_ENCODER
            
            config = COMBINED_HYBRID_SEARCH_CROSS_ENCODER
            config.limit = num_results
            
            results = await self._graphiti.search_(
                query=query,
                config=config,
                group_ids=group_ids,
            )
            
            return {
                "edges": [self._edge_to_dict(e) for e in results.edges],
                "nodes": [self._node_to_dict(n) for n in results.nodes],
                "episodes": [self._episode_to_dict(ep) for ep in results.episodes],
                "communities": [self._community_to_dict(c) for c in results.communities],
                "edge_scores": results.edge_reranker_scores,
                "node_scores": results.node_reranker_scores,
            }
            
        except Exception as e:
            logger.error(f"[Graphiti] 高级搜索失败: {e}")
            return {"edges": [], "nodes": [], "episodes": [], "communities": []}
    
    def _edge_to_dict(self, edge) -> Dict[str, Any]:
        """EntityEdge 转字典"""
        return {
            "uuid": edge.uuid,
            "fact": edge.fact,
            "name": edge.name,
            "source_node_uuid": edge.source_node_uuid,
            "target_node_uuid": edge.target_node_uuid,
            "valid_at": edge.valid_at.isoformat() if edge.valid_at else None,
            "invalid_at": edge.invalid_at.isoformat() if edge.invalid_at else None,
            "group_id": edge.group_id,
        }
    
    def _node_to_dict(self, node) -> Dict[str, Any]:
        """EntityNode 转字典"""
        return {
            "uuid": node.uuid,
            "name": node.name,
            "summary": node.summary,
            "labels": node.labels,
            "group_id": node.group_id,
            "created_at": node.created_at.isoformat() if node.created_at else None,
        }
    
    def _episode_to_dict(self, episode) -> Dict[str, Any]:
        """EpisodicNode 转字典"""
        return {
            "uuid": episode.uuid,
            "name": episode.name,
            "content": episode.content,
            "source": episode.source.value,
            "valid_at": episode.valid_at.isoformat() if episode.valid_at else None,
            "group_id": episode.group_id,
        }
    
    def _community_to_dict(self, community) -> Dict[str, Any]:
        """CommunityNode 转字典"""
        return {
            "uuid": community.uuid,
            "name": community.name,
            "summary": community.summary,
            "group_id": community.group_id,
        }
    
    # ============================================================
    # 时序查询
    # ============================================================
    
    async def temporal_query(
        self,
        entity_name: str,
        time_point: datetime,
        num_results: int = 30,
    ) -> TemporalQueryResult:
        """
        时间点查询：查询某实体在特定时间的状态
        
        利用 Graphiti 的 Bi-Temporal 模型：
        - valid_at: 事实生效时间
        - invalid_at: 事实失效时间
        
        使用 SearchFilters 在数据库层面进行时间过滤，提高效率。
        
        Args:
            entity_name: 实体名称
            time_point: 时间点
            num_results: 最大结果数
        
        Returns:
            时间点查询结果
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._graphiti:
            return TemporalQueryResult(
                entity=entity_name,
                time_point=time_point,
                facts=[],
                facts_count=0,
            )
        
        try:
            from graphiti_core.search.search_filters import SearchFilters
            from graphiti_core.search.search_config import (
                SearchConfig,
                EdgeSearchConfig,
                EdgeSearchMethod,
                EdgeReranker,
            )
            
            # 使用 SearchFilters 在数据库层面过滤（更高效）
            search_filter = SearchFilters(
                valid_at_before=time_point,  # 事实必须在 time_point 之前生效
                # 注意：Graphiti 目前没有 invalid_at 过滤，需要在内存中过滤
            )
            
            config = SearchConfig(
                edge_config=EdgeSearchConfig(
                    search_methods=[EdgeSearchMethod.cosine_similarity, EdgeSearchMethod.bm25],
                    reranker=EdgeReranker.rrf,
                ),
                limit=num_results * 2,  # 多取一些，后面还要过滤 invalid_at
            )
            
            # 搜索实体相关的边
            search_results = await self._graphiti.search_(
                query=entity_name,
                config=config,
                search_filter=search_filter,
            )
            
            # 在内存中过滤 invalid_at（数据库层面暂不支持）
            valid_facts = []
            for i, edge in enumerate(search_results.edges):
                invalid_at = getattr(edge, 'invalid_at', None)
                valid_at = getattr(edge, 'valid_at', None)
                
                # 事实在 time_point 时未失效
                if invalid_at and invalid_at <= time_point:
                    continue
                
                score = search_results.edge_reranker_scores[i] if i < len(search_results.edge_reranker_scores) else 1.0
                
                valid_facts.append({
                    "fact": edge.fact if hasattr(edge, 'fact') else str(edge),
                    "valid_from": valid_at.isoformat() if valid_at else None,
                    "valid_to": invalid_at.isoformat() if invalid_at else None,
                    "relation": getattr(edge, 'name', ''),
                    "score": score,
                })
                
                if len(valid_facts) >= num_results:
                    break
            
            logger.debug(
                f"[Graphiti] 时序查询完成: entity='{entity_name}', "
                f"time={time_point.isoformat()}, facts={len(valid_facts)}"
            )
            
            return TemporalQueryResult(
                entity=entity_name,
                time_point=time_point,
                facts=valid_facts,
                facts_count=len(valid_facts),
            )
            
        except Exception as e:
            logger.error(f"[Graphiti] 时序查询失败: {e}")
            return TemporalQueryResult(
                entity=entity_name,
                time_point=time_point,
                facts=[],
                facts_count=0,
            )
    
    # ============================================================
    # Markdown 同步
    # ============================================================
    
    async def sync_from_markdown(
        self,
        include_diaries: bool = True,
        include_nodes: bool = True,
        days_back: Optional[int] = None,
        use_bulk: bool = True,
    ) -> Dict[str, int]:
        """
        从 Markdown 文件同步到 Graphiti
        
        使用 add_episode_bulk 批量导入，效率提升 10x+
        
        Args:
            include_diaries: 是否同步日记
            include_nodes: 是否同步节点
            days_back: 只同步最近 N 天的日记（None 表示全部）
            use_bulk: 是否使用批量导入（推荐开启）
        
        Returns:
            同步统计 {"diary": N, "node": M}
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._graphiti:
            return {"diary": 0, "node": 0}
        
        synced = {"diary": 0, "node": 0}
        group_id = self.config.group_id.default
        
        # 收集要同步的文件
        diary_episodes = []
        node_episodes = []
        
        # 收集日记
        if include_diaries:
            daily_dir = self.lifebook_path / "daily"
            if daily_dir.exists():
                from datetime import timedelta
                cutoff_date = None
                if days_back:
                    cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
                
                for md_file in sorted(daily_dir.glob("*.md")):
                    date_str = md_file.stem
                    
                    # 日期过滤
                    if cutoff_date and date_str < cutoff_date:
                        continue
                    
                    try:
                        content = md_file.read_text(encoding="utf-8")
                        timestamp = datetime.strptime(date_str, "%Y-%m-%d")
                        
                        diary_episodes.append({
                            "name": f"diary:{date_str}",
                            "content": content,
                            "timestamp": timestamp,
                            "source_description": f"LifeBook diary: {date_str}",
                        })
                        
                    except Exception as e:
                        logger.error(f"[Graphiti] 读取日记失败 {md_file.name}: {e}")
        
        # 收集节点
        if include_nodes:
            nodes_dir = self.lifebook_path / "nodes"
            if nodes_dir.exists():
                for md_file in nodes_dir.glob("*.md"):
                    try:
                        content = md_file.read_text(encoding="utf-8")
                        
                        node_episodes.append({
                            "name": f"node:{md_file.stem}",
                            "content": content,
                            "timestamp": datetime.now(),
                            "source_description": f"LifeBook node: {md_file.stem}",
                        })
                        
                    except Exception as e:
                        logger.error(f"[Graphiti] 读取节点失败 {md_file.name}: {e}")
        
        # 批量导入或逐个导入
        if use_bulk and (diary_episodes or node_episodes):
            try:
                # 使用批量导入
                synced = await self._sync_bulk(diary_episodes, node_episodes, group_id)
            except Exception as e:
                logger.warning(f"[Graphiti] 批量导入失败，降级到逐个导入: {e}")
                synced = await self._sync_individual(diary_episodes, node_episodes)
        else:
            synced = await self._sync_individual(diary_episodes, node_episodes)
        
        logger.info(
            f"[Graphiti] Markdown 同步完成: "
            f"日记={synced['diary']}, 节点={synced['node']}"
        )
        return synced
    
    async def _sync_bulk(
        self,
        diary_episodes: List[Dict],
        node_episodes: List[Dict],
        group_id: str,
    ) -> Dict[str, int]:
        """使用 add_episode_bulk 批量同步"""
        from graphiti_core.utils.bulk_utils import RawEpisode
        from graphiti_core.nodes import EpisodeType as GraphitiEpisodeType
        
        synced = {"diary": 0, "node": 0}
        
        # 准备日记批量数据
        if diary_episodes:
            raw_diary_episodes = [
                RawEpisode(
                    name=ep["name"],
                    content=ep["content"],
                    source_description=ep["source_description"],
                    reference_time=ep["timestamp"],
                    source=GraphitiEpisodeType.text,
                )
                for ep in diary_episodes
            ]
            
            result = await self._graphiti.add_episode_bulk(
                bulk_episodes=raw_diary_episodes,
                group_id=group_id,
            )
            synced["diary"] = len(result.episodes)
            logger.info(f"[Graphiti] 批量导入日记: {synced['diary']} 条")
        
        # 准备节点批量数据
        if node_episodes:
            raw_node_episodes = [
                RawEpisode(
                    name=ep["name"],
                    content=ep["content"],
                    source_description=ep["source_description"],
                    reference_time=ep["timestamp"],
                    source=GraphitiEpisodeType.text,  # 节点也用 text
                )
                for ep in node_episodes
            ]
            
            result = await self._graphiti.add_episode_bulk(
                bulk_episodes=raw_node_episodes,
                group_id=group_id,
            )
            synced["node"] = len(result.episodes)
            logger.info(f"[Graphiti] 批量导入节点: {synced['node']} 条")
        
        return synced
    
    async def _sync_individual(
        self,
        diary_episodes: List[Dict],
        node_episodes: List[Dict],
    ) -> Dict[str, int]:
        """逐个导入（降级方案）"""
        synced = {"diary": 0, "node": 0}
        
        for ep in diary_episodes:
            try:
                await self.add_episode(
                    content=ep["content"],
                    source=ep["name"],
                    episode_type=EpisodeType.DIARY,
                    timestamp=ep["timestamp"],
                )
                synced["diary"] += 1
            except Exception as e:
                logger.error(f"[Graphiti] 同步日记失败 {ep['name']}: {e}")
        
        for ep in node_episodes:
            try:
                await self.add_episode(
                    content=ep["content"],
                    source=ep["name"],
                    episode_type=EpisodeType.NODE,
                )
                synced["node"] += 1
            except Exception as e:
                logger.error(f"[Graphiti] 同步节点失败 {ep['name']}: {e}")
        
        return synced
    
    # ============================================================
    # Community 构建
    # ============================================================
    
    async def build_communities(
        self,
        group_ids: Optional[List[str]] = None,
    ) -> Tuple[List[Any], List[Any]]:
        """
        构建社区层级摘要
        
        使用 Graphiti 的 Community 功能提取高层次知识摘要。
        这是 GraphRAG 的核心特性。
        
        Args:
            group_ids: 限定分组（None 表示全部）
        
        Returns:
            (community_nodes, community_edges) 元组
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._graphiti:
            return [], []
        
        try:
            community_nodes, community_edges = await self._graphiti.build_communities(
                group_ids=group_ids
            )
            
            logger.info(
                f"[Graphiti] 社区构建完成: "
                f"nodes={len(community_nodes)}, edges={len(community_edges)}"
            )
            return community_nodes, community_edges
            
        except Exception as e:
            logger.error(f"[Graphiti] 社区构建失败: {e}")
            return [], []
    
    # ============================================================
    # 图谱可视化数据
    # ============================================================
    
    async def get_graph_data(self, limit: int = 100) -> Dict[str, Any]:
        """
        获取图谱可视化数据
        
        优化：使用单次查询获取完整子图（节点 + 边）
        
        Args:
            limit: 返回的最大节点/边数量
        
        Returns:
            {"nodes": [...], "edges": [...]}
        """
        if not self._initialized or not self._driver:
            return {"nodes": [], "edges": []}
        
        try:
            # 优化：单次查询获取完整子图
            combined_query = f"""
                MATCH (s:Entity)-[:RELATES_TO]->(r:RelatesToNode_)-[:RELATES_TO]->(t:Entity)
                RETURN s.uuid AS source_uuid, s.name AS source_name, s.summary AS source_summary,
                       s.labels AS source_labels, s.group_id AS source_group_id,
                       t.uuid AS target_uuid, t.name AS target_name, t.summary AS target_summary,
                       t.labels AS target_labels, t.group_id AS target_group_id,
                       r.uuid AS edge_uuid, r.name AS edge_name, r.fact AS edge_fact,
                       r.valid_at AS edge_valid_at, r.invalid_at AS edge_invalid_at
                LIMIT {limit}
            """
            results, _, _ = await self._driver.execute_query(combined_query)
            
            # 使用字典去重节点
            node_map = {}
            edges = []
            
            for row in results:
                # 添加源节点
                source_uuid = row.get("source_uuid")
                if source_uuid and source_uuid not in node_map:
                    node_map[source_uuid] = {
                        "uuid": source_uuid,
                        "name": row.get("source_name"),
                        "type": "Entity",
                        "summary": row.get("source_summary", ""),
                        "labels": row.get("source_labels", []),
                    }
                
                # 添加目标节点
                target_uuid = row.get("target_uuid")
                if target_uuid and target_uuid not in node_map:
                    node_map[target_uuid] = {
                        "uuid": target_uuid,
                        "name": row.get("target_name"),
                        "type": "Entity",
                        "summary": row.get("target_summary", ""),
                        "labels": row.get("target_labels", []),
                    }
                
                # 添加边
                edge_uuid = row.get("edge_uuid")
                if edge_uuid:
                    valid_at = row.get("edge_valid_at")
                    invalid_at = row.get("edge_invalid_at")
                    edges.append({
                        "uuid": edge_uuid,
                        "name": row.get("edge_name"),
                        "fact": row.get("edge_fact", ""),
                        "source_uuid": source_uuid,
                        "target_uuid": target_uuid,
                        "valid_at": valid_at.isoformat() if valid_at else None,
                        "invalid_at": invalid_at.isoformat() if invalid_at else None,
                    })
            
            nodes = list(node_map.values())
            
            logger.debug(f"[Graphiti] 获取图谱数据: nodes={len(nodes)}, edges={len(edges)}")
            return {"nodes": nodes, "edges": edges}
            
        except Exception as e:
            logger.error(f"[Graphiti] 获取图谱数据失败: {e}")
            return {"nodes": [], "edges": []}
    
    # ============================================================
    # 统计
    # ============================================================
    
    async def get_stats(self) -> Dict[str, Any]:
        """获取 Graphiti 统计信息"""
        if not self._initialized:
            return {
                "enabled": self.config.enabled,
                "initialized": False,
                "backend": self.config.backend,
            }
        
        return {
            "enabled": self.config.enabled,
            "initialized": True,
            "backend": self.config.backend,
            "db_path": self.config.kuzu_db_path if self.config.backend == "kuzu" else self.config.neo4j_uri,
            "llm_model": self.config.llm.model,
            "embedding_model": self.config.embedding.model,
            "reranker_enabled": self.config.reranker_enabled,
        }


# ============================================================
# 同步包装器
# ============================================================

class GraphitiSyncAdapter:
    """
    同步版本的 Graphiti 适配器
    
    为非异步上下文提供同步调用接口
    """
    
    def __init__(self, config: Dict[str, Any], lifebook_path: str):
        self._async_adapter = GraphitiAdapter.from_config(config, lifebook_path)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """获取或创建事件循环"""
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop
    
    def _run(self, coro):
        """运行协程"""
        return self._get_loop().run_until_complete(coro)
    
    @property
    def is_enabled(self) -> bool:
        return self._async_adapter.is_enabled
    
    @property
    def is_initialized(self) -> bool:
        return self._async_adapter.is_initialized
    
    def initialize(self) -> None:
        self._run(self._async_adapter.initialize())
    
    def close(self) -> None:
        self._run(self._async_adapter.close())
    
    def add_episode(
        self,
        content: str,
        source: str,
        episode_type: EpisodeType = EpisodeType.CONVERSATION,
        timestamp: Optional[datetime] = None,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[str]:
        return self._run(self._async_adapter.add_episode(
            content, source, episode_type, timestamp, user_id, project_id
        ))
    
    def add_diary(self, date: str, content: str, user_id: Optional[str] = None) -> Optional[str]:
        return self._run(self._async_adapter.add_diary(date, content, user_id))
    
    def add_node_content(self, node_name: str, content: str, user_id: Optional[str] = None) -> Optional[str]:
        return self._run(self._async_adapter.add_node_content(node_name, content, user_id))
    
    def add_conversation(
        self,
        session_id: str,
        turn_id: int,
        user_message: str,
        assistant_message: str,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        return self._run(self._async_adapter.add_conversation(
            session_id, turn_id, user_message, assistant_message, user_id
        ))
    
    def search(
        self,
        query: str,
        num_results: int = 10,
        group_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        return self._run(self._async_adapter.search(query, num_results, group_ids))
    
    def temporal_query(
        self,
        entity_name: str,
        time_point: datetime,
        num_results: int = 30,
    ) -> TemporalQueryResult:
        return self._run(self._async_adapter.temporal_query(entity_name, time_point, num_results))
    
    def sync_from_markdown(
        self,
        include_diaries: bool = True,
        include_nodes: bool = True,
        days_back: Optional[int] = None,
    ) -> Dict[str, int]:
        return self._run(self._async_adapter.sync_from_markdown(
            include_diaries, include_nodes, days_back
        ))
    
    def get_stats(self) -> Dict[str, Any]:
        return self._run(self._async_adapter.get_stats())
    
    def get_graph_data(self, limit: int = 100) -> Dict[str, Any]:
        """获取图谱可视化数据"""
        return self._run(self._async_adapter.get_graph_data(limit))
    
    def __enter__(self) -> 'GraphitiSyncAdapter':
        self.initialize()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ============================================================
# 便捷函数
# ============================================================

_global_adapter: Optional[GraphitiAdapter] = None


async def get_graphiti_adapter(
    config: Optional[Dict[str, Any]] = None,
    lifebook_path: Optional[str] = None,
) -> Optional[GraphitiAdapter]:
    """
    获取全局 Graphiti 适配器实例
    
    如果未初始化，会尝试创建新实例
    """
    global _global_adapter
    
    if _global_adapter is not None and _global_adapter.is_initialized:
        return _global_adapter
    
    if config is None or lifebook_path is None:
        return None
    
    _global_adapter = GraphitiAdapter.from_config(config, lifebook_path)
    await _global_adapter.initialize()
    return _global_adapter


async def close_graphiti_adapter() -> None:
    """关闭全局适配器"""
    global _global_adapter
    
    if _global_adapter is not None:
        await _global_adapter.close()
        _global_adapter = None
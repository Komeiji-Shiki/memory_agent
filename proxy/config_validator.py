"""
配置验证模块

使用 Pydantic 验证配置文件的完整性和类型安全。
"""

from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator


class ModelRouteConfig(BaseModel):
    """模型路由配置"""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    actual_model: Optional[str] = None
    thinking_mode: Optional[Any] = None  # bool | "auto"
    enable_thinking: bool = False
    thinking_budget_tokens: Optional[int] = None
    use_xml_tools: bool = False
    use_user_key: bool = False
    
    @field_validator('thinking_budget_tokens')
    @classmethod
    def validate_budget(cls, v):
        if v is not None and not (1 <= v <= 128000):
            raise ValueError('thinking_budget_tokens 必须在 1-128000 之间')
        return v
    
    @field_validator('base_url')
    @classmethod
    def validate_url(cls, v):
        if v and not v.startswith(('http://', 'https://')):
            raise ValueError('base_url 必须以 http:// 或 https:// 开头')
        return v


class MemoryAgentConfig(BaseModel):
    """记忆代理配置"""
    model: str = "deepseek-reasoner"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    max_iterations: int = Field(default=30, ge=1, le=100)
    timeout: int = Field(default=60, ge=10, le=300)
    system_prompt: str = ""
    query_instruction: str = ""


class ContextConfig(BaseModel):
    """上下文配置"""
    insertion_position: str = "system_append"
    simple_mode_insertion_position: Optional[str] = None
    max_context_tokens: int = Field(default=80000, ge=1000, le=200000)
    max_dynamic_memories: int = Field(default=10, ge=1, le=50)
    disable_truncation: bool = True
    recent_days: int = Field(default=7, ge=1, le=30)
    
    # 分层记忆配置
    class LayeredMemory(BaseModel):
        enabled: bool = True
        short_term_days: int = Field(default=7, ge=1, le=30)
        short_term_max_chars: int = Field(default=1000000, ge=1000)
        include_weekly: bool = True
        weekly_max_chars: int = Field(default=1000000, ge=1000)
        include_monthly: bool = True
        monthly_max_chars: int = Field(default=1000000, ge=1000)
        include_quarterly: bool = True
        quarterly_max_chars: int = Field(default=1000000, ge=1000)
        lookback_months: int = Field(default=5, ge=1, le=12)
    
    layered_memory: LayeredMemory = Field(default_factory=LayeredMemory)


class RAGConfig(BaseModel):
    """RAG 配置"""
    enabled: bool = False
    api_key: str = ""
    model: str = "Qwen/Qwen3-Embedding-8B"
    base_url: str = "https://api.siliconflow.cn/v1/embeddings"
    chunk_size: int = Field(default=500, ge=100, le=2000)
    chunk_overlap: int = Field(default=50, ge=0, le=500)
    top_k: int = Field(default=5, ge=1, le=20)
    similarity_threshold: float = Field(default=0.4, ge=0.0, le=1.0)


class GraphitiConfig(BaseModel):
    """Graphiti 配置"""
    enabled: bool = False
    backend: str = "kuzu"  # kuzu | neo4j
    
    class KuzuConfig(BaseModel):
        db_path: str = "./lifebook/.graphiti.kuzu"
    
    class Neo4jConfig(BaseModel):
        uri: str = "bolt://localhost:7687"
        username: str = "neo4j"
        password: str = ""
        database: str = "lifebook"
    
    class LLMConfig(BaseModel):
        base_url: str = "https://api.deepseek.com/v1"
        api_key: str = ""
        model: str = "deepseek-reasoner"
        small_model: str = "deepseek-chat"
        temperature: float = Field(default=1.0, ge=0.0, le=2.0)
        max_tokens: int = Field(default=32768, ge=1000, le=128000)
    
    class EmbeddingConfig(BaseModel):
        base_url: str = "https://api.siliconflow.cn/v1"
        api_key: str = ""
        model: str = "Qwen/Qwen3-Embedding-8B"
        dim: int = Field(default=4096, ge=128, le=8192)
    
    class CacheConfig(BaseModel):
        enabled: bool = True
        ttl_seconds: int = Field(default=300, ge=60, le=3600)
        max_size: int = Field(default=1000, ge=100, le=10000)
        cleanup_interval: int = Field(default=60, ge=10, le=300)
    
    kuzu: KuzuConfig = Field(default_factory=KuzuConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    
    @field_validator('backend')
    @classmethod
    def validate_backend(cls, v):
        if v not in ('kuzu', 'neo4j'):
            raise ValueError('backend 必须是 kuzu 或 neo4j')
        return v


class PostConversationConfig(BaseModel):
    """对话后总结配置"""
    enabled: bool = True
    auto_summarize: bool = True
    summarize_model: str = "deepseek-reasoner"
    cache_ttl: int = Field(default=3600, ge=300, le=86400)
    min_messages: int = Field(default=2, ge=1, le=10)
    pending_preview_max_chars: int = Field(default=1000, ge=100, le=5000)


class ConversationLoggerConfig(BaseModel):
    """对话记录器配置"""
    enabled: bool = True
    session_timeout_minutes: int = Field(default=30, ge=5, le=120)
    prefix_match_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_turns_per_file: int = Field(default=100, ge=10, le=1000)
    max_recent_files_hours: int = Field(default=24, ge=1, le=168)
    index_to_graphiti: bool = True
    async_index: bool = True


class ServerConfig(BaseModel):
    """服务器主配置"""
    # 基础配置
    chat_completions_url: str = "https://api.deepseek.com/beta/v1/chat/completions"
    models_url: str = "https://api.deepseek.com/v1/models"
    api_key: str = ""
    access_keys: List[str] = Field(default_factory=list)
    allow_user_api_key: bool = True
    
    # 服务器设置
    host: str = "0.0.0.0"
    port: int = Field(default=8003, ge=1, le=65535)
    debug: bool = False
    log_level: str = "INFO"
    
    # 功能开关
    mcp_enabled: bool = True
    auto_execute_mcp_tools: bool = True
    memory_enabled: bool = True
    system_prompt_enabled: bool = True
    
    # 迭代和重试
    max_iterations: int = Field(default=100, ge=1, le=1000)
    keep_tool_results_count: int = Field(default=3, ge=0, le=10)
    max_retries: int = Field(default=0, ge=0, le=10)
    
    # 系统提示词
    system_prompt: str = ""
    
    # 子配置
    memory_agent: MemoryAgentConfig = Field(default_factory=MemoryAgentConfig)
    model_routes: Dict[str, ModelRouteConfig] = Field(default_factory=dict)
    context: ContextConfig = Field(default_factory=ContextConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    graphiti: GraphitiConfig = Field(default_factory=GraphitiConfig)
    post_conversation: PostConversationConfig = Field(default_factory=PostConversationConfig)
    conversation_logger: ConversationLoggerConfig = Field(default_factory=ConversationLoggerConfig)
    
    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v):
        v = v.upper()
        if v not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
            raise ValueError('log_level 必须是 DEBUG/INFO/WARNING/ERROR/CRITICAL 之一')
        return v
    
    @field_validator('port')
    @classmethod
    def validate_port(cls, v):
        if not 1 <= v <= 65535:
            raise ValueError('端口必须在 1-65535 之间')
        return v
    
    @model_validator(mode='before')
    @classmethod
    def set_defaults(cls, values):
        """设置默认值和兼容性处理"""
        # 确保 _default 路由存在
        if isinstance(values, dict) and 'model_routes' in values:
            if '_default' not in values['model_routes']:
                values['model_routes']['_default'] = {'use_user_key': True}
        
        return values
    
    class Config:
        # 允许额外字段（兼容旧配置）
        extra = 'allow'


def validate_config(config: Dict[str, Any]) -> ServerConfig:
    """
    验证配置并返回类型化的配置对象
    
    Args:
        config: 原始配置字典
        
    Returns:
        验证后的 ServerConfig
        
    Raises:
        ValidationError: 配置验证失败
    """
    return ServerConfig(**config)


def validate_config_safe(config: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[ServerConfig]]:
    """
    安全地验证配置，不抛出异常
    
    Args:
        config: 原始配置字典
        
    Returns:
        (是否成功, 错误信息, 配置对象) 元组
    """
    try:
        validated = validate_config(config)
        return True, None, validated
    except Exception as e:
        return False, str(e), None
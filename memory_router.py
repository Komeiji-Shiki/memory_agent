"""
Memory Router - 记忆路由器

⚠️ 注意：
当前项目运行时实际导入的是包版 [`memory_router/__init__.py`](memory_router/__init__.py)
并进一步使用 [`memory_router/core.py`](memory_router/core.py) 中的 `MemoryRouter` 实现。
本文件是历史遗留的单文件版本，保留用于参考/对照；修改这里通常**不会**影响当前服务运行行为。

根据模型ID路由请求，支持四种模式：

## 模式说明

### 1. 记忆增强模式 (memory)
- **触发条件**: 模型名以 `-memory` 或 `-memory-simple` 结尾
- **工作流程**:
  1. Memory Agent（小模型）检索相关记忆
  2. 将检索结果注入上下文
  3. 主模型（大模型）生成回复
- **区别**:
  - `-memory`: 主模型可使用记忆工具（能主动查询/写入）
  - `-memory-simple`: 主模型无工具（只读上下文，更稳定）
- **示例**: `claude-3-5-sonnet-memory`, `gpt-4o-memory-simple`

### 2. 记录模式 (record)
- **触发条件**: 模型名以 `-record` 结尾
- **工作流程**:
  1. 直接透传给主模型（不进行记忆检索）
  2. 对话结束后，调用总结模型生成摘要
  3. 摘要存入 pending 暂存区
- **用途**: 快速对话（无检索延迟），但仍保留对话记录
- **示例**: `claude-3-5-sonnet-record`, `gpt-4o-record`

### 3. 日志模式 (log)
- **触发条件**: 模型名以 `-log` 结尾
- **工作流程**:
  1. 注入固定记忆（短期日记、周总结等）
  2. 直接透传给主模型（不进行Agent检索）
  3. 对话结束后，只记录原始对话到 JSONL（不调用模型总结）
- **用途**: 需要固定记忆但不想产生额外 API 调用的场景
- **示例**: `claude-3-5-sonnet-log`, `gpt-4o-log`

### 4. 日志写入模式 (log-write)
- **触发条件**: 模型名以 `-log-write` 结尾
- **工作流程**:
  1. 注入固定记忆（短期日记、周总结等）
  2. 不进行 Agent 检索
  3. 主模型可直接调用记忆读写工具
  4. 对话结束后，只记录原始对话到 JSONL（不调用模型总结）
- **用途**: 需要固定记忆 + 主模型可直接操作记忆库，但不想触发对话后总结
- **示例**: `claude-3-5-sonnet-log-write`, `gpt-4o-log-write`

### 5. 记忆管理模式 (manager)
- **触发条件**: 模型名为 `memory-manager`, `memory-agent`, `lifebook` 等
- **工作流程**:
  1. 直接使用 Agent 模型
  2. 启用所有读写工具
  3. 用于直接管理记忆库
- **用途**: 手动整理记忆、批量操作、调试

### 6. 透传模式 (passthrough)
- **触发条件**: 不匹配上述任何模式
- **工作流程**: 直接转发请求，不进行任何记忆处理
- **示例**: `deepseek-v3`, `gpt-4o`

## 配置说明
- `model_routes`: 定义各模型的 API 配置
- `memory_agent`: Agent 模型配置
- `memory_manager.model_ids`: 管理模式的模型ID列表
- `main_model_memory_tools`: 主模型记忆工具配置
"""

import os
import re
import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Generator
from dataclasses import dataclass

# 动态获取最新配置（若可用）
try:
    from proxy.config import get_config
except ImportError:
    get_config = None

# 统一记忆工具名（唯一权威来源在 proxy.message_utils）
try:
    from proxy.message_utils import MEMORY_TOOL_NAMES as _UNIFIED_MEMORY_TOOL_NAMES
except ImportError:
    _UNIFIED_MEMORY_TOOL_NAMES = None

# 记忆模块
from memory_agent.tools import MemoryTools
from memory_agent.agent import MemoryAgent, AgentConfig, AgentResult
from memory_agent.context_builder import ContextBuilder, ContextConfig, InsertionPosition
from memory_store.reader import LifeBookReader
from memory_store.metadata import MetadataManager
from memory_store.rag import RAGIndex, RAGConfig, RAGSearcher
from memory_store.conversation_logger import ConversationLogger, LoggerConfig
from memory_agent.post_summarizer import PostConversationSummarizer, SummarizerConfig


@dataclass
class RouteResult:
    """路由结果"""
    mode: str  # "memory", "memory-simple", "manager", "record", "log", "log-write", "passthrough"
    base_model: str  # 实际使用的模型
    enable_write: bool  # 是否启用写入工具
    enable_main_model_tools: bool  # 大模型是否可用记忆工具
    enable_summarize: bool = True  # 是否启用对话后总结


class MemoryRouter:
    """记忆路由器"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化路由器
        
        Args:
            config: 配置字典（来自config.jsonc）
        """
        self.config = config
        self.memory_enabled = config.get("memory_enabled", True)
        
        # 记忆管理模型ID（只保留一个，避免混淆）
        manager_config = config.get("memory_manager", {})
        self.manager_model_ids = set(manager_config.get("model_ids", [
            "memory-manager"
        ]))
        
        # 模型路由配置
        self.model_routes = config.get("model_routes", {})
        
        # LifeBook配置
        lifebook_config = config.get("lifebook", {})
        self.lifebook_path = lifebook_config.get("root_path", "./lifebook")
        self.encoding = lifebook_config.get("encoding", "utf-8")
        
        # 确保目录存在
        os.makedirs(self.lifebook_path, exist_ok=True)
        
        # 初始化调试日志器（使用正确的日志目录）
        from memory_store.debug_logger import get_debug_logger
        debug_log_dir = os.path.join(self.lifebook_path, "debug_logs")
        get_debug_logger(debug_log_dir)
        
        # 初始化记忆工具（延迟初始化）
        self._memory_tools: Optional[MemoryTools] = None
        self._memory_tools_write: Optional[MemoryTools] = None
        self._memory_agent: Optional[MemoryAgent] = None
        self._context_builder: Optional[ContextBuilder] = None
        self._metadata_manager: Optional[MetadataManager] = None
        self._conversation_logger: Optional[ConversationLogger] = None
        
        # 上下文配置
        ctx_config = config.get("context", {})
        
        # 分层记忆配置
        layered_config = ctx_config.get("layered_memory", {})
        layered_enabled = layered_config.get("enabled", True)
        short_term_config = layered_config.get("short_term", {})
        weekly_config = layered_config.get("weekly", {})
        monthly_config = layered_config.get("monthly", {})
        quarterly_config = layered_config.get("quarterly", {})
        
        # 额外挂载配置
        extra_mount_config = ctx_config.get("extra_mount", {})
        
        self.context_config = ContextConfig(
            insertion_position=InsertionPosition(
                ctx_config.get("insertion_position", "system_append")
            ),
            prefix=ctx_config.get("insertion_template", {}).get(
                "prefix", "\n\n---\n## 📚 相关记忆\n\n"
            ),
            suffix=ctx_config.get("insertion_template", {}).get(
                "suffix", "\n---\n"
            ),
            empty_hint=ctx_config.get("insertion_template", {}).get(
                "empty_hint", ""
            ),
            enable_confirmation=ctx_config.get("insertion_confirmation", {}).get(
                "enabled", False
            ),
            assistant_ack=ctx_config.get("insertion_confirmation", {}).get(
                "assistant_ack", "好的，我已了解这些背景信息。"
            ),
            # 额外挂载（可选的永久自定义记忆文件）
            extra_mount_enabled=extra_mount_config.get("enabled", False),
            extra_mount_prefix_path=extra_mount_config.get("prefix_path", "lifebook/extra/prefix.md"),
            extra_mount_suffix_path=extra_mount_config.get("suffix_path", "lifebook/extra/suffix.md"),
            include_recent_days=ctx_config.get("recent_days", 7),
            include_current_weekly=True,
            include_current_monthly=ctx_config.get("include_current_month", True),
            max_context_tokens=ctx_config.get("max_context_tokens", 8000),
            simple_mode_insertion_position=ctx_config.get("simple_mode_insertion_position"),
            # 分层记忆配置
            use_layered_memory=layered_enabled,
            short_term_days=short_term_config.get("days", 7),
            short_term_max_chars=short_term_config.get("max_chars_per_entry", 3000),
            include_weekly_summaries=weekly_config.get("enabled", True),
            weekly_max_chars=weekly_config.get("max_chars", 1500),
            include_monthly_summaries=monthly_config.get("enabled", True),
            monthly_max_chars=monthly_config.get("max_chars", 2000),
            include_quarterly_summaries=quarterly_config.get("enabled", True),
            quarterly_max_chars=quarterly_config.get("max_chars", 2500),
            lookback_months=quarterly_config.get("lookback_months", 5),
            # 禁用截断（完整发送记忆内容给主模型）
            disable_truncation=ctx_config.get("disable_truncation", False),
            # 自定义内容（在记忆后插入）- 旧版配置，建议使用 extra_mount
            custom_content_enabled=ctx_config.get("custom_content", {}).get("enabled", False),
            custom_content=ctx_config.get("custom_content", {}).get("content", "")
        )
        
        # 大模型记忆工具配置
        main_tools_config = config.get("main_model_memory_tools", {})
        self.main_model_tools_enabled = main_tools_config.get("enabled", True)
        self.main_model_write_tools = main_tools_config.get("include_write_tools", False)
        self.main_model_tools_hint = main_tools_config.get("tools_hint", "")
        
        # 对话后总结配置 → 委托给 PostConversationSummarizer
        post_config = config.get("post_conversation", {})
        self.post_summarize_enabled = (
            post_config.get("enabled", False) and post_config.get("auto_summarize", False)
        )
        self._summarizer_config = SummarizerConfig(
            enabled=self.post_summarize_enabled,
            model=post_config.get("summarize_model", "deepseek-chat"),
            prompt=post_config.get("summarize_prompt", ""),
            suffix=post_config.get("summarize_suffix", SummarizerConfig.suffix),
            min_messages=post_config.get("min_messages", 2),
            pending_preview_max_chars=post_config.get("pending_preview_max_chars", 200),
            cache_ttl=post_config.get("cache_ttl", 3600),
            lifebook_path=self.lifebook_path,
            encoding=self.encoding,
        )
        self._summarizer: Optional[PostConversationSummarizer] = None
        
        # RAG 配置
        rag_config = config.get("rag", {})
        self.rag_config = RAGConfig(
            api_key=rag_config.get("api_key", ""),
            model=rag_config.get("model", "Qwen/Qwen3-Embedding-8B"),
            base_url=rag_config.get("base_url", "https://api.siliconflow.cn/v1/embeddings"),
            chunk_size=rag_config.get("chunk_size", 500),
            chunk_overlap=rag_config.get("chunk_overlap", 50),
            top_k=rag_config.get("top_k", 5),
            similarity_threshold=rag_config.get("similarity_threshold", 0.3),
            enabled=rag_config.get("enabled", False)
        )
        
        # 全局 RAG 索引
        self._rag_index: Optional[RAGIndex] = None
        
        # Graphiti 配置
        self.graphiti_config = config.get("graphiti", {})
        self.graphiti_enabled = self.graphiti_config.get("enabled", False)
        if self.graphiti_enabled:
            logging.info(f"[Graphiti] 配置已加载 (backend: {self.graphiti_config.get('backend', 'kuzu')})")
        
        # 对话记录器配置
        self.conversation_logger_config = config.get("conversation_logger", {})
        self.conversation_logger_enabled = self.conversation_logger_config.get("enabled", True)
        if self.conversation_logger_enabled:
            logging.info("[ConversationLogger] 原始对话保留机制已启用")

        # 性能缓存
        self._history_check_cache = None  # (result, timestamp)
        self._history_check_ttl = 60  # 缓存60秒
        self._pending_today_cache = None  # (content, timestamp)
        self._pending_today_ttl = 30  # 缓存30秒
        self._last_refresh_time = 0  # 上次刷新配置的时间戳
        self._refresh_interval = 1.0  # 最多1秒刷新一次配置
    
    def _refresh_dynamic_config(self):
        """从热重载配置获取最新的模型路由和管理模型ID（带节流）"""
        if get_config is None:
            return
        
        # 节流：最多每 _refresh_interval 秒刷新一次
        now = time.time()
        if now - self._last_refresh_time < self._refresh_interval:
            return
        self._last_refresh_time = now
        
        try:
            cfg = get_config()
            self.model_routes = cfg.get("model_routes", self.model_routes)
            manager_cfg = cfg.get("memory_manager", {})
            # 如果配置缺失则保留原值
            new_manager_ids = set(manager_cfg.get("model_ids", list(self.manager_model_ids)))
            if new_manager_ids:
                self.manager_model_ids = new_manager_ids
        except Exception as e:
            logging.debug(f"[MemoryRouter] 动态刷新配置失败: {e}")
    
    @property
    def rag_index(self) -> Optional[RAGIndex]:
        """获取RAG索引"""
        if self._rag_index is None and self.rag_config.enabled and self.rag_config.api_key:
            try:
                self._rag_index = RAGIndex(self.lifebook_path, self.rag_config, self.encoding)
                logging.info(f"[RAG] 索引已初始化，共 {len(self._rag_index.entries)} 条向量")
            except Exception as e:
                logging.error(f"[RAG] 初始化失败: {e}")
        return self._rag_index
    
    @property
    def memory_tools(self) -> MemoryTools:
        """获取只读记忆工具"""
        if self._memory_tools is None:
            self._memory_tools = MemoryTools(
                self.lifebook_path,
                enable_write=False,
                encoding=self.encoding,
                rag_config=self.rag_config if self.rag_config.enabled else None,
                graphiti_config=self.graphiti_config if self.graphiti_enabled else None
            )
        return self._memory_tools
    
    @property
    def memory_tools_write(self) -> MemoryTools:
        """获取可写记忆工具"""
        if self._memory_tools_write is None:
            self._memory_tools_write = MemoryTools(
                self.lifebook_path,
                enable_write=True,
                encoding=self.encoding,
                rag_config=self.rag_config if self.rag_config.enabled else None,
                graphiti_config=self.graphiti_config if self.graphiti_enabled else None
            )
        return self._memory_tools_write
    
    @property
    def memory_agent(self) -> MemoryAgent:
        """获取记忆Agent"""
        if self._memory_agent is None:
            agent_config = self.config.get("memory_agent", {})
            self._memory_agent = MemoryAgent(
                memory_tools=self.memory_tools,
                config=AgentConfig(
                    model=agent_config.get("model", "deepseek-reasoner"),
                    api_key=agent_config.get("api_key") or self.config.get("api_key", ""),
                    base_url=agent_config.get("base_url", "https://api.deepseek.com/v1"),
                    max_iterations=agent_config.get("max_iterations", 10),
                    timeout=agent_config.get("timeout", 60),
                    system_prompt=agent_config.get("system_prompt", ""),
                    query_instruction=agent_config.get("query_instruction", "")
                )
            )
        return self._memory_agent
    
    @property
    def metadata_manager(self) -> MetadataManager:
        """获取元数据管理器"""
        if self._metadata_manager is None:
            self._metadata_manager = MetadataManager(self.lifebook_path)
        return self._metadata_manager
    
    @property
    def context_builder(self) -> ContextBuilder:
        """获取上下文组装器"""
        if self._context_builder is None:
            reader = LifeBookReader(self.lifebook_path, self.encoding)
            self._context_builder = ContextBuilder(
                reader,
                self.context_config,
                self.metadata_manager
            )
        return self._context_builder
    
    @property
    def conversation_logger(self) -> Optional[ConversationLogger]:
        """获取对话记录器"""
        if not self.conversation_logger_enabled:
            return None
        
        if self._conversation_logger is None:
            # 获取 Graphiti 适配器（如果启用）
            graphiti_adapter = None
            if self.graphiti_enabled:
                # 延迟导入，避免循环依赖
                try:
                    from memory_store.graphiti_adapter import GraphitiAdapter
                    # TODO: 实际初始化 Graphiti 适配器
                    # graphiti_adapter = GraphitiAdapter(self.graphiti_config, self.lifebook_path)
                except ImportError:
                    logging.debug("[ConversationLogger] Graphiti 适配器暂未实现")
            
            self._conversation_logger = ConversationLogger(
                lifebook_path=self.lifebook_path,
                config=self.config,
                graphiti_adapter=graphiti_adapter
            )
        
        return self._conversation_logger
    
    def route(self, model: str) -> RouteResult:
        """
        路由模型请求
        
        Args:
            model: 请求的模型ID
            
        Returns:
            RouteResult
        """
        # 每次路由前刷新配置，确保新模型即时可用
        self._refresh_dynamic_config()
        
        # 检查是否是记忆管理模式
        if model in self.manager_model_ids:
            return RouteResult(
                mode="manager",
                base_model=self.config.get("memory_agent", {}).get("model", "deepseek-reasoner"),
                enable_write=True,
                enable_main_model_tools=True
            )
        
        # 检查是否带新的 -memory-simple 后缀 (大模型无工具)
        if model.endswith("-memory-simple"):
            base_model = model[:-14] # 去掉 "-memory-simple"
            return RouteResult(
                mode="memory",
                base_model=base_model,
                enable_write=False,
                enable_main_model_tools=False # 禁用大模型的工具
            )
        # 检查是否带 -memory 后缀 (大模型有工具)
        elif model.endswith("-memory"):
            base_model = model[:-7]  # 去掉 "-memory"
            return RouteResult(
                mode="memory",
                base_model=base_model,
                enable_write=False,
                enable_main_model_tools=self.main_model_tools_enabled
            )
        # 检查是否带 -record 后缀 (只记录不检索，但会触发总结)
        elif model.endswith("-record"):
            base_model = model[:-7]  # 去掉 "-record"
            return RouteResult(
                mode="record",
                base_model=base_model,
                enable_write=False,
                enable_main_model_tools=False,
                enable_summarize=True  # 启用对话后总结
            )
        # 检查是否带 -log-write 后缀 (固定记忆 + 主模型记忆读写工具 + 仅记录原始对话)
        elif model.endswith("-log-write"):
            base_model = model[:-10]  # 去掉 "-log-write"
            return RouteResult(
                mode="log-write",
                base_model=base_model,
                enable_write=True,
                enable_main_model_tools=True,
                enable_summarize=False  # 禁用对话后总结
            )
        # 检查是否带 -log 后缀 (只记录原始对话，不触发总结)
        elif model.endswith("-log"):
            base_model = model[:-4]  # 去掉 "-log"
            return RouteResult(
                mode="log",
                base_model=base_model,
                enable_write=False,
                enable_main_model_tools=False,
                enable_summarize=False  # 禁用对话后总结
            )
        
        # 普通透传
        return RouteResult(
            mode="passthrough",
            base_model=model,
            enable_write=False,
            enable_main_model_tools=False,
            enable_summarize=False  # 透传模式不总结
        )
    
    def get_actual_model_config(self, base_model: str) -> Dict[str, Any]:
        """
        获取实际模型配置
        
        Args:
            base_model: 基础模型ID
            
        Returns:
            模型配置字典
        """
        self._refresh_dynamic_config()
        routes = self.model_routes or {}
        if base_model in routes:
            return routes[base_model]
        
        # 使用默认配置
        return routes.get("_default", {"use_user_key": True})
    
    def _check_has_history(self) -> Tuple[bool, int, int]:
        """
        检查是否有足够的历史记录需要搜索（带缓存）
        
        Returns:
            (是否需要Agent检索, 日记总数, 运行天数)
        """
        # 检查缓存
        now = time.time()
        if self._history_check_cache is not None:
            cached_result, cached_time = self._history_check_cache
            if now - cached_time < self._history_check_ttl:
                return cached_result
        
        try:
            from memory_store.reader import LifeBookReader
            reader = LifeBookReader(self.lifebook_path, self.encoding)
            all_diaries = reader.list_all_diaries()
            diary_count = len(all_diaries)
            
            if not all_diaries:
                return False, 0, 0
            
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            
            # 计算运行天数
            earliest = min(all_diaries)
            days_running = 0
            try:
                earliest_date = datetime.strptime(earliest, '%Y-%m-%d')
                days_running = (datetime.now() - earliest_date).days
            except:
                pass
            
            # 关键改进：运行天数 < 7 天，短期记忆已完整覆盖，无需Agent检索
            short_term_days = self.context_config.short_term_days  # 默认7天
            if days_running < short_term_days:
                logging.info(f"[检查历史] 运行天数 {days_running} < {short_term_days}天，短期记忆已完整覆盖，跳过检索")
                return False, diary_count, days_running
            
            # 检查是否有今天之前的日记
            has_past_diaries = any(d < today for d in all_diaries)
            
            result = (has_past_diaries, diary_count, days_running)
            self._history_check_cache = (result, now)
            return result
        except Exception as e:
            logging.warning(f"[检查历史] 出错: {e}")
            return True, 0, 0  # 出错时默认需要搜索
    
    def _is_search_needed(self, query: str) -> bool:
        """
        智能判断是否需要搜索记忆
        
        一些简单问候或当前状态询问不需要搜索历史
        """
        # 不需要搜索的模式
        no_search_patterns = [
            r'^(你好|hi|hello|hey|嗨|哈喽)[\s!！。.]*$',
            r'^(早上好|晚上好|下午好|早安|晚安)[\s!！。.]*$',
            r'^测试[\s!！。.]*$',
            r'^你是谁[\s?？]*$',
            r'^(介绍一下)?你自己[\s?？]*$',
        ]
        
        import re
        query_lower = query.strip().lower()
        
        for pattern in no_search_patterns:
            if re.match(pattern, query_lower, re.IGNORECASE):
                return False
        
        return True

    def _has_images(self, messages: List[Dict[str, Any]]) -> bool:
        """检查对话中是否包含图片内容"""
        # 只检查最后一条用户消息
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and (item.get("type") == "image_url" or item.get("type") == "image"):
                            return True
                break
        return False

    def _get_agent_recent_memory(self) -> str:
        """获取最近N天的日记内容以提供给Agent（使用分层配置的天数）"""
        try:
            # 获取记忆库范围信息
            all_diaries = self.context_builder.reader.list_all_diaries()
            if all_diaries:
                earliest = min(all_diaries)
                latest = max(all_diaries)
                range_info = f"📅 记忆库范围: {earliest} ~ {latest} (共{len(all_diaries)}天记录)\n\n"
            else:
                range_info = "📅 记忆库范围: 无历史记录\n\n"
            
            parts = [range_info]
            
            # 使用配置的短期记忆天数
            days = self.context_config.short_term_days
            recent_diaries = self.context_builder.reader.read_recent_diaries(days)
            if recent_diaries:
                parts.append(f"## 最近{days}天记忆\n")
                for diary in recent_diaries:
                    # 完整内容（与主模型保持一致）
                    max_chars = self.context_config.short_term_max_chars
                    content = diary.content[:max_chars]
                    if len(diary.content) > max_chars:
                        content += "\n... (已截断)"
                    parts.append(f"### 日期: {diary.date}\n{content}\n")
            
            # 【新增】今日 pending 内容（还没汇总成日记的对话摘要）
            pending_content = self._get_today_pending_for_agent()
            if pending_content:
                parts.append(pending_content)
            
            if len(parts) == 1:  # 只有 range_info
                return range_info + "（最近无日记和待处理记录）"
            
            return "\n".join(parts)
        except Exception as e:
            logging.error(f"[错误] 获取Agent最近记忆失败: {e}")
            return ""
    
    def _get_today_pending_for_agent(self) -> str:
        """获取今日 pending 内容（给搜索 Agent 用，带缓存）"""
        # 检查缓存
        now = time.time()
        if self._pending_today_cache is not None:
            cached_content, cached_time = self._pending_today_cache
            if now - cached_time < self._pending_today_ttl:
                return cached_content
        
        try:
            from memory_store.pending_manager import PendingManager
            
            pending_mgr = PendingManager(self.lifebook_path, self.encoding)
            all_sessions = pending_mgr.get_all_sessions()
            
            if not all_sessions:
                return ""
            
            today = datetime.now().strftime('%Y-%m-%d')
            parts = []
            total_summaries = 0
            
            for session in all_sessions:
                session_date = session.start_time.strftime('%Y-%m-%d')
                
                # 只包含今天的会话
                if session_date != today:
                    continue
                
                if not session.summaries:
                    continue
                
                for summary in session.summaries:
                    ts = datetime.fromisoformat(summary.timestamp)
                    time_str = ts.strftime('%H:%M')
                    
                    parts.append(f"- {time_str} [{summary.topic}]: {summary.summary[:300]}...")
                    total_summaries += 1
            
            if total_summaries == 0:
                self._pending_today_cache = ("", now)
                return ""
            
            header = f"\n## 🗒️ 今日待归档记录（{total_summaries}条，尚未写入日记）\n"
            result = header + "\n".join(parts)
            self._pending_today_cache = (result, now)
            return result
            
        except Exception as e:
            logging.warning(f"[Agent] 获取 pending 失败: {e}")
            return ""
    
    def process_memory_request(
        self,
        messages: List[Dict[str, Any]],
        route_result: RouteResult,
        user_api_key: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], AgentResult]:
        """
        处理记忆增强请求（同步版本）
        
        1. 检查是否需要搜索
        2. 提取用户最后一条消息作为查询
        3. 调用Agent检索相关记忆
        4. 组装上下文
        
        Args:
            messages: 原始消息列表
            route_result: 路由结果
            user_api_key: 用户API Key（用于Agent）
            
        Returns:
            (增强后的消息, 可用工具列表, Agent结果)
        """
        # 提取查询
        query = self._extract_query(messages)
        
        # 检查是否有历史记录（返回：是否需要检索, 日记数, 运行天数）
        has_history, diary_count, days_running = self._check_has_history()
        
        # 检查是否需要搜索
        search_needed = self._is_search_needed(query)
        
        # 检查是否包含图片（DeepSeek 暂不支持）
        has_images = self._has_images(messages)
        
        # 如果没有历史、不需要搜索或包含图片，跳过Agent检索
        if not has_history or not search_needed or has_images:
            if has_images:
                reason = "对话包含图片内容（当前检索代理不支持）"
            elif not has_history:
                if days_running > 0 and days_running < self.context_config.short_term_days:
                    reason = f"运行仅{days_running}天，短期记忆已完整覆盖"
                else:
                    reason = "没有历史记录"
            else:
                reason = "当前问题不需要搜索历史"
                
            logging.info(f"[记忆检索] 跳过检索：{reason}（日记数: {diary_count}）")
            
            # 创建空的Agent结果
            agent_result = AgentResult(
                success=True,
                content=f"（{reason}，直接回复即可）",
                reasoning="",
                tool_calls=[],
                iterations=0,
                tokens_used={}
            )
        else:
            # 提取完整对话上下文
            context = self._extract_context(messages)
            
            # 为Agent注入完整的短期记忆（使用配置的天数）
            recent_memory = self._get_agent_recent_memory()
            if recent_memory:
                context = f"{recent_memory}\n\n[原始对话上下文]\n{context}"

            # 调用Agent检索
            logging.info(f"[记忆检索] 开始检索相关记忆...")
            logging.debug(f"[记忆检索] 查询: {query[:100]}...")
            
            agent_result = self.memory_agent.retrieve(
                query=query,
                context=context,
                include_write_tools=route_result.enable_write
            )
            
            logging.info(f"[记忆检索] 完成，找到 {len(agent_result.tool_calls)} 次工具调用")
            if agent_result.success:
                logging.debug(f"[记忆检索] 结果预览: {agent_result.content[:200]}...")
        
        # 组装上下文
        # 检查是否为simple模式 (大模型无工具)
        is_simple_mode = not route_result.enable_main_model_tools
        override_pos = None
        if is_simple_mode:
            override_pos = self.context_config.simple_mode_insertion_position

        built = self.context_builder.build(
            messages=messages,
            dynamic_memory=agent_result.content if agent_result.success else "",
            include_fixed=True,
            override_insertion_position=override_pos,
            model_name=route_result.base_model  # 传递模型名以支持条件挂载
        )
        
        # 更新上次交互时间
        self.metadata_manager.update_last_interaction()
        
        # 获取可用工具（如果启用大模型工具）
        tools = []
        result_messages = built.messages
        if route_result.enable_main_model_tools:
            # 根据配置决定是否包含写入工具
            include_write = self.main_model_write_tools or route_result.enable_write
            if include_write:
                tools = self.memory_tools_write.get_openai_tools(include_write=True)
            else:
                tools = self.memory_tools.get_openai_tools(include_write=False)
            
            # 添加工具使用提示到系统消息
            if tools:
                # 检查工具列表中是否有 graphiti 工具
                has_graphiti_tools = any(
                    t.get("function", {}).get("name", "").startswith("graphiti_")
                    for t in tools
                )
                tools_hint = self.context_builder.get_memory_tools_prompt(
                    enable_write=include_write,
                    custom_hint=self.main_model_tools_hint,
                    include_graphiti=has_graphiti_tools
                )
                result_messages = self._add_tools_hint_to_messages(result_messages, tools_hint)
        
        return result_messages, tools, agent_result
    
    def process_memory_request_stream(
        self,
        messages: List[Dict[str, Any]],
        route_result: RouteResult,
        user_api_key: Optional[str] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """
        处理记忆增强请求（流式版本）
        
        实时输出Agent的思考过程，让用户不用干等
        
        Yields:
            {"type": "reasoning", "content": "..."} - 思维链内容
            {"type": "final", "messages": [...], "tools": [...], "agent_result": {...}} - 最终结果
        """
        # 提取查询
        query = self._extract_query(messages)
        
        # 检查是否有历史记录（返回：是否需要检索, 日记数, 运行天数）
        has_history, diary_count, days_running = self._check_has_history()
        
        # 检查是否需要搜索
        search_needed = self._is_search_needed(query)
        
        # 检查是否包含图片
        has_images = self._has_images(messages)
        
        # 如果没有历史、不需要搜索或包含图片，直接跳过Agent
        if not has_history or not search_needed or has_images:
            if has_images:
                reason = "对话包含图片内容（当前检索代理不支持）"
            elif not has_history:
                if days_running > 0 and days_running < self.context_config.short_term_days:
                    reason = f"运行仅{days_running}天，短期记忆已完整覆盖"
                else:
                    reason = "没有历史记录"
            else:
                reason = "当前问题不需要搜索历史"
                
            logging.info(f"[记忆检索-流式] 跳过检索：{reason}（日记数: {diary_count}）")
            
            yield {"type": "reasoning", "content": f"（{reason}，直接回复）\n\n"}
            
            agent_result = AgentResult(
                success=True,
                content=f"（{reason}）",
                reasoning="",
                tool_calls=[],
                iterations=0,
                tokens_used={}
            )
            
            # 组装上下文（只包含固定部分，不搜索）
            built = self.context_builder.build(
                messages=messages,
                dynamic_memory="",
                include_fixed=True,
                model_name=route_result.base_model  # 传递模型名以支持条件挂载
            )
            
            # 更新上次交互时间
            self.metadata_manager.update_last_interaction()
            
            # 获取可用工具
            tools = []
            result_messages = built.messages
            if route_result.enable_main_model_tools:
                include_write = self.main_model_write_tools or route_result.enable_write
                if include_write:
                    tools = self.memory_tools_write.get_openai_tools(include_write=True)
                else:
                    tools = self.memory_tools.get_openai_tools(include_write=False)
                
                # 【修复】添加工具使用提示到系统消息
                if tools:
                    has_graphiti_tools = any(
                        t.get("function", {}).get("name", "").startswith("graphiti_")
                        for t in tools
                    )
                    tools_hint = self.context_builder.get_memory_tools_prompt(
                        enable_write=include_write,
                        custom_hint=self.main_model_tools_hint,
                        include_graphiti=has_graphiti_tools
                    )
                    result_messages = self._add_tools_hint_to_messages(result_messages, tools_hint)
            
            # yield最终结果
            yield {
                "type": "final",
                "messages": result_messages,
                "tools": tools,
                "agent_result": agent_result
            }
            return
        
        # 有历史且需要搜索，使用流式Agent
        # 提取完整对话上下文
        context = self._extract_context(messages)

        # 为Agent注入完整的短期记忆
        recent_memory = self._get_agent_recent_memory()
        if recent_memory:
            context = f"{recent_memory}\n\n[原始对话上下文]\n{context}"
        
        # 输出开始提示
        yield {"type": "reasoning", "content": "🔍 正在检索相关记忆...\n\n"}
        
        logging.info(f"[记忆检索-流式] 开始检索相关记忆...")
        logging.debug(f"[记忆检索-流式] 查询: {query[:100]}...")
        
        # 使用流式Agent检索
        agent_result = None
        is_first_content = True  # 标记是否是第一个content事件
        for event in self.memory_agent.retrieve_stream(
            query=query,
            context=context,
            include_write_tools=route_result.enable_write
        ):
            event_type = event.get("type")
            
            if event_type == "iteration_start":
                iteration = event.get("iteration", 1)
                yield {"type": "reasoning", "content": f"\n--- 迭代 {iteration} ---\n"}
                
            elif event_type == "reasoning":
                # 直接传递思维链内容
                yield {"type": "reasoning", "content": event.get("content", "")}
                
            elif event_type == "content":
                # Agent的输出内容也放到reasoning里
                # 只在第一个content事件前加空行分隔（区分思考和结论）
                if is_first_content:
                    yield {"type": "reasoning", "content": "\n\n" + event.get("content", "")}
                    is_first_content = False
                else:
                    yield {"type": "reasoning", "content": event.get("content", "")}
                
            elif event_type == "tool_call":
                name = event.get("name", "")
                args = event.get("arguments", {})
                import json
                args_str = json.dumps(args, ensure_ascii=False)
                yield {"type": "reasoning", "content": f"\n「调用工具: {name} 参数: {args_str}」\n"}
                
            elif event_type == "tool_result":
                name = event.get("name", "")
                result = event.get("result", "")
                yield {"type": "reasoning", "content": f"[{name}结果] {result}\n"}
                
            elif event_type in ("complete", "error", "max_iterations"):
                agent_result = event.get("result")
                break
        
        # 如果没有结果，创建一个失败结果
        if agent_result is None:
            agent_result = AgentResult(
                success=False,
                content="记忆检索未完成",
                reasoning="",
                tool_calls=[],
                iterations=0,
                tokens_used={}
            )
        
        logging.info(f"[记忆检索-流式] 完成，找到 {len(agent_result.tool_calls)} 次工具调用")
        
        # 输出完成提示
        yield {"type": "reasoning", "content": "\n\n📚 记忆检索完成，开始生成回复...\n\n"}
        
        # 组装上下文
        is_simple_mode = not route_result.enable_main_model_tools
        override_pos = None
        if is_simple_mode:
            override_pos = self.context_config.simple_mode_insertion_position

        built = self.context_builder.build(
            messages=messages,
            dynamic_memory=agent_result.content if agent_result.success else "",
            include_fixed=True,
            override_insertion_position=override_pos,
            model_name=route_result.base_model  # 传递模型名以支持条件挂载
        )
        
        # 更新上次交互时间
        self.metadata_manager.update_last_interaction()
        
        # 获取可用工具
        tools = []
        result_messages = built.messages
        if route_result.enable_main_model_tools:
            include_write = self.main_model_write_tools or route_result.enable_write
            if include_write:
                tools = self.memory_tools_write.get_openai_tools(include_write=True)
            else:
                tools = self.memory_tools.get_openai_tools(include_write=False)
            
            # 添加工具使用提示到系统消息
            if tools:
                has_graphiti_tools = any(
                    t.get("function", {}).get("name", "").startswith("graphiti_")
                    for t in tools
                )
                tools_hint = self.context_builder.get_memory_tools_prompt(
                    enable_write=include_write,
                    custom_hint=self.main_model_tools_hint,
                    include_graphiti=has_graphiti_tools
                )
                result_messages = self._add_tools_hint_to_messages(result_messages, tools_hint)
        
        # yield最终结果（这样调用方可以通过遍历获取）
        yield {
            "type": "final",
            "messages": result_messages,
            "tools": tools,
            "agent_result": agent_result
        }
        
    
    def process_manager_request(
        self,
        messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        处理记忆管理请求
        
        直接返回消息和写入工具列表
        
        Args:
            messages: 原始消息列表
            
        Returns:
            (消息, 可用工具列表)
        """
        # 从配置读取管理模式系统提示词
        manager_config = self.config.get("memory_manager", {})
        system_prompt = manager_config.get("system_prompt", """你是LifeBook记忆管理助手。你可以直接操作记忆库。

## 可用工具

### 查询
- search_memories: 搜索记忆
- read_diary: 读取日记
- get_node: 获取节点
- list_nodes: 列出节点
- get_memory_overview: 获取记忆概览
- read_graph: 读取知识图谱

### 写入
- add_to_diary: 向日记添加内容
- create_node: 创建节点
- update_node: 更新节点
- delete_node: 删除节点
- create_relations: 创建节点间关系
- add_observations: 添加观察事实

请根据用户需求执行操作。""")
        
        # 检查是否已有系统消息
        if messages and messages[0].get("role") == "system":
            messages = messages.copy()
            messages[0] = messages[0].copy()
            messages[0]["content"] = system_prompt + "\n\n" + messages[0]["content"]
        else:
            messages = [{"role": "system", "content": system_prompt}] + messages
        
        # 获取写入工具
        tools = self.memory_tools_write.get_openai_tools(include_write=True)
        
        return messages, tools
    
    def execute_memory_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        enable_write: bool = False
    ) -> str:
        """
        执行记忆工具
        
        Args:
            tool_name: 工具名称
            arguments: 参数
            enable_write: 是否启用写入
            
        Returns:
            工具执行结果
        """
        if enable_write:
            return self.memory_tools_write.call_tool(tool_name, arguments)
        else:
            return self.memory_tools.call_tool(tool_name, arguments)
    
    def is_memory_tool(self, tool_name: str) -> bool:
        """检查是否是记忆工具（引用 proxy.message_utils 的统一列表）"""
        if _UNIFIED_MEMORY_TOOL_NAMES is not None:
            return tool_name in _UNIFIED_MEMORY_TOOL_NAMES
        # 回退：最小集合（避免导入失败时功能完全丧失）
        return tool_name in {
            "search_memories", "rag_search", "read_diary", "read_summary",
            "get_node", "list_nodes", "get_memory_overview", "read_all_nodes",
            "read_graph", "add_observations", "create_relations",
            "add_to_diary", "create_node", "update_node", "create_summary",
            "edit_diary", "edit_node", "edit_summary", "rewrite_diary",
            "delete_node", "delete_summary", "add_to_pending",
            "graphiti_search", "graphiti_temporal", "graphiti_add",
            "graphiti_multi_hop", "graphiti_sync_node", "graphiti_get_stats",
        }
    
    def _add_tools_hint_to_messages(
        self,
        messages: List[Dict[str, Any]],
        tools_hint: str
    ) -> List[Dict[str, Any]]:
        """在消息中添加工具使用提示"""
        if not tools_hint:
            return messages
        
        messages = [m.copy() for m in messages]
        
        # 找到系统消息并追加提示
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = messages[0]["content"] + "\n\n" + tools_hint
        else:
            # 没有系统消息，创建一个
            messages.insert(0, {"role": "system", "content": tools_hint})
        
        return messages
    
    def _extract_query(self, messages: List[Dict[str, Any]]) -> str:
        """提取用户查询（支持多模态列表格式）"""
        # 找最后一条用户消息
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                
                # 如果是字符串，直接返回
                if isinstance(content, str):
                    return content
                
                # 如果是列表（多模态），提取文字部分
                if isinstance(content, list):
                    texts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            texts.append(item.get("text", ""))
                        elif isinstance(item, str):
                            texts.append(item)
                    return " ".join(texts)
                
                return str(content)
        return ""
    
    def _extract_context(self, messages: List[Dict[str, Any]], include_all: bool = True) -> str:
        """
        提取对话上下文（用于记忆检索Agent）
        
        Args:
            messages: 完整消息列表
            include_all: 是否包含全部对话（True=完整上下文）
        """
        
        def process_content(content):
            """处理消息内容（支持多模态，过滤图片base64以节省token）"""
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            texts.append(item.get("text", ""))
                        elif item.get("type") in ["image_url", "image"]:
                            texts.append("[图片]")  # 替换图片base64为占位符
                    elif isinstance(item, str):
                        texts.append(item)
                return " ".join(texts)
            elif content is None:
                return ""
            return str(content)
        
        # 收集所有消息（不包括最后一条用户消息，因为它作为 query 单独传）
        context_messages = []
        skip_last_user = True
        
        for msg in reversed(messages):
            role = msg.get("role", "")
            if role == "user":
                if skip_last_user:
                    skip_last_user = False  # 跳过最后一条用户消息
                    continue
            context_messages.insert(0, msg)
        
        if not context_messages:
            return ""
        
        # 格式化完整对话
        lines = []
        for msg in context_messages:
            role = msg.get("role", "")
            content = process_content(msg.get("content", ""))  # 使用处理函数过滤图片
            
            # 根据角色处理
            if role == "system":
                # 系统消息保留完整（可能包含重要人设）
                lines.append(f"[系统提示]: {content}")
            elif role == "user":
                lines.append(f"用户: {content}")
            elif role == "assistant":
                lines.append(f"助手: {content}")
        
        return "\n\n".join(lines)
    
    def get_virtual_models(self) -> List[Dict[str, Any]]:
        """获取虚拟模型列表（用于 /v1/models 接口）"""
        # 动态刷新，确保新增模型即刻列出
        self._refresh_dynamic_config()
        
        models = []
        routes = self.model_routes or {}
        
        # 记忆增强模型
        for model_id in routes.keys():
            if model_id.startswith("_"):
                continue
            # -memory (大模型有工具)
            models.append({
                "id": f"{model_id}-memory",
                "object": "model",
                "owned_by": "lifebook-proxy (tools)",
                "permission": []
            })
            # -memory-simple (大模型无工具)
            models.append({
                "id": f"{model_id}-memory-simple",
                "object": "model",
                "owned_by": "lifebook-proxy (no-tools)",
                "permission": []
            })
            # -record (只记录不检索，触发总结)
            models.append({
                "id": f"{model_id}-record",
                "object": "model",
                "owned_by": "lifebook-proxy (record-only)",
                "permission": []
            })
            # -log (只记录原始对话，不触发总结)
            models.append({
                "id": f"{model_id}-log",
                "object": "model",
                "owned_by": "lifebook-proxy (log-only)",
                "permission": []
            })
            # -log-write (固定记忆 + 主模型记忆读写工具 + 仅记录原始对话)
            models.append({
                "id": f"{model_id}-log-write",
                "object": "model",
                "owned_by": "lifebook-proxy (log-write)",
                "permission": []
            })
        
        # 记忆管理模型
        for model_id in self.manager_model_ids:
            models.append({
                "id": model_id,
                "object": "model",
                "owned_by": "lifebook-proxy",
                "permission": []
            })
        
        # 原始模型
        for model_id in self.model_routes.keys():
            if model_id.startswith("_"):
                continue
            models.append({
                "id": model_id,
                "object": "model",
                "owned_by": "proxy",
                "permission": []
            })
        
        return models
    
    def rebuild_index(self):
        """重建记忆索引"""
        self.memory_tools.indexer.rebuild_index()
        logging.info("记忆索引已重建")
    
    def log_conversation(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        response: str,
        user_key: str = "default",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        记录对话到原始对话保留系统
        
        Args:
            messages: 完整消息历史
            model: 使用的模型
            response: AI 回复
            user_key: 用户标识（如 API Key）
            metadata: 额外元数据
        
        Returns:
            对话文件路径（字符串），如果禁用则返回 None
        """
        if not self.conversation_logger_enabled:
            return None
        
        logger = self.conversation_logger
        if logger is None:
            return None
        
        try:
            file_path = logger.log_turn(
                messages=messages,
                model=model,
                response=response,
                user_key=user_key,
                metadata=metadata
            )
            return str(file_path)
        except Exception as e:
            logging.warning(f"[对话记录] 失败: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """获取记忆系统统计"""
        return self.memory_tools.indexer.get_stats()
    
    @property
    def summarizer(self) -> PostConversationSummarizer:
        """获取对话后总结器（延迟初始化）"""
        if self._summarizer is None:
            agent_config = self.config.get("memory_agent", {})
            self._summarizer = PostConversationSummarizer(
                config=self._summarizer_config,
                memory_tools_write=self.memory_tools_write,
                model_config_resolver=self.get_actual_model_config,
                fallback_api_config={
                    "api_key": agent_config.get("api_key", ""),
                    "base_url": agent_config.get("base_url", "https://api.deepseek.com/v1"),
                },
            )
        return self._summarizer
    
    def get_last_conversation(self) -> Optional[Tuple[List[Dict[str, Any]], str, str]]:
        """获取缓存的最后一次对话（委托给 summarizer）"""
        return self.summarizer.get_last_conversation()
    
    def clear_conversation_cache(self):
        """手动清理对话缓存（委托给 summarizer）"""
        self.summarizer.clear_conversation_cache()
    
    def summarize_and_save(
        self,
        messages: List[Dict[str, Any]],
        response_content: str,
        async_mode: bool = True,
        main_model_reasoning: Optional[str] = None
    ) -> Optional[str]:
        """对话后总结并暂存（委托给 summarizer）"""
        return self.summarizer.summarize_and_save(
            messages, response_content, async_mode, main_model_reasoning
        )
    


# 全局路由器
# ⚠️ 同上：当前运行时优先使用包版 [`memory_router/__init__.py`](memory_router/__init__.py)
# 和 [`memory_router/core.py`](memory_router/core.py) 里的全局路由器。
# 这里的单文件版全局对象仅保留作兼容/参考，不是主服务生效入口。
_router: Optional[MemoryRouter] = None


def init_memory_router(config: Dict[str, Any]) -> MemoryRouter:
    """初始化全局路由器"""
    global _router
    _router = MemoryRouter(config)
    return _router


def get_memory_router() -> Optional[MemoryRouter]:
    """获取全局路由器"""
    return _router


# 测试代码已移至 tests/test_memory_router.py
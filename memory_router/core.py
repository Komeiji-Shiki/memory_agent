"""
Memory Router Core - 核心路由逻辑

负责模型路由、记忆检索和上下文组装。
"""

import os
import re
import time
import logging
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Generator
from dataclasses import dataclass

# 动态获取最新配置（若可用）
try:
    from proxy.config import get_config
except ImportError:
    get_config = None

from memory_agent.tools import MemoryTools
from memory_agent.agent import MemoryAgent, AgentConfig, AgentResult
from memory_agent.context_builder import ContextBuilder, ContextConfig, InsertionPosition
from memory_store.reader import LifeBookReader
from memory_store.metadata import MetadataManager
from memory_store.rag import RAGIndex, RAGConfig, RAGSearcher
from memory_store.conversation_logger import ConversationLogger

# 从 constants 导入常量
try:
    from proxy.constants import ModelSuffixes, RouteModes, MemoryToolNames, Defaults
except ImportError:
    # 兼容直接运行
    class ModelSuffixes:
        MEMORY = "-memory"
        MEMORY_SIMPLE = "-memory-simple"
        RECORD = "-record"
        LOG = "-log"
    
    class RouteModes:
        MEMORY = "memory"
        MANAGER = "manager"
        RECORD = "record"
        LOG = "log"
        PASSTHROUGH = "passthrough"
    
    class Defaults:
        ENCODING = "utf-8"
        SHORT_TERM_DAYS = 7
        MAX_CONTEXT_TOKENS = 8000


@dataclass
class RouteResult:
    """路由结果"""
    mode: str  # RouteModes 中的值
    base_model: str  # 实际使用的模型
    enable_write: bool  # 是否启用写入工具
    enable_main_model_tools: bool  # 大模型是否可用记忆工具
    enable_summarize: bool = True  # 是否启用对话后总结


class MemoryRouter:
    """记忆路由器 - 核心类"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化路由器
        
        Args:
            config: 配置字典（来自config.jsonc）
        """
        self.config = config
        self.memory_enabled = config.get("memory_enabled", True)
        
        # 记忆管理模型ID
        manager_config = config.get("memory_manager", {})
        self.manager_model_ids = set(manager_config.get("model_ids", [
            "memory-manager"
        ]))
        
        # 模型路由配置
        self.model_routes = config.get("model_routes", {})
        
        # LifeBook配置
        lifebook_config = config.get("lifebook", {})
        self.lifebook_path = lifebook_config.get("root_path", "./lifebook")
        self.encoding = lifebook_config.get("encoding", Defaults.ENCODING)
        
        # 确保目录存在
        os.makedirs(self.lifebook_path, exist_ok=True)
        
        # 初始化调试日志器
        from memory_store.debug_logger import get_debug_logger
        debug_log_dir = os.path.join(self.lifebook_path, "debug_logs")
        get_debug_logger(debug_log_dir)
        
        # 延迟初始化
        self._memory_tools: Optional[MemoryTools] = None
        self._memory_tools_write: Optional[MemoryTools] = None
        self._memory_agent: Optional[MemoryAgent] = None
        self._context_builder: Optional[ContextBuilder] = None
        self._metadata_manager: Optional[MetadataManager] = None
        
        # 加载配置
        self._load_context_config(config)
        self._load_rag_config(config)
        self._load_main_model_config(config)
        self._load_post_conversation_config(config)
        self._load_graphiti_config(config)
        
        # 对话记录器
        self._conversation_logger: Optional[ConversationLogger] = None
        self.conversation_logger_config = config.get("conversation_logger", {})
        self.conversation_logger_enabled = self.conversation_logger_config.get("enabled", True)
        if self.conversation_logger_enabled:
            logging.info("[ConversationLogger] 原始对话保留机制已启用")
        
        # 对话缓存
        self._last_conversation = None
        self._last_conversation_ttl = self.post_config.get("cache_ttl", 3600)
        
        # 延迟导入总结器
        self._summarizer = None
    
    def _refresh_dynamic_config(self):
        """从热重载配置获取最新的模型路由和管理模型ID"""
        if get_config is None:
            return
        try:
            cfg = get_config()
            self.model_routes = cfg.get("model_routes", self.model_routes)
            manager_cfg = cfg.get("memory_manager", {})
            new_manager_ids = set(manager_cfg.get("model_ids", list(self.manager_model_ids)))
            if new_manager_ids:
                self.manager_model_ids = new_manager_ids
        except Exception as e:
            logging.debug(f"[MemoryRouterCore] 动态刷新配置失败: {e}")
    
    def _load_context_config(self, config: Dict[str, Any]):
        """加载上下文配置"""
        ctx_config = config.get("context", {})
        layered_config = ctx_config.get("layered_memory", {})
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
            extra_mount_enabled=extra_mount_config.get("enabled", False),
            extra_mount_prefix_path=extra_mount_config.get("prefix_path", "lifebook/extra/prefix.md"),
            extra_mount_suffix_path=extra_mount_config.get("suffix_path", "lifebook/extra/suffix.md"),
            include_recent_days=ctx_config.get("recent_days", Defaults.SHORT_TERM_DAYS),
            include_current_weekly=True,
            include_current_monthly=ctx_config.get("include_current_month", True),
            max_context_tokens=ctx_config.get("max_context_tokens", Defaults.MAX_CONTEXT_TOKENS),
            simple_mode_insertion_position=ctx_config.get("simple_mode_insertion_position"),
            use_layered_memory=layered_config.get("enabled", True),
            short_term_days=layered_config.get("short_term", {}).get("days", 7),
            short_term_max_chars=layered_config.get("short_term", {}).get("max_chars_per_entry", 3000),
            include_weekly_summaries=layered_config.get("weekly", {}).get("enabled", True),
            weekly_max_chars=layered_config.get("weekly", {}).get("max_chars", 1500),
            include_monthly_summaries=layered_config.get("monthly", {}).get("enabled", True),
            monthly_max_chars=layered_config.get("monthly", {}).get("max_chars", 2000),
            include_quarterly_summaries=layered_config.get("quarterly", {}).get("enabled", True),
            quarterly_max_chars=layered_config.get("quarterly", {}).get("max_chars", 2500),
            lookback_months=layered_config.get("quarterly", {}).get("lookback_months", 5),
            disable_truncation=ctx_config.get("disable_truncation", False),
            custom_content_enabled=ctx_config.get("custom_content", {}).get("enabled", False),
            custom_content=ctx_config.get("custom_content", {}).get("content", "")
        )
    
    def _load_rag_config(self, config: Dict[str, Any]):
        """加载RAG配置"""
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
        self._rag_index: Optional[RAGIndex] = None
    
    def _load_main_model_config(self, config: Dict[str, Any]):
        """加载主模型记忆工具配置"""
        main_tools_config = config.get("main_model_memory_tools", {})
        self.main_model_tools_enabled = main_tools_config.get("enabled", True)
        self.main_model_write_tools = main_tools_config.get("include_write_tools", False)
        self.main_model_tools_hint = main_tools_config.get("tools_hint", "")
    
    def _load_post_conversation_config(self, config: Dict[str, Any]):
        """加载对话后总结配置"""
        post_config = config.get("post_conversation", {})
        self.post_summarize_enabled = post_config.get("enabled", False) and post_config.get("auto_summarize", False)
        self.post_summarize_model = post_config.get("summarize_model", "deepseek-chat")
        self.post_summarize_prompt = post_config.get("summarize_prompt", "")
        self.post_summarize_suffix = post_config.get("summarize_suffix", "")
        self.post_min_messages = post_config.get("min_messages", 2)
        self.post_pending_preview_max_chars = post_config.get("pending_preview_max_chars", 200)
        self.post_config = post_config  # 保存完整配置
    
    def _load_graphiti_config(self, config: Dict[str, Any]):
        """加载Graphiti配置"""
        self.graphiti_config = config.get("graphiti", {})
        self.graphiti_enabled = self.graphiti_config.get("enabled", False)
        if self.graphiti_enabled:
            logging.info(f"[Graphiti] 配置已加载 (backend: {self.graphiti_config.get('backend', 'kuzu')})")
    
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
                    max_iterations=agent_config.get("max_iterations", 30),
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
            graphiti_adapter = None
            if self.graphiti_enabled:
                try:
                    from memory_store.graphiti_adapter import GraphitiAdapter
                except ImportError:
                    logging.debug("[ConversationLogger] Graphiti 适配器暂未实现")
            
            self._conversation_logger = ConversationLogger(
                lifebook_path=self.lifebook_path,
                config=self.config,
                graphiti_adapter=graphiti_adapter
            )
        
        return self._conversation_logger
    
    @property
    def summarizer(self):
        """获取对话总结器"""
        if self._summarizer is None:
            from .summarize import ConversationSummarizer
            self._summarizer = ConversationSummarizer(
                config=self.config,
                lifebook_path=self.lifebook_path,
                encoding=self.encoding
            )
        return self._summarizer
    
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
                mode=RouteModes.MANAGER,
                base_model=self.config.get("memory_agent", {}).get("model", "deepseek-reasoner"),
                enable_write=True,
                enable_main_model_tools=True
            )
        
        # 检查是否带 -memory-simple 后缀
        if model.endswith(ModelSuffixes.MEMORY_SIMPLE):
            base_model = model[:-len(ModelSuffixes.MEMORY_SIMPLE)]
            return RouteResult(
                mode=RouteModes.MEMORY,
                base_model=base_model,
                enable_write=False,
                enable_main_model_tools=False
            )
        # 检查是否带 -memory 后缀
        elif model.endswith(ModelSuffixes.MEMORY):
            base_model = model[:-len(ModelSuffixes.MEMORY)]
            return RouteResult(
                mode=RouteModes.MEMORY,
                base_model=base_model,
                enable_write=False,
                enable_main_model_tools=self.main_model_tools_enabled
            )
        # 检查是否带 -record 后缀
        elif model.endswith(ModelSuffixes.RECORD):
            base_model = model[:-len(ModelSuffixes.RECORD)]
            return RouteResult(
                mode=RouteModes.RECORD,
                base_model=base_model,
                enable_write=False,
                enable_main_model_tools=False,
                enable_summarize=True
            )
        # 检查是否带 -log-write 后缀
        elif model.endswith(ModelSuffixes.LOG_WRITE):
            base_model = model[:-len(ModelSuffixes.LOG_WRITE)]
            return RouteResult(
                mode=RouteModes.LOG_WRITE,
                base_model=base_model,
                enable_write=True,
                enable_main_model_tools=True,
                enable_summarize=False
            )
        # 检查是否带 -log 后缀
        elif model.endswith(ModelSuffixes.LOG):
            base_model = model[:-len(ModelSuffixes.LOG)]
            return RouteResult(
                mode=RouteModes.LOG,
                base_model=base_model,
                enable_write=False,
                enable_main_model_tools=False,
                enable_summarize=False
            )
        
        # 普通透传
        return RouteResult(
            mode=RouteModes.PASSTHROUGH,
            base_model=model,
            enable_write=False,
            enable_main_model_tools=False,
            enable_summarize=False
        )
    
    def get_actual_model_config(self, base_model: str) -> Dict[str, Any]:
        """获取实际模型配置"""
        self._refresh_dynamic_config()
        routes = self.model_routes or {}
        if base_model in routes:
            return routes[base_model]
        return routes.get("_default", {"use_user_key": True})
    
    def _check_has_history(self) -> Tuple[bool, int, int]:
        """
        检查是否有足够的历史记录需要搜索
        
        Returns:
            (是否需要Agent检索, 日记总数, 运行天数)
        """
        try:
            reader = LifeBookReader(self.lifebook_path, self.encoding)
            all_diaries = reader.list_all_diaries()
            diary_count = len(all_diaries)
            
            if not all_diaries:
                return False, 0, 0
            
            today = datetime.now().strftime("%Y-%m-%d")
            
            # 计算运行天数
            days_running = 0
            try:
                earliest = min(all_diaries)
                earliest_date = datetime.strptime(earliest, '%Y-%m-%d')
                days_running = (datetime.now() - earliest_date).days
            except:
                pass
            
            # 运行天数 < 7 天，短期记忆已完整覆盖
            short_term_days = self.context_config.short_term_days
            if days_running < short_term_days:
                logging.info(f"[检查历史] 运行天数 {days_running} < {short_term_days}天，短期记忆已完整覆盖")
                return False, diary_count, days_running
            
            has_past_diaries = any(d < today for d in all_diaries)
            return has_past_diaries, diary_count, days_running
            
        except Exception as e:
            logging.warning(f"[检查历史] 出错: {e}")
            return True, 0, 0
    
    def _is_search_needed(self, query: str) -> bool:
        """智能判断是否需要搜索记忆"""
        no_search_patterns = [
            r'^(你好|hi|hello|hey|嗨|哈喽)[\\s!！。.]*$',
            r'^(早上好|晚上好|下午好|早安|晚安)[\\s!！。.]*$',
            r'^测试[\\s!！。.]*$',
            r'^你是谁[\\s?？]*$',
            r'^(介绍一下)?你自己[\\s?？]*$',
        ]
        
        query_lower = query.strip().lower()
        
        for pattern in no_search_patterns:
            if re.match(pattern, query_lower, re.IGNORECASE):
                return False
        
        return True
    
    def _has_images(self, messages: List[Dict[str, Any]]) -> bool:
        """检查对话中是否包含图片内容"""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") in ("image_url", "image"):
                            return True
                break
        return False
    
    def _get_agent_recent_memory(self) -> str:
        """获取最近N天的日记内容以提供给Agent"""
        try:
            all_diaries = self.context_builder.reader.list_all_diaries()
            if all_diaries:
                earliest = min(all_diaries)
                latest = max(all_diaries)
                range_info = f"📅 记忆库范围: {earliest} ~ {latest} (共{len(all_diaries)}天记录)\n\n"
            else:
                range_info = "📅 记忆库范围: 无历史记录\n\n"
            
            parts = [range_info]
            
            days = self.context_config.short_term_days
            recent_diaries = self.context_builder.reader.read_recent_diaries(days)
            if recent_diaries:
                parts.append(f"## 最近{days}天记忆\n")
                for diary in recent_diaries:
                    max_chars = self.context_config.short_term_max_chars
                    content = diary.content[:max_chars]
                    if len(diary.content) > max_chars:
                        content += "\n... (已截断)"
                    parts.append(f"### 日期: {diary.date}\n{content}\n")
            
            # 添加今日 pending 内容
            pending_content = self._get_today_pending_for_agent()
            if pending_content:
                parts.append(pending_content)
            
            if len(parts) == 1:
                return range_info + "（最近无日记和待处理记录）"
            
            return "\n".join(parts)
        except Exception as e:
            logging.error(f"[错误] 获取Agent最近记忆失败: {e}")
            return ""
    
    def _get_today_pending_for_agent(self) -> str:
        """获取今日 pending 内容（给搜索 Agent 用）"""
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
                return ""
            
            header = f"\n## 🗒️ 今日待归档记录（{total_summaries}条，尚未写入日记）\n"
            return header + "\n".join(parts)
            
        except Exception as e:
            logging.warning(f"[Agent] 获取 pending 失败: {e}")
            return ""
    
    def _extract_query(self, messages: List[Dict[str, Any]]) -> str:
        """提取用户查询（支持多模态列表格式）"""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                
                if isinstance(content, str):
                    return content
                
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
        """提取对话上下文（用于记忆检索Agent）"""
        def process_content(content):
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            texts.append(item.get("text", ""))
                        elif item.get("type") in ["image_url", "image"]:
                            texts.append("[图片]")
                    elif isinstance(item, str):
                        texts.append(item)
                return " ".join(texts)
            elif content is None:
                return ""
            return str(content)
        
        context_messages = []
        skip_last_user = True
        
        for msg in reversed(messages):
            role = msg.get("role", "")
            if role == "user":
                if skip_last_user:
                    skip_last_user = False
                    continue
            context_messages.insert(0, msg)
        
        if not context_messages:
            return ""
        
        lines = []
        for msg in context_messages:
            role = msg.get("role", "")
            content = process_content(msg.get("content", ""))
            
            if role == "system":
                lines.append(f"[系统提示]: {content}")
            elif role == "user":
                lines.append(f"用户: {content}")
            elif role == "assistant":
                lines.append(f"助手: {content}")
        
        return "\n\n".join(lines)
    
    def process_memory_request(
        self,
        messages: List[Dict[str, Any]],
        route_result: 'RouteResult',
        user_api_key: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], AgentResult]:
        """
        处理记忆增强请求（同步版本）
        
        Args:
            messages: 原始消息列表
            route_result: 路由结果
            user_api_key: 用户API Key
            
        Returns:
            (增强后的消息, 可用工具列表, Agent结果)
        """
        query = self._extract_query(messages)
        has_history, diary_count, days_running = self._check_has_history()
        search_needed = self._is_search_needed(query)
        has_images = self._has_images(messages)
        
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
            
            agent_result = AgentResult(
                success=True,
                content=f"（{reason}，直接回复即可）",
                reasoning="",
                tool_calls=[],
                iterations=0,
                tokens_used={}
            )
        else:
            context = self._extract_context(messages)
            recent_memory = self._get_agent_recent_memory()
            if recent_memory:
                context = f"{recent_memory}\n\n[原始对话上下文]\n{context}"
            
            logging.info(f"[记忆检索] 开始检索相关记忆...")
            agent_result = self.memory_agent.retrieve(
                query=query,
                context=context,
                include_write_tools=route_result.enable_write
            )
            logging.info(f"[记忆检索] 完成，找到 {len(agent_result.tool_calls)} 次工具调用")
        
        # 组装上下文
        is_simple_mode = not route_result.enable_main_model_tools
        override_pos = self.context_config.simple_mode_insertion_position if is_simple_mode else None
        
        built = self.context_builder.build(
            messages=messages,
            dynamic_memory=agent_result.content if agent_result.success else "",
            include_fixed=True,
            override_insertion_position=override_pos
        )
        
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
            
            if tools:
                has_graphiti_tools = any(
                    t.get("function", {}).get("name", "").startswith("graphiti_")
                    for t in tools
                )
                tools_hint = self.context_builder.get_memory_tools_prompt(
                    enable_write=include_write,
                    custom_hint=self.main_model_tools_hint,
                    include_graphiti=has_graphiti_tools,
                    use_xml_tools=self.get_actual_model_config(route_result.base_model).get("use_xml_tools", False)
                )
                result_messages = self._add_tools_hint_to_messages(result_messages, tools_hint)
        
        return result_messages, tools, agent_result
    
    def process_memory_request_stream(
        self,
        messages: List[Dict[str, Any]],
        route_result: 'RouteResult',
        user_api_key: Optional[str] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """
        处理记忆增强请求（流式版本）
        
        Yields:
            {"type": "reasoning", "content": "..."} - 思维链内容
            {"type": "final", "messages": [...], "tools": [...], "agent_result": {...}} - 最终结果
        """
        query = self._extract_query(messages)
        has_history, diary_count, days_running = self._check_has_history()
        search_needed = self._is_search_needed(query)
        has_images = self._has_images(messages)
        
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
            
            built = self.context_builder.build(
                messages=messages,
                dynamic_memory="",
                include_fixed=True
            )
            
            self.metadata_manager.update_last_interaction()
            
            tools = []
            result_messages = built.messages
            if route_result.enable_main_model_tools:
                include_write = self.main_model_write_tools or route_result.enable_write
                if include_write:
                    tools = self.memory_tools_write.get_openai_tools(include_write=True)
                else:
                    tools = self.memory_tools.get_openai_tools(include_write=False)
                
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
            
            yield {
                "type": "final",
                "messages": result_messages,
                "tools": tools,
                "agent_result": agent_result
            }
            return
        
        # 需要检索
        context = self._extract_context(messages)
        recent_memory = self._get_agent_recent_memory()
        if recent_memory:
            context = f"{recent_memory}\n\n[原始对话上下文]\n{context}"
        
        yield {"type": "reasoning", "content": "🔍 正在检索相关记忆...\n\n"}
        logging.info(f"[记忆检索-流式] 开始检索相关记忆...")
        
        agent_result = None
        is_first_content = True
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
                yield {"type": "reasoning", "content": event.get("content", "")}
            elif event_type == "content":
                if is_first_content:
                    yield {"type": "reasoning", "content": "\n\n" + event.get("content", "")}
                    is_first_content = False
                else:
                    yield {"type": "reasoning", "content": event.get("content", "")}
            elif event_type == "tool_call":
                import json
                name = event.get("name", "")
                args = event.get("arguments", {})
                args_str = json.dumps(args, ensure_ascii=False)
                yield {"type": "reasoning", "content": f"\n「调用工具: {name} 参数: {args_str}」\n"}
            elif event_type == "tool_result":
                name = event.get("name", "")
                result = event.get("result", "")
                yield {"type": "reasoning", "content": f"[{name}结果] {result}\n"}
            elif event_type in ("complete", "error", "max_iterations"):
                agent_result = event.get("result")
                break
        
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
        yield {"type": "reasoning", "content": "\n\n📚 记忆检索完成，开始生成回复...\n\n"}
        
        # 组装上下文
        is_simple_mode = not route_result.enable_main_model_tools
        override_pos = self.context_config.simple_mode_insertion_position if is_simple_mode else None
        
        built = self.context_builder.build(
            messages=messages,
            dynamic_memory=agent_result.content if agent_result.success else "",
            include_fixed=True,
            override_insertion_position=override_pos
        )
        
        self.metadata_manager.update_last_interaction()
        
        tools = []
        result_messages = built.messages
        if route_result.enable_main_model_tools:
            include_write = self.main_model_write_tools or route_result.enable_write
            if include_write:
                tools = self.memory_tools_write.get_openai_tools(include_write=True)
            else:
                tools = self.memory_tools.get_openai_tools(include_write=False)
            
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
        
        Returns:
            (消息, 可用工具列表)
        """
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
        
        if messages and messages[0].get("role") == "system":
            messages = messages.copy()
            messages[0] = messages[0].copy()
            messages[0]["content"] = system_prompt + "\n\n" + messages[0]["content"]
        else:
            messages = [{"role": "system", "content": system_prompt}] + messages
        
        tools = self.memory_tools_write.get_openai_tools(include_write=True)
        return messages, tools
    
    def execute_memory_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        enable_write: bool = False
    ) -> str:
        """执行记忆工具"""
        if enable_write:
            return self.memory_tools_write.call_tool(tool_name, arguments)
        else:
            return self.memory_tools.call_tool(tool_name, arguments)
    
    def is_memory_tool(self, tool_name: str) -> bool:
        """检查是否是记忆工具"""
        memory_tool_names = {
            "search_memories", "rag_search", "read_diary", "read_summary",
            "get_node", "list_recent", "get_current_context", "get_current_time",
            "list_all_tags", "list_all_people",
            "list_nodes", "get_memory_overview", "read_all_nodes",
            "read_graph", "add_observations", "create_relations",
            "graphiti_search", "graphiti_temporal", "graphiti_add",
            "graphiti_multi_hop", "graphiti_sync_node", "graphiti_get_stats",
            "add_to_diary", "create_node", "update_node", "create_summary",
            "edit_diary", "edit_node", "edit_summary", "rewrite_diary",
            "delete_node", "delete_summary",
            "add_to_pending"
        }
        return tool_name in memory_tool_names
    
    def _add_tools_hint_to_messages(
        self,
        messages: List[Dict[str, Any]],
        tools_hint: str
    ) -> List[Dict[str, Any]]:
        """在消息中添加工具使用提示"""
        if not tools_hint:
            return messages
        
        messages = [m.copy() for m in messages]
        
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = messages[0]["content"] + "\n\n" + tools_hint
        else:
            messages.insert(0, {"role": "system", "content": tools_hint})
        
        return messages
    
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
        
        Returns:
            对话文件路径，如果禁用则返回 None
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
    
    def summarize_and_save(
        self,
        messages: List[Dict[str, Any]],
        response_content: str,
        async_mode: bool = True,
        main_model_reasoning: Optional[str] = None
    ) -> Optional[str]:
        """
        对话后总结并暂存
        
        Returns:
            如果同步执行，返回总结内容；异步执行返回None
        """
        return self.summarizer.summarize_and_save(
            messages=messages,
            response_content=response_content,
            async_mode=async_mode,
            main_model_reasoning=main_model_reasoning,
            memory_tools_write=self.memory_tools_write
        )
    
    def get_last_conversation(self) -> Optional[Tuple[List[Dict[str, Any]], str, str]]:
        """获取缓存的最后一次对话"""
        return self.summarizer.get_last_conversation()
    
    def clear_conversation_cache(self):
        """清理对话缓存"""
        self.summarizer.clear_cache()
        logging.debug("[对话缓存] 已手动清理")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取记忆系统统计"""
        return self.memory_tools.indexer.get_stats()
    
    def rebuild_index(self):
        """重建记忆索引"""
        self.memory_tools.indexer.rebuild_index()
        logging.info("记忆索引已重建")
    
    def get_virtual_models(self) -> List[Dict[str, str]]:
        """
        获取虚拟模型列表（用于 /v1/models 接口）
        
        Returns:
            虚拟模型列表
        """
        self._refresh_dynamic_config()
        virtual_models = []
        
        # 记忆管理模型
        for model_id in self.manager_model_ids:
            virtual_models.append({
                "id": model_id,
                "object": "model",
                "created": int(__import__('time').time()),
                "owned_by": "lifebook-memory"
            })
        
        # 记忆增强模型后缀
        base_models = list(self.model_routes.keys()) if self.model_routes else []
        if "_default" in base_models:
            base_models.remove("_default")
        
        # 如果没有配置，添加一些默认模型
        if not base_models:
            base_models = ["deepseek-chat", "deepseek-reasoner"]
        
        for base_model in base_models:
            # -memory 模型（完整记忆增强）
            virtual_models.append({
                "id": f"{base_model}-memory",
                "object": "model",
                "created": int(__import__('time').time()),
                "owned_by": "lifebook-memory"
            })
            # -memory-simple 模型（简单模式）
            virtual_models.append({
                "id": f"{base_model}-memory-simple",
                "object": "model",
                "created": int(__import__('time').time()),
                "owned_by": "lifebook-memory"
            })
            # -record 模型（记录模式）
            virtual_models.append({
                "id": f"{base_model}-record",
                "object": "model",
                "created": int(__import__('time').time()),
                "owned_by": "lifebook-memory"
            })
            # -log 模型（仅日志模式）
            virtual_models.append({
                "id": f"{base_model}-log",
                "object": "model",
                "created": int(__import__('time').time()),
                "owned_by": "lifebook-memory"
            })
            # -log-write 模型（日志模式 + 主模型记忆读写工具）
            virtual_models.append({
                "id": f"{base_model}-log-write",
                "object": "model",
                "created": int(__import__('time').time()),
                "owned_by": "lifebook-memory"
            })
        
        return virtual_models


# 全局路由器
_router: Optional[MemoryRouter] = None


def init_memory_router(config: Dict[str, Any]) -> MemoryRouter:
    """初始化全局路由器"""
    global _router
    _router = MemoryRouter(config)
    return _router


def get_memory_router() -> Optional[MemoryRouter]:
    """获取全局路由器"""
    return _router
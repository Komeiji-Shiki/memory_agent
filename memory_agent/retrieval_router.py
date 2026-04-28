"""
检索路由器

根据查询复杂度智能选择检索策略：
- simple: 简单查询，单次检索即可
- medium: 中等复杂度，可能需要迭代检索
- complex: 复杂查询，使用完整迭代检索

结合：
1. 复杂度分类 - 决定使用简单检索还是迭代检索
2. MemR3 迭代检索 - 处理需要多步推理的查询
3. 缓存层 - 热门查询快速响应
4. 后备策略 - 极复杂查询的降级处理
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime
import re
import logging

from .iterative_retriever import (
    IterativeRetriever,
    IterativeRetrievalResult,
    create_iterative_retriever
)

# 导入缓存模块
try:
    from memory_store.retrieval_cache import (
        RetrievalCache,
        CacheConfig,
        CacheWarmer,
        create_retrieval_cache,
    )
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False

logger = logging.getLogger(__name__)


class QueryComplexity(Enum):
    """查询复杂度级别"""
    SIMPLE = "simple"      # 简单：精确查找、是非问题
    MEDIUM = "medium"      # 中等：需要一些推理
    COMPLEX = "complex"    # 复杂：多跳推理、时间计算、比较分析


class RetrievalStrategy(Enum):
    """检索策略"""
    SINGLE = "single"          # 单次检索
    ITERATIVE = "iterative"    # 迭代检索
    AGENT = "agent"            # Agent 深度检索（预留）


@dataclass
class RouterConfig:
    """路由器配置"""
    # 复杂度判断阈值
    simple_max_length: int = 15        # 查询长度 <= 此值可能是简单查询
    complex_min_length: int = 50       # 查询长度 >= 此值可能是复杂查询
    
    # 迭代检索配置
    max_iterations: int = 3            # 最大迭代次数
    min_evidence_count: int = 2        # 最少证据数量
    
    # 策略选择
    default_strategy: str = "auto"     # auto | single | iterative
    enable_llm_reflect: bool = False   # 是否启用 LLM 反思（成本较高）
    
    # 后备配置
    fallback_on_error: bool = True     # 出错时是否降级到简单检索
    
    # 缓存配置
    cache_enabled: bool = True         # 是否启用缓存
    cache_ttl_seconds: int = 300       # 缓存过期时间（秒）
    cache_max_size: int = 1000         # 最大缓存条目数
    cache_normalize_queries: bool = True  # 查询规范化


@dataclass
class RoutingResult:
    """路由结果"""
    evidence: List[Dict]
    evidence_summary: str
    iterations: int
    strategy: str
    complexity: str
    gaps: List[str] = field(default_factory=list)
    refined_queries: List[str] = field(default_factory=list)
    agent_supplement: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
    cached: bool = False  # 是否来自缓存


class RetrievalRouter:
    """
    检索路由器
    
    智能选择检索策略，结合：
    - 复杂度分类
    - 迭代检索
    - 缓存加速
    - 成本控制
    """
    
    def __init__(
        self,
        graphiti_adapter,
        config: Optional[RouterConfig] = None,
        llm_client=None,
        cache: Optional[Any] = None,
    ):
        """
        初始化路由器
        
        Args:
            graphiti_adapter: Graphiti 适配器
            config: 路由器配置
            llm_client: LLM 客户端（可选，用于迭代检索的反思）
            cache: 缓存实例（可选，不传则根据配置自动创建）
        """
        self.graphiti = graphiti_adapter
        self.config = config or RouterConfig()
        self.llm = llm_client
        
        # 创建迭代检索器
        self.iterative_retriever = IterativeRetriever(
            graphiti_adapter=graphiti_adapter,
            llm_client=llm_client,
            max_iterations=self.config.max_iterations,
            min_evidence_count=self.config.min_evidence_count,
            enable_llm_reflect=self.config.enable_llm_reflect
        )
        
        # 初始化缓存
        self._cache: Optional[RetrievalCache] = None
        self._cache_warmer: Optional[CacheWarmer] = None
        
        if self.config.cache_enabled and CACHE_AVAILABLE:
            if cache is not None:
                self._cache = cache
            else:
                cache_config = CacheConfig(
                    ttl_seconds=self.config.cache_ttl_seconds,
                    max_size=self.config.cache_max_size,
                    normalize_queries=self.config.cache_normalize_queries,
                )
                self._cache = RetrievalCache(config=cache_config)
            
            # 创建预热器
            self._cache_warmer = CacheWarmer(
                cache=self._cache,
                graphiti_adapter=graphiti_adapter,
            )
            
            logger.info(f"[Router] 缓存已启用: TTL={self.config.cache_ttl_seconds}s, max_size={self.config.cache_max_size}")
        elif self.config.cache_enabled and not CACHE_AVAILABLE:
            logger.warning("[Router] 缓存配置已启用但模块不可用")
        
        # 复杂查询模式（用于复杂度判断）
        self._complex_patterns = [
            r"(为什么|怎么|如何)",           # 因果/方法
            r"(比较|对比|区别|不同|相同)",    # 比较
            r"(和|以及|还有).*什么",          # 多部分
            r"(变化|发展|演化|历史|过程)",    # 时序演化
            r"(关系|联系|相关|影响)",         # 深层关系
            r"(总结|分析|评价|评估)",         # 综合分析
            r"(多久|多长时间|持续)",          # 时间计算
            r"(都有|有哪些|所有)",            # 列举
        ]
        
        # 简单查询模式
        self._simple_patterns = [
            r"^.{0,15}是(谁|什么)$",          # "xxx是谁/什么"
            r"^\d{4}[-年]?\d{0,2}",            # 日期开头
            r"^(有没有|是否|能不能)",          # 是非问题
            r"^(查|搜|找).{0,10}$",            # 短查询
            r"^(读|看|打开)",                 # 读取命令
        ]
    
    def retrieve(
        self,
        query: str,
        context: str = "",
        force_strategy: Optional[str] = None,
        num_results: int = 10
    ) -> RoutingResult:
        """
        智能检索入口
        
        Args:
            query: 用户查询
            context: 上下文（如对话历史）
            force_strategy: 强制策略 ("single" | "iterative")
            num_results: 期望返回的结果数
        
        Returns:
            RoutingResult
        """
        # 强制策略
        if force_strategy == "single":
            return self._single_retrieve(query, num_results, "forced_single")
        elif force_strategy == "iterative":
            return self._iterative_retrieve(query, context, "forced_iterative")
        
        # 自动判断复杂度
        complexity = self._classify_complexity(query)
        logger.info(f"[Router] 查询复杂度: {complexity.value}, query='{query[:50]}...'")
        
        try:
            if complexity == QueryComplexity.SIMPLE:
                return self._single_retrieve(query, num_results, complexity.value)
            
            elif complexity == QueryComplexity.MEDIUM:
                # 中等复杂度：尝试迭代检索，但限制迭代次数
                result = self._iterative_retrieve(query, context, complexity.value)
                
                # 如果迭代检索效果不好，补充简单检索结果
                if len(result.evidence) < 2:
                    simple_result = self._single_retrieve(query, num_results, "supplement")
                    result.evidence.extend(simple_result.evidence)
                    result.evidence_summary += "\n" + simple_result.evidence_summary
                
                return result
            
            else:  # COMPLEX
                # 复杂查询：完整迭代检索
                result = self._iterative_retrieve(query, context, complexity.value)
                
                # 如果仍有未解决的 gaps，记录下来
                if result.gaps:
                    logger.warning(f"[Router] 复杂查询仍有 {len(result.gaps)} 个信息缺口")
                
                return result
                
        except Exception as e:
            logger.error(f"[Router] 检索出错: {e}")
            
            if self.config.fallback_on_error:
                logger.info("[Router] 降级到简单检索")
                return self._single_retrieve(query, num_results, "fallback")
            
            return RoutingResult(
                evidence=[],
                evidence_summary=f"检索失败: {e}",
                iterations=0,
                strategy="error",
                complexity="unknown",
                success=False,
                error=str(e)
            )
    
    async def retrieve_async(
        self,
        query: str,
        context: str = "",
        force_strategy: Optional[str] = None,
        num_results: int = 10
    ) -> RoutingResult:
        """智能检索入口（异步版本）"""
        if force_strategy == "single":
            return await self._single_retrieve_async(query, num_results, "forced_single")
        elif force_strategy == "iterative":
            return await self._iterative_retrieve_async(query, context, "forced_iterative")
        
        complexity = self._classify_complexity(query)
        
        try:
            if complexity == QueryComplexity.SIMPLE:
                return await self._single_retrieve_async(query, num_results, complexity.value)
            elif complexity == QueryComplexity.MEDIUM:
                result = await self._iterative_retrieve_async(query, context, complexity.value)
                if len(result.evidence) < 2:
                    simple_result = await self._single_retrieve_async(query, num_results, "supplement")
                    result.evidence.extend(simple_result.evidence)
                    result.evidence_summary += "\n" + simple_result.evidence_summary
                return result
            else:
                return await self._iterative_retrieve_async(query, context, complexity.value)
                
        except Exception as e:
            logger.error(f"[Router] 异步检索出错: {e}")
            if self.config.fallback_on_error:
                return await self._single_retrieve_async(query, num_results, "fallback")
            return RoutingResult(
                evidence=[],
                evidence_summary=f"检索失败: {e}",
                iterations=0,
                strategy="error",
                complexity="unknown",
                success=False,
                error=str(e)
            )
    
    def _single_retrieve(
        self,
        query: str,
        num_results: int,
        complexity: str
    ) -> RoutingResult:
        """单次检索（同步），支持缓存"""
        # 尝试从缓存获取
        if self._cache is not None:
            cached_evidence = self._cache.get(query)
            if cached_evidence is not None:
                logger.debug(f"[Router] 缓存命中: '{query[:30]}...'")
                return RoutingResult(
                    evidence=cached_evidence,
                    evidence_summary=self._format_evidence_summary(cached_evidence),
                    iterations=0,
                    strategy="cached",
                    complexity=complexity,
                    success=True,
                    cached=True,
                )
        
        try:
            results = self.graphiti.search(query, num_results=num_results)
            
            # 标准化结果
            evidence = []
            for r in results:
                if isinstance(r, dict):
                    evidence.append(r)
                else:
                    evidence.append({
                        "content": getattr(r, "content", "") or getattr(r, "fact", str(r)),
                        "source": getattr(r, "source", "graphiti"),
                        "score": getattr(r, "score", 1.0),
                        "valid_at": getattr(r, "valid_at", None),
                    })
            
            # 缓存结果
            if self._cache is not None and evidence:
                self._cache.set(query, evidence)
            
            # 构建摘要
            summary = self._format_evidence_summary(evidence)
            
            return RoutingResult(
                evidence=evidence,
                evidence_summary=summary,
                iterations=1,
                strategy="single",
                complexity=complexity,
                success=True,
                cached=False,
            )
            
        except Exception as e:
            logger.error(f"[Router] 单次检索失败: {e}")
            return RoutingResult(
                evidence=[],
                evidence_summary=f"检索失败: {e}",
                iterations=0,
                strategy="single",
                complexity=complexity,
                success=False,
                error=str(e)
            )
    
    async def _single_retrieve_async(
        self,
        query: str,
        num_results: int,
        complexity: str
    ) -> RoutingResult:
        """单次检索（异步），支持缓存"""
        # 尝试从缓存获取
        if self._cache is not None:
            cached_evidence = self._cache.get(query)
            if cached_evidence is not None:
                logger.debug(f"[Router] 缓存命中: '{query[:30]}...'")
                return RoutingResult(
                    evidence=cached_evidence,
                    evidence_summary=self._format_evidence_summary(cached_evidence),
                    iterations=0,
                    strategy="cached",
                    complexity=complexity,
                    success=True,
                    cached=True,
                )
        
        try:
            results = await self.graphiti.search(query, num_results=num_results)
            
            evidence = []
            for r in results:
                if isinstance(r, dict):
                    evidence.append(r)
                else:
                    evidence.append({
                        "content": getattr(r, "content", "") or getattr(r, "fact", str(r)),
                        "source": getattr(r, "source", "graphiti"),
                        "score": getattr(r, "score", 1.0),
                        "valid_at": getattr(r, "valid_at", None),
                    })
            
            # 缓存结果
            if self._cache is not None and evidence:
                self._cache.set(query, evidence)
            
            summary = self._format_evidence_summary(evidence)
            
            return RoutingResult(
                evidence=evidence,
                evidence_summary=summary,
                iterations=1,
                strategy="single",
                complexity=complexity,
                success=True,
                cached=False,
            )
            
        except Exception as e:
            return RoutingResult(
                evidence=[],
                evidence_summary=f"检索失败: {e}",
                iterations=0,
                strategy="single",
                complexity=complexity,
                success=False,
                error=str(e)
            )
    
    def _iterative_retrieve(
        self,
        query: str,
        context: str,
        complexity: str
    ) -> RoutingResult:
        """迭代检索（同步）"""
        result = self.iterative_retriever.retrieve(query, context)
        
        return RoutingResult(
            evidence=result.evidence,
            evidence_summary=self._format_evidence_summary(result.evidence),
            iterations=result.iterations,
            strategy="iterative",
            complexity=complexity,
            gaps=result.gaps,
            refined_queries=result.refined_queries,
            success=result.success,
            error=result.error
        )
    
    async def _iterative_retrieve_async(
        self,
        query: str,
        context: str,
        complexity: str
    ) -> RoutingResult:
        """迭代检索（异步）"""
        result = await self.iterative_retriever.retrieve_async(query, context)
        
        return RoutingResult(
            evidence=result.evidence,
            evidence_summary=self._format_evidence_summary(result.evidence),
            iterations=result.iterations,
            strategy="iterative",
            complexity=complexity,
            gaps=result.gaps,
            refined_queries=result.refined_queries,
            success=result.success,
            error=result.error
        )
    
    def _classify_complexity(self, query: str) -> QueryComplexity:
        """
        分类查询复杂度
        
        基于：
        - 查询长度
        - 模式匹配
        - 关键词检测
        """
        query_clean = query.strip()
        
        # 检查简单模式
        for pattern in self._simple_patterns:
            if re.search(pattern, query_clean):
                return QueryComplexity.SIMPLE
        
        # 检查复杂模式
        complex_score = 0
        for pattern in self._complex_patterns:
            if re.search(pattern, query_clean):
                complex_score += 1
        
        # 多个复杂模式匹配 -> 复杂
        if complex_score >= 2:
            return QueryComplexity.COMPLEX
        
        # 单个复杂模式 -> 中等
        if complex_score == 1:
            return QueryComplexity.MEDIUM
        
        # 按长度判断
        query_len = len(query_clean)
        
        if query_len <= self.config.simple_max_length:
            return QueryComplexity.SIMPLE
        elif query_len >= self.config.complex_min_length:
            return QueryComplexity.COMPLEX
        else:
            return QueryComplexity.MEDIUM
    
    def _format_evidence_summary(
        self,
        evidence: List[Dict],
        max_items: int = 10,
        max_content_len: int = 200
    ) -> str:
        """格式化证据摘要"""
        if not evidence:
            return "未找到相关记忆。"
        
        lines = [f"## 📚 相关记忆（共 {len(evidence)} 条）\n"]
        
        for i, e in enumerate(evidence[:max_items], 1):
            content = e.get("content", "") or e.get("fact", "")
            if len(content) > max_content_len:
                content = content[:max_content_len] + "..."
            
            source = e.get("source", "unknown")
            score = e.get("score", 0)
            
            # 时序信息
            valid_at = e.get("valid_at")
            time_str = ""
            if valid_at:
                if hasattr(valid_at, 'strftime'):
                    time_str = f" ({valid_at.strftime('%Y-%m-%d')})"
                else:
                    time_str = f" ({str(valid_at)[:10]})"
            
            lines.append(f"{i}. [{source}]{time_str} {content}")
            lines.append(f"   相关度: {score:.2f}")
            lines.append("")
        
        if len(evidence) > max_items:
            lines.append(f"... 还有 {len(evidence) - max_items} 条结果")
        
        return "\n".join(lines)
    
    def format_result_for_context(self, result: RoutingResult) -> str:
        """
        将路由结果格式化为上下文（供主模型使用）
        
        Args:
            result: 路由结果
            
        Returns:
            格式化的记忆上下文
        """
        output = result.evidence_summary
        
        # 添加检索元信息
        if result.iterations > 1:
            output += f"\n\n*（经过 {result.iterations} 轮迭代检索，策略: {result.strategy}）*"
        
        if result.cached:
            output += f"\n*（来自缓存）*"
        
        if result.gaps:
            output += f"\n*（未解决的信息缺口: {', '.join(result.gaps[:3])}）*"
        
        if result.agent_supplement:
            output += f"\n\n### 深度分析\n{result.agent_supplement}"
        
        return output
    
    # ==================== 缓存管理方法 ====================
    
    def warmup_cache(self, num_results: int = 5) -> Dict[str, int]:
        """
        预热缓存
        
        Args:
            num_results: 每个查询获取的结果数
            
        Returns:
            预热统计 {query: result_count}
        """
        if self._cache_warmer is None:
            logger.warning("[Router] 缓存预热器不可用")
            return {}
        
        return self._cache_warmer.warmup(num_results)
    
    async def warmup_cache_async(self, num_results: int = 5) -> Dict[str, int]:
        """异步预热缓存"""
        if self._cache_warmer is None:
            return {}
        
        return await self._cache_warmer.warmup_async(num_results)
    
    def add_warmup_query(self, query: str):
        """添加预热查询"""
        if self._cache_warmer is not None:
            self._cache_warmer.add_query(query)
    
    def get_cache_stats(self) -> Optional[Dict]:
        """获取缓存统计"""
        if self._cache is None:
            return None
        
        return self._cache.stats
    
    def clear_cache(self):
        """清空缓存"""
        if self._cache is not None:
            self._cache.clear()
            logger.info("[Router] 缓存已清空")
    
    def invalidate_cache(self, query: str) -> bool:
        """使特定查询的缓存失效"""
        if self._cache is not None:
            return self._cache.invalidate(query)
        return False
    
    @property
    def cache_size(self) -> int:
        """当前缓存大小"""
        if self._cache is not None:
            return self._cache.size
        return 0


# ==================== 工厂函数 ====================

def create_retrieval_router(
    graphiti_adapter,
    config: Optional[Dict[str, Any]] = None,
    llm_client=None,
    cache: Optional[Any] = None,
) -> RetrievalRouter:
    """
    创建检索路由器的工厂函数
    
    Args:
        graphiti_adapter: Graphiti 适配器
        config: 配置字典（支持嵌套的 cache 子配置）
        llm_client: LLM 客户端
        cache: 外部传入的缓存实例（可选）
    
    Returns:
        RetrievalRouter 实例
    """
    router_config = RouterConfig()
    
    if config:
        router_config.simple_max_length = config.get("simple_max_length", 15)
        router_config.complex_min_length = config.get("complex_min_length", 50)
        router_config.max_iterations = config.get("max_iterations", 3)
        router_config.min_evidence_count = config.get("min_evidence_count", 2)
        router_config.default_strategy = config.get("default_strategy", "auto")
        router_config.enable_llm_reflect = config.get("enable_llm_reflect", False)
        router_config.fallback_on_error = config.get("fallback_on_error", True)
        
        # 缓存配置
        cache_config = config.get("cache", {})
        router_config.cache_enabled = cache_config.get("enabled", True)
        router_config.cache_ttl_seconds = cache_config.get("ttl_seconds", 300)
        router_config.cache_max_size = cache_config.get("max_size", 1000)
        router_config.cache_normalize_queries = cache_config.get("normalize_queries", True)
    
    return RetrievalRouter(
        graphiti_adapter=graphiti_adapter,
        config=router_config,
        llm_client=llm_client,
        cache=cache,
    )
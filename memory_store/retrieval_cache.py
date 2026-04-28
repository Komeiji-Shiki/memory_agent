"""
检索结果缓存

优雅实现的缓存层，支持：
- TTL（生存时间）过期
- LRU（最近最少使用）淘汰
- 查询规范化（相似查询命中同一缓存）
- 泛型类型支持
- 线程安全
- 统计信息收集
- 预热机制（支持并行）
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import wraps
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Protocol,
    Tuple,
    TypeVar,
    Union,
)

# 导入异步工具
try:
    from .async_utils import parallel_tasks, warmup_cache_async
except ImportError:
    # 兼容直接运行
    pass

logger = logging.getLogger(__name__)

# ============================================================================
# 类型定义
# ============================================================================

T = TypeVar("T")  # 缓存值类型
K = TypeVar("K")  # 缓存键类型


@dataclass(frozen=True)
class CacheConfig:
    """缓存配置（不可变）"""
    # 基础配置
    ttl_seconds: int = 300          # 默认5分钟过期
    max_size: int = 1000            # 最大缓存条目数
    
    # 清理策略
    cleanup_interval: int = 60      # 自动清理间隔（秒）
    cleanup_batch_size: int = 100   # 每次清理的最大条目数
    
    # 查询规范化
    normalize_queries: bool = True  # 是否规范化查询
    case_insensitive: bool = True   # 忽略大小写
    
    # 统计
    enable_stats: bool = True       # 是否启用统计
    
    @classmethod
    def from_dict(cls, config: Dict) -> CacheConfig:
        """从字典创建配置"""
        cache_config = config.get("cache", {})
        return cls(
            ttl_seconds=cache_config.get("ttl_seconds", 300),
            max_size=cache_config.get("max_size", 1000),
            cleanup_interval=cache_config.get("cleanup_interval", 60),
            cleanup_batch_size=cache_config.get("cleanup_batch_size", 100),
            normalize_queries=cache_config.get("normalize_queries", True),
            case_insensitive=cache_config.get("case_insensitive", True),
            enable_stats=cache_config.get("enable_stats", True),
        )


@dataclass
class CacheEntry(Generic[T]):
    """缓存条目"""
    value: T
    created_at: float           # 创建时间戳
    expires_at: float           # 过期时间戳
    access_count: int = 0       # 访问次数
    last_accessed: float = 0    # 最后访问时间戳
    version: int = 0            # 版本号（用于失效检测）
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() > self.expires_at
    
    def touch(self):
        """更新访问信息"""
        self.access_count += 1
        self.last_accessed = time.time()


@dataclass
class CacheStats:
    """缓存统计"""
    hits: int = 0               # 命中次数
    misses: int = 0             # 未命中次数
    evictions: int = 0          # 淘汰次数
    expirations: int = 0        # 过期清理次数
    total_queries: int = 0      # 总查询次数
    
    @property
    def hit_rate(self) -> float:
        """命中率"""
        if self.total_queries == 0:
            return 0.0
        return self.hits / self.total_queries
    
    def record_hit(self):
        self.hits += 1
        self.total_queries += 1
    
    def record_miss(self):
        self.misses += 1
        self.total_queries += 1
    
    def to_dict(self) -> Dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "total_queries": self.total_queries,
            "hit_rate": f"{self.hit_rate:.2%}",
        }


# ============================================================================
# 查询规范化器
# ============================================================================

class QueryNormalizer:
    """
    查询规范化器
    
    将相似的查询映射到同一个缓存键，提高缓存命中率。
    
    规范化策略：
    1. 去除首尾空白
    2. 统一大小写
    3. 去除标点符号
    4. 压缩连续空白
    5. 中文分词规范化（可选）
    """
    
    # 常见停用词（可扩展）
    STOP_WORDS = {
        "的", "了", "是", "在", "我", "有", "和", "就",
        "不", "人", "都", "一", "一个", "上", "也", "很",
        "到", "说", "要", "去", "你", "会", "着", "没有",
        "看", "好", "自己", "这", "那", "什么", "吗", "啊",
    }
    
    # 标点符号模式
    PUNCTUATION_PATTERN = re.compile(r'[^\w\s\u4e00-\u9fff]')
    WHITESPACE_PATTERN = re.compile(r'\s+')
    
    def __init__(
        self,
        case_insensitive: bool = True,
        remove_punctuation: bool = True,
        remove_stop_words: bool = False,
    ):
        self.case_insensitive = case_insensitive
        self.remove_punctuation = remove_punctuation
        self.remove_stop_words = remove_stop_words
    
    def normalize(self, query: str) -> str:
        """规范化查询字符串"""
        result = query.strip()
        
        if self.case_insensitive:
            result = result.lower()
        
        if self.remove_punctuation:
            result = self.PUNCTUATION_PATTERN.sub(' ', result)
        
        # 压缩空白
        result = self.WHITESPACE_PATTERN.sub(' ', result).strip()
        
        if self.remove_stop_words:
            words = result.split()
            words = [w for w in words if w not in self.STOP_WORDS]
            result = ' '.join(words)
        
        return result
    
    def make_key(self, query: str) -> str:
        """生成缓存键"""
        normalized = self.normalize(query)
        # 使用 MD5 作为键（短且快）
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()


# ============================================================================
# 核心缓存实现
# ============================================================================

class Cache(Generic[K, T], ABC):
    """缓存抽象基类"""
    
    @abstractmethod
    def get(self, key: K) -> Optional[T]:
        """获取缓存值"""
        ...
    
    @abstractmethod
    def set(self, key: K, value: T, ttl: Optional[int] = None):
        """设置缓存值"""
        ...
    
    @abstractmethod
    def delete(self, key: K) -> bool:
        """删除缓存值"""
        ...
    
    @abstractmethod
    def clear(self):
        """清空缓存"""
        ...
    
    @abstractmethod
    def size(self) -> int:
        """当前缓存大小"""
        ...


class LRUTTLCache(Cache[str, T]):
    """
    LRU + TTL 双重淘汰缓存
    
    特性：
    - 基于 OrderedDict 实现 O(1) LRU
    - TTL 过期自动清理
    - 版本号失效机制
    - 线程安全（使用锁）
    - 统计信息收集
    """
    
    def __init__(self, config: Optional[CacheConfig] = None):
        self.config = config or CacheConfig()
        self._cache: OrderedDict[str, CacheEntry[T]] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = CacheStats() if self.config.enable_stats else None
        
        # 后台清理
        self._cleanup_task: Optional[asyncio.Task] = None
        self._last_cleanup = time.time()
        
        # 全局版本号（每次图谱更新时递增）
        self._global_version: int = 0
    
    def get(self, key: str) -> Optional[T]:
        """
        获取缓存值
        
        命中时移动到末尾（LRU）
        过期或版本过时时返回 None 并删除
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                if self._stats:
                    self._stats.record_miss()
                return None
            
            # 检查过期
            if entry.is_expired():
                del self._cache[key]
                if self._stats:
                    self._stats.record_miss()
                    self._stats.expirations += 1
                return None
            
            # 检查版本（图谱更新后旧缓存失效）
            if entry.version < self._global_version:
                del self._cache[key]
                if self._stats:
                    self._stats.record_miss()
                    self._stats.expirations += 1
                return None
            
            # 命中：更新访问信息，移动到末尾
            entry.touch()
            self._cache.move_to_end(key)
            
            if self._stats:
                self._stats.record_hit()
            
            return entry.value
    
    def set(self, key: str, value: T, ttl: Optional[int] = None):
        """
        设置缓存值
        
        超过容量时淘汰最旧的条目
        """
        ttl = ttl or self.config.ttl_seconds
        now = time.time()
        
        entry = CacheEntry(
            value=value,
            created_at=now,
            expires_at=now + ttl,
            last_accessed=now,
            version=self._global_version,  # 记录当前版本
        )
        
        with self._lock:
            # 如果键已存在，先删除（保证顺序）
            if key in self._cache:
                del self._cache[key]
            
            # 容量检查
            while len(self._cache) >= self.config.max_size:
                # 淘汰最旧的（头部）
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                if self._stats:
                    self._stats.evictions += 1
            
            self._cache[key] = entry
    
    def delete(self, key: str) -> bool:
        """删除缓存值"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
    
    def size(self) -> int:
        """当前缓存大小"""
        return len(self._cache)
    
    def cleanup_expired(self) -> int:
        """
        清理过期条目
        
        Returns:
            清理的条目数
        """
        cleaned = 0
        now = time.time()
        
        with self._lock:
            # 收集过期的键
            expired_keys = []
            for key, entry in self._cache.items():
                if entry.is_expired():
                    expired_keys.append(key)
                    if len(expired_keys) >= self.config.cleanup_batch_size:
                        break
            
            # 删除
            for key in expired_keys:
                del self._cache[key]
                cleaned += 1
            
            if self._stats:
                self._stats.expirations += cleaned
        
        self._last_cleanup = now
        
        if cleaned > 0:
            logger.debug(f"Cache cleanup: removed {cleaned} expired entries")
        
        return cleaned
    
    def get_stats(self) -> Optional[Dict]:
        """获取统计信息"""
        if self._stats is None:
            return None
        
        stats = self._stats.to_dict()
        stats["size"] = self.size()
        stats["max_size"] = self.config.max_size
        
        return stats
    
    def reset_stats(self):
        """重置统计"""
        if self._stats:
            self._stats = CacheStats()
    
    def increment_version(self):
        """
        递增全局版本号
        
        调用后，所有旧版本的缓存条目将被视为无效。
        应在图谱更新（add_episode）后调用。
        """
        with self._lock:
            self._global_version += 1
            logger.debug(f"Cache version incremented to {self._global_version}")
    
    @property
    def version(self) -> int:
        """当前全局版本号"""
        return self._global_version


# ============================================================================
# 检索缓存（高级封装）
# ============================================================================

class RetrievalCache:
    """
    检索结果缓存
    
    针对 Graphiti/RAG 检索优化的缓存层：
    - 查询规范化
    - 结果序列化
    - 异步支持
    - 预热机制
    """
    
    def __init__(
        self,
        config: Optional[CacheConfig] = None,
        normalizer: Optional[QueryNormalizer] = None,
    ):
        self.config = config or CacheConfig()
        self._cache: LRUTTLCache[List[Dict]] = LRUTTLCache(self.config)
        self._normalizer = normalizer or QueryNormalizer(
            case_insensitive=self.config.case_insensitive,
        )
    
    def get(self, query: str) -> Optional[List[Dict]]:
        """
        获取缓存的检索结果
        
        Args:
            query: 原始查询
            
        Returns:
            缓存的结果列表，未命中返回 None
        """
        if not self.config.normalize_queries:
            return self._cache.get(query)
        
        key = self._normalizer.make_key(query)
        return self._cache.get(key)
    
    def set(
        self,
        query: str,
        results: List[Dict],
        ttl: Optional[int] = None
    ):
        """
        缓存检索结果
        
        Args:
            query: 原始查询
            results: 检索结果
            ttl: 可选的自定义 TTL
        """
        if not self.config.normalize_queries:
            self._cache.set(query, results, ttl)
            return
        
        key = self._normalizer.make_key(query)
        self._cache.set(key, results, ttl)
    
    def get_or_fetch(
        self,
        query: str,
        fetch_fn: Callable[[], List[Dict]],
        ttl: Optional[int] = None
    ) -> List[Dict]:
        """
        获取缓存，未命中时调用 fetch_fn 获取并缓存
        
        Args:
            query: 查询
            fetch_fn: 获取数据的函数
            ttl: 可选的 TTL
            
        Returns:
            检索结果
        """
        cached = self.get(query)
        if cached is not None:
            return cached
        
        results = fetch_fn()
        self.set(query, results, ttl)
        return results
    
    async def get_or_fetch_async(
        self,
        query: str,
        fetch_fn: Callable[[], Any],  # 可以是协程函数
        ttl: Optional[int] = None
    ) -> List[Dict]:
        """
        异步版本的 get_or_fetch
        """
        cached = self.get(query)
        if cached is not None:
            return cached
        
        if asyncio.iscoroutinefunction(fetch_fn):
            results = await fetch_fn()
        else:
            results = fetch_fn()
        
        self.set(query, results, ttl)
        return results
    
    def invalidate(self, query: str) -> bool:
        """使特定查询的缓存失效"""
        if not self.config.normalize_queries:
            return self._cache.delete(query)
        
        key = self._normalizer.make_key(query)
        return self._cache.delete(key)
    
    def clear(self):
        """清空所有缓存"""
        self._cache.clear()
    
    def cleanup(self) -> int:
        """清理过期缓存"""
        return self._cache.cleanup_expired()
    
    @property
    def stats(self) -> Optional[Dict]:
        """获取统计信息"""
        return self._cache.get_stats()
    
    @property
    def size(self) -> int:
        """当前缓存大小"""
        return self._cache.size()
    
    def on_graph_updated(self):
        """
        图谱更新通知
        
        当 add_episode 或其他修改图谱的操作完成后调用，
        使所有旧版本的缓存失效。
        """
        self._cache.increment_version()
        logger.info(f"[Cache] 图谱更新，缓存版本递增到 {self._cache.version}")
    
    @property
    def version(self) -> int:
        """当前缓存版本"""
        return self._cache.version


# ============================================================================
# 缓存预热器
# ============================================================================

class CacheWarmer:
    """
    缓存预热器
    
    在系统启动时预先加载常见查询的结果到缓存中。
    支持并行预热以加速启动过程。
    """
    
    # 默认预热查询（常见实体）
    DEFAULT_WARMUP_QUERIES = [
        "主人",
        "灰魂",
        "LifeBook",
        "记忆系统",
        "最近的项目",
        "今天",
    ]
    
    def __init__(
        self,
        cache: RetrievalCache,
        graphiti_adapter: Any = None,
        custom_queries: Optional[List[str]] = None,
        max_concurrent: int = 3,
    ):
        self.cache = cache
        self.graphiti = graphiti_adapter
        self.warmup_queries = custom_queries or self.DEFAULT_WARMUP_QUERIES.copy()
        self.max_concurrent = max_concurrent
        
        self._warmed = False
        self._warmup_results: Dict[str, int] = {}  # query -> result_count
    
    def add_query(self, query: str):
        """添加预热查询"""
        if query not in self.warmup_queries:
            self.warmup_queries.append(query)
    
    def warmup(self, num_results: int = 5) -> Dict[str, int]:
        """
        同步预热（串行执行，向后兼容）
        
        Args:
            num_results: 每个查询获取的结果数
            
        Returns:
            {query: result_count} 预热结果统计
        """
        if not self.graphiti:
            logger.warning("CacheWarmer: no graphiti adapter provided")
            return {}
        
        results = {}
        
        for query in self.warmup_queries:
            try:
                search_results = self.graphiti.search(query, num_results=num_results)
                if search_results:
                    self.cache.set(query, search_results)
                    results[query] = len(search_results)
                else:
                    results[query] = 0
            except Exception as e:
                logger.warning(f"CacheWarmer: failed to warm '{query}': {e}")
                results[query] = -1
        
        self._warmed = True
        self._warmup_results = results
        
        success_count = sum(1 for v in results.values() if v > 0)
        logger.info(f"Cache warmup complete: {success_count}/{len(results)} queries cached")
        
        return results
    
    async def warmup_async(self, num_results: int = 5) -> Dict[str, int]:
        """
        异步预热（并行执行）
        
        使用 asyncio 并行预热所有查询，大幅提升启动速度。
        
        Args:
            num_results: 每个查询获取的结果数
            
        Returns:
            {query: result_count} 预热结果统计
        """
        if not self.graphiti:
            logger.warning("CacheWarmer: no graphiti adapter provided")
            return {}
        
        # 定义搜索函数
        def search_fn(query: str) -> List[Dict]:
            return self.graphiti.search(query, num_results=num_results)
        
        # 定义缓存设置函数
        def cache_set_fn(query: str, results: List[Dict]) -> None:
            self.cache.set(query, results)
        
        # 使用异步工具并行预热
        try:
            self._warmup_results = await warmup_cache_async(
                queries=self.warmup_queries,
                search_fn=search_fn,
                cache_set_fn=cache_set_fn,
                max_concurrent=self.max_concurrent
            )
        except NameError:
            # 如果 async_utils 不可用，回退到串行
            logger.warning("Async utils not available, falling back to serial warmup")
            return self.warmup(num_results)
        
        self._warmed = True
        
        success_count = sum(1 for v in self._warmup_results.values() if v > 0)
        logger.info(f"Async cache warmup complete: {success_count}/{len(self._warmup_results)} queries cached")
        
        return self._warmup_results
    
    @property
    def is_warmed(self) -> bool:
        """是否已完成预热"""
        return self._warmed
    
    @property
    def warmup_stats(self) -> Dict[str, Any]:
        """预热统计"""
        return {
            "is_warmed": self._warmed,
            "queries_count": len(self.warmup_queries),
            "results": self._warmup_results,
            "max_concurrent": self.max_concurrent,
        }


# ============================================================================
# 缓存装饰器
# ============================================================================

def cached(
    cache: RetrievalCache,
    key_fn: Optional[Callable[..., str]] = None,
    ttl: Optional[int] = None,
):
    """
    缓存装饰器
    
    用于装饰检索函数，自动缓存结果。
    
    Usage:
        @cached(cache, key_fn=lambda query, **kw: query)
        def search(query: str, num_results: int = 10):
            ...
    """
    def decorator(fn: Callable[..., List[Dict]]):
        @wraps(fn)
        def wrapper(*args, **kwargs) -> List[Dict]:
            # 生成缓存键
            if key_fn:
                key = key_fn(*args, **kwargs)
            else:
                # 默认使用第一个参数作为键
                key = str(args[0]) if args else str(kwargs)
            
            # 尝试获取缓存
            cached_result = cache.get(key)
            if cached_result is not None:
                return cached_result
            
            # 调用原函数
            result = fn(*args, **kwargs)
            
            # 缓存结果
            cache.set(key, result, ttl)
            
            return result
        
        return wrapper
    
    return decorator


def cached_async(
    cache: RetrievalCache,
    key_fn: Optional[Callable[..., str]] = None,
    ttl: Optional[int] = None,
):
    """异步版本的缓存装饰器"""
    def decorator(fn: Callable):
        @wraps(fn)
        async def wrapper(*args, **kwargs) -> List[Dict]:
            if key_fn:
                key = key_fn(*args, **kwargs)
            else:
                key = str(args[0]) if args else str(kwargs)
            
            cached_result = cache.get(key)
            if cached_result is not None:
                return cached_result
            
            result = await fn(*args, **kwargs)
            cache.set(key, result, ttl)
            
            return result
        
        return wrapper
    
    return decorator


# ============================================================================
# 工厂函数
# ============================================================================

def create_retrieval_cache(config: Optional[Dict] = None) -> RetrievalCache:
    """
    创建检索缓存的工厂函数
    
    Args:
        config: 配置字典，可包含 cache 子配置
        
    Returns:
        配置好的 RetrievalCache 实例
    """
    cache_config = CacheConfig.from_dict(config or {})
    return RetrievalCache(config=cache_config)


def create_cache_warmer(
    cache: RetrievalCache,
    graphiti_adapter: Any = None,
    custom_queries: Optional[List[str]] = None,
) -> CacheWarmer:
    """
    创建缓存预热器的工厂函数
    """
    return CacheWarmer(
        cache=cache,
        graphiti_adapter=graphiti_adapter,
        custom_queries=custom_queries,
    )
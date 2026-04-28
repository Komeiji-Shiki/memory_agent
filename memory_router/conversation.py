"""
Conversation Cache - 对话缓存管理

管理最后一次对话的缓存，支持 TTL 过期。
"""

import time
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class CachedConversation:
    """缓存的对话数据"""
    messages: List[Dict[str, Any]]
    response_content: str
    reasoning: str
    timestamp: float = field(default_factory=time.time)
    
    def is_expired(self, ttl_seconds: int) -> bool:
        """检查是否过期"""
        return time.time() - self.timestamp > ttl_seconds


class ConversationCache:
    """对话缓存管理器"""
    
    def __init__(self, ttl_seconds: int = 3600):
        """
        初始化缓存
        
        Args:
            ttl_seconds: 缓存存活时间（秒）
        """
        self.ttl_seconds = ttl_seconds
        self._cache: Optional[CachedConversation] = None
    
    def set(
        self,
        messages: List[Dict[str, Any]],
        response_content: str,
        reasoning: str = ""
    ) -> None:
        """
        设置缓存
        
        Args:
            messages: 对话消息列表
            response_content: 响应内容
            reasoning: 思考过程
        """
        self._cache = CachedConversation(
            messages=messages,
            response_content=response_content,
            reasoning=reasoning
        )
        logging.debug(f"[对话缓存] 已缓存对话，TTL={self.ttl_seconds}s")
    
    def get(self) -> Optional[Tuple[List[Dict[str, Any]], str, str]]:
        """
        获取缓存的对话
        
        Returns:
            (messages, response_content, reasoning) 或 None
        """
        if self._cache is None:
            return None
        
        if self._cache.is_expired(self.ttl_seconds):
            logging.debug(f"[对话缓存] 已过期，清理")
            self._cache = None
            return None
        
        return (self._cache.messages, self._cache.response_content, self._cache.reasoning)
    
    def clear(self) -> None:
        """清理缓存"""
        self._cache = None
        logging.debug("[对话缓存] 已手动清理")
    
    def update_ttl(self, ttl_seconds: int) -> None:
        """更新 TTL"""
        self.ttl_seconds = ttl_seconds
    
    @property
    def is_cached(self) -> bool:
        """检查是否有有效缓存"""
        return self.get() is not None
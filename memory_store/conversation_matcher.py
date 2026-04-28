"""
对话会话匹配器

解决核心问题：OpenAI API 标准没有 session_id，需要通过消息内容来判断是续写还是新会话。

匹配策略：
1. 内存缓存 - 快速匹配最近活跃的会话
2. 消息指纹 - 基于消息结构和内容的哈希
3. 前缀匹配 - 判断新消息是否是已有对话的延续
4. 时间窗口 - 超时则视为新会话
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# 数据类型定义
# ============================================================================

@dataclass(frozen=True)
class MatchConfig:
    """匹配器配置（不可变）"""
    session_timeout_minutes: int = 30
    prefix_match_threshold: float = 0.7
    max_recent_files_hours: int = 24
    fingerprint_message_count: int = 5
    fingerprint_content_length: int = 100
    
    @classmethod
    def from_dict(cls, config: Dict) -> MatchConfig:
        """从配置字典创建"""
        return cls(
            session_timeout_minutes=config.get("session_timeout_minutes", 30),
            prefix_match_threshold=config.get("prefix_match_threshold", 0.7),
            max_recent_files_hours=config.get("max_recent_files_hours", 24),
            fingerprint_message_count=config.get("fingerprint_message_count", 5),
            fingerprint_content_length=config.get("fingerprint_content_length", 100),
        )


@dataclass
class MatchResult:
    """匹配结果"""
    file_path: Path
    is_new: bool
    confidence: float
    match_method: str
    session_id: str = field(default="")
    
    def __post_init__(self):
        if not self.session_id:
            self.session_id = self.file_path.stem


@dataclass
class ActiveSession:
    """活跃会话状态"""
    file_path: Path
    fingerprint: str
    last_update: datetime
    turn_count: int = 0
    
    def is_expired(self, timeout: timedelta) -> bool:
        """检查是否超时"""
        return datetime.now() - self.last_update > timeout


# ============================================================================
# 消息处理工具
# ============================================================================

class MessageFingerprinter:
    """消息指纹生成器"""
    
    def __init__(self, config: MatchConfig):
        self.config = config
    
    @staticmethod
    def _extract_text_from_content(content, include_image_marker: bool = True) -> str:
        """
        从消息内容中提取文本（包含图片标记）
        
        支持：
        1. 字符串: "Hello"
        2. 多模态列表: [{"type": "text", "text": "Hello"}, {"type": "image_url", ...}]
        
        Args:
            content: 消息内容
            include_image_marker: 是否在有图片时添加 [IMG] 标记（用于匹配）
        """
        if content is None:
            return ""
        
        if isinstance(content, str):
            return content
        
        if isinstance(content, list):
            text_parts = []
            image_count = 0
            
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type == "text":
                        text_value = item.get("text", "")
                        if isinstance(text_value, str):
                            text_parts.append(text_value)
                        elif isinstance(text_value, list):
                            text_parts.append(" ".join(str(t) for t in text_value))
                        else:
                            text_parts.append(str(text_value) if text_value else "")
                    elif item_type in ("image_url", "image"):
                        image_count += 1
                elif isinstance(item, list):
                    text_parts.append(" ".join(str(i) for i in item))
            
            result = " ".join(text_parts)
            
            # 在有图片时添加标记，确保匹配时能识别
            if include_image_marker and image_count > 0:
                result = f"[IMG:{image_count}] {result}"
            
            return result
        
        # 其他类型强制转字符串
        return str(content)
    
    def compute(self, messages: List[Dict]) -> str:
        """
        计算消息序列的指纹
        
        使用前几轮 user + assistant 消息的内容前缀生成稳定哈希，
        这样即使后续有新消息追加，指纹也不变。
        
        改进：加入 assistant 消息，避免相同开头（如 "test"）的不同对话被误判
        """
        # 提取 user 和 assistant 消息（处理多模态格式）
        message_parts = []
        for m in messages:
            role = m.get("role")
            if role in ("user", "assistant"):
                text = self._extract_text_from_content(m.get("content"))
                # 格式: "U:text" 或 "A:text"
                prefix = "U:" if role == "user" else "A:"
                message_parts.append(f"{prefix}{text[:self.config.fingerprint_content_length]}")
        
        # 取前 N 条（2倍，因为现在包含 user 和 assistant）
        selected = message_parts[:self.config.fingerprint_message_count * 2]
        
        if not selected:
            return ""
        
        # 拼接并哈希
        combined = "|".join(selected)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]
    
    def compute_structure_fingerprint(self, messages: List[Dict]) -> str:
        """
        计算消息结构指纹
        
        用于快速判断消息序列结构是否变化（如角色序列、消息数量）
        """
        structure = []
        for m in messages[:10]:
            role = m.get('role', '?')
            content = m.get('content', '')
            # 处理多模态格式
            if isinstance(content, list):
                content_len = len(self._extract_text_from_content(content))
            elif isinstance(content, str):
                content_len = len(content)
            else:
                content_len = 0
            structure.append(f"{role}:{content_len}")
        combined = "|".join(structure)
        return hashlib.md5(combined.encode()).hexdigest()[:12]


class SimilarityCalculator:
    """相似度计算器"""
    
    @staticmethod
    def jaccard_char(text1: str, text2: str) -> float:
        """字符级 Jaccard 相似度"""
        if not text1 or not text2:
            return 0.0
        
        text1, text2 = text1.strip(), text2.strip()
        
        if text1 == text2:
            return 1.0
        
        # 前缀匹配给高分
        if text1.startswith(text2) or text2.startswith(text1):
            return 0.95
        
        set1, set2 = set(text1), set(text2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
    
    @staticmethod
    def sequence_prefix_match(
        existing: List[str],
        new: List[str],
        threshold: float = 0.7
    ) -> Tuple[bool, float]:
        """
        序列前缀匹配
        
        判断 new 序列是否是 existing 的延续
        返回 (是否匹配, 匹配率)
        """
        if not existing or not new:
            return False, 0.0
        
        # 【修复】新消息数量必须 > 已有数量，才能算续写
        if len(new) <= len(existing):
            return False, 0.0
        
        match_count = 0
        for i, old in enumerate(existing):
            if i >= len(new):
                break
            
            similarity = SimilarityCalculator.jaccard_char(old, new[i])
            if similarity >= threshold:
                match_count += 1
        
        match_ratio = match_count / len(existing)
        return match_ratio >= 0.8, match_ratio


# ============================================================================
# 会话文件读写
# ============================================================================

class ConversationFileReader:
    """对话文件读取器"""
    
    @staticmethod
    def read_header(file_path: Path) -> Optional[Dict]:
        """读取文件头"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                first_line = f.readline()
                if first_line:
                    data = json.loads(first_line)
                    if data.get("type") == "header":
                        return data
        except (json.JSONDecodeError, IOError):
            pass
        return None
    
    @staticmethod
    def read_turns(file_path: Path) -> List[Dict]:
        """读取所有对话轮次"""
        turns = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data.get("type") == "turn":
                            turns.append(data)
                    except json.JSONDecodeError:
                        continue
        except IOError:
            pass
        return turns
    
    @staticmethod
    def extract_user_messages(turns: List[Dict], max_chars: int = 200) -> List[str]:
        """从轮次中提取用户消息（去掉图片标记以便匹配）"""
        import re
        result = []
        for turn in turns:
            user_text = turn.get("user", "")
            # 去掉图片标记 [🖼️N张图片] 或 [🖼️N/M张图片已保存]
            user_text = re.sub(r'\[🖼️[^\]]*\]\s*', '', user_text)
            result.append(user_text[:max_chars])
        return result
    
    @staticmethod
    def extract_conversation_messages(turns: List[Dict], max_chars: int = 200) -> List[str]:
        """从轮次中提取用户+助手消息对（用于更精确的会话匹配）"""
        import re
        result = []
        for turn in turns:
            # 提取用户消息
            user_text = turn.get("user", "")
            # 将 [🖼️N张图片] 转换为 [IMG:N] 格式
            img_match = re.search(r'\[🖼️(\d+)', user_text)
            if img_match:
                img_count = img_match.group(1)
                user_text = re.sub(r'\[🖼️[^\]]*\]\s*', f'[IMG:{img_count}] ', user_text)
            result.append(f"U:{user_text[:max_chars]}")
            
            # 提取助手消息
            assistant_text = turn.get("assistant", "")
            result.append(f"A:{assistant_text[:max_chars]}")
        return result


# ============================================================================
# 核心匹配器
# ============================================================================

class ConversationMatcher:
    """
    务实的对话匹配器
    
    核心策略：内存缓存 + 指纹匹配 + 前缀续写检测
    
    工作流程：
    1. 检查内存中的活跃会话（最快）
    2. 扫描最近文件查找可能的续写
    3. 都不匹配则创建新会话
    """
    
    def __init__(
        self,
        conversations_dir: Path,
        config: Optional[MatchConfig] = None
    ):
        self.dir = conversations_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        
        self.config = config or MatchConfig()
        self.fingerprinter = MessageFingerprinter(self.config)
        self.file_reader = ConversationFileReader()
        
        # 活跃会话缓存：user_hash -> ActiveSession
        self._active_sessions: Dict[str, ActiveSession] = {}
        
        # 会话超时
        self._timeout = timedelta(minutes=self.config.session_timeout_minutes)
    
    def match(
        self,
        messages: List[Dict],
        user_key: str = "default"
    ) -> MatchResult:
        """
        匹配对话文件
        
        Args:
            messages: 消息列表
            user_key: 用户标识（API Key 或其他唯一标识）
        
        Returns:
            MatchResult
        """
        user_hash = self._hash_user(user_key)
        
        # 策略 1：检查内存中的活跃会话（最快路径）
        if user_hash in self._active_sessions:
            session = self._active_sessions[user_hash]
            
            if not session.is_expired(self._timeout) and session.file_path.exists():
                # 验证是否是续写
                if self._is_continuation(session.file_path, messages):
                    self._touch_session(user_hash, session.file_path, messages)
                    return MatchResult(
                        file_path=session.file_path,
                        is_new=False,
                        confidence=0.95,
                        match_method="active_session_continuation"
                    )
        
        # 策略 2：扫描最近文件查找续写
        result = self._find_recent_continuation(messages, user_hash)
        if result:
            self._register_session(user_hash, result.file_path, messages)
            return result
        
        # 策略 3：创建新会话
        new_session = self._create_new_session(user_hash)
        self._register_session(user_hash, new_session.file_path, messages)
        return new_session
    
    def _hash_user(self, user_key: str) -> str:
        """用户标识哈希"""
        return hashlib.md5(user_key.encode()).hexdigest()[:8]
    
    def _is_continuation(self, conv_file: Path, new_messages: List[Dict]) -> bool:
        """
        判断新消息是否是已有对话的延续
        
        核心逻辑：
        1. 提取已有对话的用户消息
        2. 提取新消息中的用户消息
        3. 检查是否前缀匹配
        """
        existing_turns = self.file_reader.read_turns(conv_file)
        if not existing_turns:
            return False
        
        # 提取 user+assistant 交替消息对
        existing_msgs = self.file_reader.extract_conversation_messages(existing_turns)
        new_msgs = []
        for m in new_messages:
            role = m.get("role")
            if role in ("user", "assistant"):
                text = MessageFingerprinter._extract_text_from_content(m.get("content"))
                prefix = "U:" if role == "user" else "A:"
                new_msgs.append(f"{prefix}{text[:200]}")
        
        if not existing_msgs or not new_msgs:
            return False
        
        is_match, ratio = SimilarityCalculator.sequence_prefix_match(
            existing_msgs,
            new_msgs,
            self.config.prefix_match_threshold
        )
        
        if is_match:
            logger.debug(f"续写匹配成功: ratio={ratio:.2f}")
        
        return is_match
    
    def _find_recent_continuation(
        self,
        messages: List[Dict],
        user_hash: str
    ) -> Optional[MatchResult]:
        """在最近的文件中查找可能的续写（支持日期子目录结构）"""
        cutoff = datetime.now() - timedelta(hours=self.config.max_recent_files_hours)
        
        # 收集最近的日期子目录（今天和昨天等）
        recent_files = []
        
        # 1. 先检查日期子目录结构 (conversations/2026-01-22/*.jsonl)
        for date_dir in sorted(self.dir.iterdir(), reverse=True):
            if date_dir.is_dir() and self._is_date_dir(date_dir.name):
                pattern = f"*_{user_hash}.jsonl"
                for f in date_dir.glob(pattern):
                    if f.stat().st_mtime > cutoff.timestamp():
                        recent_files.append(f)
        
        # 2. 兼容旧的扁平结构 (conversations/*.jsonl)
        pattern = f"*_{user_hash}.jsonl"
        for f in self.dir.glob(pattern):
            if f.is_file() and f.stat().st_mtime > cutoff.timestamp():
                recent_files.append(f)
        
        # 按修改时间排序
        recent_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        for conv_file in recent_files[:5]:  # 最多检查 5 个文件
            if self._is_continuation(conv_file, messages):
                return MatchResult(
                    file_path=conv_file,
                    is_new=False,
                    confidence=0.85,
                    match_method="file_scan_continuation"
                )
        
        return None
    
    def _is_date_dir(self, name: str) -> bool:
        """检查目录名是否为日期格式 (YYYY-MM-DD)"""
        if len(name) != 10:
            return False
        try:
            datetime.strptime(name, "%Y-%m-%d")
            return True
        except ValueError:
            return False
    
    def _create_new_session(self, user_hash: str) -> MatchResult:
        """创建新会话文件（使用日期子目录）"""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%H%M%S")
        
        # 创建日期子目录
        date_dir = self.dir / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        
        # 文件名格式: HHMMSS_userhash.jsonl
        file_path = date_dir / f"{timestamp}_{user_hash}.jsonl"
        
        # 避免文件名冲突
        counter = 1
        while file_path.exists():
            file_path = date_dir / f"{timestamp}_{counter}_{user_hash}.jsonl"
            counter += 1
        
        return MatchResult(
            file_path=file_path,
            is_new=True,
            confidence=1.0,
            match_method="new"
        )
    
    def _register_session(
        self,
        user_hash: str,
        file_path: Path,
        messages: List[Dict]
    ):
        """注册/更新活跃会话"""
        fingerprint = self.fingerprinter.compute(messages)
        self._active_sessions[user_hash] = ActiveSession(
            file_path=file_path,
            fingerprint=fingerprint,
            last_update=datetime.now(),
            turn_count=len([m for m in messages if m.get("role") == "user"])
        )
    
    def _touch_session(
        self,
        user_hash: str,
        file_path: Path,
        messages: List[Dict]
    ):
        """更新会话的最后活跃时间"""
        if user_hash in self._active_sessions:
            session = self._active_sessions[user_hash]
            self._active_sessions[user_hash] = ActiveSession(
                file_path=session.file_path,
                fingerprint=session.fingerprint,
                last_update=datetime.now(),
                turn_count=len([m for m in messages if m.get("role") == "user"])
            )
    
    def cleanup_expired(self):
        """清理过期的会话缓存"""
        now = datetime.now()
        expired_timeout = self._timeout * 2
        
        expired = [
            user_hash
            for user_hash, session in self._active_sessions.items()
            if session.is_expired(expired_timeout)
        ]
        
        for user_hash in expired:
            del self._active_sessions[user_hash]
        
        if expired:
            logger.debug(f"清理了 {len(expired)} 个过期会话缓存")
    
    def get_active_session_count(self) -> int:
        """获取活跃会话数量"""
        return len(self._active_sessions)
    
    def compute_fingerprint(self, messages: List[Dict]) -> str:
        """公开的指纹计算方法（供 Logger 使用）"""
        return self.fingerprinter.compute(messages)
    
    def compute_structure_fingerprint(self, messages: List[Dict]) -> str:
        """公开的结构指纹计算方法"""
        return self.fingerprinter.compute_structure_fingerprint(messages)
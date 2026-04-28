"""
原始对话记录器

职责：
1. 使用 ConversationMatcher 匹配/创建会话文件
2. 以 JSONL 格式完整保存每轮对话
3. 维护会话元数据（header/footer）
4. 可选：异步索引到 Graphiti

文件格式：
    第一行: {"type": "header", "session_id": "...", "start_time": "...", ...}
    中间行: {"type": "turn", "turn_id": 1, "timestamp": "...", "user": "...", "assistant": "..."}
    最后行: {"type": "footer", "end_time": "...", "turn_count": N}
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from .conversation_matcher import ConversationMatcher, MatchConfig, MatchResult

logger = logging.getLogger(__name__)


# ============================================================================
# 配置
# ============================================================================

@dataclass(frozen=True)
class LoggerConfig:
    """记录器配置"""
    enabled: bool = True
    max_turns_per_file: int = 100
    index_to_graphiti: bool = True
    async_index: bool = True
    
    @classmethod
    def from_dict(cls, config: Dict) -> LoggerConfig:
        return cls(
            enabled=config.get("enabled", True),
            max_turns_per_file=config.get("max_turns_per_file", 100),
            index_to_graphiti=config.get("index_to_graphiti", True),
            async_index=config.get("async_index", True),
        )


# ============================================================================
# 协议定义
# ============================================================================

class GraphitiIndexer(Protocol):
    """Graphiti 索引器协议（依赖注入）"""
    
    async def add_episode(
        self,
        content: str,
        source: str,
        episode_type: Any,
        timestamp: datetime,
        **kwargs
    ) -> Optional[str]:
        """添加 Episode"""
        ...


class SyncGraphitiIndexer(Protocol):
    """同步版 Graphiti 索引器协议"""
    
    def add_episode(
        self,
        content: str,
        source: str,
        episode_type: Any,
        timestamp: datetime,
        **kwargs
    ) -> Optional[str]:
        """添加 Episode"""
        ...


# ============================================================================
# 数据类型
# ============================================================================

@dataclass
class TurnRecord:
    """对话轮次记录"""
    turn_id: int
    timestamp: datetime
    user: str
    assistant: str
    model: str
    metadata: Dict = field(default_factory=dict)
    images: List[str] = field(default_factory=list)  # 图片相对路径列表
    
    def to_dict(self) -> Dict:
        result = {
            "type": "turn",
            "turn_id": self.turn_id,
            "timestamp": self.timestamp.isoformat(),
            "user": self.user,
            "assistant": self.assistant,
            "model": self.model,
        }
        if self.metadata:
            result["metadata"] = self.metadata
        if self.images:
            result["images"] = self.images
        return result


@dataclass
class SessionHeader:
    """会话头信息"""
    session_id: str
    start_time: datetime
    model: str
    fingerprint: str
    system_prompt_preview: Optional[str] = None
    client_session_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        result = {
            "type": "header",
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "model": self.model,
            "fingerprint": self.fingerprint,
        }
        if self.system_prompt_preview:
            result["system_prompt_preview"] = self.system_prompt_preview
        if self.client_session_id:
            result["client_session_id"] = self.client_session_id
        return result


@dataclass
class SessionFooter:
    """会话尾信息"""
    end_time: datetime
    turn_count: int
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "type": "footer",
            "end_time": self.end_time.isoformat(),
            "turn_count": self.turn_count,
            "updated_at": self.updated_at.isoformat()
        }


@dataclass
class ConversationData:
    """完整对话数据"""
    header: Optional[SessionHeader]
    turns: List[TurnRecord]
    footer: Optional[SessionFooter]
    file_path: Optional[Path] = None


# ============================================================================
# 文件操作
# ============================================================================

class ConversationFileWriter:
    """对话文件写入器"""
    
    @staticmethod
    def write_header(file_path: Path, header: SessionHeader):
        """写入文件头（覆盖模式）"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(header.to_dict(), ensure_ascii=False) + "\n")
    
    @staticmethod
    def append_turn(file_path: Path, turn: TurnRecord):
        """追加对话轮次"""
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn.to_dict(), ensure_ascii=False) + "\n")
    
    @staticmethod
    def update_footer(file_path: Path, footer: SessionFooter):
        """更新文件尾"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # 移除旧的 footer
            if lines and '"type": "footer"' in lines[-1]:
                lines = lines[:-1]
            
            # 追加新 footer
            lines.append(json.dumps(footer.to_dict(), ensure_ascii=False) + "\n")
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            logger.error(f"更新 footer 失败: {e}")


class ConversationFileReader:
    """对话文件读取器"""
    
    @staticmethod
    def read_conversation(file_path: Path) -> ConversationData:
        """读取完整对话"""
        header = None
        turns = []
        footer = None
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        record_type = data.get("type")
                        
                        if record_type == "header":
                            header = SessionHeader(
                                session_id=data.get("session_id", ""),
                                start_time=datetime.fromisoformat(data.get("start_time", "")),
                                model=data.get("model", ""),
                                fingerprint=data.get("fingerprint", ""),
                                system_prompt_preview=data.get("system_prompt_preview"),
                                client_session_id=data.get("client_session_id"),
                            )
                        elif record_type == "turn":
                            turns.append(TurnRecord(
                                turn_id=data.get("turn_id", 0),
                                timestamp=datetime.fromisoformat(data.get("timestamp", "")),
                                user=data.get("user", ""),
                                assistant=data.get("assistant", ""),
                                model=data.get("model", ""),
                                metadata=data.get("metadata", {}),
                                images=data.get("images", []),
                            ))
                        elif record_type == "footer":
                            footer = SessionFooter(
                                end_time=datetime.fromisoformat(data.get("end_time", "")),
                                turn_count=data.get("turn_count", 0),
                            )
                    except (json.JSONDecodeError, ValueError):
                        continue
        except IOError as e:
            logger.error(f"读取对话文件失败: {e}")
        
        return ConversationData(
            header=header,
            turns=turns,
            footer=footer,
            file_path=file_path
        )
    
    @staticmethod
    def count_turns(file_path: Path) -> int:
        """统计轮次数量"""
        count = 0
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if '"type": "turn"' in line:
                        count += 1
        except IOError:
            pass
        return count


# ============================================================================
# 核心记录器
# ============================================================================

class ConversationLogger:
    """
    原始对话记录器
    
    职责：
    1. 匹配/创建会话文件
    2. 记录每轮对话
    3. 可选：异步索引到 Graphiti
    """
    
    def __init__(
        self,
        lifebook_path: str,
        config: Optional[Dict] = None,
        graphiti_adapter: Optional[Any] = None
    ):
        self.lifebook_path = Path(lifebook_path)
        self.conv_dir = self.lifebook_path / "conversations"
        self.conv_dir.mkdir(parents=True, exist_ok=True)
        
        # 解析配置
        conv_config = config.get("conversation_logger", {}) if config else {}
        self.config = LoggerConfig.from_dict(conv_config)
        
        # 匹配器配置
        match_config = MatchConfig.from_dict(conv_config)
        self.matcher = ConversationMatcher(self.conv_dir, match_config)
        
        # Graphiti 适配器（可选）
        self.graphiti = graphiti_adapter
        
        # 文件操作器
        self.file_writer = ConversationFileWriter()
        self.file_reader = ConversationFileReader()
        
        # 当前会话状态
        self._current_file: Optional[Path] = None
        self._current_turn: int = 0
        
        logger.info(f"ConversationLogger 初始化完成: {self.conv_dir}")
    
    def log_turn(
        self,
        messages: List[Dict],
        model: str,
        response: str,
        user_key: str = "default",
        metadata: Optional[Dict] = None
    ) -> Path:
        """
        记录一轮对话
        
        Args:
            messages: 完整消息历史（包括 system）
            model: 使用的模型
            response: AI 回复
            user_key: 用户标识
            metadata: 额外元数据
        
        Returns:
            对话文件路径
        """
        if not self.config.enabled:
            # 返回占位路径
            return self.conv_dir / "disabled.jsonl"
        
        # 1. 匹配或创建会话
        match_result = self.matcher.match(messages, user_key)
        conv_file = match_result.file_path
        
        if match_result.is_new:
            self._init_new_file(conv_file, messages, model)
            self._current_turn = 0
        else:
            # 从文件读取当前轮次数
            self._current_turn = self.file_reader.count_turns(conv_file)
        
        logger.debug(
            f"会话匹配: {conv_file.name} "
            f"(method={match_result.match_method}, confidence={match_result.confidence:.2f})"
        )
        
        # 2. 提取当前轮的用户消息和图片
        current_user, image_paths = self._extract_last_user_message_with_images(messages, conv_file)
        
        if not current_user:
            logger.debug("未找到用户消息，跳过记录")
            return conv_file
        
        # 3. 创建并追加轮次记录
        self._current_turn += 1
        turn = TurnRecord(
            turn_id=self._current_turn,
            timestamp=datetime.now(),
            user=current_user,
            assistant=response,
            model=model,
            metadata=metadata or {},
            images=image_paths
        )
        
        self.file_writer.append_turn(conv_file, turn)
        
        # 4. 更新 footer
        footer = SessionFooter(
            end_time=datetime.now(),
            turn_count=self._current_turn
        )
        self.file_writer.update_footer(conv_file, footer)
        
        # 5. 异步索引到 Graphiti（如果启用）
        if self.graphiti and self.config.index_to_graphiti:
            self._index_to_graphiti(current_user, response, conv_file)
        
        self._current_file = conv_file
        
        logger.debug(f"记录轮次 {self._current_turn}: {conv_file.name}")
        
        return conv_file
    
    def _init_new_file(
        self,
        conv_file: Path,
        messages: List[Dict],
        model: str
    ):
        """初始化新的对话文件"""
        fingerprint = self.matcher.compute_fingerprint(messages)
        
        # 提取 system prompt 预览
        system_preview = None
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                # 处理多模态格式
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(str(item.get("text", "")))
                        elif isinstance(item, str):
                            text_parts.append(item)
                    content = " ".join(text_parts)
                elif not isinstance(content, str):
                    content = str(content) if content else ""
                system_preview = content[:200] if content else None
                break
        
        header = SessionHeader(
            session_id=conv_file.stem,
            start_time=datetime.now(),
            model=model,
            fingerprint=fingerprint,
            system_prompt_preview=system_preview
        )
        
        self.file_writer.write_header(conv_file, header)
        logger.info(f"创建新会话: {conv_file.name}")
    
    def _extract_last_user_message(self, messages: List[Dict]) -> Optional[str]:
        """
        提取最后一条用户消息（简化版，不保存图片）
        
        支持两种格式：
        1. 纯文本: {"role": "user", "content": "Hello"}
        2. 多模态: {"role": "user", "content": [{"type": "text", "text": "..."}, {"type": "image_url", ...}]}
        """
        text, _ = self._extract_last_user_message_with_images(messages, None)
        return text
    
    def _extract_last_user_message_with_images(
        self,
        messages: List[Dict],
        conv_file: Optional[Path]
    ) -> Tuple[Optional[str], List[str]]:
        """
        提取最后一条用户消息，并保存图片
        
        支持两种图片格式：
        1. OpenAI 格式: {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        2. Claude 格式: {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}
        
        Args:
            messages: 消息列表
            conv_file: 对话文件路径（用于确定图片保存位置）
        
        Returns:
            (文本内容, 图片相对路径列表)
        """
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content")
                if content is None:
                    continue
                
                # 调试日志：打印实际收到的 content 结构
                import json as _json
                try:
                    if isinstance(content, list):
                        logger.info(f"[调试] content 是列表，长度={len(content)}")
                        for idx, item in enumerate(content[:3]):  # 只打印前3个
                            item_preview = str(item)[:200] if not isinstance(item, dict) else _json.dumps(item, ensure_ascii=False, default=str)[:200]
                            logger.info(f"[调试] content[{idx}] 类型={type(item).__name__}, 内容预览={item_preview}")
                    else:
                        logger.info(f"[调试] content 类型={type(content).__name__}, 长度={len(str(content)) if content else 0}")
                except Exception as e:
                    logger.warning(f"[调试] 打印 content 失败: {e}")
                
                # 处理字符串类型
                if isinstance(content, str):
                    return content, []
                
                # 处理多模态列表类型
                if isinstance(content, list):
                    text_parts = []
                    image_paths = []
                    image_count = 0
                    
                    for item in content:
                        # 处理字符串元素（直接文本）
                        if isinstance(item, str):
                            text_parts.append(item)
                            continue
                        
                        # 处理字典元素（结构化内容）
                        if isinstance(item, dict):
                            item_type = item.get("type")
                            
                            if item_type == "text":
                                text_value = item.get("text", "")
                                # 确保 text 是字符串（有些格式可能是列表）
                                if isinstance(text_value, list):
                                    text_parts.append(" ".join(str(t) for t in text_value))
                                elif isinstance(text_value, str):
                                    text_parts.append(text_value)
                                else:
                                    text_parts.append(str(text_value) if text_value else "")
                            
                            # OpenAI 格式: type="image_url"
                            elif item_type == "image_url":
                                image_count += 1
                                if conv_file:
                                    image_path = self._save_image_from_item(
                                        item, conv_file, image_count
                                    )
                                    if image_path:
                                        image_paths.append(image_path)
                                    else:
                                        logger.debug(f"图片 {image_count} 保存失败或跳过")
                            
                            # Claude/Anthropic 格式: type="image"
                            elif item_type == "image":
                                image_count += 1
                                if conv_file:
                                    image_path = self._save_image_from_claude_format(
                                        item, conv_file, image_count
                                    )
                                    if image_path:
                                        image_paths.append(image_path)
                                    else:
                                        logger.debug(f"图片 {image_count} (Claude格式) 保存失败或跳过")
                        
                        # 处理列表元素（嵌套内容，转为字符串）
                        elif isinstance(item, list):
                            text_parts.append(" ".join(str(i) for i in item))
                    
                    # 拼接文本部分
                    text_content = "\n".join(text_parts).strip()
                    
                    # 如果有图片，添加标记（包括保存失败的）
                    if image_count > 0:
                        saved_count = len(image_paths)
                        if saved_count == image_count:
                            img_marker = f"[🖼️{saved_count}张图片]"
                        else:
                            img_marker = f"[🖼️{saved_count}/{image_count}张图片已保存]"
                        text_content = f"{img_marker} {text_content}" if text_content else img_marker
                    
                    return text_content if text_content else None, image_paths
                
        return None, []
    
    def _save_image_from_item(
        self,
        item: Dict,
        conv_file: Path,
        index: int
    ) -> Optional[str]:
        """
        从消息项中提取并保存图片
        
        Args:
            item: {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
            conv_file: 对话文件路径
            index: 图片序号
        
        Returns:
            保存的图片相对路径（相对于 conversations 目录）
        """
        try:
            image_url = item.get("image_url", {})
            url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url)
            
            if not url:
                return None
            
            # 解析 data URL
            if url.startswith("data:"):
                # 格式: data:image/png;base64,iVBORw0KGgo...
                match = re.match(r'data:image/(\w+);base64,(.+)', url)
                if not match:
                    logger.warning("无法解析图片 data URL 格式")
                    return None
                
                image_format = match.group(1).lower()
                if image_format == "jpeg":
                    image_format = "jpg"
                base64_data = match.group(2)
                
                # 解码 base64
                try:
                    image_data = base64.b64decode(base64_data)
                except Exception as e:
                    logger.warning(f"base64 解码失败: {e}")
                    return None
                
                # 生成文件名: turn_{turn_id}_{index}_{hash}.{ext}
                content_hash = hashlib.md5(image_data[:1024]).hexdigest()[:8]
                filename = f"turn_{self._current_turn + 1}_{index}_{content_hash}.{image_format}"
                
                # 确定保存目录 (与对话文件同级的 images 子目录)
                date_dir = conv_file.parent
                images_dir = date_dir / "images"
                images_dir.mkdir(parents=True, exist_ok=True)
                
                # 保存图片
                image_path = images_dir / filename
                with open(image_path, "wb") as f:
                    f.write(image_data)
                
                logger.info(f"保存图片: {image_path}")
                
                # 返回相对路径 (相对于 conversations 目录)
                # 格式: 2026-01-23/images/turn_1_1_abc12345.png
                rel_path = f"{date_dir.name}/images/{filename}"
                return rel_path
            
            elif url.startswith("http"):
                # HTTP URL，记录但不下载
                logger.debug(f"跳过 HTTP 图片 URL: {url[:50]}...")
                return None
            
            else:
                logger.warning(f"未知的图片 URL 格式: {url[:50]}...")
                return None
                
        except Exception as e:
            logger.error(f"保存图片失败: {e}")
            return None
    
    def _save_image_from_claude_format(
        self,
        item: Dict,
        conv_file: Path,
        index: int
    ) -> Optional[str]:
        """
        从 Claude/Anthropic 格式的消息项中提取并保存图片
        
        Claude 格式:
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "iVBORw0KGgo..."
            }
        }
        
        Args:
            item: Claude 格式的图片消息项
            conv_file: 对话文件路径
            index: 图片序号
        
        Returns:
            保存的图片相对路径（相对于 conversations 目录）
        """
        try:
            source = item.get("source", {})
            if not isinstance(source, dict):
                logger.warning("Claude 图片格式错误: source 不是字典")
                return None
            
            source_type = source.get("type", "")
            if source_type != "base64":
                logger.warning(f"不支持的 Claude 图片 source 类型: {source_type}")
                return None
            
            media_type = source.get("media_type", "")
            base64_data = source.get("data", "")
            
            if not base64_data:
                logger.warning("Claude 图片 data 为空")
                return None
            
            # 解析 media_type 获取图片格式
            # 格式如: "image/png", "image/jpeg", "image/gif", "image/webp"
            if "/" in media_type:
                image_format = media_type.split("/")[1].lower()
            else:
                image_format = "png"  # 默认
            
            # 统一格式名称
            if image_format == "jpeg":
                image_format = "jpg"
            
            # 解码 base64
            try:
                image_data = base64.b64decode(base64_data)
            except Exception as e:
                logger.warning(f"Claude 图片 base64 解码失败: {e}")
                return None
            
            # 生成文件名: turn_{turn_id}_{index}_{hash}.{ext}
            content_hash = hashlib.md5(image_data[:1024]).hexdigest()[:8]
            filename = f"turn_{self._current_turn + 1}_{index}_{content_hash}.{image_format}"
            
            # 确定保存目录 (与对话文件同级的 images 子目录)
            date_dir = conv_file.parent
            images_dir = date_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            
            # 保存图片
            image_path = images_dir / filename
            with open(image_path, "wb") as f:
                f.write(image_data)
            
            logger.info(f"保存图片 (Claude格式): {image_path}")
            
            # 返回相对路径 (相对于 conversations 目录)
            # 格式: 2026-01-23/images/turn_1_1_abc12345.png
            rel_path = f"{date_dir.name}/images/{filename}"
            return rel_path
            
        except Exception as e:
            logger.error(f"保存 Claude 格式图片失败: {e}")
            return None
    
    def _index_to_graphiti(
        self,
        user_msg: str,
        assistant_msg: str,
        conv_file: Path
    ):
        """将对话索引到 Graphiti"""
        episode_content = f"用户: {user_msg}\n灰魂: {assistant_msg}"
        source = f"conv:{conv_file.stem}:{self._current_turn}"
        
        if self.config.async_index:
            # 异步索引
            self._async_index(episode_content, source)
        else:
            # 同步索引
            self._sync_index(episode_content, source)
    
    def _async_index(self, content: str, source: str):
        """异步索引到 Graphiti"""
        try:
            # 尝试获取事件循环
            try:
                loop = asyncio.get_running_loop()
                # 已在异步上下文，创建任务
                asyncio.create_task(self._do_async_index(content, source))
            except RuntimeError:
                # 不在异步上下文，使用线程池
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(self._sync_index, content, source)
        except Exception as e:
            logger.warning(f"异步索引调度失败: {e}")
    
    async def _do_async_index(self, content: str, source: str):
        """执行异步索引"""
        try:
            if hasattr(self.graphiti, 'add_episode'):
                await self.graphiti.add_episode(
                    content=content,
                    source=source,
                    episode_type="conversation",
                    timestamp=datetime.now()
                )
                logger.debug(f"异步索引成功: {source}")
        except Exception as e:
            logger.warning(f"Graphiti 异步索引失败: {e}")
    
    def _sync_index(self, content: str, source: str):
        """同步索引到 Graphiti"""
        try:
            if hasattr(self.graphiti, 'add_episode'):
                self.graphiti.add_episode(
                    content=content,
                    source=source,
                    episode_type="conversation",
                    timestamp=datetime.now()
                )
                logger.debug(f"同步索引成功: {source}")
        except Exception as e:
            logger.warning(f"Graphiti 同步索引失败: {e}")
    
    # ========================================================================
    # 查询接口
    # ========================================================================
    
    def get_conversation(self, session_id: str) -> Optional[ConversationData]:
        """
        读取完整对话
        
        Args:
            session_id: 会话 ID（文件名，不含扩展名）
        
        Returns:
            ConversationData 或 None
        """
        # 1. 先在日期子目录中查找
        for date_dir in self.conv_dir.iterdir():
            if date_dir.is_dir() and self._is_date_dir(date_dir.name):
                conv_file = date_dir / f"{session_id}.jsonl"
                if conv_file.exists():
                    return self.file_reader.read_conversation(conv_file)
                # 模糊匹配
                for f in date_dir.glob(f"*{session_id}*.jsonl"):
                    return self.file_reader.read_conversation(f)
        
        # 2. 兼容旧的扁平结构
        conv_file = self.conv_dir / f"{session_id}.jsonl"
        if conv_file.exists():
            return self.file_reader.read_conversation(conv_file)
        
        # 3. 尝试模糊匹配旧结构
        for f in self.conv_dir.glob(f"{session_id}*.jsonl"):
            if f.is_file():
                return self.file_reader.read_conversation(f)
        
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
    
    def list_conversations(
        self,
        days: int = 7,
        include_preview: bool = True
    ) -> List[Dict]:
        """
        列出最近的对话（支持日期子目录结构）
        
        Args:
            days: 回溯天数
            include_preview: 是否包含消息预览
        
        Returns:
            对话信息列表
        """
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)
        conversations = []
        all_files = []
        
        # 1. 收集日期子目录中的文件
        for date_dir in self.conv_dir.iterdir():
            if date_dir.is_dir() and self._is_date_dir(date_dir.name):
                try:
                    dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                    if dir_date.date() >= cutoff.date():
                        for f in date_dir.glob("*.jsonl"):
                            all_files.append((f, date_dir.name))
                except ValueError:
                    continue
        
        # 2. 兼容旧的扁平结构
        for f in self.conv_dir.glob("*.jsonl"):
            if f.is_file():
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime.date() >= cutoff.date():
                        # 从文件名提取日期
                        date_part = f.stem.split('_')[0] if '_' in f.stem else None
                        all_files.append((f, date_part))
                except Exception:
                    continue
        
        # 按修改时间排序
        all_files.sort(key=lambda x: x[0].stat().st_mtime, reverse=True)
        
        for f, date_str in all_files:
            try:
                conv = self.file_reader.read_conversation(f)
                if conv.header:
                    info = {
                        "session_id": f.stem,
                        "date": date_str,
                        "start_time": conv.header.start_time.isoformat() if conv.header else None,
                        "end_time": conv.footer.end_time.isoformat() if conv.footer else None,
                        "turn_count": len(conv.turns),
                        "model": conv.header.model if conv.header else None
                    }
                    
                    if include_preview and conv.turns:
                        info["first_message"] = conv.turns[0].user[:100]
                        info["last_message"] = conv.turns[-1].assistant[:100]
                    
                    conversations.append(info)
            except Exception:
                continue
        
        return conversations
    
    def get_conversations_for_date(self, date_str: str) -> List[ConversationData]:
        """
        获取指定日期的所有对话（支持日期子目录结构）
        
        Args:
            date_str: 日期字符串 (YYYY-MM-DD)
        
        Returns:
            对话数据列表
        """
        conversations = []
        
        # 1. 先查找日期子目录
        date_dir = self.conv_dir / date_str
        if date_dir.exists() and date_dir.is_dir():
            for conv_file in date_dir.glob("*.jsonl"):
                conv = self.file_reader.read_conversation(conv_file)
                if conv.turns:
                    conversations.append(conv)
        
        # 2. 兼容旧的扁平结构
        for conv_file in self.conv_dir.glob(f"{date_str}*.jsonl"):
            if conv_file.is_file():
                conv = self.file_reader.read_conversation(conv_file)
                if conv.turns:
                    conversations.append(conv)
        
        # 按时间排序
        conversations.sort(
            key=lambda c: c.header.start_time if c.header else datetime.min
        )
        
        return conversations
    
    # ========================================================================
    # 维护接口
    # ========================================================================
    
    def cleanup_matcher_cache(self):
        """清理匹配器缓存"""
        self.matcher.cleanup_expired()
    
    @property
    def active_session_count(self) -> int:
        """活跃会话数量"""
        return self.matcher.get_active_session_count()
    
    @property
    def current_file(self) -> Optional[Path]:
        """当前会话文件"""
        return self._current_file
    
    @property
    def current_turn(self) -> int:
        """当前轮次"""
        return self._current_turn
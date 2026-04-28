"""
日记生成器

从原始对话生成每日日记。

数据源优先级：
1. pending 目录下的摘要文件（已经过一次总结）
2. conversations 目录下的原始对话（完整保留）

工作流程：
1. 收集指定日期的所有对话/摘要
2. 使用 LLM 生成日记
3. 保存到 daily 目录
4. 可选同步到 Graphiti
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Union

from .conversation_logger import ConversationData, ConversationFileReader

logger = logging.getLogger(__name__)


# ============================================================================
# 配置
# ============================================================================

@dataclass(frozen=True)
class DiaryGeneratorConfig:
    """日记生成器配置"""
    auto_generate: bool = False
    model: str = "deepseek-chat"
    consolidate_prompt: str = ""
    merge_prompt: str = ""
    sync_to_graphiti: bool = True
    
    @classmethod
    def from_dict(cls, config: Dict) -> DiaryGeneratorConfig:
        pending_config = config.get("pending", {})
        return cls(
            auto_generate=config.get("diary_generation", {}).get("auto_generate", False),
            model=config.get("diary_generation", {}).get("model", 
                   config.get("post_conversation", {}).get("summarize_model", "deepseek-chat")),
            consolidate_prompt=pending_config.get("consolidate_prompt", DEFAULT_CONSOLIDATE_PROMPT),
            merge_prompt=pending_config.get("merge_prompt", DEFAULT_MERGE_PROMPT),
            sync_to_graphiti=config.get("graphiti", {}).get("sync", {}).get("auto_sync_markdown", False),
        )


# 默认提示词（从 config.jsonc 复制，作为后备）
DEFAULT_CONSOLIDATE_PROMPT = """请将以下一个"清醒周期"内的多次对话摘要整合成一篇流畅的日记。

要求：
1. 以第三人称整理，在日记称用户为主人，称ai/llm为灰魂
2. 按时间顺序组织，但要自然衔接，但标明每部分时间（24小时制）
3. 提炼主要事件
4. 不遗漏任何可能有用的细节
5. 尽可能详细但不杂乱

<对话摘要>
{content}
</对话摘要>

称用户为主人，称ai/llm为灰魂:"我"应该是灰魂，用户/主人等指代用户的内容→主人
只记录内容，不进行评价，不进行不必要的情感升华。只记录完整内容，不在记录事实后进行感情总结。使用第三人称总结，如：主人在对话中纠正了灰魂...主人和灰魂讨论了...
只描述进行了的对话。不额外总结感想。

请以第三人称输出整合后的日记："""

DEFAULT_MERGE_PROMPT = """<现有日记内容>
{existing_content}
</现有日记内容>

---
请将以下新的对话摘要整合到现有日记中，生成一篇完整的日记。

<新的对话摘要>
{content}
</新的对话摘要>

要求：
1. 以第三人称整理，在日记称用户为主人，称ai/llm为灰魂
2. 按时间顺序组织，但要自然衔接，但标明每部分时间（24小时制）
3. 提炼主要事件
4. 不遗漏任何可能有用的细节
5. 尽可能详细但不杂乱
6. 输出新增部分，不输出重复部分

只记录内容，不进行评价，不进行不必要的情感升华。使用第三人称总结。
只描述进行了的对话。不额外总结感想。

请以第三人称输出追加的日记："""


# ============================================================================
# 协议定义
# ============================================================================

class LLMClient(Protocol):
    """LLM 客户端协议"""
    
    async def generate(self, prompt: str, **kwargs) -> str:
        """生成文本"""
        ...


class SyncLLMClient(Protocol):
    """同步 LLM 客户端协议"""
    
    def generate(self, prompt: str, **kwargs) -> str:
        """生成文本"""
        ...


class GraphitiIndexer(Protocol):
    """Graphiti 索引器协议"""
    
    async def add_episode(
        self,
        content: str,
        source: str,
        episode_type: Any,
        timestamp: datetime,
        **kwargs
    ) -> Optional[str]:
        ...


# ============================================================================
# 数据收集器
# ============================================================================

class ContentCollector:
    """内容收集器 - 从多个数据源收集日记素材"""
    
    def __init__(self, lifebook_path: Path):
        self.lifebook_path = lifebook_path
        self.pending_dir = lifebook_path / "pending"
        self.conv_dir = lifebook_path / "conversations"
        self.daily_dir = lifebook_path / "daily"
        
        self.conv_reader = ConversationFileReader()
    
    def collect_pending_summaries(self, target_date: date) -> str:
        """
        收集 pending 目录下的摘要
        
        pending 目录结构：
        - session_2026-01-21_1224.md
        """
        date_str = target_date.strftime("%Y-%m-%d")
        summaries = []
        
        if not self.pending_dir.exists():
            return ""
        
        # 查找该日期的 session 文件
        for f in self.pending_dir.glob(f"session_{date_str}*.md"):
            try:
                content = f.read_text(encoding="utf-8")
                if content.strip():
                    summaries.append(content)
            except Exception as e:
                logger.warning(f"读取 pending 文件失败: {f}, {e}")
        
        if summaries:
            logger.debug(f"从 pending 目录收集到 {len(summaries)} 个摘要")
        
        return "\n\n---\n\n".join(summaries)
    
    def collect_conversations(self, target_date: date) -> List[ConversationData]:
        """收集 conversations 目录下的原始对话"""
        date_str = target_date.strftime("%Y-%m-%d")
        conversations = []
        
        if not self.conv_dir.exists():
            return []
        
        for conv_file in self.conv_dir.glob(f"{date_str}*.jsonl"):
            try:
                conv = self.conv_reader.read_conversation(conv_file)
                if conv.turns:
                    conversations.append(conv)
            except Exception as e:
                logger.warning(f"读取对话文件失败: {conv_file}, {e}")
        
        # 按时间排序
        conversations.sort(
            key=lambda c: c.header.start_time if c.header else datetime.min
        )
        
        if conversations:
            logger.debug(f"从 conversations 目录收集到 {len(conversations)} 个对话")
        
        return conversations
    
    def format_conversations(self, conversations: List[ConversationData]) -> str:
        """将对话格式化为文本"""
        parts = []
        
        for conv in conversations:
            if not conv.header:
                continue
            
            header = conv.header
            parts.append(f"## 对话 {header.session_id} ({header.model})")
            parts.append(f"开始时间: {header.start_time.strftime('%H:%M')}")
            parts.append("")
            
            for turn in conv.turns:
                ts = turn.timestamp.strftime("%H:%M")
                parts.append(f"### [{ts}]")
                parts.append(f"**用户**: {turn.user}")
                parts.append(f"**AI**: {turn.assistant}")
                parts.append("")
        
        return "\n".join(parts)
    
    def read_existing_diary(self, target_date: date) -> Optional[str]:
        """读取已存在的日记"""
        date_str = target_date.strftime("%Y-%m-%d")
        diary_path = self.daily_dir / f"{date_str}.md"
        
        if diary_path.exists():
            try:
                return diary_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"读取日记失败: {diary_path}, {e}")
        
        return None
    
    def save_diary(self, target_date: date, content: str) -> Path:
        """保存日记"""
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        
        date_str = target_date.strftime("%Y-%m-%d")
        diary_path = self.daily_dir / f"{date_str}.md"
        
        diary_path.write_text(content, encoding="utf-8")
        logger.info(f"日记已保存: {diary_path}")
        
        return diary_path


# ============================================================================
# 日记生成结果
# ============================================================================

@dataclass
class DiaryGenerationResult:
    """日记生成结果"""
    success: bool
    message: str
    content: Optional[str] = None
    diary_path: Optional[Path] = None
    source_conversations: int = 0
    source_turns: int = 0
    source_pending: int = 0
    is_merge: bool = False
    graphiti_synced: bool = False


# ============================================================================
# 核心生成器
# ============================================================================

class DiaryGenerator:
    """
    日记生成器
    
    从原始对话生成每日日记，支持：
    - 新建日记（consolidate_prompt）
    - 追加日记（merge_prompt）
    - 同步到 Graphiti
    """
    
    def __init__(
        self,
        lifebook_path: str,
        config: Dict,
        llm_client: Optional[Any] = None,
        graphiti_adapter: Optional[Any] = None
    ):
        self.lifebook_path = Path(lifebook_path)
        self.config = DiaryGeneratorConfig.from_dict(config)
        self.collector = ContentCollector(self.lifebook_path)
        
        self.llm = llm_client
        self.graphiti = graphiti_adapter
        
        logger.info(f"DiaryGenerator 初始化完成: model={self.config.model}")
    
    async def generate_for_date(
        self,
        target_date: date,
        force_regenerate: bool = False
    ) -> DiaryGenerationResult:
        """
        为指定日期生成日记
        
        Args:
            target_date: 目标日期
            force_regenerate: 是否强制重新生成
        
        Returns:
            DiaryGenerationResult
        """
        date_str = target_date.strftime("%Y-%m-%d")
        
        # 1. 收集内容
        # 优先使用 pending 摘要，没有则用原始对话
        pending_content = self.collector.collect_pending_summaries(target_date)
        conversations = self.collector.collect_conversations(target_date)
        
        if not pending_content and not conversations:
            return DiaryGenerationResult(
                success=False,
                message=f"{date_str} 没有对话记录",
            )
        
        # 2. 准备内容
        if pending_content:
            content = pending_content
            source_pending = pending_content.count("---") + 1
            source_conversations = 0
            source_turns = 0
        else:
            content = self.collector.format_conversations(conversations)
            source_pending = 0
            source_conversations = len(conversations)
            source_turns = sum(len(c.turns) for c in conversations)
        
        # 3. 检查现有日记
        existing_diary = self.collector.read_existing_diary(target_date)
        is_merge = existing_diary is not None and not force_regenerate
        
        if existing_diary and not force_regenerate:
            # 追加模式：检查是否有新内容
            # 这里简单判断，实际可以更精细
            logger.debug(f"日记已存在，将追加新内容")
        
        # 4. 生成日记
        if self.llm:
            diary_content = await self._generate_with_llm(
                content=content,
                existing_diary=existing_diary if is_merge else None,
                date_str=date_str
            )
        else:
            diary_content = self._generate_simple(content, date_str)
        
        if not diary_content:
            return DiaryGenerationResult(
                success=False,
                message="日记生成失败",
            )
        
        # 5. 如果是追加模式，合并内容
        if is_merge and existing_diary:
            diary_content = existing_diary + "\n\n---\n\n" + diary_content
        
        # 6. 保存
        diary_path = self.collector.save_diary(target_date, diary_content)
        
        # 7. 同步到 Graphiti
        graphiti_synced = False
        if self.graphiti and self.config.sync_to_graphiti:
            graphiti_synced = await self._sync_to_graphiti(
                diary_content, date_str, target_date
            )
        
        return DiaryGenerationResult(
            success=True,
            message="日记生成成功",
            content=diary_content,
            diary_path=diary_path,
            source_conversations=source_conversations,
            source_turns=source_turns,
            source_pending=source_pending,
            is_merge=is_merge,
            graphiti_synced=graphiti_synced,
        )
    
    async def _generate_with_llm(
        self,
        content: str,
        existing_diary: Optional[str],
        date_str: str
    ) -> Optional[str]:
        """使用 LLM 生成日记"""
        try:
            if existing_diary:
                # 追加模式
                prompt = self.config.merge_prompt.format(
                    existing_content=existing_diary,
                    content=content
                )
            else:
                # 新建模式
                prompt = self.config.consolidate_prompt.format(content=content)
            
            # 调用 LLM
            if hasattr(self.llm, 'generate'):
                if asyncio.iscoroutinefunction(self.llm.generate):
                    response = await self.llm.generate(prompt)
                else:
                    response = self.llm.generate(prompt)
            elif hasattr(self.llm, 'chat'):
                # OpenAI 风格客户端
                if hasattr(self.llm.chat, 'completions'):
                    result = await self.llm.chat.completions.create(
                        model=self.config.model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=8000
                    )
                    response = result.choices[0].message.content
                else:
                    response = await self.llm.chat(prompt)
            else:
                logger.warning("未知的 LLM 客户端类型，使用简单模板")
                return self._generate_simple(content, date_str)
            
            return response.strip() if response else None
            
        except Exception as e:
            logger.error(f"LLM 生成日记失败: {e}")
            return self._generate_simple(content, date_str)
    
    def _generate_simple(self, content: str, date_str: str) -> str:
        """无 LLM 时的简单模板"""
        return f"# {date_str} 日记\n\n{content}"
    
    async def _sync_to_graphiti(
        self,
        content: str,
        date_str: str,
        target_date: date
    ) -> bool:
        """将日记同步到 Graphiti"""
        try:
            if hasattr(self.graphiti, 'add_episode'):
                timestamp = datetime.combine(target_date, datetime.min.time())
                
                if asyncio.iscoroutinefunction(self.graphiti.add_episode):
                    await self.graphiti.add_episode(
                        content=content,
                        source=f"diary:{date_str}",
                        episode_type="diary",
                        timestamp=timestamp
                    )
                else:
                    self.graphiti.add_episode(
                        content=content,
                        source=f"diary:{date_str}",
                        episode_type="diary",
                        timestamp=timestamp
                    )
                
                logger.info(f"日记已同步到 Graphiti: {date_str}")
                return True
        except Exception as e:
            logger.warning(f"Graphiti 同步失败: {e}")
        
        return False
    
    async def generate_missing_diaries(
        self,
        days_back: int = 7
    ) -> List[DiaryGenerationResult]:
        """
        生成最近缺失的日记
        
        Args:
            days_back: 回溯天数
        
        Returns:
            生成结果列表
        """
        results = []
        today = date.today()
        
        for i in range(1, days_back + 1):  # 跳过今天
            target_date = today - timedelta(days=i)
            
            # 检查日记是否存在
            existing = self.collector.read_existing_diary(target_date)
            if existing:
                continue
            
            # 生成日记
            result = await self.generate_for_date(target_date)
            results.append(result)
            
            if result.success:
                logger.info(f"生成缺失日记: {target_date}")
        
        return results
    
    # ========================================================================
    # 同步版本包装
    # ========================================================================
    
    def generate_for_date_sync(
        self,
        target_date: date,
        force_regenerate: bool = False
    ) -> DiaryGenerationResult:
        """同步版本的日记生成"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(
            self.generate_for_date(target_date, force_regenerate)
        )
    
    def generate_missing_diaries_sync(
        self,
        days_back: int = 7
    ) -> List[DiaryGenerationResult]:
        """同步版本的缺失日记生成"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(
            self.generate_missing_diaries(days_back)
        )
"""
Pending Manager - 待处理摘要管理

实现对话摘要暂存 + 智能分割汇总机制：
1. 每次对话后，摘要存入当前会话的 Markdown 文件
2. 智能检测"睡眠间隔"（长时间无对话）作为会话分割点
3. 汇总时，将同一"清醒周期"的摘要合并成日记

存储格式（Markdown）：
lifebook/pending/
├── session_2025-12-28_0830.md   ← 一个"清醒周期"
├── session_2025-12-29_0900.md
└── archived/                     ← 归档目录
"""

import os
import re
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from pathlib import Path
from openai import OpenAI
import httpx

from memory_store.debug_logger import get_debug_logger


# 汇总模式
class ConsolidateMode:
    DIARY_ONLY = "diary_only"      # 只生成日记
    NODES_ONLY = "nodes_only"      # 只提取/更新节点
    DIARY_AND_NODES = "both"       # 同时生成日记和节点


@dataclass
class PendingSummary:
    """待处理的对话摘要"""
    timestamp: str  # ISO格式时间戳
    summary: str  # 摘要内容
    topic: str  # 对话主题（简短描述）
    tool_calls: List[str]  # 调用的工具列表
    raw_turns: int  # 原始对话轮数


@dataclass
class Session:
    """一个"清醒周期"会话"""
    session_id: str  # 格式: 2025-12-28_0830
    start_time: datetime
    end_time: datetime
    summaries: List[PendingSummary]
    file_path: Path


class PendingManager:
    """待处理摘要管理器（智能睡眠间隔分割版）"""
    
    # 默认睡眠间隔（小时）- 超过这个时间无对话视为"睡眠"
    DEFAULT_SLEEP_GAP_HOURS = 6
    
    # 安全模板占位符（使用不太可能出现在用户内容中的格式）
    PLACEHOLDER_CONTENT = "<<<CONTENT>>>"
    PLACEHOLDER_EXISTING = "<<<EXISTING_CONTENT>>>"
    
    def __init__(self, lifebook_path: str, encoding: str = "utf-8", sleep_gap_hours: float = None):
        self.lifebook_path = Path(lifebook_path)
        self.pending_dir = self.lifebook_path / "pending"
        self.encoding = encoding
        self.sleep_gap_hours = sleep_gap_hours or self.DEFAULT_SLEEP_GAP_HOURS
        
        # 确保目录存在
        self.pending_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_current_session_file(self) -> Tuple[Path, str]:
        """
        获取当前应该写入的会话文件
        
        逻辑：
        1. 查找所有现有会话文件
        2. 检查最新会话的最后一条摘要时间
        3. 如果距离现在超过 sleep_gap_hours，开始新会话
        4. 否则继续写入现有会话
        
        Returns:
            (文件路径, 会话ID)
        """
        now = datetime.now()
        
        # 查找所有会话文件
        session_files = sorted(self.pending_dir.glob("session_*.md"), reverse=True)
        
        if session_files:
            latest_file = session_files[0]
            last_time = self._get_last_summary_time(latest_file)
            
            if last_time:
                gap = now - last_time
                gap_hours = gap.total_seconds() / 3600
                
                if gap_hours < self.sleep_gap_hours:
                    # 继续使用当前会话
                    session_id = latest_file.stem.replace("session_", "")
                    return latest_file, session_id
        
        # 开始新会话
        session_id = now.strftime("%Y-%m-%d_%H%M")
        new_file = self.pending_dir / f"session_{session_id}.md"
        
        # 创建新会话文件
        self._init_session_file(new_file, session_id, now)
        
        return new_file, session_id
    
    def _init_session_file(self, file_path: Path, session_id: str, start_time: datetime):
        """初始化新的会话文件"""
        date_str = start_time.strftime("%Y年%m月%d日")
        time_str = start_time.strftime("%H:%M")
        
        header = f"""---
session_id: {session_id}
session_start: {start_time.isoformat()}
topics: []
---

# 📝 待处理摘要 - {date_str} {time_str} 开始

"""
        with open(file_path, "w", encoding=self.encoding) as f:
            f.write(header)
    
    def _get_last_summary_time(self, file_path: Path) -> Optional[datetime]:
        """获取会话文件中最后一条摘要的时间"""
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, "r", encoding=self.encoding) as f:
                content = f.read()
            
            # 匹配所有时间戳 ## HH:MM (YYYY-MM-DDTHH:MM:SS)
            # 支持：可选毫秒、可选时区（+08:00 或 Z）
            pattern = r'## \d{2}:\d{2} \((\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?)\)'
            matches = re.findall(pattern, content)
            
            if matches:
                return self._parse_timestamp(matches[-1])
            
            # 回退：使用 session_start
            start_match = re.search(
                r'session_start: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?)',
                content
            )
            if start_match:
                return self._parse_timestamp(start_match.group(1))
                
        except Exception as e:
            print(f"[Pending] 读取时间失败: {e}")
        
        return None
    
    def _parse_timestamp(self, ts_str: str) -> datetime:
        """
        解析时间戳字符串，支持多种格式
        
        支持的格式：
        - 2025-12-31T08:00:00
        - 2025-12-31T08:00:00.123456
        - 2025-12-31T08:00:00+08:00
        - 2025-12-31T08:00:00Z
        """
        # 移除时区后缀（简化处理，假设都是本地时间）
        ts_clean = ts_str.rstrip('Z')
        if '+' in ts_clean:
            ts_clean = ts_clean.split('+')[0]
        elif ts_clean.count('-') > 2:  # 可能有负时区如 -05:00
            parts = ts_clean.rsplit('-', 1)
            if ':' in parts[-1]:  # 确认是时区而不是日期
                ts_clean = parts[0]
        
        return datetime.fromisoformat(ts_clean)
    
    def _safe_template_replace(self, template: str, variables: Dict[str, str]) -> str:
        """
        安全的模板变量替换
        
        使用多层策略避免用户内容中的变量被错误替换：
        1. 先替换特殊占位符 (<<<CONTENT>>> 等)
        2. 再替换标准占位符 ({content} 等)
        
        Args:
            template: 模板字符串
            variables: 变量字典
            
        Returns:
            替换后的字符串
        """
        result = template
        
        # 第一步：替换特殊占位符（不太可能出现在用户内容中）
        special_placeholders = {
            self.PLACEHOLDER_CONTENT: variables.get("content", ""),
            self.PLACEHOLDER_EXISTING: variables.get("existing_content", ""),
        }
        
        for placeholder, value in special_placeholders.items():
            result = result.replace(placeholder, value)
        
        # 第二步：替换标准占位符（用于用户自定义模板）
        # 使用正则避免部分匹配问题
        for key, value in variables.items():
            # 只替换 {key} 格式，不替换 {{key}} 格式（用于转义）
            pattern = r'\{' + re.escape(key) + r'\}'
            result = re.sub(pattern, lambda m: value, result)
        
        # 第三步：将转义的双大括号还原
        result = result.replace('{{', '{').replace('}}', '}')
        
        return result
    
    def add_pending(self, summary: PendingSummary) -> bool:
        """
        添加待处理摘要到当前会话
        
        摘要以 Markdown 格式追加到会话文件
        """
        try:
            file_path, session_id = self._get_current_session_file()
            
            # 格式化摘要
            ts = datetime.fromisoformat(summary.timestamp)
            time_display = ts.strftime("%H:%M")
            
            entry = f"\n## {time_display} ({summary.timestamp}) - {summary.topic}\n\n"
            entry += f"{summary.summary}\n"
            
            if summary.tool_calls:
                entry += f"\n> 🔧 工具调用: {', '.join(summary.tool_calls)}\n"
            
            entry += f"\n> 📊 对话轮数: {summary.raw_turns}\n"
            entry += "\n---\n"
            
            # 追加到文件
            with open(file_path, "a", encoding=self.encoding) as f:
                f.write(entry)
            
            # 更新 frontmatter 的 topics
            self._update_session_topics(file_path, summary.topic)
            
            print(f"[暂存] 摘要已保存到 session_{session_id}.md")
            return True
            
        except Exception as e:
            print(f"[暂存] 保存失败: {e}")
            return False
    
    def _update_session_topics(self, file_path: Path, new_topic: str):
        """更新会话文件的 topics 列表"""
        try:
            with open(file_path, "r", encoding=self.encoding) as f:
                content = f.read()
            
            # 解析现有 topics
            match = re.search(r'topics: \[(.*?)\]', content)
            if match:
                topics_str = match.group(1)
                if topics_str:
                    topics = [t.strip().strip('"\'') for t in topics_str.split(',')]
                else:
                    topics = []
                
                if new_topic not in topics:
                    topics.append(new_topic)
                    new_topics_str = ', '.join(f'"{t}"' for t in topics)
                    content = re.sub(r'topics: \[.*?\]', f'topics: [{new_topics_str}]', content)
                    
                    with open(file_path, "w", encoding=self.encoding) as f:
                        f.write(content)
                        
        except Exception as e:
            print(f"[Pending] 更新topics失败: {e}")
    
    def get_all_sessions(self, include_archived: bool = False) -> List[Session]:
        """
        获取所有待处理会话
        
        Args:
            include_archived: 是否包含已归档的会话
        """
        sessions = []
        
        # 兼容性修复：在某些环境下 glob 可能会受到路径分隔符影响
        # 先确保目录存在，然后直接列出文件
        if not self.pending_dir.exists():
            return []
        
        # 获取待处理目录的会话
        files = [f for f in self.pending_dir.iterdir() if f.name.startswith("session_") and f.suffix == ".md"]
        for file_path in sorted(files):
            session = self._parse_session_file(file_path)
            if session and session.summaries:
                sessions.append(session)
        
        # 如果需要，也获取已归档的会话
        if include_archived:
            archive_dir = self.pending_dir / "archived"
            if archive_dir.exists():
                archived_files = [f for f in archive_dir.iterdir() if f.name.startswith("session_") and f.suffix == ".md"]
                for file_path in sorted(archived_files):
                    session = self._parse_session_file(file_path)
                    if session and session.summaries:
                        sessions.append(session)
        
        return sessions
    
    def get_archived_sessions(self) -> List[Session]:
        """获取所有已归档的会话"""
        sessions = []
        archive_dir = self.pending_dir / "archived"
        
        print(f"[Pending] 检查归档目录: {archive_dir}")
        
        if not archive_dir.exists():
            print(f"[Pending] 归档目录不存在")
            return []
        
        files = [f for f in archive_dir.iterdir() if f.name.startswith("session_") and f.suffix == ".md"]
        print(f"[Pending] 找到 {len(files)} 个归档文件: {[f.name for f in files]}")
        
        for file_path in sorted(files, reverse=True):  # 最新的在前
            session = self._parse_session_file(file_path)
            if session:
                print(f"[Pending] 解析成功: {session.session_id}, 摘要数: {len(session.summaries)}")
                if session.summaries:
                    sessions.append(session)
            else:
                print(f"[Pending] 解析失败: {file_path}")
        
        print(f"[Pending] 返回 {len(sessions)} 个归档会话")
        return sessions
    
    def restore_session(self, session_id: str) -> bool:
        """
        从归档恢复会话到待处理目录
        
        恢复后可以重新进行汇总
        """
        archive_dir = self.pending_dir / "archived"
        archived_path = archive_dir / f"session_{session_id}.md"
        pending_path = self.pending_dir / f"session_{session_id}.md"
        
        if not archived_path.exists():
            print(f"[Pending] 归档会话 {session_id} 不存在")
            return False
        
        try:
            # 如果待处理目录已有同名文件，先备份
            if pending_path.exists():
                backup_path = self.pending_dir / f"session_{session_id}_backup.md"
                pending_path.rename(backup_path)
            
            # 从归档移回待处理
            archived_path.rename(pending_path)
            print(f"[Pending] 已恢复会话 {session_id}")
            return True
        except Exception as e:
            print(f"[Pending] 恢复失败: {e}")
            return False
    
    def _parse_session_file(self, file_path: Path) -> Optional[Session]:
        """解析会话文件"""
        try:
            with open(file_path, "r", encoding=self.encoding) as f:
                content = f.read()
            
            # 解析 session_id
            session_id_match = re.search(r'session_id: ([\w\-_]+)', content)
            session_id = session_id_match.group(1) if session_id_match else file_path.stem.replace("session_", "")
            
            # 解析 session_start - 支持可选毫秒
            start_match = re.search(r'session_start: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)', content)
            start_time = datetime.fromisoformat(start_match.group(1)) if start_match else datetime.now()
            
            # 解析摘要条目 - 支持可选毫秒
            summaries = []
            pattern = r'## (\d{2}:\d{2}) \((\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)\) - (.+?)\n\n(.*?)(?=\n---|\n## |$)'
            matches = re.findall(pattern, content, re.DOTALL)
            
            for match in matches:
                time_display, timestamp, topic, body = match
                
                # 解析工具调用
                tools_match = re.search(r'> 🔧 工具调用: (.+)', body)
                tool_calls = [t.strip() for t in tools_match.group(1).split(',')] if tools_match else []
                
                # 解析对话轮数
                turns_match = re.search(r'> 📊 对话轮数: (\d+)', body)
                raw_turns = int(turns_match.group(1)) if turns_match else 0
                
                # 提取纯摘要内容
                summary_text = re.sub(r'\n> [🔧📊].+', '', body).strip()
                
                summaries.append(PendingSummary(
                    timestamp=timestamp,
                    summary=summary_text,
                    topic=topic.strip(),
                    tool_calls=tool_calls,
                    raw_turns=raw_turns
                ))
            
            # 计算 end_time
            end_time = datetime.fromisoformat(summaries[-1].timestamp) if summaries else start_time
            
            return Session(
                session_id=session_id,
                start_time=start_time,
                end_time=end_time,
                summaries=summaries,
                file_path=file_path
            )
            
        except Exception as e:
            print(f"[Pending] 解析会话文件失败 {file_path}: {e}")
            return None
    
    def get_pending_sessions(self, exclude_active: bool = True) -> List[Session]:
        """
        获取可以汇总的会话
        
        Args:
            exclude_active: 排除当前活跃会话（最后一条摘要距今不超过 sleep_gap_hours）
        """
        sessions = self.get_all_sessions()
        
        if not exclude_active:
            return sessions
        
        now = datetime.now()
        result = []
        
        for session in sessions:
            gap = now - session.end_time
            gap_hours = gap.total_seconds() / 3600
            
            if gap_hours >= self.sleep_gap_hours:
                result.append(session)
        
        return result
    
    def get_pending_dates(self, include_today: bool = False) -> List[str]:
        """获取所有有待处理摘要的日期（兼容旧接口）"""
        sessions = self.get_pending_sessions(exclude_active=not include_today)
        
        dates = set()
        for session in sessions:
            dates.add(session.start_time.strftime("%Y-%m-%d"))
        
        return sorted(list(dates), reverse=True)
    
    def get_pending_for_date(self, date: str) -> List[PendingSummary]:
        """获取指定日期的所有待处理摘要（兼容旧接口）"""
        sessions = self.get_all_sessions()
        
        summaries = []
        for session in sessions:
            if session.start_time.strftime("%Y-%m-%d") == date:
                summaries.extend(session.summaries)
        
        return summaries
    
    def mark_session_processed(self, session_id: str, archive: bool = True) -> bool:
        """标记会话已处理"""
        file_path = self.pending_dir / f"session_{session_id}.md"
        
        if not file_path.exists():
            return False
        
        try:
            if archive:
                archive_dir = self.pending_dir / "archived"
                archive_dir.mkdir(parents=True, exist_ok=True)
                archive_path = archive_dir / f"session_{session_id}.md"
                file_path.rename(archive_path)
            else:
                file_path.unlink()
            return True
        except Exception as e:
            print(f"[暂存] 处理失败: {e}")
            return False
    
    def mark_processed(self, date: str, archive: bool = True) -> bool:
        """标记某天的摘要已处理（兼容旧接口）"""
        sessions = self.get_all_sessions()
        success = True
        
        for session in sessions:
            if session.start_time.strftime("%Y-%m-%d") == date:
                if not self.mark_session_processed(session.session_id, archive):
                    success = False
        
        return success
    
    def consolidate_session(
        self,
        session: Session,
        model: str = "deepseek-chat",
        api_key: str = "",
        base_url: str = "https://api.deepseek.com/v1",
        custom_prompt: str = "",
        consolidate_prompt: str = "",
        merge_prompt: str = "",
        append_to_existing: bool = True
    ) -> Dict[str, Any]:
        """
        将一个会话的所有摘要汇总成日记
        
        日记日期以会话开始时间为准
        
        Args:
            append_to_existing: 如果当天日记已存在，是否追加而不是覆盖
        """
        if not session.summaries:
            return {
                "success": False,
                "content": "",
                "message": f"会话 {session.session_id} 没有摘要"
            }
        
        diary_date = session.start_time.strftime("%Y-%m-%d")
        
        # 检查当天日记是否已存在
        from memory_store.reader import LifeBookReader
        from memory_store.writer import LifeBookWriter
        
        reader = LifeBookReader(self.lifebook_path, self.encoding)
        writer = LifeBookWriter(self.lifebook_path, self.encoding)
        
        existing_diary = reader.read_diary(diary_date)
        existing_content = ""
        if existing_diary and append_to_existing:
            existing_content = existing_diary.content
            print(f"[汇总] 日记 {diary_date} 已存在，将追加新内容")
        
        # 组装摘要内容
        summary_texts = []
        for s in session.summaries:
            ts = datetime.fromisoformat(s.timestamp)
            time_str = ts.strftime("%H:%M")
            text = f"### {time_str} - {s.topic}\n{s.summary}"
            if s.tool_calls:
                text += f"\n> 操作: {', '.join(s.tool_calls)}"
            summary_texts.append(text)
        
        combined_content = "\n\n".join(summary_texts)
        
        # 计算会话时间跨度
        duration = session.end_time - session.start_time
        duration_str = f"{int(duration.total_seconds() / 3600)}小时{int((duration.total_seconds() % 3600) / 60)}分钟"
        
        # 构建汇总提示 - 使用安全的模板替换
        template_vars = {
            "content": combined_content,
            "existing_content": existing_content,
            "start_time": session.start_time.strftime('%H:%M'),
            "end_time": session.end_time.strftime('%H:%M'),
            "full_start_time": session.start_time.strftime('%Y-%m-%d %H:%M'),
            "duration": duration_str,
            "summary_count": str(len(session.summaries)),
        }
        
        if existing_content:
            # 有现有内容时，要求整合
            # 优先级：custom_prompt > merge_prompt > 默认值
            if custom_prompt:
                prompt = custom_prompt
            elif merge_prompt:
                prompt = merge_prompt
            else:
                # 硬编码默认值（仅在没有配置时使用）
                # 使用特殊占位符避免冲突
                prompt = f"""请将以下新的对话摘要整合到现有日记中，生成一篇完整的日记。

现有日记内容：
<<<EXISTING_CONTENT>>>

---

新的对话摘要（{session.start_time.strftime('%H:%M')} ~ {session.end_time.strftime('%H:%M')}，跨度 {duration_str}）：
<<<CONTENT>>>

要求：
1. 用第一人称（"我"）撰写
2. 按时间顺序组织，自然衔接现有内容和新内容
3. 不要有重复，保持流畅
4. 保留重要的人名、项目名等细节
5. 输出完整的日记（不是只输出新增部分）

请生成整合后的完整日记："""
        else:
            # 新建日记
            # 优先级：custom_prompt > consolidate_prompt > 默认值
            if custom_prompt:
                prompt = custom_prompt
            elif consolidate_prompt:
                prompt = consolidate_prompt
            else:
                # 硬编码默认值（仅在没有配置时使用）
                prompt = f"""请将以下一个"清醒周期"（{duration_str}）内的多次对话摘要整合成一篇流畅的日记。

这个周期从 {session.start_time.strftime('%Y-%m-%d %H:%M')} 开始，到 {session.end_time.strftime('%H:%M')} 结束。

要求：
1. 用第一人称（"我"）撰写
2. 按时间顺序组织，但要自然衔接
3. 提炼主要事件和收获
4. 保持日记风格，不要太像工作报告
5. 保留重要的人名、项目名等细节
6. 适当加入情感和反思

对话摘要：
<<<CONTENT>>>

请生成整合后的日记："""
        
        # 安全的模板替换：先替换特殊占位符，再替换标准占位符
        prompt = self._safe_template_replace(prompt, template_vars)
        
        # 记录调试日志
        get_debug_logger().log_pending_consolidate(
            model=model,
            prompt=prompt,
            session_id=session.session_id,
            diary_date=diary_date,
            extra={
                "summary_count": len(session.summaries),
                "has_existing_diary": bool(existing_content),
                "duration": str(duration)
            }
        )
        
        try:
            # 创建不带代理的客户端，避免系统代理设置导致的兼容性问题
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=httpx.Client(proxy=None)
            )
            
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=30000,  # 增加token限制以容纳长日记
                temperature=1
            )
            
            diary_content = response.choices[0].message.content
            
            # 保存到日记
            if existing_content:
                # 已有日记，使用追加模式
                # 添加分隔线和时间段标记
                append_content = f"\n\n---\n\n## 📝 {session.start_time.strftime('%H:%M')} ~ {session.end_time.strftime('%H:%M')} 补充\n\n{diary_content}"
                success = writer.append_to_diary(diary_date, append_content)
            else:
                # 新日记，创建
                title = f"{diary_date} 日记"
                success = writer.create_diary(
                    diary_date,
                    diary_content,
                    title=title,
                    overwrite=False
                )
            
            if success:
                # 写入后立即更新 SQLite 索引，保证 search_memories 可检索到新日记
                try:
                    from memory_store.sqlite_indexer import SqliteIndexer
                    indexer = SqliteIndexer(str(self.lifebook_path), encoding=self.encoding)
                    diary_file_path = str(self.lifebook_path / "daily" / f"{diary_date}.md")
                    indexer.index_file(diary_file_path)
                except Exception:
                    pass

                # 标记会话已处理
                self.mark_session_processed(session.session_id, archive=True)
                
                action = "追加" if existing_content else "生成"
                return {
                    "success": True,
                    "content": diary_content,
                    "message": f"日记 {diary_date} {action}成功（整合了 {len(session.summaries)} 条摘要，跨度 {duration_str}）"
                }
            else:
                return {
                    "success": False,
                    "content": diary_content,
                    "message": "日记生成成功但保存失败"
                }
                
        except Exception as e:
            return {
                "success": False,
                "content": "",
                "message": f"汇总失败: {str(e)}"
            }
    
    def consolidate_with_tools(
        self,
        session: Session,
        model: str = "deepseek-chat",
        api_key: str = "",
        base_url: str = "https://api.deepseek.com/v1",
        mode: str = ConsolidateMode.DIARY_AND_NODES,
        consolidate_prompt: str = "",
        max_iterations: int = 30,  # 增加默认迭代次数，给复杂节点提取更多空间
        append_to_existing: bool = True
    ) -> Dict[str, Any]:
        """
        使用工具调用的汇总方法
        
        支持三种模式：
        - diary_only: 只生成日记（和原方法一样）
        - nodes_only: 只提取/更新节点（不生成日记）
        - both: 同时生成日记和节点
        
        Args:
            session: 要汇总的会话
            model: 模型名称
            api_key: API密钥
            base_url: API基础URL
            mode: 汇总模式
            consolidate_prompt: 自定义提示词
            max_iterations: 最大工具调用轮数
            append_to_existing: 如果当天日记已存在，是否追加
            
        Returns:
            操作结果字典
        """
        if not session.summaries:
            return {
                "success": False,
                "content": "",
                "message": f"会话 {session.session_id} 没有摘要",
                "tool_calls": []
            }
        
        diary_date = session.start_time.strftime("%Y-%m-%d")
        
        # 初始化工具
        from memory_agent.tools import MemoryTools
        memory_tools = MemoryTools(str(self.lifebook_path), enable_write=True, encoding=self.encoding)
        
        # 根据模式选择工具
        if mode == ConsolidateMode.NODES_ONLY:
            # 只提供节点相关工具（包含 create_relations）
            available_tools = ["create_node", "update_node", "add_observations", "create_relations", "get_node", "list_nodes"]
        else:
            # 日记+节点模式：提供节点工具（包含 create_relations）
            available_tools = ["create_node", "update_node", "add_observations", "create_relations", "get_node", "list_nodes"]
        
        # 过滤工具列表
        all_tools = memory_tools.get_openai_tools(include_write=True)
        tools = [t for t in all_tools if t["function"]["name"] in available_tools]
        
        # 检查现有日记
        from memory_store.reader import LifeBookReader
        from memory_store.writer import LifeBookWriter
        
        reader = LifeBookReader(self.lifebook_path, self.encoding)
        writer = LifeBookWriter(self.lifebook_path, self.encoding)
        
        existing_diary = reader.read_diary(diary_date)
        existing_content = ""
        if existing_diary and append_to_existing:
            existing_content = existing_diary.content
        
        # 组装摘要内容
        summary_texts = []
        for s in session.summaries:
            ts = datetime.fromisoformat(s.timestamp)
            time_str = ts.strftime("%H:%M")
            text = f"### {time_str} - {s.topic}\n{s.summary}"
            if s.tool_calls:
                text += f"\n> 操作: {', '.join(s.tool_calls)}"
            summary_texts.append(text)
        
        combined_content = "\n\n".join(summary_texts)
        
        # 计算时间跨度
        duration = session.end_time - session.start_time
        duration_str = f"{int(duration.total_seconds() / 3600)}小时{int((duration.total_seconds() % 3600) / 60)}分钟"
        
        # 构建提示词
        if consolidate_prompt:
            prompt = consolidate_prompt
        else:
            prompt = self._build_consolidate_prompt_with_tools(
                mode=mode,
                combined_content=combined_content,
                existing_content=existing_content,
                session=session,
                duration_str=duration_str
            )
        
        # 模板替换
        template_vars = {
            "content": combined_content,
            "existing_content": existing_content,
            "start_time": session.start_time.strftime('%H:%M'),
            "end_time": session.end_time.strftime('%H:%M'),
            "full_start_time": session.start_time.strftime('%Y-%m-%d %H:%M'),
            "duration": duration_str,
            "summary_count": str(len(session.summaries)),
        }
        prompt = self._safe_template_replace(prompt, template_vars)
        
        # 记录调试日志
        get_debug_logger().log_pending_consolidate(
            model=model,
            prompt=prompt,
            session_id=session.session_id,
            diary_date=diary_date,
            extra={
                "mode": mode,
                "summary_count": len(session.summaries),
                "has_existing_diary": bool(existing_content),
                "available_tools": available_tools
            }
        )
        
        try:
            # 创建客户端
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=httpx.Client(proxy=None)
            )
            
            # 多轮对话
            messages = [{"role": "user", "content": prompt}]
            tool_call_history = []
            diary_content = ""
            iteration = 0
            
            while iteration < max_iterations:
                print(f"[汇总] === 迭代 {iteration + 1}/{max_iterations} ===")
                
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools if tools else None,
                    max_tokens=30000,
                    temperature=1
                )
                
                message = response.choices[0].message
                finish_reason = response.choices[0].finish_reason
                
                # 记录LLM输出
                if message.content:
                    content_preview = message.content[:200] + "..." if len(message.content) > 200 else message.content
                    print(f"[汇总] LLM输出: {content_preview}")
                
                if message.tool_calls:
                    print(f"[汇总] 工具调用数: {len(message.tool_calls)}")
                
                print(f"[汇总] finish_reason: {finish_reason}")
                
                # 检查是否完成
                if finish_reason == "stop" or not message.tool_calls:
                    diary_content = message.content or ""
                    print(f"[汇总] 循环结束，日记内容长度: {len(diary_content)}")
                    break
                
                # 处理工具调用
                if message.tool_calls:
                    # 添加 assistant 消息
                    assistant_msg = {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            for tc in message.tool_calls
                        ]
                    }
                    # DeepSeek reasoner 需要 reasoning_content 字段
                    if hasattr(message, 'reasoning_content') and message.reasoning_content:
                        assistant_msg["reasoning_content"] = message.reasoning_content
                    else:
                        # 如果没有，添加空字符串（某些模型需要）
                        assistant_msg["reasoning_content"] = ""
                    messages.append(assistant_msg)
                    
                    # 执行工具调用
                    for tc in message.tool_calls:
                        tool_name = tc.function.name
                        try:
                            arguments = json.loads(tc.function.arguments) if tc.function.arguments else {}
                        except json.JSONDecodeError:
                            arguments = {}
                        
                        # 执行工具
                        result = memory_tools.call_tool(tool_name, arguments)
                        
                        tool_call_history.append({
                            "name": tool_name,
                            "arguments": arguments,
                            "result": result[:500] + "..." if len(result) > 500 else result,
                            "iteration": iteration + 1
                        })
                        
                        print(f"[汇总] 工具调用: {tool_name} -> {result[:100]}...")
                        
                        # 添加工具结果
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result
                        })
                
                iteration += 1
            
            print(f"[汇总] 循环完成，共 {iteration} 次迭代，工具调用 {len(tool_call_history)} 次")
            
            # 如果循环结束但没有日记内容，再请求一次让LLM生成日记
            if not diary_content and mode != ConsolidateMode.NODES_ONLY:
                print(f"[汇总] 工具调用完成但无日记内容，发送补充请求生成日记...")
                
                # 添加提示让LLM输出日记
                messages.append({
                    "role": "user",
                    "content": "工具调用已完成。现在请根据前面的对话摘要，生成日记内容。用第三人称撰写，称用户为「主人」，AI为「灰魂」。"
                })
                
                try:
                    final_response = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=30000,
                        temperature=1
                    )
                    diary_content = final_response.choices[0].message.content or ""
                    print(f"[汇总] 补充请求获得日记内容: {len(diary_content)} 字")
                except Exception as e:
                    print(f"[汇总] 补充请求失败: {e}")
            
            # 根据模式保存结果
            result_info = {
                "success": True,
                "tool_calls": tool_call_history,
                "iterations": iteration + 1
            }
            
            if mode == ConsolidateMode.NODES_ONLY:
                # 只提取节点，不保存日记
                result_info["content"] = ""
                result_info["message"] = f"节点提取完成，执行了 {len(tool_call_history)} 次工具调用"
                # 不归档会话，让用户可以继续生成日记
            else:
                # 保存日记
                if diary_content:
                    if existing_content:
                        append_content = f"\n\n---\n\n## 📝 {session.start_time.strftime('%H:%M')} ~ {session.end_time.strftime('%H:%M')} 补充\n\n{diary_content}"
                        success = writer.append_to_diary(diary_date, append_content)
                    else:
                        title = f"{diary_date} 日记"
                        success = writer.create_diary(diary_date, diary_content, title=title, overwrite=False)
                    
                    if success:
                        # 写入后立即更新 SQLite 索引，保证 search_memories 可检索到新日记
                        try:
                            diary_file_path = str(self.lifebook_path / "daily" / f"{diary_date}.md")
                            memory_tools.indexer.index_file(diary_file_path)
                        except Exception:
                            pass

                        self.mark_session_processed(session.session_id, archive=True)
                        action = "追加" if existing_content else "生成"
                        result_info["content"] = diary_content
                        result_info["message"] = f"日记 {diary_date} {action}成功（执行了 {len(tool_call_history)} 次工具调用）"
                    else:
                        result_info["success"] = False
                        result_info["content"] = diary_content
                        result_info["message"] = "日记保存失败"
                else:
                    result_info["success"] = False
                    result_info["content"] = ""
                    result_info["message"] = "LLM 未返回日记内容"
            
            return result_info
            
        except Exception as e:
            return {
                "success": False,
                "content": "",
                "message": f"汇总失败: {str(e)}",
                "tool_calls": []
            }
    
    def _build_consolidate_prompt_with_tools(
        self,
        mode: str,
        combined_content: str,
        existing_content: str,
        session: 'Session',
        duration_str: str,
        custom_prompt: str = ""
    ) -> str:
        """构建带工具调用的汇总提示词
        
        如果提供了 custom_prompt，会优先使用它；否则使用默认模板。
        """
        
        date_str = session.start_time.strftime("%Y年%m月%d日")
        
        # 如果有自定义提示词，直接使用
        if custom_prompt:
            return custom_prompt
        
        # 工具使用说明（统一用于所有模式）
        tools_doc = """## 可用工具

### 节点创建/更新
- **create_node(name, type, content, tags?)** - 直接创建新节点
  - type: "人物" | "地点" | "事物" | "概念"
  - ⚠️ 直接调用！无需先查询是否存在。如已存在会返回提示。
  
- **update_node(name, content, mode?)** - 更新现有节点内容
  - mode: "append"(追加) | "replace"(替换)，默认 append
  
- **add_observations(observations)** - 批量添加观察事实
  - 格式: [{"name": "节点名", "contents": ["观察1", "观察2"]}]

### 🔗 关系创建（重要！）
- **create_relations(relations)** - 创建节点间关系，让知识图谱产生联系
  - 格式: [{"from": "节点A", "to": "节点B", "relation_type": "关系类型"}]
  
  **何时创建关系**（请积极识别以下场景）：
  - 人物与项目：主人 --创建/开发/维护--> 某项目
  - 人物与工具：主人 --使用--> VSCode、灰魂 --基于--> 大语言模型
  - 人物与人物：小明 --朋友/同事--> 小红
  - 事物与概念：LifeBook系统 --属于--> 记忆管理
  - 事物与事物：项目A --依赖--> 项目B
  
  **常用关系类型**：创建、使用、开发、维护、属于、包含、依赖、朋友、同事、喜欢、基于

### 查询（可选）
- **list_nodes(type?)** - 列出现有节点概览
- **get_node(name)** - 获取节点详情

## ⚠️ 重要提示
1. **直接创建**：无需先 get_node 检查，直接 create_node。已存在会提示。
2. **批量操作**：尽量一次调用处理多个，避免逐个查询。
3. **积极建立关系**：创建节点后，思考它与其他节点的关系，用 create_relations 连接起来！
4. **只记重要的**：只记录对话中真正有价值、值得长期保存的实体。
"""
        
        if mode == ConsolidateMode.NODES_ONLY:
            # 只提取节点
            return f"""{tools_doc}

---

## 对话摘要
{combined_content}

---

## 任务
分析对话，提取重要实体创建/更新节点。

### 节点类型
- 人物：对话提到的人（用户、AI、其他人）
- 事物：项目、工具、软件、游戏、作品等
- 概念：抽象概念、方法论、技术等
- 地点：地理位置

### 操作策略
1. 直接用 create_node 创建新实体（系统自动判断是否已存在）
2. 对已有实体有新信息，用 update_node 或 add_observations 补充
3. 如需建立实体间关系，用 create_relations

完成后简要说明创建/更新了哪些节点。"""
        
        elif mode == ConsolidateMode.DIARY_AND_NODES:
            # 同时生成日记和节点
            base_prompt = f"""{tools_doc}

---

## 对话摘要（{date_str} {session.start_time.strftime('%H:%M')} ~ {session.end_time.strftime('%H:%M')}，跨度 {duration_str}）
{combined_content}
"""
            
            if existing_content:
                base_prompt += f"""
---

## 现有日记内容
{existing_content}

---

## 任务

### 1. 提取节点
直接用 create_node 创建新实体。对已有实体用 add_observations 补充。可用 create_relations 建立关系。

### 2. 生成日记
用第三人称撰写，称用户为「主人」，AI为「灰魂」。将新内容与现有日记整合，不重复。

完成工具调用后，输出新增的日记内容（追加部分）。"""
            else:
                base_prompt += f"""
---

## 任务

### 1. 提取节点
直接用 create_node 创建新实体。对已有实体用 add_observations 补充。可用 create_relations 建立关系。

### 2. 生成日记
用第三人称撰写，称用户为「主人」，AI为「灰魂」。按时间顺序组织，保留重要细节。

完成工具调用后，输出日记内容。"""
            
            return base_prompt
        
        else:
            # diary_only 模式不使用此方法
            return ""
    
    def direct_convert_session(
        self,
        session: Session,
        append_to_existing: bool = True
    ) -> Dict[str, Any]:
        """
        直接将会话的摘要转换为日记（不使用LLM）
        
        适用于用户已经审核过摘要内容，觉得没问题可以直接转换的情况。
        
        Args:
            session: 要转换的会话
            append_to_existing: 如果当天日记已存在，是否追加
            
        Returns:
            操作结果字典
        """
        if not session.summaries:
            return {
                "success": False,
                "content": "",
                "message": f"会话 {session.session_id} 没有摘要"
            }
        
        diary_date = session.start_time.strftime("%Y-%m-%d")
        
        from memory_store.reader import LifeBookReader
        from memory_store.writer import LifeBookWriter
        
        reader = LifeBookReader(self.lifebook_path, self.encoding)
        writer = LifeBookWriter(self.lifebook_path, self.encoding)
        
        existing_diary = reader.read_diary(diary_date)
        has_existing = existing_diary and append_to_existing
        
        # 计算会话时间跨度
        duration = session.end_time - session.start_time
        duration_mins = int(duration.total_seconds() / 60)
        
        # 格式化摘要为日记内容
        diary_parts = []
        
        # 添加会话时间段标题
        time_range = f"{session.start_time.strftime('%H:%M')} ~ {session.end_time.strftime('%H:%M')}"
        
        if has_existing:
            diary_parts.append(f"## 📝 {time_range} 记录")
        else:
            # 新日记添加日期标题
            date_str = session.start_time.strftime("%Y年%m月%d日")
            weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][session.start_time.weekday()]
            diary_parts.append(f"## {date_str} {weekday}")
            diary_parts.append("")
        
        diary_parts.append("")
        
        # 格式化每条摘要
        for s in session.summaries:
            ts = datetime.fromisoformat(s.timestamp)
            time_str = ts.strftime("%H:%M")
            
            diary_parts.append(f"### {time_str} - {s.topic}")
            diary_parts.append("")
            diary_parts.append(s.summary)
            
            if s.tool_calls:
                diary_parts.append("")
                diary_parts.append(f"> 🔧 操作: {', '.join(s.tool_calls)}")
            
            diary_parts.append("")
        
        diary_content = "\n".join(diary_parts)
        
        try:
            if has_existing:
                # 追加到现有日记
                append_content = f"\n\n---\n\n{diary_content}"
                success = writer.append_to_diary(diary_date, append_content)
            else:
                # 创建新日记
                title = f"{diary_date} 日记"
                success = writer.create_diary(
                    diary_date,
                    diary_content,
                    title=title,
                    overwrite=False
                )
            
            if success:
                # 写入后立即更新 SQLite 索引，保证 search_memories 可检索到新日记
                try:
                    from memory_store.sqlite_indexer import SqliteIndexer
                    indexer = SqliteIndexer(str(self.lifebook_path), encoding=self.encoding)
                    diary_file_path = str(self.lifebook_path / "daily" / f"{diary_date}.md")
                    indexer.index_file(diary_file_path)
                except Exception:
                    pass

                # 标记会话已处理
                self.mark_session_processed(session.session_id, archive=True)
                
                action = "追加" if has_existing else "创建"
                return {
                    "success": True,
                    "content": diary_content,
                    "message": f"日记 {diary_date} {action}成功（直接转换了 {len(session.summaries)} 条摘要，时长 {duration_mins} 分钟）"
                }
            else:
                return {
                    "success": False,
                    "content": diary_content,
                    "message": "日记转换成功但保存失败"
                }
                
        except Exception as e:
            return {
                "success": False,
                "content": "",
                "message": f"直接转换失败: {str(e)}"
            }
    
    def consolidate_to_diary(
        self,
        date: str,
        model: str = "deepseek-chat",
        api_key: str = "",
        base_url: str = "https://api.deepseek.com/v1",
        custom_prompt: str = ""
    ) -> Dict[str, Any]:
        """
        将某天的所有会话汇总成日记（兼容旧接口）
        
        注意：这会把该天所有会话合并成一篇日记
        """
        sessions = [s for s in self.get_all_sessions()
                   if s.start_time.strftime("%Y-%m-%d") == date]
        
        if not sessions:
            return {
                "success": False,
                "content": "",
                "message": f"没有找到 {date} 的待处理摘要"
            }
        
        # 合并所有会话的摘要
        all_summaries = []
        for session in sessions:
            all_summaries.extend(session.summaries)
        
        if not all_summaries:
            return {
                "success": False,
                "content": "",
                "message": f"没有找到 {date} 的待处理摘要"
            }
        
        # 创建虚拟会话进行汇总
        merged_session = Session(
            session_id=date,
            start_time=sessions[0].start_time,
            end_time=sessions[-1].end_time,
            summaries=all_summaries,
            file_path=sessions[0].file_path
        )
        
        result = self.consolidate_session(merged_session, model, api_key, base_url, custom_prompt)
        
        if result["success"]:
            # 标记所有会话已处理
            for session in sessions:
                self.mark_session_processed(session.session_id, archive=True)
        
        return result
    
    def consolidate_all_ready(
        self,
        model: str = "deepseek-chat",
        api_key: str = "",
        base_url: str = "https://api.deepseek.com/v1",
        custom_prompt: str = "",
        consolidate_prompt: str = "",
        merge_prompt: str = ""
    ) -> List[Dict[str, Any]]:
        """
        智能汇总所有准备好的会话
        
        只处理已经"结束"的会话（最后一条摘要距今超过 sleep_gap_hours）
        每个会话生成独立的日记
        """
        sessions = self.get_pending_sessions(exclude_active=True)
        
        results = []
        for session in sessions:
            result = self.consolidate_session(
                session, model, api_key, base_url, custom_prompt,
                consolidate_prompt=consolidate_prompt,
                merge_prompt=merge_prompt
            )
            result["session_id"] = session.session_id
            results.append(result)
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """获取待处理摘要统计"""
        sessions = self.get_all_sessions()
        ready_sessions = self.get_pending_sessions(exclude_active=True)
        
        stats = {
            "total_sessions": len(sessions),
            "ready_sessions": len(ready_sessions),
            "total_summaries": sum(len(s.summaries) for s in sessions),
            "ready_summaries": sum(len(s.summaries) for s in ready_sessions),
            "sessions": [],
            "pending_dates": [],
            "by_date": {}
        }
        
        for session in sessions:
            date = session.start_time.strftime("%Y-%m-%d")
            is_ready = session in ready_sessions
            
            session_info = {
                "session_id": session.session_id,
                "start_time": session.start_time.isoformat(),
                "end_time": session.end_time.isoformat(),
                "summary_count": len(session.summaries),
                "is_ready": is_ready,
                "date": date
            }
            stats["sessions"].append(session_info)
            
            if date not in stats["pending_dates"]:
                stats["pending_dates"].append(date)
            
            if date not in stats["by_date"]:
                stats["by_date"][date] = 0
            stats["by_date"][date] += len(session.summaries)
        
        stats["pending_dates"].sort(reverse=True)
        return stats


# 便捷函数
def create_pending_summary(
    summary: str,
    topic: str,
    tool_calls: List[str] = None,
    raw_turns: int = 0
) -> PendingSummary:
    """创建待处理摘要"""
    return PendingSummary(
        timestamp=datetime.now().isoformat(),
        summary=summary,
        topic=topic,
        tool_calls=tool_calls or [],
        raw_turns=raw_turns
    )
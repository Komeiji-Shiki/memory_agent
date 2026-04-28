"""
LifeBook Writer - 写入日记、总结、节点

支持：
- 创建新条目
- 追加内容
- 更新内容
- 自动创建目录
- 并发写入保护（文件锁）
"""

import os
import re
import threading
from datetime import datetime
from typing import Dict, Optional, Any
from pathlib import Path
from contextlib import contextmanager


# 全局文件锁字典，用于进程内并发控制
_file_locks: Dict[str, threading.Lock] = {}
_file_locks_lock = threading.Lock()


def _get_file_lock(file_path: str) -> threading.Lock:
    """获取文件对应的锁（懒创建）"""
    with _file_locks_lock:
        if file_path not in _file_locks:
            _file_locks[file_path] = threading.Lock()
        return _file_locks[file_path]


class LifeBookWriter:
    """
    LifeBook 写入器
    
    特性：
    - 线程安全：使用文件锁防止并发写入冲突
    - 跨进程安全：使用 filelock 库（如果可用）或降级为线程锁
    """
    
    def __init__(self, root_path: str, encoding: str = "utf-8"):
        """
        初始化写入器
        
        Args:
            root_path: LifeBook根目录路径
            encoding: 文件编码，默认utf-8
        """
        self.root_path = Path(root_path)
        self.encoding = encoding
        
        # 检查是否有 filelock 库可用
        self._has_filelock = False
        try:
            import filelock
            self._has_filelock = True
        except ImportError:
            pass
        
        # 目录结构
        self.daily_dir = self.root_path / "daily"
        self.weekly_dir = self.root_path / "weekly"
        self.monthly_dir = self.root_path / "monthly"
        self.quarterly_dir = self.root_path / "quarterly"
        self.yearly_dir = self.root_path / "yearly"
        self.nodes_dir = self.root_path / "nodes"
        
        # 确保目录存在
        self._ensure_directories()
    
    def _ensure_directories(self):
        """确保所有必要目录存在"""
        for dir_path in [
            self.daily_dir,
            self.weekly_dir,
            self.monthly_dir,
            self.quarterly_dir,
            self.yearly_dir,
            self.nodes_dir
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    # ==================== 日记写入 ====================
    
    def create_diary(
        self,
        date: str,
        content: str,
        title: Optional[str] = None,
        tags: Optional[list] = None,
        overwrite: bool = False
    ) -> bool:
        """
        创建日记
        
        Args:
            date: 日期 YYYY-MM-DD
            content: 日记内容
            title: 标题（可选）
            tags: 标签列表（可选）
            overwrite: 是否覆盖已存在的文件
            
        Returns:
            是否成功
        """
        file_path = self.daily_dir / f"{date}.md"
        
        if file_path.exists() and not overwrite:
            return False
        
        # 构建内容
        full_content = self._build_diary_content(date, content, title, tags)
        
        return self._write_file(file_path, full_content)
    
    def append_to_diary(
        self,
        date: str,
        content: str,
        section: Optional[str] = None,
        create_if_missing: bool = True
    ) -> bool:
        """
        向日记追加内容
        
        Args:
            date: 日期 YYYY-MM-DD
            content: 要追加的内容
            section: 追加到哪个章节（可选，如 "## 今日事件"）
            create_if_missing: 如果日记不存在是否创建
            
        Returns:
            是否成功
        """
        file_path = self.daily_dir / f"{date}.md"
        
        if not file_path.exists():
            if create_if_missing:
                return self.create_diary(date, content)
            return False
        
        # 读取现有内容
        existing = self._read_file(file_path)
        if existing is None:
            return False
        
        # 追加内容
        if section:
            # 使用改进的章节查找方法
            insert_pos = self._find_section_end(existing, section)
            if insert_pos is not None:
                # 在章节末尾插入
                new_content = existing[:insert_pos].rstrip() + "\n\n" + content + "\n" + existing[insert_pos:].lstrip()
            else:
                # 章节不存在，创建它
                new_content = existing.rstrip() + f"\n\n{section}\n\n{content}"
        else:
            # 直接追加到末尾
            new_content = existing.rstrip() + "\n\n" + content
        
        return self._write_file(file_path, new_content)
    
    def update_diary(
        self,
        date: str,
        content: str,
        title: Optional[str] = None,
        tags: Optional[list] = None
    ) -> bool:
        """
        更新/覆盖日记
        
        Args:
            date: 日期 YYYY-MM-DD
            content: 新内容
            title: 新标题（可选）
            tags: 新标签（可选）
            
        Returns:
            是否成功
        """
        return self.create_diary(date, content, title, tags, overwrite=True)
    
    def add_diary_entry_today(self, content: str, section: Optional[str] = None) -> bool:
        """向今天的日记追加内容"""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.append_to_diary(today, content, section)
    
    # ==================== 总结写入 ====================
    
    def create_summary(
        self,
        summary_type: str,
        identifier: str,
        content: str,
        title: Optional[str] = None,
        overwrite: bool = False
    ) -> bool:
        """
        创建总结
        
        Args:
            summary_type: weekly, monthly, quarterly, yearly
            identifier: 标识符，如 2025-W52, 2025-12
            content: 总结内容
            title: 标题（可选）
            overwrite: 是否覆盖
            
        Returns:
            是否成功
        """
        dir_map = {
            "weekly": self.weekly_dir,
            "monthly": self.monthly_dir,
            "quarterly": self.quarterly_dir,
            "yearly": self.yearly_dir
        }
        
        if summary_type not in dir_map:
            return False
        
        file_path = dir_map[summary_type] / f"{identifier}.md"
        
        if file_path.exists() and not overwrite:
            return False
        
        # 构建内容
        full_content = self._build_summary_content(summary_type, identifier, content, title)
        
        return self._write_file(file_path, full_content)
    
    def append_to_summary(
        self,
        summary_type: str,
        identifier: str,
        content: str,
        section: Optional[str] = None
    ) -> bool:
        """
        向总结追加内容
        
        Args:
            summary_type: weekly, monthly, quarterly, yearly
            identifier: 标识符
            content: 要追加的内容
            section: 追加到哪个章节
            
        Returns:
            是否成功
        """
        dir_map = {
            "weekly": self.weekly_dir,
            "monthly": self.monthly_dir,
            "quarterly": self.quarterly_dir,
            "yearly": self.yearly_dir
        }
        
        if summary_type not in dir_map:
            return False
        
        file_path = dir_map[summary_type] / f"{identifier}.md"
        
        if not file_path.exists():
            # 创建新总结
            return self.create_summary(summary_type, identifier, content)
        
        existing = self._read_file(file_path)
        if existing is None:
            return False
        
        if section:
            # 使用改进的章节查找方法
            insert_pos = self._find_section_end(existing, section)
            if insert_pos is not None:
                new_content = existing[:insert_pos].rstrip() + "\n\n" + content + "\n" + existing[insert_pos:].lstrip()
            else:
                new_content = existing.rstrip() + f"\n\n{section}\n\n{content}"
        else:
            new_content = existing.rstrip() + "\n\n" + content
        
        return self._write_file(file_path, new_content)
    
    # ==================== 节点写入 ====================
    
    def create_node(
        self,
        name: str,
        node_type: str,
        content: str,
        tags: Optional[list] = None,
        metadata: Optional[Dict[str, Any]] = None,
        overwrite: bool = False
    ) -> bool:
        """
        创建节点
        
        Args:
            name: 节点名称
            node_type: 类型（人物/地点/事物/概念）
            content: 节点内容
            tags: 标签列表
            metadata: 额外元数据
            overwrite: 是否覆盖
            
        Returns:
            是否成功
        """
        # 文件名格式：类型-名称.md
        filename = f"{node_type}-{name}.md"
        file_path = self.nodes_dir / filename
        
        if file_path.exists() and not overwrite:
            return False
        
        full_content = self._build_node_content(name, node_type, content, tags, metadata)
        
        return self._write_file(file_path, full_content)
    
    def update_node(
        self,
        name: str,
        content: str,
        mode: str = "append"
    ) -> bool:
        """
        更新节点
        
        Args:
            name: 节点名称
            content: 新内容
            mode: "append" 追加, "replace" 替换
            
        Returns:
            是否成功
        """
        # 查找节点文件
        file_path = None
        for f in self.nodes_dir.glob(f"*-{name}.md"):
            file_path = f
            break
        
        if file_path is None:
            file_path = self.nodes_dir / f"{name}.md"
            if not file_path.exists():
                return False
        
        if mode == "replace":
            return self._write_file(file_path, content)
        
        # 追加模式
        existing = self._read_file(file_path)
        if existing is None:
            return False
        
        new_content = existing + "\n\n" + content
        return self._write_file(file_path, new_content)
    
    def add_relation_to_node(
        self,
        name: str,
        relation_type: str,
        target: str
    ) -> bool:
        """
        向节点添加关系
        
        Args:
            name: 节点名称
            relation_type: 关系类型（如 "朋友", "同事", "位于"）
            target: 目标节点名称
            
        Returns:
            是否成功
        """
        relation_content = f"- {relation_type}: [[{target}]]"
        return self.update_node(name, relation_content, mode="append")
    
    # ==================== 辅助方法 ====================
    
    def _build_diary_content(
        self,
        date: str,
        content: str,
        title: Optional[str] = None,
        tags: Optional[list] = None
    ) -> str:
        """构建日记完整内容"""
        parts = []
        
        # Frontmatter
        parts.append("---")
        parts.append(f"date: {date}")
        if title:
            parts.append(f"title: \"{title}\"")
        if tags:
            parts.append(f"tags: [{', '.join(tags)}]")
        parts.append("---")
        parts.append("")
        
        # 标题
        if title:
            parts.append(f"# {title}")
        else:
            parts.append(f"# {date} 日记")
        parts.append("")
        
        # 正文
        parts.append(content)
        
        return "\n".join(parts)
    
    def _build_summary_content(
        self,
        summary_type: str,
        identifier: str,
        content: str,
        title: Optional[str] = None
    ) -> str:
        """构建总结完整内容"""
        type_names = {
            "weekly": "周总结",
            "monthly": "月总结",
            "quarterly": "季度总结",
            "yearly": "年度总结"
        }
        
        parts = []
        
        # Frontmatter
        parts.append("---")
        parts.append(f"type: {summary_type}")
        parts.append(f"identifier: {identifier}")
        parts.append(f"created: {datetime.now().strftime('%Y-%m-%d')}")
        parts.append("---")
        parts.append("")
        
        # 标题
        type_name = type_names.get(summary_type, "总结")
        if title:
            parts.append(f"# {title}")
        else:
            parts.append(f"# {identifier} {type_name}")
        parts.append("")
        
        # 正文
        parts.append(content)
        
        return "\n".join(parts)
    
    def _build_node_content(
        self,
        name: str,
        node_type: str,
        content: str,
        tags: Optional[list] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """构建节点完整内容"""
        parts = []
        
        # Frontmatter
        parts.append("---")
        parts.append(f"name: \"{name}\"")
        parts.append(f"type: {node_type}")
        parts.append(f"created: {datetime.now().strftime('%Y-%m-%d')}")
        if tags:
            parts.append(f"tags: [{', '.join(tags)}]")
        if metadata:
            for key, value in metadata.items():
                parts.append(f"{key}: {value}")
        parts.append("---")
        parts.append("")
        
        # 标题
        parts.append(f"# {name}")
        parts.append("")
        
        # 类型标记
        parts.append(f"> 类型：{node_type}")
        parts.append("")
        
        # 正文
        parts.append(content)
        
        return "\n".join(parts)
    
    def _read_file(self, file_path: Path) -> Optional[str]:
        """读取文件内容"""
        try:
            with open(file_path, "r", encoding=self.encoding) as f:
                return f.read()
        except Exception as e:
            print(f"读取文件失败 {file_path}: {e}")
            return None
    
    def _find_section_end(self, content: str, section: str) -> Optional[int]:
        """
        查找章节的末尾位置（下一个同级或更高级标题之前）
        
        改进的逻辑：
        - 正确处理嵌套标题（子标题不会中断搜索）
        - 处理代码块中的假标题
        - 返回适合插入的位置
        
        Args:
            content: 文件内容
            section: 章节标题（如 "## 今日事件"）
            
        Returns:
            插入位置，或 None 如果章节不存在
        """
        # 提取章节级别
        section_match = re.match(r'^(#+)\s*(.+)$', section.strip())
        if not section_match:
            return None
        
        section_level = len(section_match.group(1))
        section_title = section_match.group(2).strip()
        
        # 按行处理，跟踪代码块状态
        lines = content.split('\n')
        in_code_block = False
        section_start = -1
        
        for i, line in enumerate(lines):
            # 检测代码块
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                continue
            
            if in_code_block:
                continue
            
            # 检测标题
            header_match = re.match(r'^(#+)\s*(.+)$', line)
            if not header_match:
                continue
            
            header_level = len(header_match.group(1))
            header_title = header_match.group(2).strip()
            
            if section_start == -1:
                # 还没找到目标章节
                if header_level == section_level and header_title == section_title:
                    section_start = i
            else:
                # 已找到目标章节，寻找结束位置
                if header_level <= section_level:
                    # 遇到同级或更高级标题，章节结束
                    # 计算该行之前的位置
                    return sum(len(lines[j]) + 1 for j in range(i))
        
        if section_start == -1:
            return None  # 章节不存在
        
        # 章节延续到文件末尾
        return len(content)
    
    @contextmanager
    def _file_lock(self, file_path: Path):
        """
        文件锁上下文管理器
        
        优先使用 filelock 库（跨进程安全），
        如果不可用则降级为线程锁（仅进程内安全）
        """
        file_str = str(file_path.absolute())
        
        if self._has_filelock:
            # 使用 filelock 库
            import filelock
            lock_path = file_path.with_suffix(file_path.suffix + '.lock')
            lock = filelock.FileLock(lock_path, timeout=30)
            try:
                with lock:
                    yield
            finally:
                # 尝试清理锁文件（可选）
                try:
                    if lock_path.exists() and not lock.is_locked:
                        lock_path.unlink()
                except:
                    pass
        else:
            # 降级为线程锁
            lock = _get_file_lock(file_str)
            with lock:
                yield
    
    def _write_file(self, file_path: Path, content: str) -> bool:
        """
        写入文件（带锁保护）
        
        使用文件锁防止并发写入冲突。
        """
        try:
            with self._file_lock(file_path):
                with open(file_path, "w", encoding=self.encoding) as f:
                    f.write(content)
            return True
        except Exception as e:
            print(f"写入文件失败 {file_path}: {e}")
            return False


# 测试代码已移至 tests/test_memory_store.py
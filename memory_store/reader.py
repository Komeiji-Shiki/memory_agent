"""
LifeBook Reader - 读取日记、总结、节点

支持 Obsidian 格式：
- [[链接]] 语法
- #标签 语法
- YAML frontmatter
"""

import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DiaryEntry:
    """日记条目"""
    date: str  # YYYY-MM-DD
    content: str
    title: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    file_path: str = ""


@dataclass
class SummaryEntry:
    """总结条目（周/月/季/年）"""
    type: str  # weekly, monthly, quarterly, yearly
    identifier: str  # 如 2025-W52, 2025-12, 2025-Q4, 2025
    content: str
    title: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    file_path: str = ""


@dataclass
class NodeEntry:
    """节点条目（人物/地点/事物）"""
    name: str
    type: str  # 人物, 地点, 事物, 概念
    content: str
    tags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    file_path: str = ""


class LifeBookReader:
    """LifeBook 读取器"""
    
    def __init__(self, root_path: str, encoding: str = "utf-8"):
        """
        初始化读取器
        
        Args:
            root_path: LifeBook根目录路径
            encoding: 文件编码，默认utf-8
        """
        self.root_path = Path(root_path)
        self.encoding = encoding
        
        # 目录结构
        self.daily_dir = self.root_path / "daily"
        self.weekly_dir = self.root_path / "weekly"
        self.monthly_dir = self.root_path / "monthly"
        self.quarterly_dir = self.root_path / "quarterly"
        self.yearly_dir = self.root_path / "yearly"
        self.nodes_dir = self.root_path / "nodes"
    
    # ==================== 日记读取 ====================
    
    def read_diary(self, date: str) -> Optional[DiaryEntry]:
        """
        读取指定日期的日记
        
        Args:
            date: 日期字符串，格式 YYYY-MM-DD
            
        Returns:
            DiaryEntry 或 None
        """
        file_path = self.daily_dir / f"{date}.md"
        
        if not file_path.exists():
            return None
        
        content = self._read_file(file_path)
        if content is None:
            return None
        
        frontmatter, body = self._parse_frontmatter(content)
        tags = self._extract_tags(body)
        links = self._extract_links(body)
        title = frontmatter.get("title") or self._extract_first_heading(body)
        
        return DiaryEntry(
            date=date,
            content=body,
            title=title,
            tags=tags,
            links=links,
            frontmatter=frontmatter,
            file_path=str(file_path)
        )
    
    def read_diaries_range(
        self, 
        start_date: str, 
        end_date: str
    ) -> List[DiaryEntry]:
        """
        读取日期范围内的所有日记
        
        Args:
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD（包含）
            
        Returns:
            DiaryEntry 列表
        """
        entries = []
        
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        
        current = start
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            entry = self.read_diary(date_str)
            if entry:
                entries.append(entry)
            current += timedelta(days=1)
        
        return entries
    
    def read_recent_diaries(self, days: int = 7) -> List[DiaryEntry]:
        """
        读取最近N天的日记
        
        Args:
            days: 天数，默认7
            
        Returns:
            DiaryEntry 列表（按日期降序）
        """
        today = datetime.now()
        start = today - timedelta(days=days - 1)
        
        entries = self.read_diaries_range(
            start.strftime("%Y-%m-%d"),
            today.strftime("%Y-%m-%d")
        )
        
        # 按日期升序排序（旧→新，时间线顺序）
        entries.sort(key=lambda x: x.date, reverse=False)
        return entries
    
    def list_all_diaries(self) -> List[str]:
        """
        列出所有日记文件的日期
        
        Returns:
            日期列表 ["2025-12-29", "2025-12-28", ...]
        """
        if not self.daily_dir.exists():
            return []
        
        dates = []
        for f in self.daily_dir.glob("*.md"):
            date_str = f.stem  # 文件名不含扩展名
            # 验证日期格式
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
                dates.append(date_str)
            except ValueError:
                continue
        
        dates.sort(reverse=True)
        return dates
    
    # ==================== 总结读取 ====================
    
    def read_summary(self, summary_type: str, identifier: str) -> Optional[SummaryEntry]:
        """
        读取总结
        
        Args:
            summary_type: weekly, monthly, quarterly, yearly
            identifier: 标识符，如 2025-W52, 2025-12, 2025-Q4, 2025
            
        Returns:
            SummaryEntry 或 None
        """
        dir_map = {
            "weekly": self.weekly_dir,
            "monthly": self.monthly_dir,
            "quarterly": self.quarterly_dir,
            "yearly": self.yearly_dir
        }
        
        if summary_type not in dir_map:
            return None
        
        summary_dir = dir_map[summary_type]
        file_path = summary_dir / f"{identifier}.md"
        
        if not file_path.exists():
            return None
        
        content = self._read_file(file_path)
        if content is None:
            return None
        
        _, body = self._parse_frontmatter(content)
        tags = self._extract_tags(body)
        links = self._extract_links(body)
        title = self._extract_first_heading(body)
        
        return SummaryEntry(
            type=summary_type,
            identifier=identifier,
            content=body,
            title=title,
            tags=tags,
            links=links,
            file_path=str(file_path)
        )
    
    def read_current_weekly(self) -> Optional[SummaryEntry]:
        """读取本周总结（ISO 周历）"""
        today = datetime.now()
        # ISO 周历年份可能与日历年份不同
        # 例如：2025-12-29 属于 2026-W01（因为该周的周四在2026年）
        iso_year, week_num, _ = today.isocalendar()
        identifier = f"{iso_year}-W{week_num:02d}"
        return self.read_summary("weekly", identifier)
    
    def read_current_monthly(self) -> Optional[SummaryEntry]:
        """读取本月总结"""
        today = datetime.now()
        identifier = today.strftime("%Y-%m")
        return self.read_summary("monthly", identifier)
    
    def read_current_quarterly(self) -> Optional[SummaryEntry]:
        """读取本季度总结"""
        today = datetime.now()
        quarter = (today.month - 1) // 3 + 1
        identifier = f"{today.year}-Q{quarter}"
        return self.read_summary("quarterly", identifier)
    
    def list_summaries(self, summary_type: str) -> List[str]:
        """
        列出某类总结的所有标识符
        
        Args:
            summary_type: weekly, monthly, quarterly, yearly
            
        Returns:
            标识符列表
        """
        dir_map = {
            "weekly": self.weekly_dir,
            "monthly": self.monthly_dir,
            "quarterly": self.quarterly_dir,
            "yearly": self.yearly_dir
        }
        
        if summary_type not in dir_map:
            return []
        
        summary_dir = dir_map[summary_type]
        if not summary_dir.exists():
            return []
        
        identifiers = [f.stem for f in summary_dir.glob("*.md")]
        identifiers.sort(reverse=True)
        return identifiers
    
    # ==================== 节点读取 ====================
    
    def read_node(self, name: str) -> Optional[NodeEntry]:
        """
        读取节点
        
        Args:
            name: 节点名称（文件名，不含.md）
            
        Returns:
            NodeEntry 或 None
        """
        file_path = self.nodes_dir / f"{name}.md"
        
        if not file_path.exists():
            # 尝试带类型前缀的文件名
            for f in self.nodes_dir.glob(f"*-{name}.md"):
                file_path = f
                break
            else:
                return None
        
        content = self._read_file(file_path)
        if content is None:
            return None
        
        frontmatter, body = self._parse_frontmatter(content)
        tags = self._extract_tags(body)
        links = self._extract_links(body)
        
        # 从文件名或frontmatter推断类型
        node_type = frontmatter.get("type", "未知")
        if "-" in file_path.stem:
            node_type = file_path.stem.split("-")[0]
        
        return NodeEntry(
            name=name,
            type=node_type,
            content=body,
            tags=tags,
            links=links,
            frontmatter=frontmatter,
            file_path=str(file_path)
        )
    
    def list_nodes(self, node_type: Optional[str] = None) -> List[str]:
        """
        列出所有节点
        
        Args:
            node_type: 可选，筛选类型（人物/地点/事物）
            
        Returns:
            节点名称列表
        """
        if not self.nodes_dir.exists():
            return []
        
        nodes = []
        for f in self.nodes_dir.glob("*.md"):
            name = f.stem
            if node_type:
                if name.startswith(f"{node_type}-"):
                    nodes.append(name)
            else:
                nodes.append(name)
        
        nodes.sort()
        return nodes
    
    def search_nodes_by_name(self, query: str) -> List[NodeEntry]:
        """
        按名称搜索节点
        
        Args:
            query: 搜索关键词
            
        Returns:
            匹配的节点列表
        """
        results = []
        for name in self.list_nodes():
            if query.lower() in name.lower():
                node = self.read_node(name)
                if node:
                    results.append(node)
        return results
    
    # ==================== 全局搜索 ====================
    
    def search_all(
        self,
        query: str,
        include_diaries: bool = True,
        include_summaries: bool = True,
        include_nodes: bool = True,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        全局搜索
        
        Args:
            query: 搜索关键词
            include_diaries: 是否搜索日记
            include_summaries: 是否搜索总结
            include_nodes: 是否搜索节点
            date_start: 开始日期（仅日记）
            date_end: 结束日期（仅日记）
            limit: 返回数量限制
            
        Returns:
            搜索结果列表
        """
        results = []
        query_lower = query.lower()
        
        # 搜索日记
        if include_diaries:
            if date_start and date_end:
                diaries = self.read_diaries_range(date_start, date_end)
            else:
                # 默认搜索最近30天
                diaries = self.read_recent_diaries(30)
            
            for diary in diaries:
                if query_lower in diary.content.lower():
                    # 提取匹配的上下文
                    snippet = self._extract_snippet(diary.content, query)
                    results.append({
                        "type": "diary",
                        "date": diary.date,
                        "title": diary.title,
                        "snippet": snippet,
                        "tags": diary.tags,
                        "file_path": diary.file_path
                    })
        
        # 搜索总结
        if include_summaries:
            for summary_type in ["weekly", "monthly", "quarterly", "yearly"]:
                for identifier in self.list_summaries(summary_type)[:10]:  # 每类最多10个
                    summary = self.read_summary(summary_type, identifier)
                    if summary and query_lower in summary.content.lower():
                        snippet = self._extract_snippet(summary.content, query)
                        results.append({
                            "type": f"summary_{summary_type}",
                            "identifier": identifier,
                            "title": summary.title,
                            "snippet": snippet,
                            "file_path": summary.file_path
                        })
        
        # 搜索节点
        if include_nodes:
            for name in self.list_nodes():
                node = self.read_node(name)
                if node and query_lower in node.content.lower():
                    snippet = self._extract_snippet(node.content, query)
                    results.append({
                        "type": f"node_{node.type}",
                        "name": node.name,
                        "snippet": snippet,
                        "tags": node.tags,
                        "file_path": node.file_path
                    })
        
        # 限制返回数量
        return results[:limit]
    
    # ==================== 辅助方法 ====================
    
    def _read_file(self, file_path: Path) -> Optional[str]:
        """读取文件内容"""
        try:
            with open(file_path, "r", encoding=self.encoding) as f:
                return f.read()
        except Exception as e:
            print(f"读取文件失败 {file_path}: {e}")
            return None
    
    def _parse_frontmatter(self, content: str) -> Tuple[Dict[str, Any], str]:
        """
        解析 YAML frontmatter
        
        使用 PyYAML 库解析，支持：
        - 多行值（使用 | 或 > 语法）
        - 列表格式（`tags: [a, b]` 或缩进列表）
        - 嵌套对象
        - 各种 YAML 数据类型
        
        如果 PyYAML 不可用，降级为简单解析。
        
        Returns:
            (frontmatter字典, 正文内容)
        """
        if not content.startswith("---"):
            return {}, content
        
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content
        
        frontmatter_str = parts[1].strip()
        body = parts[2].strip()
        
        # 尝试使用 PyYAML 解析
        try:
            import yaml
            frontmatter = yaml.safe_load(frontmatter_str)
            if frontmatter is None:
                frontmatter = {}
            elif not isinstance(frontmatter, dict):
                # 如果解析结果不是字典，包装为字典
                frontmatter = {"value": frontmatter}
            return frontmatter, body
        except ImportError:
            # PyYAML 未安装，使用简单解析
            pass
        except yaml.YAMLError as e:
            # YAML 解析失败，使用简单解析
            print(f"[Reader] YAML 解析失败，使用简单解析: {e}")
        
        # 降级：简单解析（处理基本 key: value 格式）
        frontmatter = {}
        current_key = None
        current_value_lines = []
        
        for line in frontmatter_str.split("\n"):
            # 检查是否是新的 key: value 行
            if ":" in line and not line.startswith(" ") and not line.startswith("\t"):
                # 保存之前的 key-value
                if current_key is not None:
                    frontmatter[current_key] = self._parse_simple_value(
                        "\n".join(current_value_lines)
                    )
                
                key, value = line.split(":", 1)
                current_key = key.strip()
                current_value_lines = [value.strip()]
            elif current_key is not None:
                # 多行值的续行
                current_value_lines.append(line)
        
        # 保存最后一个 key-value
        if current_key is not None:
            frontmatter[current_key] = self._parse_simple_value(
                "\n".join(current_value_lines)
            )
        
        return frontmatter, body
    
    def _parse_simple_value(self, value: str) -> Any:
        """
        简单值解析（降级模式使用）
        
        处理基本类型：字符串、数字、布尔值、简单列表
        """
        value = value.strip()
        
        if not value:
            return ""
        
        # 去除引号
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            return value[1:-1]
        
        # 检查是否是简单列表 [a, b, c]
        if value.startswith("[") and value.endswith("]"):
            items = value[1:-1].split(",")
            return [item.strip().strip("'\"") for item in items if item.strip()]
        
        # 检查布尔值
        if value.lower() in ("true", "yes", "on"):
            return True
        if value.lower() in ("false", "no", "off"):
            return False
        
        # 检查数字
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            pass
        
        return value
    
    def _extract_tags(self, content: str) -> List[str]:
        """提取 #标签"""
        # 匹配 #标签 但排除 ## 标题
        tags = re.findall(r'(?<![#\w])#(\w+)', content)
        return list(set(tags))
    
    def _extract_links(self, content: str) -> List[str]:
        """提取 [[链接]]"""
        links = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content)
        return list(set(links))
    
    def _extract_first_heading(self, content: str) -> Optional[str]:
        """提取第一个标题"""
        match = re.search(r'^#+ (.+)$', content, re.MULTILINE)
        return match.group(1).strip() if match else None
    
    def _extract_snippet(self, content: str, query: str, context_chars: int = 100) -> str:
        """提取包含关键词的片段"""
        query_lower = query.lower()
        content_lower = content.lower()
        
        pos = content_lower.find(query_lower)
        if pos == -1:
            return content[:200] + "..." if len(content) > 200 else content
        
        start = max(0, pos - context_chars)
        end = min(len(content), pos + len(query) + context_chars)
        
        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        
        return snippet


# 测试代码已移至 tests/test_memory_store.py
"""
Memory Indexer - 记忆索引器

构建和维护记忆的索引：
- 关键词倒排索引
- 标签索引
- 人物关系索引
- 日期索引

支持增量更新和持久化
"""

import os
import re
import json
import logging
from datetime import datetime
from typing import Dict, List, Set, Optional, Any, Tuple
from pathlib import Path
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import jieba  # 中文分词

# 预加载 jieba 词典（启动时执行一次）
# 这会显著减少首次分词的延迟
jieba.initialize()

from .reader import LifeBookReader


@dataclass
class IndexEntry:
    """索引条目"""
    file_path: str
    entry_type: str  # diary, summary_weekly, node_人物, etc.
    date: Optional[str] = None
    title: Optional[str] = None
    snippet: str = ""


@dataclass
class MemoryIndex:
    """记忆索引结构"""
    # 关键词 -> 文件列表
    keywords: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
    
    # 标签 -> 文件列表
    tags: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
    
    # 人物 -> 文件列表（从[[人物]]链接提取）
    people: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
    
    # 日期 -> 文件路径
    dates: Dict[str, str] = field(default_factory=dict)
    
    # 文件路径 -> 元数据
    metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # 索引版本和更新时间
    version: str = "1.0"
    last_updated: str = ""


class MemoryIndexer:
    """记忆索引器"""
    
    def __init__(
        self,
        root_path: str,
        index_file: str = ".memory_index.json",
        encoding: str = "utf-8"
    ):
        """
        初始化索引器
        
        Args:
            root_path: LifeBook根目录
            index_file: 索引文件名
            encoding: 文件编码
        """
        self.root_path = Path(root_path)
        self.index_file_path = self.root_path / index_file  # 改名避免与方法名冲突
        self.encoding = encoding
        self.reader = LifeBookReader(root_path, encoding)
        
        # 加载或创建索引
        self.index = self._load_index()
        
        # 停用词
        self.stopwords = self._load_stopwords()
        
        # 已知人物节点缓存（用于人物识别优化）
        self._known_people_cache: Optional[Set[str]] = None
        self._known_people_cache_time: Optional[float] = None
        self._CACHE_TTL = 300  # 缓存5分钟
        
        # 如果索引为空，自动重建
        if not self.index.metadata:
            logging.info("[索引器] 索引为空，自动重建...")
            self.rebuild_index()
    
    def _load_stopwords(self) -> Set[str]:
        """加载停用词"""
        # 基础停用词
        stopwords = {
            "的", "了", "是", "在", "我", "有", "和", "就",
            "不", "人", "都", "一", "一个", "上", "也", "很",
            "到", "说", "要", "去", "你", "会", "着", "没有",
            "看", "好", "自己", "这", "那", "但", "还", "为",
            "the", "a", "an", "is", "are", "was", "were",
            "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "must", "shall",
            "to", "of", "in", "for", "on", "with", "at",
            "by", "from", "as", "or", "and", "but", "if",
            "then", "else", "when", "up", "out", "so", "no"
        }
        return stopwords
    
    def _load_index(self) -> MemoryIndex:
        """加载索引文件"""
        if self.index_file_path.exists():
            try:
                with open(self.index_file_path, "r", encoding=self.encoding) as f:
                    data = json.load(f)
                    index = MemoryIndex()
                    index.keywords = defaultdict(list, data.get("keywords", {}))
                    index.tags = defaultdict(list, data.get("tags", {}))
                    index.people = defaultdict(list, data.get("people", {}))
                    index.dates = data.get("dates", {})
                    index.metadata = data.get("metadata", {})
                    index.version = data.get("version", "1.0")
                    index.last_updated = data.get("last_updated", "")
                    return index
            except Exception as e:
                logging.error(f"加载索引失败: {e}")
        
        return MemoryIndex()
    
    def save_index(self):
        """保存索引到文件"""
        try:
            data = {
                "keywords": dict(self.index.keywords),
                "tags": dict(self.index.tags),
                "people": dict(self.index.people),
                "dates": self.index.dates,
                "metadata": self.index.metadata,
                "version": self.index.version,
                "last_updated": datetime.now().isoformat()
            }
            with open(self.index_file_path, "w", encoding=self.encoding) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logging.error(f"保存索引失败: {e}")
            return False
    
    def rebuild_index(self):
        """重建完整索引"""
        logging.info("开始重建索引...")
        
        # 清空索引
        self.index = MemoryIndex()
        
        # 索引日记
        self._index_diaries()
        
        # 索引总结
        self._index_summaries()
        
        # 索引节点
        self._index_nodes()
        
        # 保存
        self.save_index()
        logging.info(f"索引重建完成：{len(self.index.keywords)} 个关键词，"
              f"{len(self.index.tags)} 个标签，"
              f"{len(self.index.people)} 个人物")
    
    def _index_diaries(self):
        """索引所有日记"""
        for date in self.reader.list_all_diaries():
            diary = self.reader.read_diary(date)
            if diary:
                self._index_content(
                    file_path=diary.file_path,
                    content=diary.content,
                    entry_type="diary",
                    date=date,
                    title=diary.title,
                    tags=diary.tags,
                    links=diary.links
                )
    
    def _index_summaries(self):
        """索引所有总结"""
        for summary_type in ["weekly", "monthly", "quarterly", "yearly"]:
            for identifier in self.reader.list_summaries(summary_type):
                summary = self.reader.read_summary(summary_type, identifier)
                if summary:
                    self._index_content(
                        file_path=summary.file_path,
                        content=summary.content,
                        entry_type=f"summary_{summary_type}",
                        date=None,
                        title=summary.title,
                        tags=summary.tags,
                        links=summary.links
                    )
    
    def _index_nodes(self):
        """索引所有节点"""
        for name in self.reader.list_nodes():
            node = self.reader.read_node(name)
            if node:
                self._index_content(
                    file_path=node.file_path,
                    content=node.content,
                    entry_type=f"node_{node.type}",
                    date=None,
                    title=node.name,
                    tags=node.tags,
                    links=node.links
                )
                
                # 如果节点类型是"人物"，专门加入人物索引
                if node.type == "人物":
                    # 提取节点名称（去掉类型前缀）
                    person_name = node.name
                    if "-" in name:
                        person_name = name.split("-", 1)[1] if name.startswith("人物-") else name
                    if node.file_path not in self.index.people[person_name]:
                        self.index.people[person_name].append(node.file_path)
    
    def _get_known_people(self) -> Set[str]:
        """
        获取已知人物节点名称（带缓存）
        
        返回不带前缀的人物名称集合，如 {"小明", "小红", ...}
        缓存有效期为 5 分钟
        """
        import time
        now = time.time()
        
        # 检查缓存是否有效
        if (self._known_people_cache is not None and
            self._known_people_cache_time is not None and
            now - self._known_people_cache_time < self._CACHE_TTL):
            return self._known_people_cache
        
        # 重建缓存
        nodes_dir = self.root_path / "nodes"
        known_people = set()
        
        if nodes_dir.exists():
            for f in nodes_dir.iterdir():
                if f.is_file() and f.suffix == ".md" and f.stem.startswith("人物-"):
                    # 提取人物名称（去掉"人物-"前缀）
                    person_name = f.stem[3:]  # len("人物-") = 3
                    known_people.add(person_name)
        
        self._known_people_cache = known_people
        self._known_people_cache_time = now
        return known_people
    
    def invalidate_people_cache(self):
        """手动使人物缓存失效（在添加/删除人物节点后调用）"""
        self._known_people_cache = None
        self._known_people_cache_time = None
    
    def _index_content(
        self,
        file_path: str,
        content: str,
        entry_type: str,
        date: Optional[str],
        title: Optional[str],
        tags: List[str],
        links: List[str]
    ):
        """索引单个内容"""
        # 提取关键词
        keywords = self._extract_keywords(content)
        for kw in keywords:
            if file_path not in self.index.keywords[kw]:
                self.index.keywords[kw].append(file_path)
        
        # 索引标签
        for tag in tags:
            if file_path not in self.index.tags[tag]:
                self.index.tags[tag].append(file_path)
        
        # 获取已知人物列表（使用缓存）
        known_people = self._get_known_people()
        
        # 索引人物链接
        for link in links:
            person_name = None
            
            # 情况1：明确以"人物-"开头的链接
            if link.startswith("人物-"):
                person_name = link[3:]  # 去掉"人物-"前缀
            
            # 情况2：链接名称是已知人物（如 [[小明]] 而不是 [[人物-小明]]）
            elif link in known_people:
                person_name = link
            
            # 添加到人物索引
            if person_name:
                if file_path not in self.index.people[person_name]:
                    self.index.people[person_name].append(file_path)
        
        # 索引日期
        if date:
            self.index.dates[date] = file_path
        
        # 存储元数据
        self.index.metadata[file_path] = {
            "type": entry_type,
            "date": date,
            "title": title,
            "tags": tags,
            "snippet": content[:200] if content else ""
        }
    
    def _extract_keywords(self, content: str, min_length: int = 2) -> List[str]:
        """
        提取关键词
        
        使用jieba分词，过滤停用词和短词
        """
        if not content:
            return []
        
        # 分词
        words = jieba.cut(content)
        
        # 过滤
        keywords = []
        for word in words:
            word = word.strip().lower()
            if (len(word) >= min_length and 
                word not in self.stopwords and
                not word.isdigit() and
                re.match(r'^[\w\u4e00-\u9fff\-]+$', word)): # 允许连字符 -
                keywords.append(word)
        
        return list(set(keywords))
    
    # ==================== 搜索方法 ====================
    
    def search(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        people: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        entry_types: Optional[List[str]] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        搜索记忆
        
        Args:
            query: 搜索关键词
            tags: 筛选标签
            people: 筛选人物
            date_start: 开始日期
            date_end: 结束日期
            entry_types: 筛选类型 (diary, summary_weekly, node_人物, etc.)
            limit: 返回数量限制
            
        Returns:
            搜索结果列表
        """
        # 收集匹配的文件（带评分）
        file_scores: Dict[str, float] = defaultdict(float)
        
        # 1. 直接包含匹配 (针对 ID、日期等特殊格式)
        if query and len(query) >= 3:
            query_lower = query.lower()
            for file_path, meta in self.index.metadata.items():
                # 匹配文件名 (文件名通常包含关键 ID)
                if query_lower in os.path.basename(file_path).lower():
                    file_scores[file_path] += 10.0 # 文件名匹配给予极高权重
                
                # 匹配标题
                title = meta.get("title")
                if title and query_lower in title.lower():
                    file_scores[file_path] += 5.0
                    
                # 匹配日期
                date = meta.get("date")
                if date and query_lower in date.lower():
                    file_scores[file_path] += 5.0

        # 2. 关键词分词匹配
        query_keywords = self._extract_keywords(query) if query else []
        for kw in query_keywords:
            if kw in self.index.keywords:
                for file_path in self.index.keywords[kw]:
                    file_scores[file_path] += 1.0
        
        # 标签匹配（加权）
        if tags:
            for tag in tags:
                if tag in self.index.tags:
                    for file_path in self.index.tags[tag]:
                        file_scores[file_path] += 2.0
        
        # 人物匹配（加权）
        if people:
            for person in people:
                if person in self.index.people:
                    for file_path in self.index.people[person]:
                        file_scores[file_path] += 2.0
        
        # 如果没有关键词但有筛选条件
        if not file_scores and (tags or people):
            candidate_files = set()
            if tags:
                for tag in tags:
                    candidate_files.update(self.index.tags.get(tag, []))
            if people:
                for person in people:
                    candidate_files.update(self.index.people.get(person, []))
            for f in candidate_files:
                file_scores[f] = 1.0
        
        # 过滤和排序
        results = []
        for file_path, score in sorted(file_scores.items(), key=lambda x: -x[1]):
            meta = self.index.metadata.get(file_path, {})
            
            # 类型过滤
            if entry_types and meta.get("type") not in entry_types:
                continue
            
            # 日期过滤
            entry_date = meta.get("date")
            if date_start and entry_date and entry_date < date_start:
                continue
            if date_end and entry_date and entry_date > date_end:
                continue
            
            results.append({
                "file_path": file_path,
                "score": score,
                "type": meta.get("type"),
                "date": entry_date,
                "title": meta.get("title"),
                "tags": meta.get("tags", []),
                "snippet": meta.get("snippet", "")
            })
            
            if len(results) >= limit:
                break
        
        return results
    
    def search_by_tag(self, tag: str, limit: int = 20) -> List[Dict[str, Any]]:
        """按标签搜索"""
        return self.search("", tags=[tag], limit=limit)
    
    def search_by_person(self, person: str, limit: int = 20) -> List[Dict[str, Any]]:
        """按人物搜索"""
        return self.search("", people=[person], limit=limit)
    
    def search_by_date_range(
        self,
        date_start: str,
        date_end: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """按日期范围搜索"""
        results = []
        for date, file_path in self.index.dates.items():
            if date_start <= date <= date_end:
                meta = self.index.metadata.get(file_path, {})
                results.append({
                    "file_path": file_path,
                    "date": date,
                    "type": meta.get("type"),
                    "title": meta.get("title"),
                    "snippet": meta.get("snippet", "")
                })
        
        results.sort(key=lambda x: x["date"], reverse=True)
        return results[:limit]
    
    def get_all_tags(self) -> List[Tuple[str, int]]:
        """获取所有标签及其出现次数"""
        return sorted(
            [(tag, len(files)) for tag, files in self.index.tags.items()],
            key=lambda x: -x[1]
        )
    
    def get_all_people(self) -> List[Tuple[str, int]]:
        """获取所有人物及其出现次数"""
        return sorted(
            [(person, len(files)) for person, files in self.index.people.items()],
            key=lambda x: -x[1]
        )
    
    def get_recent_entries(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取最近N天的条目"""
        from datetime import timedelta
        
        today = datetime.now()
        start_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
        
        return self.search_by_date_range(start_date, end_date)
    
    # ==================== 增量更新 ====================
    
    def index_file(self, file_path: str):
        """索引单个文件（增量更新）"""
        path = Path(file_path)
        
        if not path.exists():
            # 文件被删除，从索引中移除
            self._remove_from_index(file_path)
            return
        
        # 根据路径判断类型并重新索引
        relative_path = path.relative_to(self.root_path) if path.is_absolute() else path
        parts = relative_path.parts
        
        if parts[0] == "daily":
            date = path.stem
            diary = self.reader.read_diary(date)
            if diary:
                self._remove_from_index(file_path)
                self._index_content(
                    file_path=str(path),
                    content=diary.content,
                    entry_type="diary",
                    date=date,
                    title=diary.title,
                    tags=diary.tags,
                    links=diary.links
                )
        
        elif parts[0] in ["weekly", "monthly", "quarterly", "yearly"]:
            summary_type = parts[0]
            identifier = path.stem
            summary = self.reader.read_summary(summary_type, identifier)
            if summary:
                self._remove_from_index(file_path)
                self._index_content(
                    file_path=str(path),
                    content=summary.content,
                    entry_type=f"summary_{summary_type}",
                    date=None,
                    title=summary.title,
                    tags=summary.tags,
                    links=summary.links
                )
        
        elif parts[0] == "nodes":
            name = path.stem
            node = self.reader.read_node(name)
            if node:
                self._remove_from_index(file_path)
                self._index_content(
                    file_path=str(path),
                    content=node.content,
                    entry_type=f"node_{node.type}",
                    date=None,
                    title=node.name,
                    tags=node.tags,
                    links=node.links
                )
        
        self.save_index()
    
    def _remove_from_index(self, file_path: str):
        """从索引中移除文件"""
        # 从关键词索引移除
        for kw in list(self.index.keywords.keys()):
            if file_path in self.index.keywords[kw]:
                self.index.keywords[kw].remove(file_path)
                if not self.index.keywords[kw]:
                    del self.index.keywords[kw]
        
        # 从标签索引移除
        for tag in list(self.index.tags.keys()):
            if file_path in self.index.tags[tag]:
                self.index.tags[tag].remove(file_path)
                if not self.index.tags[tag]:
                    del self.index.tags[tag]
        
        # 从人物索引移除
        for person in list(self.index.people.keys()):
            if file_path in self.index.people[person]:
                self.index.people[person].remove(file_path)
                if not self.index.people[person]:
                    del self.index.people[person]
        
        # 从日期索引移除
        for date, path in list(self.index.dates.items()):
            if path == file_path:
                del self.index.dates[date]
                break
        
        # 从元数据移除
        if file_path in self.index.metadata:
            del self.index.metadata[file_path]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        type_counts = defaultdict(int)
        for meta in self.index.metadata.values():
            type_counts[meta.get("type", "unknown")] += 1
        
        return {
            "total_files": len(self.index.metadata),
            "total_keywords": len(self.index.keywords),
            "total_tags": len(self.index.tags),
            "total_people": len(self.index.people),
            "total_dates": len(self.index.dates),
            "by_type": dict(type_counts),
            "last_updated": self.index.last_updated
        }


# 测试代码已移至 tests/test_memory_store.py
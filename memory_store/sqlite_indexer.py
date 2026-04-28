"""
SQLite Memory Indexer - SQLite记忆索引器

使用SQLite替代JSON存储索引，提供：
- 更好的性能（增量更新，无需完整加载）
- 支持并发读取
- 原子性写入（事务保护）
- 高效查询（SQL索引）

保持与 MemoryIndexer 相同的公开接口
"""

import os
import re
import sqlite3
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Any, Tuple
from pathlib import Path
from contextlib import contextmanager
import jieba

# 预加载 jieba 词典
jieba.initialize()

from .reader import LifeBookReader


class SqliteIndexer:
    """SQLite记忆索引器 - MemoryIndexer 的高性能替代"""
    
    # 数据库版本，用于未来升级
    DB_VERSION = "1.0"
    
    def __init__(
        self,
        root_path: str,
        db_file: str = ".memory_index.db",
        encoding: str = "utf-8"
    ):
        """
        初始化索引器
        
        Args:
            root_path: LifeBook根目录
            db_file: 数据库文件名
            encoding: 文件编码
        """
        # 统一使用绝对路径，避免工作目录变化导致索引/文件存在性判断异常
        self.root_path = Path(root_path).resolve()
        self.db_path = self.root_path / db_file
        self.encoding = encoding
        self.reader = LifeBookReader(str(self.root_path), encoding)
        
        # 停用词
        self.stopwords = self._load_stopwords()
        
        # 已知人物节点缓存（用于人物识别优化）
        self._known_people_cache: Optional[Set[str]] = None
        self._known_people_cache_time: Optional[float] = None
        self._CACHE_TTL = 300  # 缓存5分钟
        
        # 初始化数据库
        self._init_db()
        
        # 如果索引为空，自动重建
        if self._is_empty():
            logging.info("[SQLite索引器] 索引为空，自动重建...")
            self.rebuild_index()
    
    def _load_stopwords(self) -> Set[str]:
        """加载停用词"""
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
    
    @contextmanager
    def _get_connection(self, readonly: bool = False):
        """获取数据库连接（上下文管理器）"""
        # SQLite URI 模式允许只读连接
        if readonly:
            uri = f"file:{self.db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
        else:
            conn = sqlite3.connect(str(self.db_path))
        
        conn.row_factory = sqlite3.Row
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        
        try:
            yield conn
            if not readonly:
                conn.commit()
        except Exception:
            if not readonly:
                conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_db(self):
        """初始化数据库表结构"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 文件元数据表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    type TEXT NOT NULL,
                    date TEXT,
                    title TEXT,
                    snippet TEXT,
                    tags_json TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_type ON files(type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_date ON files(date)")
            
            # 关键词倒排索引表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    word TEXT NOT NULL,
                    file_id INTEGER NOT NULL,
                    weight REAL DEFAULT 1.0,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    UNIQUE(word, file_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_keywords_word ON keywords(word)")
            
            # 标签表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    file_id INTEGER NOT NULL,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    UNIQUE(name, file_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name)")
            
            # 人物关联表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS people (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    file_id INTEGER NOT NULL,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    UNIQUE(name, file_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_people_name ON people(name)")
            
            # 链接表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_file_id INTEGER NOT NULL,
                    target TEXT NOT NULL,
                    FOREIGN KEY (source_file_id) REFERENCES files(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_file_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_links_target ON links(target)")
            
            # 元数据版本表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            
            # 初始化版本信息
            cursor.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("version", self.DB_VERSION)
            )
            cursor.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("last_updated", "")
            )
    
    def _is_empty(self) -> bool:
        """检查索引是否为空"""
        with self._get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM files")
            return cursor.fetchone()[0] == 0
    
    def _to_relative_path(self, file_path: str) -> str:
        """将路径转换为相对于 root_path 的路径"""
        path = Path(file_path)
        
        # 1. 尝试用 relative_to 处理（适用于绝对路径或包含完整root的相对路径）
        try:
            if path.is_absolute():
                return str(path.relative_to(self.root_path)).replace("\\", "/")
            else:
                # 检查相对路径是否已经包含 root_path 的目录名
                # 例如：Path("./lifebook") 的 name 是 "lifebook"
                # 如果 file_path 是 "lifebook/daily/2025-01-01.md"，需要去掉 "lifebook/"
                path_str = str(path).replace("\\", "/")
                root_name = self.root_path.name
                
                # 处理各种可能的前缀格式
                prefixes_to_remove = [
                    f"{root_name}/",      # lifebook/
                    f"./{root_name}/",    # ./lifebook/
                ]
                
                for prefix in prefixes_to_remove:
                    if path_str.startswith(prefix):
                        return path_str[len(prefix):]
                
                # 如果不包含 root_path 前缀，直接返回
                return path_str
        except ValueError:
            # 如果不在 root_path 下，保持原样
            return str(path).replace("\\", "/")
    
    def _to_absolute_path(self, relative_path: str) -> str:
        """将相对路径转换为绝对路径"""
        return str(self.root_path / relative_path)
    
    # ==================== 重建索引 ====================
    
    def rebuild_index(self):
        """重建完整索引"""
        # 重建前强制失效人物缓存，避免 people 识别使用过期数据
        self.invalidate_people_cache()

        logging.info("开始重建SQLite索引...")
        start_time = time.time()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 清空所有表
            cursor.execute("DELETE FROM links")
            cursor.execute("DELETE FROM people")
            cursor.execute("DELETE FROM tags")
            cursor.execute("DELETE FROM keywords")
            cursor.execute("DELETE FROM files")
            
            # 重置自增计数器
            cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('files', 'keywords', 'tags', 'people', 'links')")
            
            # 索引日记
            self._index_diaries(cursor)
            
            # 索引总结
            self._index_summaries(cursor)
            
            # 索引节点
            self._index_nodes(cursor)
            
            # 更新最后更新时间
            cursor.execute(
                "UPDATE meta SET value = ? WHERE key = 'last_updated'",
                (datetime.now().isoformat(),)
            )
        
        elapsed = time.time() - start_time
        stats = self.get_stats()
        logging.info(
            f"SQLite索引重建完成（{elapsed:.2f}秒）：{stats['total_files']} 个文件，"
            f"{stats['total_keywords']} 个关键词，{stats['total_tags']} 个标签，"
            f"{stats['total_people']} 个人物"
        )
    
    def _index_diaries(self, cursor: sqlite3.Cursor):
        """索引所有日记"""
        for date in self.reader.list_all_diaries():
            diary = self.reader.read_diary(date)
            if diary:
                self._index_content(
                    cursor=cursor,
                    file_path=diary.file_path,
                    content=diary.content,
                    entry_type="diary",
                    date=date,
                    title=diary.title,
                    tags=diary.tags,
                    links=diary.links
                )
    
    def _index_summaries(self, cursor: sqlite3.Cursor):
        """索引所有总结"""
        for summary_type in ["weekly", "monthly", "quarterly", "yearly"]:
            for identifier in self.reader.list_summaries(summary_type):
                summary = self.reader.read_summary(summary_type, identifier)
                if summary:
                    self._index_content(
                        cursor=cursor,
                        file_path=summary.file_path,
                        content=summary.content,
                        entry_type=f"summary_{summary_type}",
                        date=None,
                        title=summary.title,
                        tags=summary.tags,
                        links=summary.links
                    )
    
    def _index_nodes(self, cursor: sqlite3.Cursor):
        """索引所有节点"""
        for name in self.reader.list_nodes():
            node = self.reader.read_node(name)
            if node:
                self._index_content(
                    cursor=cursor,
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
                    person_name = node.name
                    if "-" in name:
                        person_name = name.split("-", 1)[1] if name.startswith("人物-") else name
                    
                    # 获取刚插入的文件ID
                    rel_path = self._to_relative_path(node.file_path)
                    cursor.execute("SELECT id FROM files WHERE path = ?", (rel_path,))
                    row = cursor.fetchone()
                    if row:
                        cursor.execute(
                            "INSERT OR IGNORE INTO people (name, file_id) VALUES (?, ?)",
                            (person_name, row['id'])
                        )
    
    def _get_known_people(self) -> Set[str]:
        """获取已知人物节点名称（带缓存）"""
        now = time.time()
        
        if (self._known_people_cache is not None and
            self._known_people_cache_time is not None and
            now - self._known_people_cache_time < self._CACHE_TTL):
            return self._known_people_cache
        
        nodes_dir = self.root_path / "nodes"
        known_people = set()
        
        if nodes_dir.exists():
            for f in nodes_dir.iterdir():
                if f.is_file() and f.suffix == ".md" and f.stem.startswith("人物-"):
                    person_name = f.stem[3:]
                    known_people.add(person_name)
        
        self._known_people_cache = known_people
        self._known_people_cache_time = now
        return known_people
    
    def invalidate_people_cache(self):
        """手动使人物缓存失效"""
        self._known_people_cache = None
        self._known_people_cache_time = None
    
    def _index_content(
        self,
        cursor: sqlite3.Cursor,
        file_path: str,
        content: str,
        entry_type: str,
        date: Optional[str],
        title: Optional[str],
        tags: List[str],
        links: List[str]
    ):
        """索引单个内容"""
        import json
        
        # 转换为相对路径
        rel_path = self._to_relative_path(file_path)
        
        # 插入文件元数据
        cursor.execute("""
            INSERT OR REPLACE INTO files (path, type, date, title, snippet, tags_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            rel_path,
            entry_type,
            date,
            title,
            content[:200] if content else "",
            json.dumps(tags, ensure_ascii=False),
            datetime.now().isoformat()
        ))
        
        file_id = cursor.lastrowid
        
        # 索引关键词
        keywords = self._extract_keywords(content)
        for kw in keywords:
            cursor.execute(
                "INSERT OR IGNORE INTO keywords (word, file_id) VALUES (?, ?)",
                (kw, file_id)
            )
        
        # 索引标签
        for tag in tags:
            cursor.execute(
                "INSERT OR IGNORE INTO tags (name, file_id) VALUES (?, ?)",
                (tag, file_id)
            )
        
        # 获取已知人物
        known_people = self._get_known_people()
        
        # 索引人物链接
        for link in links:
            person_name = None
            
            if link.startswith("人物-"):
                person_name = link[3:]
            elif link in known_people:
                person_name = link
            
            if person_name:
                cursor.execute(
                    "INSERT OR IGNORE INTO people (name, file_id) VALUES (?, ?)",
                    (person_name, file_id)
                )
            
            # 记录所有链接
            cursor.execute(
                "INSERT INTO links (source_file_id, target) VALUES (?, ?)",
                (file_id, link)
            )
    
    def _extract_keywords(self, content: str, min_length: int = 2) -> List[str]:
        """提取关键词"""
        if not content:
            return []
        
        words = jieba.cut(content)
        
        keywords = []
        for word in words:
            word = word.strip().lower()
            if (len(word) >= min_length and 
                word not in self.stopwords and
                not word.isdigit() and
                re.match(r'^[\w\u4e00-\u9fff\-]+$', word)):
                keywords.append(word)
        
        return list(set(keywords))
    
    # ==================== 增量更新 ====================
    
    def index_file(self, file_path: str):
        """索引单个文件（增量更新）

        支持传入：
        - 绝对路径：.../lifebook/daily/2025-01-01.md
        - 相对 lifebook 根目录：daily/2025-01-01.md
        - 带根目录前缀的相对路径：lifebook/daily/2025-01-01.md 或 ./lifebook/daily/...
        """
        raw_path = Path(file_path)

        # 统一转换为相对于 root_path 的路径（修复传入 lifebook/xxx 导致类型判断失败的问题）
        rel_path_str = self._to_relative_path(str(raw_path))
        rel_path = Path(rel_path_str)

        parts = rel_path.parts
        if not parts:
            return

        top_dir = parts[0]
        indexable_dirs = {"daily", "weekly", "monthly", "quarterly", "yearly", "nodes"}
        if top_dir not in indexable_dirs:
            # 避免误删/误索引非 LifeBook 核心目录的文件
            return

        # 统一得到绝对路径（避免工作目录变化导致 exists 判断失效）
        abs_path = self.root_path / rel_path

        if not abs_path.exists():
            self._remove_from_index(file_path)
            return

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 先删除旧记录（ON DELETE CASCADE 会自动清理关联表）
            self._remove_from_index_internal(cursor, file_path)

            if top_dir == "daily":
                date = rel_path.stem
                diary = self.reader.read_diary(date)
                if diary:
                    self._index_content(
                        cursor=cursor,
                        file_path=str(abs_path),
                        content=diary.content,
                        entry_type="diary",
                        date=date,
                        title=diary.title,
                        tags=diary.tags,
                        links=diary.links
                    )

            elif top_dir in ["weekly", "monthly", "quarterly", "yearly"]:
                summary_type = top_dir
                identifier = rel_path.stem
                summary = self.reader.read_summary(summary_type, identifier)
                if summary:
                    self._index_content(
                        cursor=cursor,
                        file_path=str(abs_path),
                        content=summary.content,
                        entry_type=f"summary_{summary_type}",
                        date=None,
                        title=summary.title,
                        tags=summary.tags,
                        links=summary.links
                    )

            elif top_dir == "nodes":
                name = rel_path.stem
                node = self.reader.read_node(name)
                if node:
                    self._index_content(
                        cursor=cursor,
                        file_path=str(abs_path),
                        content=node.content,
                        entry_type=f"node_{node.type}",
                        date=None,
                        title=node.name,
                        tags=node.tags,
                        links=node.links
                    )

                    # 增量索引时，对人物节点也要写入 people 表（与 rebuild_index 行为一致）
                    if node.type == "人物":
                        person_name = name
                        if name.startswith("人物-"):
                            person_name = name.split("-", 1)[1]

                        rel_db_path = self._to_relative_path(str(abs_path))
                        cursor.execute("SELECT id FROM files WHERE path = ?", (rel_db_path,))
                        row = cursor.fetchone()
                        if row:
                            cursor.execute(
                                "INSERT OR IGNORE INTO people (name, file_id) VALUES (?, ?)",
                                (person_name, row["id"])
                            )

            # 更新最后更新时间
            cursor.execute(
                "UPDATE meta SET value = ? WHERE key = 'last_updated'",
                (datetime.now().isoformat(),)
            )
    
    def _remove_from_index(self, file_path: str):
        """从索引中移除文件（公开方法）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            self._remove_from_index_internal(cursor, file_path)
    
    def _remove_from_index_internal(self, cursor: sqlite3.Cursor, file_path: str):
        """从索引中移除文件（内部方法）"""
        rel_path = self._to_relative_path(file_path)
        
        # 由于设置了 ON DELETE CASCADE，只需删除 files 记录
        # 其他关联记录会自动删除
        cursor.execute("DELETE FROM files WHERE path = ?", (rel_path,))
    
    def save_index(self):
        """保存索引（SQLite版本为空操作，自动保存）"""
        # SQLite 使用事务自动保存，此方法保持兼容性
        pass
    
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
        """搜索记忆"""
        import json
        
        with self._get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            
            # 收集匹配的文件ID及评分
            file_scores: Dict[int, float] = {}
            
            # 1. 直接包含匹配
            if query and len(query) >= 3:
                query_lower = query.lower()
                
                # 文件名匹配
                cursor.execute("""
                    SELECT id FROM files 
                    WHERE LOWER(path) LIKE ? OR LOWER(title) LIKE ? OR date LIKE ?
                """, (f"%{query_lower}%", f"%{query_lower}%", f"%{query_lower}%"))
                
                for row in cursor.fetchall():
                    file_scores[row['id']] = file_scores.get(row['id'], 0) + 10.0
            
            # 2. 关键词分词匹配
            if query:
                query_keywords = self._extract_keywords(query)
                for kw in query_keywords:
                    cursor.execute("""
                        SELECT file_id FROM keywords WHERE word = ?
                    """, (kw,))
                    for row in cursor.fetchall():
                        file_scores[row['file_id']] = file_scores.get(row['file_id'], 0) + 1.0
            
            # 3. 标签匹配
            if tags:
                for tag in tags:
                    cursor.execute("""
                        SELECT file_id FROM tags WHERE name = ?
                    """, (tag,))
                    for row in cursor.fetchall():
                        file_scores[row['file_id']] = file_scores.get(row['file_id'], 0) + 2.0
            
            # 4. 人物匹配
            if people:
                for person in people:
                    cursor.execute("""
                        SELECT file_id FROM people WHERE name = ?
                    """, (person,))
                    for row in cursor.fetchall():
                        file_scores[row['file_id']] = file_scores.get(row['file_id'], 0) + 2.0
            
            # 5. 如果没有关键词但有筛选条件
            if not file_scores and (tags or people):
                if tags:
                    placeholders = ",".join("?" * len(tags))
                    cursor.execute(f"""
                        SELECT DISTINCT file_id FROM tags WHERE name IN ({placeholders})
                    """, tags)
                    for row in cursor.fetchall():
                        file_scores[row['file_id']] = 1.0
                
                if people:
                    placeholders = ",".join("?" * len(people))
                    cursor.execute(f"""
                        SELECT DISTINCT file_id FROM people WHERE name IN ({placeholders})
                    """, people)
                    for row in cursor.fetchall():
                        file_scores[row['file_id']] = file_scores.get(row['file_id'], 0) + 1.0
            
            # 获取文件详情并过滤
            results = []
            sorted_files = sorted(file_scores.items(), key=lambda x: -x[1])
            
            for file_id, score in sorted_files:
                cursor.execute("""
                    SELECT path, type, date, title, snippet, tags_json 
                    FROM files WHERE id = ?
                """, (file_id,))
                row = cursor.fetchone()
                
                if not row:
                    continue
                
                # 类型过滤
                if entry_types and row['type'] not in entry_types:
                    continue
                
                # 日期过滤
                entry_date = row['date']
                if date_start and entry_date and entry_date < date_start:
                    continue
                if date_end and entry_date and entry_date > date_end:
                    continue
                
                # 解析标签
                try:
                    tags_list = json.loads(row['tags_json']) if row['tags_json'] else []
                except json.JSONDecodeError:
                    tags_list = []
                
                results.append({
                    "file_path": self._to_absolute_path(row['path']),
                    "score": score,
                    "type": row['type'],
                    "date": entry_date,
                    "title": row['title'],
                    "tags": tags_list,
                    "snippet": row['snippet'] or ""
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
        import json
        
        with self._get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT path, type, date, title, snippet, tags_json
                FROM files 
                WHERE date IS NOT NULL AND date >= ? AND date <= ?
                ORDER BY date DESC
                LIMIT ?
            """, (date_start, date_end, limit))
            
            results = []
            for row in cursor.fetchall():
                try:
                    tags_list = json.loads(row['tags_json']) if row['tags_json'] else []
                except json.JSONDecodeError:
                    tags_list = []
                
                results.append({
                    "file_path": self._to_absolute_path(row['path']),
                    "date": row['date'],
                    "type": row['type'],
                    "title": row['title'],
                    "snippet": row['snippet'] or "",
                    "tags": tags_list
                })
            
            return results
    
    def get_recent_entries(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取最近N天的条目"""
        today = datetime.now()
        start_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
        
        return self.search_by_date_range(start_date, end_date)
    
    # ==================== 统计方法 ====================
    
    def get_all_tags(self) -> List[Tuple[str, int]]:
        """获取所有标签及其出现次数"""
        with self._get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT name, COUNT(*) as cnt 
                FROM tags 
                GROUP BY name 
                ORDER BY cnt DESC
            """)
            
            return [(row['name'], row['cnt']) for row in cursor.fetchall()]
    
    def get_all_people(self) -> List[Tuple[str, int]]:
        """获取所有人物及其出现次数"""
        with self._get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT name, COUNT(*) as cnt 
                FROM people 
                GROUP BY name 
                ORDER BY cnt DESC
            """)
            
            return [(row['name'], row['cnt']) for row in cursor.fetchall()]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        with self._get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            
            # 文件数量
            cursor.execute("SELECT COUNT(*) FROM files")
            total_files = cursor.fetchone()[0]
            
            # 关键词数量（去重）
            cursor.execute("SELECT COUNT(DISTINCT word) FROM keywords")
            total_keywords = cursor.fetchone()[0]
            
            # 标签数量（去重）
            cursor.execute("SELECT COUNT(DISTINCT name) FROM tags")
            total_tags = cursor.fetchone()[0]
            
            # 人物数量（去重）
            cursor.execute("SELECT COUNT(DISTINCT name) FROM people")
            total_people = cursor.fetchone()[0]
            
            # 日期条目数量
            cursor.execute("SELECT COUNT(*) FROM files WHERE date IS NOT NULL")
            total_dates = cursor.fetchone()[0]
            
            # 按类型统计
            cursor.execute("""
                SELECT type, COUNT(*) as cnt 
                FROM files 
                GROUP BY type
            """)
            by_type = {row['type']: row['cnt'] for row in cursor.fetchall()}
            
            # 最后更新时间
            cursor.execute("SELECT value FROM meta WHERE key = 'last_updated'")
            row = cursor.fetchone()
            last_updated = row['value'] if row else ""
            
            return {
                "total_files": total_files,
                "total_keywords": total_keywords,
                "total_tags": total_tags,
                "total_people": total_people,
                "total_dates": total_dates,
                "by_type": by_type,
                "last_updated": last_updated
            }
    
    # ==================== 兼容性属性 ====================
    
    @property
    def index(self):
        """
        兼容性属性：返回一个模拟 MemoryIndex 的对象
        
        警告：这会加载全部数据到内存，仅用于向后兼容
        """
        return _CompatibilityIndex(self)


class _CompatibilityIndex:
    """
    兼容性包装器，模拟 MemoryIndex 的行为
    
    用于需要直接访问 indexer.index.xxx 的旧代码
    """
    
    def __init__(self, indexer: SqliteIndexer):
        self._indexer = indexer
    
    @property
    def tags(self) -> Dict[str, List[str]]:
        """获取标签字典（兼容用）"""
        import json
        result = {}
        
        with self._indexer._get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.name, f.path 
                FROM tags t 
                JOIN files f ON t.file_id = f.id
            """)
            for row in cursor.fetchall():
                tag = row['name']
                path = self._indexer._to_absolute_path(row['path'])
                if tag not in result:
                    result[tag] = []
                result[tag].append(path)
        
        return result
    
    @property
    def people(self) -> Dict[str, List[str]]:
        """获取人物字典（兼容用）"""
        result = {}
        
        with self._indexer._get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.name, f.path 
                FROM people p 
                JOIN files f ON p.file_id = f.id
            """)
            for row in cursor.fetchall():
                person = row['name']
                path = self._indexer._to_absolute_path(row['path'])
                if person not in result:
                    result[person] = []
                result[person].append(path)
        
        return result
    
    @property
    def metadata(self) -> Dict[str, Dict[str, Any]]:
        """获取元数据字典（兼容用）"""
        import json
        result = {}
        
        with self._indexer._get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT path, type, date, title, snippet, tags_json 
                FROM files
            """)
            for row in cursor.fetchall():
                path = self._indexer._to_absolute_path(row['path'])
                try:
                    tags = json.loads(row['tags_json']) if row['tags_json'] else []
                except json.JSONDecodeError:
                    tags = []
                
                result[path] = {
                    "type": row['type'],
                    "date": row['date'],
                    "title": row['title'],
                    "tags": tags,
                    "snippet": row['snippet'] or ""
                }
        
        return result


# 测试代码
if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    # 测试用
    if len(sys.argv) > 1:
        test_path = sys.argv[1]
    else:
        test_path = "./lifebook"
    
    print(f"测试 SQLite 索引器: {test_path}")
    indexer = SqliteIndexer(test_path)
    
    print("\n统计信息:")
    stats = indexer.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")
    
    print("\n标签:")
    for tag, count in indexer.get_all_tags()[:5]:
        print(f"  #{tag}: {count}")
    
    print("\n人物:")
    for person, count in indexer.get_all_people()[:5]:
        print(f"  [[{person}]]: {count}")
    
    print("\n搜索 '主人':")
    results = indexer.search("主人", limit=3)
    for r in results:
        print(f"  - {r['title'] or r['file_path']}")
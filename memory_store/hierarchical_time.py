"""
层级时间索引

借鉴 LingYi 的层级时间节点设计，在 Graphiti 之上构建辅助时间索引。

设计思路：
- 不修改 Graphiti 核心
- 维护一个 SQLite 辅助表
- 与 Graphiti 的 valid_at 同步
- 支持按年/月/日/周期查询

层级结构：
    Year("2024年")
      ↑ BELONGS_TO
    Month("12月", time="2024年12月")
      ↑ BELONGS_TO
    Day("25日", time="2024年12月25日")

使用方式：
    index = HierarchicalTimeIndex("./time_index.db")
    
    # 索引边的时间
    index.index_edge(edge_uuid, valid_at, raw_time)
    
    # 按年查询
    edge_uuids = index.query_by_year(2024)
    
    # 按月查询
    edge_uuids = index.query_by_month(2024, 12)
    
    # 查询周期性事件
    edge_uuids = index.query_recurring(month=12, day=25)
"""

from __future__ import annotations

import sqlite3
import re
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TimeType(Enum):
    """时间类型枚举"""
    STATIC = "static"           # 静态时间点
    RECURRING = "recurring"     # 周期性事件
    RANGE = "range"             # 时间范围
    FUZZY = "fuzzy"             # 模糊时间


class RecurrencePattern(Enum):
    """周期模式枚举"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    CUSTOM = "custom"


@dataclass
class TimeInfo:
    """时间信息"""
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    hour: Optional[int] = None
    minute: Optional[int] = None
    weekday: Optional[int] = None  # 0=Monday, 6=Sunday
    time_type: TimeType = TimeType.STATIC
    recurrence_pattern: Optional[RecurrencePattern] = None
    raw_text: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "hour": self.hour,
            "minute": self.minute,
            "weekday": self.weekday,
            "time_type": self.time_type.value,
            "recurrence_pattern": self.recurrence_pattern.value if self.recurrence_pattern else None,
            "raw_text": self.raw_text,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'TimeInfo':
        return cls(
            year=d.get("year"),
            month=d.get("month"),
            day=d.get("day"),
            hour=d.get("hour"),
            minute=d.get("minute"),
            weekday=d.get("weekday"),
            time_type=TimeType(d.get("time_type", "static")),
            recurrence_pattern=RecurrencePattern(d["recurrence_pattern"]) if d.get("recurrence_pattern") else None,
            raw_text=d.get("raw_text", ""),
        )
    
    @classmethod
    def from_datetime(cls, dt: datetime, raw_text: str = "") -> 'TimeInfo':
        return cls(
            year=dt.year,
            month=dt.month,
            day=dt.day,
            hour=dt.hour,
            minute=dt.minute,
            weekday=dt.weekday(),
            time_type=TimeType.STATIC,
            raw_text=raw_text,
        )


class ChineseTimeExtractor:
    """
    中文时间提取器
    
    支持多种中文时间表达方式
    """
    
    # 周期性时间模式
    RECURRING_PATTERNS = [
        (r"每天", RecurrencePattern.DAILY),
        (r"每日", RecurrencePattern.DAILY),
        (r"每周", RecurrencePattern.WEEKLY),
        (r"每月", RecurrencePattern.MONTHLY),
        (r"每年", RecurrencePattern.YEARLY),
        (r"每逢", RecurrencePattern.CUSTOM),
    ]
    
    # 星期映射
    WEEKDAY_MAP = {
        "一": 0, "二": 1, "三": 2, "四": 3, 
        "五": 4, "六": 5, "日": 6, "天": 6,
    }
    
    def extract(self, text: str) -> TimeInfo:
        """
        从文本中提取时间信息
        
        Args:
            text: 中文时间文本
        
        Returns:
            TimeInfo 对象
        """
        info = TimeInfo(raw_text=text)
        
        # 检查周期性
        for pattern, recurrence in self.RECURRING_PATTERNS:
            if re.search(pattern, text):
                info.time_type = TimeType.RECURRING
                info.recurrence_pattern = recurrence
                break
        
        # 提取年份
        year_match = re.search(r"(\d{4})年", text)
        if year_match:
            info.year = int(year_match.group(1))
        
        # 提取月份
        month_match = re.search(r"(\d{1,2})月", text)
        if month_match:
            info.month = int(month_match.group(1))
        
        # 提取日期
        day_match = re.search(r"(\d{1,2})[日号]", text)
        if day_match:
            info.day = int(day_match.group(1))
        
        # 提取时间
        hour_match = re.search(r"(\d{1,2})[点时]", text)
        if hour_match:
            info.hour = int(hour_match.group(1))
        
        minute_match = re.search(r"(\d{1,2})分", text)
        if minute_match:
            info.minute = int(minute_match.group(1))
        
        # 提取星期
        weekday_match = re.search(r"(?:星期|周)([一二三四五六日天])", text)
        if weekday_match:
            info.weekday = self.WEEKDAY_MAP.get(weekday_match.group(1))
        
        # 判断是否为模糊时间
        fuzzy_patterns = ["最近", "前几天", "上个月", "去年", "以前", "之前", "曾经"]
        if any(p in text for p in fuzzy_patterns) and not info.year:
            info.time_type = TimeType.FUZZY
        
        return info
    
    def to_datetime(self, info: TimeInfo, reference: Optional[datetime] = None) -> Optional[datetime]:
        """
        将 TimeInfo 转换为 datetime
        
        Args:
            info: TimeInfo 对象
            reference: 参考时间（用于补全缺失部分）
        
        Returns:
            datetime 或 None
        """
        reference = reference or datetime.now()
        
        if info.time_type == TimeType.RECURRING:
            # 周期性事件，使用今年的日期
            year = reference.year
        else:
            year = info.year or reference.year
        
        month = info.month or 1
        day = info.day or 1
        hour = info.hour or 0
        minute = info.minute or 0
        
        try:
            return datetime(year, month, day, hour, minute)
        except ValueError:
            return None


class HierarchicalTimeIndex:
    """
    层级时间索引
    
    使用 SQLite 存储时间索引，支持高效的时间范围查询
    """
    
    def __init__(self, db_path: str):
        """
        初始化时间索引
        
        Args:
            db_path: SQLite 数据库路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.extractor = ChineseTimeExtractor()
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS time_index (
                    edge_uuid TEXT PRIMARY KEY,
                    year INTEGER,
                    month INTEGER,
                    day INTEGER,
                    hour INTEGER,
                    minute INTEGER,
                    weekday INTEGER,
                    time_type TEXT DEFAULT 'static',
                    recurrence_pattern TEXT,
                    raw_time TEXT,
                    created_at TEXT
                )
            """)
            
            # 创建索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_year ON time_index(year)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_year_month ON time_index(year, month)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_year_month_day ON time_index(year, month, day)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_time_type ON time_index(time_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recurrence ON time_index(recurrence_pattern)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_weekday ON time_index(weekday)")
            
            # 额外的元数据表（用于存储边的完整信息）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS edge_metadata (
                    edge_uuid TEXT PRIMARY KEY,
                    fact TEXT,
                    source_node_uuid TEXT,
                    target_node_uuid TEXT,
                    metadata TEXT,
                    created_at TEXT
                )
            """)
            
            conn.commit()
    
    def index_edge(
        self,
        edge_uuid: str,
        valid_at: datetime,
        raw_time: str = "",
        fact: str = "",
        source_node_uuid: str = "",
        target_node_uuid: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        索引一条边的时间
        
        Args:
            edge_uuid: 边的 UUID
            valid_at: 生效时间
            raw_time: 原始时间文本（可选）
            fact: 事实描述（可选）
            source_node_uuid: 源节点 UUID
            target_node_uuid: 目标节点 UUID
            metadata: 额外元数据
        """
        # 从原始文本提取时间信息
        if raw_time:
            time_info = self.extractor.extract(raw_time)
            # 用 valid_at 补全缺失的部分
            if time_info.year is None:
                time_info.year = valid_at.year
            if time_info.month is None:
                time_info.month = valid_at.month
            if time_info.day is None:
                time_info.day = valid_at.day
        else:
            time_info = TimeInfo.from_datetime(valid_at)
        
        with sqlite3.connect(self.db_path) as conn:
            # 插入或更新时间索引
            conn.execute("""
                INSERT OR REPLACE INTO time_index
                (edge_uuid, year, month, day, hour, minute, weekday, 
                 time_type, recurrence_pattern, raw_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                edge_uuid,
                time_info.year,
                time_info.month,
                time_info.day,
                time_info.hour,
                time_info.minute,
                time_info.weekday if time_info.weekday is not None else valid_at.weekday(),
                time_info.time_type.value,
                time_info.recurrence_pattern.value if time_info.recurrence_pattern else None,
                raw_time or valid_at.isoformat(),
                datetime.now().isoformat(),
            ))
            
            # 插入边元数据
            if fact or source_node_uuid or target_node_uuid:
                conn.execute("""
                    INSERT OR REPLACE INTO edge_metadata
                    (edge_uuid, fact, source_node_uuid, target_node_uuid, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    edge_uuid,
                    fact,
                    source_node_uuid,
                    target_node_uuid,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    datetime.now().isoformat(),
                ))
            
            conn.commit()
        
        logger.debug(
            f"[TimeIndex] 索引边: {edge_uuid[:8]}... "
            f"({time_info.year}/{time_info.month}/{time_info.day})"
        )
    
    def index_batch(
        self,
        edges: List[Dict[str, Any]],
    ):
        """
        批量索引边
        
        Args:
            edges: 边数据列表，每个应包含 uuid, valid_at 等字段
        """
        with sqlite3.connect(self.db_path) as conn:
            for edge in edges:
                edge_uuid = edge.get("uuid")
                valid_at = edge.get("valid_at")
                
                if not edge_uuid or not valid_at:
                    continue
                
                # 解析 valid_at
                if isinstance(valid_at, str):
                    try:
                        valid_at = datetime.fromisoformat(valid_at.replace("Z", "+00:00"))
                    except:
                        valid_at = datetime.now()
                
                raw_time = edge.get("raw_time", "")
                if raw_time:
                    time_info = self.extractor.extract(raw_time)
                    if time_info.year is None:
                        time_info.year = valid_at.year
                    if time_info.month is None:
                        time_info.month = valid_at.month
                    if time_info.day is None:
                        time_info.day = valid_at.day
                else:
                    time_info = TimeInfo.from_datetime(valid_at)
                
                conn.execute("""
                    INSERT OR REPLACE INTO time_index
                    (edge_uuid, year, month, day, hour, minute, weekday, 
                     time_type, recurrence_pattern, raw_time, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    edge_uuid,
                    time_info.year,
                    time_info.month,
                    time_info.day,
                    time_info.hour,
                    time_info.minute,
                    time_info.weekday if time_info.weekday is not None else valid_at.weekday(),
                    time_info.time_type.value,
                    time_info.recurrence_pattern.value if time_info.recurrence_pattern else None,
                    raw_time or valid_at.isoformat(),
                    datetime.now().isoformat(),
                ))
            
            conn.commit()
        
        logger.info(f"[TimeIndex] 批量索引: {len(edges)} 条")
    
    def query_by_year(self, year: int) -> List[str]:
        """查询某年的所有边 UUID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT edge_uuid FROM time_index WHERE year = ?",
                (year,)
            )
            return [row[0] for row in cursor.fetchall()]
    
    def query_by_month(self, year: int, month: int) -> List[str]:
        """查询某月的所有边 UUID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT edge_uuid FROM time_index WHERE year = ? AND month = ?",
                (year, month)
            )
            return [row[0] for row in cursor.fetchall()]
    
    def query_by_day(self, year: int, month: int, day: int) -> List[str]:
        """查询某天的所有边 UUID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT edge_uuid FROM time_index WHERE year = ? AND month = ? AND day = ?",
                (year, month, day)
            )
            return [row[0] for row in cursor.fetchall()]
    
    def query_by_weekday(self, weekday: int) -> List[str]:
        """
        查询某星期几的所有边 UUID
        
        Args:
            weekday: 0=Monday, 6=Sunday
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT edge_uuid FROM time_index WHERE weekday = ?",
                (weekday,)
            )
            return [row[0] for row in cursor.fetchall()]
    
    def query_recurring(
        self,
        pattern: Optional[RecurrencePattern] = None,
        month: Optional[int] = None,
        day: Optional[int] = None,
    ) -> List[str]:
        """
        查询周期性事件
        
        Args:
            pattern: 周期模式（可选）
            month: 月份（可选，用于查询特定月份的周期事件）
            day: 日期（可选，用于查询特定日期的周期事件）
        """
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT edge_uuid FROM time_index WHERE time_type = 'recurring'"
            params = []
            
            if pattern:
                query += " AND recurrence_pattern = ?"
                params.append(pattern.value)
            if month:
                query += " AND month = ?"
                params.append(month)
            if day:
                query += " AND day = ?"
                params.append(day)
            
            cursor = conn.execute(query, params)
            return [row[0] for row in cursor.fetchall()]
    
    def query_range(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> List[str]:
        """
        查询时间范围内的边
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT edge_uuid FROM time_index 
                WHERE (year > ? OR (year = ? AND month > ?) OR (year = ? AND month = ? AND day >= ?))
                  AND (year < ? OR (year = ? AND month < ?) OR (year = ? AND month = ? AND day <= ?))
            """, (
                start_date.year, start_date.year, start_date.month,
                start_date.year, start_date.month, start_date.day,
                end_date.year, end_date.year, end_date.month,
                end_date.year, end_date.month, end_date.day,
            ))
            return [row[0] for row in cursor.fetchall()]
    
    def query_upcoming_events(
        self,
        days: int = 7,
        include_recurring: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        查询即将到来的事件
        
        Args:
            days: 未来多少天
            include_recurring: 是否包含周期性事件
        """
        now = datetime.now()
        end_date = now + timedelta(days=days)
        
        results = []
        
        with sqlite3.connect(self.db_path) as conn:
            # 静态事件
            cursor = conn.execute("""
                SELECT edge_uuid, year, month, day, raw_time
                FROM time_index 
                WHERE time_type = 'static'
                  AND year = ? AND month = ?
                  AND day >= ? AND day <= ?
            """, (
                now.year, now.month, now.day, end_date.day
            ))
            
            for row in cursor.fetchall():
                results.append({
                    "edge_uuid": row[0],
                    "date": f"{row[1]}-{row[2]:02d}-{row[3]:02d}",
                    "raw_time": row[4],
                    "is_recurring": False,
                })
            
            # 周期性事件
            if include_recurring:
                # 年度周期：匹配月/日
                cursor = conn.execute("""
                    SELECT edge_uuid, month, day, raw_time
                    FROM time_index 
                    WHERE time_type = 'recurring' AND recurrence_pattern = 'yearly'
                      AND month = ?
                      AND day >= ? AND day <= ?
                """, (now.month, now.day, end_date.day))
                
                for row in cursor.fetchall():
                    results.append({
                        "edge_uuid": row[0],
                        "date": f"{now.year}-{row[1]:02d}-{row[2]:02d}",
                        "raw_time": row[3],
                        "is_recurring": True,
                        "recurrence": "yearly",
                    })
                
                # 月度周期：匹配日
                cursor = conn.execute("""
                    SELECT edge_uuid, day, raw_time
                    FROM time_index 
                    WHERE time_type = 'recurring' AND recurrence_pattern = 'monthly'
                      AND day >= ? AND day <= ?
                """, (now.day, end_date.day))
                
                for row in cursor.fetchall():
                    results.append({
                        "edge_uuid": row[0],
                        "date": f"{now.year}-{now.month:02d}-{row[1]:02d}",
                        "raw_time": row[2],
                        "is_recurring": True,
                        "recurrence": "monthly",
                    })
        
        return results
    
    def get_time_info(self, edge_uuid: str) -> Optional[TimeInfo]:
        """获取边的时间信息"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT year, month, day, hour, minute, weekday, 
                       time_type, recurrence_pattern, raw_time
                FROM time_index WHERE edge_uuid = ?
            """, (edge_uuid,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            return TimeInfo(
                year=row[0],
                month=row[1],
                day=row[2],
                hour=row[3],
                minute=row[4],
                weekday=row[5],
                time_type=TimeType(row[6]) if row[6] else TimeType.STATIC,
                recurrence_pattern=RecurrencePattern(row[7]) if row[7] else None,
                raw_text=row[8] or "",
            )
    
    def delete_edge(self, edge_uuid: str):
        """删除边的索引"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM time_index WHERE edge_uuid = ?", (edge_uuid,))
            conn.execute("DELETE FROM edge_metadata WHERE edge_uuid = ?", (edge_uuid,))
            conn.commit()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM time_index").fetchone()[0]
            static = conn.execute(
                "SELECT COUNT(*) FROM time_index WHERE time_type = 'static'"
            ).fetchone()[0]
            recurring = conn.execute(
                "SELECT COUNT(*) FROM time_index WHERE time_type = 'recurring'"
            ).fetchone()[0]
            
            # 按年统计
            by_year = {}
            cursor = conn.execute(
                "SELECT year, COUNT(*) FROM time_index GROUP BY year ORDER BY year"
            )
            for row in cursor.fetchall():
                by_year[row[0]] = row[1]
            
            return {
                "total": total,
                "static": static,
                "recurring": recurring,
                "by_year": by_year,
            }


# ============================================================
# 与 Graphiti 的同步机制
# ============================================================

class TimeIndexSynchronizer:
    """
    时间索引同步器
    
    负责将 Graphiti 的边同步到时间索引
    """
    
    def __init__(
        self,
        time_index: HierarchicalTimeIndex,
        graphiti_adapter=None,
    ):
        self.time_index = time_index
        self.graphiti = graphiti_adapter
    
    async def sync_from_graphiti(self, group_ids: Optional[List[str]] = None) -> int:
        """
        从 Graphiti 同步边到时间索引
        
        Args:
            group_ids: 限定的分组（可选）
        
        Returns:
            同步的边数量
        """
        if not self.graphiti or not self.graphiti.is_initialized:
            logger.warning("[TimeIndexSync] Graphiti 未初始化")
            return 0
        
        # 这里需要查询 Graphiti 的所有边
        # 由于 Graphiti 没有直接的 list_all_edges 方法，
        # 我们使用搜索 API 获取边（这是个简化实现）
        
        try:
            # 使用通配查询获取边
            results = await self.graphiti.search_advanced(
                query="*",
                num_results=1000,
                group_ids=group_ids,
            )
            
            edges = results.get("edges", [])
            
            # 批量索引
            for edge in edges:
                valid_at = edge.get("valid_at")
                if valid_at:
                    if isinstance(valid_at, str):
                        try:
                            valid_at = datetime.fromisoformat(valid_at.replace("Z", "+00:00"))
                        except:
                            continue
                    
                    self.time_index.index_edge(
                        edge_uuid=edge.get("uuid"),
                        valid_at=valid_at,
                        raw_time=edge.get("raw_time", ""),
                        fact=edge.get("fact", ""),
                        source_node_uuid=edge.get("source_node_uuid", ""),
                        target_node_uuid=edge.get("target_node_uuid", ""),
                    )
            
            logger.info(f"[TimeIndexSync] 同步完成: {len(edges)} 条边")
            return len(edges)
            
        except Exception as e:
            logger.error(f"[TimeIndexSync] 同步失败: {e}")
            return 0
    
    def sync_edge(self, edge: Dict[str, Any]):
        """
        同步单条边（实时同步用）
        
        Args:
            edge: 边数据
        """
        valid_at = edge.get("valid_at")
        if not valid_at:
            return
        
        if isinstance(valid_at, str):
            try:
                valid_at = datetime.fromisoformat(valid_at.replace("Z", "+00:00"))
            except:
                return
        
        self.time_index.index_edge(
            edge_uuid=edge.get("uuid"),
            valid_at=valid_at,
            raw_time=edge.get("raw_time", ""),
            fact=edge.get("fact", ""),
            source_node_uuid=edge.get("source_node_uuid", ""),
            target_node_uuid=edge.get("target_node_uuid", ""),
        )


# ============================================================
# 便捷函数
# ============================================================

_default_index: Optional[HierarchicalTimeIndex] = None


def get_time_index(db_path: str = "./.time_index.db") -> HierarchicalTimeIndex:
    """获取默认时间索引（单例模式）"""
    global _default_index
    if _default_index is None:
        _default_index = HierarchicalTimeIndex(db_path)
    return _default_index


def index_edge_time(
    edge_uuid: str,
    valid_at: datetime,
    raw_time: str = "",
):
    """索引边时间的快捷函数"""
    get_time_index().index_edge(edge_uuid, valid_at, raw_time)


def query_by_date(year: int, month: int = None, day: int = None) -> List[str]:
    """按日期查询的快捷函数"""
    index = get_time_index()
    if day is not None:
        return index.query_by_day(year, month, day)
    elif month is not None:
        return index.query_by_month(year, month)
    else:
        return index.query_by_year(year)


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    import tempfile
    import os
    
    # 创建临时数据库
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_time_index.db")
        index = HierarchicalTimeIndex(db_path)
        
        print("=" * 60)
        print("层级时间索引测试")
        print("=" * 60)
        
        # 1. 索引边
        print("\n1. 索引边")
        test_edges = [
            ("edge_001", datetime(2024, 12, 25, 10, 30), "2024年12月25日圣诞节"),
            ("edge_002", datetime(2024, 12, 31, 23, 59), "2024年12月31日跨年"),
            ("edge_003", datetime(2025, 1, 1, 0, 0), "2025年元旦"),
            ("edge_004", datetime(2024, 12, 25), "每年圣诞节"),
            ("edge_005", datetime(2024, 1, 15), "每月15号发工资"),
        ]
        
        for uuid, dt, raw_time in test_edges:
            index.index_edge(uuid, dt, raw_time)
        print(f"   索引了 {len(test_edges)} 条边")
        
        # 2. 按年查询
        print("\n2. 按年查询 (2024)")
        results = index.query_by_year(2024)
        print(f"   结果: {results}")
        
        # 3. 按月查询
        print("\n3. 按月查询 (2024年12月)")
        results = index.query_by_month(2024, 12)
        print(f"   结果: {results}")
        
        # 4. 按日查询
        print("\n4. 按日查询 (2024年12月25日)")
        results = index.query_by_day(2024, 12, 25)
        print(f"   结果: {results}")
        
        # 5. 查询周期性事件
        print("\n5. 查询周期性事件")
        results = index.query_recurring()
        print(f"   结果: {results}")
        
        # 6. 时间提取测试
        print("\n6. 中文时间提取测试")
        extractor = ChineseTimeExtractor()
        test_times = [
            "2024年12月25日下午3点",
            "每年生日",
            "每月1号",
            "上周五",
            "最近几天",
        ]
        for time_str in test_times:
            info = extractor.extract(time_str)
            print(f"   '{time_str}' → {info.to_dict()}")
        
        # 7. 统计信息
        print("\n7. 统计信息")
        stats = index.get_stats()
        print(f"   总数: {stats['total']}")
        print(f"   静态: {stats['static']}")
        print(f"   周期: {stats['recurring']}")
        print(f"   按年: {stats['by_year']}")
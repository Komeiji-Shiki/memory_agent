# 🔮 借鉴 LingYiProject 改进 LifeBook 知识图谱规划

> ⚠️ 本文档属于规划 / 设计 / 实施记录的混合文档，不应视为当前仓库功能现状的唯一依据。
> 当前实际支持的模式、入口路径与运行方式，请优先以 [`README.md`](README.md) 和 [`MemoryRouter.route()`](memory_router.py:384) 对应的实际实现为准。
>
> 分析 LingYiProject 的知识图谱实现，提取可复用设计模式，增强我们的 Graphiti 时序知识图谱

## ✅ 实施进度

| 模块 | 状态 | 文件 |
|------|------|------|
| 快捷标注语法解析器 | ✅ 完成 | [`annotation_parser.py`](memory_store/annotation_parser.py) |
| 置信度累积机制 | ✅ 完成 | [`confidence_manager.py`](memory_store/confidence_manager.py) |
| 检索时 AI 筛选 | ✅ 完成 | [`relevance_filter.py`](memory_agent/relevance_filter.py) |
| 迭代检索器集成 | ✅ 完成 | [`iterative_retriever.py`](memory_agent/iterative_retriever.py) |
| 记忆衰减管理器 | ✅ 完成 | [`memory_decay.py`](memory_store/memory_decay.py) |
| 层级时间索引 | ✅ 完成 | [`hierarchical_time.py`](memory_store/hierarchical_time.py) |
| 五元组显式写入 | ✅ 完成 | [`quintuple_writer.py`](memory_store/quintuple_writer.py) |

## 📊 系统对比分析

### 核心架构对比

| 特性 | LifeBook + Graphiti | LingYiProject |
|------|---------------------|---------------|
| **图数据库** | Kuzu/Neo4j（Graphiti 封装） | Neo4j（直接操作） |
| **实体抽取** | Graphiti 自动 LLM 抽取 | 五元组 + 手动标注 |
| **时间模型** | Bi-Temporal（边属性） | 层级时间节点 |
| **节点类型** | Entity（通用） | Character/Location/Entity/Time |
| **检索策略** | MemR3 迭代检索 | 关键词 + Embedding + AI 筛选 |
| **置信度** | 边的 valid_at/invalid_at | 累积置信度机制 |
| **遗忘机制** | ❌ 无 | ✅ significance 衰减 |

### 各自优势

#### LifeBook + Graphiti 的优势
```
✅ Graphiti 框架成熟，自动实体/关系抽取
✅ Bi-Temporal 原生支持，时间点查询精确
✅ 混合检索（语义 + BM25 + 图遍历）
✅ 支持多后端（Kuzu/Neo4j/FalkorDB/Neptune）
✅ MemR3 风格的 Evidence-Gap 迭代检索
✅ 社区检测（Community）支持
```

#### LingYiProject 的优势
```
✅ 中文友好的五元组数据模型
✅ 层级时间节点设计（精细时间查询）
✅ 置信度累积机制（多来源验证）
✅ 遗忘机制（significance 衰减）
✅ 快捷标注语法（[时间](地点)<角色>）
✅ 检索时 AI 筛选相关性
✅ 节点类型明确区分
```

---

## 🎯 可借鉴的改进点

### 优先级 P0（核心改进）

#### 1. 快捷标注语法解析器

**问题**：当前用户手动输入记忆时，需要依赖 LLM 抽取实体，成本高且不够精准

**LingYi 方案**：
```python
# 标注解析：[时间](地点)<角色>
"<主人>在[2024年12月25日](家里)吃了苹果"

# 解析结果
{
    "subject": {"name": "主人", "type": "Character"},
    "predicate": "吃了",
    "object": "苹果",
    "time": "2024年12月25日",
    "location": "家里"
}
```

**改进方案**：
```python
# memory_store/annotation_parser.py

import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

@dataclass
class ParsedAnnotation:
    """解析后的标注结构"""
    subject: Optional[str] = None
    subject_type: str = "Entity"
    predicate: Optional[str] = None
    object: Optional[str] = None
    object_type: str = "Entity"
    time: Optional[str] = None
    location: Optional[str] = None
    with_persons: List[str] = None
    raw_text: str = ""
    
class AnnotationParser:
    """
    快捷标注语法解析器
    
    语法规则：
    - [xxx] → 时间
    - (xxx) → 地点
    - <xxx> → 角色/人物
    - {xxx} → 事物/概念（可选）
    - 无标注 → 普通实体
    
    示例：
    "<主人>在[2024年12月25日](家里)和<小明>一起吃火锅"
    → subject=主人, time=2024年12月25日, location=家里, with_persons=[小明]
    """
    
    # 正则模式
    TIME_PATTERN = re.compile(r'\[([^\]]+)\]')
    LOCATION_PATTERN = re.compile(r'\(([^)]+)\)')
    CHARACTER_PATTERN = re.compile(r'<([^>]+)>')
    ENTITY_PATTERN = re.compile(r'\{([^}]+)\}')
    
    def parse(self, text: str) -> ParsedAnnotation:
        """解析标注文本"""
        result = ParsedAnnotation(raw_text=text)
        
        # 提取时间
        time_matches = self.TIME_PATTERN.findall(text)
        if time_matches:
            result.time = time_matches[0]
        
        # 提取地点
        location_matches = self.LOCATION_PATTERN.findall(text)
        if location_matches:
            result.location = location_matches[0]
        
        # 提取角色（第一个是主体，其余是同行者）
        character_matches = self.CHARACTER_PATTERN.findall(text)
        if character_matches:
            result.subject = character_matches[0]
            result.subject_type = "Character"
            if len(character_matches) > 1:
                result.with_persons = character_matches[1:]
        
        # 提取事物/概念
        entity_matches = self.ENTITY_PATTERN.findall(text)
        if entity_matches:
            result.object = entity_matches[0]
            result.object_type = "Entity"
        
        # 清理标注后的纯文本，尝试提取谓词
        clean_text = self._remove_annotations(text)
        result.predicate = self._extract_predicate(clean_text)
        
        return result
    
    def _remove_annotations(self, text: str) -> str:
        """移除所有标注，获取纯文本"""
        text = self.TIME_PATTERN.sub('', text)
        text = self.LOCATION_PATTERN.sub('', text)
        text = self.CHARACTER_PATTERN.sub('', text)
        text = self.ENTITY_PATTERN.sub('', text)
        return text.strip()
    
    def _extract_predicate(self, text: str) -> Optional[str]:
        """从纯文本中提取谓词（简单实现）"""
        # 移除常见连接词
        text = re.sub(r'^(在|和|与|跟|把|被|让|给)', '', text)
        text = re.sub(r'(一起|一块儿|一同)', '', text)
        
        # 保留动词短语
        if text:
            # 简单取前10个字符作为谓词
            return text[:10].strip()
        return None
    
    def has_annotations(self, text: str) -> bool:
        """检查文本是否包含标注"""
        return bool(
            self.TIME_PATTERN.search(text) or
            self.LOCATION_PATTERN.search(text) or
            self.CHARACTER_PATTERN.search(text) or
            self.ENTITY_PATTERN.search(text)
        )
```

---

#### 2. 置信度累积机制

**问题**：当前 Graphiti 边只有 valid_at/invalid_at，无法表达"多来源验证后更可信"

**LingYi 方案**：
```python
# 多来源时自动提升置信度
new_confidence = 1 - (1 - old_confidence) * (1 - confidence / 2)
```

**改进方案**：
```python
# memory_store/confidence_manager.py

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime
import math

@dataclass
class ConfidenceInfo:
    """置信度信息"""
    value: float  # 当前置信度 0-1
    sources: List[str]  # 来源列表
    evidence: str  # 证据说明
    last_updated: datetime
    
class ConfidenceManager:
    """
    置信度管理器
    
    实现多来源验证的置信度累积：
    - 相同来源重复提及 → 小幅提升
    - 不同来源验证 → 大幅提升
    - 矛盾信息 → 降低置信度
    """
    
    def __init__(self, base_confidence: float = 0.5):
        self.base_confidence = base_confidence
    
    def accumulate(
        self,
        current: ConfidenceInfo,
        new_confidence: float,
        new_source: str,
        new_evidence: str = ""
    ) -> ConfidenceInfo:
        """
        累积置信度
        
        公式: new = 1 - (1 - old) * (1 - delta)
        其中 delta = new_confidence / 2 如果是新来源
             delta = new_confidence / 4 如果是相同来源
        """
        if new_source in current.sources:
            # 相同来源，小幅提升
            delta = new_confidence / 4
        else:
            # 新来源，大幅提升
            delta = new_confidence / 2
            current.sources.append(new_source)
        
        # 累积公式
        new_value = 1 - (1 - current.value) * (1 - delta)
        
        # 限制在 0-1 范围
        new_value = max(0.0, min(1.0, new_value))
        
        # 合并证据
        if new_evidence:
            if current.evidence:
                current.evidence += f"; {new_evidence}"
            else:
                current.evidence = new_evidence
        
        return ConfidenceInfo(
            value=new_value,
            sources=current.sources,
            evidence=current.evidence,
            last_updated=datetime.now()
        )
    
    def decay(
        self,
        current: ConfidenceInfo,
        days_passed: int,
        importance: float = 0.5
    ) -> ConfidenceInfo:
        """
        置信度衰减（用于长期未验证的事实）
        
        衰减公式: decay_rate = (1 - importance^2) / 100
        """
        if days_passed <= 0:
            return current
        
        decay_rate = (1 - importance ** 2) / 100
        decay_factor = math.exp(-decay_rate * days_passed)
        
        new_value = current.value * decay_factor
        
        return ConfidenceInfo(
            value=max(0.1, new_value),  # 最低保留 0.1
            sources=current.sources,
            evidence=current.evidence,
            last_updated=current.last_updated
        )
    
    def contradict(
        self,
        current: ConfidenceInfo,
        contradiction_strength: float = 0.5
    ) -> ConfidenceInfo:
        """
        处理矛盾信息
        
        降低置信度，但不归零
        """
        new_value = current.value * (1 - contradiction_strength * 0.5)
        
        return ConfidenceInfo(
            value=max(0.1, new_value),
            sources=current.sources,
            evidence=current.evidence + " [存在矛盾信息]",
            last_updated=datetime.now()
        )
```

---

#### 3. 检索时 AI 筛选

**问题**：当前迭代检索器的 Reflect 步骤只评估证据是否充分，没有筛选无关结果

**LingYi 方案**：
```python
# 检索后让 AI 判断每个节点是否与当前话题相关
# 返回布尔列表，过滤无关节点
```

**改进方案**：

在 [`iterative_retriever.py`](memory_agent/iterative_retriever.py) 中添加筛选步骤：

```python
# memory_agent/relevance_filter.py

from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class RelevanceFilter:
    """
    检索结果相关性筛选器
    
    借鉴 LingYi 的 _filter_related_nodes 设计：
    1. 将候选结果格式化
    2. 让 LLM 判断每个结果是否与查询相关
    3. 返回过滤后的结果
    """
    
    FILTER_PROMPT = """你是一个记忆相关性判断助手。请判断以下每条记忆是否与用户的查询话题相关。

## 用户查询
{query}

## 话题摘要
{summary}

## 待筛选的记忆（共 {count} 条）
{memories}

## 输出格式
请输出一个 JSON 数组，每个元素是 true/false，表示对应记忆是否相关。
数组长度必须等于记忆数量 {count}。

示例输出（假设有3条记忆）：
[true, false, true]

## 你的判断
"""
    
    def __init__(self, llm_client=None, min_batch_size: int = 3):
        """
        初始化筛选器
        
        Args:
            llm_client: LLM 客户端（可选，无则跳过筛选）
            min_batch_size: 最少多少条才触发筛选（减少 LLM 调用）
        """
        self.llm = llm_client
        self.min_batch_size = min_batch_size
    
    def filter(
        self,
        query: str,
        results: List[Dict[str, Any]],
        summary: str = ""
    ) -> List[Dict[str, Any]]:
        """
        筛选相关结果
        
        Args:
            query: 原始查询
            results: 检索结果列表
            summary: 话题摘要（可选）
        
        Returns:
            过滤后的结果列表
        """
        # 数量太少，跳过筛选
        if len(results) < self.min_batch_size:
            return results
        
        # 无 LLM，跳过筛选
        if not self.llm:
            logger.debug("[RelevanceFilter] 无 LLM，跳过筛选")
            return results
        
        try:
            # 格式化记忆
            memories_text = self._format_memories(results)
            
            # 构建 prompt
            prompt = self.FILTER_PROMPT.format(
                query=query,
                summary=summary or query,
                count=len(results),
                memories=memories_text
            )
            
            # 调用 LLM
            response = self.llm.generate(prompt)
            
            # 解析结果
            relevance_flags = self._parse_response(response, len(results))
            
            # 筛选
            filtered = [
                r for r, is_relevant in zip(results, relevance_flags)
                if is_relevant
            ]
            
            logger.info(
                f"[RelevanceFilter] 筛选完成: {len(results)} → {len(filtered)}"
            )
            
            return filtered
            
        except Exception as e:
            logger.error(f"[RelevanceFilter] 筛选失败: {e}")
            return results  # 失败时返回原结果
    
    async def filter_async(
        self,
        query: str,
        results: List[Dict[str, Any]],
        summary: str = ""
    ) -> List[Dict[str, Any]]:
        """异步版本的筛选"""
        if len(results) < self.min_batch_size or not self.llm:
            return results
        
        try:
            memories_text = self._format_memories(results)
            prompt = self.FILTER_PROMPT.format(
                query=query,
                summary=summary or query,
                count=len(results),
                memories=memories_text
            )
            
            response = await self.llm.generate_async(prompt)
            relevance_flags = self._parse_response(response, len(results))
            
            return [
                r for r, is_relevant in zip(results, relevance_flags)
                if is_relevant
            ]
            
        except Exception as e:
            logger.error(f"[RelevanceFilter] 异步筛选失败: {e}")
            return results
    
    def _format_memories(self, results: List[Dict[str, Any]]) -> str:
        """格式化记忆为文本"""
        lines = []
        for i, r in enumerate(results, 1):
            content = r.get("content", "") or r.get("fact", str(r))
            # 截断过长内容
            if len(content) > 200:
                content = content[:200] + "..."
            
            source = r.get("source", "unknown")
            score = r.get("score", 0)
            
            lines.append(f"{i}. [{source}] (score={score:.2f}) {content}")
        
        return "\n".join(lines)
    
    def _parse_response(self, response: str, expected_count: int) -> List[bool]:
        """解析 LLM 响应"""
        import json
        import re
        
        # 尝试提取 JSON 数组
        json_match = re.search(r'\[[\s\S]*?\]', response)
        if json_match:
            try:
                flags = json.loads(json_match.group())
                if len(flags) == expected_count:
                    return [bool(f) for f in flags]
            except json.JSONDecodeError:
                pass
        
        # 解析失败，默认全部保留
        logger.warning("[RelevanceFilter] 无法解析响应，保留全部结果")
        return [True] * expected_count
```

---

### 优先级 P1（重要改进）

#### 4. 遗忘机制（Significance 衰减）

**问题**：当前所有边权重相同，长期不被提及的旧信息与新信息同等重要

**LingYi 方案**：
```python
# 节点有 significance 属性（记忆清晰度）
# 衰减公式: new_significance = significance - (1 - importance²) / 10
```

**改进方案**：
```python
# memory_store/memory_decay.py

from datetime import datetime, timedelta
from typing import Dict, Any, List
import math
import logging

logger = logging.getLogger(__name__)

class MemoryDecayManager:
    """
    记忆衰减管理器
    
    实现 Ebbinghaus 遗忘曲线启发的衰减机制：
    - 新记忆衰减快
    - 被多次强化的记忆衰减慢
    - 高重要性记忆衰减慢
    """
    
    def __init__(
        self,
        base_decay_rate: float = 0.1,  # 基础衰减率
        min_significance: float = 0.1,  # 最低保留值
        reinforce_boost: float = 0.3,   # 强化提升
    ):
        self.base_decay_rate = base_decay_rate
        self.min_significance = min_significance
        self.reinforce_boost = reinforce_boost
    
    def calculate_significance(
        self,
        edge_data: Dict[str, Any],
        current_time: datetime = None
    ) -> float:
        """
        计算边的当前 significance
        
        考虑因素：
        - 上次更新时间
        - importance 属性
        - 被引用次数
        """
        current_time = current_time or datetime.now()
        
        # 获取边属性
        last_updated = edge_data.get("last_updated") or edge_data.get("created_at")
        importance = edge_data.get("importance", 0.5)
        reference_count = edge_data.get("reference_count", 1)
        base_significance = edge_data.get("significance", 1.0)
        
        # 计算时间差（天数）
        if isinstance(last_updated, str):
            try:
                last_updated = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            except:
                last_updated = current_time
        
        days_passed = (current_time - last_updated).days if last_updated else 0
        
        if days_passed <= 0:
            return base_significance
        
        # 衰减率：重要性高则衰减慢
        # decay_rate = base_rate * (1 - importance²)
        decay_rate = self.base_decay_rate * (1 - importance ** 2)
        
        # 引用次数降低衰减
        reference_factor = 1 / math.sqrt(reference_count)
        decay_rate *= reference_factor
        
        # 计算衰减
        decayed = base_significance * math.exp(-decay_rate * days_passed)
        
        return max(self.min_significance, decayed)
    
    def reinforce(
        self,
        edge_data: Dict[str, Any],
        reinforcement_strength: float = 1.0
    ) -> Dict[str, Any]:
        """
        强化记忆（被提及/引用时调用）
        
        效果：
        - 提升 significance
        - 增加 reference_count
        - 更新 last_updated
        """
        current_sig = edge_data.get("significance", 1.0)
        reference_count = edge_data.get("reference_count", 1)
        
        # 提升 significance
        boost = self.reinforce_boost * reinforcement_strength
        new_sig = min(1.0, current_sig + boost * (1 - current_sig))
        
        # 更新属性
        edge_data["significance"] = new_sig
        edge_data["reference_count"] = reference_count + 1
        edge_data["last_updated"] = datetime.now().isoformat()
        
        return edge_data
    
    def batch_decay(
        self,
        edges: List[Dict[str, Any]],
        threshold: float = 0.3
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        批量计算衰减，返回需要保留和可以归档的边
        
        Args:
            edges: 边列表
            threshold: 低于此值的边建议归档
        
        Returns:
            (active_edges, archive_edges)
        """
        active = []
        archive = []
        
        current_time = datetime.now()
        
        for edge in edges:
            sig = self.calculate_significance(edge, current_time)
            edge["significance"] = sig
            
            if sig >= threshold:
                active.append(edge)
            else:
                archive.append(edge)
        
        return active, archive
```

---

#### 5. 层级时间节点（可选增强）

**问题**：Graphiti 的时间存储在边属性，查询"某月的所有事件"需要扫描

**LingYi 方案**：
```
Year("2024年")
  ↑ BELONGS_TO
Month("12月", time="2024年12月")
  ↑ BELONGS_TO
Day("25日", time="2024年12月25日")
```

**改进方案**：

考虑到 Graphiti 已有 Bi-Temporal 模型，我们可以在**扩展层**实现层级时间，而不修改 Graphiti 核心：

```python
# memory_store/hierarchical_time.py

"""
层级时间索引
在 Graphiti 之上构建一个辅助索引，支持按时间层级查询

设计：
- 不修改 Graphiti 核心
- 维护一个 SQLite 辅助表
- 与 Graphiti 的 valid_at 同步
"""

import sqlite3
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class HierarchicalTimeIndex:
    """
    层级时间索引
    
    表结构:
    - time_index(edge_uuid, year, month, day, hour, time_type)
    
    time_type: static | recurring
    """
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS time_index (
                    edge_uuid TEXT PRIMARY KEY,
                    year INTEGER,
                    month INTEGER,
                    day INTEGER,
                    hour INTEGER,
                    time_type TEXT DEFAULT 'static',
                    raw_time TEXT,
                    created_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_year ON time_index(year)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_month ON time_index(year, month)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_day ON time_index(year, month, day)")
    
    def index_edge(
        self,
        edge_uuid: str,
        valid_at: datetime,
        raw_time: str = ""
    ):
        """索引一条边的时间"""
        time_type = self._detect_time_type(raw_time)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO time_index
                (edge_uuid, year, month, day, hour, time_type, raw_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                edge_uuid,
                valid_at.year,
                valid_at.month,
                valid_at.day,
                valid_at.hour,
                time_type,
                raw_time,
                datetime.now().isoformat()
            ))
    
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
    
    def query_recurring(self, month: int = None, day: int = None) -> List[str]:
        """查询周期性事件（如每年生日）"""
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT edge_uuid FROM time_index WHERE time_type = 'recurring'"
            params = []
            
            if month:
                query += " AND month = ?"
                params.append(month)
            if day:
                query += " AND day = ?"
                params.append(day)
            
            cursor = conn.execute(query, params)
            return [row[0] for row in cursor.fetchall()]
    
    def _detect_time_type(self, raw_time: str) -> str:
        """检测时间类型"""
        if not raw_time:
            return "static"
        
        # 如果有"每"开头或无年份，视为周期性
        if raw_time.startswith("每") or not re.search(r"\d{4}年", raw_time):
            return "recurring"
        
        return "static"
    
    def parse_chinese_time(self, time_str: str) -> Optional[datetime]:
        """解析中文时间字符串"""
        try:
            # 提取年月日时
            year = int(re.search(r"(\d{4})年", time_str).group(1)) if re.search(r"(\d{4})年", time_str) else datetime.now().year
            month = int(re.search(r"(\d{1,2})月", time_str).group(1)) if re.search(r"(\d{1,2})月", time_str) else 1
            day = int(re.search(r"(\d{1,2})[日号]", time_str).group(1)) if re.search(r"(\d{1,2})[日号]", time_str) else 1
            hour = int(re.search(r"(\d{1,2})[点时]", time_str).group(1)) if re.search(r"(\d{1,2})[点时]", time_str) else 0
            
            return datetime(year, month, day, hour)
        except:
            return None
```

---

### 优先级 P2（锦上添花）

#### 6. 节点类型区分

在 Graphiti 的 Entity 基础上增加 label 区分：

```python
# 在添加节点时指定类型
ENTITY_TYPE_LABELS = {
    "Character": ["Character", "Person", "Entity"],
    "Location": ["Location", "Place", "Entity"],
    "Event": ["Event", "Entity"],
    "Concept": ["Concept", "Entity"],
    "Thing": ["Thing", "Entity"],
}
```

#### 7. 五元组显式写入工具

```python
# 新增记忆写入工具
async def write_quintuple(
    subject: str,
    predicate: str,
    object: str,
    time: str = None,
    location: str = None,
    with_persons: List[str] = None,
    importance: float = 0.5,
    confidence: float = 0.5,
    context: str = "reality"
) -> str:
    """
    显式写入五元组到知识图谱
    
    适用场景：
    - 用户明确告知某个事实
    - 从对话中提取的高置信度信息
    - 手动整理的核心记忆
    """
    pass
```

---

## 📦 实施方案

### Phase 1: 核心改进（3-4天）

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 快捷标注解析器 | `memory_store/annotation_parser.py` | 0.5天 |
| 置信度管理器 | `memory_store/confidence_manager.py` | 0.5天 |
| 相关性筛选器 | `memory_agent/relevance_filter.py` | 1天 |
| 集成到迭代检索器 | `memory_agent/iterative_retriever.py` | 0.5天 |
| 测试验证 | - | 0.5天 |

### Phase 2: 遗忘机制（2-3天）

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 记忆衰减管理器 | `memory_store/memory_decay.py` | 1天 |
| 集成到 Graphiti 适配器 | `memory_store/graphiti_adapter.py` | 0.5天 |
| 定时衰减任务 | `memory_store/decay_scheduler.py` | 0.5天 |
| 测试验证 | - | 0.5天 |

### Phase 3: 时间索引增强（2天）

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 层级时间索引 | `memory_store/hierarchical_time.py` | 1天 |
| 同步机制 | - | 0.5天 |
| 测试验证 | - | 0.5天 |

---

## 🔄 集成架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LifeBook v2.1 改进版架构                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  用户输入                                                                     │
│  "<主人>在[2024年12月](家里)和<小明>吃火锅"                                   │
│                  │                                                           │
│                  ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                     AnnotationParser (新增)                              │  │
│  │  解析快捷标注 → ParsedAnnotation                                         │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                  │                                                           │
│                  ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                     Graphiti 适配器                                       │  │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐   │  │
│  │  │ ConfidenceManager │  │  MemoryDecay     │  │ HierarchicalTime    │   │  │
│  │  │ (置信度累积)       │  │  (遗忘机制)       │  │ (时间索引)           │   │  │
│  │  └──────────────────┘  └──────────────────┘  └──────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                  │                                                           │
│                  ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                     Graphiti 核心（不修改）                               │  │
│  │  • add_episode()  • search_()  • Bi-Temporal                            │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                  │                                                           │
│                  ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                     迭代检索器 (改进)                                      │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐   │  │
│  │  │  Retrieve → RelevanceFilter (新增) → Reflect → Refine → Loop    │   │  │
│  │  └──────────────────────────────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📋 验收标准

### P0 功能验收

| 功能 | 测试用例 | 通过标准 |
|------|---------|---------|
| 标注解析 | `"<主人>在[今天](家里)写代码"` | 正确提取 subject/time/location |
| 置信度累积 | 同一事实两次写入 | 置信度上升 |
| 相关性筛选 | 混杂无关结果的检索 | 过滤掉 50%+ 无关项 |

### P1 功能验收

| 功能 | 测试用例 | 通过标准 |
|------|---------|---------|
| 遗忘衰减 | 30天前的低重要性记忆 | significance 降至 <0.5 |
| 时间查询 | 查询"2024年12月" | 正确返回该月所有事件 |

---

## ⚠️ 风险与应对

### 风险1：LLM 调用成本增加

相关性筛选会增加 LLM 调用。

**应对**：
- 设置 min_batch_size 阈值（<3 条不筛选）
- 使用小模型（gpt-4o-mini）进行筛选
- 缓存常见查询的筛选结果

### 风险2：与 Graphiti 版本冲突

扩展层代码可能与 Graphiti 新版本不兼容。

**应对**：
- 扩展层独立于 Graphiti 核心
- 只通过公开 API 交互
- 锁定 Graphiti 版本

### 风险3：中文时间解析不准确

正则解析可能遗漏特殊格式。

**应对**：
- 维护常见中文时间模式列表
- 失败时回退到 LLM 解析
- 添加用户反馈机制

---

## 📅 时间线

```
Week 1 (Day 1-5):
├── Day 1-2: AnnotationParser + ConfidenceManager
├── Day 3-4: RelevanceFilter + 集成
└── Day 5: 测试 + 文档

Week 2 (Day 6-10):
├── Day 6-7: MemoryDecayManager
├── Day 8-9: HierarchicalTimeIndex
└── Day 10: 全量测试 + 部署

总计: ~10 个工作日
```

---

## 🎯 总结

借鉴 LingYiProject 的核心改进点：

| 改进 | 来源 | 收益 |
|------|------|------|
| **快捷标注语法** | LingYi | 降低用户输入成本 |
| **置信度累积** | LingYi | 多来源验证更可靠 |
| **AI 筛选检索** | LingYi | 提高检索精准度 |
| **遗忘机制** | LingYi | 模拟人类记忆特性 |
| **时间层级索引** | LingYi | 支持时间范围查询 |

这些改进与现有的 Graphiti + MemR3 架构完美互补，形成更强大的中文知识图谱系统~ 😸

---

## 📁 新增文件清单

```
memory_store/
├── annotation_parser.py      # 快捷标注语法解析器
├── confidence_manager.py     # 置信度累积机制
├── memory_decay.py           # 记忆衰减管理器
├── hierarchical_time.py      # 层级时间索引
├── quintuple_writer.py       # 五元组显式写入工具
└── __init__.py               # 已更新导出

memory_agent/
├── relevance_filter.py       # 检索结果相关性筛选器
└── iterative_retriever.py    # 已集成筛选功能
```

## 🎯 使用示例

### 快捷标注语法

```python
from memory_store import parse_annotation

result = parse_annotation("<主人>在[2024年12月25日](家里)和<小明>吃{火锅}#美食#")
print(result.subject)      # "主人"
print(result.time.raw)     # "2024年12月25日"
print(result.location)     # "家里"
print(result.with_persons) # ["小明"]
print(result.entities)     # ["火锅"]
print(result.tags)         # ["美食"]
```

### 置信度管理

```python
from memory_store import ConfidenceManager, SourceType

manager = ConfidenceManager()
info = manager.create(0.5, "user_input", SourceType.USER_INPUT)
info = manager.accumulate(info, 0.8, "diary_001", "日记记录验证")
print(info.value)  # 置信度提升
```

### 记忆衰减

```python
from memory_store import MemoryDecayManager

manager = MemoryDecayManager()
edge_data = {"significance": 1.0, "importance": 0.5, "created_at": "..."}
new_sig = manager.calculate_significance(edge_data)  # 计算衰减后的值
edge_data = manager.reinforce(edge_data)  # 被引用时强化
```

### 五元组写入

```python
from memory_store import QuintupleWriter

writer = QuintupleWriter(graphiti_adapter)
result = await writer.write_from_annotation(
    "<主人>在[每天早上](家里)喝{咖啡}"
)
```

---

*规划创建时间：2026-01-22*
*实施完成时间：2026-01-23*
*作者：灰魂* 🐱
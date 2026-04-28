"""
快捷标注语法解析器

借鉴 LingYiProject 的标注语法，为 LifeBook 提供快速输入记忆的能力。

语法规则：
- [xxx] → 时间
- (xxx) → 地点
- <xxx> → 角色/人物
- {xxx} → 事物/概念
- #xxx# → 标签/分类
- 无标注 → 普通文本

示例：
"<主人>在[2024年12月25日](家里)和<小明>一起吃火锅"
→ subject=主人, time=2024年12月25日, location=家里, with_persons=[小明]

使用方式：
    parser = AnnotationParser()
    result = parser.parse("<主人>在[今天](公司)开会")
    print(result.subject)  # "主人"
    print(result.time)     # "今天"
    print(result.location) # "公司"
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class EntityType(Enum):
    """实体类型枚举"""
    CHARACTER = "Character"  # 角色/人物
    LOCATION = "Location"    # 地点
    TIME = "Time"            # 时间
    ENTITY = "Entity"        # 通用事物
    CONCEPT = "Concept"      # 概念
    TAG = "Tag"              # 标签


@dataclass
class ParsedEntity:
    """解析后的实体"""
    text: str
    entity_type: EntityType
    start_pos: int = 0
    end_pos: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "type": self.entity_type.value,
            "start": self.start_pos,
            "end": self.end_pos,
        }


@dataclass
class ParsedTime:
    """解析后的时间信息"""
    raw: str                              # 原始文本
    datetime: Optional[datetime] = None   # 解析后的 datetime
    is_range: bool = False                # 是否是时间范围
    end_datetime: Optional[datetime] = None  # 范围结束时间
    is_recurring: bool = False            # 是否周期性（如"每天"）
    recurrence_pattern: Optional[str] = None  # 周期模式
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw,
            "datetime": self.datetime.isoformat() if self.datetime else None,
            "is_range": self.is_range,
            "end_datetime": self.end_datetime.isoformat() if self.end_datetime else None,
            "is_recurring": self.is_recurring,
            "recurrence_pattern": self.recurrence_pattern,
        }


@dataclass
class ParsedAnnotation:
    """解析后的完整标注结构"""
    # 主体
    subject: Optional[str] = None
    subject_type: EntityType = EntityType.ENTITY
    
    # 谓词/动作
    predicate: Optional[str] = None
    
    # 宾语/对象
    object: Optional[str] = None
    object_type: EntityType = EntityType.ENTITY
    
    # 时间
    time: Optional[ParsedTime] = None
    
    # 地点
    location: Optional[str] = None
    
    # 同行者/相关人物
    with_persons: List[str] = field(default_factory=list)
    
    # 提到的事物/概念
    entities: List[str] = field(default_factory=list)
    
    # 标签
    tags: List[str] = field(default_factory=list)
    
    # 所有解析出的实体（用于调试和高级用途）
    all_entities: List[ParsedEntity] = field(default_factory=list)
    
    # 原始文本
    raw_text: str = ""
    
    # 清理后的纯文本（移除所有标注）
    clean_text: str = ""
    
    # 是否包含有效标注
    has_annotations: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return {
            "subject": self.subject,
            "subject_type": self.subject_type.value,
            "predicate": self.predicate,
            "object": self.object,
            "object_type": self.object_type.value,
            "time": self.time.to_dict() if self.time else None,
            "location": self.location,
            "with_persons": self.with_persons,
            "entities": self.entities,
            "tags": self.tags,
            "raw_text": self.raw_text,
            "clean_text": self.clean_text,
            "has_annotations": self.has_annotations,
        }
    
    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    def to_quintuple(self) -> Dict[str, Any]:
        """
        转换为五元组格式
        
        五元组: (subject, predicate, object, time, location)
        这是知识图谱的标准表示形式
        """
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object or (self.entities[0] if self.entities else None),
            "time": self.time.raw if self.time else None,
            "location": self.location,
            # 扩展字段
            "with_persons": self.with_persons,
            "tags": self.tags,
        }


class ChineseTimeParser:
    """
    中文时间解析器
    
    支持多种中文时间表达方式：
    - 相对时间：今天、昨天、明天、上周、下个月
    - 绝对时间：2024年12月25日、2024/12/25、12月25号
    - 模糊时间：最近、前几天、上个月底
    - 周期时间：每天、每周一、每年生日
    """
    
    # 相对时间映射
    RELATIVE_TIME_MAP = {
        "今天": lambda: datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
        "昨天": lambda: datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1),
        "前天": lambda: datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2),
        "大前天": lambda: datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=3),
        "明天": lambda: datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1),
        "后天": lambda: datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2),
        "上周": lambda: datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(weeks=1),
        "下周": lambda: datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(weeks=1),
        "上个月": lambda: (datetime.now().replace(day=1) - timedelta(days=1)).replace(day=1),
        "下个月": lambda: (datetime.now().replace(day=28) + timedelta(days=5)).replace(day=1),
        "去年": lambda: datetime.now().replace(year=datetime.now().year - 1),
        "明年": lambda: datetime.now().replace(year=datetime.now().year + 1),
        "现在": lambda: datetime.now(),
        "刚才": lambda: datetime.now() - timedelta(minutes=5),
        "刚刚": lambda: datetime.now() - timedelta(minutes=2),
    }
    
    # 周期性时间模式
    RECURRING_PATTERNS = [
        (r"每天", "daily"),
        (r"每周([一二三四五六日天])?", "weekly"),
        (r"每月(\d{1,2}[日号])?", "monthly"),
        (r"每年", "yearly"),
        (r"每隔(\d+)天", "every_n_days"),
    ]
    
    def parse(self, time_str: str) -> ParsedTime:
        """
        解析时间字符串
        
        Args:
            time_str: 中文时间字符串
        
        Returns:
            ParsedTime 对象
        """
        time_str = time_str.strip()
        
        # 检查周期性时间
        for pattern, recurrence in self.RECURRING_PATTERNS:
            if re.match(pattern, time_str):
                return ParsedTime(
                    raw=time_str,
                    is_recurring=True,
                    recurrence_pattern=recurrence,
                )
        
        # 检查相对时间
        for rel_time, get_dt in self.RELATIVE_TIME_MAP.items():
            if rel_time in time_str:
                return ParsedTime(
                    raw=time_str,
                    datetime=get_dt(),
                )
        
        # 尝试解析绝对时间
        dt = self._parse_absolute_time(time_str)
        if dt:
            return ParsedTime(raw=time_str, datetime=dt)
        
        # 无法解析，返回原始文本
        return ParsedTime(raw=time_str)
    
    def _parse_absolute_time(self, time_str: str) -> Optional[datetime]:
        """解析绝对时间"""
        now = datetime.now()
        
        # 模式1: 2024年12月25日 14点30分
        patterns = [
            # 完整格式
            (r"(\d{4})年(\d{1,2})月(\d{1,2})[日号]\s*(\d{1,2})[点时](\d{1,2})分?", 
             lambda m: datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]))),
            
            # 年月日时
            (r"(\d{4})年(\d{1,2})月(\d{1,2})[日号]\s*(\d{1,2})[点时]",
             lambda m: datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]))),
            
            # 年月日
            (r"(\d{4})年(\d{1,2})月(\d{1,2})[日号]?",
             lambda m: datetime(int(m[1]), int(m[2]), int(m[3]))),
            
            # 月日（默认今年）
            (r"(\d{1,2})月(\d{1,2})[日号]",
             lambda m: datetime(now.year, int(m[1]), int(m[2]))),
            
            # ISO 格式
            (r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})",
             lambda m: datetime(int(m[1]), int(m[2]), int(m[3]))),
            
            # 紧凑格式 20241225
            (r"^(\d{4})(\d{2})(\d{2})$",
             lambda m: datetime(int(m[1]), int(m[2]), int(m[3]))),
        ]
        
        for pattern, converter in patterns:
            match = re.search(pattern, time_str)
            if match:
                try:
                    return converter(match.groups())
                except (ValueError, TypeError):
                    continue
        
        return None


class AnnotationParser:
    """
    快捷标注语法解析器
    
    语法规则：
    - [xxx] → 时间
    - (xxx) → 地点
    - <xxx> → 角色/人物
    - {xxx} → 事物/概念
    - #xxx# → 标签
    
    示例：
    "<主人>在[2024年12月25日](家里)和<小明>一起吃{火锅}#美食#"
    → subject=主人, time=2024年12月25日, location=家里, 
       with_persons=[小明], entities=[火锅], tags=[美食]
    """
    
    # 正则模式（带捕获位置）
    TIME_PATTERN = re.compile(r'\[([^\]]+)\]')
    LOCATION_PATTERN = re.compile(r'\(([^)]+)\)')
    CHARACTER_PATTERN = re.compile(r'<([^>]+)>')
    ENTITY_PATTERN = re.compile(r'\{([^}]+)\}')
    TAG_PATTERN = re.compile(r'#([^#]+)#')
    
    # 连接词（用于提取谓词）
    CONNECTORS = [
        "在", "和", "与", "跟", "把", "被", "让", "给", "用", "对",
        "一起", "一块儿", "一同", "共同",
    ]
    
    # 常见动词后缀（用于谓词边界检测）
    VERB_SUFFIXES = ["了", "过", "着", "完", "好", "掉"]
    
    def __init__(self, time_parser: Optional[ChineseTimeParser] = None):
        """
        初始化解析器
        
        Args:
            time_parser: 时间解析器（可选，默认使用内置解析器）
        """
        self.time_parser = time_parser or ChineseTimeParser()
    
    def parse(self, text: str) -> ParsedAnnotation:
        """
        解析标注文本
        
        Args:
            text: 带标注的文本
        
        Returns:
            ParsedAnnotation 对象
        """
        result = ParsedAnnotation(raw_text=text)
        all_entities: List[ParsedEntity] = []
        
        # 提取时间
        time_matches = list(self.TIME_PATTERN.finditer(text))
        if time_matches:
            time_raw = time_matches[0].group(1)
            result.time = self.time_parser.parse(time_raw)
            all_entities.append(ParsedEntity(
                text=time_raw,
                entity_type=EntityType.TIME,
                start_pos=time_matches[0].start(),
                end_pos=time_matches[0].end(),
            ))
        
        # 提取地点
        location_matches = list(self.LOCATION_PATTERN.finditer(text))
        if location_matches:
            result.location = location_matches[0].group(1)
            all_entities.append(ParsedEntity(
                text=result.location,
                entity_type=EntityType.LOCATION,
                start_pos=location_matches[0].start(),
                end_pos=location_matches[0].end(),
            ))
        
        # 提取角色（第一个是主体，其余是同行者）
        character_matches = list(self.CHARACTER_PATTERN.finditer(text))
        if character_matches:
            result.subject = character_matches[0].group(1)
            result.subject_type = EntityType.CHARACTER
            all_entities.append(ParsedEntity(
                text=result.subject,
                entity_type=EntityType.CHARACTER,
                start_pos=character_matches[0].start(),
                end_pos=character_matches[0].end(),
            ))
            
            if len(character_matches) > 1:
                result.with_persons = [m.group(1) for m in character_matches[1:]]
                for m in character_matches[1:]:
                    all_entities.append(ParsedEntity(
                        text=m.group(1),
                        entity_type=EntityType.CHARACTER,
                        start_pos=m.start(),
                        end_pos=m.end(),
                    ))
        
        # 提取事物/概念
        entity_matches = list(self.ENTITY_PATTERN.finditer(text))
        if entity_matches:
            result.entities = [m.group(1) for m in entity_matches]
            # 第一个事物作为宾语
            if result.entities:
                result.object = result.entities[0]
                result.object_type = EntityType.ENTITY
            
            for m in entity_matches:
                all_entities.append(ParsedEntity(
                    text=m.group(1),
                    entity_type=EntityType.ENTITY,
                    start_pos=m.start(),
                    end_pos=m.end(),
                ))
        
        # 提取标签
        tag_matches = list(self.TAG_PATTERN.finditer(text))
        if tag_matches:
            result.tags = [m.group(1) for m in tag_matches]
            for m in tag_matches:
                all_entities.append(ParsedEntity(
                    text=m.group(1),
                    entity_type=EntityType.TAG,
                    start_pos=m.start(),
                    end_pos=m.end(),
                ))
        
        # 存储所有实体
        result.all_entities = sorted(all_entities, key=lambda e: e.start_pos)
        
        # 清理标注后的纯文本
        result.clean_text = self._remove_annotations(text)
        
        # 提取谓词
        result.predicate = self._extract_predicate(result.clean_text)
        
        # 标记是否有有效标注
        result.has_annotations = bool(
            time_matches or location_matches or character_matches or 
            entity_matches or tag_matches
        )
        
        return result
    
    def _remove_annotations(self, text: str) -> str:
        """移除所有标注，获取纯文本"""
        text = self.TIME_PATTERN.sub(r'\1', text)  # 保留时间文本
        text = self.LOCATION_PATTERN.sub(r'\1', text)  # 保留地点文本
        text = self.CHARACTER_PATTERN.sub(r'\1', text)  # 保留人物文本
        text = self.ENTITY_PATTERN.sub(r'\1', text)  # 保留事物文本
        text = self.TAG_PATTERN.sub('', text)  # 移除标签
        return text.strip()
    
    def _extract_predicate(self, clean_text: str) -> Optional[str]:
        """
        从纯文本中提取谓词（动作/关系）
        
        策略：
        1. 移除常见连接词
        2. 查找动词短语
        3. 提取核心动作
        """
        if not clean_text:
            return None
        
        text = clean_text
        
        # 移除开头的连接词
        for connector in self.CONNECTORS:
            if text.startswith(connector):
                text = text[len(connector):].strip()
        
        # 移除中间的连接词
        for connector in self.CONNECTORS:
            text = text.replace(connector, " ")
        
        # 清理多余空格
        text = " ".join(text.split())
        
        if not text:
            return None
        
        # 尝试找到动词边界
        predicate = text
        for suffix in self.VERB_SUFFIXES:
            idx = text.find(suffix)
            if idx > 0:
                # 动词可能在后缀前面的几个字
                predicate = text[:idx + len(suffix)]
                break
        
        # 限制长度
        if len(predicate) > 20:
            predicate = predicate[:20]
        
        return predicate.strip() if predicate.strip() else None
    
    def has_annotations(self, text: str) -> bool:
        """检查文本是否包含标注"""
        return bool(
            self.TIME_PATTERN.search(text) or
            self.LOCATION_PATTERN.search(text) or
            self.CHARACTER_PATTERN.search(text) or
            self.ENTITY_PATTERN.search(text) or
            self.TAG_PATTERN.search(text)
        )
    
    def extract_all_entities(self, text: str) -> List[ParsedEntity]:
        """
        提取文本中的所有实体
        
        返回按位置排序的实体列表
        """
        result = self.parse(text)
        return result.all_entities
    
    def format_as_markdown(self, result: ParsedAnnotation) -> str:
        """
        将解析结果格式化为 Markdown
        
        用于生成结构化的记忆条目
        """
        lines = []
        
        # 主体和动作
        if result.subject and result.predicate:
            lines.append(f"**{result.subject}** {result.predicate}")
        elif result.predicate:
            lines.append(f"**动作**: {result.predicate}")
        
        # 时间
        if result.time:
            time_str = result.time.raw
            if result.time.datetime:
                time_str += f" ({result.time.datetime.strftime('%Y-%m-%d')})"
            lines.append(f"- 🕐 时间: {time_str}")
        
        # 地点
        if result.location:
            lines.append(f"- 📍 地点: {result.location}")
        
        # 同行者
        if result.with_persons:
            lines.append(f"- 👥 同行: {', '.join(result.with_persons)}")
        
        # 相关事物
        if result.entities:
            lines.append(f"- 📦 事物: {', '.join(result.entities)}")
        
        # 标签
        if result.tags:
            lines.append(f"- 🏷️ 标签: {', '.join('#' + t for t in result.tags)}")
        
        return "\n".join(lines)


# ============================================================
# 便捷函数
# ============================================================

_default_parser: Optional[AnnotationParser] = None


def get_parser() -> AnnotationParser:
    """获取默认解析器实例（单例模式）"""
    global _default_parser
    if _default_parser is None:
        _default_parser = AnnotationParser()
    return _default_parser


def parse_annotation(text: str) -> ParsedAnnotation:
    """
    快捷解析函数
    
    Args:
        text: 带标注的文本
    
    Returns:
        ParsedAnnotation 对象
    
    示例:
        >>> result = parse_annotation("<主人>在[今天](家里)写代码")
        >>> result.subject
        '主人'
        >>> result.location
        '家里'
    """
    return get_parser().parse(text)


def has_annotations(text: str) -> bool:
    """检查文本是否包含标注"""
    return get_parser().has_annotations(text)


def to_quintuple(text: str) -> Dict[str, Any]:
    """
    将标注文本转换为五元组
    
    Args:
        text: 带标注的文本
    
    Returns:
        五元组字典: {subject, predicate, object, time, location, ...}
    """
    return get_parser().parse(text).to_quintuple()


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    # 测试用例
    test_cases = [
        "<主人>在[2024年12月25日](家里)和<小明>一起吃{火锅}#美食#",
        "<灰魂>在[今天](公司)帮<主人>写代码",
        "[昨天晚上]去(星巴克)喝{咖啡}",
        "<主人>和<小红><小明>在[上周五](学校)参加{毕业典礼}#重要#",
        "每天早上跑步",
        "[2024/01/15]完成{项目报告}",
    ]
    
    parser = AnnotationParser()
    
    for text in test_cases:
        print(f"\n{'='*60}")
        print(f"输入: {text}")
        print("-" * 40)
        
        result = parser.parse(text)
        
        print(f"主体: {result.subject} ({result.subject_type.value})")
        print(f"谓词: {result.predicate}")
        print(f"宾语: {result.object}")
        if result.time:
            print(f"时间: {result.time.raw} → {result.time.datetime}")
        print(f"地点: {result.location}")
        print(f"同行: {result.with_persons}")
        print(f"事物: {result.entities}")
        print(f"标签: {result.tags}")
        print(f"纯文本: {result.clean_text}")
        print("-" * 40)
        print("五元组:", result.to_quintuple())
        print("-" * 40)
        print("Markdown:")
        print(parser.format_as_markdown(result))
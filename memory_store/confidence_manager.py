"""
置信度管理器

借鉴 LingYiProject 的置信度累积机制，实现多来源验证的可信度评估。

核心设计：
1. 多来源验证 → 置信度累积提升
2. 相同来源重复 → 小幅提升
3. 矛盾信息 → 降低置信度
4. 时间衰减 → 长期未验证的信息置信度下降

置信度累积公式（来自 LingYi）:
    new_confidence = 1 - (1 - old_confidence) * (1 - delta)
    其中 delta = new_confidence / 2 (新来源)
         delta = new_confidence / 4 (相同来源)

使用方式：
    manager = ConfidenceManager()
    
    # 初始置信度
    info = ConfidenceInfo(value=0.5, sources=["user_input"])
    
    # 累积来自新来源的验证
    info = manager.accumulate(info, 0.8, "diary_2024_12_25", "日记中提到")
    
    # 时间衰减
    info = manager.decay(info, days_passed=30, importance=0.5)
"""

from __future__ import annotations

import math
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ConfidenceLevel(Enum):
    """置信度等级枚举"""
    VERY_LOW = "very_low"      # 0.0 - 0.2
    LOW = "low"                # 0.2 - 0.4
    MEDIUM = "medium"          # 0.4 - 0.6
    HIGH = "high"              # 0.6 - 0.8
    VERY_HIGH = "very_high"    # 0.8 - 1.0
    
    @classmethod
    def from_value(cls, value: float) -> 'ConfidenceLevel':
        """根据数值获取等级"""
        if value < 0.2:
            return cls.VERY_LOW
        elif value < 0.4:
            return cls.LOW
        elif value < 0.6:
            return cls.MEDIUM
        elif value < 0.8:
            return cls.HIGH
        else:
            return cls.VERY_HIGH


class SourceType(Enum):
    """来源类型枚举"""
    USER_INPUT = "user_input"       # 用户直接输入
    CONVERSATION = "conversation"   # 对话提取
    DIARY = "diary"                 # 日记记录
    NODE = "node"                   # 节点文件
    EXTERNAL = "external"           # 外部数据源
    INFERENCE = "inference"         # 推理得出
    
    @property
    def base_weight(self) -> float:
        """来源类型的基础权重"""
        weights = {
            SourceType.USER_INPUT: 0.9,      # 用户直接输入最可信
            SourceType.DIARY: 0.85,          # 日记次之
            SourceType.NODE: 0.8,            # 结构化节点
            SourceType.CONVERSATION: 0.6,    # 对话提取
            SourceType.EXTERNAL: 0.5,        # 外部数据
            SourceType.INFERENCE: 0.4,       # 推理得出最低
        }
        return weights.get(self, 0.5)


@dataclass
class EvidenceRecord:
    """证据记录"""
    source: str                         # 来源标识
    source_type: SourceType             # 来源类型
    confidence: float                   # 该证据的置信度
    evidence_text: str                  # 证据文本
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "source_type": self.source_type.value,
            "confidence": self.confidence,
            "evidence_text": self.evidence_text,
            "timestamp": self.timestamp.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'EvidenceRecord':
        return cls(
            source=d["source"],
            source_type=SourceType(d["source_type"]),
            confidence=d["confidence"],
            evidence_text=d["evidence_text"],
            timestamp=datetime.fromisoformat(d["timestamp"]) if d.get("timestamp") else datetime.now(),
        )


@dataclass
class ConfidenceInfo:
    """
    置信度信息
    
    跟踪一个事实/边的完整置信度状态
    """
    value: float = 0.5                          # 当前置信度 (0-1)
    sources: List[str] = field(default_factory=list)  # 来源标识列表
    evidence_records: List[EvidenceRecord] = field(default_factory=list)  # 详细证据记录
    last_verified: Optional[datetime] = None    # 最后验证时间
    last_updated: datetime = field(default_factory=datetime.now)  # 最后更新时间
    contradiction_count: int = 0                # 矛盾次数
    verification_count: int = 0                 # 验证次数
    
    def __post_init__(self):
        if self.last_verified is None:
            self.last_verified = self.last_updated
    
    @property
    def level(self) -> ConfidenceLevel:
        """获取置信度等级"""
        return ConfidenceLevel.from_value(self.value)
    
    @property
    def source_count(self) -> int:
        """独立来源数量"""
        return len(set(self.sources))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "level": self.level.value,
            "sources": self.sources,
            "evidence_records": [e.to_dict() for e in self.evidence_records],
            "last_verified": self.last_verified.isoformat() if self.last_verified else None,
            "last_updated": self.last_updated.isoformat(),
            "contradiction_count": self.contradiction_count,
            "verification_count": self.verification_count,
            "source_count": self.source_count,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'ConfidenceInfo':
        return cls(
            value=d.get("value", 0.5),
            sources=d.get("sources", []),
            evidence_records=[EvidenceRecord.from_dict(e) for e in d.get("evidence_records", [])],
            last_verified=datetime.fromisoformat(d["last_verified"]) if d.get("last_verified") else None,
            last_updated=datetime.fromisoformat(d["last_updated"]) if d.get("last_updated") else datetime.now(),
            contradiction_count=d.get("contradiction_count", 0),
            verification_count=d.get("verification_count", 0),
        )
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'ConfidenceInfo':
        return cls.from_dict(json.loads(json_str))


class ConfidenceManager:
    """
    置信度管理器
    
    实现多来源验证的置信度累积：
    - 相同来源重复提及 → 小幅提升
    - 不同来源验证 → 大幅提升
    - 矛盾信息 → 降低置信度
    - 时间衰减 → 长期未验证的信息置信度下降
    """
    
    def __init__(
        self,
        base_confidence: float = 0.5,
        new_source_delta_factor: float = 0.5,   # 新来源的 delta 因子
        same_source_delta_factor: float = 0.25, # 相同来源的 delta 因子
        contradiction_penalty: float = 0.5,     # 矛盾惩罚系数
        min_confidence: float = 0.1,            # 最低置信度
        max_confidence: float = 0.99,           # 最高置信度
    ):
        """
        初始化置信度管理器
        
        Args:
            base_confidence: 新事实的默认置信度
            new_source_delta_factor: 新来源时的 delta 系数
            same_source_delta_factor: 相同来源时的 delta 系数
            contradiction_penalty: 矛盾信息的惩罚系数
            min_confidence: 最低保留置信度
            max_confidence: 最高置信度上限
        """
        self.base_confidence = base_confidence
        self.new_source_delta_factor = new_source_delta_factor
        self.same_source_delta_factor = same_source_delta_factor
        self.contradiction_penalty = contradiction_penalty
        self.min_confidence = min_confidence
        self.max_confidence = max_confidence
    
    def create(
        self,
        initial_confidence: Optional[float] = None,
        source: Optional[str] = None,
        source_type: SourceType = SourceType.USER_INPUT,
        evidence_text: str = "",
    ) -> ConfidenceInfo:
        """
        创建新的置信度信息
        
        Args:
            initial_confidence: 初始置信度（None 使用默认值）
            source: 初始来源标识
            source_type: 来源类型
            evidence_text: 证据文本
        
        Returns:
            新的 ConfidenceInfo 对象
        """
        confidence = initial_confidence if initial_confidence is not None else self.base_confidence
        
        # 根据来源类型调整初始置信度
        confidence = confidence * source_type.base_weight
        confidence = self._clamp(confidence)
        
        sources = [source] if source else []
        evidence_records = []
        
        if source:
            evidence_records.append(EvidenceRecord(
                source=source,
                source_type=source_type,
                confidence=confidence,
                evidence_text=evidence_text,
            ))
        
        return ConfidenceInfo(
            value=confidence,
            sources=sources,
            evidence_records=evidence_records,
            verification_count=1 if source else 0,
        )
    
    def accumulate(
        self,
        current: ConfidenceInfo,
        new_confidence: float,
        new_source: str,
        evidence_text: str = "",
        source_type: SourceType = SourceType.CONVERSATION,
    ) -> ConfidenceInfo:
        """
        累积置信度
        
        当收到新证据时，根据来源更新置信度：
        - 新来源：大幅提升
        - 相同来源：小幅提升
        
        公式: new = 1 - (1 - old) * (1 - delta)
        其中 delta = new_confidence * factor
        
        Args:
            current: 当前置信度信息
            new_confidence: 新证据的置信度
            new_source: 新证据来源
            evidence_text: 证据文本
            source_type: 来源类型
        
        Returns:
            更新后的 ConfidenceInfo（不修改原对象）
        """
        # 根据来源类型调整新置信度
        adjusted_confidence = new_confidence * source_type.base_weight
        
        # 判断是否是新来源
        is_new_source = new_source not in current.sources
        
        if is_new_source:
            # 新来源，大幅提升
            delta = adjusted_confidence * self.new_source_delta_factor
            new_sources = current.sources + [new_source]
        else:
            # 相同来源，小幅提升
            delta = adjusted_confidence * self.same_source_delta_factor
            new_sources = current.sources.copy()
        
        # 累积公式: new = 1 - (1 - old) * (1 - delta)
        new_value = 1 - (1 - current.value) * (1 - delta)
        new_value = self._clamp(new_value)
        
        # 创建新的证据记录
        new_evidence = EvidenceRecord(
            source=new_source,
            source_type=source_type,
            confidence=adjusted_confidence,
            evidence_text=evidence_text,
        )
        
        logger.debug(
            f"[ConfidenceManager] 累积: {current.value:.3f} → {new_value:.3f} "
            f"(source={new_source}, new={is_new_source}, delta={delta:.3f})"
        )
        
        return ConfidenceInfo(
            value=new_value,
            sources=new_sources,
            evidence_records=current.evidence_records + [new_evidence],
            last_verified=datetime.now(),
            last_updated=datetime.now(),
            contradiction_count=current.contradiction_count,
            verification_count=current.verification_count + 1,
        )
    
    def decay(
        self,
        current: ConfidenceInfo,
        days_passed: Optional[int] = None,
        importance: float = 0.5,
        reference_time: Optional[datetime] = None,
    ) -> ConfidenceInfo:
        """
        置信度衰减（用于长期未验证的事实）
        
        衰减公式: decay_rate = (1 - importance²) / 100
        衰减值: decayed = value * exp(-decay_rate * days)
        
        高重要性的信息衰减更慢。
        
        Args:
            current: 当前置信度信息
            days_passed: 经过的天数（None 则自动计算）
            importance: 信息重要性 (0-1)，高重要性衰减慢
            reference_time: 参考时间点（默认当前时间）
        
        Returns:
            衰减后的 ConfidenceInfo
        """
        reference_time = reference_time or datetime.now()
        
        # 计算天数
        if days_passed is None:
            if current.last_verified:
                days_passed = (reference_time - current.last_verified).days
            else:
                days_passed = 0
        
        if days_passed <= 0:
            return current
        
        # 衰减率：重要性高则衰减慢
        # decay_rate = (1 - importance²) / 100
        decay_rate = (1 - importance ** 2) / 100
        
        # 指数衰减
        decay_factor = math.exp(-decay_rate * days_passed)
        new_value = current.value * decay_factor
        new_value = max(self.min_confidence, new_value)
        
        logger.debug(
            f"[ConfidenceManager] 衰减: {current.value:.3f} → {new_value:.3f} "
            f"(days={days_passed}, importance={importance}, rate={decay_rate:.4f})"
        )
        
        return ConfidenceInfo(
            value=new_value,
            sources=current.sources,
            evidence_records=current.evidence_records,
            last_verified=current.last_verified,
            last_updated=datetime.now(),
            contradiction_count=current.contradiction_count,
            verification_count=current.verification_count,
        )
    
    def contradict(
        self,
        current: ConfidenceInfo,
        contradiction_strength: float = 0.5,
        contradiction_source: Optional[str] = None,
        contradiction_text: str = "",
    ) -> ConfidenceInfo:
        """
        处理矛盾信息
        
        降低置信度，但不归零。
        
        Args:
            current: 当前置信度信息
            contradiction_strength: 矛盾强度 (0-1)
            contradiction_source: 矛盾来源
            contradiction_text: 矛盾描述
        
        Returns:
            降低后的 ConfidenceInfo
        """
        # 降低置信度
        penalty = contradiction_strength * self.contradiction_penalty
        new_value = current.value * (1 - penalty)
        new_value = max(self.min_confidence, new_value)
        
        # 记录矛盾证据
        new_evidence_records = current.evidence_records.copy()
        if contradiction_source:
            new_evidence_records.append(EvidenceRecord(
                source=contradiction_source,
                source_type=SourceType.INFERENCE,
                confidence=-contradiction_strength,  # 负值表示矛盾
                evidence_text=f"[矛盾] {contradiction_text}",
            ))
        
        logger.debug(
            f"[ConfidenceManager] 矛盾: {current.value:.3f} → {new_value:.3f} "
            f"(strength={contradiction_strength})"
        )
        
        return ConfidenceInfo(
            value=new_value,
            sources=current.sources,
            evidence_records=new_evidence_records,
            last_verified=current.last_verified,
            last_updated=datetime.now(),
            contradiction_count=current.contradiction_count + 1,
            verification_count=current.verification_count,
        )
    
    def reinforce(
        self,
        current: ConfidenceInfo,
        reinforcement_strength: float = 0.3,
    ) -> ConfidenceInfo:
        """
        强化置信度（被引用/提及时调用）
        
        不添加新来源，但提升置信度并刷新验证时间。
        
        Args:
            current: 当前置信度信息
            reinforcement_strength: 强化强度 (0-1)
        
        Returns:
            强化后的 ConfidenceInfo
        """
        # 使用累积公式的简化版本
        delta = reinforcement_strength * self.same_source_delta_factor
        new_value = 1 - (1 - current.value) * (1 - delta)
        new_value = self._clamp(new_value)
        
        return ConfidenceInfo(
            value=new_value,
            sources=current.sources,
            evidence_records=current.evidence_records,
            last_verified=datetime.now(),
            last_updated=datetime.now(),
            contradiction_count=current.contradiction_count,
            verification_count=current.verification_count + 1,
        )
    
    def merge(
        self,
        info_list: List[ConfidenceInfo],
        strategy: str = "weighted_average",
    ) -> ConfidenceInfo:
        """
        合并多个置信度信息
        
        用于合并重复实体/边的置信度。
        
        Args:
            info_list: 置信度信息列表
            strategy: 合并策略
                - "max": 取最高值
                - "average": 简单平均
                - "weighted_average": 按来源数加权平均
                - "accumulate": 依次累积
        
        Returns:
            合并后的 ConfidenceInfo
        """
        if not info_list:
            return self.create()
        
        if len(info_list) == 1:
            return info_list[0]
        
        if strategy == "max":
            best = max(info_list, key=lambda x: x.value)
            return best
        
        elif strategy == "average":
            avg_value = sum(info.value for info in info_list) / len(info_list)
            merged_sources = list(set(s for info in info_list for s in info.sources))
            merged_evidence = [e for info in info_list for e in info.evidence_records]
            
            return ConfidenceInfo(
                value=self._clamp(avg_value),
                sources=merged_sources,
                evidence_records=merged_evidence,
                last_updated=datetime.now(),
                verification_count=sum(info.verification_count for info in info_list),
            )
        
        elif strategy == "weighted_average":
            # 按来源数量加权
            total_weight = sum(max(1, info.source_count) for info in info_list)
            weighted_sum = sum(
                info.value * max(1, info.source_count) 
                for info in info_list
            )
            avg_value = weighted_sum / total_weight if total_weight > 0 else 0.5
            
            merged_sources = list(set(s for info in info_list for s in info.sources))
            merged_evidence = [e for info in info_list for e in info.evidence_records]
            
            return ConfidenceInfo(
                value=self._clamp(avg_value),
                sources=merged_sources,
                evidence_records=merged_evidence,
                last_updated=datetime.now(),
                verification_count=sum(info.verification_count for info in info_list),
            )
        
        elif strategy == "accumulate":
            # 依次累积
            result = info_list[0]
            for info in info_list[1:]:
                for evidence in info.evidence_records:
                    result = self.accumulate(
                        result,
                        evidence.confidence,
                        evidence.source,
                        evidence.evidence_text,
                        evidence.source_type,
                    )
            return result
        
        else:
            raise ValueError(f"Unknown merge strategy: {strategy}")
    
    def should_trust(
        self,
        info: ConfidenceInfo,
        threshold: float = 0.5,
    ) -> Tuple[bool, str]:
        """
        判断是否应该信任这个信息
        
        Args:
            info: 置信度信息
            threshold: 信任阈值
        
        Returns:
            (是否信任, 原因说明)
        """
        if info.value < threshold:
            return False, f"置信度 {info.value:.2f} 低于阈值 {threshold}"
        
        if info.contradiction_count > info.verification_count / 2:
            return False, f"矛盾次数过多 ({info.contradiction_count}/{info.verification_count})"
        
        if info.source_count == 0:
            return False, "无来源信息"
        
        # 检查最后验证时间
        if info.last_verified:
            days_since_verified = (datetime.now() - info.last_verified).days
            if days_since_verified > 365:
                return False, f"超过一年未验证 ({days_since_verified} 天)"
        
        return True, f"置信度 {info.value:.2f}，{info.source_count} 个来源"
    
    def _clamp(self, value: float) -> float:
        """将值限制在有效范围内"""
        return max(self.min_confidence, min(self.max_confidence, value))


# ============================================================
# 边的置信度扩展（用于 Graphiti 集成）
# ============================================================

@dataclass
class EdgeConfidence:
    """
    边（关系）的置信度包装
    
    用于在 Graphiti 边上附加置信度信息
    """
    edge_uuid: str
    fact: str
    confidence: ConfidenceInfo
    importance: float = 0.5          # 重要性（影响衰减速度）
    significance: float = 1.0        # 记忆清晰度（用于遗忘机制）
    reference_count: int = 0         # 被引用次数
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_uuid": self.edge_uuid,
            "fact": self.fact,
            "confidence": self.confidence.to_dict(),
            "importance": self.importance,
            "significance": self.significance,
            "reference_count": self.reference_count,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'EdgeConfidence':
        return cls(
            edge_uuid=d["edge_uuid"],
            fact=d["fact"],
            confidence=ConfidenceInfo.from_dict(d["confidence"]),
            importance=d.get("importance", 0.5),
            significance=d.get("significance", 1.0),
            reference_count=d.get("reference_count", 0),
        )


# ============================================================
# 便捷函数
# ============================================================

_default_manager: Optional[ConfidenceManager] = None


def get_confidence_manager() -> ConfidenceManager:
    """获取默认置信度管理器（单例模式）"""
    global _default_manager
    if _default_manager is None:
        _default_manager = ConfidenceManager()
    return _default_manager


def create_confidence(
    initial_value: float = 0.5,
    source: Optional[str] = None,
    source_type: SourceType = SourceType.USER_INPUT,
) -> ConfidenceInfo:
    """创建置信度信息的快捷函数"""
    return get_confidence_manager().create(initial_value, source, source_type)


def accumulate_confidence(
    current: ConfidenceInfo,
    new_confidence: float,
    new_source: str,
    evidence_text: str = "",
) -> ConfidenceInfo:
    """累积置信度的快捷函数"""
    return get_confidence_manager().accumulate(
        current, new_confidence, new_source, evidence_text
    )


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    manager = ConfidenceManager()
    
    print("=" * 60)
    print("置信度管理器测试")
    print("=" * 60)
    
    # 1. 创建初始置信度
    print("\n1. 创建初始置信度")
    info = manager.create(
        initial_confidence=0.5,
        source="user_input_001",
        source_type=SourceType.USER_INPUT,
        evidence_text="用户说：主人喜欢喝咖啡",
    )
    print(f"   初始: {info.value:.3f} ({info.level.value})")
    
    # 2. 累积来自新来源的验证
    print("\n2. 累积新来源验证")
    info = manager.accumulate(
        info,
        new_confidence=0.8,
        new_source="diary_2024_12_25",
        evidence_text="日记记录：今天去星巴克喝了拿铁",
        source_type=SourceType.DIARY,
    )
    print(f"   累积后: {info.value:.3f} ({info.level.value})")
    print(f"   来源数: {info.source_count}")
    
    # 3. 相同来源再次验证
    print("\n3. 相同来源再次验证")
    info = manager.accumulate(
        info,
        new_confidence=0.7,
        new_source="diary_2024_12_25",  # 相同来源
        evidence_text="日记记录：又在咖啡厅工作",
        source_type=SourceType.DIARY,
    )
    print(f"   累积后: {info.value:.3f} ({info.level.value})")
    print(f"   来源数: {info.source_count}")
    
    # 4. 时间衰减
    print("\n4. 模拟 30 天后的衰减")
    decayed = manager.decay(info, days_passed=30, importance=0.5)
    print(f"   衰减后: {decayed.value:.3f} ({decayed.level.value})")
    
    # 5. 高重要性信息衰减更慢
    print("\n5. 高重要性信息 (importance=0.9) 30天衰减")
    important_decayed = manager.decay(info, days_passed=30, importance=0.9)
    print(f"   衰减后: {important_decayed.value:.3f} ({important_decayed.level.value})")
    
    # 6. 矛盾处理
    print("\n6. 处理矛盾信息")
    contradicted = manager.contradict(
        info,
        contradiction_strength=0.6,
        contradiction_source="conv_001",
        contradiction_text="用户说其实不太喜欢咖啡",
    )
    print(f"   矛盾后: {contradicted.value:.3f} ({contradicted.level.value})")
    print(f"   矛盾次数: {contradicted.contradiction_count}")
    
    # 7. 强化
    print("\n7. 强化置信度（被引用时）")
    reinforced = manager.reinforce(info, reinforcement_strength=0.5)
    print(f"   强化后: {reinforced.value:.3f} ({reinforced.level.value})")
    
    # 8. 是否应该信任
    print("\n8. 信任判断")
    trust, reason = manager.should_trust(info, threshold=0.5)
    print(f"   信任: {trust}, 原因: {reason}")
    
    trust, reason = manager.should_trust(contradicted, threshold=0.5)
    print(f"   矛盾后信任: {trust}, 原因: {reason}")
    
    # 9. 合并多个置信度
    print("\n9. 合并多个置信度")
    info2 = manager.create(0.7, "source_2", SourceType.CONVERSATION)
    info3 = manager.create(0.9, "source_3", SourceType.DIARY)
    merged = manager.merge([info, info2, info3], strategy="weighted_average")
    print(f"   合并后: {merged.value:.3f}")
    print(f"   来源数: {merged.source_count}")
    
    # 10. JSON 序列化
    print("\n10. JSON 序列化")
    json_str = info.to_json()
    print(f"   JSON (前100字符): {json_str[:100]}...")
    restored = ConfidenceInfo.from_json(json_str)
    print(f"   恢复后: {restored.value:.3f}")
"""
记忆衰减管理器

借鉴 LingYi 的 significance 衰减机制，实现模拟人类记忆的遗忘曲线。

核心设计：
1. significance 属性：记忆清晰度（0-1）
2. 衰减公式：基于 Ebbinghaus 遗忘曲线
3. 强化机制：被引用时提升 significance
4. 归档策略：低于阈值的记忆可归档

衰减公式（来自 LingYi）:
    decay_rate = (1 - importance²) / 100
    new_significance = significance * exp(-decay_rate * days)

使用方式：
    manager = MemoryDecayManager()
    
    # 计算衰减后的 significance
    sig = manager.calculate_significance(edge_data)
    
    # 强化记忆（被引用时）
    edge_data = manager.reinforce(edge_data)
    
    # 批量衰减并分类
    active, archive = manager.batch_decay(edges, threshold=0.3)
"""

from __future__ import annotations

import math
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class MemoryStatus(Enum):
    """记忆状态枚举"""
    ACTIVE = "active"           # 活跃记忆
    FADING = "fading"           # 正在衰减
    DORMANT = "dormant"         # 休眠（低活跃）
    ARCHIVED = "archived"       # 已归档


@dataclass
class DecayConfig:
    """衰减配置"""
    base_decay_rate: float = 0.1        # 基础衰减率
    min_significance: float = 0.1       # 最低 significance
    reinforce_boost: float = 0.3        # 强化提升量
    archive_threshold: float = 0.3      # 归档阈值
    dormant_threshold: float = 0.5      # 休眠阈值
    
    # 重要性对衰减的影响
    importance_decay_factor: float = 1.0  # importance² 的系数
    
    # 引用次数对衰减的影响
    reference_decay_reduction: float = 0.5  # 引用次数降低衰减的程度
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_decay_rate": self.base_decay_rate,
            "min_significance": self.min_significance,
            "reinforce_boost": self.reinforce_boost,
            "archive_threshold": self.archive_threshold,
            "dormant_threshold": self.dormant_threshold,
            "importance_decay_factor": self.importance_decay_factor,
            "reference_decay_reduction": self.reference_decay_reduction,
        }


@dataclass
class MemoryState:
    """
    记忆状态
    
    存储在边的 metadata 或单独的表中
    """
    significance: float = 1.0           # 记忆清晰度
    importance: float = 0.5             # 重要性（影响衰减速度）
    reference_count: int = 0            # 被引用次数
    last_accessed: Optional[datetime] = None  # 最后访问时间
    last_reinforced: Optional[datetime] = None  # 最后强化时间
    created_at: datetime = field(default_factory=datetime.now)
    status: MemoryStatus = MemoryStatus.ACTIVE
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "significance": self.significance,
            "importance": self.importance,
            "reference_count": self.reference_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "last_reinforced": self.last_reinforced.isoformat() if self.last_reinforced else None,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'MemoryState':
        return cls(
            significance=d.get("significance", 1.0),
            importance=d.get("importance", 0.5),
            reference_count=d.get("reference_count", 0),
            last_accessed=datetime.fromisoformat(d["last_accessed"]) if d.get("last_accessed") else None,
            last_reinforced=datetime.fromisoformat(d["last_reinforced"]) if d.get("last_reinforced") else None,
            created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.now(),
            status=MemoryStatus(d.get("status", "active")),
        )
    
    @classmethod
    def from_edge_data(cls, edge_data: Dict[str, Any]) -> 'MemoryState':
        """从边数据构建 MemoryState"""
        # 尝试从 metadata 或直接属性获取
        metadata = edge_data.get("metadata", {})
        memory_state = metadata.get("memory_state", {})
        
        if memory_state:
            return cls.from_dict(memory_state)
        
        # 从边的基本属性推断
        created_at = edge_data.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except:
                created_at = datetime.now()
        elif not isinstance(created_at, datetime):
            created_at = datetime.now()
        
        return cls(
            significance=edge_data.get("significance", 1.0),
            importance=edge_data.get("importance", 0.5),
            reference_count=edge_data.get("reference_count", 0),
            last_accessed=None,
            last_reinforced=None,
            created_at=created_at,
            status=MemoryStatus.ACTIVE,
        )


@dataclass
class DecayResult:
    """衰减计算结果"""
    original_significance: float
    new_significance: float
    decay_amount: float
    days_since_last_access: int
    new_status: MemoryStatus
    should_archive: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_significance": self.original_significance,
            "new_significance": self.new_significance,
            "decay_amount": self.decay_amount,
            "days_since_last_access": self.days_since_last_access,
            "new_status": self.new_status.value,
            "should_archive": self.should_archive,
        }


class MemoryDecayManager:
    """
    记忆衰减管理器
    
    实现 Ebbinghaus 遗忘曲线启发的衰减机制：
    - 新记忆衰减快
    - 被多次强化的记忆衰减慢
    - 高重要性记忆衰减慢
    """
    
    def __init__(self, config: Optional[DecayConfig] = None):
        """
        初始化衰减管理器
        
        Args:
            config: 衰减配置（可选）
        """
        self.config = config or DecayConfig()
    
    def calculate_significance(
        self,
        edge_data: Dict[str, Any],
        reference_time: Optional[datetime] = None,
    ) -> float:
        """
        计算边的当前 significance
        
        考虑因素：
        - 上次访问/更新时间
        - importance 属性
        - 被引用次数
        
        Args:
            edge_data: 边数据字典
            reference_time: 参考时间点（默认当前时间）
        
        Returns:
            当前 significance 值
        """
        reference_time = reference_time or datetime.now()
        state = MemoryState.from_edge_data(edge_data)
        
        # 计算时间差
        last_time = state.last_accessed or state.last_reinforced or state.created_at
        days_passed = (reference_time - last_time).days
        
        if days_passed <= 0:
            return state.significance
        
        # 计算衰减率
        decay_rate = self._calculate_decay_rate(state)
        
        # 指数衰减
        decay_factor = math.exp(-decay_rate * days_passed)
        new_significance = state.significance * decay_factor
        
        return max(self.config.min_significance, new_significance)
    
    def calculate_decay(
        self,
        edge_data: Dict[str, Any],
        reference_time: Optional[datetime] = None,
    ) -> DecayResult:
        """
        计算详细的衰减结果
        
        Args:
            edge_data: 边数据字典
            reference_time: 参考时间点
        
        Returns:
            DecayResult 详细结果
        """
        reference_time = reference_time or datetime.now()
        state = MemoryState.from_edge_data(edge_data)
        
        last_time = state.last_accessed or state.last_reinforced or state.created_at
        days_passed = (reference_time - last_time).days
        
        original = state.significance
        new_sig = self.calculate_significance(edge_data, reference_time)
        
        # 确定新状态
        if new_sig < self.config.archive_threshold:
            new_status = MemoryStatus.ARCHIVED
        elif new_sig < self.config.dormant_threshold:
            new_status = MemoryStatus.DORMANT
        elif new_sig < original:
            new_status = MemoryStatus.FADING
        else:
            new_status = MemoryStatus.ACTIVE
        
        return DecayResult(
            original_significance=original,
            new_significance=new_sig,
            decay_amount=original - new_sig,
            days_since_last_access=max(0, days_passed),
            new_status=new_status,
            should_archive=new_sig < self.config.archive_threshold,
        )
    
    def reinforce(
        self,
        edge_data: Dict[str, Any],
        reinforcement_strength: float = 1.0,
    ) -> Dict[str, Any]:
        """
        强化记忆（被引用/访问时调用）
        
        效果：
        - 提升 significance
        - 增加 reference_count
        - 更新 last_accessed 和 last_reinforced
        
        Args:
            edge_data: 边数据字典
            reinforcement_strength: 强化强度 (0-1)
        
        Returns:
            更新后的边数据
        """
        state = MemoryState.from_edge_data(edge_data)
        
        # 计算当前 significance（可能已衰减）
        current_sig = self.calculate_significance(edge_data)
        
        # 提升 significance
        boost = self.config.reinforce_boost * reinforcement_strength
        new_sig = min(1.0, current_sig + boost * (1 - current_sig))
        
        # 更新边数据
        now = datetime.now()
        
        edge_data["significance"] = new_sig
        edge_data["reference_count"] = state.reference_count + 1
        edge_data["last_accessed"] = now.isoformat()
        
        # 更新 metadata
        if "metadata" not in edge_data:
            edge_data["metadata"] = {}
        
        state.significance = new_sig
        state.reference_count += 1
        state.last_accessed = now
        state.last_reinforced = now
        state.status = MemoryStatus.ACTIVE
        
        edge_data["metadata"]["memory_state"] = state.to_dict()
        
        logger.debug(
            f"[MemoryDecay] 强化: {current_sig:.3f} → {new_sig:.3f} "
            f"(strength={reinforcement_strength}, refs={state.reference_count})"
        )
        
        return edge_data
    
    def apply_decay(
        self,
        edge_data: Dict[str, Any],
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        应用衰减到边数据
        
        更新 significance 和状态
        
        Args:
            edge_data: 边数据字典
            reference_time: 参考时间点
        
        Returns:
            更新后的边数据
        """
        result = self.calculate_decay(edge_data, reference_time)
        
        edge_data["significance"] = result.new_significance
        
        # 更新 metadata
        if "metadata" not in edge_data:
            edge_data["metadata"] = {}
        
        state = MemoryState.from_edge_data(edge_data)
        state.significance = result.new_significance
        state.status = result.new_status
        
        edge_data["metadata"]["memory_state"] = state.to_dict()
        edge_data["metadata"]["decay_info"] = result.to_dict()
        
        return edge_data
    
    def batch_decay(
        self,
        edges: List[Dict[str, Any]],
        reference_time: Optional[datetime] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        批量计算衰减，返回需要保留和可以归档的边
        
        Args:
            edges: 边列表
            reference_time: 参考时间点
        
        Returns:
            (active_edges, archive_edges) 元组
        """
        reference_time = reference_time or datetime.now()
        
        active = []
        archive = []
        
        for edge in edges:
            result = self.calculate_decay(edge, reference_time)
            
            # 应用衰减
            edge["significance"] = result.new_significance
            
            if result.should_archive:
                archive.append(edge)
            else:
                active.append(edge)
        
        logger.info(
            f"[MemoryDecay] 批量衰减: {len(edges)} 条 → "
            f"活跃 {len(active)} 条, 归档 {len(archive)} 条"
        )
        
        return active, archive
    
    def get_memory_stats(
        self,
        edges: List[Dict[str, Any]],
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        获取记忆统计信息
        
        Args:
            edges: 边列表
            reference_time: 参考时间点
        
        Returns:
            统计信息字典
        """
        reference_time = reference_time or datetime.now()
        
        stats = {
            "total": len(edges),
            "active": 0,
            "fading": 0,
            "dormant": 0,
            "archived": 0,
            "avg_significance": 0.0,
            "avg_reference_count": 0.0,
        }
        
        if not edges:
            return stats
        
        total_sig = 0.0
        total_refs = 0
        
        for edge in edges:
            result = self.calculate_decay(edge, reference_time)
            
            if result.new_status == MemoryStatus.ACTIVE:
                stats["active"] += 1
            elif result.new_status == MemoryStatus.FADING:
                stats["fading"] += 1
            elif result.new_status == MemoryStatus.DORMANT:
                stats["dormant"] += 1
            else:
                stats["archived"] += 1
            
            total_sig += result.new_significance
            total_refs += edge.get("reference_count", 0)
        
        stats["avg_significance"] = total_sig / len(edges)
        stats["avg_reference_count"] = total_refs / len(edges)
        
        return stats
    
    def _calculate_decay_rate(self, state: MemoryState) -> float:
        """
        计算衰减率
        
        公式: decay_rate = base_rate * (1 - importance²) / reference_factor
        
        - 重要性高 → 衰减慢
        - 引用次数多 → 衰减慢
        """
        # 重要性因子：importance² 在 0-1 之间
        importance_factor = 1 - (state.importance ** 2) * self.config.importance_decay_factor
        
        # 引用次数因子：引用越多衰减越慢
        if state.reference_count > 0:
            reference_factor = 1 / (1 + math.log1p(state.reference_count) * self.config.reference_decay_reduction)
        else:
            reference_factor = 1.0
        
        decay_rate = self.config.base_decay_rate * importance_factor * reference_factor
        
        return max(0.001, decay_rate)  # 最小衰减率


# ============================================================
# 定时衰减任务调度器
# ============================================================

class DecayScheduler:
    """
    衰减调度器
    
    用于定期执行衰减计算和归档操作
    """
    
    def __init__(
        self,
        decay_manager: MemoryDecayManager,
        interval_hours: int = 24,
    ):
        """
        初始化调度器
        
        Args:
            decay_manager: 衰减管理器
            interval_hours: 执行间隔（小时）
        """
        self.decay_manager = decay_manager
        self.interval_hours = interval_hours
        self._last_run: Optional[datetime] = None
    
    def should_run(self) -> bool:
        """检查是否应该执行衰减"""
        if self._last_run is None:
            return True
        
        elapsed = datetime.now() - self._last_run
        return elapsed >= timedelta(hours=self.interval_hours)
    
    async def run_decay_cycle(
        self,
        get_edges_func,
        update_edges_func,
        archive_edges_func=None,
    ) -> Dict[str, Any]:
        """
        执行一次衰减周期
        
        Args:
            get_edges_func: 获取边的函数 () -> List[Dict]
            update_edges_func: 更新边的函数 (List[Dict]) -> None
            archive_edges_func: 归档边的函数 (List[Dict]) -> None（可选）
        
        Returns:
            执行结果统计
        """
        if not self.should_run():
            return {"skipped": True, "reason": "not due yet"}
        
        start_time = datetime.now()
        
        # 获取所有边
        edges = await get_edges_func()
        
        if not edges:
            self._last_run = start_time
            return {"skipped": True, "reason": "no edges"}
        
        # 批量衰减
        active, archive = self.decay_manager.batch_decay(edges)
        
        # 更新活跃边
        if active:
            await update_edges_func(active)
        
        # 归档边（如果提供了归档函数）
        if archive and archive_edges_func:
            await archive_edges_func(archive)
        
        self._last_run = start_time
        
        return {
            "skipped": False,
            "total_processed": len(edges),
            "active_count": len(active),
            "archived_count": len(archive),
            "duration_ms": (datetime.now() - start_time).total_seconds() * 1000,
        }


# ============================================================
# 便捷函数
# ============================================================

_default_manager: Optional[MemoryDecayManager] = None


def get_decay_manager(config: Optional[DecayConfig] = None) -> MemoryDecayManager:
    """获取默认衰减管理器（单例模式）"""
    global _default_manager
    if _default_manager is None:
        _default_manager = MemoryDecayManager(config)
    return _default_manager


def calculate_significance(edge_data: Dict[str, Any]) -> float:
    """计算 significance 的快捷函数"""
    return get_decay_manager().calculate_significance(edge_data)


def reinforce_memory(edge_data: Dict[str, Any], strength: float = 1.0) -> Dict[str, Any]:
    """强化记忆的快捷函数"""
    return get_decay_manager().reinforce(edge_data, strength)


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    manager = MemoryDecayManager()
    
    print("=" * 60)
    print("记忆衰减管理器测试")
    print("=" * 60)
    
    # 1. 创建测试边
    print("\n1. 创建测试边")
    edge = {
        "uuid": "test_edge_001",
        "fact": "主人喜欢喝咖啡",
        "significance": 1.0,
        "importance": 0.5,
        "reference_count": 0,
        "created_at": (datetime.now() - timedelta(days=30)).isoformat(),
    }
    print(f"   初始 significance: {edge['significance']}")
    
    # 2. 计算衰减
    print("\n2. 计算 30 天后的衰减")
    result = manager.calculate_decay(edge)
    print(f"   衰减: {result.original_significance:.3f} → {result.new_significance:.3f}")
    print(f"   状态: {result.new_status.value}")
    print(f"   应归档: {result.should_archive}")
    
    # 3. 高重要性边的衰减
    print("\n3. 高重要性边 (importance=0.9) 的衰减")
    important_edge = {**edge, "importance": 0.9}
    result = manager.calculate_decay(important_edge)
    print(f"   衰减: {result.original_significance:.3f} → {result.new_significance:.3f}")
    
    # 4. 多次引用的边
    print("\n4. 多次引用的边 (reference_count=10) 的衰减")
    referenced_edge = {**edge, "reference_count": 10}
    result = manager.calculate_decay(referenced_edge)
    print(f"   衰减: {result.original_significance:.3f} → {result.new_significance:.3f}")
    
    # 5. 强化记忆
    print("\n5. 强化记忆")
    edge_copy = {**edge}
    edge_copy = manager.reinforce(edge_copy, reinforcement_strength=0.8)
    print(f"   强化后 significance: {edge_copy['significance']:.3f}")
    print(f"   引用次数: {edge_copy['reference_count']}")
    
    # 6. 批量衰减
    print("\n6. 批量衰减测试")
    edges = [
        {"uuid": f"edge_{i}", "fact": f"事实 {i}", 
         "significance": 1.0, "importance": 0.3 + i*0.1, "reference_count": i,
         "created_at": (datetime.now() - timedelta(days=30+i*10)).isoformat()}
        for i in range(5)
    ]
    active, archive = manager.batch_decay(edges)
    print(f"   输入: {len(edges)} 条")
    print(f"   活跃: {len(active)} 条")
    print(f"   归档: {len(archive)} 条")
    
    # 7. 统计信息
    print("\n7. 统计信息")
    stats = manager.get_memory_stats(edges)
    print(f"   总数: {stats['total']}")
    print(f"   活跃: {stats['active']}")
    print(f"   衰减中: {stats['fading']}")
    print(f"   休眠: {stats['dormant']}")
    print(f"   归档: {stats['archived']}")
    print(f"   平均 significance: {stats['avg_significance']:.3f}")
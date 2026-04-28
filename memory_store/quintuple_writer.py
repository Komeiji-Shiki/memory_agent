"""
五元组显式写入工具

提供直接写入结构化记忆到 Graphiti 的能力，跳过 LLM 抽取。

五元组格式：
- subject: 主体（如"主人"、"小明"）
- predicate: 谓词/关系（如"喜欢"、"住在"）
- object: 宾语/对象（如"咖啡"、"北京"）
- time: 时间（可选）
- location: 地点（可选）

使用场景：
1. 用户明确告知某个事实
2. 从对话中提取的高置信度信息
3. 手动整理的核心记忆
4. 使用标注语法输入的记忆

使用方式：
    writer = QuintupleWriter(graphiti_adapter)
    
    # 写入五元组
    result = await writer.write(
        subject="主人",
        predicate="喜欢喝",
        object="咖啡",
        time="每天早上",
        location="家里",
        importance=0.8,
    )
    
    # 从标注文本写入
    result = await writer.write_from_annotation(
        "<主人>在[每天早上](家里)喝{咖啡}"
    )
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class WriteMode(Enum):
    """写入模式"""
    DIRECT = "direct"           # 直接写入，跳过 LLM
    VALIDATE = "validate"       # 写入前验证（使用 LLM 检查重复）
    MERGE = "merge"             # 合并到现有边


@dataclass
class Quintuple:
    """五元组数据结构"""
    subject: str
    predicate: str
    object: str
    time: Optional[str] = None
    location: Optional[str] = None
    
    # 扩展字段
    subject_type: str = "Entity"
    object_type: str = "Entity"
    with_persons: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    
    # 元数据
    importance: float = 0.5
    confidence: float = 0.8
    source: str = "user_input"
    context: str = "reality"  # reality | fiction | hypothesis
    
    def to_fact(self) -> str:
        """转换为事实陈述"""
        parts = []
        
        if self.subject:
            parts.append(self.subject)
        
        if self.time:
            parts.append(f"在{self.time}")
        
        if self.location:
            parts.append(f"于{self.location}")
        
        if self.predicate:
            parts.append(self.predicate)
        
        if self.object:
            parts.append(self.object)
        
        if self.with_persons:
            parts.append(f"，同行者：{', '.join(self.with_persons)}")
        
        return "".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "time": self.time,
            "location": self.location,
            "subject_type": self.subject_type,
            "object_type": self.object_type,
            "with_persons": self.with_persons,
            "tags": self.tags,
            "importance": self.importance,
            "confidence": self.confidence,
            "source": self.source,
            "context": self.context,
            "fact": self.to_fact(),
        }


@dataclass
class WriteResult:
    """写入结果"""
    success: bool
    edge_uuid: Optional[str] = None
    source_node_uuid: Optional[str] = None
    target_node_uuid: Optional[str] = None
    fact: str = ""
    message: str = ""
    merged_with: Optional[str] = None  # 如果合并了，记录目标边 UUID
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "edge_uuid": self.edge_uuid,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "fact": self.fact,
            "message": self.message,
            "merged_with": self.merged_with,
        }


class QuintupleWriter:
    """
    五元组写入器
    
    直接将结构化记忆写入 Graphiti，跳过昂贵的 LLM 抽取。
    适用于用户明确输入或高置信度的结构化信息。
    """
    
    def __init__(
        self,
        graphiti_adapter=None,
        default_group_id: str = "lifebook",
        auto_create_nodes: bool = True,
    ):
        """
        初始化写入器
        
        Args:
            graphiti_adapter: Graphiti 适配器实例
            default_group_id: 默认分组 ID
            auto_create_nodes: 是否自动创建不存在的节点
        """
        self.graphiti = graphiti_adapter
        self.default_group_id = default_group_id
        self.auto_create_nodes = auto_create_nodes
        
        # 延迟导入标注解析器
        self._annotation_parser = None
    
    @property
    def annotation_parser(self):
        """延迟加载标注解析器"""
        if self._annotation_parser is None:
            from .annotation_parser import AnnotationParser
            self._annotation_parser = AnnotationParser()
        return self._annotation_parser
    
    async def write(
        self,
        subject: str,
        predicate: str,
        object: str,
        time: Optional[str] = None,
        location: Optional[str] = None,
        with_persons: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        importance: float = 0.5,
        confidence: float = 0.8,
        source: str = "user_input",
        context: str = "reality",
        mode: WriteMode = WriteMode.DIRECT,
        group_id: Optional[str] = None,
    ) -> WriteResult:
        """
        写入五元组到知识图谱
        
        Args:
            subject: 主体
            predicate: 谓词/关系
            object: 宾语/对象
            time: 时间（可选）
            location: 地点（可选）
            with_persons: 同行者（可选）
            tags: 标签（可选）
            importance: 重要性 (0-1)
            confidence: 置信度 (0-1)
            source: 来源标识
            context: 上下文类型
            mode: 写入模式
            group_id: 分组 ID
        
        Returns:
            WriteResult
        """
        quintuple = Quintuple(
            subject=subject,
            predicate=predicate,
            object=object,
            time=time,
            location=location,
            with_persons=with_persons or [],
            tags=tags or [],
            importance=importance,
            confidence=confidence,
            source=source,
            context=context,
        )
        
        return await self._write_quintuple(quintuple, mode, group_id)
    
    async def write_from_annotation(
        self,
        annotated_text: str,
        importance: float = 0.5,
        confidence: float = 0.8,
        source: str = "annotation",
        mode: WriteMode = WriteMode.DIRECT,
        group_id: Optional[str] = None,
    ) -> WriteResult:
        """
        从标注文本写入
        
        解析标注语法，转换为五元组后写入。
        
        Args:
            annotated_text: 带标注的文本
            importance: 重要性
            confidence: 置信度
            source: 来源
            mode: 写入模式
            group_id: 分组 ID
        
        Returns:
            WriteResult
        """
        # 解析标注
        parsed = self.annotation_parser.parse(annotated_text)
        
        if not parsed.has_annotations:
            # 没有标注，作为普通文本处理
            return WriteResult(
                success=False,
                message="文本不包含有效标注，请使用标注语法：<角色>[时间](地点){事物}",
            )
        
        # 转换为五元组
        quintuple = Quintuple(
            subject=parsed.subject or "主人",
            predicate=parsed.predicate or "",
            object=parsed.object or (parsed.entities[0] if parsed.entities else ""),
            time=parsed.time.raw if parsed.time else None,
            location=parsed.location,
            subject_type=parsed.subject_type.value if hasattr(parsed.subject_type, 'value') else str(parsed.subject_type),
            with_persons=parsed.with_persons,
            tags=parsed.tags,
            importance=importance,
            confidence=confidence,
            source=source,
        )
        
        return await self._write_quintuple(quintuple, mode, group_id)
    
    async def write_batch(
        self,
        quintuples: List[Quintuple],
        mode: WriteMode = WriteMode.DIRECT,
        group_id: Optional[str] = None,
    ) -> List[WriteResult]:
        """
        批量写入五元组
        
        Args:
            quintuples: 五元组列表
            mode: 写入模式
            group_id: 分组 ID
        
        Returns:
            WriteResult 列表
        """
        results = []
        for q in quintuples:
            result = await self._write_quintuple(q, mode, group_id)
            results.append(result)
        return results
    
    async def _write_quintuple(
        self,
        quintuple: Quintuple,
        mode: WriteMode,
        group_id: Optional[str],
    ) -> WriteResult:
        """内部写入方法"""
        group_id = group_id or self.default_group_id
        fact = quintuple.to_fact()
        
        # 检查 Graphiti 是否可用
        if not self.graphiti:
            logger.warning("[QuintupleWriter] Graphiti 适配器未配置")
            return WriteResult(
                success=False,
                fact=fact,
                message="Graphiti 适配器未配置",
            )
        
        try:
            # 根据模式选择写入策略
            if mode == WriteMode.VALIDATE:
                # 先搜索是否存在类似的边
                existing = await self._find_similar_edge(quintuple, group_id)
                if existing:
                    return WriteResult(
                        success=False,
                        fact=fact,
                        message=f"发现类似的记忆: {existing.get('fact', '')}",
                        merged_with=existing.get('uuid'),
                    )
            
            elif mode == WriteMode.MERGE:
                # 尝试合并到现有边
                existing = await self._find_similar_edge(quintuple, group_id)
                if existing:
                    merged = await self._merge_edge(existing, quintuple)
                    return WriteResult(
                        success=True,
                        edge_uuid=merged.get('uuid'),
                        fact=merged.get('fact', fact),
                        message="已合并到现有记忆",
                        merged_with=existing.get('uuid'),
                    )
            
            # 直接写入
            result = await self._create_triplet(quintuple, group_id)
            
            return WriteResult(
                success=True,
                edge_uuid=result.get('edge_uuid'),
                source_node_uuid=result.get('source_node_uuid'),
                target_node_uuid=result.get('target_node_uuid'),
                fact=fact,
                message="写入成功",
            )
            
        except Exception as e:
            logger.error(f"[QuintupleWriter] 写入失败: {e}")
            return WriteResult(
                success=False,
                fact=fact,
                message=f"写入失败: {str(e)}",
            )
    
    async def _create_triplet(
        self,
        quintuple: Quintuple,
        group_id: str,
    ) -> Dict[str, Any]:
        """
        创建三元组（节点-边-节点）
        
        使用 Graphiti 的 add_triplet 方法直接创建，
        跳过昂贵的 LLM 抽取过程。
        """
        now = datetime.now()
        
        # 解析时间
        valid_at = now
        if quintuple.time:
            try:
                from .hierarchical_time import ChineseTimeExtractor
                extractor = ChineseTimeExtractor()
                time_info = extractor.extract(quintuple.time)
                parsed_dt = extractor.to_datetime(time_info)
                if parsed_dt:
                    valid_at = parsed_dt
            except Exception:
                pass
        
        # 检查 Graphiti 是否有 add_triplet 方法
        if hasattr(self.graphiti, '_graphiti') and hasattr(self.graphiti._graphiti, 'add_triplet'):
            # 使用 Graphiti 原生的 add_triplet
            from graphiti_core.nodes import EntityNode
            from graphiti_core.edges import EntityEdge
            
            source_node = EntityNode(
                name=quintuple.subject,
                labels=[quintuple.subject_type, "Entity"],
                summary=f"{quintuple.subject}",
                group_id=group_id,
                created_at=now,
            )
            
            target_node = EntityNode(
                name=quintuple.object,
                labels=[quintuple.object_type, "Entity"],
                summary=f"{quintuple.object}",
                group_id=group_id,
                created_at=now,
            )
            
            edge = EntityEdge(
                name=quintuple.predicate,
                fact=quintuple.to_fact(),
                source_node_uuid=source_node.uuid,
                target_node_uuid=target_node.uuid,
                group_id=group_id,
                created_at=now,
                valid_at=valid_at,
                episodes=[],
                attributes={
                    "importance": quintuple.importance,
                    "confidence": quintuple.confidence,
                    "source": quintuple.source,
                    "context": quintuple.context,
                    "time_raw": quintuple.time,
                    "location": quintuple.location,
                    "with_persons": quintuple.with_persons,
                    "tags": quintuple.tags,
                },
            )
            
            result = await self.graphiti._graphiti.add_triplet(
                source_node=source_node,
                edge=edge,
                target_node=target_node,
            )
            
            return {
                "edge_uuid": result.edges[0].uuid if result.edges else edge.uuid,
                "source_node_uuid": result.nodes[0].uuid if result.nodes else source_node.uuid,
                "target_node_uuid": result.nodes[1].uuid if len(result.nodes) > 1 else target_node.uuid,
            }
        
        else:
            # 降级：使用 add_episode 方法
            # 这会触发 LLM 抽取，但确保兼容性
            content = f"{quintuple.subject}{quintuple.predicate}{quintuple.object}"
            if quintuple.time:
                content = f"在{quintuple.time}，" + content
            if quintuple.location:
                content = f"于{quintuple.location}，" + content
            
            episode_uuid = await self.graphiti.add_episode(
                content=content,
                source=f"quintuple:{quintuple.source}",
                timestamp=valid_at,
            )
            
            return {
                "edge_uuid": None,  # 无法确定具体的边 UUID
                "source_node_uuid": None,
                "target_node_uuid": None,
                "episode_uuid": episode_uuid,
            }
    
    async def _find_similar_edge(
        self,
        quintuple: Quintuple,
        group_id: str,
    ) -> Optional[Dict[str, Any]]:
        """查找类似的边"""
        if not hasattr(self.graphiti, 'search'):
            return None
        
        try:
            # 搜索类似的事实
            results = await self.graphiti.search(
                query=quintuple.to_fact(),
                num_results=5,
                group_ids=[group_id],
            )
            
            # 检查是否有高度相似的结果
            for r in results:
                # 简单的相似度检查
                result_fact = r.content if hasattr(r, 'content') else r.get('content', '')
                if self._is_similar(quintuple.to_fact(), result_fact):
                    return {
                        "uuid": r.uuid if hasattr(r, 'uuid') else r.get('uuid'),
                        "fact": result_fact,
                    }
            
            return None
            
        except Exception as e:
            logger.warning(f"[QuintupleWriter] 查找类似边失败: {e}")
            return None
    
    async def _merge_edge(
        self,
        existing: Dict[str, Any],
        quintuple: Quintuple,
    ) -> Dict[str, Any]:
        """合并到现有边（简单实现：增加置信度）"""
        # 这里只是返回现有边的信息
        # 完整实现需要更新边的属性
        return existing
    
    def _is_similar(self, fact1: str, fact2: str, threshold: float = 0.7) -> bool:
        """简单的相似度检查"""
        # 简化实现：检查关键词重叠
        words1 = set(fact1.replace("，", " ").replace("。", " ").split())
        words2 = set(fact2.replace("，", " ").replace("。", " ").split())
        
        if not words1 or not words2:
            return False
        
        intersection = words1 & words2
        union = words1 | words2
        
        jaccard = len(intersection) / len(union)
        return jaccard >= threshold


# ============================================================
# 便捷函数
# ============================================================

_default_writer: Optional[QuintupleWriter] = None


def get_quintuple_writer(graphiti_adapter=None) -> QuintupleWriter:
    """获取默认写入器"""
    global _default_writer
    if _default_writer is None:
        _default_writer = QuintupleWriter(graphiti_adapter)
    return _default_writer


async def write_quintuple(
    subject: str,
    predicate: str,
    object: str,
    time: Optional[str] = None,
    location: Optional[str] = None,
    **kwargs,
) -> WriteResult:
    """写入五元组的快捷函数"""
    return await get_quintuple_writer().write(
        subject=subject,
        predicate=predicate,
        object=object,
        time=time,
        location=location,
        **kwargs,
    )


async def write_from_annotation(
    annotated_text: str,
    **kwargs,
) -> WriteResult:
    """从标注文本写入的快捷函数"""
    return await get_quintuple_writer().write_from_annotation(
        annotated_text,
        **kwargs,
    )


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    import asyncio
    
    async def test():
        print("=" * 60)
        print("五元组写入器测试")
        print("=" * 60)
        
        writer = QuintupleWriter()  # 无 Graphiti 适配器
        
        # 1. 创建五元组
        print("\n1. 创建五元组")
        q = Quintuple(
            subject="主人",
            predicate="喜欢喝",
            object="咖啡",
            time="每天早上",
            location="家里",
            importance=0.8,
        )
        print(f"   五元组: {q.to_dict()}")
        print(f"   事实: {q.to_fact()}")
        
        # 2. 从标注解析
        print("\n2. 从标注解析")
        result = await writer.write_from_annotation(
            "<主人>在[2024年12月25日](家里)和<小明>一起吃{火锅}#美食#"
        )
        print(f"   结果: {result.to_dict()}")
        
        # 3. 直接写入（无适配器会失败）
        print("\n3. 直接写入")
        result = await writer.write(
            subject="主人",
            predicate="住在",
            object="北京",
        )
        print(f"   结果: {result.to_dict()}")
    
    asyncio.run(test())
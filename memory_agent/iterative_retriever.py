"""
MemR3 风格的迭代检索器

借鉴 MemR3 的 Evidence-Gap 闭环检索机制：
1. Retrieve - 基于当前查询检索
2. Filter - 使用 AI 筛选相关结果（新增，借鉴 LingYi）
3. Reflect - 评估证据是否充分，识别信息缺口 (Gap)
4. Refine - 根据 Gap 生成新的检索查询
5. 重复直到证据充分或达到最大迭代次数

核心思想：
    传统 Retrieve-then-Answer:
        用户问: "主人领养 Buddy 多久了？"
        1. 检索: 找到 "2024年12月领养了Buddy"
        2. 回答: "主人在2024年12月领养了Buddy" ← 没有回答"多久"！

    MemR3 迭代检索:
        1. 检索: 找到 "2024年12月领养了Buddy"
        2. 反思: 知道领养日期，但缺少"现在时间"来计算时长
        3. 再检索: 查询当前日期相关信息
        4. 回答: "主人领养Buddy已经X个月了" ✓

改进（借鉴 LingYi）:
    - 在 Retrieve 和 Reflect 之间增加 Filter 步骤
    - 使用 LLM 判断每个结果是否与查询相关
    - 过滤无关结果，提高检索精准度

参考: MemR3 Pipeline, Graphiti 论文 arXiv:2501.13956, LingYiProject
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)


class RetrievalAction(Enum):
    """检索动作枚举"""
    RETRIEVE = "retrieve"   # 继续检索
    ANSWER = "answer"       # 证据充分，可以回答了
    ABORT = "abort"         # 放弃（无法获取更多信息）


@dataclass
class EvidenceGapState:
    """
    Evidence-Gap 状态追踪器
    
    跟踪检索过程中的：
    - 已收集的证据
    - 识别出的信息缺口
    - 优化后的查询历史
    """
    query: str                                          # 原始查询
    evidence: List[Dict] = field(default_factory=list)  # 已收集的证据
    gaps: List[str] = field(default_factory=list)       # 信息缺口
    refined_queries: List[str] = field(default_factory=list)  # 优化后的查询
    iteration: int = 0                                  # 当前迭代次数
    
    def add_evidence(self, results: List[Dict]):
        """
        添加新证据，自动去重
        
        Args:
            results: 新检索到的结果列表
        """
        existing_ids = {e.get("uuid") or e.get("id") or hash(str(e)) for e in self.evidence}
        
        for r in results:
            result_id = r.get("uuid") or r.get("id") or hash(str(r))
            if result_id not in existing_ids:
                self.evidence.append(r)
                existing_ids.add(result_id)
    
    def get_evidence_summary(self, max_items: int = 10, max_content_len: int = 200) -> str:
        """
        获取证据摘要（用于 LLM 评估）
        
        Args:
            max_items: 最多显示多少条证据
            max_content_len: 每条证据内容最大长度
            
        Returns:
            格式化的证据摘要
        """
        if not self.evidence:
            return "暂无相关记忆"
        
        summary_lines = []
        for e in self.evidence[:max_items]:
            content = e.get("content", "") or e.get("fact", "") or str(e)
            if len(content) > max_content_len:
                content = content[:max_content_len] + "..."
            
            source = e.get("source", "unknown")
            valid_at = e.get("valid_at")
            
            line = f"- [{source}]"
            if valid_at:
                if hasattr(valid_at, 'strftime'):
                    line += f" ({valid_at.strftime('%Y-%m-%d')})"
                else:
                    line += f" ({str(valid_at)[:10]})"
            line += f" {content}"
            
            summary_lines.append(line)
        
        if len(self.evidence) > max_items:
            summary_lines.append(f"... 还有 {len(self.evidence) - max_items} 条")
        
        return "\n".join(summary_lines)
    
    def get_gaps_summary(self) -> str:
        """获取信息缺口摘要"""
        if not self.gaps:
            return "无明显信息缺口"
        return "、".join(self.gaps)


@dataclass
class IterativeRetrievalResult:
    """迭代检索结果"""
    evidence: List[Dict]
    evidence_summary: str
    iterations: int
    gaps: List[str]
    refined_queries: List[str]
    final_action: str
    success: bool = True
    error: Optional[str] = None
    # 新增：筛选统计
    filter_stats: Optional[Dict[str, Any]] = None


class IterativeRetriever:
    """
    MemR3 风格的迭代检索器
    
    实现 Retrieve → Reflect → Refine 闭环
    
    特性：
    - 支持有/无 LLM 两种模式
    - 无 LLM 时使用启发式规则
    - 有 LLM 时使用 LLM 进行智能反思
    - 成本控制：限制最大迭代次数
    """
    
    def __init__(
        self,
        graphiti_adapter,
        llm_client=None,
        max_iterations: int = 3,
        min_evidence_count: int = 2,
        enable_llm_reflect: bool = True,
        enable_relevance_filter: bool = True,
        relevance_filter_min_batch: int = 3,
    ):
        """
        初始化迭代检索器
        
        Args:
            graphiti_adapter: GraphitiSyncAdapter 或 GraphitiAdapter 实例
            llm_client: LLM 客户端（可选，用于智能反思和筛选）
            max_iterations: 最大迭代次数
            min_evidence_count: 最少证据数量（少于此数时强制继续检索）
            enable_llm_reflect: 是否启用 LLM 反思（需要 llm_client）
            enable_relevance_filter: 是否启用相关性筛选（借鉴 LingYi）
            relevance_filter_min_batch: 筛选器最小批量（少于此数不筛选）
        """
        self.graphiti = graphiti_adapter
        self.llm = llm_client
        self.max_iterations = max_iterations
        self.min_evidence_count = min_evidence_count
        self.enable_llm_reflect = enable_llm_reflect and llm_client is not None
        self.enable_relevance_filter = enable_relevance_filter and llm_client is not None
        
        # 创建相关性筛选器
        self._relevance_filter = None
        if self.enable_relevance_filter:
            try:
                from memory_agent.relevance_filter import CombinedRelevanceFilter
                self._relevance_filter = CombinedRelevanceFilter(
                    llm_client=llm_client,
                    llm_min_batch=relevance_filter_min_batch,
                )
                logger.info("[IterativeRetriever] 相关性筛选器已启用")
            except ImportError:
                logger.warning("[IterativeRetriever] 相关性筛选器导入失败，已禁用")
                self.enable_relevance_filter = False
    
    def retrieve(
        self,
        query: str,
        context: str = "",
        num_results_per_iteration: int = 10
    ) -> IterativeRetrievalResult:
        """
        执行迭代检索（同步版本）
        
        流程: Retrieve → Filter → Reflect → Refine → Loop
        
        Args:
            query: 用户查询
            context: 额外上下文（如对话历史）
            num_results_per_iteration: 每次迭代检索的结果数
        
        Returns:
            IterativeRetrievalResult
        """
        state = EvidenceGapState(query=query)
        action = RetrievalAction.RETRIEVE
        filter_stats = {"total_before": 0, "total_after": 0, "iterations": []}
        
        while state.iteration < self.max_iterations:
            state.iteration += 1
            logger.info(f"[IterativeRetriever] 迭代 {state.iteration}: query='{query}'")
            
            try:
                # 1. Retrieve - 执行检索
                current_query = state.refined_queries[-1] if state.refined_queries else query
                results = self._retrieve_step(current_query, num_results_per_iteration)
                
                before_count = len(results)
                filter_stats["total_before"] += before_count
                
                # 2. Filter - 相关性筛选（新增步骤）
                if self._relevance_filter and results:
                    results = self._filter_step(query, results, context)
                    after_count = len(results)
                    filter_stats["total_after"] += after_count
                    filter_stats["iterations"].append({
                        "iteration": state.iteration,
                        "before": before_count,
                        "after": after_count,
                    })
                    logger.debug(f"[IterativeRetriever] 筛选: {before_count} → {after_count}")
                else:
                    filter_stats["total_after"] += before_count
                
                state.add_evidence(results)
                
                logger.debug(f"[IterativeRetriever] 检索到 {len(results)} 条，累计 {len(state.evidence)} 条")
                
                # 3. Reflect - 评估证据是否充分
                action, gaps = self._reflect_step(state, context)
                
                if action == RetrievalAction.ANSWER:
                    logger.info(f"[IterativeRetriever] 证据充分，{state.iteration} 轮后完成")
                    break
                
                if action == RetrievalAction.ABORT:
                    logger.warning("[IterativeRetriever] 检索中止 - 无法获取更多信息")
                    break
                
                # 3. Refine - 根据 Gap 生成新查询
                if gaps:
                    state.gaps.extend(gaps)
                    refined = self._refine_step(query, gaps, state.evidence)
                    
                    if refined and refined not in state.refined_queries:
                        state.refined_queries.append(refined)
                        logger.info(f"[IterativeRetriever] 优化查询: '{refined}'")
                    else:
                        # 无法生成新查询，停止
                        logger.info("[IterativeRetriever] 无法生成新查询，停止迭代")
                        break
                        
            except Exception as e:
                logger.error(f"[IterativeRetriever] 迭代 {state.iteration} 出错: {e}")
                return IterativeRetrievalResult(
                    evidence=state.evidence,
                    evidence_summary=state.get_evidence_summary(),
                    iterations=state.iteration,
                    gaps=state.gaps,
                    refined_queries=state.refined_queries,
                    final_action="error",
                    success=False,
                    error=str(e)
                )
        
        return IterativeRetrievalResult(
            evidence=state.evidence,
            evidence_summary=state.get_evidence_summary(),
            iterations=state.iteration,
            gaps=state.gaps,
            refined_queries=state.refined_queries,
            final_action=action.value if action else "complete",
            success=True,
            filter_stats=filter_stats if self.enable_relevance_filter else None,
        )
    
    async def retrieve_async(
        self,
        query: str,
        context: str = "",
        num_results_per_iteration: int = 10
    ) -> IterativeRetrievalResult:
        """
        执行迭代检索（异步版本）
        
        流程: Retrieve → Filter → Reflect → Refine → Loop
        """
        state = EvidenceGapState(query=query)
        action = RetrievalAction.RETRIEVE
        filter_stats = {"total_before": 0, "total_after": 0, "iterations": []}
        
        while state.iteration < self.max_iterations:
            state.iteration += 1
            logger.info(f"[IterativeRetriever] 迭代 {state.iteration}: query='{query}'")
            
            try:
                # 1. Retrieve
                current_query = state.refined_queries[-1] if state.refined_queries else query
                results = await self._retrieve_step_async(current_query, num_results_per_iteration)
                
                before_count = len(results)
                filter_stats["total_before"] += before_count
                
                # 2. Filter - 相关性筛选（新增步骤）
                if self._relevance_filter and results:
                    results = await self._filter_step_async(query, results, context)
                    after_count = len(results)
                    filter_stats["total_after"] += after_count
                    filter_stats["iterations"].append({
                        "iteration": state.iteration,
                        "before": before_count,
                        "after": after_count,
                    })
                else:
                    filter_stats["total_after"] += before_count
                
                state.add_evidence(results)
                
                # 3. Reflect
                action, gaps = await self._reflect_step_async(state, context)
                
                if action in (RetrievalAction.ANSWER, RetrievalAction.ABORT):
                    break
                
                # 3. Refine
                if gaps:
                    state.gaps.extend(gaps)
                    refined = await self._refine_step_async(query, gaps, state.evidence)
                    
                    if refined and refined not in state.refined_queries:
                        state.refined_queries.append(refined)
                    else:
                        break
                        
            except Exception as e:
                logger.error(f"[IterativeRetriever] 异步迭代出错: {e}")
                return IterativeRetrievalResult(
                    evidence=state.evidence,
                    evidence_summary=state.get_evidence_summary(),
                    iterations=state.iteration,
                    gaps=state.gaps,
                    refined_queries=state.refined_queries,
                    final_action="error",
                    success=False,
                    error=str(e)
                )
        
        return IterativeRetrievalResult(
            evidence=state.evidence,
            evidence_summary=state.get_evidence_summary(),
            iterations=state.iteration,
            gaps=state.gaps,
            refined_queries=state.refined_queries,
            final_action=action.value if action else "complete",
            success=True,
            filter_stats=filter_stats if self.enable_relevance_filter else None,
        )
    
    # ==================== Filter 步骤（新增） ====================
    
    def _filter_step(
        self,
        query: str,
        results: List[Dict],
        context: str = "",
    ) -> List[Dict]:
        """
        筛选步骤：使用相关性筛选器过滤无关结果
        
        借鉴 LingYi 的 _filter_related_nodes 设计
        """
        if not self._relevance_filter:
            return results
        
        try:
            return self._relevance_filter.filter(query, results, context)
        except Exception as e:
            logger.error(f"[IterativeRetriever] 筛选失败: {e}")
            return results
    
    async def _filter_step_async(
        self,
        query: str,
        results: List[Dict],
        context: str = "",
    ) -> List[Dict]:
        """筛选步骤（异步版本）"""
        if not self._relevance_filter:
            return results
        
        try:
            return await self._relevance_filter.filter_async(query, results, context)
        except Exception as e:
            logger.error(f"[IterativeRetriever] 异步筛选失败: {e}")
            return results
    
    # ==================== Retrieve 步骤 ====================
    
    def _retrieve_step(
        self,
        query: str,
        num_results: int = 10,
        use_bfs: bool = False,
        origin_node_uuids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        检索步骤（同步）
        
        调用 Graphiti 进行混合检索，支持 BFS 图遍历
        
        Args:
            query: 查询文本
            num_results: 返回结果数
            use_bfs: 是否使用 BFS 图遍历（多跳查询增强）
            origin_node_uuids: BFS 起始节点 UUIDs
        """
        try:
            # 使用 Graphiti 适配器的同步搜索
            results = self.graphiti.search(query, num_results=num_results)
            
            # 标准化结果格式
            standardized = []
            for r in results:
                if isinstance(r, dict):
                    standardized.append(r)
                else:
                    # 如果是对象，提取属性
                    standardized.append({
                        "content": getattr(r, "content", "") or getattr(r, "fact", str(r)),
                        "source": getattr(r, "source", "graphiti"),
                        "score": getattr(r, "score", 1.0),
                        "valid_at": getattr(r, "valid_at", None),
                        "uuid": getattr(r, "uuid", None),
                        "source_node_uuid": getattr(r, "source_node_uuid", None),
                        "target_node_uuid": getattr(r, "target_node_uuid", None),
                    })
            
            return standardized
            
        except Exception as e:
            logger.error(f"[IterativeRetriever] 检索失败: {e}")
            return []
    
    async def _retrieve_step_async(
        self,
        query: str,
        num_results: int = 10,
        use_bfs: bool = False,
        origin_node_uuids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        检索步骤（异步），支持 BFS 图遍历
        
        对于复杂的多跳查询，可以使用 BFS 从已发现的节点开始扩展搜索
        """
        try:
            # 如果需要 BFS 并且有 Graphiti 的高级搜索
            if use_bfs and origin_node_uuids and hasattr(self.graphiti, 'search_advanced'):
                # 使用高级搜索配置 BFS
                results = await self._retrieve_with_bfs_async(
                    query, num_results, origin_node_uuids
                )
            else:
                results = await self.graphiti.search(query, num_results=num_results)
            
            standardized = []
            for r in results:
                if isinstance(r, dict):
                    standardized.append(r)
                else:
                    standardized.append({
                        "content": getattr(r, "content", "") or getattr(r, "fact", str(r)),
                        "source": getattr(r, "source", "graphiti"),
                        "score": getattr(r, "score", 1.0),
                        "valid_at": getattr(r, "valid_at", None),
                        "uuid": getattr(r, "uuid", None),
                        "source_node_uuid": getattr(r, "source_node_uuid", None),
                        "target_node_uuid": getattr(r, "target_node_uuid", None),
                    })
            
            return standardized
            
        except Exception as e:
            logger.error(f"[IterativeRetriever] 异步检索失败: {e}")
            return []
    
    async def _retrieve_with_bfs_async(
        self,
        query: str,
        num_results: int,
        origin_node_uuids: List[str],
    ) -> List[Dict]:
        """
        使用 BFS 图遍历的高级检索
        
        从已发现的节点开始，扩展搜索相邻节点和边
        """
        try:
            # 调用 Graphiti 的高级搜索
            advanced_results = await self.graphiti.search_advanced(
                query=query,
                num_results=num_results,
            )
            
            # 合并 edges 和 nodes 结果
            results = []
            
            # 处理 edges
            for i, edge in enumerate(advanced_results.get("edges", [])):
                score = advanced_results.get("edge_scores", [])[i] if i < len(advanced_results.get("edge_scores", [])) else 1.0
                results.append({
                    "content": edge.get("fact", ""),
                    "source": "edge",
                    "score": score,
                    "valid_at": edge.get("valid_at"),
                    "uuid": edge.get("uuid"),
                    "source_node_uuid": edge.get("source_node_uuid"),
                    "target_node_uuid": edge.get("target_node_uuid"),
                })
            
            # 处理 nodes
            for i, node in enumerate(advanced_results.get("nodes", [])):
                score = advanced_results.get("node_scores", [])[i] if i < len(advanced_results.get("node_scores", [])) else 1.0
                results.append({
                    "content": node.get("summary", node.get("name", "")),
                    "source": "node",
                    "score": score,
                    "uuid": node.get("uuid"),
                    "name": node.get("name"),
                })
            
            # 按评分排序
            results.sort(key=lambda x: x.get("score", 0), reverse=True)
            
            return results[:num_results]
            
        except Exception as e:
            logger.warning(f"[IterativeRetriever] BFS 检索失败，降级到普通检索: {e}")
            return await self.graphiti.search(query, num_results=num_results)
    
    def _extract_node_uuids(self, evidence: List[Dict]) -> List[str]:
        """从证据中提取节点 UUID，用于 BFS 扩展"""
        node_uuids = set()
        for e in evidence:
            source_uuid = e.get("source_node_uuid")
            target_uuid = e.get("target_node_uuid")
            uuid = e.get("uuid")
            
            if source_uuid:
                node_uuids.add(source_uuid)
            if target_uuid:
                node_uuids.add(target_uuid)
            if uuid and e.get("source") == "node":
                node_uuids.add(uuid)
        
        return list(node_uuids)
    
    # ==================== Reflect 步骤 ====================
    
    def _reflect_step(
        self,
        state: EvidenceGapState,
        context: str
    ) -> Tuple[RetrievalAction, List[str]]:
        """
        反思步骤：评估证据是否充分，识别信息缺口
        
        如果启用 LLM 反思且有 LLM 客户端，使用 LLM 判断
        否则使用启发式规则
        """
        # 基本检查：证据数量
        if len(state.evidence) < self.min_evidence_count:
            return RetrievalAction.RETRIEVE, ["需要更多相关信息"]
        
        # 检查是否已经迭代太多次
        if state.iteration >= self.max_iterations:
            return RetrievalAction.ANSWER, []
        
        # 如果启用 LLM 反思
        if self.enable_llm_reflect and self.llm:
            return self._reflect_with_llm(state, context)
        
        # 使用启发式规则
        return self._reflect_heuristic(state)
    
    async def _reflect_step_async(
        self,
        state: EvidenceGapState,
        context: str
    ) -> Tuple[RetrievalAction, List[str]]:
        """反思步骤（异步版本）"""
        if len(state.evidence) < self.min_evidence_count:
            return RetrievalAction.RETRIEVE, ["需要更多相关信息"]
        
        if state.iteration >= self.max_iterations:
            return RetrievalAction.ANSWER, []
        
        if self.enable_llm_reflect and self.llm:
            return await self._reflect_with_llm_async(state, context)
        
        return self._reflect_heuristic(state)
    
    def _reflect_heuristic(self, state: EvidenceGapState) -> Tuple[RetrievalAction, List[str]]:
        """
        启发式反思（无 LLM 时使用）
        
        通过模式匹配识别常见的信息缺口
        """
        query = state.query.lower()
        evidence_text = " ".join([
            e.get("content", "") or e.get("fact", "") 
            for e in state.evidence
        ]).lower()
        
        gaps = []
        
        # 模式1：时间相关问题
        time_patterns = ["多久", "多长时间", "什么时候开始", "持续", "几天", "几个月", "几年"]
        if any(p in query for p in time_patterns):
            # 检查证据中是否有时间信息
            time_found = bool(re.search(r"\d{4}[-年/]\d{1,2}", evidence_text))
            if not time_found:
                gaps.append("缺少时间信息")
        
        # 模式2：比较问题
        compare_patterns = ["比较", "对比", "区别", "不同", "相同", "和.*哪个"]
        if any(re.search(p, query) for p in compare_patterns):
            # 比较问题需要多个实体的信息
            if len(state.evidence) < 4:
                gaps.append("需要更多对比信息")
        
        # 模式3：因果问题
        causal_patterns = ["为什么", "原因", "怎么会", "导致", "因为"]
        if any(p in query for p in causal_patterns):
            # 检查是否有解释性内容
            explanation_words = ["因为", "由于", "所以", "导致", "原因是", "因此"]
            if not any(w in evidence_text for w in explanation_words):
                gaps.append("缺少原因解释")
        
        # 模式4：列举问题
        list_patterns = ["有哪些", "都有什么", "列举", "所有的"]
        if any(p in query for p in list_patterns):
            # 列举问题可能需要更多结果
            if len(state.evidence) < 5:
                gaps.append("可能还有更多相关项")
        
        # 模式5：数量问题
        count_patterns = ["多少", "几个", "数量"]
        if any(p in query for p in count_patterns):
            # 检查是否有数字
            if not re.search(r"\d+", evidence_text):
                gaps.append("缺少数量信息")
        
        # 决定下一步行动
        if gaps and state.iteration < self.max_iterations:
            return RetrievalAction.RETRIEVE, gaps
        
        return RetrievalAction.ANSWER, []
    
    def _reflect_with_llm(
        self,
        state: EvidenceGapState,
        context: str
    ) -> Tuple[RetrievalAction, List[str]]:
        """
        使用 LLM 进行反思（同步）
        
        让 LLM 判断证据是否充分，识别信息缺口
        """
        prompt = self._build_reflect_prompt(state, context)
        
        try:
            response = self.llm.generate(prompt)
            return self._parse_reflect_response(response)
        except Exception as e:
            logger.error(f"[IterativeRetriever] LLM 反思失败: {e}")
            return self._reflect_heuristic(state)
    
    async def _reflect_with_llm_async(
        self,
        state: EvidenceGapState,
        context: str
    ) -> Tuple[RetrievalAction, List[str]]:
        """使用 LLM 进行反思（异步）"""
        prompt = self._build_reflect_prompt(state, context)
        
        try:
            response = await self.llm.generate_async(prompt)
            return self._parse_reflect_response(response)
        except Exception as e:
            logger.error(f"[IterativeRetriever] LLM 异步反思失败: {e}")
            return self._reflect_heuristic(state)
    
    def _build_reflect_prompt(self, state: EvidenceGapState, context: str) -> str:
        """构建反思提示词"""
        return f"""你是一个检索评估助手。请判断当前收集的证据是否足以回答用户问题。

## 用户问题
{state.query}

## 已收集的证据（{len(state.evidence)} 条）
{state.get_evidence_summary()}

## 分析要求
1. 判断这些证据是否足以**完整**回答问题
2. 如果不足，列出还缺少什么信息

## 回答格式（严格遵守）
SUFFICIENT: yes/no
GAPS: [如果不足，列出缺少的信息，用分号分隔；如果充分则留空]

示例1:
SUFFICIENT: yes
GAPS:

示例2:
SUFFICIENT: no
GAPS: 缺少具体时间信息; 缺少项目当前状态"""
    
    def _parse_reflect_response(self, response: str) -> Tuple[RetrievalAction, List[str]]:
        """解析 LLM 反思响应"""
        response_lower = response.lower()
        
        # 检查是否充分
        if "sufficient: yes" in response_lower or "sufficient:yes" in response_lower:
            return RetrievalAction.ANSWER, []
        
        # 提取 gaps
        gaps = []
        if "gaps:" in response_lower:
            gaps_part = response.split("GAPS:")[-1].strip()
            # 处理可能的格式变体
            gaps_part = gaps_part.split("GAPS:")[-1] if "GAPS:" in gaps_part else gaps_part
            
            if gaps_part and gaps_part.lower() not in ["", "无", "none", "n/a"]:
                gaps = [g.strip() for g in gaps_part.split(";") if g.strip()]
        
        return RetrievalAction.RETRIEVE, gaps
    
    # ==================== Refine 步骤 ====================
    
    def _refine_step(
        self,
        original_query: str,
        gaps: List[str],
        evidence: List[Dict]
    ) -> Optional[str]:
        """
        优化步骤：根据 Gap 生成新的检索查询
        
        如果有 LLM，使用 LLM 生成更好的查询
        否则使用简单拼接策略
        """
        if not gaps:
            return None
        
        if self.enable_llm_reflect and self.llm:
            return self._refine_with_llm(original_query, gaps, evidence)
        
        return self._refine_simple(original_query, gaps)
    
    async def _refine_step_async(
        self,
        original_query: str,
        gaps: List[str],
        evidence: List[Dict]
    ) -> Optional[str]:
        """优化步骤（异步）"""
        if not gaps:
            return None
        
        if self.enable_llm_reflect and self.llm:
            return await self._refine_with_llm_async(original_query, gaps, evidence)
        
        return self._refine_simple(original_query, gaps)
    
    def _refine_simple(self, original_query: str, gaps: List[str]) -> str:
        """
        简单的查询优化（无 LLM 时使用）
        
        策略：提取原查询关键词 + 第一个 gap
        """
        gap = gaps[0]
        
        # 提取原查询中可能的实体（简单策略：取前15个字符）
        # 去除疑问词
        query_clean = re.sub(r"(什么|怎么|为什么|哪些|多少|多久|是否|有没有)", "", original_query)
        entity = query_clean[:15].strip()
        
        if not entity:
            entity = original_query[:15].strip()
        
        return f"{entity} {gap}"
    
    def _refine_with_llm(
        self,
        original_query: str,
        gaps: List[str],
        evidence: List[Dict]
    ) -> Optional[str]:
        """使用 LLM 生成优化查询（同步）"""
        prompt = self._build_refine_prompt(original_query, gaps, evidence)
        
        try:
            response = self.llm.generate(prompt)
            return response.strip()
        except Exception as e:
            logger.error(f"[IterativeRetriever] LLM 优化查询失败: {e}")
            return self._refine_simple(original_query, gaps)
    
    async def _refine_with_llm_async(
        self,
        original_query: str,
        gaps: List[str],
        evidence: List[Dict]
    ) -> Optional[str]:
        """使用 LLM 生成优化查询（异步）"""
        prompt = self._build_refine_prompt(original_query, gaps, evidence)
        
        try:
            response = await self.llm.generate_async(prompt)
            return response.strip()
        except Exception as e:
            logger.error(f"[IterativeRetriever] LLM 异步优化查询失败: {e}")
            return self._refine_simple(original_query, gaps)
    
    def _build_refine_prompt(
        self,
        original_query: str,
        gaps: List[str],
        evidence: List[Dict]
    ) -> str:
        """构建查询优化提示词"""
        return f"""你是一个查询优化助手。用户的原始问题无法完全回答，因为缺少一些信息。

## 原始问题
{original_query}

## 缺少的信息
{', '.join(gaps)}

## 任务
请生成一个新的检索查询，帮助找到缺少的信息。

## 要求
- 只输出查询文本，不要其他内容
- 查询应该简洁明确
- 包含关键实体和缺失信息类型

## 输出
"""


# ==================== 便捷函数 ====================

def create_iterative_retriever(
    graphiti_adapter,
    config: Optional[Dict[str, Any]] = None
) -> IterativeRetriever:
    """
    创建迭代检索器的工厂函数
    
    Args:
        graphiti_adapter: Graphiti 适配器
        config: 配置字典，可包含:
            - max_iterations: 最大迭代次数
            - min_evidence_count: 最少证据数量
            - enable_llm_reflect: 是否启用 LLM 反思
            - enable_relevance_filter: 是否启用相关性筛选（借鉴 LingYi）
            - relevance_filter_min_batch: 筛选器最小批量
    
    Returns:
        IterativeRetriever 实例
    """
    config = config or {}
    
    return IterativeRetriever(
        graphiti_adapter=graphiti_adapter,
        llm_client=config.get("llm_client"),
        max_iterations=config.get("max_iterations", 3),
        min_evidence_count=config.get("min_evidence_count", 2),
        enable_llm_reflect=config.get("enable_llm_reflect", True),
        enable_relevance_filter=config.get("enable_relevance_filter", True),
        relevance_filter_min_batch=config.get("relevance_filter_min_batch", 3),
    )
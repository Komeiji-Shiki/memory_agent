"""
检索结果相关性筛选器

借鉴 LingYi 的 _filter_related_nodes 设计，在检索后使用 LLM 判断结果与查询的相关性。

核心功能：
1. 将候选结果格式化
2. 让 LLM 判断每个结果是否与查询相关
3. 返回过滤后的结果

成本控制：
- 设置 min_batch_size 阈值（少于阈值不筛选）
- 使用小模型进行筛选
- 支持批量处理，减少 API 调用

使用方式：
    filter = RelevanceFilter(llm_client)
    
    # 同步筛选
    filtered = filter.filter(query, results, summary)
    
    # 异步筛选
    filtered = await filter.filter_async(query, results, summary)
"""

from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Protocol, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class RelevanceLevel(Enum):
    """相关性等级"""
    HIGHLY_RELEVANT = "highly_relevant"   # 高度相关
    RELEVANT = "relevant"                  # 相关
    MARGINALLY_RELEVANT = "marginally"     # 边缘相关
    NOT_RELEVANT = "not_relevant"          # 不相关


@dataclass
class FilteredResult:
    """筛选后的结果"""
    original: Dict[str, Any]         # 原始结果
    is_relevant: bool                # 是否相关
    relevance_level: RelevanceLevel  # 相关性等级
    relevance_reason: str = ""       # 相关性原因
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "original": self.original,
            "is_relevant": self.is_relevant,
            "relevance_level": self.relevance_level.value,
            "relevance_reason": self.relevance_reason,
        }


@dataclass
class FilterStats:
    """筛选统计"""
    total_input: int = 0
    total_output: int = 0
    highly_relevant: int = 0
    relevant: int = 0
    marginally_relevant: int = 0
    not_relevant: int = 0
    filter_ratio: float = 0.0
    
    def __post_init__(self):
        if self.total_input > 0:
            self.filter_ratio = 1 - (self.total_output / self.total_input)


class LLMClientProtocol(Protocol):
    """LLM 客户端协议（用于类型提示）"""
    
    def generate(self, prompt: str) -> str:
        """同步生成"""
        ...
    
    async def generate_async(self, prompt: str) -> str:
        """异步生成"""
        ...


class RelevanceFilter:
    """
    检索结果相关性筛选器
    
    借鉴 LingYi 的 _filter_related_nodes 设计：
    1. 将候选结果格式化
    2. 让 LLM 判断每个结果是否与查询相关
    3. 返回过滤后的结果
    """
    
    # 基础筛选提示词
    FILTER_PROMPT = """你是一个记忆相关性判断助手。请判断以下每条记忆是否与用户的查询话题相关。

## 用户查询
{query}

## 话题摘要
{summary}

## 待筛选的记忆（共 {count} 条）
{memories}

## 判断标准
- "highly_relevant": 直接回答问题或与问题核心主题高度相关
- "relevant": 与问题相关，提供有用的背景或上下文
- "marginally": 边缘相关，可能有一点用
- "not_relevant": 完全不相关

## 输出格式
请输出一个 JSON 数组，每个元素是上述四个等级之一。
数组长度必须等于记忆数量 {count}。

示例输出（假设有3条记忆）：
["highly_relevant", "not_relevant", "relevant"]

## 你的判断（只输出 JSON 数组，不要其他内容）
"""

    # 简化版筛选提示词（只判断是否相关）
    SIMPLE_FILTER_PROMPT = """判断以下记忆是否与查询相关。

查询: {query}

记忆:
{memories}

输出 JSON 数组，true=相关，false=不相关。
长度必须等于 {count}。

示例: [true, false, true]

判断:"""

    def __init__(
        self,
        llm_client: Optional[LLMClientProtocol] = None,
        min_batch_size: int = 3,
        use_detailed_prompt: bool = True,
        include_marginally_relevant: bool = True,
        max_content_length: int = 200,
        max_batch_size: int = 20,
    ):
        """
        初始化筛选器
        
        Args:
            llm_client: LLM 客户端（可选，无则跳过筛选）
            min_batch_size: 最少多少条才触发筛选（减少 LLM 调用）
            use_detailed_prompt: 是否使用详细提示词（返回相关性等级）
            include_marginally_relevant: 是否包含边缘相关的结果
            max_content_length: 每条记忆的最大内容长度
            max_batch_size: 每批最大处理数量
        """
        self.llm = llm_client
        self.min_batch_size = min_batch_size
        self.use_detailed_prompt = use_detailed_prompt
        self.include_marginally_relevant = include_marginally_relevant
        self.max_content_length = max_content_length
        self.max_batch_size = max_batch_size
    
    def filter(
        self,
        query: str,
        results: List[Dict[str, Any]],
        summary: str = "",
    ) -> List[Dict[str, Any]]:
        """
        筛选相关结果（同步版本）
        
        Args:
            query: 原始查询
            results: 检索结果列表
            summary: 话题摘要（可选，帮助判断上下文）
        
        Returns:
            过滤后的结果列表
        """
        # 数量太少，跳过筛选
        if len(results) < self.min_batch_size:
            logger.debug(f"[RelevanceFilter] 结果数 {len(results)} < {self.min_batch_size}，跳过筛选")
            return results
        
        # 无 LLM，跳过筛选
        if not self.llm:
            logger.debug("[RelevanceFilter] 无 LLM，跳过筛选")
            return results
        
        try:
            # 分批处理（如果结果太多）
            if len(results) > self.max_batch_size:
                return self._filter_in_batches(query, results, summary)
            
            # 格式化记忆
            memories_text = self._format_memories(results)
            
            # 构建 prompt
            if self.use_detailed_prompt:
                prompt = self.FILTER_PROMPT.format(
                    query=query,
                    summary=summary or query,
                    count=len(results),
                    memories=memories_text
                )
            else:
                prompt = self.SIMPLE_FILTER_PROMPT.format(
                    query=query,
                    count=len(results),
                    memories=memories_text
                )
            
            # 调用 LLM
            response = self.llm.generate(prompt)
            
            # 解析结果
            if self.use_detailed_prompt:
                relevance_levels = self._parse_detailed_response(response, len(results))
                filtered = self._apply_detailed_filter(results, relevance_levels)
            else:
                relevance_flags = self._parse_simple_response(response, len(results))
                filtered = [r for r, is_relevant in zip(results, relevance_flags) if is_relevant]
            
            logger.info(
                f"[RelevanceFilter] 筛选完成: {len(results)} → {len(filtered)} "
                f"(过滤率: {(1 - len(filtered)/len(results))*100:.1f}%)"
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
            # 分批处理
            if len(results) > self.max_batch_size:
                return await self._filter_in_batches_async(query, results, summary)
            
            memories_text = self._format_memories(results)
            
            if self.use_detailed_prompt:
                prompt = self.FILTER_PROMPT.format(
                    query=query,
                    summary=summary or query,
                    count=len(results),
                    memories=memories_text
                )
            else:
                prompt = self.SIMPLE_FILTER_PROMPT.format(
                    query=query,
                    count=len(results),
                    memories=memories_text
                )
            
            response = await self.llm.generate_async(prompt)
            
            if self.use_detailed_prompt:
                relevance_levels = self._parse_detailed_response(response, len(results))
                filtered = self._apply_detailed_filter(results, relevance_levels)
            else:
                relevance_flags = self._parse_simple_response(response, len(results))
                filtered = [r for r, is_relevant in zip(results, relevance_flags) if is_relevant]
            
            logger.info(
                f"[RelevanceFilter] 异步筛选完成: {len(results)} → {len(filtered)}"
            )
            
            return filtered
            
        except Exception as e:
            logger.error(f"[RelevanceFilter] 异步筛选失败: {e}")
            return results
    
    def filter_with_details(
        self,
        query: str,
        results: List[Dict[str, Any]],
        summary: str = "",
    ) -> Tuple[List[Dict[str, Any]], List[FilteredResult], FilterStats]:
        """
        筛选并返回详细信息
        
        Returns:
            (filtered_results, all_filter_results, stats)
        """
        if len(results) < self.min_batch_size or not self.llm:
            # 跳过筛选，全部标记为相关
            filter_results = [
                FilteredResult(
                    original=r,
                    is_relevant=True,
                    relevance_level=RelevanceLevel.RELEVANT,
                    relevance_reason="未执行筛选"
                )
                for r in results
            ]
            stats = FilterStats(
                total_input=len(results),
                total_output=len(results),
                relevant=len(results),
            )
            return results, filter_results, stats
        
        try:
            memories_text = self._format_memories(results)
            prompt = self.FILTER_PROMPT.format(
                query=query,
                summary=summary or query,
                count=len(results),
                memories=memories_text
            )
            
            response = self.llm.generate(prompt)
            relevance_levels = self._parse_detailed_response(response, len(results))
            
            # 构建详细结果
            filter_results = []
            filtered = []
            stats = FilterStats(total_input=len(results))
            
            for result, level in zip(results, relevance_levels):
                is_relevant = self._should_include(level)
                
                filter_result = FilteredResult(
                    original=result,
                    is_relevant=is_relevant,
                    relevance_level=level,
                )
                filter_results.append(filter_result)
                
                # 统计
                if level == RelevanceLevel.HIGHLY_RELEVANT:
                    stats.highly_relevant += 1
                elif level == RelevanceLevel.RELEVANT:
                    stats.relevant += 1
                elif level == RelevanceLevel.MARGINALLY_RELEVANT:
                    stats.marginally_relevant += 1
                else:
                    stats.not_relevant += 1
                
                if is_relevant:
                    filtered.append(result)
            
            stats.total_output = len(filtered)
            stats.filter_ratio = 1 - (len(filtered) / len(results)) if results else 0
            
            return filtered, filter_results, stats
            
        except Exception as e:
            logger.error(f"[RelevanceFilter] 详细筛选失败: {e}")
            # 失败时全部保留
            filter_results = [
                FilteredResult(
                    original=r,
                    is_relevant=True,
                    relevance_level=RelevanceLevel.RELEVANT,
                    relevance_reason=f"筛选失败: {e}"
                )
                for r in results
            ]
            stats = FilterStats(
                total_input=len(results),
                total_output=len(results),
                relevant=len(results),
            )
            return results, filter_results, stats
    
    def _format_memories(self, results: List[Dict[str, Any]]) -> str:
        """格式化记忆为文本"""
        lines = []
        for i, r in enumerate(results, 1):
            content = r.get("content", "") or r.get("fact", "") or str(r)
            
            # 截断过长内容
            if len(content) > self.max_content_length:
                content = content[:self.max_content_length] + "..."
            
            # 清理换行符
            content = content.replace("\n", " ").strip()
            
            source = r.get("source", "unknown")
            score = r.get("score", 0)
            valid_at = r.get("valid_at")
            
            # 格式化时间
            time_str = ""
            if valid_at:
                if hasattr(valid_at, 'strftime'):
                    time_str = valid_at.strftime("%Y-%m-%d")
                else:
                    time_str = str(valid_at)[:10]
            
            line = f"{i}. [{source}]"
            if time_str:
                line += f"({time_str})"
            if score:
                line += f"[{score:.2f}]"
            line += f" {content}"
            
            lines.append(line)
        
        return "\n".join(lines)
    
    def _parse_simple_response(self, response: str, expected_count: int) -> List[bool]:
        """解析简单响应（布尔数组）"""
        # 尝试提取 JSON 数组
        json_match = re.search(r'\[[\s\S]*?\]', response)
        if json_match:
            try:
                flags = json.loads(json_match.group())
                if len(flags) == expected_count:
                    return [bool(f) for f in flags]
            except json.JSONDecodeError:
                pass
        
        # 尝试逐行解析 true/false
        flags = []
        for line in response.split('\n'):
            line = line.strip().lower()
            if 'true' in line:
                flags.append(True)
            elif 'false' in line:
                flags.append(False)
        
        if len(flags) == expected_count:
            return flags
        
        # 解析失败，默认全部保留
        logger.warning(f"[RelevanceFilter] 无法解析简单响应，保留全部结果")
        return [True] * expected_count
    
    def _parse_detailed_response(self, response: str, expected_count: int) -> List[RelevanceLevel]:
        """解析详细响应（相关性等级数组）"""
        # 尝试提取 JSON 数组
        json_match = re.search(r'\[[\s\S]*?\]', response)
        if json_match:
            try:
                levels_str = json.loads(json_match.group())
                if len(levels_str) == expected_count:
                    return [self._str_to_level(s) for s in levels_str]
            except json.JSONDecodeError:
                pass
        
        # 尝试按关键词解析
        levels = []
        for line in response.split('\n'):
            line = line.strip().lower()
            if 'highly' in line or 'high' in line:
                levels.append(RelevanceLevel.HIGHLY_RELEVANT)
            elif 'not_relevant' in line or 'not relevant' in line or 'irrelevant' in line:
                levels.append(RelevanceLevel.NOT_RELEVANT)
            elif 'marginally' in line or 'marginal' in line:
                levels.append(RelevanceLevel.MARGINALLY_RELEVANT)
            elif 'relevant' in line:
                levels.append(RelevanceLevel.RELEVANT)
        
        if len(levels) == expected_count:
            return levels
        
        # 解析失败，默认全部相关
        logger.warning(f"[RelevanceFilter] 无法解析详细响应，标记全部为相关")
        return [RelevanceLevel.RELEVANT] * expected_count
    
    def _str_to_level(self, s: str) -> RelevanceLevel:
        """字符串转相关性等级"""
        s = s.lower().strip()
        if 'highly' in s or s == 'high':
            return RelevanceLevel.HIGHLY_RELEVANT
        elif 'not' in s or 'irrelevant' in s:
            return RelevanceLevel.NOT_RELEVANT
        elif 'margin' in s:
            return RelevanceLevel.MARGINALLY_RELEVANT
        else:
            return RelevanceLevel.RELEVANT
    
    def _should_include(self, level: RelevanceLevel) -> bool:
        """判断是否应该包含该相关性等级"""
        if level == RelevanceLevel.NOT_RELEVANT:
            return False
        if level == RelevanceLevel.MARGINALLY_RELEVANT:
            return self.include_marginally_relevant
        return True
    
    def _apply_detailed_filter(
        self,
        results: List[Dict[str, Any]],
        levels: List[RelevanceLevel]
    ) -> List[Dict[str, Any]]:
        """应用详细筛选"""
        return [
            r for r, level in zip(results, levels)
            if self._should_include(level)
        ]
    
    def _filter_in_batches(
        self,
        query: str,
        results: List[Dict[str, Any]],
        summary: str,
    ) -> List[Dict[str, Any]]:
        """分批筛选（同步）"""
        filtered = []
        for i in range(0, len(results), self.max_batch_size):
            batch = results[i:i + self.max_batch_size]
            batch_filtered = self.filter(query, batch, summary)
            filtered.extend(batch_filtered)
        return filtered
    
    async def _filter_in_batches_async(
        self,
        query: str,
        results: List[Dict[str, Any]],
        summary: str,
    ) -> List[Dict[str, Any]]:
        """分批筛选（异步）"""
        import asyncio
        
        batches = [
            results[i:i + self.max_batch_size]
            for i in range(0, len(results), self.max_batch_size)
        ]
        
        # 并发处理所有批次
        tasks = [
            self._filter_batch_async(query, batch, summary)
            for batch in batches
        ]
        
        results_lists = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 合并结果
        filtered = []
        for result in results_lists:
            if isinstance(result, Exception):
                logger.error(f"[RelevanceFilter] 批次筛选失败: {result}")
            else:
                filtered.extend(result)
        
        return filtered
    
    async def _filter_batch_async(
        self,
        query: str,
        batch: List[Dict[str, Any]],
        summary: str,
    ) -> List[Dict[str, Any]]:
        """筛选单个批次（异步）"""
        if not batch:
            return []
        
        memories_text = self._format_memories(batch)
        
        if self.use_detailed_prompt:
            prompt = self.FILTER_PROMPT.format(
                query=query,
                summary=summary or query,
                count=len(batch),
                memories=memories_text
            )
        else:
            prompt = self.SIMPLE_FILTER_PROMPT.format(
                query=query,
                count=len(batch),
                memories=memories_text
            )
        
        response = await self.llm.generate_async(prompt)
        
        if self.use_detailed_prompt:
            relevance_levels = self._parse_detailed_response(response, len(batch))
            return self._apply_detailed_filter(batch, relevance_levels)
        else:
            relevance_flags = self._parse_simple_response(response, len(batch))
            return [r for r, is_relevant in zip(batch, relevance_flags) if is_relevant]


# ============================================================
# 快捷启发式筛选器（无需 LLM）
# ============================================================

class HeuristicRelevanceFilter:
    """
    启发式相关性筛选器
    
    不依赖 LLM，使用关键词匹配和简单规则进行筛选。
    速度快但准确性较低，适合作为预筛选或降级方案。
    """
    
    def __init__(
        self,
        min_keyword_overlap: float = 0.3,
        min_score_threshold: float = 0.5,
    ):
        """
        初始化启发式筛选器
        
        Args:
            min_keyword_overlap: 最小关键词重叠比例
            min_score_threshold: 最小分数阈值
        """
        self.min_keyword_overlap = min_keyword_overlap
        self.min_score_threshold = min_score_threshold
    
    def filter(
        self,
        query: str,
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """启发式筛选"""
        query_keywords = self._extract_keywords(query)
        
        if not query_keywords:
            # 无法提取关键词，只按分数过滤
            return [
                r for r in results
                if r.get("score", 1.0) >= self.min_score_threshold
            ]
        
        filtered = []
        for result in results:
            content = result.get("content", "") or result.get("fact", "")
            content_keywords = self._extract_keywords(content)
            
            # 计算关键词重叠
            if content_keywords:
                overlap = len(query_keywords & content_keywords) / len(query_keywords)
            else:
                overlap = 0
            
            # 分数检查
            score = result.get("score", 1.0)
            
            # 综合判断
            if overlap >= self.min_keyword_overlap or score >= self.min_score_threshold:
                filtered.append(result)
        
        return filtered
    
    def _extract_keywords(self, text: str) -> set:
        """提取关键词（简单实现）"""
        # 移除标点和空白
        text = re.sub(r'[^\w\u4e00-\u9fff]', ' ', text)
        
        # 分词（简单按空格和中文字符）
        words = set()
        
        # 英文词
        words.update(word.lower() for word in text.split() if len(word) > 1)
        
        # 中文词（简单的 N-gram）
        chinese_chars = re.findall(r'[\u4e00-\u9fff]+', text)
        for chars in chinese_chars:
            # 2-gram 和 3-gram
            for n in [2, 3]:
                for i in range(len(chars) - n + 1):
                    words.add(chars[i:i+n])
        
        return words


# ============================================================
# 组合筛选器
# ============================================================

class CombinedRelevanceFilter:
    """
    组合筛选器
    
    先用启发式快速预筛选，再用 LLM 精确筛选。
    平衡速度和准确性。
    """
    
    def __init__(
        self,
        llm_client: Optional[LLMClientProtocol] = None,
        heuristic_threshold: float = 0.3,
        llm_min_batch: int = 5,
    ):
        self.heuristic_filter = HeuristicRelevanceFilter(
            min_keyword_overlap=heuristic_threshold
        )
        self.llm_filter = RelevanceFilter(
            llm_client=llm_client,
            min_batch_size=llm_min_batch,
        ) if llm_client else None
    
    def filter(
        self,
        query: str,
        results: List[Dict[str, Any]],
        summary: str = "",
    ) -> List[Dict[str, Any]]:
        """组合筛选"""
        # 第一阶段：启发式预筛选
        pre_filtered = self.heuristic_filter.filter(query, results)
        
        logger.debug(
            f"[CombinedFilter] 启发式预筛选: {len(results)} → {len(pre_filtered)}"
        )
        
        # 第二阶段：LLM 精确筛选
        if self.llm_filter and len(pre_filtered) >= self.llm_filter.min_batch_size:
            return self.llm_filter.filter(query, pre_filtered, summary)
        
        return pre_filtered
    
    async def filter_async(
        self,
        query: str,
        results: List[Dict[str, Any]],
        summary: str = "",
    ) -> List[Dict[str, Any]]:
        """异步组合筛选"""
        # 启发式预筛选（同步，因为很快）
        pre_filtered = self.heuristic_filter.filter(query, results)
        
        # LLM 精确筛选
        if self.llm_filter and len(pre_filtered) >= self.llm_filter.min_batch_size:
            return await self.llm_filter.filter_async(query, pre_filtered, summary)
        
        return pre_filtered


# ============================================================
# 便捷函数
# ============================================================

def create_relevance_filter(
    llm_client: Optional[LLMClientProtocol] = None,
    use_combined: bool = True,
    **kwargs
) -> RelevanceFilter | CombinedRelevanceFilter:
    """
    创建相关性筛选器
    
    Args:
        llm_client: LLM 客户端
        use_combined: 是否使用组合筛选器
        **kwargs: 其他参数
    
    Returns:
        筛选器实例
    """
    if use_combined:
        return CombinedRelevanceFilter(llm_client=llm_client, **kwargs)
    else:
        return RelevanceFilter(llm_client=llm_client, **kwargs)


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    # 模拟 LLM 客户端
    class MockLLMClient:
        def generate(self, prompt: str) -> str:
            # 模拟返回
            if "共 5 条" in prompt:
                return '["highly_relevant", "relevant", "not_relevant", "marginally", "relevant"]'
            return '["relevant"]'
        
        async def generate_async(self, prompt: str) -> str:
            return self.generate(prompt)
    
    # 测试数据
    test_results = [
        {"content": "主人喜欢喝咖啡，经常去星巴克", "source": "diary", "score": 0.9},
        {"content": "主人今天和小明一起吃了火锅", "source": "conv", "score": 0.8},
        {"content": "天气很好，阳光明媚", "source": "diary", "score": 0.7},
        {"content": "主人最近在学习 Python", "source": "conv", "score": 0.6},
        {"content": "主人喜欢喝拿铁", "source": "diary", "score": 0.85},
    ]
    
    print("=" * 60)
    print("相关性筛选器测试")
    print("=" * 60)
    
    # 1. 启发式筛选
    print("\n1. 启发式筛选 (查询: 咖啡)")
    heuristic = HeuristicRelevanceFilter()
    filtered = heuristic.filter("咖啡", test_results)
    print(f"   结果: {len(test_results)} → {len(filtered)}")
    for r in filtered:
        print(f"   - {r['content'][:30]}...")
    
    # 2. LLM 筛选
    print("\n2. LLM 筛选 (查询: 主人喜欢喝什么饮料)")
    llm_filter = RelevanceFilter(llm_client=MockLLMClient(), min_batch_size=3)
    filtered = llm_filter.filter("主人喜欢喝什么饮料", test_results)
    print(f"   结果: {len(test_results)} → {len(filtered)}")
    
    # 3. 详细筛选
    print("\n3. 详细筛选")
    filtered, details, stats = llm_filter.filter_with_details(
        "主人喜欢喝什么饮料", test_results
    )
    print(f"   统计:")
    print(f"   - 输入: {stats.total_input}")
    print(f"   - 输出: {stats.total_output}")
    print(f"   - 高度相关: {stats.highly_relevant}")
    print(f"   - 相关: {stats.relevant}")
    print(f"   - 边缘相关: {stats.marginally_relevant}")
    print(f"   - 不相关: {stats.not_relevant}")
    print(f"   - 过滤率: {stats.filter_ratio*100:.1f}%")
    
    # 4. 组合筛选
    print("\n4. 组合筛选")
    combined = CombinedRelevanceFilter(llm_client=MockLLMClient())
    filtered = combined.filter("主人喜欢喝什么饮料", test_results)
    print(f"   结果: {len(test_results)} → {len(filtered)}")
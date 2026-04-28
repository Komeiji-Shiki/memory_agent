"""
Memory Agent - 记忆检索Agent

负责多轮工具调用，从LifeBook中检索相关记忆。
支持思维链推理，可以进行迭代搜索和交叉验证。

设计：
- 小模型Agent：用于预检索，结果传给大模型
- 大模型也可以直接调用这些工具（不满意时自己检索）
- 可选：集成 MemR3 风格迭代检索器进行智能预检索
"""

import json
import time
import uuid
import logging
from typing import Dict, List, Any, Optional, Generator, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field
import httpx
from openai import OpenAI

from .tools import MemoryTools, get_openai_tools
from memory_store.debug_logger import get_debug_logger

# 类型检查时导入，避免循环依赖
if TYPE_CHECKING:
    from .retrieval_router import RetrievalRouter

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Agent配置"""
    model: str = "deepseek-reasoner"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    max_iterations: int = 5  # 减少迭代次数，避免过度搜索
    timeout: int = 60
    
    # 迭代检索器配置
    enable_iterative_retrieval: bool = False  # 是否启用迭代预检索
    iterative_retrieval_strategy: str = "auto"  # auto | single | iterative
    
    # 可自定义的查询指令（会追加到用户消息末尾）
    query_instruction: str = """## 你的任务
请根据 <current_query> 中的用户问题，使用工具搜索相关记忆。
**不要**模拟对话、不要回复用户，只需调用工具并输出搜索结果。
如果 <recent_memory> 中已包含相关信息，可以直接输出"无需检索"。"""
    
    # Graphiti 专用说明（可选追加）
    graphiti_prompt_addition: str = """

## 🔗 Graphiti 时序图谱工具（如果可用）

如果工具列表中包含 `graphiti_` 前缀的工具，说明 Graphiti 已启用：

### graphiti_search
- **功能**：语义 + 关键词 + 图遍历混合搜索
- **优势**：能找到语义相关但不含关键词的内容；支持多跳关系
- **何时用**：复杂问题、需要关系推理的问题

### graphiti_temporal
- **功能**：查询某个时间点的知识状态
- **优势**：能回答"那时候是什么情况"
- **何时用**：用户问过去某个时间的状态

### graphiti_multi_hop
- **功能**：多跳关系查询，沿关系边遍历
- **优势**：能回答"A的B的C是什么"这类问题
- **何时用**：需要多层关联推理的问题

### 选择策略
| 问题类型 | 推荐工具 |
|---------|---------|
| 精确关键词查找 | search_memories |
| 语义相关/模糊查找 | graphiti_search 或 rag_search |
| 多跳关系推理 | graphiti_search / graphiti_multi_hop |
| 时间点状态 | graphiti_temporal |
| 读具体日期日记 | read_diary |
"""
    
    system_prompt: str = """你是记忆检索助手，负责为主模型查找用户的相关历史记忆。

## ⚠️ 重要规则
1. 你**只负责搜索**，不要回复用户的问题
2. 你**只负责搜索**，不要模拟对话
3. <conversation_context> 中的内容是用户和主模型的对话历史，你只是观察者
4. <recent_memory> 中是最近的记忆，如果已经包含相关信息，说明主模型能看到，你就不用搜了
5. 只有 <current_query> 涉及更久远的记忆时，才需要使用工具搜索

## ⏰ 记忆库时间范围（重要！）
<recent_memory> 中会包含"记忆库范围"信息，例如：
- 最早记录：2025-12-28
- 最新记录：2025-12-30
- 运行天数：3 天

**关键判断**：
- 如果用户问的事情发生在"最早记录"之前，**直接输出"无需检索：记忆系统当时还未上线"**
- 如果运行天数很短（<30天），大部分历史问题都不需要搜索
- 不要浪费时间搜索不存在的时间段！

## 上下文说明
- <recent_memory>：最近7天的日记/摘要（主模型能看到）+ 记忆库时间范围
- <conversation_context>：当前对话历史（只读，不要参与对话！）
- <current_query>：需要检索的问题

## 工具使用策略
1. **search_memories**：用关键词搜索全部记忆（包括7天外的日记和各类总结）
2. **read_diary**：读取特定日期的完整日记（如 2025-01-15）
3. **read_summary**：读取周/月/季总结（如 type="monthly", identifier="2025-11"）
4. **get_node**：获取人物/概念的详细信息
5. **list_all_people**：查看记忆中出现过的所有人物

## 搜索建议
- 用户提到人名 → 搜索这个人，读取人物节点
- 用户问"上个月" → 先看记忆库范围，如果上个月在范围外就不用搜
- 用户问某个项目 → 搜索项目名关键词
- 用户提到时间 → 先检查时间是否在记忆库范围内！

## 输出格式
```
【相关记忆】
- YYYY-MM-DD: 内容摘要
- YYYY-Wxx周总结: 摘要
- 人物节点[[xxx]]: 关键信息

【涉及人物】（如有）
- 人物名
```

**快速判断输出**：
- 记忆库范围外的时间 → 无需检索：该时间段记忆系统还未上线
- recent_memory已包含信息 → 无需额外检索：短期记忆已包含
- 闲聊/玩笑/不涉及记忆 → 无需检索：当前对话不涉及历史记忆
- 搜索无结果 → 未找到相关记忆"""


@dataclass 
class AgentResult:
    """Agent执行结果"""
    success: bool
    content: str  # 最终输出内容
    reasoning: str = ""  # 思维链过程
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)  # 工具调用历史
    iterations: int = 0
    tokens_used: Dict[str, int] = field(default_factory=dict)


class MemoryAgent:
    """记忆检索Agent"""
    
    def __init__(
        self,
        memory_tools: MemoryTools,
        config: Optional[AgentConfig] = None,
        retrieval_router: Optional["RetrievalRouter"] = None
    ):
        """
        初始化Agent
        
        Args:
            memory_tools: 记忆工具实例
            config: Agent配置
            retrieval_router: 迭代检索路由器（可选，用于智能预检索）
        """
        self.memory_tools = memory_tools
        self.config = config or AgentConfig()
        self.retrieval_router = retrieval_router
        
        # 初始化OpenAI客户端（不使用系统代理，避免兼容性问题）
        self.client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            http_client=httpx.Client(proxy=None)
        )
        
        # 如果启用了迭代检索但没有传入 router，记录警告
        if self.config.enable_iterative_retrieval and not self.retrieval_router:
            logger.warning("[MemoryAgent] enable_iterative_retrieval=True 但未提供 retrieval_router")
    
    def _prepare_retrieval(
        self,
        query: str,
        context: Optional[str] = None,
        include_write_tools: bool = False,
        mode: str = "sync"
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
        """
        准备检索所需的消息和工具（公共初始化逻辑）
        
        Args:
            query: 用户问题
            context: 额外上下文
            include_write_tools: 是否包含写入工具
            mode: 模式标识，用于调试日志 ("sync" 或 "stream")
            
        Returns:
            (messages, tools, user_content)
        """
        # 构建消息
        messages = [
            {"role": "system", "content": self.config.system_prompt}
        ]
        
        # 使用 XML 标签包裹内容
        user_content = self._build_user_message(query, context, include_instruction=True)
        messages.append({"role": "user", "content": user_content})
        
        # 获取工具列表
        tools = self.memory_tools.get_openai_tools(include_write=include_write_tools)
        
        # 记录调试日志
        get_debug_logger().log_search_agent(
            model=self.config.model,
            system_prompt=self.config.system_prompt,
            user_message=user_content,
            messages=messages.copy(),
            extra={
                "query": query,
                "include_write_tools": include_write_tools,
                "tools_count": len(tools) if tools else 0,
                "mode": mode
            }
        )
        
        return messages, tools, user_content
    
    def retrieve(
        self,
        query: str,
        context: Optional[str] = None,
        include_write_tools: bool = False,
        use_iterative_retrieval: Optional[bool] = None
    ) -> AgentResult:
        """
        执行记忆检索（同步版本）
        
        Args:
            query: 用户问题
            context: 额外上下文（如最近对话，格式应包含 recent_memory 部分）
            include_write_tools: 是否包含写入工具
            use_iterative_retrieval: 是否使用迭代预检索（None 使用配置默认值）
            
        Returns:
            AgentResult
        """
        # 决定是否使用迭代预检索
        should_use_iterative = use_iterative_retrieval if use_iterative_retrieval is not None else self.config.enable_iterative_retrieval
        
        # 如果启用迭代预检索且有 router，先进行预检索
        iterative_context = ""
        if should_use_iterative and self.retrieval_router:
            iterative_result = self._run_iterative_pre_retrieval(query, context)
            if iterative_result:
                iterative_context = iterative_result
        
        # 合并迭代检索结果到 context
        enhanced_context = context or ""
        if iterative_context:
            enhanced_context = self._merge_iterative_context(enhanced_context, iterative_context)
        
        messages, tools, _ = self._prepare_retrieval(query, enhanced_context, include_write_tools, "sync")
        
        # 检查是否有 Graphiti 工具，动态追加 prompt
        has_graphiti = any(
            t["function"]["name"].startswith("graphiti_") for t in tools
        ) if tools else False
        
        if has_graphiti and self.config.graphiti_prompt_addition:
            # 修改 system prompt，追加 Graphiti 说明
            if messages and messages[0].get("role") == "system":
                messages[0]["content"] = messages[0]["content"] + self.config.graphiti_prompt_addition
        
        return self._run_agent_loop(messages, tools)
    
    def _run_iterative_pre_retrieval(
        self,
        query: str,
        context: Optional[str] = None
    ) -> Optional[str]:
        """
        运行迭代预检索
        
        使用 RetrievalRouter 进行智能预检索，收集初始证据
        
        Args:
            query: 用户查询
            context: 上下文
            
        Returns:
            格式化的预检索结果，如果失败返回 None
        """
        if not self.retrieval_router:
            return None
        
        try:
            logger.info(f"[MemoryAgent] 开始迭代预检索: '{query[:50]}...'")
            
            # 使用配置的策略
            force_strategy = None
            if self.config.iterative_retrieval_strategy != "auto":
                force_strategy = self.config.iterative_retrieval_strategy
            
            result = self.retrieval_router.retrieve(
                query=query,
                context=context or "",
                force_strategy=force_strategy
            )
            
            if result.success and result.evidence:
                logger.info(
                    f"[MemoryAgent] 预检索完成: {len(result.evidence)} 条证据, "
                    f"{result.iterations} 轮迭代, 策略={result.strategy}"
                )
                return self.retrieval_router.format_result_for_context(result)
            else:
                logger.warning(f"[MemoryAgent] 预检索无结果或失败: {result.error or '无证据'}")
                return None
                
        except Exception as e:
            logger.error(f"[MemoryAgent] 预检索出错: {e}")
            return None
    
    def _merge_iterative_context(
        self,
        original_context: str,
        iterative_context: str
    ) -> str:
        """
        合并迭代检索结果到原始上下文
        
        Args:
            original_context: 原始上下文
            iterative_context: 迭代检索结果
            
        Returns:
            合并后的上下文
        """
        if not original_context:
            return f"<iterative_retrieval>\n{iterative_context}\n</iterative_retrieval>"
        
        # 在原始上下文末尾添加迭代检索结果
        merged = original_context.rstrip()
        merged += f"\n\n<iterative_retrieval>\n{iterative_context}\n</iterative_retrieval>"
        
        return merged
    
    def _build_user_message(self, query: str, context: Optional[str] = None, include_instruction: bool = True) -> str:
        """
        构建用户消息，使用 XML 标签包裹各部分内容
        
        Args:
            query: 用户问题
            context: 上下文（包含最近记忆和对话历史）
            include_instruction: 是否包含query_instruction（DeepSeek缓存优化时设为False）
            
        Returns:
            格式化后的用户消息
        """
        from datetime import datetime
        
        parts = []
        
        # 添加当前时间信息（让小模型知道"现在"是什么时候）
        now = datetime.now()
        weekday_names = ['周一','周二','周三','周四','周五','周六','周日']
        time_info = f"""<current_time>
当前时间：{now.strftime('%Y年%m月%d日')} {weekday_names[now.weekday()]} {now.strftime('%H:%M')}
</current_time>"""
        parts.append(time_info)
        
        if context:
            # 尝试分离 recent_memory 和 conversation_context
            # context 格式通常是：
            # ## 最近N天记忆
            # ...
            # [原始对话上下文]
            # ...
            
            if "[原始对话上下文]" in context:
                # 分离两部分
                split_idx = context.find("[原始对话上下文]")
                recent_memory = context[:split_idx].strip()
                conversation = context[split_idx + len("[原始对话上下文]"):].strip()
                
                if recent_memory:
                    parts.append(f"<recent_memory>\n{recent_memory}\n</recent_memory>")
                if conversation:
                    parts.append(f"<conversation_context>\n{conversation}\n</conversation_context>")
            else:
                # 没有分隔符，整体作为上下文
                parts.append(f"<context>\n{context}\n</context>")
        
        # 分隔提示
        parts.append("---\n## 📌 以下是用户的【当前请求】，请根据此请求决定是否需要检索记忆：")
        
        # 用户问题
        parts.append(f"<current_query>\n{query}\n</current_query>")
        
        # 追加自定义指令（仅在需要时，DeepSeek缓存优化时指令已移到system消息）
        if include_instruction and self.config.query_instruction:
            parts.append(f"\n{self.config.query_instruction}")
        
        return "\n\n".join(parts)
    
    def _run_agent_loop(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]]
    ) -> AgentResult:
        """执行Agent循环"""
        iteration = 0
        tool_call_history = []
        total_reasoning = ""
        total_tokens = {"prompt": 0, "completion": 0, "total": 0}
        
        while iteration < self.config.max_iterations:
            try:
                # 调用LLM
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    tools=tools if tools else None,
                    timeout=self.config.timeout
                )
                
                message = response.choices[0].message
                finish_reason = response.choices[0].finish_reason
                
                # 统计token
                if hasattr(response, 'usage') and response.usage:
                    total_tokens["prompt"] += getattr(response.usage, 'prompt_tokens', 0)
                    total_tokens["completion"] += getattr(response.usage, 'completion_tokens', 0)
                    total_tokens["total"] += getattr(response.usage, 'total_tokens', 0)
                
                # 收集思维链
                if hasattr(message, 'reasoning_content') and message.reasoning_content:
                    total_reasoning += f"\n[迭代{iteration + 1}]\n{message.reasoning_content}\n"
                
                # 检查是否完成
                if finish_reason == "stop" or not message.tool_calls:
                    result_content = message.content or ""
                    
                    # 记录Agent响应到调试日志
                    get_debug_logger().log_search_agent(
                        model=self.config.model,
                        system_prompt="[响应记录]",
                        user_message=f"迭代次数: {iteration + 1}\n工具调用: {len(tool_call_history)} 次",
                        messages=[],
                        response=result_content,
                        extra={
                            "type": "agent_response",
                            "iterations": iteration + 1,
                            "tool_call_count": len(tool_call_history),
                            "tokens": total_tokens
                        }
                    )
                    
                    return AgentResult(
                        success=True,
                        content=result_content,
                        reasoning=total_reasoning,
                        tool_calls=tool_call_history,
                        iterations=iteration + 1,
                        tokens_used=total_tokens
                    )
                
                # 处理工具调用
                if message.tool_calls:
                    # 添加assistant消息
                    assistant_msg = {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            for tc in message.tool_calls
                        ]
                    }
                    if hasattr(message, 'reasoning_content') and message.reasoning_content:
                        assistant_msg["reasoning_content"] = message.reasoning_content
                    
                    messages.append(assistant_msg)
                    
                    # 执行工具调用
                    for tc in message.tool_calls:
                        tool_name = tc.function.name
                        try:
                            arguments = json.loads(tc.function.arguments) if tc.function.arguments else {}
                        except json.JSONDecodeError:
                            arguments = {}
                        
                        # 记录工具调用
                        tool_call_record = {
                            "id": tc.id,
                            "name": tool_name,
                            "arguments": arguments,
                            "iteration": iteration + 1
                        }
                        
                        # 执行工具
                        result = self.memory_tools.call_tool(tool_name, arguments)
                        tool_call_record["result"] = result[:500] + "..." if len(result) > 500 else result
                        tool_call_history.append(tool_call_record)
                        
                        # 添加工具结果
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result
                        })
                
                iteration += 1
                
            except Exception as e:
                return AgentResult(
                    success=False,
                    content=f"Agent执行出错: {str(e)}",
                    reasoning=total_reasoning,
                    tool_calls=tool_call_history,
                    iterations=iteration + 1,
                    tokens_used=total_tokens
                )
        
        # 达到最大迭代次数
        return AgentResult(
            success=False,
            content="达到最大迭代次数，检索未完成。",
            reasoning=total_reasoning,
            tool_calls=tool_call_history,
            iterations=iteration,
            tokens_used=total_tokens
        )
    
    def retrieve_stream(
        self,
        query: str,
        context: Optional[str] = None,
        include_write_tools: bool = False,
        use_iterative_retrieval: Optional[bool] = None
    ) -> Generator[Dict[str, Any], None, AgentResult]:
        """
        流式执行记忆检索
        
        Yields:
            中间状态更新（思维链、工具调用等）
            
        Returns:
            最终AgentResult
        """
        # 决定是否使用迭代预检索
        should_use_iterative = use_iterative_retrieval if use_iterative_retrieval is not None else self.config.enable_iterative_retrieval
        
        # 如果启用迭代预检索且有 router，先进行预检索
        iterative_context = ""
        if should_use_iterative and self.retrieval_router:
            yield {"type": "iterative_retrieval_start"}
            iterative_result = self._run_iterative_pre_retrieval(query, context)
            if iterative_result:
                iterative_context = iterative_result
                yield {"type": "iterative_retrieval_complete", "result_preview": iterative_result[:200]}
        
        # 合并迭代检索结果到 context
        enhanced_context = context or ""
        if iterative_context:
            enhanced_context = self._merge_iterative_context(enhanced_context, iterative_context)
        
        messages, tools, _ = self._prepare_retrieval(query, enhanced_context, include_write_tools, "stream")
        
        # 检查是否有 Graphiti 工具，动态追加 prompt
        has_graphiti = any(
            t["function"]["name"].startswith("graphiti_") for t in tools
        ) if tools else False
        
        if has_graphiti and self.config.graphiti_prompt_addition:
            # 修改 system prompt，追加 Graphiti 说明
            if messages and messages[0].get("role") == "system":
                messages[0]["content"] = messages[0]["content"] + self.config.graphiti_prompt_addition
        
        iteration = 0
        tool_call_history = []
        total_reasoning = ""
        total_tokens = {"prompt": 0, "completion": 0, "total": 0}
        
        while iteration < self.config.max_iterations:
            yield {"type": "iteration_start", "iteration": iteration + 1}
            
            try:
                # 流式调用
                stream = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    tools=tools if tools else None,
                    stream=True,
                    stream_options={"include_usage": True},
                    timeout=self.config.timeout
                )
                
                reasoning_content = ""
                content = ""
                tool_calls_data = {}
                finish_reason = None
                
                for chunk in stream:
                    # 统计token
                    if hasattr(chunk, 'usage') and chunk.usage:
                        if getattr(chunk.usage, 'total_tokens', 0) > 0:
                            total_tokens["prompt"] += getattr(chunk.usage, 'prompt_tokens', 0)
                            total_tokens["completion"] += getattr(chunk.usage, 'completion_tokens', 0)
                            total_tokens["total"] += getattr(chunk.usage, 'total_tokens', 0)
                    
                    if not chunk.choices:
                        continue
                    
                    delta = chunk.choices[0].delta
                    chunk_finish = chunk.choices[0].finish_reason
                    
                    if chunk_finish:
                        finish_reason = chunk_finish
                    
                    # 处理思维链
                    if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        reasoning_content += delta.reasoning_content
                        yield {
                            "type": "reasoning",
                            "content": delta.reasoning_content
                        }
                    
                    # 处理内容
                    if hasattr(delta, 'content') and delta.content:
                        content += delta.content
                        yield {
                            "type": "content",
                            "content": delta.content
                        }
                    
                    # 处理工具调用
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index if hasattr(tc, 'index') else 0
                            if idx not in tool_calls_data:
                                tool_calls_data[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""}
                                }
                            
                            if hasattr(tc, 'id') and tc.id:
                                tool_calls_data[idx]["id"] = tc.id
                            if hasattr(tc, 'function'):
                                if hasattr(tc.function, 'name') and tc.function.name:
                                    tool_calls_data[idx]["function"]["name"] += tc.function.name
                                if hasattr(tc.function, 'arguments') and tc.function.arguments:
                                    tool_calls_data[idx]["function"]["arguments"] += tc.function.arguments
                
                total_reasoning += f"\n[迭代{iteration + 1}]\n{reasoning_content}\n" if reasoning_content else ""
                
                # 检查完成
                tool_calls_list = [tool_calls_data[i] for i in sorted(tool_calls_data.keys())]
                
                if finish_reason == "stop" or not tool_calls_list:
                    result = AgentResult(
                        success=True,
                        content=content,
                        reasoning=total_reasoning,
                        tool_calls=tool_call_history,
                        iterations=iteration + 1,
                        tokens_used=total_tokens
                    )
                    yield {"type": "complete", "result": result}
                    return result
                
                # 执行工具调用
                if tool_calls_list:
                    assistant_msg = {
                        "role": "assistant",
                        "content": content,
                        "reasoning_content": reasoning_content,
                        "tool_calls": tool_calls_list
                    }
                    messages.append(assistant_msg)
                    
                    for tc in tool_calls_list:
                        tool_name = tc["function"]["name"]
                        try:
                            arguments = json.loads(tc["function"]["arguments"])
                        except:
                            arguments = {}
                        
                        yield {
                            "type": "tool_call",
                            "name": tool_name,
                            "arguments": arguments
                        }
                        
                        result = self.memory_tools.call_tool(tool_name, arguments)
                        
                        tool_call_history.append({
                            "id": tc["id"],
                            "name": tool_name,
                            "arguments": arguments,
                            "result": result[:500] + "..." if len(result) > 500 else result,
                            "iteration": iteration + 1
                        })
                        
                        yield {
                            "type": "tool_result",
                            "name": tool_name,
                            "result": result[:200] + "..." if len(result) > 200 else result
                        }
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result
                        })
                
                iteration += 1
                
            except Exception as e:
                result = AgentResult(
                    success=False,
                    content=f"Agent执行出错: {str(e)}",
                    reasoning=total_reasoning,
                    tool_calls=tool_call_history,
                    iterations=iteration + 1,
                    tokens_used=total_tokens
                )
                yield {"type": "error", "message": str(e), "result": result}
                return result
        
        # 达到最大迭代
        result = AgentResult(
            success=False,
            content="达到最大迭代次数",
            reasoning=total_reasoning,
            tool_calls=tool_call_history,
            iterations=iteration,
            tokens_used=total_tokens
        )
        yield {"type": "max_iterations", "result": result}
        return result
    
    def format_result_for_context(self, result: AgentResult) -> str:
        """
        将Agent结果格式化为上下文（供大模型使用）
        
        Args:
            result: Agent执行结果
            
        Returns:
            格式化的记忆上下文
        """
        if not result.success:
            return f"[记忆检索失败: {result.content}]"
        
        output = "## 📚 相关记忆\n\n"
        output += result.content
        
        # 如果有工具调用，添加摘要
        if result.tool_calls:
            output += "\n\n---\n"
            output += f"_检索过程：执行了 {len(result.tool_calls)} 次工具调用，"
            output += f"经过 {result.iterations} 轮推理_"
        
        return output


# 便捷函数
_global_agent: Optional[MemoryAgent] = None


def init_memory_agent(
    memory_tools: MemoryTools,
    config: Optional[AgentConfig] = None,
    retrieval_router: Optional["RetrievalRouter"] = None
) -> MemoryAgent:
    """
    初始化全局Agent
    
    Args:
        memory_tools: 记忆工具实例
        config: Agent配置
        retrieval_router: 迭代检索路由器（可选）
    """
    global _global_agent
    _global_agent = MemoryAgent(memory_tools, config, retrieval_router)
    return _global_agent


def get_memory_agent() -> Optional[MemoryAgent]:
    """获取全局Agent"""
    return _global_agent


# 测试代码已移至 tests/test_agent.py
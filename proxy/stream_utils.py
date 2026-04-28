"""
流式响应处理工具

提供构建 SSE 格式响应的辅助函数，减少 deepseek_proxy.py 的代码重复
"""

import json
from typing import Dict, Any, Optional


def create_stream_chunk(
    chat_id: str,
    created_time: int,
    model: str,
    delta: Dict[str, Any],
    finish_reason: Optional[str] = None,
    usage: Optional[Dict[str, int]] = None
) -> str:
    """
    创建 SSE 格式的流式响应 chunk
    
    Args:
        chat_id: 会话 ID
        created_time: 创建时间戳
        model: 模型名称
        delta: 增量内容
        finish_reason: 结束原因（可选）
        usage: token 使用统计（可选）
    
    Returns:
        SSE 格式的字符串
    """
    chunk_data = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created_time,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": delta,
            "logprobs": None,
            "finish_reason": finish_reason
        }]
    }
    
    if usage:
        chunk_data["usage"] = usage
    
    return f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"


def create_content_chunk(
    chat_id: str,
    created_time: int,
    model: str,
    content: str
) -> str:
    """创建包含 content 的 chunk"""
    return create_stream_chunk(
        chat_id, created_time, model,
        delta={"content": content}
    )


def create_reasoning_chunk(
    chat_id: str,
    created_time: int,
    model: str,
    reasoning_content: str
) -> str:
    """创建包含 reasoning_content 的 chunk"""
    return create_stream_chunk(
        chat_id, created_time, model,
        delta={"reasoning_content": reasoning_content}
    )


def create_final_chunk(
    chat_id: str,
    created_time: int,
    model: str,
    finish_reason: str = "stop",
    usage: Optional[Dict[str, int]] = None
) -> str:
    """创建最终的结束 chunk"""
    return create_stream_chunk(
        chat_id, created_time, model,
        delta={},
        finish_reason=finish_reason,
        usage=usage
    )


def create_done_signal() -> str:
    """创建流结束信号"""
    return "data: [DONE]\n\n"


class XmlToolInterceptor:
    """
    XML 工具调用拦截器
    
    用于在流式输出中检测和处理 <<<tool_call>>>...<<</tool_call>>> 格式的工具调用
    """
    
    TOOL_CALL_PREFIX = "<<<tool_call>>>"
    TOOL_CALL_SUFFIX = "<<</tool_call>>>"
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """重置状态"""
        self.xml_mode = False
        self.xml_buffer = ""
        self.pending_buffer = ""
        self.has_sent_content = False
    
    def process_content(
        self, 
        new_content: str, 
        chat_id: str, 
        created_time: int, 
        model: str
    ) -> tuple[list[str], bool]:
        """
        处理新内容，返回需要输出的 chunks 和是否应该继续处理
        
        Args:
            new_content: 新接收的内容
            chat_id: 会话 ID
            created_time: 创建时间
            model: 模型名称
        
        Returns:
            (chunks_to_yield, should_continue)
            - chunks_to_yield: 需要输出的 SSE chunks 列表
            - should_continue: 是否应该跳过后续处理
        """
        chunks = []
        
        # 已进入 XML 工具模式
        if self.xml_mode:
            self.xml_buffer += new_content
            
            if self.TOOL_CALL_SUFFIX in self.xml_buffer:
                # 工具调用结束，生成提示
                hint = self._extract_tool_hint()
                if hint:
                    chunks.append(create_content_chunk(chat_id, created_time, model, hint))
                    self.has_sent_content = True
                
                self.xml_mode = False
                self.xml_buffer = ""
            
            return chunks, True
        
        # 有待处理的缓冲
        if self.pending_buffer:
            self.pending_buffer += new_content
            
            if self.TOOL_CALL_PREFIX in self.pending_buffer:
                idx = self.pending_buffer.find(self.TOOL_CALL_PREFIX)
                if idx > 0:
                    normal_part = self.pending_buffer[:idx]
                    chunks.append(create_content_chunk(chat_id, created_time, model, normal_part))
                    self.has_sent_content = True
                
                self.xml_mode = True
                self.xml_buffer = self.pending_buffer[idx:]
                self.pending_buffer = ""
                return chunks, True
            
            # 检查是否可能是前缀的开始
            is_possible_prefix = (
                self.TOOL_CALL_PREFIX.startswith(self.pending_buffer) or
                self.pending_buffer.startswith(self.TOOL_CALL_PREFIX[:len(self.pending_buffer)])
            )
            
            if not is_possible_prefix:
                chunks.append(create_content_chunk(chat_id, created_time, model, self.pending_buffer))
                self.has_sent_content = True
                self.pending_buffer = ""
            
            return chunks, True
        
        # 检测 < 字符，可能是工具调用的开始
        if "<" in new_content:
            idx = new_content.find("<")
            
            if idx > 0:
                normal_part = new_content[:idx]
                chunks.append(create_content_chunk(chat_id, created_time, model, normal_part))
                self.has_sent_content = True
            
            self.pending_buffer = new_content[idx:]
            return chunks, True
        
        # 普通内容，直接输出
        chunks.append(create_content_chunk(chat_id, created_time, model, new_content))
        self.has_sent_content = True
        return chunks, False
    
    def _extract_tool_hint(self) -> Optional[str]:
        """从 XML 缓冲中提取工具调用提示"""
        import re
        try:
            name_match = re.search(r'name:\s*([^\s<\n]+)', self.xml_buffer)
            tool_name = name_match.group(1).strip() if name_match else "unknown"
            
            args_match = re.search(r'arguments:\s*(.*?)(?:<<</tool_call>>>|$)', self.xml_buffer, re.DOTALL)
            args_str = args_match.group(1).strip() if args_match else "{}"
            
            return f"\n`⚡ 调用工具: {tool_name}`\n```\n{args_str}\n```\n"
        except Exception:
            return None


def accumulate_tool_calls(
    tool_calls_data: Dict[int, Dict[str, Any]],
    delta_tool_calls: list
) -> None:
    """
    累积 tool_calls 增量数据
    
    Args:
        tool_calls_data: 累积的工具调用数据 (会被原地修改)
        delta_tool_calls: 增量工具调用数据
    """
    for tc in delta_tool_calls:
        tc_index = tc.index if hasattr(tc, 'index') else 0
        
        if tc_index not in tool_calls_data:
            tool_calls_data[tc_index] = {
                "id": tc.id if hasattr(tc, 'id') and tc.id else f"call_{tc_index}",
                "type": tc.type if hasattr(tc, 'type') else "function",
                "function": {"name": "", "arguments": ""}
            }
        
        if hasattr(tc, 'id') and tc.id:
            tool_calls_data[tc_index]["id"] = tc.id
        
        if hasattr(tc, 'function'):
            if hasattr(tc.function, 'name') and tc.function.name:
                tool_calls_data[tc_index]["function"]["name"] += tc.function.name
            if hasattr(tc.function, 'arguments') and tc.function.arguments:
                tool_calls_data[tc_index]["function"]["arguments"] += tc.function.arguments


def accumulate_usage(
    total_usage: Dict[str, Any],
    chunk_usage: Any
) -> None:
    """
    累积 token 使用统计
    
    Args:
        total_usage: 累计使用统计 (会被原地修改)
        chunk_usage: 单次 chunk 的使用统计
    """
    if not chunk_usage:
        return
    
    total_usage["prompt_tokens"] += getattr(chunk_usage, 'prompt_tokens', 0)
    total_usage["completion_tokens"] += getattr(chunk_usage, 'completion_tokens', 0)
    total_usage["total_tokens"] += getattr(chunk_usage, 'total_tokens', 0)
    
    # 扩展统计
    if hasattr(chunk_usage, 'prompt_tokens_details'):
        if "prompt_tokens_details" not in total_usage:
            total_usage["prompt_tokens_details"] = {"cached_tokens": 0}
        total_usage["prompt_tokens_details"]["cached_tokens"] += getattr(
            chunk_usage.prompt_tokens_details, 'cached_tokens', 0
        )
    
    if hasattr(chunk_usage, 'completion_tokens_details'):
        if "completion_tokens_details" not in total_usage:
            total_usage["completion_tokens_details"] = {"reasoning_tokens": 0}
        total_usage["completion_tokens_details"]["reasoning_tokens"] += getattr(
            chunk_usage.completion_tokens_details, 'reasoning_tokens', 0
        )
    
    if hasattr(chunk_usage, 'prompt_cache_hit_tokens'):
        if "prompt_cache_hit_tokens" not in total_usage:
            total_usage["prompt_cache_hit_tokens"] = 0
        total_usage["prompt_cache_hit_tokens"] += getattr(chunk_usage, 'prompt_cache_hit_tokens', 0)
    
    if hasattr(chunk_usage, 'prompt_cache_miss_tokens'):
        if "prompt_cache_miss_tokens" not in total_usage:
            total_usage["prompt_cache_miss_tokens"] = 0
        total_usage["prompt_cache_miss_tokens"] += getattr(chunk_usage, 'prompt_cache_miss_tokens', 0)
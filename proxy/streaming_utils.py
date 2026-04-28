"""
流式处理工具模块

提供统一的流式响应处理、工具调用解析和消息构建功能。
被 DeepSeekProxy 和 MemoryAgent 共享使用。
"""

import json
import re
import uuid
import time
import logging
from typing import Dict, List, Any, Optional, Generator, Tuple
from dataclasses import dataclass, field


@dataclass
class StreamChunk:
    """流式响应数据块"""
    content: str = ""
    reasoning_content: str = ""
    tool_calls: List[Dict] = field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Optional[Dict] = None
    
    def is_empty(self) -> bool:
        """检查是否为空块"""
        return not (self.content or self.reasoning_content or self.tool_calls)


@dataclass  
class ToolCallData:
    """工具调用数据"""
    id: str
    name: str
    arguments: str
    index: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式"""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments
            }
        }


@dataclass
class ParsedStreamResult:
    """解析后的流式结果"""
    content: str
    reasoning_content: str
    tool_calls: List[ToolCallData]
    finish_reason: Optional[str]
    usage: Dict[str, int]


class StreamingParser:
    """流式响应解析器"""
    
    # XML 工具调用标记
    TOOL_CALL_PREFIX = "<<<tool_call>>>"
    TOOL_CALL_SUFFIX = "<<</tool_call>>>"
    
    def __init__(self):
        self.tool_calls_data: Dict[int, Dict] = {}
        self.xml_buffer: str = ""
        self.pending_buffer: str = ""
        self.xml_tool_mode: bool = False
        
    def parse_chunk(self, chunk: Any) -> Optional[StreamChunk]:
        """
        解析单个流式响应块
        
        Args:
            chunk: OpenAI 流式响应块
            
        Returns:
            StreamChunk 或 None
        """
        result = StreamChunk()
        
        if not chunk.choices:
            # 处理 usage 信息
            if hasattr(chunk, 'usage') and chunk.usage:
                result.usage = self._extract_usage(chunk.usage)
            return result if result.usage else None
        
        delta = chunk.choices[0].delta
        finish_reason = chunk.choices[0].finish_reason
        
        if finish_reason:
            result.finish_reason = finish_reason
        
        # 提取 reasoning_content
        if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
            result.reasoning_content = delta.reasoning_content
        
        # 提取 content
        if hasattr(delta, 'content') and delta.content:
            result.content = delta.content
        
        # 提取 tool_calls
        if hasattr(delta, 'tool_calls') and delta.tool_calls:
            result.tool_calls = self._parse_tool_calls_delta(delta.tool_calls)
        
        return result
    
    def _extract_usage(self, usage: Any) -> Dict[str, int]:
        """提取 usage 信息"""
        result = {
            "prompt_tokens": getattr(usage, 'prompt_tokens', 0),
            "completion_tokens": getattr(usage, 'completion_tokens', 0),
            "total_tokens": getattr(usage, 'total_tokens', 0)
        }
        
        # 提取 details
        if hasattr(usage, 'completion_tokens_details') and usage.completion_tokens_details:
            details = usage.completion_tokens_details
            if hasattr(details, 'reasoning_tokens'):
                result["reasoning_tokens"] = details.reasoning_tokens
        
        if hasattr(usage, 'prompt_tokens_details') and usage.prompt_tokens_details:
            details = usage.prompt_tokens_details
            if hasattr(details, 'cached_tokens'):
                result["cached_tokens"] = details.cached_tokens
        
        return result
    
    def _parse_tool_calls_delta(self, tool_calls: List[Any]) -> List[Dict]:
        """解析工具调用增量"""
        result = []
        for tc in tool_calls:
            tc_data = {
                "index": tc.index if hasattr(tc, 'index') else 0,
                "id": tc.id if hasattr(tc, 'id') and tc.id else "",
            }
            
            if hasattr(tc, 'function'):
                func = tc.function
                if hasattr(func, 'name') and func.name:
                    tc_data["name"] = func.name
                if hasattr(func, 'arguments') and func.arguments:
                    tc_data["arguments"] = func.arguments
            
            result.append(tc_data)
        
        return result
    
    def parse_xml_tool_calls(self, content: str) -> List[Dict[str, Any]]:
        """
        解析 XML 格式的工具调用
        
        Args:
            content: 包含 XML 工具调用的文本
            
        Returns:
            工具调用列表
        """
        tool_calls = []
        
        # 匹配 <<<tool_call>>> ... <<</tool_call>>>
        pattern = r'<<<tool_call>>>(.*?)<<</tool_call>>>'
        matches = re.findall(pattern, content, re.DOTALL)
        
        for match in matches:
            try:
                # 解析 name 和 arguments
                name_match = re.search(r'name:\s*([^\s<\n]+)', match)
                tool_name = name_match.group(1).strip() if name_match else "unknown"
                
                args_match = re.search(r'arguments:\s*(\{.*?\})$', match, re.DOTALL)
                if args_match:
                    args_str = args_match.group(1).strip()
                    try:
                        arguments = json.loads(args_str)
                    except json.JSONDecodeError:
                        arguments = {"raw": args_str}
                else:
                    arguments = {}
                
                tool_calls.append({
                    "name": tool_name,
                    "arguments": arguments
                })
            except Exception as e:
                logging.warning(f"解析 XML 工具调用失败: {e}")
        
        # 也尝试匹配 <tool_call> 格式（不带 <<< >>>）
        alt_pattern = r'<tool_call>(.*?)</tool_call>'
        alt_matches = re.findall(alt_pattern, content, re.DOTALL)
        
        for match in alt_matches:
            if match not in [m for m in matches]:  # 避免重复
                try:
                    name_match = re.search(r'name:\s*([^\s<\n]+)', match)
                    tool_name = name_match.group(1).strip() if name_match else "unknown"
                    
                    args_match = re.search(r'arguments:\s*(\{.*?\})$', match, re.DOTALL)
                    if args_match:
                        args_str = args_match.group(1).strip()
                        try:
                            arguments = json.loads(args_str)
                        except json.JSONDecodeError:
                            arguments = {"raw": args_str}
                    else:
                        arguments = {}
                    
                    tool_calls.append({
                        "name": tool_name,
                        "arguments": arguments
                    })
                except Exception as e:
                    logging.warning(f"解析备用 XML 工具调用失败: {e}")
        
        return tool_calls
    
    def collect_tool_calls(self, chunk: StreamChunk) -> List[ToolCallData]:
        """
        收集完整的工具调用
        
        将增量更新的 tool_calls 聚合成完整的调用
        """
        # 更新内部状态
        for tc in chunk.tool_calls:
            idx = tc.get("index", 0)
            
            if idx not in self.tool_calls_data:
                self.tool_calls_data[idx] = {
                    "id": "",
                    "name": "",
                    "arguments": ""
                }
            
            if tc.get("id"):
                self.tool_calls_data[idx]["id"] = tc["id"]
            if tc.get("name"):
                self.tool_calls_data[idx]["name"] += tc["name"]
            if tc.get("arguments"):
                self.tool_calls_data[idx]["arguments"] += tc["arguments"]
        
        # 转换为 ToolCallData 列表
        result = []
        for idx in sorted(self.tool_calls_data.keys()):
            data = self.tool_calls_data[idx]
            if data["id"] and data["name"]:  # 确保有完整信息
                result.append(ToolCallData(
                    id=data["id"],
                    name=data["name"],
                    arguments=data["arguments"],
                    index=idx
                ))
        
        return result
    
    def reset(self):
        """重置解析器状态"""
        self.tool_calls_data.clear()
        self.xml_buffer = ""
        self.pending_buffer = ""
        self.xml_tool_mode = False


class SSEBuilder:
    """SSE 响应构建器"""
    
    def __init__(self, chat_id: Optional[str] = None, model: str = "unknown"):
        self.chat_id = chat_id or f"chatcmpl-{uuid.uuid4().hex[:24]}"
        self.model = model
        self.created_time = int(time.time())
        self.chunk_count = 0
    
    def build_chunk(
        self,
        content: str = "",
        reasoning_content: str = "",
        finish_reason: Optional[str] = None,
        usage: Optional[Dict] = None
    ) -> str:
        """
        构建 SSE 格式的数据块
        
        Args:
            content: 普通内容
            reasoning_content: 推理内容
            finish_reason: 结束原因
            usage: Token 使用信息
            
        Returns:
            SSE 格式的字符串
        """
        delta = {}
        
        if reasoning_content:
            delta["reasoning_content"] = reasoning_content
        
        if content:
            delta["content"] = content
        
        # 构建基础响应
        chunk_data = {
            "id": self.chat_id,
            "object": "chat.completion.chunk",
            "created": self.created_time,
            "model": self.model,
            "choices": [{
                "index": 0,
                "delta": delta,
                "logprobs": None,
                "finish_reason": finish_reason
            }]
        }
        
        if usage:
            chunk_data["usage"] = usage
        
        self.chunk_count += 1
        
        return f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
    
    def build_tool_call_chunk(self, tool_calls: List[Dict], finish_reason: Optional[str] = None) -> str:
        """构建工具调用类型的数据块"""
        chunk_data = {
            "id": self.chat_id,
            "object": "chat.completion.chunk",
            "created": self.created_time,
            "model": self.model,
            "choices": [{
                "index": 0,
                "delta": {},
                "logprobs": None,
                "finish_reason": finish_reason or "tool_calls"
            }]
        }
        
        return f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
    
    def build_done(self) -> str:
        """构建结束标记"""
        return "data: [DONE]\n\n"


class ToolCallFormatter:
    """工具调用格式化器"""
    
    @staticmethod
    def format_for_display(tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        格式化工具调用为显示文本
        
        Args:
            tool_name: 工具名称
            arguments: 参数
            
        Returns:
            格式化的显示文本
        """
        args_str = json.dumps(arguments, ensure_ascii=False, indent=2)
        
        if len(args_str) > 200:
            args_display = args_str[:200] + "..."
        else:
            args_display = args_str
        
        return f"\n`⚡ 调用工具: {tool_name}`\n```\n{args_display}\n```\n"
    
    @staticmethod
    def format_call_plan(tool_calls: List[Dict]) -> str:
        """格式化多个工具调用计划"""
        lines = []
        for tc in tool_calls:
            name = tc.get("function", {}).get("name", "unknown")
            args = tc.get("function", {}).get("arguments", "{}")
            lines.append(f"- {name}: {args[:100]}...")
        
        return "\n".join(lines) + "\n"
    
    @staticmethod
    def parse_arguments(args_str: str) -> Dict[str, Any]:
        """
        安全地解析参数 JSON
        
        Args:
            args_str: JSON 字符串
            
        Returns:
            解析后的字典，失败返回空字典
        """
        if not args_str:
            return {}
        
        try:
            return json.loads(args_str)
        except json.JSONDecodeError as e:
            logging.warning(f"JSON 解析失败: {e}, 尝试修复...")
            
            # 尝试修复常见的 JSON 错误
            try:
                # 修复尾部逗号
                fixed = re.sub(r',\s*}', '}', args_str)
                fixed = re.sub(r',\s*]', ']', fixed)
                
                # 修复空值
                fixed = re.sub(r'("[\w]+"\s*:\s*)([,}])', r'\1""\2', fixed)
                
                return json.loads(fixed)
            except json.JSONDecodeError:
                logging.error(f"JSON 修复失败，原始: {args_str[:200]}...")
                return {}


class MessageBuilder:
    """消息构建工具"""
    
    @staticmethod
    def build_assistant_message(
        content: str = "",
        reasoning_content: str = "",
        tool_calls: Optional[List[Dict]] = None,
        include_reasoning: bool = True
    ) -> Dict[str, Any]:
        """
        构建助手消息
        
        Args:
            content: 内容
            reasoning_content: 推理内容
            tool_calls: 工具调用
            include_reasoning: 是否包含推理内容
            
        Returns:
            消息字典
        """
        msg: Dict[str, Any] = {
            "role": "assistant"
        }
        
        # 组合内容
        combined_content = ""
        if reasoning_content and include_reasoning:
            combined_content = f"<think>{reasoning_content}</think>\n"
        if content:
            combined_content += content
        
        msg["content"] = combined_content if combined_content else None
        
        if tool_calls:
            msg["tool_calls"] = tool_calls
        
        if reasoning_content and include_reasoning:
            msg["reasoning_content"] = reasoning_content
        
        return msg
    
    @staticmethod
    def build_tool_result_message(
        tool_call_id: str,
        result: str
    ) -> Dict[str, Any]:
        """构建工具结果消息"""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result
        }
    
    @staticmethod
    def merge_tool_results(tool_results: List[str]) -> str:
        """合并多个工具结果为一条消息"""
        if len(tool_results) == 1:
            return tool_results[0]
        
        merged = []
        for i, result in enumerate(tool_results, 1):
            merged.append(f"[工具结果 {i}]\n{result}")
        
        return "\n\n".join(merged)


# 便捷函数
def create_streaming_context(model: str = "unknown") -> Tuple[StreamingParser, SSEBuilder]:
    """
    创建流式处理上下文
    
    Returns:
        (parser, builder) 元组
    """
    return StreamingParser(), SSEBuilder(model=model)


def format_stream_error(error: Exception, chat_id: Optional[str] = None) -> str:
    """格式化流式错误响应"""
    builder = SSEBuilder(chat_id=chat_id)
    
    error_content = f"[错误: {type(error).__name__}] {str(error)}"
    
    return builder.build_chunk(
        content=error_content,
        finish_reason="error"
    ) + builder.build_done()
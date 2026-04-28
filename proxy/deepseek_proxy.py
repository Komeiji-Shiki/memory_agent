"""
DeepSeek 代理处理器

核心类，处理流式和非流式请求，执行 MCP 和记忆工具调用
支持配置热重载
"""

import copy
import json
import os
import re
import sys
import time
import uuid
import logging
from typing import List, Dict, Any, Optional, Generator, Iterator, TypeVar

import httpx
from openai import OpenAI

from .config import get_config, get_base_url_from_chat_url, subscribe_config_changes
from .message_utils import (
    message_to_dict,
    format_tool_call_text,
    replace_old_tool_results,
    merge_assistant_message,
    parse_xml_tool_calls,
    is_memory_tool,
    is_memory_write_tool,
    MEMORY_TOOL_NAMES
)


# 尝试导入热重载事件类型
try:
    from .config_hot_reload import ConfigChangeEvent
    HAS_HOT_RELOAD = True
except ImportError:
    HAS_HOT_RELOAD = False


T = TypeVar('T')


def safe_stream_iterator(stream: Iterator[T], chat_id: str = "") -> Generator[T, None, None]:
    """
    安全的流式响应迭代器包装器
    
    捕获迭代过程中的JSON解析错误等异常，记录日志并跳过损坏的chunk，
    而不是让整个流式响应失败。
    
    Args:
        stream: 原始流式响应迭代器
        chat_id: 用于日志记录的Chat ID
    
    Yields:
        成功解析的chunk
    """
    while True:
        try:
            chunk = next(stream)
            yield chunk
        except StopIteration:
            # 正常结束
            break
        except json.JSONDecodeError as e:
            # JSON解析错误，记录并跳过
            logging.warning(f"[流式响应] JSON解析错误，跳过损坏的chunk (Chat ID: {chat_id}): {e}")
            continue
        except Exception as e:
            # 检查是否是JSON相关的嵌套异常
            error_str = str(e).lower()
            if 'json' in error_str or 'decode' in error_str or 'delimiter' in error_str:
                logging.warning(f"[流式响应] 数据解析错误，跳过损坏的chunk (Chat ID: {chat_id}): {e}")
                continue
            else:
                # 其他异常向上抛出
                raise


class DeepSeekProxy:
    """DeepSeek 代理处理器"""
    
    def __init__(
        self,
        api_key: str,
        mcp_manager: Optional[Any] = None,
        base_url: Optional[str] = None,
        memory_router: Optional[Any] = None
    ):
        """
        初始化代理
        
        Args:
            api_key: API 密钥
            mcp_manager: MCP 管理器（可选）
            base_url: API 基础 URL（可选）
            memory_router: 记忆路由器（可选）
        """
        self.api_key = api_key
        self.mcp_manager = mcp_manager
        self.memory_router = memory_router
        self.mcp_call_counter = 0  # 每个请求独立的MCP调用计数器
        
        # 初始化 OpenAI 客户端
        self._init_client(base_url)
        
        # 订阅配置变更
        self._setup_config_watcher()
    
    def _init_client(self, base_url: Optional[str] = None):
        """初始化 OpenAI 客户端"""
        config = get_config()
        
        if base_url is None:
            base_url = get_base_url_from_chat_url(
                config.get("chat_completions_url", "https://api.deepseek.com/v1/chat/completions")
            )
        
        # 创建不带代理的 http 客户端，避免系统代理设置导致的兼容性问题
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=base_url,
            http_client=httpx.Client(proxy=None),
            max_retries=config.get("max_retries", 0)
        )
        
        logging.info(f"[DeepSeekProxy] OpenAI 客户端已初始化: base_url={base_url}")
    
    def _setup_config_watcher(self):
        """设置配置变更监听"""
        if HAS_HOT_RELOAD:
            def on_config_changed(event):
                """配置变更回调"""
                changed_keys = event.changed_keys if hasattr(event, 'changed_keys') else set()
                
                # 检查是否需要重新初始化客户端
                client_related_keys = {
                    'chat_completions_url', 'models_url', 'api_key',
                    'max_retries', 'base_url'
                }
                
                if changed_keys and any(k in client_related_keys or
                                       any(c in k for c in client_related_keys)
                                       for k in changed_keys):
                    logging.info("[DeepSeekProxy] 检测到客户端相关配置变更，重新初始化客户端")
                    self._init_client()
                
                # 记录配置变更
                if changed_keys:
                    logging.info(f"[DeepSeekProxy] 配置已更新，变更项: {changed_keys}")
            
            try:
                subscribe_config_changes(on_config_changed)
                logging.info("[DeepSeekProxy] 已订阅配置变更通知")
            except Exception as e:
                logging.warning(f"[DeepSeekProxy] 订阅配置变更失败: {e}")
    
    def _execute_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """执行 MCP 工具"""
        if not self.mcp_manager:
            return None
        
        # 增加调用计数
        self.mcp_call_counter += 1
        call_number = self.mcp_call_counter
        
        # 日志记录
        logging.info(f"[MCP工具调用 #{call_number}] {tool_name}")
        logging.debug(f"[MCP工具调用 #{call_number}] 参数: {json.dumps(arguments, ensure_ascii=False)}")
        
        logging.info(f"[MCP Tool Execute #{call_number}] 调用工具 '{tool_name}'，参数: {arguments}")
        result = self.mcp_manager.call_tool(tool_name, arguments)
        
        # 结果显示
        result_str = str(result or '')
        display_limit = 2000
        if len(result_str) > display_limit:
            display_result = result_str[:display_limit] + f"\n... (剩余 {len(result_str)-display_limit} 字符)"
        else:
            display_result = result_str
        
        logging.info(f"[MCP工具结果 #{call_number}] {tool_name}")
        logging.debug(f"[MCP工具结果 #{call_number}] {display_result}")
        
        logging.info(f"[MCP Tool Result #{call_number}] 工具 '{tool_name}' 返回结果: {result_str}")
        return result
    
    def _is_mcp_tool(self, tool_name: str) -> bool:
        """检查是否是 MCP 工具"""
        if not self.mcp_manager:
            return False
        return tool_name in self.mcp_manager.tools
    
    def _should_add_reasoning_content(self, model: str) -> bool:
        """
        判断是否应该为指定模型添加 reasoning_content 字段
        """
        config = get_config()
        
        # 检查模型路由中的配置
        model_routes = config.get('model_routes', {})
        route_config = model_routes.get(model, {})
        thinking_mode = route_config.get('thinking_mode')
        
        if thinking_mode is not None:
            if thinking_mode is True:
                return True
            elif thinking_mode is False:
                return False
            elif thinking_mode == "auto":
                return "deepseek" in model.lower() or "reasoner" in model.lower() or \
                       ("claude" in model.lower() and "thinking" in model.lower())
        
        # 使用全局配置
        thinking_config = config.get("deepseek_thinking_mode", {})
        if not thinking_config.get("enabled", True):
            return False
        
        if thinking_config.get("auto_detect", True):
            return "deepseek" in model.lower() or "reasoner" in model.lower()
        else:
            return True
    
    def _get_outbound_reasoning_field(self, model: str) -> str:
        """
        获取发往上游时 assistant 消息使用的推理字段名
        
        只有特殊模型 [vercel] deepseek-v3.2-thinking 在工具续调时需要使用 reasoning。
        其他模型保持标准字段 reasoning_content。
        """
        if model == "[vercel] deepseek-v3.2-thinking":
            return "reasoning"
        return "reasoning_content"
    
    def _normalize_assistant_reasoning_fields(self, messages: List[Dict[str, Any]], model: str) -> int:
        """
        标准化 assistant 消息中的推理字段
        
        说明：
        - 仅在 thinking 模式模型下处理
        - 绝大多数模型对上游发送 reasoning_content
        - [vercel] deepseek-v3.2-thinking 只在出站时改为 reasoning
        - 同时移除另一种字段，避免网关/上游校验混乱
        
        Returns:
            被标准化的消息数量
        """
        if not self._should_add_reasoning_content(model):
            return 0
        
        outbound_field = self._get_outbound_reasoning_field(model)
        other_field = "reasoning_content" if outbound_field == "reasoning" else "reasoning"
        
        fixed_count = 0
        for msg in messages:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            
            reasoning_text = msg.get("reasoning_content")
            if not isinstance(reasoning_text, str):
                reasoning_text = msg.get("reasoning")
            if not isinstance(reasoning_text, str):
                reasoning_text = ""
            
            changed = False
            
            if msg.get(outbound_field) != reasoning_text:
                msg[outbound_field] = reasoning_text
                changed = True
            
            if other_field in msg:
                del msg[other_field]
                changed = True
            
            if changed:
                fixed_count += 1
        
        return fixed_count
    
    def process_request_stream(
        self,
        messages: List[Dict[str, Any]],
        model: str = "deepseek-reasoner",
        tools: Optional[List[Dict[str, Any]]] = None,
        execute_mcp_tools: bool = True,
        **kwargs
    ) -> Generator[str, None, None]:
        """
        处理流式聊天补全请求
        
        Args:
            messages: 消息列表
            model: 模型名称
            tools: 工具列表
            execute_mcp_tools: 是否自动执行 MCP 工具调用
            **kwargs: 其他参数
        
        Yields:
            SSE 格式的流式响应数据
        """
        config = get_config()
        
        # 合并 MCP 工具
        combined_tools = list(tools) if tools else []
        if self.mcp_manager:
            mcp_tools = self.mcp_manager.get_openai_tools()
            combined_tools.extend(mcp_tools)
        
        client_response_model = model
        
        if not combined_tools:
            combined_tools = None
        
        messages_copy = [msg.copy() for msg in messages]
        iteration = 0
        max_iterations = config.get('max_iterations', 100)
        chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created_time = int(time.time())
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        logging.info(f"[请求开始] Chat ID: {chat_id}, 模型: {model}, 消息数: {len(messages_copy)}, 流式: True")
        
        # 工具调用历史
        tool_call_history = []
        keep_tool_results_count = config.get('keep_tool_results_count', 0)
        
        logging.info(f"[流式请求] Chat ID: {chat_id}, 模型: {model}, 消息数: {len(messages_copy)}")
        logging.debug(f"[流式请求] 保留工具结果数: {keep_tool_results_count}, 工具数: {len(combined_tools) if combined_tools else 0}")
        if combined_tools:
            tool_names = [t.get("function", {}).get("name", "?") for t in combined_tools[:5]]
            logging.debug(f"[流式请求] 工具列表(前5): {tool_names}")
        
        while iteration < max_iterations:
            # 替换历史工具结果
            replace_old_tool_results(messages_copy, tool_call_history, keep_tool_results_count)
            
            fixed_reasoning_count = self._normalize_assistant_reasoning_fields(messages_copy, model)
            if fixed_reasoning_count > 0:
                logging.debug(
                    f"[消息标准化] 已按字段 {self._get_outbound_reasoning_field(model)} "
                    f"标准化 {fixed_reasoning_count} 条 assistant 推理消息"
                )
            
            logging.info(f"[迭代 {iteration+1}/{max_iterations}] 开始 Chat ID: {chat_id}")
            
            try:
                logging.debug(f"[API请求] model={model}, messages_count={len(messages_copy)}, tools_count={len(combined_tools) if combined_tools else 0}")
                
                # 检查是否使用 XML 格式工具调用
                model_routes = config.get('model_routes', {})
                route_config = model_routes.get(model, model_routes.get('_default', {}))
                use_xml_tools = route_config.get('use_xml_tools', False)
                
                if use_xml_tools:
                    logging.debug(f"[XML工具模式] 不传 tools 参数")
                    combined_tools = None
                else:
                    # 添加 strict: true（deep copy 避免污染原始工具定义）
                    if combined_tools:
                        combined_tools = copy.deepcopy(combined_tools)
                        for tool in combined_tools:
                            if tool.get("type") == "function" and "function" in tool:
                                tool["function"]["strict"] = True
                                params = tool["function"].get("parameters", {})
                                if params.get("type") == "object" and "properties" in params:
                                    params["required"] = list(params["properties"].keys())
                                    params["additionalProperties"] = False
                
                # 准备额外参数
                extra_body = {}
                
                # 检查是否需要启用 thinking
                enable_thinking = route_config.get('enable_thinking', False)
                
                if enable_thinking:
                    if iteration > 0:
                        enable_thinking = False
                        logging.debug(f"[Thinking] 工具调用后禁用")
                    elif messages_copy:
                        last_msg = messages_copy[-1]
                        if isinstance(last_msg, dict) and last_msg.get('role') == 'assistant':
                            enable_thinking = False
                            logging.debug(f"[Thinking] 检测到 prefill，禁用")
                
                if enable_thinking:
                    extra_body['thinking'] = {"type": "enabled"}
                    if route_config.get('thinking_budget_tokens'):
                        extra_body['thinking']['budget_tokens'] = route_config.get('thinking_budget_tokens')
                    logging.debug(f"[Thinking] 已启用")
                
                stream_response = self.client.chat.completions.create(
                    model=model,
                    messages=messages_copy,
                    tools=combined_tools,
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body=extra_body if extra_body else None,
                    **kwargs
                )
            except Exception as api_error:
                logging.error(f"[API错误] {type(api_error).__name__}: {api_error}", exc_info=True)
                raise
            
            # 收集响应
            reasoning_content = ""
            content = ""
            tool_calls_data = {}
            finish_reason = None
            
            # 🔧 每次迭代只记录最后一个 usage，避免流式响应中重复累加
            iteration_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            
            # XML 工具调用拦截状态
            xml_tool_mode = False
            xml_buffer = ""
            pending_buffer = ""
            TOOL_CALL_PREFIX = "<<<tool_call>>>"
            has_sent_content = False
            
            first_chunk = True
            for chunk in safe_stream_iterator(stream_response, chat_id):
                if first_chunk:
                    logging.debug(f"[原始chunk] {chunk}")
                    first_chunk = False
                
                # 🔧 记录 usage（覆盖而非累加，只保留最后一个有效值）
                # 兼容 Claude 原生格式 (input_tokens/output_tokens) 和 OpenAI 格式 (prompt_tokens/completion_tokens)
                if hasattr(chunk, 'usage') and chunk.usage:
                    usage = chunk.usage
                    total_tokens = getattr(usage, 'total_tokens', 0) or 0
                    # 兼容两种格式
                    prompt_tokens = getattr(usage, 'prompt_tokens', 0) or getattr(usage, 'input_tokens', 0) or 0
                    completion_tokens = getattr(usage, 'completion_tokens', 0) or getattr(usage, 'output_tokens', 0) or 0
                    # 只有当有有效值时才覆盖
                    if total_tokens > 0 or prompt_tokens > 0 or completion_tokens > 0:
                        iteration_usage["prompt_tokens"] = prompt_tokens
                        iteration_usage["completion_tokens"] = completion_tokens
                        iteration_usage["total_tokens"] = total_tokens
                
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                chunk_finish_reason = chunk.choices[0].finish_reason
                
                if chunk_finish_reason:
                    finish_reason = chunk_finish_reason
                
                # 处理 reasoning_content (同时支持 reasoning 和 reasoning_content 字段)
                # Vercel 后端返回 reasoning，DeepSeek 返回 reasoning_content
                r_content = getattr(delta, 'reasoning_content', None) or getattr(delta, 'reasoning', None)
                if r_content:
                    reasoning_content += r_content
                    
                    if has_sent_content:
                        pass  # 忽略乱序的 reasoning
                    else:
                        chunk_data = {
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": client_response_model,
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "reasoning_content": r_content,
                                    "reasoning": r_content
                                },
                                "logprobs": None,
                                "finish_reason": None
                            }]
                        }
                        yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                
                # 处理 content
                if hasattr(delta, 'content') and delta.content:
                    new_content = delta.content
                    content += new_content
                    
                    # XML 工具调用拦截
                    if xml_tool_mode:
                        xml_buffer += new_content
                        
                        if "<<</tool_call>>>" in xml_buffer:
                            try:
                                name_match = re.search(r'name:\s*([^\s<\n]+)', xml_buffer)
                                tool_name = name_match.group(1).strip() if name_match else "unknown"
                                
                                args_match = re.search(r'arguments:\s*(.*?)(?:<<</tool_call>>>|$)', xml_buffer, re.DOTALL)
                                args_str = args_match.group(1).strip() if args_match else "{}"
                                
                                hint_text = f"\n`⚡ 调用工具: {tool_name}`\n```\n{args_str}\n```\n"
                                
                                chunk_data = {
                                    "id": chat_id,
                                    "object": "chat.completion.chunk",
                                    "created": created_time,
                                    "model": client_response_model,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"content": hint_text},
                                        "logprobs": None,
                                        "finish_reason": None
                                    }]
                                }
                                has_sent_content = True
                                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                            except Exception as e:
                                logging.warning(f"[XML工具调用提示] 解析失败: {e}")
                            
                            xml_tool_mode = False
                            xml_buffer = ""
                        
                        continue
                    
                    elif pending_buffer:
                        pending_buffer += new_content
                        
                        if TOOL_CALL_PREFIX in pending_buffer:
                            idx = pending_buffer.find(TOOL_CALL_PREFIX)
                            if idx > 0:
                                normal_part = pending_buffer[:idx]
                                has_sent_content = True
                                chunk_data = {
                                    "id": chat_id,
                                    "object": "chat.completion.chunk",
                                    "created": created_time,
                                    "model": client_response_model,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"content": normal_part},
                                        "logprobs": None,
                                        "finish_reason": None
                                    }]
                                }
                                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                            xml_tool_mode = True
                            xml_buffer = pending_buffer[idx:]
                            pending_buffer = ""
                            continue
                        
                        is_possible_prefix = TOOL_CALL_PREFIX.startswith(pending_buffer) or \
                                            pending_buffer.startswith(TOOL_CALL_PREFIX[:len(pending_buffer)])
                        
                        if not is_possible_prefix:
                            has_sent_content = True
                            chunk_data = {
                                "id": chat_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": client_response_model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": pending_buffer},
                                    "logprobs": None,
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                            pending_buffer = ""
                        
                        continue
                    
                    elif "<" in new_content:
                        idx = new_content.find("<")
                        
                        if idx > 0:
                            normal_part = new_content[:idx]
                            has_sent_content = True
                            chunk_data = {
                                "id": chat_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": client_response_model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": normal_part},
                                    "logprobs": None,
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                        
                        pending_buffer = new_content[idx:]
                        continue
                    
                    else:
                        has_sent_content = True
                        chunk_data = {
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": client_response_model,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": new_content},
                                "logprobs": None,
                                "finish_reason": None
                            }]
                        }
                        yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                
                # 处理 tool_calls
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    for tc in delta.tool_calls:
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
            
            # 流式结束，累加本次迭代的 usage 到总计
            if iteration_usage["total_tokens"] > 0 or iteration_usage["prompt_tokens"] > 0:
                logging.info(f"[Token消耗] Prompt: {iteration_usage['prompt_tokens']}, Completion: {iteration_usage['completion_tokens']}, Total: {iteration_usage['total_tokens']} (Chat ID: {chat_id})")
                total_usage["prompt_tokens"] += iteration_usage["prompt_tokens"]
                total_usage["completion_tokens"] += iteration_usage["completion_tokens"]
                total_usage["total_tokens"] += iteration_usage["total_tokens"]
            
            # 检查工具调用
            tool_calls_list = [tool_calls_data[i] for i in sorted(tool_calls_data.keys())] if tool_calls_data else None
            
            logging.debug(f"[流式响应] finish_reason={finish_reason}, content_len={len(content)}, reasoning_len={len(reasoning_content)}, tool_calls数={len(tool_calls_list) if tool_calls_list else 0}")
            
            if tool_calls_list:
                for tc in tool_calls_list:
                    args_str = tc['function']['arguments']
                    args_len = len(args_str)
                    try:
                        json.loads(args_str) if args_str else {}
                        json_valid = "✓"
                    except json.JSONDecodeError as e:
                        json_valid = f"✗ JSON解析失败: {e}"
                    
                    if args_len > 200:
                        logging.debug(f"  - 工具: {tc['function']['name']}, 参数长度: {args_len}, JSON: {json_valid}")
                    else:
                        logging.debug(f"  - 工具: {tc['function']['name']}, 参数: {args_str} (JSON: {json_valid})")
            
            # 如果没有工具调用
            if not tool_calls_list:
                final_chunk = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "logprobs": None,
                        "finish_reason": finish_reason or "stop"
                    }],
                    "usage": total_usage
                }
                yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
                
                logging.info(f"[请求结束] 原因: {finish_reason or 'stop'}, 总消耗: {total_usage} (Chat ID: {chat_id})")
                
                # 检查 XML 格式工具调用
                if content and ("<<<tool_call>>>" in content or "<tool_call>" in content):
                    xml_tool_calls = parse_xml_tool_calls(content)
                    if xml_tool_calls:
                        logging.info(f"[XML工具调用] 检测到 {len(xml_tool_calls)} 个")
                        
                        tool_results = []
                        for tc in xml_tool_calls:
                            tool_name = tc.get("name", "")
                            tool_args = tc.get("arguments", {})
                            
                            if is_memory_tool(tool_name) and self.memory_router:
                                logging.info(f"[XML记忆工具调用] {tool_name}")
                                logging.debug(f"[XML记忆工具调用] 参数: {json.dumps(tool_args, ensure_ascii=False)}")
                                
                                is_write = is_memory_write_tool(tool_name)
                                result = self.memory_router.execute_memory_tool(tool_name, tool_args, enable_write=is_write)
                                logging.info(f"[XML记忆工具结果] {result[:200]}..." if len(result) > 200 else f"[XML记忆工具结果] {result}")
                                tool_results.append(f"[{tool_name} 结果]\n{result}")
                        
                        if tool_results:
                            # 构建新消息继续调用
                            clean_content = content
                            clean_content = re.sub(r'<<<tool_call>>>.*?<<</tool_call>>>', '', clean_content, flags=re.DOTALL)
                            clean_content = re.sub(r'<tool_call>.*?</tool_call>', '', clean_content, flags=re.DOTALL)
                            clean_content = clean_content.strip()
                            
                            combined_content = ""
                            if reasoning_content:
                                combined_content = f"<think>{reasoning_content}</think>\n"
                            if clean_content:
                                combined_content += clean_content
                            
                            assistant_msg = {
                                "role": "assistant",
                                "content": combined_content if combined_content else "（调用工具中...）"
                            }
                            messages_copy.append(assistant_msg)
                            
                            tool_results_text = "\n\n".join(tool_results)
                            messages_copy.append({
                                "role": "user",
                                "content": f"[工具调用结果]\n\n{tool_results_text}\n\n请根据以上工具返回的信息继续回答。"
                            })
                            
                            logging.debug(f"[XML工具调用] 继续调用模型...")
                            iteration += 1
                            continue
                
                yield "data: [DONE]\n\n"
                return
            
            # 执行工具调用
            if tool_calls_list and execute_mcp_tools:
                mcp_tool_calls = []
                memory_tool_calls = []
                non_auto_tool_calls = []
                
                for tc in tool_calls_list:
                    tool_name = tc["function"]["name"]
                    if self.mcp_manager and self._is_mcp_tool(tool_name):
                        mcp_tool_calls.append(tc)
                    elif is_memory_tool(tool_name):
                        memory_tool_calls.append(tc)
                    else:
                        non_auto_tool_calls.append(tc)
                
                # 执行记忆工具
                if memory_tool_calls and self.memory_router:
                    tool_call_texts = []
                    for tc in memory_tool_calls:
                        name = tc["function"]["name"]
                        args_str = tc["function"]["arguments"]
                        logging.info(f"[记忆工具调用] Chat ID: {chat_id}, 工具: {name}, 参数: {args_str}")
                        tool_call_texts.append(format_tool_call_text(name, args_str))
                    
                    tools_text = "\n".join(tool_call_texts) + "\n"
                    
                    delta_key = "reasoning_content" if self._should_add_reasoning_content(model) else "content"
                    chunk_data = {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {delta_key: tools_text},
                            "logprobs": None,
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                    
                    # 构建 assistant 消息
                    combined_content = ""
                    if reasoning_content:
                        combined_content = f"<think>{reasoning_content}</think>\n"
                    if content:
                        combined_content += content
                    
                    assistant_msg = {
                        "role": "assistant",
                        "content": combined_content if combined_content else None,
                        "tool_calls": tool_calls_list
                    }
                    if self._should_add_reasoning_content(model):
                        assistant_msg["reasoning_content"] = reasoning_content or ""
                    messages_copy.append(assistant_msg)
                    
                    # 执行工具
                    for tc in memory_tool_calls:
                        try:
                            args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                        except json.JSONDecodeError:
                            args = {}
                        
                        is_write = is_memory_write_tool(tc["function"]["name"])
                        
                        logging.info(f"[记忆工具调用{'(写入)' if is_write else ''}] {tc['function']['name']}")
                        logging.debug(f"[记忆工具调用] 参数: {json.dumps(args, ensure_ascii=False)}")
                        
                        result = self.memory_router.execute_memory_tool(tc["function"]["name"], args, enable_write=is_write)
                        
                        logging.info(f"[记忆工具结果] {result[:200]}..." if len(result) > 200 else f"[记忆工具结果] {result}")
                        
                        tool_call_history.append(tc["id"])
                        messages_copy.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result
                        })
                    
                    iteration += 1
                    continue
                
                # 执行 MCP 工具
                if mcp_tool_calls and self.mcp_manager:
                    tool_call_texts = []
                    for tc in mcp_tool_calls:
                        name = tc["function"]["name"]
                        args_str = tc["function"]["arguments"]
                        logging.info(f"[工具调用计划] Chat ID: {chat_id}, 工具: {name}, 参数: {args_str}")
                        tool_call_texts.append(format_tool_call_text(name, args_str))
                    
                    tools_text_for_user = "\n".join(tool_call_texts) + "\n"
                    
                    delta_key = "reasoning_content" if self._should_add_reasoning_content(model) else "content"
                    chunk_data = {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {delta_key: tools_text_for_user},
                            "logprobs": None,
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                    
                    # 构建助手消息
                    combined_content = ""
                    if reasoning_content:
                        combined_content = f"<think>{reasoning_content}</think>\n"
                    if content:
                        combined_content += content
                    
                    assistant_msg = {
                        "role": "assistant",
                        "content": combined_content if combined_content else None,
                        "tool_calls": tool_calls_list
                    }
                    if self._should_add_reasoning_content(model):
                        assistant_msg["reasoning_content"] = reasoning_content or ""
                    
                    messages_copy.append(assistant_msg)
                    
                    for tc in mcp_tool_calls:
                        try:
                            args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                        except json.JSONDecodeError:
                            args = {}
                        
                        result = self._execute_mcp_tool(tc["function"]["name"], args)
                        
                        tool_call_history.append(tc["id"])
                        messages_copy.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result or "工具执行失败"
                        })
                    
                    iteration += 1
                    continue
                
                # 非自动执行的工具调用
                if non_auto_tool_calls:
                    final_chunk = {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {},
                            "logprobs": None,
                            "finish_reason": "tool_calls"
                        }],
                        "usage": total_usage
                    }
                    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
                    logging.info(f"[流式请求结束] 非MCP工具调用，总消耗: {total_usage}")
                    yield "data: [DONE]\n\n"
                    return
            
            # 有工具调用但不自动执行
            final_chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "logprobs": None,
                    "finish_reason": "tool_calls"
                }],
                "usage": total_usage
            }
            yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
            logging.info(f"[流式请求结束] 自动执行禁用，总消耗: {total_usage}")
            yield "data: [DONE]\n\n"
            return
        
        # 达到最大迭代次数
        error_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"content": "[达到最大工具调用迭代次数]"},
                "logprobs": None,
                "finish_reason": "length"
            }],
            "usage": total_usage
        }
        yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
        logging.info(f"[流式请求结束] 达到最大迭代次数，总消耗: {total_usage}")
        yield "data: [DONE]\n\n"
    
    def process_request(
        self,
        messages: List[Dict[str, Any]],
        model: str = "deepseek-reasoner",
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        execute_mcp_tools: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        处理非流式聊天补全请求
        
        Args:
            messages: 消息列表
            model: 模型名称
            tools: 工具列表
            stream: 是否流式（此方法仅处理非流式）
            execute_mcp_tools: 是否自动执行 MCP 工具调用
            **kwargs: 其他参数
            
        Returns:
            完整响应
        """
        config = get_config()
        
        # 合并 MCP 工具
        combined_tools = list(tools) if tools else []
        if self.mcp_manager:
            mcp_tools = self.mcp_manager.get_openai_tools()
            combined_tools.extend(mcp_tools)
        
        if not combined_tools:
            combined_tools = None
        
        messages_copy = [msg.copy() for msg in messages]
        iteration = 0
        max_iterations = config.get('max_iterations', 100)
        assistant_msg_index = None
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        
        logging.info(f"[请求开始] Chat ID: {chat_id}, 模型: {model}, 消息数: {len(messages_copy)}, 流式: False")
        
        tool_call_history = []
        keep_tool_results_count = config.get('keep_tool_results_count', 0)
        
        while iteration < max_iterations:
            replace_old_tool_results(messages_copy, tool_call_history, keep_tool_results_count)
            
            fixed_reasoning_count = self._normalize_assistant_reasoning_fields(messages_copy, model)
            if fixed_reasoning_count > 0:
                logging.debug(
                    f"[消息标准化] 已按字段 {self._get_outbound_reasoning_field(model)} "
                    f"标准化 {fixed_reasoning_count} 条 assistant 推理消息"
                )
            
            response = self.client.chat.completions.create(
                model=model,
                messages=messages_copy,
                tools=combined_tools,
                **kwargs
            )
            
            message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason
            
            # 累计 token 使用
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                total_usage["prompt_tokens"] += getattr(usage, 'prompt_tokens', 0)
                total_usage["completion_tokens"] += getattr(usage, 'completion_tokens', 0)
                total_usage["total_tokens"] += getattr(usage, 'total_tokens', 0)
                
                if hasattr(usage, 'prompt_tokens_details'):
                    if "prompt_tokens_details" not in total_usage:
                        total_usage["prompt_tokens_details"] = {"cached_tokens": 0}
                    total_usage["prompt_tokens_details"]["cached_tokens"] += getattr(usage.prompt_tokens_details, 'cached_tokens', 0)
                
                if hasattr(usage, 'completion_tokens_details'):
                    if "completion_tokens_details" not in total_usage:
                        total_usage["completion_tokens_details"] = {"reasoning_tokens": 0}
                    total_usage["completion_tokens_details"]["reasoning_tokens"] += getattr(usage.completion_tokens_details, 'reasoning_tokens', 0)
                
                if hasattr(usage, 'prompt_cache_hit_tokens'):
                    if "prompt_cache_hit_tokens" not in total_usage:
                        total_usage["prompt_cache_hit_tokens"] = 0
                    total_usage["prompt_cache_hit_tokens"] += getattr(usage, 'prompt_cache_hit_tokens', 0)
                
                if hasattr(usage, 'prompt_cache_miss_tokens'):
                    if "prompt_cache_miss_tokens" not in total_usage:
                        total_usage["prompt_cache_miss_tokens"] = 0
                    total_usage["prompt_cache_miss_tokens"] += getattr(usage, 'prompt_cache_miss_tokens', 0)
            
            # 支持两种字段名：reasoning_content (DeepSeek) 和 reasoning (Vercel)
            new_reasoning = getattr(message, 'reasoning_content', None) or getattr(message, 'reasoning', None) or ""
            new_content = message.content or ""
            new_tool_calls = message.tool_calls
            
            if iteration == 0:
                new_msg_dict = message_to_dict(message)
                messages_copy.append(new_msg_dict)
                assistant_msg_index = len(messages_copy) - 1
            else:
                merge_assistant_message(
                    messages_copy,
                    assistant_msg_index,
                    new_reasoning,
                    new_content,
                    new_tool_calls
                )
            
            # 如果没有工具调用
            if new_tool_calls is None:
                final_msg = messages_copy[assistant_msg_index]
                
                message_obj = {
                    "role": "assistant",
                    "content": final_msg.get("content", ""),
                    "reasoning_content": final_msg.get("reasoning_content", "")
                }
                
                result = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "message": message_obj,
                        "logprobs": None,
                        "finish_reason": finish_reason
                    }],
                    "usage": total_usage
                }
                
                if hasattr(response, 'system_fingerprint'):
                    result["system_fingerprint"] = response.system_fingerprint
                
                return result
            
            # 执行 MCP 工具
            if new_tool_calls and execute_mcp_tools and self.mcp_manager:
                mcp_tool_calls = []
                non_mcp_tool_calls = []
                
                for tc in new_tool_calls:
                    if self._is_mcp_tool(tc.function.name):
                        mcp_tool_calls.append(tc)
                    else:
                        non_mcp_tool_calls.append(tc)
                
                if mcp_tool_calls:
                    for tc in mcp_tool_calls:
                        try:
                            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                        except json.JSONDecodeError:
                            args = {}
                        
                        result = self._execute_mcp_tool(tc.function.name, args)
                        
                        tool_call_history.append(tc.id)
                        messages_copy.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result or "工具执行失败"
                        })
                    
                    iteration += 1
                    continue
                
                # 返回非 MCP 工具调用
                if non_mcp_tool_calls:
                    final_msg = messages_copy[assistant_msg_index]
                    
                    message_obj = {
                        "role": "assistant",
                        "content": final_msg.get("content", ""),
                        "reasoning_content": final_msg.get("reasoning_content", ""),
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "function": {
                                    "arguments": tc.function.arguments,
                                    "name": tc.function.name
                                },
                                "type": tc.type,
                                "index": tc.index if hasattr(tc, 'index') else i
                            }
                            for i, tc in enumerate(non_mcp_tool_calls)
                        ]
                    }
                    
                    result = {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "message": message_obj,
                            "logprobs": None,
                            "finish_reason": "tool_calls"
                        }],
                        "usage": total_usage
                    }
                    
                    if hasattr(response, 'system_fingerprint'):
                        result["system_fingerprint"] = response.system_fingerprint
                    
                    return result
            
            # 返回工具调用请求
            final_msg = messages_copy[assistant_msg_index]
            
            message_obj = {
                "role": "assistant",
                "content": final_msg.get("content", ""),
                "reasoning_content": final_msg.get("reasoning_content", ""),
                "tool_calls": final_msg.get("tool_calls", [])
            }
            
            result = {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": message_obj,
                    "logprobs": None,
                    "finish_reason": "tool_calls"
                }],
                "usage": total_usage
            }
            
            if hasattr(response, 'system_fingerprint'):
                result["system_fingerprint"] = response.system_fingerprint
            
            return result
        
        # 达到最大迭代次数
        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "达到最大迭代次数"
                },
                "finish_reason": "length"
            }],
            "usage": total_usage
        }
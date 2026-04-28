"""
聊天补全路由

处理 /v1/chat/completions 请求
"""

import json
import sys
import logging
import uuid
import time
from flask import Blueprint, request, jsonify, Response, stream_with_context

from ..config import get_config
from ..auth import validate_access_key
from ..deepseek_proxy import DeepSeekProxy
from ..think_parser import StreamThinkParser
from ..image_captioner import maybe_caption_images

# 全局变量（由主模块设置）
mcp_manager = None
memory_router = None
MEMORY_AVAILABLE = False

# DeepSeekProxy 实例缓存 (key → DeepSeekProxy)
# key = (api_key, base_url, use_mcp, use_memory)
_proxy_cache: dict = {}
_PROXY_CACHE_MAX_SIZE = 32

chat_bp = Blueprint('chat', __name__)


def set_managers(mcp_mgr, mem_router, mem_available):
    """设置全局管理器（由主模块调用）"""
    global mcp_manager, memory_router, MEMORY_AVAILABLE
    mcp_manager = mcp_mgr
    memory_router = mem_router
    MEMORY_AVAILABLE = mem_available


@chat_bp.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    """处理聊天补全请求"""
    global mcp_manager, memory_router, MEMORY_AVAILABLE
    
    config = get_config()
    
    try:
        data = request.get_json()
        
        # 保存原始消息（用于对话后总结，避免伪造消息被计入）
        original_messages_for_summary = data.get('messages', [])
        
        # 验证访问密钥
        auth_header = request.headers.get('Authorization', '')
        is_valid, api_key, error_msg = validate_access_key(auth_header)
        if not is_valid:
            return jsonify({"error": {"message": error_msg, "type": "auth_error"}}), 401
        
        # 提取参数
        messages = data.get('messages', [])
        model = data.get('model')
        
        if not model:
            return jsonify({"error": {"message": "Missing required parameter: model", "type": "invalid_request_error"}}), 400
        
        # 记忆系统路由
        memory_tools_for_request = []
        use_mcp_for_this_request = True
        route_result = None
        is_memory_mode = False
        is_record_mode = False  # 只记录不检索模式（触发总结）
        is_log_mode = False  # 日志模式（只记录原始对话，不触发总结）
        
        stream = data.get('stream', False)
        
        if MEMORY_AVAILABLE and memory_router and config.get("memory_enabled", True):
            route_result = memory_router.route(model)
            
            if route_result.mode == "memory":
                use_mcp_for_this_request = False
                is_memory_mode = True
                logging.info(f"[记忆模式] {model} -> 检索记忆 + {route_result.base_model} (MCP已禁用)")
                
                if not stream:
                    try:
                        enhanced_messages, memory_tools, agent_result = memory_router.process_memory_request(
                            messages=messages,
                            route_result=route_result,
                            user_api_key=api_key
                        )
                        messages = enhanced_messages
                        
                        if route_result.enable_main_model_tools and memory_tools:
                            memory_tools_for_request = memory_tools
                        
                        model = route_result.base_model
                        
                    except Exception as e:
                        logging.error(f"[记忆检索失败] {e}", exc_info=True)
                        is_memory_mode = False
                else:
                    model = route_result.base_model
            
            elif route_result.mode == "record":
                # 只记录模式：注入固定记忆，但不调用Agent检索，对话后触发总结
                use_mcp_for_this_request = True  # 允许使用MCP
                is_record_mode = True
                model = route_result.base_model
                logging.info(f"[记录模式] {model} -> 注入固定记忆（无Agent检索） + 对话后总结")
                
                # 注入固定记忆（短期日记、周总结等）
                try:
                    built = memory_router.context_builder.build(
                        messages=messages,
                        dynamic_memory="",  # 无动态检索结果
                        include_fixed=True,  # 包含固定记忆
                        model_name=route_result.base_model  # 传递模型名以支持条件挂载
                    )
                    messages = built.messages
                    logging.debug(f"[记录模式] 注入固定记忆，字符数: {built.total_chars}")
                    
                    # build 之后更新上次交互时间
                    memory_router.metadata_manager.update_last_interaction()
                    
                    # 检查并应用预填充
                    try:
                        from memory_agent.message_orchestrator import get_orchestrator
                        from pathlib import Path
                        lifebook_path = config.get('lifebook', {}).get('root_path', './lifebook')
                        config_dir = Path(lifebook_path) / "extra"
                        orchestrator = get_orchestrator(config_dir)
                        
                        if orchestrator.should_use_prefill(model):
                            prefill_content = orchestrator.get_prefill_content()
                            if prefill_content:
                                # 在消息末尾插入预填充 assistant 消息
                                messages = list(messages)
                                messages.append({
                                    "role": "assistant",
                                    "content": prefill_content
                                })
                                logging.info(f"[预填充] 已插入 assistant 预填充消息 ({len(prefill_content)} 字符)")
                    except Exception as e:
                        logging.debug(f"[预填充] 检查预填充配置失败: {e}")
                        
                except Exception as e:
                    logging.warning(f"[记录模式] 注入固定记忆失败: {e}")
            
            elif route_result.mode == "log-write":
                # 日志写入模式：注入固定记忆，不调用Agent检索，主模型可调用记忆读写工具，对话后只记录原始对话
                use_mcp_for_this_request = True  # 保持 log 模式行为，允许使用MCP
                is_memory_mode = True  # 让代理层能够执行记忆工具
                is_log_mode = True     # 复用 log 模式的“只记录不总结”逻辑
                model = route_result.base_model
                logging.info(f"[日志写入模式] {model} -> 注入固定记忆（无Agent检索） + 主模型记忆读写工具 + 仅记录原始对话")
                
                try:
                    built = memory_router.context_builder.build(
                        messages=messages,
                        dynamic_memory="",  # 无动态检索结果
                        include_fixed=True,  # 包含固定记忆
                        model_name=route_result.base_model  # 传递模型名以支持条件挂载
                    )
                    messages = built.messages
                    logging.debug(f"[日志写入模式] 注入固定记忆，字符数: {built.total_chars}")
                    
                    # build 之后更新上次交互时间
                    memory_router.metadata_manager.update_last_interaction()
                    
                    # 给主模型挂载记忆读写工具
                    if route_result.enable_main_model_tools:
                        memory_tools_for_request = memory_router.memory_tools_write.get_openai_tools(include_write=True)
                        if memory_tools_for_request:
                            has_graphiti_tools = any(
                                t.get("function", {}).get("name", "").startswith("graphiti_")
                                for t in memory_tools_for_request
                            )
                            tools_hint = memory_router.context_builder.get_memory_tools_prompt(
                                enable_write=True,
                                custom_hint=memory_router.main_model_tools_hint,
                                include_graphiti=has_graphiti_tools,
                                use_xml_tools=memory_router.get_actual_model_config(route_result.base_model).get("use_xml_tools", False)
                            )
                            messages = memory_router._add_tools_hint_to_messages(messages, tools_hint)
                    
                    # 检查并应用预填充
                    try:
                        from memory_agent.message_orchestrator import get_orchestrator
                        from pathlib import Path
                        lifebook_path = config.get('lifebook', {}).get('root_path', './lifebook')
                        config_dir = Path(lifebook_path) / "extra"
                        orchestrator = get_orchestrator(config_dir)
                        
                        if orchestrator.should_use_prefill(model):
                            prefill_content = orchestrator.get_prefill_content()
                            if prefill_content:
                                # 在消息末尾插入预填充 assistant 消息
                                messages = list(messages)
                                messages.append({
                                    "role": "assistant",
                                    "content": prefill_content
                                })
                                logging.info(f"[预填充] 已插入 assistant 预填充消息 ({len(prefill_content)} 字符)")
                    except Exception as e:
                        logging.debug(f"[预填充] 检查预填充配置失败: {e}")
                        
                except Exception as e:
                    logging.warning(f"[日志写入模式] 注入固定记忆失败: {e}")
            
            elif route_result.mode == "log":
                # 日志模式：注入固定记忆，但不调用Agent检索，对话后只记录原始对话（不触发总结）
                use_mcp_for_this_request = True  # 允许使用MCP
                is_log_mode = True
                model = route_result.base_model
                logging.info(f"[日志模式] {model} -> 注入固定记忆（无Agent检索） + 仅记录原始对话")
                
                # 注入固定记忆（短期日记、周总结等）
                try:
                    built = memory_router.context_builder.build(
                        messages=messages,
                        dynamic_memory="",  # 无动态检索结果
                        include_fixed=True,  # 包含固定记忆
                        model_name=route_result.base_model  # 传递模型名以支持条件挂载
                    )
                    messages = built.messages
                    logging.debug(f"[日志模式] 注入固定记忆，字符数: {built.total_chars}")
                    
                    # build 之后更新上次交互时间
                    memory_router.metadata_manager.update_last_interaction()
                    
                    # 检查并应用预填充
                    try:
                        from memory_agent.message_orchestrator import get_orchestrator
                        from pathlib import Path
                        lifebook_path = config.get('lifebook', {}).get('root_path', './lifebook')
                        config_dir = Path(lifebook_path) / "extra"
                        orchestrator = get_orchestrator(config_dir)
                        
                        if orchestrator.should_use_prefill(model):
                            prefill_content = orchestrator.get_prefill_content()
                            if prefill_content:
                                # 在消息末尾插入预填充 assistant 消息
                                messages = list(messages)
                                messages.append({
                                    "role": "assistant",
                                    "content": prefill_content
                                })
                                logging.info(f"[预填充] 已插入 assistant 预填充消息 ({len(prefill_content)} 字符)")
                    except Exception as e:
                        logging.debug(f"[预填充] 检查预填充配置失败: {e}")
                        
                except Exception as e:
                    logging.warning(f"[日志模式] 注入固定记忆失败: {e}")
            
            elif route_result.mode == "manager":
                use_mcp_for_this_request = False
                is_memory_mode = True  # 启用记忆工具执行！
                logging.info(f"[管理模式] {model} -> 记忆管理 (MCP已禁用)")
                
                try:
                    enhanced_messages, memory_tools = memory_router.process_manager_request(messages)
                    messages = enhanced_messages
                    memory_tools_for_request = memory_tools
                    model = route_result.base_model
                except Exception as e:
                    logging.error(f"[记忆管理初始化失败] {e}", exc_info=True)
        
        # 预处理消息
        messages = [msg.copy() if isinstance(msg, dict) else msg for msg in messages]
        
        # 角色修正：非首条 System -> User
        system_convert_count = 0
        for i in range(1, len(messages)):
            if isinstance(messages[i], dict) and messages[i].get('role') == 'system':
                messages[i]['role'] = 'user'
                system_convert_count += 1
        
        if system_convert_count > 0:
            logging.debug(f"[角色修正] 已将 {system_convert_count} 条中间 System 消息转换为 User 消息")
        
        # 检查是否需要 reasoning_content
        model_routes = config.get('model_routes', {})
        route_config = model_routes.get(model, model_routes.get('_default', {}))
        actual_model = route_config.get('actual_model', model) if route_config else model

        # Non-vision fallback: convert images to text when needed
        try:
            messages, _ = maybe_caption_images(
                messages=messages,
                model=actual_model,
                route_config=route_config,
                config=config,
                api_key=api_key or ""
            )
        except Exception as e:
            logging.warning(f"[ImageFallback] failed: {e}")
        
        thinking_mode = route_config.get('thinking_mode') if route_config else None
        needs_reasoning_content = False
        
        if thinking_mode is not None:
            if thinking_mode is True:
                needs_reasoning_content = True
            elif thinking_mode is False:
                needs_reasoning_content = False
            elif thinking_mode == "auto":
                needs_reasoning_content = "deepseek" in actual_model.lower() or "reasoner" in actual_model.lower()
        else:
            thinking_config = config.get("deepseek_thinking_mode", {})
            if thinking_config.get("enabled", True):
                if thinking_config.get("auto_detect", True):
                    needs_reasoning_content = "deepseek" in actual_model.lower() or "reasoner" in actual_model.lower()
                else:
                    needs_reasoning_content = True
        
        enable_thinking = route_config.get('enable_thinking', False) if route_config else False
        
        if enable_thinking and messages:
            last_msg = messages[-1]
            if isinstance(last_msg, dict) and last_msg.get('role') == 'assistant':
                enable_thinking = False
                logging.debug(f"[Claude Thinking] 检测到 prefill，禁用 thinking 模式")
        
        # 处理 assistant 消息
        fixed_count = 0
        removed_count = 0
        content_fixed_count = 0
        assistant_count = 0
        
        for i, msg in enumerate(messages):
            if isinstance(msg, dict) and msg.get('role') == 'assistant':
                assistant_count += 1
                
                if needs_reasoning_content:
                    # thinking 模式：确保 assistant 具有标准字段 reasoning_content
                    # 若客户端只回传了 reasoning（别名），迁移到 reasoning_content
                    if 'reasoning_content' not in msg or msg.get('reasoning_content') is None:
                        alias_reasoning = msg.get('reasoning')
                        messages[i]['reasoning_content'] = alias_reasoning if isinstance(alias_reasoning, str) else ''
                        fixed_count += 1
                    
                    # 清理非标准别名，避免上游校验歧义
                    if 'reasoning' in messages[i]:
                        del messages[i]['reasoning']
                else:
                    if 'reasoning_content' in msg:
                        if not msg.get('content'):
                            messages[i]['content'] = msg['reasoning_content']
                            content_fixed_count += 1
                        del messages[i]['reasoning_content']
                        removed_count += 1
                    
                    # 非 thinking 模式也移除别名字段
                    if 'reasoning' in messages[i]:
                        del messages[i]['reasoning']
        
        if fixed_count > 0:
            logging.debug(f"[消息补全] 为 {fixed_count} 条 Assistant 消息补充 reasoning_content 字段")
        if removed_count > 0:
            logging.debug(f"[消息清理] 从 {removed_count} 条 Assistant 消息移除 reasoning_content 字段")
        
        # Prefill 转换
        converted_count = 0
        if needs_reasoning_content and messages:
            last_msg_index = len(messages) - 1
            last_msg = messages[last_msg_index]
            
            if isinstance(last_msg, dict) and last_msg.get('role') == 'assistant':
                if 'content' in last_msg and last_msg['content']:
                    content_len = len(last_msg['content'])
                    current_reasoning = last_msg.get('reasoning_content', '')
                    new_reasoning = (current_reasoning + "\n" + last_msg['content']).strip()
                    messages[last_msg_index]['reasoning_content'] = new_reasoning
                    messages[last_msg_index]['content'] = ''
                    converted_count += 1
                    logging.debug(f"[Prefill 转换] 已将 content ({content_len} 字符) 移至 reasoning_content")
        
        # 记录消息摘要
        logging.debug(f"[消息摘要] 准备发送 {len(messages)} 条消息")
        for i, msg in enumerate(messages):
            if isinstance(msg, dict):
                role = msg.get('role', 'unknown')
                content_len = len(msg.get('content') or '')
                reasoning_len = len(msg.get('reasoning_content') or '')
                tool_calls_count = len(msg.get('tool_calls') or [])
                logging.debug(f"  [{i}] {role}: content={content_len} chars, reasoning={reasoning_len} chars, tools={tool_calls_count}")
        
        # 添加系统提示词
        # 注意：-record 和 -log 模式不需要工具调用相关的系统提示词（因为不使用工具）
        should_add_system_prompt = config.get('system_prompt_enabled', False) and not is_record_mode and not is_log_mode
        if should_add_system_prompt:
            system_prompt = config.get('system_prompt', '')
            if system_prompt:
                if messages and messages[0].get('role') == 'system':
                    messages = messages.copy()
                    messages[0] = messages[0].copy()
                    messages[0]['content'] = system_prompt + "\n\n" + messages[0]['content']
                else:
                    messages = [{"role": "system", "content": system_prompt}] + messages
        
        # 合并工具
        tools = data.get('tools') or []
        if memory_tools_for_request:
            tools = list(tools) + memory_tools_for_request
        if not tools:
            tools = None
        
        execute_mcp_tools = data.get('execute_mcp_tools', config.get('auto_execute_mcp_tools', True))
        
        # 其他参数
        kwargs = {}
        for key in ['temperature', 'top_p', 'max_tokens', 'presence_penalty', 'frequency_penalty']:
            if key in data:
                kwargs[key] = data[key]
        
        # 获取路由配置
        effective_base_url = route_config.get('base_url') if route_config else None
        effective_api_key = route_config.get('api_key') or api_key
        actual_model = route_config.get('actual_model', model) if route_config else model
        
        if effective_base_url:
            logging.info(f"[模型路由] {model} -> {actual_model} @ {effective_base_url}")
        
        # 获取或创建代理（复用连接池）
        effective_mcp = mcp_manager if use_mcp_for_this_request else None
        effective_memory = memory_router if is_memory_mode else None
        cache_key = (effective_api_key, effective_base_url, id(effective_mcp), id(effective_memory))
        proxy = _proxy_cache.get(cache_key)
        if proxy is None:
            proxy = DeepSeekProxy(effective_api_key, effective_mcp, effective_base_url, effective_memory)
            # 简单 LRU：超过最大缓存数时清空
            if len(_proxy_cache) >= _PROXY_CACHE_MAX_SIZE:
                _proxy_cache.clear()
            _proxy_cache[cache_key] = proxy
        
        model = actual_model
        
        # 流式响应
        if stream:
            final_messages = messages
            final_tools = tools
            final_model = model
            
            # 检查是否需要使用预填充解析器
            use_prefill_parser = False
            prefill_think_tag = "</think>"
            
            if MEMORY_AVAILABLE and memory_router:
                try:
                    from memory_agent.message_orchestrator import get_orchestrator
                    from pathlib import Path
                    lifebook_path = config.get('lifebook', {}).get('root_path', './lifebook')
                    config_dir = Path(lifebook_path) / "extra"
                    orchestrator = get_orchestrator(config_dir)
                    
                    # 检查是否为该模型启用了预填充
                    if orchestrator.should_use_prefill(model):
                        use_prefill_parser = True
                        prefill_think_tag = orchestrator.get_think_tag()
                        logging.info(f"[预填充] 启用流式解析器，think_tag={prefill_think_tag}")
                except Exception as e:
                    logging.debug(f"[预填充] 检查预填充配置失败: {e}")
            
            def generate():
                nonlocal final_messages, final_tools, final_model
                
                chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
                created_time = int(time.time())
                collected_content = []
                collected_reasoning = []
                
                # 创建预填充解析器
                think_parser = StreamThinkParser(prefill_think_tag) if use_prefill_parser else None
                
                try:
                    # 记忆增强模式：流式输出 Agent 思考
                    # 注意：只有 memory 模式需要流式检索，manager 模式已在前面同步处理
                    if route_result and route_result.mode == "memory":
                        logging.info(f"[流式记忆检索] 开始...")
                        
                        for event in memory_router.process_memory_request_stream(
                            messages=final_messages,
                            route_result=route_result,
                            user_api_key=api_key
                        ):
                            event_type = event.get("type")
                            
                            if event_type == "reasoning":
                                reasoning_text = event.get("content", "")
                                if reasoning_text:
                                    chunk_data = {
                                        "id": chat_id,
                                        "object": "chat.completion.chunk",
                                        "created": created_time,
                                        "model": final_model,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"reasoning_content": reasoning_text},
                                            "logprobs": None,
                                            "finish_reason": None
                                        }]
                                    }
                                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                            
                            elif event_type == "final":
                                final_messages = event.get("messages", final_messages)
                                final_tools = event.get("tools", [])
                                
                                if route_result.enable_main_model_tools and final_tools:
                                    user_tools = data.get('tools') or []
                                    final_tools = list(user_tools) + final_tools
                                else:
                                    final_tools = data.get('tools') or []
                                
                                if not final_tools:
                                    final_tools = None
                                
                                logging.info(f"[流式记忆检索] 完成，开始调用主模型...")
                    
                    # 调用主模型
                    logging.debug(f"[调试] 准备调用主模型 {final_model}，消息数: {len(final_messages)}")
                    
                    for chunk in proxy.process_request_stream(
                        messages=final_messages,
                        model=final_model,
                        tools=final_tools,
                        execute_mcp_tools=execute_mcp_tools,
                        **kwargs
                    ):
                        # 解析 chunk
                        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                            try:
                                chunk_json = chunk[6:].strip()
                                if chunk_json:
                                    chunk_data = json.loads(chunk_json)
                                    
                                    # 处理预填充解析
                                    if think_parser and "choices" in chunk_data and chunk_data["choices"]:
                                        delta = chunk_data["choices"][0].get("delta", {})
                                        original_content = delta.get("content", "")
                                        original_reasoning = delta.get("reasoning_content", "")
                                        
                                        # 只有当没有原生 reasoning_content 时才解析 content
                                        if original_content and not original_reasoning:
                                            reasoning_part, content_part = think_parser.process(original_content)
                                            
                                            # 重构 delta
                                            new_delta = {}
                                            if reasoning_part:
                                                new_delta["reasoning_content"] = reasoning_part
                                                collected_reasoning.append(reasoning_part)
                                            if content_part:
                                                new_delta["content"] = content_part
                                                collected_content.append(content_part)
                                            
                                            if new_delta:
                                                chunk_data["choices"][0]["delta"] = new_delta
                                                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                                            continue
                                    
                                    # 记忆模式、记录模式、日志模式都需要收集内容
                                    if is_memory_mode or is_record_mode or is_log_mode:
                                        if "choices" in chunk_data and chunk_data["choices"]:
                                            delta = chunk_data["choices"][0].get("delta", {})
                                            if "content" in delta and delta["content"]:
                                                collected_content.append(delta["content"])
                                            if "reasoning_content" in delta and delta["reasoning_content"]:
                                                collected_reasoning.append(delta["reasoning_content"])
                            except (json.JSONDecodeError, KeyError, IndexError):
                                pass
                        
                        yield chunk
                    
                    # 刷新预填充解析器的残余内容
                    if think_parser:
                        r, c = think_parser.flush()
                        if r:
                            collected_reasoning.append(r)
                            chunk_data = {
                                "id": chat_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": final_model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"reasoning_content": r},
                                    "logprobs": None,
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                        if c:
                            collected_content.append(c)
                            chunk_data = {
                                "id": chat_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": final_model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": c},
                                    "logprobs": None,
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                    
                    # 对话处理（日志在 summarize_and_save 内部输出，这里不重复）
                    # 记忆模式、记录模式、日志模式都需要记录原始对话
                    # 注意：传入原始消息而非编排后的消息，避免伪造消息被计入用户消息数
                    if (is_memory_mode or is_record_mode or is_log_mode) and memory_router and collected_content:
                        full_content = "".join(collected_content)
                        full_reasoning = "".join(collected_reasoning)
                        if full_content.strip():
                            # 1. 记录原始对话（Phase 2）- 所有模式都记录
                            memory_router.log_conversation(
                                messages=original_messages_for_summary,
                                model=final_model,
                                response=full_content,
                                user_key=api_key or "default",
                                metadata={
                                    "reasoning_content": full_reasoning,
                                    "stream": True
                                }
                            )
                            
                            # 2. 触发对话总结 - 只有 memory 和 record 模式触发，log 模式跳过
                            if not is_log_mode:
                                memory_router.summarize_and_save(
                                    messages=original_messages_for_summary,
                                    response_content=full_content,
                                    async_mode=True,
                                    main_model_reasoning=full_reasoning
                                )
                    
                except Exception as e:
                    logging.error(f"[流式请求异常] {e}", exc_info=True)
                    error_chunk = {
                        "error": {
                            "message": str(e),
                            "type": "server_error",
                            "code": "internal_error"
                        }
                    }
                    yield f"data: {json.dumps(error_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
            
            return Response(
                stream_with_context(generate()),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                    'X-Accel-Buffering': 'no'
                }
            )
        
        # 非流式响应
        response = proxy.process_request(
            messages=messages,
            model=model,
            tools=tools,
            stream=False,
            execute_mcp_tools=execute_mcp_tools,
            **kwargs
        )
        
        if response and "usage" in response and response["usage"]:
            logging.info(f"[Tokens] Total usage: {response['usage']}")
        
        # 非流式处理（记忆模式、记录模式、日志模式都需要记录）
        # 注意：传入原始消息而非编排后的消息，避免伪造消息被计入用户消息数
        if (is_memory_mode or is_record_mode or is_log_mode) and memory_router and response and "choices" in response:
            try:
                msg = response["choices"][0].get("message", {})
                content = msg.get("content", "")
                reasoning = msg.get("reasoning_content", "")
                if content:
                    # 1. 记录原始对话（Phase 2）- 所有模式都记录
                    memory_router.log_conversation(
                        messages=original_messages_for_summary,
                        model=model,
                        response=content,
                        user_key=api_key or "default",
                        metadata={
                            "reasoning_content": reasoning or "",
                            "stream": False,
                            "tokens": response.get("usage", {})
                        }
                    )
                    
                    # 2. 触发对话总结 - 只有 memory 和 record 模式触发，log 模式跳过
                    if not is_log_mode:
                        memory_router.summarize_and_save(
                            messages=original_messages_for_summary,
                            response_content=content,
                            async_mode=True,
                            main_model_reasoning=reasoning
                        )
            except Exception as e:
                logging.warning(f"[非流式处理失败] {e}")
        
        return jsonify(response)
    
    except Exception as e:
        logging.error(f"[请求处理失败] {e}", exc_info=True)
        return jsonify({
            "error": {
                "message": str(e),
                "type": "server_error",
                "code": "internal_error"
            }
        }), 500

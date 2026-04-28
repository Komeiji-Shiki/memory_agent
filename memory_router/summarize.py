"""
Conversation Summarizer - 对话后总结模块

处理对话总结、节点操作和暂存管理。
"""

import json
import re
import time
import logging
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

import httpx
from openai import OpenAI

from memory_store.pending_manager import PendingManager, create_pending_summary


class ConversationSummarizer:
    """对话总结器"""
    
    def __init__(self, config: Dict[str, Any], lifebook_path: str, encoding: str = "utf-8"):
        self.config = config
        self.lifebook_path = lifebook_path
        self.encoding = encoding
        
        # 总结配置
        post_config = config.get("post_conversation", {})
        self.enabled = post_config.get("enabled", False) and post_config.get("auto_summarize", False)
        self.summarize_model = post_config.get("summarize_model", "deepseek-chat")
        self.summarize_prompt = post_config.get("summarize_prompt", "")
        self.summarize_suffix = post_config.get("summarize_suffix", "")
        self.min_messages = post_config.get("min_messages", 2)
        self.pending_preview_max_chars = post_config.get("pending_preview_max_chars", 200)
        self.cache_ttl = post_config.get("cache_ttl", 3600)
        
        # post_conversation 单独设置的 API 配置（最高优先级）
        self.post_base_url = post_config.get("base_url", "")
        self.post_api_key = post_config.get("api_key", "")
        
        # 高级 LLM 参数配置
        self.max_tokens = post_config.get("max_tokens", None)  # None 表示使用自动判断
        self.max_tokens_reasoner = post_config.get("max_tokens_reasoner", 3000)  # reasoner 模型默认值
        self.max_tokens_normal = post_config.get("max_tokens_normal", 1500)  # 普通模型默认值
        self.temperature = post_config.get("temperature", 0.3)
        self.top_p = post_config.get("top_p", None)  # None 表示不设置
        self.max_context_chars = post_config.get("max_context_chars", 100000)  # 最大上下文字符数
        
        # API 配置
        self.api_key = config.get("api_key", "")
        self.memory_agent_config = config.get("memory_agent", {})
        
        # 缓存
        self._last_conversation: Optional[Tuple] = None
    
    def summarize_and_save(
        self,
        messages: List[Dict[str, Any]],
        response_content: str,
        async_mode: bool = True,
        main_model_reasoning: Optional[str] = None,
        memory_tools_write: Optional[Any] = None
    ) -> Optional[str]:
        """
        对话后总结并暂存
        
        Args:
            messages: 原始对话消息
            response_content: 主模型的回复内容
            async_mode: 是否异步执行
            main_model_reasoning: 主模型的思考过程
            memory_tools_write: 可写的记忆工具实例
            
        Returns:
            如果同步执行，返回总结内容；异步执行返回None
        """
        if not self.enabled:
            return None
        
        # 检查消息数量
        user_messages = [m for m in messages if m.get("role") == "user"]
        if len(user_messages) < self.min_messages:
            logging.info(f"[对话总结] ⏭️ 跳过 - 消息数不足 ({len(user_messages)} < {self.min_messages})")
            return None
        
        logging.info(f"[对话总结] 准备总结 (用户消息数: {len(user_messages)})")
        
        # 缓存对话
        m_reasoning = main_model_reasoning or ""
        self._last_conversation = (messages, response_content, m_reasoning, time.time())
        
        if async_mode:
            def _thread_wrapper():
                try:
                    self._do_summarize(messages, response_content, m_reasoning, memory_tools_write)
                except Exception as e:
                    logging.error(f"[对话总结-异步] 线程执行出错: {e}", exc_info=True)
            
            thread = threading.Thread(target=_thread_wrapper, daemon=True)
            thread.start()
            return None
        else:
            return self._do_summarize(messages, response_content, m_reasoning, memory_tools_write)
    
    def _do_summarize(
        self,
        messages: List[Dict[str, Any]],
        response_content: str,
        main_model_reasoning: str,
        memory_tools_write: Optional[Any]
    ) -> Optional[str]:
        """执行总结"""
        try:
            # 构建对话文本
            conversation_text = self._format_conversation(messages, response_content, main_model_reasoning)
            
            # 获取 API 配置
            model_config = self._get_model_config()
            api_key = model_config.get("api_key", "")
            base_url = model_config.get("base_url", "https://api.deepseek.com/v1")
            
            # 创建客户端
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=httpx.Client(proxy=None)
            )
            
            # 定义工具
            summary_tools = self._get_summary_tools()
            
            # 获取已存在的摘要
            existing_summaries = self._get_existing_summaries()
            
            # 构建提示词
            user_message = self._build_prompt(existing_summaries, conversation_text)
            
            # 调用模型
            is_reasoner = "reasoner" in self.summarize_model.lower()
            
            # 计算 max_tokens
            if self.max_tokens is not None:
                max_tokens = self.max_tokens
            else:
                max_tokens = self.max_tokens_reasoner if is_reasoner else self.max_tokens_normal
            
            # 构建请求参数
            request_params = {
                "model": self.summarize_model,
                "messages": [{"role": "user", "content": user_message}],
                "tools": summary_tools,
                "tool_choice": "auto",
                "max_tokens": max_tokens,
                "temperature": self.temperature
            }
            
            # 可选参数：top_p
            if self.top_p is not None:
                request_params["top_p"] = self.top_p
            
            response = client.chat.completions.create(**request_params)
            
            # 处理结果
            return self._process_response(response, messages, memory_tools_write)
            
        except Exception as e:
            error_str = str(e)
            if "Content Exists Risk" in error_str or "content_filter" in error_str.lower():
                logging.warning(f"[对话总结] ⚠️ 内容因敏感被屏蔽，跳过本次记录")
                return None
            
            logging.error(f"[对话总结] 出错: {e}", exc_info=True)
            return None
    
    def _get_model_config(self) -> Dict[str, str]:
        """
        获取总结模型配置
        
        优先级（从高到低）：
        1. post_conversation 中单独设置的 base_url/api_key（如果非空）
        2. model_routes 中对应模型的配置
        3. memory_agent 的配置
        4. 主 api_key
        """
        # 1. 优先使用 post_conversation 中单独设置的值
        if self.post_base_url and self.post_api_key:
            logging.debug(f"[对话总结] 使用 post_conversation 单独配置的 API")
            return {
                "api_key": self.post_api_key,
                "base_url": self.post_base_url
            }
        
        # 2. 检查 model_routes
        model_routes = self.config.get("model_routes", {})
        route_config = model_routes.get(self.summarize_model, {})
        
        # 如果只设置了其中一个，与 route 配置混合
        result_api_key = self.post_api_key if self.post_api_key else None
        result_base_url = self.post_base_url if self.post_base_url else None
        
        if route_config.get("use_user_key"):
            # 使用用户 key（memory_agent 或主 key）
            if result_api_key is None:
                result_api_key = self.memory_agent_config.get("api_key", self.api_key)
            if result_base_url is None:
                result_base_url = self.memory_agent_config.get("base_url", "https://api.deepseek.com/v1")
        else:
            # 使用 route 配置
            if result_api_key is None:
                result_api_key = route_config.get("api_key", self.api_key)
            if result_base_url is None:
                result_base_url = route_config.get("base_url", "https://api.deepseek.com/v1")
        
        return {
            "api_key": result_api_key,
            "base_url": result_base_url
        }
    
    def _get_summary_tools(self) -> List[Dict]:
        """获取总结工具定义"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "record_summary",
                    "description": "记录对话摘要到 pending 暂存区",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "worth_recording": {"type": "boolean", "description": "是否值得记录"},
                            "topic": {"type": "string", "description": "简短主题（20字以内）"},
                            "summary": {"type": "string", "description": "第一人称对话摘要（100-500字）"},
                            "reason": {"type": "string", "description": "如果不记录，说明原因"}
                        },
                        "required": ["worth_recording"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_node",
                    "description": "创建新的人物/地点/事物/概念节点",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "节点名称"},
                            "type": {"type": "string", "enum": ["人物", "地点", "事物", "概念"], "description": "节点类型"},
                            "content": {"type": "string", "description": "节点内容描述"},
                            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"}
                        },
                        "required": ["name", "type", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "update_node",
                    "description": "更新已有节点的内容",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "节点名称"},
                            "content": {"type": "string", "description": "要追加的内容"},
                            "mode": {"type": "string", "enum": ["append", "replace"], "default": "append"}
                        },
                        "required": ["name", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "add_observations",
                    "description": "向节点添加观察（离散事实）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "observations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string", "description": "节点名称"},
                                        "contents": {"type": "array", "items": {"type": "string"}, "description": "观察内容列表"}
                                    },
                                    "required": ["name", "contents"]
                                }
                            }
                        },
                        "required": ["observations"]
                    }
                }
            }
        ]
    
    def _get_existing_summaries(self) -> str:
        """获取今日已存在的摘要"""
        try:
            pending_mgr = PendingManager(self.lifebook_path, self.encoding)
            all_sessions = pending_mgr.get_all_sessions()
            
            today = datetime.now().strftime('%Y-%m-%d')
            summary_count = 0
            summaries_text = ""
            
            for session in all_sessions:
                session_date = session.start_time.strftime('%Y-%m-%d')
                if session_date != today or not session.summaries:
                    continue
                
                for s in session.summaries:
                    summary_count += 1
                    max_len = self.pending_preview_max_chars
                    if len(s.summary) > max_len:
                        preview = "..." + s.summary[-max_len:]
                    else:
                        preview = s.summary
                    summaries_text += f"{summary_count}. [{s.topic}] {preview}\n"
            
            if summaries_text:
                return f"\n### 本会话已记录的摘要：\n{summaries_text}"
            return ""
            
        except Exception as e:
            logging.warning(f"[对话总结] 获取已存在摘要失败: {e}")
            return ""
    
    def _build_prompt(self, existing_summaries: str, conversation_text: str) -> str:
        """构建提示词"""
        base_prompt = self.summarize_prompt or """分析用户和AI的对话，使用 record_summary 工具记录摘要。
判断标准：记录重要决定/计划、具体人物/事件、学习收获、任务完成。不记录闲聊、调试、纠错。"""
        
        summary_prompt = f"{base_prompt}{existing_summaries}\n\n请注意：如果当前对话的内容在上述已记录摘要中已有体现，请将 worth_recording 设为 false。"
        
        is_reasoner = "reasoner" in self.summarize_model.lower()
        reasoner_hint = "\n请分析当前对话是否具有记录价值，并使用 record_summary 工具提交你的判断结果。" if is_reasoner else ""
        
        return f"""{summary_prompt}{reasoner_hint}

## 需要分析的对话

<conversation>
{conversation_text}
</conversation>

{self.summarize_suffix}"""
    
    def _process_response(
        self,
        response: Any,
        messages: List[Dict[str, Any]],
        memory_tools_write: Optional[Any]
    ) -> Optional[str]:
        """处理模型响应"""
        message = response.choices[0].message
        summary_result = {"worth_recording": False, "reason": "未触发工具调用"}
        node_operations = []
        
        # 处理工具调用
        if message.tool_calls:
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                raw_args = tool_call.function.arguments
                
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args = self._fix_malformed_json(raw_args)
                
                if tool_name == "record_summary":
                    summary_result = args
                    logging.info(f"[对话总结] record_summary 参数: {args}")
                
                elif tool_name in ("create_node", "update_node", "add_observations"):
                    if memory_tools_write:
                        try:
                            result = memory_tools_write.call_tool(tool_name, args)
                            node_operations.append({"tool": tool_name, "args": args, "result": result})
                            logging.debug(f"[对话总结] {tool_name}: {result[:100]}...")
                        except Exception as e:
                            logging.error(f"[对话总结] {tool_name} 执行失败: {e}")
        
        # 记录 token 消耗
        if response.usage:
            usage = response.usage
            token_info = {
                "prompt": usage.prompt_tokens,
                "completion": usage.completion_tokens,
                "total": usage.total_tokens
            }
            if hasattr(usage, 'completion_tokens_details') and usage.completion_tokens_details:
                if hasattr(usage.completion_tokens_details, 'reasoning_tokens'):
                    token_info["reasoning"] = usage.completion_tokens_details.reasoning_tokens
            
            logging.info(f"[对话总结] Token消耗: {token_info}")
        
        # 处理摘要存储
        if summary_result.get("worth_recording"):
            return self._save_summary(summary_result, messages, node_operations)
        else:
            reason = summary_result.get("reason", "不值得记录")
            logging.info(f"[对话总结] ⏭️ 跳过 - 原因: {reason}")
            return None
    
    def _save_summary(
        self,
        summary_result: Dict,
        messages: List[Dict[str, Any]],
        node_operations: List[Dict]
    ) -> Optional[str]:
        """保存摘要到 pending"""
        try:
            pending_mgr = PendingManager(self.lifebook_path, self.encoding)
            
            user_msg_count = len([m for m in messages if m.get("role") == "user"])
            tool_calls_list = [op["tool"] for op in node_operations]
            
            pending_summary = create_pending_summary(
                summary=summary_result.get("summary", ""),
                topic=summary_result.get("topic", "对话记录"),
                tool_calls=tool_calls_list,
                raw_turns=user_msg_count
            )
            
            success = pending_mgr.add_pending(pending_summary)
            
            if success:
                topic = summary_result.get('topic', '-')
                logging.info(f"[对话总结] ✅ 已暂存 - 主题: {topic}")
                return summary_result.get("summary")
            else:
                logging.warning(f"[对话总结] 暂存失败")
                return None
                
        except Exception as e:
            logging.error(f"[对话总结] 保存失败: {e}")
            return None
    
    def _fix_malformed_json(self, raw_json: str) -> Dict[str, Any]:
        """尝试修复不规范的 JSON"""
        import json
        
        if not raw_json:
            return {}
        
        fixed = raw_json
        
        try:
            # 修复空值
            fixed = re.sub(r'("[\w]+"\s*:\s*)([,}])', r'\1""\2', fixed)
            # 修复尾部逗号
            fixed = re.sub(r',\s*}', '}', fixed)
            fixed = re.sub(r',\s*]', ']', fixed)
            # 补全括号
            if fixed.count('{') > fixed.count('}'):
                fixed = fixed + '}' * (fixed.count('{') - fixed.count('}'))
            
            return json.loads(fixed)
            
        except json.JSONDecodeError:
            # 使用正则提取关键字段
            result = {}
            worth_match = re.search(r'"worth_recording"\s*:\s*(true|false)', raw_json, re.IGNORECASE)
            if worth_match:
                result["worth_recording"] = worth_match.group(1).lower() == "true"
            
            topic_match = re.search(r'"topic"\s*:\s*"([^"]*)"', raw_json)
            if topic_match:
                result["topic"] = topic_match.group(1)
            
            summary_match = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_json, re.DOTALL)
            if summary_match:
                result["summary"] = summary_match.group(1).replace('\\"', '"').replace('\\n', '\n')
            
            return result
    
    def _format_conversation(
        self,
        messages: List[Dict[str, Any]],
        response_content: str,
        main_model_reasoning: str
    ) -> str:
        """格式化对话用于总结"""
        def process_content(content):
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            texts.append(item.get("text", ""))
                        elif item.get("type") in ["image_url", "image"]:
                            texts.append("[图片]")
                    elif isinstance(item, str):
                        texts.append(item)
                return " ".join(texts)
            elif content is None:
                return ""
            return str(content)
        
        def truncate_content(content, max_len=10000):
            if len(content) > max_len:
                return content[:4000] + f"\n... (省略 {len(content)-max_len} 字符) ...\n" + content[-4000:]
            return content
        
        # 过滤消息
        conversation_messages = [
            m for m in messages[-50:]  # 限制最近50条
            if m.get("role") in ("user", "assistant")
        ]
        
        # 找到最后一条 user 消息
        last_user_idx = -1
        last_user_msg = None
        for i in range(len(conversation_messages) - 1, -1, -1):
            if conversation_messages[i].get("role") == "user":
                last_user_idx = i
                last_user_msg = conversation_messages[i]
                break
        
        # 分割历史和当前轮
        history_messages = conversation_messages[:last_user_idx] if last_user_idx > 0 else []
        
        result_parts = []
        
        # 历史上下文
        if history_messages:
            history_lines = []
            for msg in history_messages:
                role = msg.get("role", "")
                content = truncate_content(process_content(msg.get("content")))
                if role == "user":
                    history_lines.append(f"用户: {content}")
                elif role == "assistant":
                    history_lines.append(f"助手: {content}")
            
            if history_lines:
                result_parts.append(
                    "## 📜 历史上下文（仅供理解背景）\n"
                    "<history>\n" +
                    "\n\n".join(history_lines) +
                    "\n</history>"
                )
        
        # 当前轮次
        current_lines = []
        if last_user_msg:
            user_content = truncate_content(process_content(last_user_msg.get("content")))
            current_lines.append(f"👤 用户: {user_content}")
        
        assistant_parts = ["🤖 助手:"]
        if main_model_reasoning:
            reasoning_truncated = truncate_content(main_model_reasoning, 20000)
            assistant_parts.append(
                f"\n### 💭 主模型思考过程\n"
                f"<main_thought>\n{reasoning_truncated}\n</main_thought>"
            )
        
        if response_content:
            final_response = truncate_content(response_content, 15000)
            assistant_parts.append(f"\n{final_response}")
        
        current_lines.append("\n".join(assistant_parts))
        
        result_parts.append(
            "## ⭐ 当前轮次（**请重点总结这部分**）\n"
            "<current_turn>\n" +
            "\n\n".join(current_lines) +
            "\n</current_turn>"
        )
        
        result = "\n\n---\n\n".join(result_parts)
        
        # 总长度限制（使用配置值）
        max_len = self.max_context_chars
        if len(result) > max_len:
            result = f"...(对话过长，已截断)...\n\n" + result[-max_len:]
        
        return result
    
    def get_last_conversation(self) -> Optional[Tuple]:
        """获取缓存的最后一次对话"""
        if self._last_conversation is None:
            return None
        
        # 检查是否过期
        if len(self._last_conversation) >= 4:
            timestamp = self._last_conversation[3]
            if time.time() - timestamp > self.cache_ttl:
                logging.debug(f"[对话缓存] 已过期，清理 (TTL={self.cache_ttl}s)")
                self._last_conversation = None
                return None
            return self._last_conversation[:3]
        else:
            return self._last_conversation[:3] if len(self._last_conversation) >= 3 else None
    
    def clear_cache(self):
        """清理对话缓存"""
        self._last_conversation = None
"""
PostConversationSummarizer - 对话后总结器

从 MemoryRouter 中抽取的独立模块，负责：
1. 判断对话是否值得记录
2. 生成对话摘要（调用总结模型 + 工具调用）
3. 存入 pending 暂存区
4. 执行附带的节点操作（create_node, update_node, add_observations）
5. 管理对话缓存（用于手动重试）

设计原则：
- 不依赖 MemoryRouter，只依赖注入的配置和工具
- 通过 SummarizerConfig 集中管理配置
- 通过 Callable 解耦模型配置解析
"""

import json
import logging
import re
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from openai import OpenAI
import httpx


@dataclass
class SummarizerConfig:
    """总结器配置（从 config.jsonc 的 post_conversation 段解析）"""
    enabled: bool = False
    model: str = "deepseek-chat"
    prompt: str = ""
    suffix: str = (
        "请分析 **<current_turn>** 中的当前轮对话（忽略 <history>），然后调用工具。\n"
        "可调用的工具：record_summary（必须调用）、create_node、update_node、add_observations（可选）。\n"
        "**不要**模拟对话、不要回复对话中的问题，只需分析并调用工具。"
    )
    min_messages: int = 2
    pending_preview_max_chars: int = 200
    cache_ttl: int = 3600
    lifebook_path: str = "./lifebook"
    encoding: str = "utf-8"


# ─── 摘要工具定义（给总结模型使用）───

SUMMARY_TOOLS: List[Dict[str, Any]] = [
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
                    "reason": {"type": "string", "description": "如果不记录，说明原因"},
                },
                "required": ["worth_recording"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_node",
            "description": "创建新的人物/地点/事物/概念节点。在对话中发现新的重要实体时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "节点名称"},
                    "type": {
                        "type": "string",
                        "enum": ["人物", "地点", "事物", "概念"],
                        "description": "节点类型",
                    },
                    "content": {"type": "string", "description": "节点内容描述"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签列表（可选）",
                    },
                },
                "required": ["name", "type", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_node",
            "description": "更新已有节点的内容。在对话中发现关于已知实体的新信息时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "节点名称"},
                    "content": {"type": "string", "description": "要追加的内容"},
                    "mode": {
                        "type": "string",
                        "enum": ["append", "replace"],
                        "description": "更新模式：append追加，replace替换",
                        "default": "append",
                    },
                },
                "required": ["name", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_observations",
            "description": "向节点添加观察（离散事实）。用于记录关于人物/事物的具体事实。",
            "parameters": {
                "type": "object",
                "properties": {
                    "observations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "节点名称"},
                                "contents": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "要添加的观察内容列表",
                                },
                            },
                            "required": ["name", "contents"],
                        },
                        "description": "要添加观察的节点列表",
                    }
                },
                "required": ["observations"],
            },
        },
    },
]


class PostConversationSummarizer:
    """
    对话后总结器

    职责：在对话结束后判断是否值得记录、生成摘要、存入 pending、
    执行节点操作（create_node / update_node / add_observations）。

    使用方式::

        summarizer = PostConversationSummarizer(
            config=SummarizerConfig(...),
            memory_tools_write=tools,
            model_config_resolver=router.get_actual_model_config,
            fallback_api_config={"api_key": "...", "base_url": "..."},
        )
        summarizer.summarize_and_save(messages, response_content)
    """

    def __init__(
        self,
        config: SummarizerConfig,
        memory_tools_write,
        model_config_resolver: Callable[[str], Dict[str, Any]],
        fallback_api_config: Dict[str, Any],
    ):
        """
        Args:
            config: 总结器配置
            memory_tools_write: 可写记忆工具实例（需有 call_tool 方法）
            model_config_resolver: 模型配置解析函数 (model_name) -> config_dict
            fallback_api_config: 回退 API 配置 {"api_key": ..., "base_url": ...}
        """
        self.config = config
        self.memory_tools_write = memory_tools_write
        self._resolve_model_config = model_config_resolver
        self._fallback_api = fallback_api_config

        # 对话缓存（用于手动重试总结）
        # 格式: (messages, response_content, main_model_reasoning, timestamp)
        self._last_conversation: Optional[Tuple] = None

        logging.debug(
            f"[PostSummarizer] 初始化完成 (model={config.model}, "
            f"suffix前30字={config.suffix[:30]}...)"
        )

    # ─── 公共接口 ─────────────────────────────────────────

    def summarize_and_save(
        self,
        messages: List[Dict[str, Any]],
        response_content: str,
        async_mode: bool = True,
        main_model_reasoning: Optional[str] = None,
    ) -> Optional[str]:
        """
        对话后总结并暂存（不直接写入日记）

        流程：
        1. 检查是否启用 & 消息数量是否足够
        2. 缓存对话（用于重试）
        3. 异步/同步调用 _do_summarize_and_pending

        Args:
            messages: 原始对话消息
            response_content: 主模型的回复内容
            async_mode: 是否异步执行（不阻塞主流程）
            main_model_reasoning: 主模型的思考过程（可选）

        Returns:
            同步执行时返回总结内容；异步执行返回 None
        """
        if not self.config.enabled:
            return None

        # 检查消息数量
        user_messages = [m for m in messages if m.get("role") == "user"]
        if len(user_messages) < self.config.min_messages:
            logging.info(
                f"[对话总结] ⏭️ 跳过 - 消息数不足 "
                f"({len(user_messages)} < {self.config.min_messages})"
            )
            return None

        logging.info(
            f"[对话总结] 准备总结 (用户消息数: {len(user_messages)}, "
            f"阈值: {self.config.min_messages})"
        )

        m_reasoning = main_model_reasoning or ""

        # 缓存对话（带时间戳）
        self._last_conversation = (messages, response_content, m_reasoning, time.time())

        if async_mode:

            def _thread_wrapper():
                try:
                    self._do_summarize_and_pending(messages, response_content, m_reasoning)
                except Exception as e:
                    logging.error(f"[对话总结-异步] 线程执行出错: {e}", exc_info=True)

            thread = threading.Thread(target=_thread_wrapper, daemon=True)
            thread.start()
            return None
        else:
            return self._do_summarize_and_pending(messages, response_content, m_reasoning)

    def get_last_conversation(
        self,
    ) -> Optional[Tuple[List[Dict[str, Any]], str, str]]:
        """
        获取缓存的最后一次对话（用于手动重试总结）

        自动检查 TTL，过期则返回 None 并清理缓存。

        Returns:
            (messages, response_content, reasoning) 或 None
        """
        if self._last_conversation is None:
            return None

        if len(self._last_conversation) >= 4:
            timestamp = self._last_conversation[3]
            if time.time() - timestamp > self.config.cache_ttl:
                logging.debug(
                    f"[对话缓存] 已过期，清理 (TTL={self.config.cache_ttl}s)"
                )
                self._last_conversation = None
                return None
            return self._last_conversation[:3]
        else:
            # 兼容旧格式（无时间戳）
            return (
                self._last_conversation[:3]
                if len(self._last_conversation) >= 3
                else None
            )

    def clear_conversation_cache(self):
        """手动清理对话缓存"""
        self._last_conversation = None
        logging.debug("[对话缓存] 已手动清理")

    # ─── 核心实现 ─────────────────────────────────────────

    def _do_summarize_and_pending(
        self,
        messages: List[Dict[str, Any]],
        response_content: str,
        main_model_reasoning: str = "",
    ) -> Optional[str]:
        """
        生成摘要并存入 pending（不直接写入日记）

        流程：
        1. 格式化对话文本
        2. 获取已有 pending 摘要（防重复）
        3. 调用总结模型（原生工具模式）
        4. 处理工具调用（record_summary + 节点操作）
        5. 存入 pending 暂存区
        """
        try:
            from memory_store.pending_manager import PendingManager, create_pending_summary

            cfg = self.config

            # 构建对话文本
            conversation_text = self._format_conversation_for_summary(
                messages, response_content, main_model_reasoning
            )

            # 解析 API 配置
            api_key, base_url = self._resolve_api_config()

            # 创建不带代理的客户端
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=httpx.Client(proxy=None),
            )

            # 获取已有 pending 摘要（防重复记录）
            pending_mgr = PendingManager(cfg.lifebook_path, cfg.encoding)
            existing_summaries_text = self._build_existing_summaries_text(pending_mgr)

            # 组装 prompt
            base_prompt = cfg.prompt or (
                "分析用户和AI的对话，使用 record_summary 工具记录摘要。\n"
                "判断标准：记录重要决定/计划、具体人物/事件、学习收获、任务完成。"
                "不记录闲聊、调试、纠错。"
            )

            summary_prompt = (
                f"{base_prompt}\n{existing_summaries_text}\n\n"
                "请注意：如果当前对话的内容在上述已记录摘要中已有体现，"
                "请在 record_summary 中将 worth_recording 设为 false，避免重复记录。"
            )

            # 针对 deepseek-reasoner 的特殊处理
            is_reasoner = "reasoner" in cfg.model.lower()
            reasoner_hint = (
                "\n请分析当前对话是否具有记录价值，并使用 record_summary 工具提交你的判断结果。"
                if is_reasoner
                else ""
            )

            user_message = (
                f"{summary_prompt}{reasoner_hint}\n\n"
                f"## 需要分析的对话\n\n"
                f"<conversation>\n{conversation_text}\n</conversation>\n\n"
                f"{cfg.suffix}"
            )

            logging.info(
                f"[对话摘要] 调用 {cfg.model} (原生工具模式 + 暂存感知)..."
            )

            # 记录调试日志
            from memory_store.debug_logger import get_debug_logger

            get_debug_logger().log_post_conversation(
                model=cfg.model,
                prompt=user_message,
                conversation_length=len(conversation_text),
                extra={
                    "has_existing_summaries": bool(existing_summaries_text),
                    "is_reasoner": is_reasoner,
                },
            )

            # 调用总结模型
            response = client.chat.completions.create(
                model=cfg.model,
                messages=[{"role": "user", "content": user_message}],
                tools=SUMMARY_TOOLS,
                tool_choice="auto",
                max_tokens=3000 if is_reasoner else 1500,
                temperature=0.3,
            )

            # 记录 token 消耗
            usage = response.usage
            if usage:
                logging.info(
                    f"[对话摘要] Token消耗: prompt={usage.prompt_tokens}, "
                    f"completion={usage.completion_tokens}, total={usage.total_tokens}"
                )

            # 处理工具调用
            message = response.choices[0].message
            summary_result, node_operations = self._process_tool_calls(
                message, is_reasoner
            )

            # 记录调试日志
            self._log_tool_call_result(
                message, summary_result, node_operations, usage
            )

            # 存储摘要
            if summary_result.get("worth_recording"):
                return self._store_pending_summary(
                    pending_mgr, summary_result, node_operations, messages
                )
            else:
                reason = summary_result.get("reason", "不值得记录")
                logging.info(f"[对话摘要] ⏭️ 跳过 - 原因: {reason}")
                if node_operations:
                    ops = ", ".join(op["tool"] for op in node_operations)
                    logging.debug(f"[对话摘要] 但执行了节点操作: {ops}")
                return None

        except Exception as e:
            error_str = str(e)
            if "Content Exists Risk" in error_str or "content_filter" in error_str.lower():
                logging.warning("[对话摘要] ⚠️ 内容因敏感被屏蔽，跳过本次记录")
                return None
            logging.error(f"[对话摘要] 出错: {e}", exc_info=True)
            return None

    # ─── 辅助方法 ─────────────────────────────────────────

    def _resolve_api_config(self) -> Tuple[str, str]:
        """解析总结模型的 API 配置，返回 (api_key, base_url)"""
        model_config = self._resolve_model_config(self.config.model)
        if model_config.get("use_user_key"):
            return (
                self._fallback_api.get("api_key", ""),
                self._fallback_api.get("base_url", "https://api.deepseek.com/v1"),
            )
        return (
            model_config.get("api_key", ""),
            model_config.get("base_url", "https://api.deepseek.com/v1"),
        )

    def _build_existing_summaries_text(self, pending_mgr) -> str:
        """构建已有 pending 摘要文本（用于防重复）"""
        all_sessions = pending_mgr.get_all_sessions()
        today = datetime.now().strftime("%Y-%m-%d")
        parts = []
        count = 0

        for session in all_sessions:
            session_date = session.start_time.strftime("%Y-%m-%d")
            if session_date != today or not session.summaries:
                continue
            for s in session.summaries:
                count += 1
                max_len = self.config.pending_preview_max_chars
                preview = (
                    f"...{s.summary[-max_len:]}"
                    if len(s.summary) > max_len
                    else s.summary
                )
                parts.append(f"{count}. [{s.topic}] {preview}")

        if not parts:
            return ""
        return f"\n### 本会话已记录的摘要：\n" + "\n".join(parts)

    def _process_tool_calls(
        self, message, is_reasoner: bool
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        处理总结模型返回的工具调用

        Returns:
            (summary_result, node_operations)
        """
        summary_result: Dict[str, Any] = {
            "worth_recording": False,
            "reason": "未触发工具调用",
        }
        node_operations: List[Dict[str, Any]] = []

        if message.tool_calls:
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                raw_args = tool_call.function.arguments
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError as e:
                    logging.warning(f"[对话摘要] JSON解析失败: {e}, 尝试修复...")
                    args = self._fix_malformed_json(raw_args)
                    if args:
                        logging.info("[对话摘要] JSON修复成功")
                    else:
                        logging.warning(
                            f"[对话摘要] JSON修复失败，原始参数: {raw_args[:300]}..."
                        )

                logging.debug(f"[对话摘要] 处理工具调用: {tool_name}")

                if tool_name == "record_summary":
                    summary_result = args
                    logging.info(f"[对话摘要] record_summary 参数: {args}")
                elif tool_name in ("create_node", "update_node", "add_observations"):
                    try:
                        result = self.memory_tools_write.call_tool(tool_name, args)
                        node_operations.append(
                            {"tool": tool_name, "args": args, "result": result}
                        )
                        logging.debug(f"[对话摘要] {tool_name}: {result[:100]}...")
                    except Exception as e:
                        logging.error(f"[对话摘要] {tool_name} 执行失败: {e}")

        elif is_reasoner and message.content:
            logging.debug(
                "[对话摘要] Reasoner 未调用工具，尝试解析正文内容..."
            )
            logging.debug(f"Reasoner 回复内容: {message.content[:200]}...")

        return summary_result, node_operations

    def _log_tool_call_result(
        self, message, summary_result, node_operations, usage
    ):
        """记录工具调用结果到调试日志"""
        from memory_store.debug_logger import get_debug_logger

        response_extra: Dict[str, Any] = {
            "type": "tool_call_result",
            "tool_calls_count": len(message.tool_calls) if message.tool_calls else 0,
            "tools_called": (
                [tc.function.name for tc in message.tool_calls]
                if message.tool_calls
                else []
            ),
        }

        if usage:
            token_usage: Dict[str, int] = {
                "prompt": usage.prompt_tokens,
                "completion": usage.completion_tokens,
                "total": usage.total_tokens,
            }
            if (
                hasattr(usage, "completion_tokens_details")
                and usage.completion_tokens_details
            ):
                details = usage.completion_tokens_details
                if hasattr(details, "reasoning_tokens"):
                    token_usage["reasoning"] = details.reasoning_tokens
            response_extra["token_usage"] = token_usage

        response_text = (
            json.dumps(
                {
                    "summary_result": summary_result,
                    "node_operations": node_operations,
                },
                ensure_ascii=False,
                indent=2,
            )
            if message.tool_calls
            else (message.content or "")
        )

        get_debug_logger().log_post_conversation(
            model=self.config.model + " [response]",
            prompt="[工具调用结果]",
            conversation_length=0,
            response=response_text,
            extra=response_extra,
        )

    def _store_pending_summary(
        self,
        pending_mgr,
        summary_result: Dict[str, Any],
        node_operations: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> Optional[str]:
        """将摘要存入 pending 暂存区"""
        from memory_store.pending_manager import create_pending_summary

        user_msg_count = len([m for m in messages if m.get("role") == "user"])
        tool_calls_list = [op["tool"] for op in node_operations]

        pending_summary = create_pending_summary(
            summary=summary_result.get("summary", ""),
            topic=summary_result.get("topic", "对话记录"),
            tool_calls=tool_calls_list,
            raw_turns=user_msg_count,
        )

        success = pending_mgr.add_pending(pending_summary)

        if success:
            topic = summary_result.get("topic", "-")
            preview = summary_result.get("summary", "")[:100]
            logging.info(f"[对话摘要] ✅ 已暂存 - 主题: {topic}")
            logging.debug(f"[对话摘要] 摘要预览: {preview}...")
            if node_operations:
                logging.debug(
                    f"[对话摘要] 节点操作: {', '.join(tool_calls_list)}"
                )
            return summary_result.get("summary")
        else:
            logging.warning("[对话摘要] 暂存失败")
            return None

    # ─── 格式化 & 修复 ───────────────────────────────────

    @staticmethod
    def _fix_malformed_json(raw_json: str) -> Dict[str, Any]:
        """
        尝试修复模型生成的不规范 JSON

        常见问题：
        - "reason": } （空值没有引号）
        - 尾部多余逗号
        - 字段值被截断
        """
        if not raw_json:
            return {}

        fixed = raw_json

        try:
            # 1. 修复空值: "key": } → "key": ""}
            fixed = re.sub(r'("[\w]+"\s*:\s*)([,}])', r'\1""\2', fixed)
            # 2. 修复尾部逗号
            fixed = re.sub(r",\s*}", "}", fixed)
            fixed = re.sub(r",\s*]", "]", fixed)
            # 3. 补全截断的 }
            if fixed.count("{") > fixed.count("}"):
                fixed += "}" * (fixed.count("{") - fixed.count("}"))

            return json.loads(fixed)

        except json.JSONDecodeError:
            # 回退：正则提取关键字段
            try:
                result: Dict[str, Any] = {}

                worth_match = re.search(
                    r'"worth_recording"\s*:\s*(true|false)', raw_json, re.IGNORECASE
                )
                if worth_match:
                    result["worth_recording"] = worth_match.group(1).lower() == "true"

                topic_match = re.search(r'"topic"\s*:\s*"([^"]*)"', raw_json)
                if topic_match:
                    result["topic"] = topic_match.group(1)

                summary_match = re.search(
                    r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_json, re.DOTALL
                )
                if summary_match:
                    result["summary"] = (
                        summary_match.group(1)
                        .replace('\\"', '"')
                        .replace("\\n", "\n")
                    )

                reason_match = re.search(r'"reason"\s*:\s*"([^"]*)"', raw_json)
                if reason_match:
                    result["reason"] = reason_match.group(1)

                if result:
                    logging.debug(
                        f"[对话摘要] 使用正则提取到字段: {list(result.keys())}"
                    )
                    return result

            except Exception as regex_err:
                logging.debug(f"[对话摘要] 正则提取也失败: {regex_err}")

            return {}

    @staticmethod
    def _format_conversation_for_summary(
        messages: List[Dict[str, Any]],
        response_content: str,
        main_model_reasoning: Optional[str] = None,
    ) -> str:
        """
        格式化对话用于总结

        将对话分为【历史上下文】和【当前轮次】两部分：
        - 历史部分：仅供理解上下文，不需要重复总结
        - 当前轮次：本次对话的重点，需要总结的内容
        """

        def process_content(content) -> str:
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            texts.append(item.get("text", ""))
                        elif item.get("type") in ("image_url", "image"):
                            texts.append("[图片]")
                return " ".join(texts)
            elif content is None:
                return ""
            return str(content)

        def truncate(text: str, max_len: int = 10000) -> str:
            if len(text) > max_len:
                return (
                    text[:4000]
                    + f"\n... (省略 {len(text) - max_len} 字符) ...\n"
                    + text[-4000:]
                )
            return text

        # 过滤：只保留 user / assistant，最近 50 条
        conv_msgs = [
            m for m in messages[-50:] if m.get("role") in ("user", "assistant")
        ]

        # 找最后一条 user 消息
        last_user_idx = -1
        last_user_msg = None
        for i in range(len(conv_msgs) - 1, -1, -1):
            if conv_msgs[i].get("role") == "user":
                last_user_idx = i
                last_user_msg = conv_msgs[i]
                break

        history_msgs = conv_msgs[:last_user_idx] if last_user_idx > 0 else []

        result_parts: List[str] = []

        # === 历史上下文 ===
        if history_msgs:
            lines = []
            for msg in history_msgs:
                role = msg.get("role", "")
                content = truncate(process_content(msg.get("content")))
                if role == "user":
                    lines.append(f"用户: {content}")
                elif role == "assistant":
                    lines.append(f"助手: {content}")

            if lines:
                result_parts.append(
                    "## 📜 历史上下文（仅供理解背景，无需重复总结）\n"
                    "<history>\n"
                    + "\n\n".join(lines)
                    + "\n</history>"
                )

        # === 当前轮次 ===
        current_lines: List[str] = []

        if last_user_msg:
            user_content = truncate(process_content(last_user_msg.get("content")))
            current_lines.append(f"👤 用户: {user_content}")

        assistant_parts = ["🤖 助手:"]

        if main_model_reasoning:
            reasoning_truncated = truncate(main_model_reasoning, 20000)
            assistant_parts.append(
                f"\n### 💭 主模型思考过程（包含重要细节）\n"
                f"<main_thought>\n{reasoning_truncated}\n</main_thought>"
            )

        final_response = response_content or ""
        if final_response:
            final_response = truncate(final_response, 15000)
            assistant_parts.append(f"\n{final_response}")

        current_lines.append("\n".join(assistant_parts))

        result_parts.append(
            "## ⭐ 当前轮次（**请重点总结这部分**）\n"
            "<current_turn>\n"
            + "\n\n".join(current_lines)
            + "\n</current_turn>"
        )

        result = "\n\n---\n\n".join(result_parts)

        # 终极总长度限制
        MAX_TOTAL_LEN = 100000
        if len(result) > MAX_TOTAL_LEN:
            result = f"...(对话过长，已截断)...\n\n{result[-MAX_TOTAL_LEN:]}"

        return result
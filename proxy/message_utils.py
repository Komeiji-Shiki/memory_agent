"""
消息处理工具

提供消息格式转换、工具调用解析等功能
"""

import json
import re
from typing import Dict, List, Any, Optional


def message_to_dict(message) -> Dict[str, Any]:
    """
    将 OpenAI SDK 消息对象转换为字典格式
    
    Args:
        message: OpenAI SDK 返回的消息对象
        
    Returns:
        消息字典
    """
    result = {
        "role": message.role,
        "content": message.content or "",
    }
    
    # 支持两种字段名：reasoning_content (DeepSeek) 和 reasoning (Vercel)
    reasoning = getattr(message, 'reasoning_content', None) or getattr(message, 'reasoning', None)
    if reasoning:
        result["reasoning_content"] = reasoning
    
    if hasattr(message, 'tool_calls') and message.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "function": {
                    "arguments": tc.function.arguments,
                    "name": tc.function.name
                },
                "type": tc.type,
                "index": tc.index if hasattr(tc, 'index') else i
            }
            for i, tc in enumerate(message.tool_calls)
        ]
    
    return result


def format_tool_call_text(tool_name: str, arguments: str) -> str:
    """
    将工具调用格式化为简单文本格式，用于流式输出
    
    Args:
        tool_name: 工具名称
        arguments: 参数 JSON 字符串
        
    Returns:
        格式化的文本
    """
    return f"\n「调用工具: {tool_name} 输入内容: {arguments}」\n"


def replace_old_tool_results(
    messages: List[Dict[str, Any]], 
    tool_call_history: List[str], 
    keep_count: int
) -> None:
    """
    将历史工具调用结果替换为占位符「调用完毕」
    保留最近 N 次工具调用的完整结果
    
    Args:
        messages: 消息列表（会被原地修改）
        tool_call_history: 按时间顺序排列的工具调用 ID 列表
        keep_count: 保留最近多少次工具调用的完整结果
                   - 0: 保留当前轮次所有
                   - >0: 保留最近 N 次
                   - <0: 不保留任何
    """
    if keep_count == 0:
        # 保留所有当前轮次的工具调用
        keep_ids = set(tool_call_history)
    elif keep_count > 0:
        # 保留最近 keep_count 次工具调用
        keep_ids = set(tool_call_history[-keep_count:]) if tool_call_history else set()
    else:
        # 不保留任何工具调用
        keep_ids = set()
    
    for msg in messages:
        if isinstance(msg, dict) and msg.get('role') == 'tool':
            tool_call_id = msg.get('tool_call_id', '')
            # 如果不在保留列表中，替换为占位符
            if tool_call_id not in keep_ids:
                msg['content'] = '调用完毕'


def merge_assistant_message(
    messages: List[Dict[str, Any]],
    assistant_msg_index: Optional[int],
    new_reasoning: str,
    new_content: str,
    new_tool_calls: Optional[List]
) -> None:
    """
    合并助手消息（用于多轮工具调用）
    
    Args:
        messages: 消息列表（会被原地修改）
        assistant_msg_index: 助手消息的索引
        new_reasoning: 新的思考内容
        new_content: 新的回复内容
        new_tool_calls: 新的工具调用
    """
    # 删除所有 tool 消息
    while messages and isinstance(messages[-1], dict) and messages[-1].get('role') == 'tool':
        messages.pop()
    
    if assistant_msg_index is not None and assistant_msg_index < len(messages):
        prev_assistant = messages[assistant_msg_index]
        
        # 保留原始的 reasoning_content，不添加工具调用JSON
        old_reasoning = prev_assistant.get('reasoning_content', '') or ''
        
        # 追加新的思维链
        if new_reasoning:
            combined_reasoning = old_reasoning + "\n\n" + new_reasoning if old_reasoning else new_reasoning
            prev_assistant['reasoning_content'] = combined_reasoning
        
        # 更新工具调用
        if new_tool_calls:
            prev_assistant['tool_calls'] = [
                {
                    "id": tc.id,
                    "function": {
                        "arguments": tc.function.arguments,
                        "name": tc.function.name
                    },
                    "type": tc.type,
                    "index": tc.index if hasattr(tc, 'index') else i
                }
                for i, tc in enumerate(new_tool_calls)
            ]
        else:
            if 'tool_calls' in prev_assistant:
                del prev_assistant['tool_calls']
            prev_assistant['content'] = new_content


def parse_arguments(args_str: str) -> Dict[str, Any]:
    """
    解析工具调用参数，支持 JSON 和 YAML 格式
    
    Args:
        args_str: 参数字符串，可能是 JSON 或 YAML 格式
        
    Returns:
        解析后的参数字典
    """
    if not args_str or not args_str.strip():
        return {}
    
    args_str = args_str.strip()
    
    # 1. 首先尝试 JSON 解析
    try:
        return json.loads(args_str)
    except json.JSONDecodeError:
        pass
    
    # 2. 尝试 YAML 解析
    try:
        import yaml
        result = yaml.safe_load(args_str)
        if isinstance(result, dict):
            return result
        elif result is None:
            return {}
        else:
            print(f"[工具调用] YAML 解析结果不是字典: {type(result)}")
            return {}
    except ImportError:
        print(f"[工具调用] YAML 库未安装，无法解析 YAML 格式参数")
    except Exception as yaml_err:
        print(f"[工具调用] YAML 解析失败: {yaml_err}")
    
    # 3. 尝试简单的 key: value 格式解析
    try:
        result = {}
        lines = args_str.strip().split('\n')
        for line in lines:
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                # 尝试解析值的类型
                if value.lower() == 'true':
                    result[key] = True
                elif value.lower() == 'false':
                    result[key] = False
                elif value.lower() == 'null' or value.lower() == 'none':
                    result[key] = None
                else:
                    try:
                        result[key] = int(value)
                    except ValueError:
                        try:
                            result[key] = float(value)
                        except ValueError:
                            # 移除可能的引号
                            if (value.startswith('"') and value.endswith('"')) or \
                               (value.startswith("'") and value.endswith("'")):
                                value = value[1:-1]
                            result[key] = value
        if result:
            print(f"[工具调用] 使用简单 key:value 格式解析成功: {result}")
            return result
    except Exception as simple_err:
        print(f"[工具调用] 简单格式解析失败: {simple_err}")
    
    print(f"[工具调用] 参数解析失败（所有方法都失败）: {args_str[:200]}")
    return {}


def parse_xml_tool_calls(content: str) -> List[Dict[str, Any]]:
    """
    解析 XML 格式的工具调用
    
    支持两种格式：
    1. 新格式（推荐）：
       <<<tool_call>>>
       name: search_memories
       arguments: {"query": "关键词"}
       <<</tool_call>>>
    
    2. 旧格式（兼容）：
       <tool_call>
       <name>search_memories</name>
       <arguments>{"query": "关键词"}</arguments>
       </tool_call>
    
    Args:
        content: 包含工具调用的内容
        
    Returns:
        工具调用列表
    """
    tool_calls = []
    
    # 新格式：<<<tool_call>>> ... <<</tool_call>>>
    new_pattern = r'<<<tool_call>>>\s*name:\s*(.*?)\s*arguments:\s*(.*?)\s*<<</tool_call>>>'
    new_matches = re.findall(new_pattern, content, re.DOTALL)
    
    for name, args_str in new_matches:
        name = name.strip()
        arguments = parse_arguments(args_str)
        
        tool_calls.append({
            "name": name,
            "arguments": arguments
        })
    
    # 如果新格式没找到，尝试旧格式（兼容）
    if not tool_calls:
        old_pattern = r'<tool_call>\s*<name>(.*?)</name>\s*<arguments>(.*?)</arguments>\s*</tool_call>'
        old_matches = re.findall(old_pattern, content, re.DOTALL)
        
        for name, args_str in old_matches:
            name = name.strip()
            arguments = parse_arguments(args_str)
            
            tool_calls.append({
                "name": name,
                "arguments": arguments
            })
    
    return tool_calls


# 记忆工具名称集合（用于工具分类）
# ⚠️ 这是唯一权威来源，memory_router.py 也应引用此处
MEMORY_TOOL_NAMES = {
    # 查询工具
    "search_memories", "rag_search", "read_diary", "read_summary",
    "get_node", "list_recent", "get_current_context", "get_current_time",
    "list_all_tags", "list_all_people",
    # 概览工具
    "list_nodes", "get_memory_overview", "read_all_nodes",
    # 知识图谱工具（MCP memory 风格）
    "read_graph", "add_observations", "create_relations",
    # Graphiti 时序图谱工具
    "graphiti_search", "graphiti_temporal", "graphiti_add",
    "graphiti_multi_hop", "graphiti_sync_node", "graphiti_get_stats",
    # 写入工具
    "add_to_diary", "create_node", "update_node", "create_summary",
    # 编辑工具（类似 apply_diff）
    "edit_diary", "edit_node", "edit_summary", "rewrite_diary",
    # 删除工具
    "delete_node", "delete_summary",
    # Pending 工具
    "add_to_pending",
    # 对话后总结专用工具
    "record_summary"
}

MEMORY_WRITE_TOOL_NAMES = {
    "add_to_diary", "create_node", "update_node", "create_summary",
    "edit_diary", "edit_node", "edit_summary", "rewrite_diary",
    "delete_node", "delete_summary", "add_observations", "create_relations",
    # Graphiti 写入
    "graphiti_add", "graphiti_sync_node",
    # Pending
    "add_to_pending", "record_summary"
}


def is_memory_tool(tool_name: str) -> bool:
    """检查是否是记忆工具"""
    return tool_name in MEMORY_TOOL_NAMES


def is_memory_write_tool(tool_name: str) -> bool:
    """检查是否是记忆写入工具"""
    return tool_name in MEMORY_WRITE_TOOL_NAMES
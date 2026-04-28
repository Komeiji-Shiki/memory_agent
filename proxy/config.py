"""
配置加载模块

支持 JSONC 格式（带注释的 JSON）
支持配置热重载
"""

import json
import os
import re
from typing import Dict, Any, Callable, Optional

# 尝试导入热重载模块
try:
    from .config_hot_reload import get_hot_config, ConfigChangeEvent
    HAS_HOT_RELOAD = True
except ImportError:
    HAS_HOT_RELOAD = False


# 全局配置（模块级别单例）
CONFIG: Dict[str, Any] = {}

# 是否启用热重载
_hot_reload_enabled: bool = True


def enable_hot_reload(enabled: bool = True):
    """
    启用或禁用热重载
    
    Args:
        enabled: 是否启用
    """
    global _hot_reload_enabled
    _hot_reload_enabled = enabled


def load_config(config_path: str = "config.jsonc") -> Dict[str, Any]:
    """
    加载配置文件（支持 JSONC 格式，带注释）
    
    如果启用了热重载，会自动初始化热重载管理器。
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置字典
    """
    global CONFIG
    
    # 如果启用了热重载，使用热重载管理器
    if HAS_HOT_RELOAD and _hot_reload_enabled:
        hot_config = get_hot_config(config_path, auto_reload=True, poll_interval=1.0)
        CONFIG = hot_config.get_config()
        return CONFIG
    
    # 传统方式加载
    default_config = {
        "chat_completions_url": "https://api.deepseek.com/v1/chat/completions",
        "models_url": "https://api.deepseek.com/v1/models",
        "api_key": "",
        "access_keys": [],
        "allow_user_api_key": True,
        "host": "127.0.0.1",
        "port": 8002,
        "debug": False,
        "mcp_enabled": True,
        "auto_execute_mcp_tools": True,
        "max_iterations": 100,
        "keep_tool_results_count": 0,
        "max_retries": 0,
        "system_prompt_enabled": False,
        "system_prompt": "## 工具调用注意事项\n\n当你使用工具获取信息时，请注意以下几点：\n\n1. **工具调用结果不会保存在对话历史中**：每次工具调用的原始结果只会在当前回合可见，后续对话中将无法再访问这些原始数据。\n\n2. **主动提取和整理信息**：在收到工具返回的结果后，请在你的思考过程中提取所有有用的信息，包括：\n   - 关键数据和数值\n   - 重要的名称、日期、地点等\n   - 相关的上下文信息\n   - 可能在后续对话中需要引用的内容\n\n3. **在回复中复述关键信息**：将提取的重要信息融入你的回复中，这样用户和你都能在后续对话中参考这些信息。\n\n4. **结构化输出**：当工具返回大量信息时，请以清晰、结构化的方式呈现，便于理解和后续引用。"
    }
    
    if not os.path.exists(config_path):
        print(f"配置文件 {config_path} 不存在，使用默认配置")
        CONFIG = default_config
        return CONFIG
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 移除 JSONC 注释
        content = _strip_jsonc_comments(content)
        
        config = json.loads(content)
        
        # 调试：显示从配置文件加载的关键配置
        print(f"✓ 配置文件加载成功: {config_path}")
        if 'port' in config:
            print(f"  - 配置文件中的端口: {config['port']}")
        if 'host' in config:
            print(f"  - 配置文件中的主机: {config['host']}")
        
        # 合并默认配置
        for key, value in default_config.items():
            if key not in config:
                config[key] = value
        
        CONFIG = config
        return CONFIG
        
    except Exception as e:
        print(f"✗ 加载配置文件失败: {e}，使用默认配置")
        import traceback
        traceback.print_exc()
        CONFIG = default_config
        return CONFIG


def _strip_jsonc_comments(content: str) -> str:
    """
    移除 JSONC 注释
    
    支持:
    - 多行注释 /* ... */
    - 单行注释 // ...（不在字符串中）
    """
    # 1. 移除多行注释 /* ... */
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    
    # 2. 移除单行注释 // ...（但保留字符串中的 //）
    lines = []
    for line in content.split('\n'):
        if '//' in line:
            # 检查 // 是否在字符串中
            in_string = False
            quote_char = None
            comment_pos = -1
            
            for i, char in enumerate(line):
                if char in ('"', "'") and (i == 0 or line[i-1] != '\\'):
                    if not in_string:
                        in_string = True
                        quote_char = char
                    elif char == quote_char:
                        in_string = False
                        quote_char = None
                elif char == '/' and i < len(line) - 1 and line[i+1] == '/' and not in_string:
                    comment_pos = i
                    break
            
            if comment_pos >= 0:
                line = line[:comment_pos]
        
        lines.append(line)
    
    return '\n'.join(lines)


def get_base_url_from_chat_url(chat_url: str) -> str:
    """
    从聊天补全 URL 中提取基础 URL（用于 OpenAI SDK）
    
    Args:
        chat_url: 聊天补全 API URL
        
    Returns:
        基础 URL（到 /v1）
    """
    if '/chat/completions' in chat_url:
        return chat_url.rsplit('/chat/completions', 1)[0]
    return chat_url


def get_config() -> Dict[str, Any]:
    """
    获取当前配置
    
    如果启用了热重载，始终返回最新的配置。
    
    Returns:
        配置字典
    """
    global CONFIG
    
    # 如果启用了热重载，从热重载管理器获取最新配置
    if HAS_HOT_RELOAD and _hot_reload_enabled:
        try:
            return get_hot_config().get_config()
        except Exception as e:
            print(f"[Config] 热重载获取配置失败: {e}，使用缓存配置")
    
    return CONFIG.copy() if CONFIG else {}


def get_config_value(key: str, default: Any = None) -> Any:
    """
    获取配置项（支持点号分隔的路径）
    
    Args:
        key: 配置键（如 "graphiti.enabled"）
        default: 默认值
        
    Returns:
        配置值
    """
    if HAS_HOT_RELOAD and _hot_reload_enabled:
        try:
            return get_hot_config().get(key, default)
        except Exception as e:
            print(f"[Config] 热重载获取配置值失败: {e}")
    
    # 传统方式
    config = get_config()
    keys = key.split('.')
    
    value = config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    
    return value


def subscribe_config_changes(callback: Callable[[Any], None]) -> bool:
    """
    订阅配置变更事件
    
    Args:
        callback: 回调函数，接收 ConfigChangeEvent 参数
        
    Returns:
        是否订阅成功
    """
    if HAS_HOT_RELOAD and _hot_reload_enabled:
        try:
            get_hot_config().subscribe(callback)
            return True
        except Exception as e:
            print(f"[Config] 订阅配置变更失败: {e}")
    
    return False


def unsubscribe_config_changes(callback: Callable[[Any], None]) -> bool:
    """
    取消订阅配置变更事件
    
    Args:
        callback: 之前注册的回调函数
        
    Returns:
        是否取消成功
    """
    if HAS_HOT_RELOAD and _hot_reload_enabled:
        try:
            return get_hot_config().unsubscribe(callback)
        except Exception as e:
            print(f"[Config] 取消订阅配置变更失败: {e}")
    
    return False


def reload_config() -> bool:
    """
    手动强制重载配置
    
    Returns:
        是否成功
    """
    if HAS_HOT_RELOAD and _hot_reload_enabled:
        try:
            return get_hot_config().reload()
        except Exception as e:
            print(f"[Config] 手动重载配置失败: {e}")
    
    # 传统方式：重新加载文件
    try:
        load_config()
        return True
    except Exception as e:
        print(f"[Config] 重载配置失败: {e}")
        return False


def update_config(updates: Dict[str, Any]) -> None:
    """
    更新配置
    
    注意：此更新仅保存在内存中，不会写入配置文件。
    要永久修改配置，请直接编辑配置文件。
    
    Args:
        updates: 要更新的配置项
    """
    global CONFIG
    
    # 如果启用了热重载，也通过热重载管理器更新
    if HAS_HOT_RELOAD and _hot_reload_enabled:
        try:
            hot_config = get_hot_config()
            with hot_config._lock:
                hot_config._config.update(updates)
        except Exception as e:
            print(f"[Config] 热重载更新失败: {e}")
    
    # 同时更新本地缓存
    CONFIG.update(updates)
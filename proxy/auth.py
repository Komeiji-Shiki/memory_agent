"""
认证模块

处理访问密钥验证和 API Key 获取
"""

from typing import Tuple, Optional
from .config import get_config


def validate_access_key(auth_header: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    验证访问密钥
    
    Args:
        auth_header: Authorization 请求头
        
    Returns:
        (是否有效, API Key, 错误消息)
    """
    config = get_config()
    
    access_keys = config.get("access_keys", [])
    allow_user_api_key = config.get("allow_user_api_key", True)
    config_api_key = config.get("api_key", "")
    
    # 提取用户提供的key
    user_key = ""
    if auth_header.startswith('Bearer '):
        user_key = auth_header[7:]
    
    # 如果没有配置访问密钥（开放模式）
    if not access_keys:
        # 优先使用用户的Key
        if allow_user_api_key and user_key:
            return True, user_key, None
        # 其次使用配置的Key
        if config_api_key:
            return True, config_api_key, None
        # 如果用户提供了key就用用户的
        if user_key:
            return True, user_key, None
        # 没有任何可用的key
        return False, None, "No API key available. Please configure api_key in config.jsonc or provide Authorization header."
    
    # 有配置访问密钥时，需要验证
    if not user_key:
        return False, None, "Missing Authorization header"
    
    # 检查是否是有效的访问密钥
    if user_key in access_keys:
        # 使用配置的 API Key
        if config_api_key:
            return True, config_api_key, None
        return False, None, "Server API key not configured"
    
    # 如果允许用户使用自己的 API Key
    if allow_user_api_key:
        return True, user_key, None
    
    return False, None, "Invalid access key"
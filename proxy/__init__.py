"""
Proxy 模块 - DeepSeek OpenAI 兼容代理服务器

模块结构:
- config.py: 配置加载
- auth.py: 访问认证
- deepseek_proxy.py: 核心代理类
- message_utils.py: 消息处理工具
- routes/: Flask 路由蓝图
"""

from .config import load_config, get_base_url_from_chat_url, CONFIG
from .auth import validate_access_key
from .deepseek_proxy import DeepSeekProxy

__all__ = [
    'load_config',
    'get_base_url_from_chat_url', 
    'CONFIG',
    'validate_access_key',
    'DeepSeekProxy',
]
"""
Flask 路由蓝图模块

包含：
- chat: /v1/chat/completions
- models: /v1/models, /v1/balance
- mcp: /v1/mcp/*
- static: 静态页面
"""

from .chat import chat_bp
from .models import models_bp
from .mcp import mcp_bp
from .static import static_bp

__all__ = ['chat_bp', 'models_bp', 'mcp_bp', 'static_bp']
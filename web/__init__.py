"""
Web Management API - 记忆管理Web接口

模块结构：
- api.py           - 主入口，整合所有路由
- core.py          - 核心配置和组件初始化
- config_routes.py - 配置管理 API
- diary_routes.py  - 日记/节点/搜索/统计 API
- backup_routes.py - 备份/恢复 API
- backup.py        - 备份工具（CLI）
- summary_routes.py - 总结生成 API
- pending_routes.py - 待处理摘要 API
- rag_routes.py    - RAG 语义搜索 API
- debug_routes.py  - 调试日志 API
"""

from .api import memory_bp

__all__ = ['memory_bp']
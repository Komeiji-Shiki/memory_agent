"""
Memory Web API - 记忆管理REST API

模块化结构：
- core.py          - 核心配置和组件初始化
- config_routes.py - 配置管理 API
- diary_routes.py  - 日记/节点/搜索/统计 API
- backup_routes.py - 备份/恢复 API
- summary_routes.py - 总结生成 API
- pending_routes.py - 待处理摘要 API
- rag_routes.py    - RAG 语义搜索 API
- debug_routes.py  - 调试日志 API
- backup.py        - 备份工具（CLI）

提供以下接口：
- /api/memory/diaries - 日记列表
- /api/memory/diary/{date} - 日记详情/创建/更新
- /api/memory/nodes - 节点列表
- /api/memory/node/{name} - 节点详情
- /api/memory/search - 搜索
- /api/memory/stats - 统计
- /api/memory/backup - 备份
- /api/memory/rebuild-index - 重建索引
- /api/memory/config - 配置读取/保存
- /api/memory/summary/* - 总结生成
- /api/memory/pending/* - 待处理摘要
- /api/memory/rag/* - RAG 搜索
- /api/memory/debug/* - 调试日志
"""

from flask import Blueprint

# 创建主蓝图
memory_bp = Blueprint('memory_api', __name__, url_prefix='/api/memory')

# 导入各子模块蓝图
from .config_routes import config_bp
from .diary_routes import diary_bp
from .backup_routes import backup_bp
from .summary_routes import summary_bp
from .pending_routes import pending_bp
from .rag_routes import rag_bp
from .debug_routes import debug_bp
from .graph_routes import graph_bp
from .extra_routes import extra_bp
from .orchestrator_routes import orchestrator_bp
from .graphiti_routes import graphiti_bp
from .conversation_routes import conversation_bp


def _register_routes(parent_bp: Blueprint, child_bp: Blueprint):
    """将子蓝图的路由注册到父蓝图"""
    for rule in child_bp.deferred_functions:
        rule(parent_bp)


# 注册所有子路由到主蓝图
_register_routes(memory_bp, config_bp)
_register_routes(memory_bp, diary_bp)
_register_routes(memory_bp, backup_bp)
_register_routes(memory_bp, summary_bp)
_register_routes(memory_bp, pending_bp)
_register_routes(memory_bp, rag_bp)
_register_routes(memory_bp, debug_bp)
_register_routes(memory_bp, graph_bp)
_register_routes(memory_bp, extra_bp)
_register_routes(memory_bp, orchestrator_bp)
_register_routes(memory_bp, graphiti_bp)
_register_routes(memory_bp, conversation_bp)


# 为了兼容性，也导出核心功能
from .core import (
    load_config,
    save_config,
    invalidate_config_cache,
    init_components,
    get_reader,
    get_writer,
    get_indexer,
    get_lifebook_path,
    get_backup_path
)

__all__ = [
    'memory_bp',
    'load_config',
    'save_config',
    'invalidate_config_cache',
    'init_components',
    'get_reader',
    'get_writer',
    'get_indexer',
    'get_lifebook_path',
    'get_backup_path'
]
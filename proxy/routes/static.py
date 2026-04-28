"""
静态页面路由

处理首页和管理页面
"""

import os
from flask import Blueprint, current_app

static_bp = Blueprint('static_pages', __name__)


@static_bp.route('/')
def index():
    """返回首页"""
    return current_app.send_static_file('index.html')


@static_bp.route('/admin')
def admin():
    """MCP 管理界面"""
    return current_app.send_static_file('mcp_admin.html')


@static_bp.route('/lifebook')
@static_bp.route('/lifebook-admin')
@static_bp.route('/memory-admin')
def lifebook_admin():
    """LifeBook 记忆系统管理界面"""
    try:
        # 从项目根目录加载 admin.html
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        admin_path = os.path.join(base_dir, 'web', 'admin.html')
        with open(admin_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"无法加载管理页面: {e}", 500


@static_bp.route('/tools')
def tools_page():
    """MCP 工具列表页面"""
    return current_app.send_static_file('tools.html')


@static_bp.route('/status')
def status_page():
    """健康状态页面"""
    return current_app.send_static_file('health.html')
"""
DeepSeek OpenAI 兼容代理服务器

主入口文件 - 初始化和启动服务器
模块化重构后的代码结构见 proxy/ 目录
"""

import sys
import logging
from logging.handlers import RotatingFileHandler

from flask import Flask

# 导入代理模块
from proxy.config import load_config, CONFIG
from proxy.routes import chat_bp, models_bp, mcp_bp, static_bp
from proxy.routes.chat import set_managers as set_chat_managers
from proxy.routes.models import set_managers as set_models_managers
from proxy.routes.mcp import set_managers as set_mcp_managers


# MCP 支持
try:
    from mcp_servers.mcp_client import get_mcp_manager, MCPManager
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    print("警告: MCP 客户端未找到，MCP 功能将被禁用")

# 记忆系统支持
try:
    from memory_router import MemoryRouter, init_memory_router, get_memory_router
    MEMORY_AVAILABLE = True
except ImportError as e:
    MEMORY_AVAILABLE = False
    print(f"警告: 记忆系统未找到，记忆功能将被禁用: {e}")


def setup_logging(log_file='proxy_server.log', log_level='INFO', debug=False):
    """配置日志记录
    
    Args:
        log_file: 日志文件路径
        log_level: 日志级别字符串 (DEBUG, INFO, WARNING, ERROR)
        debug: 是否启用调试模式，优先级高于 log_level
    """
    # 转换字符串日志级别
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR
    }
    numeric_level = level_map.get(log_level.upper(), logging.INFO)
    
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setFormatter(log_formatter)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if debug else numeric_level)
    
    if logger.hasHandlers():
        logger.handlers.clear()
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    logging.info("日志系统初始化完成")


def create_app(config_path: str = "config.jsonc") -> Flask:
    """创建 Flask 应用"""
    # 加载配置
    config = load_config(config_path)
    
    # 创建 Flask 应用
    app = Flask(__name__, static_folder='static', static_url_path='/static')
    
    # 注册蓝图
    app.register_blueprint(chat_bp)
    app.register_blueprint(models_bp)
    app.register_blueprint(mcp_bp)
    app.register_blueprint(static_bp)
    
    # 注册 Web 管理 API
    try:
        from web.api import memory_bp
        app.register_blueprint(memory_bp)
        print("✓ Web管理API已加载")
    except ImportError as e:
        print(f"警告: Web管理API未加载: {e}")
    
    return app


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='DeepSeek OpenAI 兼容代理服务器')
    parser.add_argument('--config', type=str, default='config.jsonc', help='配置文件路径')
    parser.add_argument('--host', type=str, help='监听地址（覆盖配置文件）')
    parser.add_argument('--port', type=int, help='监听端口（覆盖配置文件）')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    parser.add_argument('--no-mcp', action='store_true', help='禁用 MCP 功能')
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(args.config)
    
    # 设置日志（读取配置的日志级别）
    debug = args.debug or config.get('debug', False)
    log_level = config.get('log_level', 'INFO')
    setup_logging(log_level=log_level, debug=debug)
    
    # 命令行参数覆盖配置
    host = args.host or config.get('host', '127.0.0.1')
    port = args.port or config.get('port', 8002)
    mcp_enabled = config.get('mcp_enabled', True) and not args.no_mcp
    
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    
    print("=" * 60)
    print("DeepSeek OpenAI 兼容代理服务器")
    print("=" * 60)
    print(f"配置文件: {args.config}")
    print(f"日志级别: {log_level}")
    print(f"监听地址: {host}:{port}")
    print(f"管理界面: http://{display_host}:{port}/lifebook-admin")
    print(f"API 端点: http://{display_host}:{port}/v1/chat/completions")
    print(f"后端 API: {config.get('chat_completions_url', 'N/A')}")
    
    # 访问控制状态
    access_keys = config.get('access_keys', [])
    if access_keys:
        print(f"访问控制: 已启用 ({len(access_keys)} 个密钥)")
    else:
        print("访问控制: 已禁用（开放访问）")
    
    if config.get('api_key'):
        print("转发 Key: 已配置")
    else:
        print("转发 Key: 未配置（使用用户 Key）")
    
    # 初始化 MCP
    mcp_manager = None
    if MCP_AVAILABLE and mcp_enabled:
        try:
            mcp_manager = get_mcp_manager()
            print(f"MCP 配置: mcp_servers/ 目录")
            print(f"MCP 服务器: {len(mcp_manager.servers)} 个配置, {len(mcp_manager.connections)} 个运行中")
            print(f"MCP 工具: {len(mcp_manager.tools)} 个可用")
        except Exception as e:
            print(f"MCP 初始化失败: {e}")
            import traceback
            traceback.print_exc()
            mcp_manager = None
    else:
        print("MCP: 已禁用")
    
    # 初始化记忆系统
    memory_router = None
    memory_enabled = config.get('memory_enabled', True)
    if MEMORY_AVAILABLE and memory_enabled:
        try:
            memory_router = init_memory_router(config)
            lifebook_path = config.get('lifebook', {}).get('root_path', './lifebook')
            print(f"记忆系统: 已启用")
            print(f"LifeBook 路径: {lifebook_path}")
            print(f"记忆模式: xxx-memory (检索增强), memory-manager (管理)")
            
            virtual_models = memory_router.get_virtual_models()
            memory_models = [m['id'] for m in virtual_models if 'memory' in m['id']][:3]
            if memory_models:
                print(f"记忆增强模型示例: {', '.join(memory_models)}")
            
        except Exception as e:
            print(f"记忆系统初始化失败: {e}")
            import traceback
            traceback.print_exc()
            memory_router = None
    else:
        if not MEMORY_AVAILABLE:
            print("记忆系统: 模块未加载")
        else:
            print("记忆系统: 已禁用")
    
    # 设置路由模块的全局管理器
    set_chat_managers(mcp_manager, memory_router, MEMORY_AVAILABLE)
    set_models_managers(memory_router, MEMORY_AVAILABLE)
    set_mcp_managers(mcp_manager, MCP_AVAILABLE)
    
    # 创建应用
    app = create_app(args.config)
    
    print(f"Web管理: http://{display_host}:{port}/lifebook-admin")
    print("=" * 60)
    
    # 运行服务器
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
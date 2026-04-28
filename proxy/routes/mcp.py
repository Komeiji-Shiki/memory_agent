"""
MCP 管理路由

处理 /v1/mcp/* 请求
"""

from flask import Blueprint, request, jsonify

# 全局变量
mcp_manager = None
MCP_AVAILABLE = False

mcp_bp = Blueprint('mcp', __name__)


def set_managers(mcp_mgr, mcp_available):
    """设置全局管理器"""
    global mcp_manager, MCP_AVAILABLE
    mcp_manager = mcp_mgr
    MCP_AVAILABLE = mcp_available


@mcp_bp.route('/v1/mcp/status', methods=['GET'])
def mcp_status():
    """获取 MCP 状态"""
    if not MCP_AVAILABLE:
        return jsonify({"error": "MCP 功能不可用"}), 503
    
    if not mcp_manager:
        return jsonify({"error": "MCP 管理器未初始化"}), 503
    
    return jsonify({
        "servers": mcp_manager.get_status(),
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "server": tool.server_name
            }
            for tool in mcp_manager.tools.values()
        ]
    })


@mcp_bp.route('/v1/mcp/tools', methods=['GET'])
def mcp_tools():
    """获取 MCP 工具列表（OpenAI 格式）"""
    if not MCP_AVAILABLE or not mcp_manager:
        return jsonify({"tools": []})
    
    return jsonify({
        "tools": mcp_manager.get_openai_tools()
    })


@mcp_bp.route('/v1/mcp/servers', methods=['GET'])
def mcp_list_servers():
    """列出所有 MCP 服务器"""
    if not MCP_AVAILABLE or not mcp_manager:
        return jsonify({"servers": {}})
    
    return jsonify({
        "servers": mcp_manager.get_status()
    })


@mcp_bp.route('/v1/mcp/servers', methods=['POST'])
def mcp_add_server():
    """添加 MCP 服务器"""
    if not MCP_AVAILABLE:
        return jsonify({"error": "MCP 功能不可用"}), 503
    
    if not mcp_manager:
        return jsonify({"error": "MCP 管理器未初始化"}), 503
    
    data = request.get_json()
    name = data.get('name')
    command = data.get('command')
    args = data.get('args', [])
    description = data.get('description', '')
    enabled = data.get('enabled', True)
    env = data.get('env')
    
    if not name or not command:
        return jsonify({"error": "缺少必要参数: name, command"}), 400
    
    success = mcp_manager.add_server(name, command, args, description, enabled, env)
    
    if success:
        return jsonify({
            "success": True,
            "message": f"服务器 {name} 已添加",
            "status": mcp_manager.get_status().get(name)
        })
    else:
        return jsonify({"error": f"添加服务器 {name} 失败"}), 500


@mcp_bp.route('/v1/mcp/servers/<name>', methods=['DELETE'])
def mcp_remove_server(name: str):
    """移除 MCP 服务器"""
    if not MCP_AVAILABLE or not mcp_manager:
        return jsonify({"error": "MCP 功能不可用"}), 503
    
    success = mcp_manager.remove_server(name)
    
    if success:
        return jsonify({
            "success": True,
            "message": f"服务器 {name} 已移除"
        })
    else:
        return jsonify({"error": f"服务器 {name} 不存在"}), 404


@mcp_bp.route('/v1/mcp/servers/<name>/start', methods=['POST'])
def mcp_start_server(name: str):
    """启动 MCP 服务器"""
    if not MCP_AVAILABLE or not mcp_manager:
        return jsonify({"error": "MCP 功能不可用"}), 503
    
    success = mcp_manager.start_server(name)
    
    if success:
        return jsonify({
            "success": True,
            "message": f"服务器 {name} 已启动",
            "status": mcp_manager.get_status().get(name)
        })
    else:
        return jsonify({"error": f"启动服务器 {name} 失败"}), 500


@mcp_bp.route('/v1/mcp/servers/<name>/stop', methods=['POST'])
def mcp_stop_server(name: str):
    """停止 MCP 服务器"""
    if not MCP_AVAILABLE or not mcp_manager:
        return jsonify({"error": "MCP 功能不可用"}), 503
    
    mcp_manager.stop_server(name)
    
    return jsonify({
        "success": True,
        "message": f"服务器 {name} 已停止"
    })


@mcp_bp.route('/v1/mcp/reload', methods=['POST'])
def mcp_reload():
    """重新加载 MCP 配置"""
    if not MCP_AVAILABLE:
        return jsonify({"error": "MCP 功能不可用"}), 503
    
    if mcp_manager:
        mcp_manager.reload_config()
        return jsonify({
            "success": True,
            "message": "MCP 配置已重新加载",
            "servers": mcp_manager.get_status()
        })
    else:
        return jsonify({"error": "MCP 管理器未初始化"}), 503


@mcp_bp.route('/v1/mcp/servers/all', methods=['GET'])
def mcp_list_all_servers():
    """列出所有可用的 MCP 服务器（包括禁用的）"""
    if not MCP_AVAILABLE:
        return jsonify({"error": "MCP 功能不可用"}), 503
    
    try:
        from mcp_servers import get_available_servers
        servers = get_available_servers()
        
        result = {}
        for name, info in servers.items():
            result[name] = {
                "name": name,
                "type": info.get("type", "stdio"),
                "description": info.get("description", ""),
                "enabled": info.get("enabled", False),
                "config": info.get("config", {}),
                "path": info.get("path", ""),
                "server_file": info.get("server_file"),
                "running": mcp_manager and name in mcp_manager.connections if mcp_manager else False,
                "tools_count": len([t for t in mcp_manager.tools.values() if t.server_name == name]) if mcp_manager else 0
            }
        
        return jsonify({"servers": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@mcp_bp.route('/v1/mcp/servers/<name>/enable', methods=['POST'])
def mcp_enable_server(name: str):
    """启用 MCP 服务器"""
    if not MCP_AVAILABLE:
        return jsonify({"error": "MCP 功能不可用"}), 503
    
    try:
        from mcp_servers import enable_server
        success = enable_server(name)
        
        if success:
            if mcp_manager:
                mcp_manager.reload_config()
            
            return jsonify({
                "success": True,
                "message": f"服务器 {name} 已启用"
            })
        else:
            return jsonify({"error": f"服务器 {name} 不存在"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@mcp_bp.route('/v1/mcp/servers/<name>/disable', methods=['POST'])
def mcp_disable_server(name: str):
    """禁用 MCP 服务器"""
    if not MCP_AVAILABLE:
        return jsonify({"error": "MCP 功能不可用"}), 503
    
    try:
        from mcp_servers import disable_server
        success = disable_server(name)
        
        if success:
            if mcp_manager and name in mcp_manager.connections:
                mcp_manager.stop_server(name)
            
            return jsonify({
                "success": True,
                "message": f"服务器 {name} 已禁用"
            })
        else:
            return jsonify({"error": f"禁用服务器 {name} 失败"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@mcp_bp.route('/v1/mcp/servers/<name>/details', methods=['GET'])
def mcp_server_details(name: str):
    """获取 MCP 服务器详情"""
    if not MCP_AVAILABLE:
        return jsonify({"error": "MCP 功能不可用"}), 503
    
    try:
        from mcp_servers import get_available_servers
        servers = get_available_servers()
        
        if name not in servers:
            return jsonify({"error": f"服务器 {name} 不存在"}), 404
        
        info = servers[name]
        config = info.get("config", {})
        
        # 获取工具列表
        tools = []
        if mcp_manager and name in mcp_manager.connections:
            for tool in mcp_manager.tools.values():
                if tool.server_name == name:
                    tools.append({
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema
                    })
        
        result = {
            "name": name,
            "type": info.get("type", "stdio"),
            "description": info.get("description", ""),
            "enabled": info.get("enabled", False),
            "running": mcp_manager and name in mcp_manager.connections if mcp_manager else False,
            "path": info.get("path", ""),
            "server_file": info.get("server_file"),
            "config": config,
            "tools": tools
        }
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
"""
模型和账户路由

处理 /v1/models, /v1/balance 等请求
"""

import requests
from flask import Blueprint, request, jsonify

from ..config import get_config
from ..auth import validate_access_key

# 全局变量
memory_router = None
MEMORY_AVAILABLE = False

models_bp = Blueprint('models', __name__)


def set_managers(mem_router, mem_available):
    """设置全局管理器"""
    global memory_router, MEMORY_AVAILABLE
    memory_router = mem_router
    MEMORY_AVAILABLE = mem_available


@models_bp.route('/v1/balance', methods=['GET'])
@models_bp.route('/v1/credits', methods=['GET'])
@models_bp.route('/user/balance', methods=['GET'])
def get_balance():
    """查询账号余额"""
    config = get_config()
    
    auth_header = request.headers.get('Authorization', '')
    is_valid, api_key, error_msg = validate_access_key(auth_header)
    if not is_valid:
        return jsonify({"error": {"message": error_msg, "type": "auth_error"}}), 401
    
    balance_url = "https://api.deepseek.com/user/balance"
    
    try:
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        response = requests.get(balance_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({
                "error": {
                    "message": f"Failed to fetch balance: {response.status_code}",
                    "type": "api_error"
                }
            }), response.status_code
            
    except requests.exceptions.Timeout:
        return jsonify({
            "error": {
                "message": "Request to balance API timed out",
                "type": "timeout_error"
            }
        }), 504
    except Exception as e:
        return jsonify({
            "error": {
                "message": f"Failed to fetch balance: {str(e)}",
                "type": "server_error"
            }
        }), 500


@models_bp.route('/models', methods=['GET'])
@models_bp.route('/v1/models', methods=['GET'])
def list_models():
    """列出可用模型"""
    print(f"[API] 收到模型列表请求: {request.path}")
    
    config = get_config()
    models = []
    
    if MEMORY_AVAILABLE and memory_router:
        models = memory_router.get_virtual_models()
    else:
        model_routes = config.get('model_routes', {})
        for model_id in model_routes.keys():
            if model_id.startswith("_"):
                continue
            # 原始模型
            models.append({
                "id": model_id,
                "object": "model",
                "owned_by": "proxy",
                "permission": []
            })
            # 记忆增强版本
            models.append({
                "id": f"{model_id}-memory",
                "object": "model",
                "owned_by": "lifebook-proxy",
                "permission": []
            })
        
        # 记忆管理模型
        manager_ids = config.get("memory_manager", {}).get("model_ids", ["memory-manager"])
        for model_id in manager_ids:
            models.append({
                "id": model_id,
                "object": "model",
                "owned_by": "lifebook-proxy",
                "permission": []
            })
    
    return jsonify({
        "object": "list",
        "data": models
    })


@models_bp.route('/health', methods=['GET'])
def health():
    """健康检查"""
    from . import mcp as mcp_module
    
    mcp_manager = getattr(mcp_module, 'mcp_manager', None)
    
    status = {"status": "ok"}
    
    if mcp_manager:
        status["mcp"] = {
            "available": True,
            "servers": mcp_manager.get_status(),
            "tools_count": len(mcp_manager.tools)
        }
    else:
        status["mcp"] = {"available": False}
    
    return jsonify(status)
"""
配置管理路由

提供配置的查看、热重载和管理接口。

端点：
- GET /api/memory/config - 获取当前配置（脱敏）
- POST /api/memory/config - 保存配置
- POST /api/memory/config/reload - 手动重载配置
- GET /api/memory/config/status - 获取配置热重载状态
- GET /api/memory/config/model_routes - 获取模型路由
"""

import json
import os
import requests
from flask import Blueprint, jsonify, request

# 导入原始配置模块
try:
    from proxy.config import get_config, reload_config
except ImportError:
    def get_config() -> dict:
        return {}
    def reload_config() -> bool:
        return False

# 敏感配置项
SENSITIVE_KEYS = {
    "api_key", "access_keys", "password", "secret", "token", "auth", "credential",
}


def mask_sensitive_value(key: str, value) -> any:
    """脱敏敏感值"""
    key_lower = key.lower()
    for sensitive in SENSITIVE_KEYS:
        if sensitive in key_lower:
            if isinstance(value, str):
                return value[:2] + "****" + value[-2:] if len(value) > 4 else "****"
            elif isinstance(value, list):
                return [mask_sensitive_value(key, v) for v in value]
            return "****"
    
    if isinstance(value, dict):
        return {k: mask_sensitive_value(k, v) for k, v in value.items()}
    return value


def _load_raw_config() -> dict:
    """Load raw config from disk (preferred) with a safe fallback."""
    try:
        from web.core import load_config as core_load_config
        return core_load_config(force_reload=False)
    except Exception:
        return get_config()



def get_safe_config(config=None) -> dict:
    """????????"""
    raw_config = _load_raw_config() if config is None else config
    return mask_sensitive_value("root", raw_config)


def _is_masked(value) -> bool:
    return isinstance(value, str) and "****" in value


def _merge_config(existing: dict, incoming: dict) -> dict:
    """递归合并配置，保留被脱敏的敏感字段"""
    if not isinstance(incoming, dict):
        return incoming
    merged = dict(existing) if isinstance(existing, dict) else {}
    for key, value in incoming.items():
        if isinstance(value, dict):
            merged[key] = _merge_config(merged.get(key, {}), value)
            continue
        key_lower = str(key).lower()
        if any(s in key_lower for s in SENSITIVE_KEYS) and _is_masked(value):
            if key in merged:
                continue
        merged[key] = value
    return merged


def _normalize_models_base_url(base_url: str) -> str:
    """将模型接口地址归一化为 base_url（通常以 /v1 结尾）"""
    value = str(base_url or "").strip()
    if not value:
        raise ValueError("缺少 API 地址")
    if not value.startswith(("http://", "https://")):
        raise ValueError("API 地址必须以 http:// 或 https:// 开头")

    value = value.rstrip("/")
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    elif value.endswith("/models"):
        value = value[: -len("/models")]

    return value.rstrip("/")


def _resolve_model_route_api_key(config: dict, route_name: str, incoming_key) -> str:
    """优先使用前端传入明文 key，否则回退到已保存的路由 key"""
    if isinstance(incoming_key, str):
        api_key = incoming_key.strip()
        if api_key and "****" not in api_key:
            return api_key

    if route_name:
        route_config = config.get("model_routes", {}).get(route_name, {})
        if isinstance(route_config, dict):
            saved_key = route_config.get("api_key")
            if isinstance(saved_key, str) and saved_key:
                return saved_key

    return ""


# 创建蓝图 - 注意：这里使用空前缀，实际前缀在 api.py 中统一处理
config_bp = Blueprint('config', __name__, url_prefix='')


@config_bp.route('/config', methods=['GET'])
def get_config_endpoint():
    """获取当前配置（默认脱敏，可选返回明文）"""
    try:
        reveal_secrets = str(request.args.get("reveal_secrets", "")).lower() in {"1", "true", "yes", "on"}
        raw_config = _load_raw_config()
        cfg = raw_config if reveal_secrets else get_safe_config(raw_config)
        return jsonify({
            "success": True,
            "config": cfg
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@config_bp.route('/config', methods=['POST'])
def save_config_endpoint():
    """保存配置"""
    try:
        from web.core import save_config as core_save_config, load_config as core_load_config
        
        config = core_load_config()
        data = request.get_json()
        
        if not data:
            return jsonify({"success": False, "error": "缺少配置数据"}), 400
        
        # 更新配置（默认跳过敏感字段，但允许更新顶层 api_key）
        for key, value in data.items():
            # 顶层敏感字段处理
            if key in SENSITIVE_KEYS:
                if key == "api_key":
                    # 前端可能传来脱敏占位符：此时保留原值
                    if _is_masked(value):
                        continue
                    config[key] = value
                # 其他敏感字段仍跳过（如 access_keys/password/token 等）
                continue

            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key] = _merge_config(config.get(key, {}), value)
            else:
                config[key] = value
        
        # 保存
        core_save_config(config)
        
        # 触发重载
        reload_config()
        
        return jsonify({
            "success": True,
            "message": "配置已保存"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@config_bp.route('/config/reload', methods=['POST'])
def reload_config_endpoint():
    """手动重载配置"""
    try:
        success = reload_config()
        return jsonify({
            "success": success,
            "message": "配置已重新加载" if success else "配置重载失败"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@config_bp.route('/config/status', methods=['GET'])
def get_status_endpoint():
    """获取配置状态"""
    try:
        return jsonify({
            "success": True,
            "status": {
                "config_exists": os.path.exists("config.jsonc")
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@config_bp.route('/config/model_routes', methods=['GET'])
def get_model_routes_endpoint():
    """获取模型路由配置"""
    try:
        config = _load_raw_config()
        model_routes = config.get("model_routes", {})
        
        reveal_secrets = str(request.args.get("reveal_secrets", "")).lower() in {"1", "true", "yes", "on"}
        
        # 默认脱敏；当 reveal_secrets=1 时返回原始 api_key 供前端查看
        safe_routes: dict = {}
        for key, value in model_routes.items():
            if isinstance(value, dict):
                safe_value: dict = {}
                for k, v in value.items():
                    k_lower = str(k).lower()
                    
                    # api_key：可选返回明文（前端查看已配置的原始密钥）
                    if k_lower == "api_key":
                        if reveal_secrets:
                            safe_value[k] = v
                        elif isinstance(v, str):
                            safe_value[k] = v[:4] + "****" + v[-4:] if len(v) > 8 else "****"
                        else:
                            safe_value[k] = v
                        continue
                    
                    # 其他敏感字段一律不返回
                    if any(s in k_lower for s in SENSITIVE_KEYS):
                        continue
                    
                    safe_value[k] = v
                safe_routes[key] = safe_value
            else:
                safe_routes[key] = value
        
        # 前端期望 data.value 格式
        return jsonify({
            "success": True,
            "value": safe_routes
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@config_bp.route('/config/model_routes/models', methods=['POST'])
def fetch_model_route_models_endpoint():
    """根据 API 地址获取模型列表"""
    try:
        data = request.get_json(silent=True) or {}
        raw_base_url = data.get('base_url')
        if not raw_base_url:
            return jsonify({"success": False, "error": "缺少 base_url"}), 400

        config = _load_raw_config()
        route_name = str(data.get('route_name') or '').strip()
        base_url = _normalize_models_base_url(str(raw_base_url))
        api_key = _resolve_model_route_api_key(config, route_name, data.get('api_key'))

        headers = {'Accept': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        models_url = f'{base_url}/models'
        response = requests.get(models_url, headers=headers, timeout=15)

        try:
            payload = response.json()
        except ValueError:
            return jsonify({
                "success": False,
                "error": f"模型接口返回了非 JSON 响应（HTTP {response.status_code}）"
            }), 502

        if response.status_code >= 400:
            error_message = None
            if isinstance(payload, dict):
                error_obj = payload.get('error')
                if isinstance(error_obj, dict):
                    error_message = error_obj.get('message')
                elif isinstance(error_obj, str):
                    error_message = error_obj

            return jsonify({
                "success": False,
                "error": error_message or f"模型接口请求失败（HTTP {response.status_code}）",
                "status_code": response.status_code
            }), response.status_code

        model_items = payload.get('data')
        if not isinstance(model_items, list):
            return jsonify({
                "success": False,
                "error": "模型接口返回格式不是 OpenAI 兼容的 data 列表"
            }), 502

        model_ids = sorted({
            str(item.get('id')).strip()
            for item in model_items
            if isinstance(item, dict) and str(item.get('id') or '').strip()
        })

        return jsonify({
            "success": True,
            "base_url": base_url,
            "models_url": models_url,
            "models": model_ids
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "请求模型接口超时"}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "error": f"请求模型接口失败: {e}"}), 502
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@config_bp.route('/config/model_routes', methods=['POST', 'PUT'])
def update_model_routes_endpoint():
    """更新模型路由配置"""
    try:
        from web.core import save_config as core_save_config, load_config as core_load_config
        
        config = core_load_config()
        data = request.get_json()
        
        if not data:
            return jsonify({"success": False, "error": "缺少数据"}), 400
        
        # 兼容两种格式：{ value: {...} } 或 { model_routes: {...} }
        new_routes = data.get('value') or data.get('model_routes')
        if not new_routes:
            return jsonify({"success": False, "error": "缺少 value 或 model_routes"}), 400
        
        # 合并 api_key：如果前端传来的是脱敏值，保留原有的 api_key
        existing_routes = config.get('model_routes', {})
        for route_name, route_config in new_routes.items():
            if isinstance(route_config, dict) and 'api_key' in route_config:
                # 检查是否是脱敏值（包含 ****）
                if '****' in route_config.get('api_key', ''):
                    # 保留原有的 api_key
                    if route_name in existing_routes and 'api_key' in existing_routes[route_name]:
                        route_config['api_key'] = existing_routes[route_name]['api_key']
        
        config['model_routes'] = new_routes
        core_save_config(config)
        
        # 热重载：保存后立即刷新内存配置，确保新增模型无需重启即可生效
        try:
            reload_config()
        except Exception as e:
            # 热重载失败不影响保存，但记录错误
            return jsonify({"success": False, "error": f"已保存但重载失败: {e}"}), 500
        
        return jsonify({"success": True, "message": "模型路由已更新并已重载"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

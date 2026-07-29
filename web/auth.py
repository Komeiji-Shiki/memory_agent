"""
Web 管理 API 认证

安全策略（挂在 memory_bp 的 before_request 上，覆盖 /api/memory/* 全部路由）：

- 回环地址（127.0.0.1 / ::1）请求且未开启 require_auth：直接放行，本机使用零打扰；
- 非回环地址请求：无论 require_auth 如何设置，一律要求有效密钥（安全默认，
  防止 host 配成 0.0.0.0 后管理面板裸奔）；
- require_auth = true：回环地址也要求密钥；
- 密钥来源：web_api.access_keys，未配置时回退顶层 access_keys；
- 密钥传递：请求头 X-API-Key: <key> 或 Authorization: Bearer <key>。
"""

import ipaddress
import logging

from flask import request

from .core import load_config
from .errors import api_error_response

logger = logging.getLogger(__name__)


def _is_loopback(addr: str) -> bool:
    """判断请求来源是否为回环地址"""
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def _extract_key() -> str:
    """从请求头提取密钥（X-API-Key 优先，其次 Authorization: Bearer）"""
    key = request.headers.get("X-API-Key", "")
    if key:
        return key.strip()
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):].strip()
    return ""


def require_web_auth():
    """
    管理 API 认证守卫（before_request）。

    Returns:
        None 表示放行；否则返回 (response, status) 拒绝请求。
    """
    # CORS 预检请求不携带自定义头，直接放行（真正的请求仍会被校验）
    if request.method == "OPTIONS":
        return None

    config = load_config()
    web_cfg = config.get("web_api", {})
    require_auth = bool(web_cfg.get("require_auth", False))

    is_local = _is_loopback(request.remote_addr or "")

    if is_local and not require_auth:
        return None

    valid_keys = web_cfg.get("access_keys") or config.get("access_keys") or []
    if not valid_keys:
        if is_local:
            # require_auth 已开启但未配置密钥：放行本机并告警，避免把管理员锁在门外
            logger.warning(
                "[WebAuth] web_api.require_auth 已开启但未配置任何密钥"
                "（web_api.access_keys / access_keys 均为空），本机请求放行"
            )
            return None
        logger.warning(
            "[WebAuth] 拒绝非本机访问 %s %s（来源 %s）：未配置管理密钥",
            request.method, request.path, request.remote_addr,
        )
        return api_error_response(
            "管理 API 未配置访问密钥，拒绝非本机访问。"
            "请在 config.jsonc 的 web_api.access_keys 或 access_keys 中配置密钥。",
            status=403,
            code="FORBIDDEN",
        )

    key = _extract_key()
    if key and key in valid_keys:
        return None

    logger.warning(
        "[WebAuth] 认证失败 %s %s（来源 %s）",
        request.method, request.path, request.remote_addr,
    )
    return api_error_response(
        "需要有效的管理密钥：请求头 X-API-Key: <key> 或 Authorization: Bearer <key>",
        status=401,
        code="UNAUTHORIZED",
    )

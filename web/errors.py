"""
统一 Web API 错误处理。

目标：
- 保持错误响应格式统一；
- 将异常文本返回给前端，便于管理台直接展示和排查；
- 所有未预期异常仍写入服务端日志，并附带 request_id 方便定位；
- 不返回 traceback，避免响应体过大。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Mapping, Optional

from flask import Blueprint, has_request_context, jsonify, request
from werkzeug.exceptions import HTTPException


logger = logging.getLogger("lifebook.web.api")

DEFAULT_INTERNAL_ERROR_MESSAGE = "服务器内部错误"


class ApiError(Exception):
    """可安全返回给前端的 API 错误。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = "BAD_REQUEST",
        details: Optional[Any] = None,
        log_message: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details
        self.log_message = log_message


def _make_request_id() -> str:
    """生成或复用请求 ID。"""
    if has_request_context():
        incoming = request.headers.get("X-Request-ID")
        if incoming:
            return incoming[:128]
    return uuid.uuid4().hex[:12]


def _request_log_context() -> str:
    """获取适合写入日志的请求上下文。"""
    if not has_request_context():
        return "request_context=unavailable"
    return (
        f"method={request.method} path={request.path} "
        f"remote_addr={request.remote_addr or '-'}"
    )


def api_error_response(
    message: str,
    *,
    status: int = 500,
    code: Optional[str] = None,
    details: Optional[Any] = None,
    extra: Optional[Mapping[str, Any]] = None,
    request_id: Optional[str] = None,
):
    """构造统一错误响应。"""
    rid = request_id or _make_request_id()
    payload: dict[str, Any] = {
        "success": False,
        "error": message,
        "error_code": code or ("INTERNAL_ERROR" if status >= 500 else "BAD_REQUEST"),
        "request_id": rid,
    }

    if details is not None:
        payload["details"] = details
    if extra:
        payload.update(extra)

    response = jsonify(payload)
    response.headers["X-Request-ID"] = rid
    return response, status


def _exception_message(exc: Exception) -> str:
    """把异常转换成适合前端展示的文本。"""
    message = str(exc).strip()
    if message:
        return message
    return exc.__class__.__name__


def handle_api_exception(
    exc: Exception,
    context: str = "Web API",
    *,
    message: Optional[str] = None,
    status: int = 500,
    code: str = "INTERNAL_ERROR",
    extra: Optional[Mapping[str, Any]] = None,
):
    """记录异常并返回统一 API 错误响应。"""
    request_id = _make_request_id()

    if isinstance(exc, ApiError):
        log_text = exc.log_message or exc.message
        if exc.status_code >= 500:
            logger.error(
                "Web API error [%s] %s context=%s message=%s",
                request_id,
                _request_log_context(),
                context,
                log_text,
                exc_info=True,
            )
        else:
            logger.warning(
                "Web API client error [%s] %s context=%s message=%s",
                request_id,
                _request_log_context(),
                context,
                log_text,
            )
        return api_error_response(
            exc.message,
            status=exc.status_code,
            code=exc.code,
            details=exc.details,
            extra=extra,
            request_id=request_id,
        )

    if isinstance(exc, HTTPException):
        status_code = exc.code or 500
        public_message = message or exc.description or _exception_message(exc)
        logger.warning(
            "Web API HTTPException [%s] %s context=%s status=%s message=%s",
            request_id,
            _request_log_context(),
            context,
            status_code,
            exc.description,
            exc_info=status_code >= 500,
        )
        return api_error_response(
            public_message,
            status=status_code,
            code=exc.name.upper().replace(" ", "_") if exc.name else code,
            extra=extra,
            request_id=request_id,
        )

    logger.error(
        "Web API unexpected exception [%s] %s context=%s exception=%r",
        request_id,
        _request_log_context(),
        context,
        exc,
        exc_info=True,
    )
    return api_error_response(
        message or _exception_message(exc) or DEFAULT_INTERNAL_ERROR_MESSAGE,
        status=status,
        code=code,
        extra=extra,
        request_id=request_id,
    )


def log_nonfatal_exception(exc: Exception, context: str) -> None:
    """记录不影响接口主流程的非致命异常。"""
    logger.warning(
        "Web API non-fatal exception %s context=%s exception=%r",
        _request_log_context(),
        context,
        exc,
        exc_info=True,
    )


def register_error_handlers(blueprint: Blueprint) -> None:
    """给 Web API 蓝图注册兜底错误处理器。"""

    @blueprint.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return handle_api_exception(exc, "blueprint ApiError")

    @blueprint.errorhandler(HTTPException)
    def _handle_http_error(exc: HTTPException):
        return handle_api_exception(exc, "blueprint HTTPException")

    @blueprint.errorhandler(Exception)
    def _handle_unexpected_error(exc: Exception):
        return handle_api_exception(exc, "blueprint unexpected exception")

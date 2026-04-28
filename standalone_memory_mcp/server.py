#!/usr/bin/env python3
"""
Standalone Memory MCP Server

目标：
- 将本项目现有记忆系统工具（MemoryTools）通过 MCP stdio 暴露出去
- 供任意外部 MCP 客户端接入（如 Claude Code / 其他支持 MCP 的客户端）
- 不依赖当前项目内置的 mcp_servers 管理目录

协议：
- initialize
- notifications/initialized
- tools/list
- tools/call
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"

# 兼容别名：对齐项目内历史工具名
COMPAT_TOOL_ALIASES: Dict[str, str] = {
    "get_current_time": "get_current_context",
}


def _stderr(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _ensure_stdio_utf8() -> None:
    """确保 stdio 使用 UTF-8，避免 Windows 代码页导致 MCP 中文乱码。"""
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdin, "buffer"):
                sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
            if hasattr(sys.stdout, "buffer"):
                sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
            if hasattr(sys.stderr, "buffer"):
                sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
        except Exception:
            # 不阻断启动，降级使用系统默认编码
            pass


def _jsonrpc_result(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "result": result,
    }


def _jsonrpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


class MemoryBackend:
    """封装 MemoryTools 初始化与工具调用。"""

    def __init__(
        self,
        project_root: Path,
        config_path: Path,
        enable_write: bool,
    ) -> None:
        self.project_root = project_root
        self.config_path = config_path
        self.enable_write = enable_write

        self._memory_tools = None
        self._tool_map: Dict[str, Any] = {}
        self._alias_map: Dict[str, str] = {}

    def initialize(self) -> None:
        # 1) 注入项目路径，保证可导入 memory_agent / proxy 等模块
        if str(self.project_root) not in sys.path:
            sys.path.insert(0, str(self.project_root))

        # 2) 加载配置（避免 load_config 的 stdout 打印污染 MCP 协议）
        with redirect_stdout(sys.stderr):
            from proxy.config import enable_hot_reload, load_config

            enable_hot_reload(False)
            config = load_config(str(self.config_path))

        # 3) 解析路径与配置
        lifebook_cfg = config.get("lifebook", {})
        lifebook_path_raw = lifebook_cfg.get("root_path", "./lifebook")
        encoding = lifebook_cfg.get("encoding", "utf-8")

        lifebook_path = Path(lifebook_path_raw)
        if not lifebook_path.is_absolute():
            lifebook_path = (self.project_root / lifebook_path).resolve()

        rag_cfg = config.get("rag", {})
        graphiti_cfg = config.get("graphiti", {})

        # 4) 初始化 MemoryTools（同样避免 stdout 污染）
        with redirect_stdout(sys.stderr):
            from memory_store.rag import RAGConfig
            from memory_agent.tools import MemoryTools

            rag_config = RAGConfig(
                api_key=rag_cfg.get("api_key", ""),
                model=rag_cfg.get("model", "Qwen/Qwen3-Embedding-8B"),
                base_url=rag_cfg.get("base_url", "https://api.siliconflow.cn/v1/embeddings"),
                chunk_size=rag_cfg.get("chunk_size", 500),
                chunk_overlap=rag_cfg.get("chunk_overlap", 50),
                top_k=rag_cfg.get("top_k", 5),
                similarity_threshold=rag_cfg.get("similarity_threshold", 0.3),
                enabled=rag_cfg.get("enabled", False),
            )

            self._memory_tools = MemoryTools(
                lifebook_path=str(lifebook_path),
                enable_write=self.enable_write,
                encoding=encoding,
                rag_config=rag_config if rag_config.enabled else None,
                graphiti_config=graphiti_cfg if graphiti_cfg.get("enabled", False) else None,
            )

        # 5) 构建工具映射
        available_tools = self._memory_tools.get_available_tools(include_write=self.enable_write)
        self._tool_map = {tool.name: tool for tool in available_tools}

        # 6) 注入兼容别名（如别名未被原生工具注册）
        for alias, target in COMPAT_TOOL_ALIASES.items():
            if alias not in self._tool_map and target in self._tool_map:
                self._alias_map[alias] = target
                base = self._tool_map[target]
                self._tool_map[alias] = type(
                    "AliasTool",
                    (),
                    {
                        "name": alias,
                        "description": f"{base.description}（兼容别名，映射到 {target}）",
                        "parameters": base.parameters,
                    },
                )()

        _stderr(
            f"[memory-mcp] initialized. tools={len(self._tool_map)}, "
            f"enable_write={self.enable_write}, lifebook={lifebook_path}"
        )

    @property
    def tool_names(self) -> List[str]:
        return sorted(self._tool_map.keys())

    def list_tools_payload(self) -> List[Dict[str, Any]]:
        tools: List[Dict[str, Any]] = []
        for name in self.tool_names:
            tool = self._tool_map[name]
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.parameters,
                }
            )
        return tools

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        resolved_name = self._alias_map.get(name, name)

        if resolved_name not in self._tool_map:
            return (
                {
                    "content": [
                        {
                            "type": "text",
                            "text": f"错误：未知工具 '{name}'",
                        }
                    ],
                    "isError": True,
                },
                True,
            )

        if not isinstance(arguments, dict):
            arguments = {}

        # 避免内部 print 输出污染 stdout
        with redirect_stdout(sys.stderr):
            text = self._memory_tools.call_tool(resolved_name, arguments)

        is_error = bool(
            text.startswith("错误")
            or text.startswith("✗")
            or text.lower().startswith("error")
        )

        payload: Dict[str, Any] = {
            "content": [
                {
                    "type": "text",
                    "text": text,
                }
            ]
        }
        if is_error:
            payload["isError"] = True

        return payload, is_error


class MemoryMCPServer:
    """最小 MCP stdio 服务器。"""

    def __init__(self, backend: MemoryBackend) -> None:
        self.backend = backend

    def handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = message.get("method")
        request_id = message.get("id")

        # Notification 无需返回，但也允许处理
        is_notification = request_id is None

        if method == "initialize":
            result = {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "standalone-memory-mcp",
                    "version": "1.0.0",
                },
            }
            return _jsonrpc_result(request_id, result)

        if method == "notifications/initialized":
            return None

        if method == "tools/list":
            result = {"tools": self.backend.list_tools_payload()}
            return _jsonrpc_result(request_id, result)

        if method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments", {})

            if not name or not isinstance(name, str):
                return _jsonrpc_error(request_id, -32602, "Invalid params: missing tool name")

            result, _ = self.backend.call_tool(name, arguments)
            return _jsonrpc_result(request_id, result)

        if is_notification:
            return None

        return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")


def _parse_args() -> argparse.Namespace:
    default_project_root = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(description="Standalone Memory MCP Server (stdio)")
    parser.add_argument(
        "--project-root",
        type=str,
        default=str(default_project_root),
        help="Memory 项目根目录（默认：当前脚本上级目录）",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="",
        help="配置文件路径（默认：<project-root>/config.jsonc）",
    )
    parser.add_argument(
        "--enable-write",
        type=str,
        default="true",
        help="是否启用写入工具（true/false，默认 true）",
    )
    return parser.parse_args()


def main() -> int:
    _ensure_stdio_utf8()
    args = _parse_args()

    project_root = Path(args.project_root).resolve()
    config_path = Path(args.config).resolve() if args.config else (project_root / "config.jsonc").resolve()
    enable_write = _parse_bool(args.enable_write)

    if not project_root.exists():
        _stderr(f"[memory-mcp] project root not found: {project_root}")
        return 1

    if not config_path.exists():
        _stderr(f"[memory-mcp] config not found: {config_path}")
        return 1

    backend = MemoryBackend(
        project_root=project_root,
        config_path=config_path,
        enable_write=enable_write,
    )

    try:
        backend.initialize()
    except Exception as e:
        _stderr(f"[memory-mcp] init failed: {e}")
        return 1

    server = MemoryMCPServer(backend)

    while True:
        line = sys.stdin.readline()
        if not line:
            break

        line = line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            error = _jsonrpc_error(None, -32700, "Parse error: invalid JSON")
            sys.stdout.write(json.dumps(error, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue

        try:
            response = server.handle_message(message)
        except Exception as e:
            response = _jsonrpc_error(message.get("id"), -32603, f"Internal error: {e}")

        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
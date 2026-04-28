#!/usr/bin/env python3
from __future__ import annotations

"""
Hardened Windows CMD MCP server.

Goals:
- Restrict command execution to a workspace root
- Block obviously dangerous / destructive commands at the server layer
- Disable batch execution by default unless explicitly enabled by environment
- Provide command analysis before execution
- Keep compatibility with existing tool names
"""

import asyncio
import json
import locale
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


SERVER_NAME = "windows-cmd"
SERVER_VERSION = "2.0.0"

DEFAULT_TIMEOUT = 60
DEFAULT_INTERACTIVE_TIMEOUT = 120
DEFAULT_MAX_TIMEOUT = 300
AUDIT_LOG_FILENAME = ".mcp_cmd_audit.jsonl"

SAFE_EXECUTABLES_STRICT = {
    "dir",
    "echo",
    "type",
    "more",
    "where",
    "whoami",
    "hostname",
    "ver",
    "chcp",
    "git",
    "python",
    "py",
    "pytest",
    "node",
    "npm",
    "pnpm",
    "bun",
    "uv",
    "cargo",
    "go",
    "dotnet",
    "cmake",
    "ninja",
    "java",
    "javac",
}

ALWAYS_BLOCK_EXECUTABLES = {
    "bcdedit",
    "cipher",
    "diskpart",
    "format",
    "manage-bde",
    "mountvol",
    "shutdown",
    "vssadmin",
    "wbadmin",
}

NETWORK_EXECUTABLES = {
    "curl",
    "wget",
    "bitsadmin",
    "certutil",
    "ftp",
    "tftp",
}

DESTRUCTIVE_PATTERNS: List[Tuple[str, str]] = [
    (r"(^|[&|()])\s*(?:del|erase)\b", "检测到删除文件命令"),
    (r"(^|[&|()])\s*(?:rd|rmdir)\b", "检测到删除目录命令"),
    (r"(^|[&|()])\s*format\b", "检测到格式化磁盘命令"),
    (r"(^|[&|()])\s*diskpart\b", "检测到磁盘分区操作"),
    (r"(^|[&|()])\s*shutdown\b", "检测到关机或重启命令"),
    (r"(^|[&|()])\s*taskkill\b", "检测到强制结束进程命令"),
    (r"(^|[&|()])\s*(?:reg|reg\.exe)\s+(?:add|delete|import|restore|load|unload|save)\b", "检测到注册表修改命令"),
    (r"(^|[&|()])\s*(?:sc|sc\.exe)\s+(?:create|config|delete|start|stop)\b", "检测到系统服务修改命令"),
    (r"(^|[&|()])\s*(?:schtasks)\s+/(?:create|delete|change|run|end)\b", "检测到计划任务修改命令"),
    (r"(^|[&|()])\s*(?:takeown|icacls)\b", "检测到权限接管或修改命令"),
    (r"(^|[&|()])\s*(?:net|net1)\s+(?:user|localgroup|share|use)\b", "检测到账户或共享管理命令"),
    (r"(^|[&|()])\s*(?:vssadmin|wbadmin|manage-bde|mountvol|bcdedit|cipher)\b", "检测到系统级存储或启动配置命令"),
    (r"\bgit\s+reset\b[^&|]*--hard\b", "检测到 destructive git reset --hard"),
    (r"\bgit\s+clean\b[^&|]*-(?:[A-Za-z]*f[A-Za-z]*d|[A-Za-z]*d[A-Za-z]*f|xfd|xdf)\b", "检测到 destructive git clean"),
    (r"\bgit\s+push\b[^&|]*--force(?:-with-lease)?\b", "检测到 force push"),
    (r"\bgit\s+checkout\b[^&|]*\s--\s*\.?", "检测到 checkout 覆盖工作区命令"),
]

CRITICAL_BLOCK_PATTERNS: List[Tuple[str, str]] = [
    (r"(^|[&|()])\s*format\b", "禁止格式化磁盘"),
    (r"(^|[&|()])\s*diskpart\b", "禁止磁盘分区操作"),
    (r"(^|[&|()])\s*shutdown\b", "禁止关机或重启"),
    (r"(^|[&|()])\s*(?:vssadmin|wbadmin|manage-bde|mountvol|bcdedit|cipher)\b", "禁止系统级存储或启动配置操作"),
]

INLINE_SCRIPT_PATTERNS: List[Tuple[str, str]] = [
    (r"(^|[&|()])\s*(?:python|py)\b[^&|]*\s-c\b", "禁止 Python 内联脚本执行"),
    (r"(^|[&|()])\s*node\b[^&|]*\s-e\b", "禁止 Node.js 内联脚本执行"),
    (r"(^|[&|()])\s*bun\b[^&|]*\s(?:-e|x)\b", "禁止 Bun 内联脚本执行"),
    (r"(^|[&|()])\s*(?:cmd|cmd\.exe)\b[^&|]*\s/(?:c|k)\b", "禁止在命令中再次嵌套 cmd"),
]

DOWNLOAD_EXECUTION_PATTERNS: List[Tuple[str, str]] = [
    (r"\bcurl\b[^|&]*\|\s*(?:cmd|powershell|pwsh)\b", "禁止下载后直接执行"),
    (r"\bcertutil\b[^|&]*\s-urlcache\b", "禁止通过 certutil 下载内容"),
    (r"\bbitsadmin\b", "禁止通过 bitsadmin 下载内容"),
    (r"\b(?:powershell|pwsh)\b[^|&]*\b(?:iex|invoke-expression|invoke-webrequest|irm)\b", "禁止 PowerShell 下载执行"),
]

BATCH_EXTENSIONS = {".bat", ".cmd"}


@dataclass(frozen=True)
class CommandSafetyResult:
    allowed: bool
    risk_level: str
    reasons: List[str]
    matched_rules: List[str]
    executables: List[str]
    shell_features: List[str]
    policy_mode: str


def parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def to_posix_path(value: str) -> str:
    return value.replace("\\", "/")


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class HardenedCMDServer:
    def __init__(self, workspace_root: Path):
        self.workspace_root = self._resolve_root(workspace_root)
        self.policy_mode = os.environ.get("CMD_POLICY_MODE", "balanced").strip().lower() or "balanced"
        if self.policy_mode not in {"balanced", "strict"}:
            self.policy_mode = "balanced"

        self.max_timeout = self._parse_positive_int(os.environ.get("CMD_MAX_TIMEOUT"), DEFAULT_MAX_TIMEOUT)
        self.allow_batch = parse_bool(os.environ.get("CMD_ALLOW_BATCH"), default=False)
        self.allow_network = parse_bool(os.environ.get("CMD_ALLOW_NETWORK"), default=False)
        self.allow_powershell = parse_bool(os.environ.get("CMD_ALLOW_POWERSHELL"), default=False)
        self.allow_shell_operators = parse_bool(os.environ.get("CMD_ALLOW_SHELL_OPERATORS"), default=False)
        self.allow_pipes = parse_bool(os.environ.get("CMD_ALLOW_PIPES"), default=False)
        self.allow_redirection = parse_bool(os.environ.get("CMD_ALLOW_REDIRECTION"), default=False)
        self.audit_log_path = self.workspace_root / AUDIT_LOG_FILENAME
        self.default_encoding = locale.getpreferredencoding(False) or "utf-8"

        self.tools = [
            {
                "name": "analyze_cmd",
                "description": "分析 CMD 命令的安全级别、命中的阻断规则和工作目录信息，不执行命令。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "要分析的 CMD 命令"},
                        "cwd": {"type": "string", "description": "工作目录，默认当前目录", "default": None},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "execute_cmd",
                "description": "在受限的 Windows CMD 环境中执行命令。命令会经过服务端安全分析与危险命令阻断。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "要执行的 CMD 命令"},
                        "timeout": {"type": "number", "description": "超时时间（秒），默认60秒", "default": DEFAULT_TIMEOUT},
                        "cwd": {"type": "string", "description": "工作目录，支持相对路径和绝对路径", "default": None},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "execute_cmd_interactive",
                "description": "兼容保留：仍然执行 CMD 命令，但同样受服务端安全限制。注意它并不支持真实交互输入，只是使用较长超时。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "要执行的 CMD 命令"},
                        "timeout": {
                            "type": "number",
                            "description": "超时时间（秒），默认120秒",
                            "default": DEFAULT_INTERACTIVE_TIMEOUT,
                        },
                        "cwd": {"type": "string", "description": "工作目录，支持相对路径和绝对路径", "default": None},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "run_batch_file",
                "description": "执行批处理文件(.bat/.cmd)。默认禁用，需通过环境变量 CMD_ALLOW_BATCH=1 显式启用；执行前会通过内容安全检查。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "批处理文件路径，支持相对路径和绝对路径"},
                        "args": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "传递给批处理文件的参数",
                            "default": [],
                        },
                        "timeout": {
                            "type": "number",
                            "description": "超时时间（秒），默认120秒",
                            "default": DEFAULT_INTERACTIVE_TIMEOUT,
                        },
                    },
                    "required": ["filepath"],
                },
            },
            {
                "name": "create_batch_file",
                "description": "创建批处理文件(.bat/.cmd)。默认禁用，需通过环境变量 CMD_ALLOW_BATCH=1 显式启用；写入前会通过内容安全检查。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "批处理文件路径，支持相对路径和绝对路径"},
                        "content": {"type": "string", "description": "批处理文件内容"},
                    },
                    "required": ["filepath", "content"],
                },
            },
        ]

    def _parse_positive_int(self, raw_value: Optional[str], default: int) -> int:
        try:
            if raw_value is None or raw_value == "":
                return default
            value = int(raw_value)
            return value if value > 0 else default
        except Exception:
            return default

    def _resolve_root(self, workspace_root: Path) -> Path:
        root = workspace_root.resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(f"工作区根目录不是目录: {root}")
        return root

    def _canonicalize_path(self, raw_path: str) -> Path:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("path 不能为空")

        candidate = Path(raw_path.strip())
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate

        if candidate.exists():
            return candidate.resolve(strict=True)

        missing_parts: List[str] = []
        current = candidate
        while not current.exists():
            missing_parts.append(current.name)
            parent = current.parent
            if parent == current:
                break
            current = parent

        base = current.resolve(strict=True) if current.exists() else current.resolve(strict=False)
        for part in reversed(missing_parts):
            base = base / part
        return base

    def _resolve_path(self, raw_path: str, *, allow_missing: bool = False) -> Path:
        resolved = self._canonicalize_path(raw_path)
        if not allow_missing and not resolved.exists():
            raise FileNotFoundError(f"路径不存在: {resolved}")
        if not is_relative_to(resolved, self.workspace_root):
            raise PermissionError(f"路径超出工作区根目录: {resolved}")
        return resolved

    def _resolve_cwd(self, cwd: Optional[str]) -> Path:
        directory = self.workspace_root if cwd in (None, "", ".") else self._resolve_path(cwd)
        if not directory.exists():
            raise FileNotFoundError(f"工作目录不存在: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"工作目录不是目录: {directory}")
        return directory

    def _collect_shell_features(self, command: str) -> List[str]:
        features: List[str] = []
        if "\n" in command or "\r" in command:
            features.append("newline")
        if "&&" in command:
            features.append("&&")
        if "||" in command:
            features.append("||")
        if re.search(r"(?<!\^)(?<!&)&(?!&)", command):
            features.append("&")
        if re.search(r"(?<!\^)\|", command):
            features.append("|")
        if re.search(r"(?<!\^)>", command):
            features.append(">")
        if re.search(r"(?<!\^)<", command):
            features.append("<")
        return features

    def _extract_executables(self, command: str) -> List[str]:
        segments = re.split(r"(?<!\^)(?:&&|\|\||[&|])", command)
        executables: List[str] = []

        for segment in segments:
            current = segment.strip()
            if not current:
                continue
            current = current.lstrip("(").strip()
            match = re.match(r'^"?(?P<cmd>[^"\s<>|&]+)', current)
            if not match:
                continue
            token = match.group("cmd").strip()
            if not token:
                continue
            executable = Path(token).name.lower()
            executables.append(executable)

        deduped: List[str] = []
        seen = set()
        for executable in executables:
            if executable not in seen:
                deduped.append(executable)
                seen.add(executable)
        return deduped

    def _check_regex_rules(
        self,
        command: str,
        rules: Sequence[Tuple[str, str]],
        reasons: List[str],
        matched_rules: List[str],
    ) -> None:
        lowered = command.lower()
        for pattern, reason in rules:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                reasons.append(reason)
                matched_rules.append(pattern)

    def _analyze_command(self, command: str, cwd: Path) -> CommandSafetyResult:
        raw_command = (command or "").strip()
        if not raw_command:
            raise ValueError("command 不能为空")

        blocked_reasons: List[str] = []
        warning_reasons: List[str] = []
        matched_rules: List[str] = []
        shell_features = self._collect_shell_features(raw_command)
        executables = self._extract_executables(raw_command)

        if not executables:
            blocked_reasons.append("无法识别命令入口，拒绝执行")
            return CommandSafetyResult(
                allowed=False,
                risk_level="critical",
                reasons=blocked_reasons,
                matched_rules=matched_rules,
                executables=[],
                shell_features=shell_features,
                policy_mode=self.policy_mode,
            )

        if "newline" in shell_features:
            warning_reasons.append("命令包含换行，建议拆成多次调用后再执行")
            matched_rules.append("shell:newline")

        for executable in executables:
            if executable in ALWAYS_BLOCK_EXECUTABLES:
                blocked_reasons.append(f"命令包含被硬阻断的极高风险可执行入口: {executable}")
                matched_rules.append(f"blocked-executable:{executable}")

        if not self.allow_network:
            for executable in executables:
                if executable in NETWORK_EXECUTABLES:
                    warning_reasons.append(f"检测到网络下载类命令: {executable}")
                    matched_rules.append(f"network-executable:{executable}")

        if not self.allow_powershell:
            for executable in executables:
                if executable in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
                    warning_reasons.append(f"检测到 PowerShell 执行，已标记为高风险: {executable}")
                    matched_rules.append(f"powershell:{executable}")

        if not self.allow_shell_operators:
            for feature in ("&&", "||", "&"):
                if feature in shell_features:
                    warning_reasons.append(f"检测到多命令拼接操作符: {feature}")
                    matched_rules.append(f"shell-operator:{feature}")

        if not self.allow_pipes and "|" in shell_features:
            warning_reasons.append("检测到管道操作符 |")
            matched_rules.append("shell-pipe:|")

        if not self.allow_redirection:
            for feature in (">", "<"):
                if feature in shell_features:
                    warning_reasons.append(f"检测到重定向操作符: {feature}")
                    matched_rules.append(f"shell-redirection:{feature}")

        for executable in executables:
            if executable.endswith((".vbs", ".js")):
                blocked_reasons.append(f"禁止在 execute_cmd 中直接执行脚本文件: {executable}")
                matched_rules.append(f"script-entry:{executable}")

        self._check_regex_rules(raw_command, CRITICAL_BLOCK_PATTERNS, blocked_reasons, matched_rules)
        self._check_regex_rules(raw_command, DESTRUCTIVE_PATTERNS, warning_reasons, matched_rules)
        self._check_regex_rules(raw_command, INLINE_SCRIPT_PATTERNS, warning_reasons, matched_rules)
        self._check_regex_rules(raw_command, DOWNLOAD_EXECUTION_PATTERNS, blocked_reasons, matched_rules)

        if self.policy_mode == "strict":
            unknown = [executable for executable in executables if executable not in SAFE_EXECUTABLES_STRICT]
            if unknown:
                blocked_reasons.append("strict 模式仅允许白名单命令入口，以下入口未被允许: " + ", ".join(unknown))
                matched_rules.append("policy:strict-whitelist")

        blocked_reasons = list(dict.fromkeys(blocked_reasons))
        warning_reasons = [reason for reason in dict.fromkeys(warning_reasons) if reason not in blocked_reasons]
        reasons = blocked_reasons + warning_reasons

        allowed = len(blocked_reasons) == 0
        if blocked_reasons:
            risk_level = "critical"
        elif warning_reasons:
            risk_level = "high"
        else:
            risk_level = "low"

        return CommandSafetyResult(
            allowed=allowed,
            risk_level=risk_level,
            reasons=reasons,
            matched_rules=matched_rules,
            executables=executables,
            shell_features=shell_features,
            policy_mode=self.policy_mode,
        )

    def _analyze_batch_content(self, content: str, cwd: Path) -> CommandSafetyResult:
        if not self.allow_batch:
            return CommandSafetyResult(
                allowed=False,
                risk_level="blocked",
                reasons=["当前策略默认禁用批处理文件能力，请在启动环境中设置 CMD_ALLOW_BATCH=1 后再使用"],
                matched_rules=["policy:batch-disabled"],
                executables=[],
                shell_features=[],
                policy_mode=self.policy_mode,
            )

        aggregate_reasons: List[str] = []
        aggregate_rules: List[str] = []
        aggregate_executables: List[str] = []
        aggregate_features: List[str] = []

        for index, raw_line in enumerate(content.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if lowered.startswith("rem ") or lowered == "rem" or line.startswith("::"):
                continue

            analysis = self._analyze_command(line, cwd)
            aggregate_executables.extend(analysis.executables)
            aggregate_features.extend(analysis.shell_features)
            if not analysis.allowed:
                for reason in analysis.reasons:
                    aggregate_reasons.append(f"第 {index} 行: {reason}")
                for rule in analysis.matched_rules:
                    aggregate_rules.append(f"line:{index}:{rule}")

        if aggregate_reasons:
            return CommandSafetyResult(
                allowed=False,
                risk_level="blocked",
                reasons=aggregate_reasons,
                matched_rules=aggregate_rules,
                executables=aggregate_executables,
                shell_features=aggregate_features,
                policy_mode=self.policy_mode,
            )

        return CommandSafetyResult(
            allowed=True,
            risk_level="low",
            reasons=[],
            matched_rules=[],
            executables=aggregate_executables,
            shell_features=aggregate_features,
            policy_mode=self.policy_mode,
        )

    def _success(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, **payload}, ensure_ascii=False, indent=2),
                }
            ]
        }

    def _error(self, message: str, **extra: Any) -> Dict[str, Any]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": False, "error": message, **extra}, ensure_ascii=False, indent=2),
                }
            ],
            "isError": True,
        }

    def _audit(self, event: str, payload: Dict[str, Any]) -> None:
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **payload,
        }
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _cap_timeout(self, timeout: Optional[float], default: int) -> int:
        if timeout is None:
            return min(default, self.max_timeout)
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        return min(int(timeout), self.max_timeout)

    def _parse_direct_script_invocation(self, command: str) -> Tuple[Optional[str], Optional[List[str]]]:
        stripped = command.strip()
        if not stripped:
            return None, None

        match = re.match(r'^\s*(?:"(?P<quoted>[^"]+)"|(?P<bare>\S+))(?P<rest>.*)$', stripped)
        if not match:
            return None, None

        target = match.group("quoted") or match.group("bare") or ""
        rest = (match.group("rest") or "").strip()
        lowered = target.lower()

        if not lowered.endswith((".bat", ".cmd", ".ps1")):
            return None, None

        extra_args = shlex.split(rest, posix=False) if rest else []

        if lowered.endswith((".bat", ".cmd")):
            return target, ["cmd.exe", "/d", "/c", target, *extra_args]

        return target, ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", target, *extra_args]

    def _run_cmd(self, command: str, cwd: Path, timeout: int) -> Dict[str, Any]:
        direct_script_path, direct_script_args = self._parse_direct_script_invocation(command)

        if direct_script_args is not None:
            effective_command = subprocess.list2cmdline(direct_script_args)
            run_kwargs = {
                "args": direct_script_args,
                "capture_output": True,
                "text": True,
                "timeout": timeout,
                "encoding": self.default_encoding,
                "errors": "replace",
                "cwd": str(cwd),
            }
        else:
            effective_command = command
            run_kwargs = {
                "args": ["cmd.exe", "/d", "/s", "/c", effective_command],
                "capture_output": True,
                "text": True,
                "timeout": timeout,
                "encoding": self.default_encoding,
                "errors": "replace",
                "cwd": str(cwd),
            }

        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if create_no_window:
            run_kwargs["creationflags"] = create_no_window

        result = subprocess.run(**run_kwargs)

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "command": command,
            "effective_command": effective_command,
        }

    async def analyze_cmd(self, command: str, cwd: str = None) -> Dict[str, Any]:
        try:
            resolved_cwd = self._resolve_cwd(cwd)
            analysis = self._analyze_command(command, resolved_cwd)
            payload = {
                "command": command,
                "cwd": str(resolved_cwd),
                "relative_cwd": "." if resolved_cwd == self.workspace_root else to_posix_path(str(resolved_cwd.relative_to(self.workspace_root))),
                "analysis": {
                    "allowed": analysis.allowed,
                    "risk_level": analysis.risk_level,
                    "reasons": analysis.reasons,
                    "matched_rules": analysis.matched_rules,
                    "executables": analysis.executables,
                    "shell_features": analysis.shell_features,
                    "policy_mode": analysis.policy_mode,
                },
                "policy": {
                    "workspace_root": str(self.workspace_root),
                    "policy_mode": self.policy_mode,
                    "allow_batch": self.allow_batch,
                    "allow_network": self.allow_network,
                    "allow_powershell": self.allow_powershell,
                    "allow_shell_operators": self.allow_shell_operators,
                    "allow_pipes": self.allow_pipes,
                    "allow_redirection": self.allow_redirection,
                    "max_timeout": self.max_timeout,
                    "audit_log": str(self.audit_log_path),
                },
            }
            self._audit("analyze_cmd", payload)
            return self._success(payload)
        except Exception as exc:
            return self._error(str(exc), command=command, cwd=cwd)

    async def execute_cmd(self, command: str, timeout: int = DEFAULT_TIMEOUT, cwd: str = None) -> Dict[str, Any]:
        try:
            resolved_cwd = self._resolve_cwd(cwd)
            effective_timeout = self._cap_timeout(timeout, DEFAULT_TIMEOUT)
            analysis = self._analyze_command(command, resolved_cwd)
            if not analysis.allowed:
                payload = {
                    "command": command,
                    "cwd": str(resolved_cwd),
                    "analysis": {
                        "allowed": analysis.allowed,
                        "risk_level": analysis.risk_level,
                        "reasons": analysis.reasons,
                        "matched_rules": analysis.matched_rules,
                        "executables": analysis.executables,
                        "shell_features": analysis.shell_features,
                        "policy_mode": analysis.policy_mode,
                    },
                }
                self._audit("execute_cmd_blocked", payload)
                return self._error("命令被服务端安全策略阻止执行", **payload)

            result = self._run_cmd(command, resolved_cwd, effective_timeout)
            payload = {
                **result,
                "cwd": str(resolved_cwd),
                "relative_cwd": "." if resolved_cwd == self.workspace_root else to_posix_path(str(resolved_cwd.relative_to(self.workspace_root))),
                "timeout": effective_timeout,
                "analysis": {
                    "allowed": analysis.allowed,
                    "risk_level": analysis.risk_level,
                    "reasons": analysis.reasons,
                    "matched_rules": analysis.matched_rules,
                    "executables": analysis.executables,
                    "shell_features": analysis.shell_features,
                    "policy_mode": analysis.policy_mode,
                },
            }
            self._audit("execute_cmd", payload)
            return self._success(payload)
        except subprocess.TimeoutExpired:
            payload = {
                "command": command,
                "cwd": cwd,
                "timeout": timeout,
            }
            self._audit("execute_cmd_timeout", payload)
            return self._error(f"命令执行超时（超过 {timeout} 秒）", **payload)
        except Exception as exc:
            payload = {"command": command, "cwd": cwd}
            self._audit("execute_cmd_error", {**payload, "error": str(exc)})
            return self._error(str(exc), **payload)

    async def execute_cmd_interactive(self, command: str, timeout: int = DEFAULT_INTERACTIVE_TIMEOUT, cwd: str = None) -> Dict[str, Any]:
        try:
            resolved_cwd = self._resolve_cwd(cwd)
            effective_timeout = self._cap_timeout(timeout, DEFAULT_INTERACTIVE_TIMEOUT)
            analysis = self._analyze_command(command, resolved_cwd)
            if not analysis.allowed:
                payload = {
                    "command": command,
                    "cwd": str(resolved_cwd),
                    "analysis": {
                        "allowed": analysis.allowed,
                        "risk_level": analysis.risk_level,
                        "reasons": analysis.reasons,
                        "matched_rules": analysis.matched_rules,
                        "executables": analysis.executables,
                        "shell_features": analysis.shell_features,
                        "policy_mode": analysis.policy_mode,
                    },
                    "note": "interactive 兼容接口同样不允许危险命令",
                }
                self._audit("execute_cmd_interactive_blocked", payload)
                return self._error("命令被服务端安全策略阻止执行", **payload)

            result = self._run_cmd(command, resolved_cwd, effective_timeout)
            payload = {
                **result,
                "cwd": str(resolved_cwd),
                "relative_cwd": "." if resolved_cwd == self.workspace_root else to_posix_path(str(resolved_cwd.relative_to(self.workspace_root))),
                "timeout": effective_timeout,
                "interactive": False,
                "note": "此接口仅保留兼容性，不支持真实交互输入",
                "analysis": {
                    "allowed": analysis.allowed,
                    "risk_level": analysis.risk_level,
                    "reasons": analysis.reasons,
                    "matched_rules": analysis.matched_rules,
                    "executables": analysis.executables,
                    "shell_features": analysis.shell_features,
                    "policy_mode": analysis.policy_mode,
                },
            }
            self._audit("execute_cmd_interactive", payload)
            return self._success(payload)
        except subprocess.TimeoutExpired:
            payload = {"command": command, "cwd": cwd, "timeout": timeout}
            self._audit("execute_cmd_interactive_timeout", payload)
            return self._error(f"命令执行超时（超过 {timeout} 秒）", **payload)
        except Exception as exc:
            payload = {"command": command, "cwd": cwd}
            self._audit("execute_cmd_interactive_error", {**payload, "error": str(exc)})
            return self._error(str(exc), **payload)

    async def run_batch_file(self, filepath: str, args: list = None, timeout: int = DEFAULT_INTERACTIVE_TIMEOUT) -> Dict[str, Any]:
        try:
            batch_path = self._resolve_path(filepath)
            if batch_path.suffix.lower() not in BATCH_EXTENSIONS:
                raise ValueError("只允许执行 .bat 或 .cmd 文件")
            if not batch_path.is_file():
                raise FileNotFoundError(f"批处理文件不存在: {batch_path}")

            content = batch_path.read_text(encoding=self.default_encoding, errors="replace")
            analysis = self._analyze_batch_content(content, batch_path.parent)
            if not analysis.allowed:
                payload = {
                    "filepath": str(batch_path),
                    "relative_path": to_posix_path(str(batch_path.relative_to(self.workspace_root))),
                    "analysis": {
                        "allowed": analysis.allowed,
                        "risk_level": analysis.risk_level,
                        "reasons": analysis.reasons,
                        "matched_rules": analysis.matched_rules,
                        "executables": analysis.executables,
                        "shell_features": analysis.shell_features,
                        "policy_mode": analysis.policy_mode,
                    },
                }
                self._audit("run_batch_file_blocked", payload)
                return self._error("批处理文件被服务端安全策略阻止执行", **payload)

            effective_timeout = self._cap_timeout(timeout, DEFAULT_INTERACTIVE_TIMEOUT)
            command = ["cmd.exe", "/d", "/s", "/c", str(batch_path), *(args or [])]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                encoding=self.default_encoding,
                errors="replace",
                cwd=str(batch_path.parent),
            )

            payload = {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "filepath": str(batch_path),
                "relative_path": to_posix_path(str(batch_path.relative_to(self.workspace_root))),
                "args": args or [],
                "timeout": effective_timeout,
                "analysis": {
                    "allowed": analysis.allowed,
                    "risk_level": analysis.risk_level,
                    "reasons": analysis.reasons,
                    "matched_rules": analysis.matched_rules,
                    "executables": analysis.executables,
                    "shell_features": analysis.shell_features,
                    "policy_mode": analysis.policy_mode,
                },
            }
            self._audit("run_batch_file", payload)
            return self._success(payload)
        except Exception as exc:
            payload = {"filepath": filepath}
            self._audit("run_batch_file_error", {**payload, "error": str(exc)})
            return self._error(str(exc), **payload)

    async def create_batch_file(self, filepath: str, content: str) -> Dict[str, Any]:
        try:
            batch_path = self._resolve_path(filepath, allow_missing=True)
            if batch_path.suffix.lower() not in BATCH_EXTENSIONS:
                raise ValueError("只允许创建 .bat 或 .cmd 文件")

            analysis = self._analyze_batch_content(content, batch_path.parent)
            if not analysis.allowed:
                payload = {
                    "filepath": str(batch_path),
                    "relative_path": to_posix_path(str(batch_path.relative_to(self.workspace_root))),
                    "analysis": {
                        "allowed": analysis.allowed,
                        "risk_level": analysis.risk_level,
                        "reasons": analysis.reasons,
                        "matched_rules": analysis.matched_rules,
                        "executables": analysis.executables,
                        "shell_features": analysis.shell_features,
                        "policy_mode": analysis.policy_mode,
                    },
                    "content_sha256": sha256(content.encode("utf-8")).hexdigest(),
                }
                self._audit("create_batch_file_blocked", payload)
                return self._error("批处理文件内容被服务端安全策略阻止写入", **payload)

            batch_path.parent.mkdir(parents=True, exist_ok=True)
            normalized_content = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
            batch_path.write_text(normalized_content, encoding=self.default_encoding)

            payload = {
                "filepath": str(batch_path),
                "relative_path": to_posix_path(str(batch_path.relative_to(self.workspace_root))),
                "message": f"批处理文件创建成功: {batch_path}",
                "content_sha256": sha256(normalized_content.encode(self.default_encoding, errors="replace")).hexdigest(),
                "analysis": {
                    "allowed": analysis.allowed,
                    "risk_level": analysis.risk_level,
                    "reasons": analysis.reasons,
                    "matched_rules": analysis.matched_rules,
                    "executables": analysis.executables,
                    "shell_features": analysis.shell_features,
                    "policy_mode": analysis.policy_mode,
                },
            }
            self._audit("create_batch_file", payload)
            return self._success(payload)
        except Exception as exc:
            payload = {"filepath": filepath}
            self._audit("create_batch_file_error", {**payload, "error": str(exc)})
            return self._error(str(exc), **payload)

    async def handle_call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name == "analyze_cmd":
            return await self.analyze_cmd(arguments.get("command", ""), arguments.get("cwd"))
        if name == "execute_cmd":
            return await self.execute_cmd(
                arguments.get("command", ""),
                arguments.get("timeout", DEFAULT_TIMEOUT),
                arguments.get("cwd"),
            )
        if name == "execute_cmd_interactive":
            return await self.execute_cmd_interactive(
                arguments.get("command", ""),
                arguments.get("timeout", DEFAULT_INTERACTIVE_TIMEOUT),
                arguments.get("cwd"),
            )
        if name == "run_batch_file":
            return await self.run_batch_file(
                arguments.get("filepath", ""),
                arguments.get("args", []),
                arguments.get("timeout", DEFAULT_INTERACTIVE_TIMEOUT),
            )
        if name == "create_batch_file":
            return await self.create_batch_file(
                arguments.get("filepath", ""),
                arguments.get("content", ""),
            )
        return self._error(f"未知工具: {name}")

    async def handle_list_tools(self) -> Dict[str, Any]:
        return {"tools": self.tools}

    async def handle_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        method = message.get("method")

        if method == "initialize":
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            }

        if method == "tools/list":
            return await self.handle_list_tools()

        if method == "tools/call":
            params = message.get("params", {})
            return await self.handle_call_tool(params.get("name", ""), params.get("arguments", {}))

        if method == "notifications/initialized":
            return {}

        return self._error(f"未知方法: {method}")

    async def run(self) -> None:
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                message = json.loads(line)
                response = await self.handle_message(message)

                if "id" in message:
                    rpc_response = {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "result": response,
                    }
                    print(json.dumps(rpc_response, ensure_ascii=False), flush=True)

            except Exception as exc:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": message.get("id") if "message" in locals() else None,
                    "error": {
                        "code": -32603,
                        "message": str(exc),
                    },
                }
                print(json.dumps(error_response, ensure_ascii=False), flush=True)


def parse_cli(argv: List[str]) -> Path:
    if len(argv) > 1:
        raise SystemExit(f"未知参数: {' '.join(argv[1:])}")
    root_arg = argv[0] if argv else None
    env_root = os.environ.get("CMD_ROOT")
    root = Path(root_arg or env_root or os.getcwd())
    return root


if __name__ == "__main__":
    workspace_root = parse_cli(sys.argv[1:])
    server = HardenedCMDServer(workspace_root=workspace_root)
    asyncio.run(server.run())

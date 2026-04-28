#!/usr/bin/env python3
from __future__ import annotations

"""
Filesystem MCP server inspired by Kilo Code.

Features:
- Workspace sandbox rooted at startup root
- .kilocodeignore / .gitignore style filtering
- Streamed text reading with pagination, byte caps and binary detection
- Directory listing with ignore rules, depth and entry limits
- Safe write / copy / move / delete with version checks
- Text-anchor editing similar to Kilo's edit tool
- Patch application with Kilo-style "*** Begin Patch" format
"""

import asyncio
import difflib
import fnmatch
import hashlib
import json
import mimetypes
import os
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


SERVER_NAME = "filesystem"
SERVER_VERSION = "2.0.0"

DEFAULT_READ_LIMIT = 5000
DEFAULT_MAX_READ_BYTES = 50 * 1024
DEFAULT_MAX_LINE_LENGTH = 2000
DEFAULT_LIST_LIMIT = 200
DEFAULT_LIST_MAX_DEPTH = 8
LINE_TRUNCATION_SUFFIX = f"... (line truncated to {DEFAULT_MAX_LINE_LENGTH} chars)"

DEFAULT_LIST_IGNORE_PATTERNS: List[str] = []

SENSITIVE_PATTERNS: List[str] = []

BINARY_EXTENSIONS = {
    ".7z",
    ".a",
    ".apk",
    ".app",
    ".aab",
    ".arw",
    ".avif",
    ".bc",
    ".bin",
    ".bmp",
    ".bz",
    ".bz2",
    ".class",
    ".com",
    ".cr2",
    ".dat",
    ".db",
    ".deb",
    ".dex",
    ".dll",
    ".dmg",
    ".doc",
    ".docx",
    ".drv",
    ".ear",
    ".efi",
    ".exe",
    ".flac",
    ".flv",
    ".gif",
    ".gz",
    ".heic",
    ".heif",
    ".ico",
    ".img",
    ".ipa",
    ".iso",
    ".jar",
    ".jpeg",
    ".jpg",
    ".jxl",
    ".ko",
    ".lib",
    ".ll",
    ".lz",
    ".m4a",
    ".mdb",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".msi",
    ".msp",
    ".nef",
    ".o",
    ".obj",
    ".odex",
    ".oat",
    ".ogg",
    ".ogv",
    ".orf",
    ".otf",
    ".pdf",
    ".pef",
    ".pkg",
    ".png",
    ".ppt",
    ".pptx",
    ".psd",
    ".pyc",
    ".pyo",
    ".raf",
    ".rar",
    ".rpm",
    ".rom",
    ".so",
    ".sqlite",
    ".svgz",
    ".sys",
    ".tar",
    ".tif",
    ".tiff",
    ".ttf",
    ".vdex",
    ".vmdk",
    ".war",
    ".wasm",
    ".wav",
    ".weba",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".wma",
    ".wmv",
    ".xapk",
    ".xls",
    ".xlsx",
    ".xz",
    ".z",
    ".zip",
}

TEXT_NAMES = {
    ".editorconfig",
    ".eslintrc",
    ".gitattributes",
    ".gitignore",
    ".npmrc",
    ".nvmrc",
    ".prettierrc",
    "dockerfile",
    "makefile",
}


def parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class IgnoreRule:
    pattern: str
    negated: bool
    anchored: bool
    directory_only: bool


@dataclass(frozen=True)
class PatchChunk:
    old_lines: List[str]
    new_lines: List[str]
    change_context: Optional[str] = None
    is_end_of_file: bool = False


@dataclass(frozen=True)
class PatchHunk:
    type: str
    path: str
    contents: str = ""
    move_path: Optional[str] = None
    chunks: Optional[List[PatchChunk]] = None


def to_posix_path(value: str) -> str:
    return value.replace("\\", "/")


def normalize_unicode(value: str) -> str:
    return (
        value.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201A", "'")
        .replace("\u201B", "'")
        .replace("\u201C", '"')
        .replace("\u201D", '"')
        .replace("\u201E", '"')
        .replace("\u201F", '"')
        .replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2015", "-")
        .replace("\u2026", "...")
        .replace("\u00A0", " ")
    )


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def number_lines(lines: List[str], start_line: int) -> str:
    return "\n".join(f"{line_number} | {line}" for line_number, line in enumerate(lines, start=start_line))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_text_diff(display_path: str, before: str, after: str) -> str:
    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=display_path,
            tofile=display_path,
            lineterm="",
        )
    )
    return "\n".join(diff_lines)


def mtime_ns(stat_result: os.stat_result) -> int:
    value = getattr(stat_result, "st_mtime_ns", None)
    if value is not None:
        return int(value)
    return int(stat_result.st_mtime * 1_000_000_000)


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for index_left, char_left in enumerate(left, start=1):
        current = [index_left]
        for index_right, char_right in enumerate(right, start=1):
            cost = 0 if char_left == char_right else 1
            current.append(
                min(
                    previous[index_right] + 1,
                    current[index_right - 1] + 1,
                    previous[index_right - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


class IgnoreMatcher:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.rules: List[IgnoreRule] = []
        self.loaded_files: List[Dict[str, str]] = []

    def reload(self) -> None:
        self.rules = []
        self.loaded_files = []

    def describe(self) -> Optional[str]:
        return None

    def _parse_ignore_content(self, content: str) -> List[IgnoreRule]:
        rules: List[IgnoreRule] = []

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            negated = line.startswith("!")
            if negated:
                line = line[1:]

            anchored = line.startswith("/")
            if anchored:
                line = line[1:]

            directory_only = line.endswith("/")
            if directory_only:
                line = line[:-1]

            line = to_posix_path(line.strip())
            if not line:
                continue

            rules.append(
                IgnoreRule(
                    pattern=line,
                    negated=negated,
                    anchored=anchored,
                    directory_only=directory_only,
                )
            )

        return rules

    def is_ignored(self, relative_path: str, is_directory: bool) -> bool:
        normalized = to_posix_path(relative_path).strip("/")
        if not normalized:
            return False

        ignored = False
        for rule in self.rules:
            if self._matches_rule(rule, normalized, is_directory):
                ignored = not rule.negated
        return ignored

    def _matches_rule(self, rule: IgnoreRule, relative_path: str, is_directory: bool) -> bool:
        path_value = relative_path.strip("/")
        segments = [segment for segment in path_value.split("/") if segment]

        if rule.directory_only:
            pattern = rule.pattern.strip("/")
            if rule.anchored:
                return path_value == pattern or path_value.startswith(pattern + "/")
            if "/" in pattern:
                return (
                    path_value == pattern
                    or path_value.startswith(pattern + "/")
                    or path_value.endswith("/" + pattern)
                    or f"/{pattern}/" in f"/{path_value}/"
                )
            return pattern in segments

        pattern = rule.pattern
        if rule.anchored:
            return fnmatch.fnmatchcase(path_value, pattern)

        if "/" in pattern:
            return (
                fnmatch.fnmatchcase(path_value, pattern)
                or path_value == pattern
                or path_value.endswith("/" + pattern)
                or fnmatch.fnmatchcase(path_value, f"*/{pattern}")
            )

        return any(fnmatch.fnmatchcase(segment, pattern) for segment in segments)


class FilesystemServer:
    def __init__(
        self,
        workspace_root: Path,
        read_only: bool = False,
        allow_outside_workspace: bool = False,
    ):
        self.workspace_root = self._resolve_root(workspace_root)
        self.read_only = read_only
        self.allow_outside_workspace = allow_outside_workspace
        self.ignore_matcher = IgnoreMatcher(self.workspace_root)
        self.ignore_matcher.reload()
        self.tools = self._build_tools()

    def _path_access_hint(self) -> str:
        return ""

    def _path_argument_description(self, target: str) -> str:
        return f"{target}，支持相对路径和绝对路径"

    def _build_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "read_file",
                "description": f"读取文本文件，支持按行分页、字节上限、二进制检测和带行号输出。{self._path_access_hint()}",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": self._path_argument_description("文件路径")},
                        "start_line": {"type": "integer", "minimum": 1, "default": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                        "limit": {"type": "integer", "minimum": 1, "default": DEFAULT_READ_LIMIT},
                        "encoding": {"type": "string", "default": "utf-8"},
                        "max_bytes": {"type": "integer", "minimum": 1, "default": DEFAULT_MAX_READ_BYTES},
                        "max_line_length": {"type": "integer", "minimum": 1, "default": DEFAULT_MAX_LINE_LENGTH},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": f"写入完整文件内容，支持创建父目录和覆盖控制。{self._path_access_hint()}",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": self._path_argument_description("目标文件路径")},
                        "content": {"type": "string", "description": "要写入的完整内容"},
                        "encoding": {"type": "string", "default": "utf-8"},
                        "create_directories": {"type": "boolean", "default": True},
                        "overwrite": {"type": "boolean", "default": True},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "create_directory",
                "description": "创建目录。适合先创建测试目录，再单独写入文件。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "目标目录路径"},
                        "parents": {"type": "boolean", "default": True},
                        "exist_ok": {"type": "boolean", "default": True}
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "list_directory",
                "description": "列出目录内容，支持递归、最大深度、条数上限、忽略规则和额外 ignore 模式。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": "."},
                        "recursive": {"type": "boolean", "default": False},
                        "max_entries": {"type": "integer", "minimum": 1, "default": DEFAULT_LIST_LIMIT},
                        "max_depth": {"type": "integer", "minimum": 0, "default": DEFAULT_LIST_MAX_DEPTH},
                        "ignore": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "额外 glob ignore 模式",
                        },
                        "include_ignored": {"type": "boolean", "default": False},
                    },
                },
            },
            {
                "name": "delete_file",
                "description": "删除文件或目录。删除非空目录时必须显式指定 recursive=true。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "recursive": {"type": "boolean", "default": False}
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "file_exists",
                "description": "检查文件或目录是否存在，并返回类型、大小、忽略状态和元信息。",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            {
                "name": "copy_file",
                "description": "复制文件到新位置，支持覆盖控制。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source_path": {"type": "string"},
                        "destination_path": {"type": "string"},
                        "overwrite": {"type": "boolean", "default": False},
                    },
                    "required": ["source_path", "destination_path"],
                },
            },
            {
                "name": "move_file",
                "description": "移动或重命名文件/目录，支持覆盖控制。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source_path": {"type": "string"},
                        "destination_path": {"type": "string"},
                        "overwrite": {"type": "boolean", "default": False},
                    },
                    "required": ["source_path", "destination_path"],
                },
            },
            {
                "name": "apply_diff",
                "description": "对单个文件执行基于行号的局部修改。支持 replace、insert、delete，并支持 expected_old_content 校验。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "changes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "operation": {
                                        "type": "string",
                                        "enum": ["replace", "insert", "delete"],
                                    },
                                    "start_line": {"type": "integer", "minimum": 1},
                                    "end_line": {"type": "integer", "minimum": 1},
                                    "content": {"type": "string"},
                                    "expected_old_content": {
                                        "type": "string",
                                        "description": "可选，replace/delete 时用于校验原文是否匹配",
                                    },
                                },
                                "required": ["operation", "start_line"],
                            },
                        },
                        "encoding": {"type": "string", "default": "utf-8"},
                    },
                    "required": ["path", "changes"],
                },
            },
            {
                "name": "edit_file",
                "description": "按旧文本锚定修改文件内容，类似 Kilo 的 edit。支持 replace_all。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                        "replace_all": {"type": "boolean", "default": False},
                        "encoding": {"type": "string", "default": "utf-8"},
                    },
                    "required": ["path", "old_string", "new_string"],
                },
            },
            {
                "name": "apply_patch",
                "description": "应用 Kilo 风格的 *** Begin Patch / *** End Patch patch。支持 add、update、delete、move。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "patch_text": {"type": "string"},
                        "encoding": {"type": "string", "default": "utf-8"},
                    },
                    "required": ["patch_text"],
                },
            },
        ]

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

        candidate = candidate.expanduser()
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

    def _is_within_workspace(self, path: Path) -> bool:
        return is_relative_to(path, self.workspace_root)

    def _resolve_path(self, raw_path: str, *, allow_missing: bool = False) -> Path:
        resolved = self._canonicalize_path(raw_path)
        if not allow_missing and not resolved.exists():
            raise FileNotFoundError(f"路径不存在: {resolved}")
        if not self.allow_outside_workspace and not self._is_within_workspace(resolved):
            raise PermissionError(f"路径超出工作区根目录: {resolved}")
        return resolved

    def _relative_to_root(self, path: Path) -> str:
        if path == self.workspace_root:
            return "."
        if self._is_within_workspace(path):
            return to_posix_path(str(path.relative_to(self.workspace_root)))
        return to_posix_path(str(path))

    def _path_payload(self, path: Path) -> Dict[str, Any]:
        return {
            "path": str(path),
            "relative_path": self._relative_to_root(path),
            "outside_workspace": not self._is_within_workspace(path),
        }

    def _assert_mutable(self) -> None:
        if self.read_only:
            raise PermissionError("当前文件系统服务处于只读模式，拒绝修改操作")

    def _assert_not_ignored(self, path: Path, *, is_directory: bool) -> None:
        if not self._is_within_workspace(path):
            return
        relative_path = "." if path == self.workspace_root else self._relative_to_root(path)
        if relative_path == ".":
            return
        if self.ignore_matcher.is_ignored(relative_path, is_directory):
            raise PermissionError(f"路径被忽略规则拒绝访问: {relative_path}")

    def _matches_extra_ignore(self, relative_path: str, is_directory: bool, patterns: Iterable[str]) -> bool:
        normalized = to_posix_path(relative_path).strip("/")
        basename = normalized.rsplit("/", 1)[-1] if normalized else normalized
        for raw_pattern in patterns:
            pattern = to_posix_path(raw_pattern.strip())
            if not pattern:
                continue
            if pattern.endswith("/"):
                prefix = pattern.rstrip("/")
                if normalized == prefix or normalized.startswith(prefix + "/") or prefix == basename:
                    return True
                continue
            if fnmatch.fnmatchcase(normalized, pattern) or fnmatch.fnmatchcase(basename, pattern):
                return True
            if is_directory and (
                fnmatch.fnmatchcase(normalized + "/", pattern)
                or fnmatch.fnmatchcase(basename + "/", pattern)
            ):
                return True
        return False

    def _is_binary_file(self, file_path: Path) -> bool:
        if file_path.suffix.lower() in BINARY_EXTENSIONS and file_path.name.lower() not in TEXT_NAMES:
            return True

        if file_path.stat().st_size == 0:
            return False

        with file_path.open("rb") as handle:
            sample = handle.read(4096)

        if b"\x00" in sample:
            return True

        non_printable = 0
        for value in sample:
            if value < 9 or (13 < value < 32):
                non_printable += 1

        return non_printable / max(1, len(sample)) > 0.3

    def _assert_version(
        self,
        path: Path,
        *,
        expected_sha256: Optional[str] = None,
        expected_mtime_ns: Optional[int] = None,
    ) -> None:
        normalized_sha256 = expected_sha256.strip() if isinstance(expected_sha256, str) else expected_sha256
        if normalized_sha256 == "":
            normalized_sha256 = None

        normalized_mtime_ns: Optional[int]
        if expected_mtime_ns in (None, 0, "", False):
            normalized_mtime_ns = None
        else:
            normalized_mtime_ns = int(expected_mtime_ns)
            if normalized_mtime_ns <= 0:
                normalized_mtime_ns = None

        if normalized_sha256 is None and normalized_mtime_ns is None:
            return

        if not path.exists():
            raise FileNotFoundError(f"版本校验失败，目标不存在: {path}")

        stat_result = path.stat()
        if normalized_mtime_ns is not None and mtime_ns(stat_result) != normalized_mtime_ns:
            raise ValueError("版本校验失败：mtime_ns 不匹配，文件可能已被其他操作修改")

        if normalized_sha256 is not None and file_sha256(path) != normalized_sha256:
            raise ValueError("版本校验失败：sha256 不匹配，文件可能已被其他操作修改")

    def _file_signature(self, path: Path) -> Dict[str, Any]:
        stat_result = path.stat()
        payload = {
            "size": stat_result.st_size,
            "mtime_ns": mtime_ns(stat_result),
        }
        if path.is_file():
            payload["sha256"] = file_sha256(path)
        return payload

    def _remove_existing_path(self, path: Path) -> None:
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

    def _directory_stats(self, directory: Path) -> Dict[str, Any]:
        file_count = 0
        directory_count = 0
        total_size = 0

        for root, dirs, files in os.walk(directory):
            directory_count += len(dirs)
            file_count += len(files)
            for filename in files:
                full_path = Path(root) / filename
                try:
                    total_size += full_path.stat().st_size
                except OSError:
                    continue

        return {
            "file_count": file_count,
            "directory_count": directory_count,
            "total_size": total_size,
        }

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

    async def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
        limit: int = DEFAULT_READ_LIMIT,
        encoding: str = "utf-8",
        max_bytes: int = DEFAULT_MAX_READ_BYTES,
        max_line_length: int = DEFAULT_MAX_LINE_LENGTH,
    ) -> Dict[str, Any]:
        try:
            if start_line < 1:
                raise ValueError("start_line 必须大于等于 1")
            if limit < 1:
                raise ValueError("limit 必须大于等于 1")
            if max_bytes < 1:
                raise ValueError("max_bytes 必须大于等于 1")
            if max_line_length < 1:
                raise ValueError("max_line_length 必须大于等于 1")
            if end_line is not None and end_line < start_line:
                raise ValueError("end_line 必须大于等于 start_line")

            effective_limit = end_line - start_line + 1 if end_line is not None else limit

            file_path = self._resolve_path(path)
            if not file_path.is_file():
                raise IsADirectoryError(f"目标不是文件: {file_path}")
            self._assert_not_ignored(file_path, is_directory=False)

            if self._is_binary_file(file_path):
                raise ValueError(f"无法按文本方式读取二进制文件: {file_path}")

            selected_lines: List[str] = []
            bytes_read = 0
            total_lines = 0
            has_more_lines = False
            truncated_by_bytes = False

            with file_path.open("r", encoding=encoding, newline=None) as handle:
                for raw_line in handle:
                    total_lines += 1
                    if total_lines < start_line:
                        continue

                    if len(selected_lines) >= effective_limit:
                        has_more_lines = True
                        continue

                    line = raw_line.rstrip("\r\n")
                    if len(line) > max_line_length:
                        line = line[:max_line_length] + f"... (line truncated to {max_line_length} chars)"

                    line_size = len(line.encode("utf-8")) + (1 if selected_lines else 0)
                    if bytes_read + line_size > max_bytes:
                        truncated_by_bytes = True
                        has_more_lines = True
                        break

                    selected_lines.append(line)
                    bytes_read += line_size

            if total_lines == 0:
                actual_end_line = 0
            else:
                if start_line > total_lines:
                    raise ValueError(f"start_line 超出文件范围，当前文件共 {total_lines} 行")
                actual_end_line = start_line + len(selected_lines) - 1 if selected_lines else start_line - 1

            truncated = has_more_lines or truncated_by_bytes
            next_start_line = actual_end_line + 1 if truncated and selected_lines else None

            return self._success(
                {
                    **self._path_payload(file_path),
                    "encoding": encoding,
                    "mime_type": mimetypes.guess_type(str(file_path))[0] or "text/plain",
                    "total_lines": total_lines if not truncated_by_bytes else None,
                    "start_line": start_line,
                    "end_line": actual_end_line,
                    "line_count": len(selected_lines),
                    "bytes_read": bytes_read,
                    "truncated": truncated,
                    "truncation_reason": "max_bytes" if truncated_by_bytes else ("limit" if has_more_lines else None),
                    "next_start_line": next_start_line,
                    "content": "\n".join(selected_lines),
                    "numbered_content": number_lines(selected_lines, start_line) if selected_lines else "",
                }
            )
        except Exception as exc:
            return self._error(str(exc), path=path)

    async def write_file(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
        create_directories: bool = True,
        overwrite: bool = True,
        expected_sha256: Optional[str] = None,
        expected_mtime_ns: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            self._assert_mutable()
            if not isinstance(content, str):
                raise ValueError("content 必须是字符串")

            file_path = self._resolve_path(path, allow_missing=True)
            self._assert_not_ignored(file_path, is_directory=False)

            existed = file_path.exists()
            if existed and file_path.is_dir():
                raise IsADirectoryError(f"目标是目录，不是文件: {file_path}")
            if existed and not overwrite:
                raise FileExistsError(f"目标文件已存在且 overwrite=false: {file_path}")

            if existed:
                self._assert_version(
                    file_path,
                    expected_sha256=expected_sha256,
                    expected_mtime_ns=expected_mtime_ns,
                )

            if create_directories:
                file_path.parent.mkdir(parents=True, exist_ok=True)

            old_content: Optional[str] = None
            if existed:
                try:
                    old_content = file_path.read_text(encoding=encoding)
                except UnicodeDecodeError:
                    old_content = None

            file_path.write_text(content, encoding=encoding)

            diff = build_text_diff(self._path_payload(file_path)["relative_path"], old_content or "", content) if old_content is not None else None
            signature = self._file_signature(file_path)

            return self._success(
                {
                    **self._path_payload(file_path),
                    "encoding": encoding,
                    "created": not existed,
                    "overwritten": existed,
                    "bytes_written": len(content.encode(encoding)),
                    "line_count": len(content.splitlines()),
                    "diff": diff,
                    "signature": signature,
                }
            )
        except Exception as exc:
            return self._error(str(exc), path=path)

    async def create_directory(
        self,
        path: str,
        parents: bool = True,
        exist_ok: bool = True,
    ) -> Dict[str, Any]:
        try:
            self._assert_mutable()
            directory = self._resolve_path(path, allow_missing=True)
            self._assert_not_ignored(directory, is_directory=True)

            existed = directory.exists()
            if existed and not directory.is_dir():
                raise FileExistsError(f"目标路径已存在且不是目录: {directory}")

            directory.mkdir(parents=parents, exist_ok=exist_ok)

            return self._success(
                {
                    **self._path_payload(directory),
                    "created": not existed,
                    "already_exists": existed,
                    "parents": parents,
                    "exist_ok": exist_ok,
                }
            )
        except Exception as exc:
            return self._error(str(exc), path=path)

    async def list_directory(
        self,
        path: str = ".",
        recursive: bool = False,
        max_entries: int = DEFAULT_LIST_LIMIT,
        max_depth: int = DEFAULT_LIST_MAX_DEPTH,
        ignore: Optional[List[str]] = None,
        include_ignored: bool = False,
    ) -> Dict[str, Any]:
        try:
            if max_entries < 1:
                raise ValueError("max_entries 必须大于等于 1")
            if max_depth < 0:
                raise ValueError("max_depth 不能小于 0")

            directory = self._resolve_path(path)
            if not directory.is_dir():
                raise NotADirectoryError(f"目标不是目录: {directory}")
            self._assert_not_ignored(directory, is_directory=True)

            extra_ignore = list(ignore or [])
            results: List[Dict[str, Any]] = []
            ignored_count = 0
            truncated = False

            def walk(current: Path, depth: int) -> None:
                nonlocal ignored_count, truncated

                if truncated:
                    return

                try:
                    entries = sorted(
                        list(os.scandir(current)),
                        key=lambda entry: (not entry.is_dir(follow_symlinks=False), entry.name.lower()),
                    )
                except OSError as exc:
                    raise OSError(f"读取目录失败: {current}: {exc}") from exc

                for entry in entries:
                    lexical_path = Path(entry.path)
                    within_workspace = self._is_within_workspace(lexical_path)
                    try:
                        resolved_entry = lexical_path.resolve(strict=True)
                        external = not is_relative_to(resolved_entry, self.workspace_root)
                    except OSError:
                        external = not within_workspace

                    relative_root = self._relative_to_root(lexical_path)
                    relative_base = to_posix_path(str(lexical_path.relative_to(directory)))
                    is_dir = entry.is_dir(follow_symlinks=False)

                    if within_workspace:
                        ignored_by_rules = self.ignore_matcher.is_ignored(relative_root, is_dir)
                        ignored_by_default = self._matches_extra_ignore(relative_root, is_dir, DEFAULT_LIST_IGNORE_PATTERNS)
                        ignored_by_extra = self._matches_extra_ignore(relative_root, is_dir, extra_ignore)
                    else:
                        ignored_by_rules = False
                        ignored_by_default = False
                        ignored_by_extra = False

                    ignored = ignored_by_rules or ignored_by_default or ignored_by_extra

                    if ignored and not include_ignored:
                        ignored_count += 1
                        continue

                    stat_result = entry.stat(follow_symlinks=False)
                    results.append(
                        {
                            "name": entry.name,
                            "path": str(lexical_path),
                            "relative_path": relative_root,
                            "relative_to_base": relative_base,
                            "type": "directory" if is_dir else "file",
                            "size": stat_result.st_size if not is_dir else None,
                            "ignored": ignored,
                            "external": external,
                        }
                    )

                    if len(results) >= max_entries:
                        truncated = True
                        return

                    if recursive and is_dir and depth < max_depth and not ignored:
                        walk(lexical_path, depth + 1)
                        if truncated:
                            return

            walk(directory, 0)

            return self._success(
                {
                    **self._path_payload(directory),
                    "recursive": recursive,
                    "max_entries": max_entries,
                    "max_depth": max_depth,
                    "count": len(results),
                    "ignored_count": ignored_count,
                    "truncated": truncated,
                    "entries": results,
                    "ignore_rules": self.ignore_matcher.describe(),
                }
            )
        except Exception as exc:
            return self._error(str(exc), path=path)

    async def delete_file(
        self,
        path: str,
        recursive: bool = False,
        expected_sha256: Optional[str] = None,
        expected_mtime_ns: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            self._assert_mutable()
            target = self._resolve_path(path)
            self._assert_not_ignored(target, is_directory=target.is_dir())

            stats_before = self._directory_stats(target) if target.is_dir() else None

            if target.is_file():
                self._assert_version(
                    target,
                    expected_sha256=expected_sha256,
                    expected_mtime_ns=expected_mtime_ns,
                )
                target.unlink()
                deleted_type = "file"
            else:
                if recursive:
                    shutil.rmtree(target)
                else:
                    target.rmdir()
                deleted_type = "directory"

            return self._success(
                {
                    **self._path_payload(target),
                    "deleted_type": deleted_type,
                    "recursive": recursive,
                    "directory_stats": stats_before,
                }
            )
        except Exception as exc:
            return self._error(str(exc), path=path)

    async def file_exists(self, path: str) -> Dict[str, Any]:
        try:
            resolved = self._resolve_path(path, allow_missing=True)
            exists = resolved.exists()
            payload: Dict[str, Any] = {
                **self._path_payload(resolved),
                "exists": exists,
            }

            if exists:
                stat_result = resolved.stat()
                is_dir = resolved.is_dir()
                payload.update(
                    {
                        "type": "directory" if is_dir else "file",
                        "size": stat_result.st_size if not is_dir else None,
                        "ignored": False
                        if resolved == self.workspace_root or not self._is_within_workspace(resolved)
                        else self.ignore_matcher.is_ignored(self._relative_to_root(resolved), is_dir),
                        "signature": self._file_signature(resolved) if resolved.is_file() else None,
                    }
                )
            else:
                parent = resolved.parent
                if parent != resolved and parent.exists():
                    payload["parent_exists"] = True
                    payload["parent_relative_path"] = "." if parent == self.workspace_root else self._relative_to_root(parent)
                else:
                    payload["parent_exists"] = False

            return self._success(payload)
        except Exception as exc:
            return self._error(str(exc), path=path)

    async def copy_file(
        self,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        try:
            self._assert_mutable()
            source = self._resolve_path(source_path)
            destination = self._resolve_path(destination_path, allow_missing=True)

            if not source.is_file():
                raise IsADirectoryError(f"copy_file 仅支持文件复制，源路径不是文件: {source}")

            self._assert_not_ignored(source, is_directory=False)
            self._assert_not_ignored(destination, is_directory=False)

            if source == destination:
                raise ValueError("源路径和目标路径相同，拒绝复制")

            if destination.exists():
                if not overwrite:
                    raise FileExistsError(f"目标路径已存在: {destination}")
                if destination.is_dir():
                    raise IsADirectoryError(f"目标路径是目录，无法以文件方式覆盖: {destination}")

            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

            return self._success(
                {
                    "source_path": str(source),
                    "source_relative_path": self._relative_to_root(source),
                    "destination_path": str(destination),
                    "destination_relative_path": self._relative_to_root(destination),
                    "signature": self._file_signature(destination),
                }
            )
        except Exception as exc:
            return self._error(str(exc), source_path=source_path, destination_path=destination_path)

    async def move_file(
        self,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        try:
            self._assert_mutable()
            source = self._resolve_path(source_path)
            destination = self._resolve_path(destination_path, allow_missing=True)

            self._assert_not_ignored(source, is_directory=source.is_dir())
            self._assert_not_ignored(destination, is_directory=False)

            if source == destination:
                raise ValueError("源路径和目标路径相同，拒绝移动")

            if destination.exists():
                if not overwrite:
                    raise FileExistsError(f"目标路径已存在: {destination}")
                self._remove_existing_path(destination)

            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))

            return self._success(
                {
                    "source_path": str(source),
                    "source_relative_path": self._relative_to_root(source),
                    "destination_path": str(destination),
                    "destination_relative_path": self._relative_to_root(destination),
                    "moved_type": "directory" if destination.is_dir() else "file",
                }
            )
        except Exception as exc:
            return self._error(str(exc), source_path=source_path, destination_path=destination_path)

    def _normalize_apply_diff_changes(
        self,
        changes: List[Dict[str, Any]],
        total_lines: int,
    ) -> List[Dict[str, Any]]:
        if not isinstance(changes, list) or not changes:
            raise ValueError("changes 必须是非空数组")

        normalized: List[Dict[str, Any]] = []
        replace_delete_ranges: List[Tuple[int, int, int]] = []
        insert_positions: set[int] = set()

        for index, raw_change in enumerate(changes):
            if not isinstance(raw_change, dict):
                raise ValueError(f"第 {index + 1} 个 change 必须是对象")

            operation = raw_change.get("operation")
            if operation not in {"replace", "insert", "delete"}:
                raise ValueError(f"第 {index + 1} 个 change 的 operation 必须是 replace、insert 或 delete")

            start_line = raw_change.get("start_line")
            if not isinstance(start_line, int) or start_line < 1:
                raise ValueError(f"第 {index + 1} 个 change 的 start_line 必须是大于等于 1 的整数")

            expected_old_content = raw_change.get("expected_old_content")
            if expected_old_content is not None and not isinstance(expected_old_content, str):
                raise ValueError(f"第 {index + 1} 个 change 的 expected_old_content 必须是字符串")

            if operation == "insert":
                if start_line > total_lines + 1:
                    raise ValueError(
                        f"第 {index + 1} 个 change 的 start_line 超出可插入范围，当前文件最多可在第 {total_lines + 1} 行前插入"
                    )
                if start_line in insert_positions:
                    raise ValueError(f"存在多个 insert 变更使用了同一个插入位置: 第 {start_line} 行前")

                content = raw_change.get("content")
                if not isinstance(content, str):
                    raise ValueError(f"第 {index + 1} 个 insert 变更必须提供字符串类型的 content")

                insert_positions.add(start_line)
                normalized.append(
                    {
                        "index": index,
                        "operation": operation,
                        "start_line": start_line,
                        "end_line": start_line - 1,
                        "content": content,
                        "expected_old_content": expected_old_content,
                    }
                )
                continue

            end_line = raw_change.get("end_line", start_line)
            if not isinstance(end_line, int) or end_line < start_line:
                raise ValueError(f"第 {index + 1} 个 change 的 end_line 必须是大于等于 start_line 的整数")
            if total_lines == 0:
                raise ValueError("目标文件为空，无法执行 replace 或 delete")
            if end_line > total_lines:
                raise ValueError(f"第 {index + 1} 个 change 超出文件行数范围，当前文件共 {total_lines} 行")

            if operation == "replace":
                content = raw_change.get("content")
                if not isinstance(content, str):
                    raise ValueError(f"第 {index + 1} 个 replace 变更必须提供字符串类型的 content")
            else:
                content = ""

            replace_delete_ranges.append((start_line, end_line, index))
            normalized.append(
                {
                    "index": index,
                    "operation": operation,
                    "start_line": start_line,
                    "end_line": end_line,
                    "content": content,
                    "expected_old_content": expected_old_content,
                }
            )

        replace_delete_ranges.sort(key=lambda item: (item[0], item[1]))
        for position in range(1, len(replace_delete_ranges)):
            previous_start, previous_end, _ = replace_delete_ranges[position - 1]
            current_start, _, current_index = replace_delete_ranges[position]
            if current_start <= previous_end:
                raise ValueError(f"变更范围发生重叠：第 {current_index + 1} 个变更与其他 replace/delete 变更冲突")

        for insert_position in insert_positions:
            for range_start, range_end, range_index in replace_delete_ranges:
                if range_start <= insert_position <= range_end:
                    raise ValueError(
                        f"insert 位置与 replace/delete 范围冲突：第 {insert_position} 行前的插入与第 {range_index + 1} 个变更冲突"
                    )

        normalized.sort(key=lambda item: (item["start_line"], item["end_line"]), reverse=True)
        return normalized

    async def apply_diff(
        self,
        path: str,
        changes: List[Dict[str, Any]],
        encoding: str = "utf-8",
        expected_sha256: Optional[str] = None,
        expected_mtime_ns: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            self._assert_mutable()
            file_path = self._resolve_path(path)
            if not file_path.is_file():
                raise IsADirectoryError(f"目标不是文件: {file_path}")
            self._assert_not_ignored(file_path, is_directory=False)
            self._assert_version(
                file_path,
                expected_sha256=expected_sha256,
                expected_mtime_ns=expected_mtime_ns,
            )

            original_text = file_path.read_text(encoding=encoding)
            newline = detect_newline(original_text)
            had_trailing_newline = original_text.endswith(("\r\n", "\n", "\r"))
            original_lines = original_text.splitlines()
            normalized_changes = self._normalize_apply_diff_changes(changes, len(original_lines))
            updated_lines = list(original_lines)
            applied_changes: List[Dict[str, Any]] = []

            for change in normalized_changes:
                operation = change["operation"]
                start_line = change["start_line"]
                end_line = change["end_line"]
                expected_old_content = change["expected_old_content"]

                if operation in {"replace", "delete"} and expected_old_content is not None:
                    expected_lines = expected_old_content.splitlines()
                    actual_lines = original_lines[start_line - 1 : end_line]
                    if actual_lines != expected_lines:
                        raise ValueError(
                            f"第 {change['index'] + 1} 个变更的 expected_old_content 与文件当前内容不匹配"
                        )

                if operation == "insert":
                    insert_lines = change["content"].splitlines()
                    updated_lines[start_line - 1 : start_line - 1] = insert_lines
                    applied_changes.append(
                        {
                            "operation": "insert",
                            "start_line": start_line,
                            "end_line": start_line - 1,
                            "new_line_count": len(insert_lines),
                        }
                    )
                elif operation == "replace":
                    replacement_lines = change["content"].splitlines()
                    updated_lines[start_line - 1 : end_line] = replacement_lines
                    applied_changes.append(
                        {
                            "operation": "replace",
                            "start_line": start_line,
                            "end_line": end_line,
                            "new_line_count": len(replacement_lines),
                        }
                    )
                else:
                    del updated_lines[start_line - 1 : end_line]
                    applied_changes.append(
                        {
                            "operation": "delete",
                            "start_line": start_line,
                            "end_line": end_line,
                            "new_line_count": 0,
                        }
                    )

            new_text = newline.join(updated_lines)
            if updated_lines and had_trailing_newline:
                new_text += newline

            file_path.write_text(new_text, encoding=encoding)
            applied_changes.sort(key=lambda item: (item["start_line"], item["end_line"]))

            return self._success(
                {
                    **self._path_payload(file_path),
                    "encoding": encoding,
                    "original_total_lines": len(original_lines),
                    "new_total_lines": len(updated_lines),
                    "applied_changes": applied_changes,
                    "diff": build_text_diff(self._relative_to_root(file_path), original_text, new_text),
                    "signature": self._file_signature(file_path),
                }
            )
        except Exception as exc:
            return self._error(str(exc), path=path)

    def _simple_replacer(self, content: str, find: str) -> Iterator[str]:
        if find in content:
            yield find

    def _line_trimmed_replacer(self, content: str, find: str) -> Iterator[str]:
        original_lines = content.split("\n")
        search_lines = find.split("\n")
        if search_lines and search_lines[-1] == "":
            search_lines.pop()

        if not search_lines:
            return

        for start in range(0, len(original_lines) - len(search_lines) + 1):
            if all(original_lines[start + offset].strip() == search_lines[offset].strip() for offset in range(len(search_lines))):
                yield "\n".join(original_lines[start : start + len(search_lines)])

    def _indentation_flexible_replacer(self, content: str, find: str) -> Iterator[str]:
        def remove_indentation(value: str) -> str:
            lines = value.split("\n")
            non_empty = [line for line in lines if line.strip()]
            if not non_empty:
                return value
            min_indent = min(len(line) - len(line.lstrip()) for line in non_empty)
            return "\n".join(line[min_indent:] if line.strip() else line for line in lines)

        normalized_find = remove_indentation(find)
        content_lines = content.split("\n")
        find_lines = find.split("\n")

        if not find_lines:
            return

        for start in range(0, len(content_lines) - len(find_lines) + 1):
            block = "\n".join(content_lines[start : start + len(find_lines)])
            if remove_indentation(block) == normalized_find:
                yield block

    def _whitespace_normalized_replacer(self, content: str, find: str) -> Iterator[str]:
        def normalize_whitespace(value: str) -> str:
            return " ".join(value.split())

        normalized_find = normalize_whitespace(find)
        lines = content.split("\n")

        for line in lines:
            if normalize_whitespace(line) == normalized_find:
                yield line

        find_lines = find.split("\n")
        if len(find_lines) > 1:
            for start in range(0, len(lines) - len(find_lines) + 1):
                block = "\n".join(lines[start : start + len(find_lines)])
                if normalize_whitespace(block) == normalized_find:
                    yield block

    def _trimmed_boundary_replacer(self, content: str, find: str) -> Iterator[str]:
        trimmed_find = find.strip()
        if trimmed_find and trimmed_find != find:
            if trimmed_find in content:
                yield trimmed_find

            lines = content.split("\n")
            find_lines = find.split("\n")
            if find_lines:
                for start in range(0, len(lines) - len(find_lines) + 1):
                    block = "\n".join(lines[start : start + len(find_lines)])
                    if block.strip() == trimmed_find:
                        yield block

    def _block_anchor_replacer(self, content: str, find: str) -> Iterator[str]:
        search_lines = find.split("\n")
        if search_lines and search_lines[-1] == "":
            search_lines.pop()
        if len(search_lines) < 3:
            return

        content_lines = content.split("\n")
        first_line = search_lines[0].strip()
        last_line = search_lines[-1].strip()

        candidates: List[Tuple[int, int, float]] = []
        for start in range(len(content_lines)):
            if content_lines[start].strip() != first_line:
                continue
            for end in range(start + 2, len(content_lines)):
                if content_lines[end].strip() != last_line:
                    continue
                actual_middle = content_lines[start + 1 : end]
                search_middle = search_lines[1:-1]
                compare_count = min(len(actual_middle), len(search_middle))
                if compare_count == 0:
                    similarity = 1.0
                else:
                    similarity = 0.0
                    for index in range(compare_count):
                        left = actual_middle[index].strip()
                        right = search_middle[index].strip()
                        max_len = max(len(left), len(right), 1)
                        similarity += 1 - (levenshtein(left, right) / max_len)
                    similarity /= compare_count
                candidates.append((start, end, similarity))
                break

        if not candidates:
            return

        candidates.sort(key=lambda item: item[2], reverse=True)
        best_start, best_end, best_similarity = candidates[0]
        if best_similarity < 0.3 and len(candidates) > 1:
            return
        yield "\n".join(content_lines[best_start : best_end + 1])

    def _replace_text(self, content: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        if old_string == new_string:
            raise ValueError("old_string 和 new_string 完全相同，没有可应用的修改")

        not_found = True
        replacers = [
            self._simple_replacer,
            self._line_trimmed_replacer,
            self._block_anchor_replacer,
            self._whitespace_normalized_replacer,
            self._indentation_flexible_replacer,
            self._trimmed_boundary_replacer,
        ]

        for replacer in replacers:
            for candidate in replacer(content, old_string):
                index = content.find(candidate)
                if index == -1:
                    continue
                not_found = False
                if replace_all:
                    return content.replace(candidate, new_string)
                if content.find(candidate, index + 1) != -1:
                    continue
                return content[:index] + new_string + content[index + len(candidate) :]

        if not_found:
            raise ValueError("无法在文件中找到 old_string，对应文本必须唯一且足够明确")
        raise ValueError("找到了多个候选匹配，请提供更多上下文让 old_string 唯一")

    async def edit_file(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        encoding: str = "utf-8",
        expected_sha256: Optional[str] = None,
        expected_mtime_ns: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            self._assert_mutable()
            file_path = self._resolve_path(path, allow_missing=(old_string == ""))
            self._assert_not_ignored(file_path, is_directory=False)

            existed = file_path.exists()
            if existed and file_path.is_dir():
                raise IsADirectoryError(f"目标是目录，不是文件: {file_path}")
            if existed:
                self._assert_version(
                    file_path,
                    expected_sha256=expected_sha256,
                    expected_mtime_ns=expected_mtime_ns,
                )

            old_content = file_path.read_text(encoding=encoding) if existed else ""
            if old_string == "":
                new_content = new_string
            else:
                if not existed:
                    raise FileNotFoundError(f"文件不存在，无法执行基于 old_string 的编辑: {file_path}")
                new_content = self._replace_text(old_content, old_string, new_string, replace_all=replace_all)

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(new_content, encoding=encoding)

            return self._success(
                {
                    **self._path_payload(file_path),
                    "encoding": encoding,
                    "created": not existed,
                    "replace_all": replace_all,
                    "diff": build_text_diff(self._relative_to_root(file_path), old_content, new_content),
                    "signature": self._file_signature(file_path),
                }
            )
        except Exception as exc:
            return self._error(str(exc), path=path)

    def _strip_patch_heredoc(self, patch_text: str) -> str:
        stripped = patch_text.strip()
        import re

        match = re.match(r"^(?:cat\s+)?<<['\"]?(\w+)['\"]?\s*\n([\s\S]*?)\n\1\s*$", stripped)
        if match:
            return match.group(2)
        return stripped

    def _parse_patch_header(self, lines: List[str], start_index: int) -> Optional[Tuple[str, str, Optional[str], int]]:
        line = lines[start_index]
        if line.startswith("*** Add File:"):
            file_path = line[len("*** Add File:") :].strip()
            return ("add", file_path, None, start_index + 1) if file_path else None

        if line.startswith("*** Delete File:"):
            file_path = line[len("*** Delete File:") :].strip()
            return ("delete", file_path, None, start_index + 1) if file_path else None

        if line.startswith("*** Update File:"):
            file_path = line[len("*** Update File:") :].strip()
            if not file_path:
                return None

            move_path: Optional[str] = None
            next_index = start_index + 1
            if next_index < len(lines) and lines[next_index].startswith("*** Move to:"):
                move_path = lines[next_index][len("*** Move to:") :].strip()
                next_index += 1

            return ("update", file_path, move_path, next_index)

        return None

    def _parse_update_chunks(self, lines: List[str], start_index: int) -> Tuple[List[PatchChunk], int]:
        chunks: List[PatchChunk] = []
        index = start_index

        while index < len(lines) and not lines[index].startswith("***"):
            if not lines[index].startswith("@@"):
                index += 1
                continue

            context_line = lines[index][2:].strip() or None
            index += 1

            old_lines: List[str] = []
            new_lines: List[str] = []
            is_end_of_file = False

            while index < len(lines) and not lines[index].startswith("@@") and not lines[index].startswith("***"):
                current = lines[index]
                if current == "*** End of File":
                    is_end_of_file = True
                    index += 1
                    break
                if current.startswith(" "):
                    content = current[1:]
                    old_lines.append(content)
                    new_lines.append(content)
                elif current.startswith("-"):
                    old_lines.append(current[1:])
                elif current.startswith("+"):
                    new_lines.append(current[1:])
                index += 1

            chunks.append(
                PatchChunk(
                    old_lines=old_lines,
                    new_lines=new_lines,
                    change_context=context_line,
                    is_end_of_file=is_end_of_file,
                )
            )

        return chunks, index

    def _parse_add_file_content(self, lines: List[str], start_index: int) -> Tuple[str, int]:
        content_lines: List[str] = []
        index = start_index

        while index < len(lines) and not lines[index].startswith("***"):
            if lines[index].startswith("+"):
                content_lines.append(lines[index][1:])
            index += 1

        return "\n".join(content_lines), index

    def _parse_patch(self, patch_text: str) -> List[PatchHunk]:
        cleaned = self._strip_patch_heredoc(patch_text)
        lines = cleaned.splitlines()
        begin_index = next((i for i, line in enumerate(lines) if line.strip() == "*** Begin Patch"), -1)
        end_index = next((i for i, line in enumerate(lines) if line.strip() == "*** End Patch"), -1)

        if begin_index == -1 or end_index == -1 or begin_index >= end_index:
            raise ValueError("Invalid patch format: missing Begin/End markers")

        hunks: List[PatchHunk] = []
        index = begin_index + 1

        while index < end_index:
            header = self._parse_patch_header(lines, index)
            if header is None:
                index += 1
                continue

            hunk_type, file_path, move_path, next_index = header
            if hunk_type == "add":
                contents, index = self._parse_add_file_content(lines, next_index)
                hunks.append(PatchHunk(type="add", path=file_path, contents=contents))
                continue

            if hunk_type == "delete":
                hunks.append(PatchHunk(type="delete", path=file_path))
                index = next_index
                continue

            chunks, index = self._parse_update_chunks(lines, next_index)
            hunks.append(PatchHunk(type="update", path=file_path, move_path=move_path, chunks=chunks))

        return hunks

    def _seek_sequence(
        self,
        lines: List[str],
        pattern: List[str],
        start_index: int,
        end_of_file: bool = False,
    ) -> int:
        if not pattern:
            return -1

        comparators = [
            lambda left, right: left == right,
            lambda left, right: left.rstrip() == right.rstrip(),
            lambda left, right: left.strip() == right.strip(),
            lambda left, right: normalize_unicode(left.strip()) == normalize_unicode(right.strip()),
        ]

        for compare in comparators:
            if end_of_file:
                from_end = len(lines) - len(pattern)
                if from_end >= start_index:
                    if all(compare(lines[from_end + offset], pattern[offset]) for offset in range(len(pattern))):
                        return from_end

            for index in range(start_index, len(lines) - len(pattern) + 1):
                if all(compare(lines[index + offset], pattern[offset]) for offset in range(len(pattern))):
                    return index

        return -1

    def _derive_new_contents_from_chunks(self, file_path: Path, chunks: List[PatchChunk], encoding: str) -> Tuple[str, str]:
        original_content = file_path.read_text(encoding=encoding)
        original_lines = original_content.split("\n")
        if original_lines and original_lines[-1] == "":
            original_lines.pop()

        replacements: List[Tuple[int, int, List[str]]] = []
        line_index = 0

        for chunk in chunks:
            if chunk.change_context:
                context_index = self._seek_sequence(original_lines, [chunk.change_context], line_index)
                if context_index == -1:
                    raise ValueError(f"Failed to find context '{chunk.change_context}' in {file_path}")
                line_index = context_index + 1

            if not chunk.old_lines:
                insertion_index = len(original_lines)
                replacements.append((insertion_index, 0, list(chunk.new_lines)))
                continue

            pattern = list(chunk.old_lines)
            new_slice = list(chunk.new_lines)
            found = self._seek_sequence(original_lines, pattern, line_index, chunk.is_end_of_file)

            if found == -1 and pattern and pattern[-1] == "":
                pattern = pattern[:-1]
                if new_slice and new_slice[-1] == "":
                    new_slice = new_slice[:-1]
                found = self._seek_sequence(original_lines, pattern, line_index, chunk.is_end_of_file)

            if found == -1:
                raise ValueError(f"Failed to find expected lines in {file_path}:\n" + "\n".join(chunk.old_lines))

            replacements.append((found, len(pattern), new_slice))
            line_index = found + len(pattern)

        replacements.sort(key=lambda item: item[0])
        updated_lines = list(original_lines)
        for start_index, old_length, new_segment in reversed(replacements):
            updated_lines[start_index : start_index + old_length] = new_segment

        if not updated_lines or updated_lines[-1] != "":
            updated_lines.append("")

        new_content = "\n".join(updated_lines)
        diff = build_text_diff(self._relative_to_root(file_path), original_content, new_content)
        return new_content, diff

    async def apply_patch(self, patch_text: str, encoding: str = "utf-8") -> Dict[str, Any]:
        try:
            self._assert_mutable()
            hunks = self._parse_patch(patch_text)
            if not hunks:
                raise ValueError("patch rejected: no hunks found")

            changes: List[Dict[str, Any]] = []
            diffs: List[str] = []

            for hunk in hunks:
                source_path = self._resolve_path(hunk.path, allow_missing=(hunk.type == "add"))
                if hunk.type == "add":
                    self._assert_not_ignored(source_path, is_directory=False)
                    if source_path.exists():
                        raise FileExistsError(f"apply_patch add 目标已存在: {source_path}")
                    changes.append(
                        {
                            "type": "add",
                            "path": source_path,
                            "new_content": hunk.contents + ("\n" if hunk.contents and not hunk.contents.endswith("\n") else ""),
                            "diff": build_text_diff(self._relative_to_root(source_path), "", hunk.contents),
                        }
                    )
                    diffs.append(changes[-1]["diff"])
                    continue

                if not source_path.exists():
                    raise FileNotFoundError(f"patch 目标不存在: {source_path}")

                self._assert_not_ignored(source_path, is_directory=source_path.is_dir())

                if hunk.type == "delete":
                    if source_path.is_dir():
                        raise IsADirectoryError(f"apply_patch delete 仅支持文件: {source_path}")
                    old_content = source_path.read_text(encoding=encoding)
                    diff = build_text_diff(self._relative_to_root(source_path), old_content, "")
                    changes.append(
                        {
                            "type": "delete",
                            "path": source_path,
                            "old_content": old_content,
                            "diff": diff,
                        }
                    )
                    diffs.append(diff)
                    continue

                if source_path.is_dir():
                    raise IsADirectoryError(f"apply_patch update 仅支持文件: {source_path}")

                new_content, diff = self._derive_new_contents_from_chunks(source_path, hunk.chunks or [], encoding)
                move_path = None
                if hunk.move_path:
                    move_path = self._resolve_path(hunk.move_path, allow_missing=True)
                    self._assert_not_ignored(move_path, is_directory=False)
                    if move_path != source_path and move_path.exists():
                        raise FileExistsError(f"apply_patch move 目标已存在: {move_path}")

                changes.append(
                    {
                        "type": "move" if move_path and move_path != source_path else "update",
                        "path": source_path,
                        "move_path": move_path,
                        "new_content": new_content,
                        "diff": diff,
                    }
                )
                diffs.append(diff)

            summary: List[str] = []
            changed_files: List[Dict[str, Any]] = []

            for change in changes:
                change_type = change["type"]
                file_path: Path = change["path"]

                if change_type == "add":
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(change["new_content"], encoding=encoding)
                    summary.append(f"A {self._relative_to_root(file_path)}")
                    changed_files.append(
                        {
                            "type": "add",
                            "path": str(file_path),
                            "relative_path": self._relative_to_root(file_path),
                            "signature": self._file_signature(file_path),
                        }
                    )
                    continue

                if change_type == "delete":
                    file_path.unlink()
                    summary.append(f"D {self._relative_to_root(file_path)}")
                    changed_files.append(
                        {
                            "type": "delete",
                            "path": str(file_path),
                            "relative_path": self._relative_to_root(file_path),
                        }
                    )
                    continue

                if change_type == "move":
                    move_path = change["move_path"]
                    move_path.parent.mkdir(parents=True, exist_ok=True)
                    move_path.write_text(change["new_content"], encoding=encoding)
                    file_path.unlink()
                    summary.append(f"M {self._relative_to_root(move_path)}")
                    changed_files.append(
                        {
                            "type": "move",
                            "path": str(file_path),
                            "relative_path": self._relative_to_root(file_path),
                            "move_path": str(move_path),
                            "move_relative_path": self._relative_to_root(move_path),
                            "signature": self._file_signature(move_path),
                        }
                    )
                    continue

                file_path.write_text(change["new_content"], encoding=encoding)
                summary.append(f"M {self._relative_to_root(file_path)}")
                changed_files.append(
                    {
                        "type": "update",
                        "path": str(file_path),
                        "relative_path": self._relative_to_root(file_path),
                        "signature": self._file_signature(file_path),
                    }
                )

            return self._success(
                {
                    "updated_files": summary,
                    "diff": "\n\n".join(part for part in diffs if part),
                    "files": changed_files,
                }
            )
        except Exception as exc:
            return self._error(str(exc))

    async def handle_call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.ignore_matcher.reload()

        handlers = {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "create_directory": self.create_directory,
            "list_directory": self.list_directory,
            "delete_file": self.delete_file,
            "file_exists": self.file_exists,
            "copy_file": self.copy_file,
            "move_file": self.move_file,
            "apply_diff": self.apply_diff,
            "edit_file": self.edit_file,
            "apply_patch": self.apply_patch,
        }

        handler = handlers.get(name)
        if handler is None:
            return self._error(f"未知工具: {name}")

        try:
            return await handler(**arguments)
        except TypeError as exc:
            return self._error(f"工具参数不匹配: {exc}", tool=name, arguments=arguments)

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


def parse_cli(argv: List[str]) -> Tuple[Path, bool, bool]:
    root_arg: Optional[str] = None
    read_only = False
    allow_outside_workspace = False

    for argument in argv:
        if argument == "--read-only":
            read_only = True
            continue
        if argument == "--allow-outside-workspace":
            allow_outside_workspace = True
            continue
        if root_arg is None:
            root_arg = argument
            continue
        raise SystemExit(f"未知参数: {argument}")

    env_root = os.environ.get("FS_ROOT")
    env_read_only = parse_bool(os.environ.get("FS_READ_ONLY"), default=False)
    env_allow_outside_workspace = parse_bool(os.environ.get("FS_ALLOW_OUTSIDE_WORKSPACE"), default=False)

    root = Path(root_arg or env_root or os.getcwd())
    return root, (read_only or env_read_only), (allow_outside_workspace or env_allow_outside_workspace)


if __name__ == "__main__":
    workspace_root, read_only_mode, allow_outside_workspace_mode = parse_cli(sys.argv[1:])
    server = FilesystemServer(
        workspace_root=workspace_root,
        read_only=read_only_mode,
        allow_outside_workspace=allow_outside_workspace_mode,
    )
    asyncio.run(server.run())
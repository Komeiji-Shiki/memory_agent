"""
JSONC（带注释的 JSON）解析工具 - 全项目唯一实现

历史上 proxy/config.py、proxy/config_hot_reload.py、web/core.py、
memory_agent/context_builder.py 各自维护了一份注释剥离逻辑，行为不完全一致。
现统一收敛到本模块，修改注释解析行为只需改这里。

提供：
- strip_jsonc_comments(content): 移除 /* */ 与 // 注释（保护字符串内的 //）
- load_jsonc(path): 读取并解析 JSONC 文件，失败抛异常
- load_jsonc_cached(path): 带 mtime 缓存的读取，适合每请求调用的热路径
"""

import json
import os
import re
import threading
from typing import Any, Dict, Optional, Tuple

__all__ = ["strip_jsonc_comments", "load_jsonc", "load_jsonc_cached", "invalidate_jsonc_cache"]


def strip_jsonc_comments(content: str) -> str:
    """
    移除 JSONC 注释

    支持:
    - 多行注释 /* ... */
    - 单行注释 // ...（保留字符串中的 //，如 URL）
    """
    # 1. 移除多行注释 /* ... */
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

    # 2. 移除单行注释 // ...（但保留字符串中的 //）
    lines = []
    for line in content.split('\n'):
        if '//' in line:
            in_string = False
            quote_char = None
            comment_pos = -1

            for i, char in enumerate(line):
                if char in ('"', "'") and (i == 0 or line[i - 1] != '\\'):
                    if not in_string:
                        in_string = True
                        quote_char = char
                    elif char == quote_char:
                        in_string = False
                        quote_char = None
                elif char == '/' and i < len(line) - 1 and line[i + 1] == '/' and not in_string:
                    comment_pos = i
                    break

            if comment_pos >= 0:
                line = line[:comment_pos]

        lines.append(line)

    return '\n'.join(lines)


def load_jsonc(path: str) -> Dict[str, Any]:
    """
    读取并解析 JSONC 文件。

    Raises:
        OSError: 文件读取失败
        json.JSONDecodeError: JSON 解析失败
    """
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    return json.loads(strip_jsonc_comments(content))


# ---------- 带 mtime 缓存的读取 ----------

_cache_lock = threading.Lock()
# path(绝对路径) -> (mtime, parsed_dict)
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def load_jsonc_cached(path: str, force_reload: bool = False) -> Optional[Dict[str, Any]]:
    """
    带 mtime 缓存的 JSONC 读取。文件未修改时直接返回缓存结果，
    适合每请求都要查配置的热路径（避免重复磁盘 IO 与解析）。

    Returns:
        解析后的字典；文件不存在或解析失败返回 None（失败会保留旧缓存不覆盖）。
    """
    abs_path = os.path.abspath(path)

    if not os.path.exists(abs_path):
        return None

    try:
        mtime = os.path.getmtime(abs_path)
    except OSError:
        return None

    with _cache_lock:
        cached = _cache.get(abs_path)
        if not force_reload and cached is not None and cached[0] == mtime:
            return cached[1]

    try:
        parsed = load_jsonc(abs_path)
    except Exception:
        # 解析失败：如有旧缓存返回旧值，避免瞬时写入半个文件导致配置抖动
        with _cache_lock:
            cached = _cache.get(abs_path)
        return cached[1] if cached is not None else None

    with _cache_lock:
        _cache[abs_path] = (mtime, parsed)
    return parsed


def invalidate_jsonc_cache(path: Optional[str] = None) -> None:
    """使缓存失效。path 为 None 时清空全部。"""
    with _cache_lock:
        if path is None:
            _cache.clear()
        else:
            _cache.pop(os.path.abspath(path), None)

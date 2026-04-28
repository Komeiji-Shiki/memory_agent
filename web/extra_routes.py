"""
额外挂载 API 路由

提供额外挂载文件（prefix.md / suffix.md）的读取和编辑接口
"""

import os
from pathlib import Path
from flask import Blueprint, request, jsonify
from .core import load_config, get_lifebook_path

# 创建蓝图
extra_bp = Blueprint('extra_api', __name__)


def _get_extra_paths():
    """获取额外挂载文件的路径配置"""
    config = load_config()
    ctx_config = config.get("context", {})
    extra_mount = ctx_config.get("extra_mount", {})
    
    return {
        "enabled": extra_mount.get("enabled", False),
        "prefix_path": extra_mount.get("prefix_path", "lifebook/extra/prefix.md"),
        "suffix_path": extra_mount.get("suffix_path", "lifebook/extra/suffix.md")
    }


def _resolve_path(relative_path: str) -> Path:
    """将相对路径解析为绝对路径"""
    # 相对于项目根目录
    base_dir = Path(get_lifebook_path()).parent
    return base_dir / relative_path


@extra_bp.route('/extra', methods=['GET'])
def get_extra_config():
    """获取额外挂载配置和内容"""
    try:
        paths = _get_extra_paths()
        
        # 读取文件内容
        prefix_content = ""
        suffix_content = ""
        
        prefix_path = _resolve_path(paths["prefix_path"])
        suffix_path = _resolve_path(paths["suffix_path"])
        
        if prefix_path.exists():
            prefix_content = prefix_path.read_text(encoding="utf-8")
        
        if suffix_path.exists():
            suffix_content = suffix_path.read_text(encoding="utf-8")
        
        return jsonify({
            "enabled": paths["enabled"],
            "prefix": {
                "path": paths["prefix_path"],
                "content": prefix_content,
                "exists": prefix_path.exists()
            },
            "suffix": {
                "path": paths["suffix_path"],
                "content": suffix_content,
                "exists": suffix_path.exists()
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@extra_bp.route('/extra/prefix', methods=['GET'])
def get_prefix():
    """获取前置挂载内容"""
    try:
        paths = _get_extra_paths()
        prefix_path = _resolve_path(paths["prefix_path"])
        
        if prefix_path.exists():
            content = prefix_path.read_text(encoding="utf-8")
        else:
            content = ""
        
        return jsonify({
            "path": paths["prefix_path"],
            "content": content,
            "exists": prefix_path.exists()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@extra_bp.route('/extra/prefix', methods=['PUT', 'POST'])
def save_prefix():
    """保存前置挂载内容"""
    try:
        data = request.get_json()
        content = data.get("content", "")
        
        paths = _get_extra_paths()
        prefix_path = _resolve_path(paths["prefix_path"])
        
        # 确保目录存在
        prefix_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        prefix_path.write_text(content, encoding="utf-8")
        
        return jsonify({
            "success": True,
            "message": "前置挂载已保存",
            "path": paths["prefix_path"],
            "length": len(content)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@extra_bp.route('/extra/suffix', methods=['GET'])
def get_suffix():
    """获取后置挂载内容"""
    try:
        paths = _get_extra_paths()
        suffix_path = _resolve_path(paths["suffix_path"])
        
        if suffix_path.exists():
            content = suffix_path.read_text(encoding="utf-8")
        else:
            content = ""
        
        return jsonify({
            "path": paths["suffix_path"],
            "content": content,
            "exists": suffix_path.exists()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@extra_bp.route('/extra/suffix', methods=['PUT', 'POST'])
def save_suffix():
    """保存后置挂载内容"""
    try:
        data = request.get_json()
        content = data.get("content", "")
        
        paths = _get_extra_paths()
        suffix_path = _resolve_path(paths["suffix_path"])
        
        # 确保目录存在
        suffix_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        suffix_path.write_text(content, encoding="utf-8")
        
        return jsonify({
            "success": True,
            "message": "后置挂载已保存",
            "path": paths["suffix_path"],
            "length": len(content)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@extra_bp.route('/extra/toggle', methods=['POST'])
def toggle_extra_mount():
    """启用/禁用额外挂载"""
    try:
        from .core import save_config
        
        data = request.get_json()
        enabled = data.get("enabled", False)
        
        config = load_config()
        
        # 确保 context.extra_mount 存在
        if "context" not in config:
            config["context"] = {}
        if "extra_mount" not in config["context"]:
            config["context"]["extra_mount"] = {}
        
        config["context"]["extra_mount"]["enabled"] = enabled
        
        save_config(config)
        
        return jsonify({
            "success": True,
            "enabled": enabled,
            "message": f"额外挂载已{'启用' if enabled else '禁用'}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
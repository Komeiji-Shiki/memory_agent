"""
Web API Core - 核心配置和组件初始化

提供：
- 配置加载（带缓存）
- 组件延迟初始化
- 共享变量
"""

import os
import re
import json
from typing import Dict, Optional

# 全局组件（延迟初始化）
_reader = None
_writer = None
_indexer = None
_lifebook_path = None
_backup_path = None

# 配置缓存
_config_cache = None
_config_mtime = None
_CONFIG_CACHE_TTL = 5  # 缓存有效期（秒），用于热重载检测

# 上传文件安全限制
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100MB
MAX_ZIP_FILES = 10000  # zip内最大文件数
MAX_ZIP_RATIO = 100  # 最大压缩比（防止zip炸弹）


def get_config_path() -> str:
    """获取配置文件路径"""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.jsonc')


def load_config(force_reload: bool = False) -> Dict:
    """
    加载配置文件（带缓存）
    
    Args:
        force_reload: 强制重新加载，忽略缓存
        
    Returns:
        配置字典
    """
    global _config_cache, _config_mtime
    
    config_path = get_config_path()
    
    if not os.path.exists(config_path):
        return {}
    
    # 检查缓存是否有效
    current_mtime = os.path.getmtime(config_path)
    
    if not force_reload and _config_cache is not None:
        # 文件未修改，使用缓存
        if _config_mtime == current_mtime:
            return _config_cache
    
    # 需要重新加载
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 移除JSONC注释
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    lines = []
    for line in content.split('\n'):
        if '//' in line:
            in_string = False
            quote_char = None
            comment_pos = -1
            for i, char in enumerate(line):
                if char in ('"', "'") and (i == 0 or line[i-1] != '\\'):
                    if not in_string:
                        in_string = True
                        quote_char = char
                    elif char == quote_char:
                        in_string = False
                        quote_char = None
                elif char == '/' and i < len(line) - 1 and line[i+1] == '/' and not in_string:
                    comment_pos = i
                    break
            if comment_pos >= 0:
                line = line[:comment_pos]
        lines.append(line)
    
    content = '\n'.join(lines)
    config = json.loads(content)
    
    # 更新缓存
    _config_cache = config
    _config_mtime = current_mtime
    
    return config


def invalidate_config_cache():
    """手动使配置缓存失效"""
    global _config_cache, _config_mtime
    _config_cache = None
    _config_mtime = None


def save_config(config: Dict) -> bool:
    """
    保存配置文件
    
    改进: 保留文件顶部的注释块（如版权声明、功能说明等）
    注意: 内部注释仍会丢失，这是JSON格式的限制
    """
    global _config_cache, _config_mtime
    
    config_path = get_config_path()
    
    # 尝试保留顶部注释块
    header_comments = ""
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                lines = []
                in_block_comment = False
                for line in f:
                    stripped = line.strip()
                    
                    # 处理块注释
                    if '/*' in stripped:
                        in_block_comment = True
                    if in_block_comment:
                        lines.append(line)
                        if '*/' in stripped:
                            in_block_comment = False
                        continue
                    
                    # 保留开头的单行注释和空行
                    if stripped.startswith('//') or stripped == '':
                        lines.append(line)
                    else:
                        # 遇到第一个非注释行（JSON内容），停止
                        break
                
                header_comments = ''.join(lines)
        except Exception:
            header_comments = ""
    
    # 生成格式化的JSON
    output = json.dumps(config, ensure_ascii=False, indent=4)
    
    with open(config_path, 'w', encoding='utf-8') as f:
        if header_comments:
            f.write(header_comments)
        f.write(output)
        f.write('\n')
    
    # 使缓存失效
    _config_cache = None
    _config_mtime = None
    
    return True


def init_components():
    """初始化组件"""
    global _reader, _writer, _indexer, _lifebook_path, _backup_path
    
    if _reader is not None:
        return
    
    try:
        config = load_config()
        lifebook_config = config.get('lifebook', {})
        _lifebook_path = lifebook_config.get('root_path', './lifebook')
        _backup_path = lifebook_config.get('backup_path', './backups')
        encoding = lifebook_config.get('encoding', 'utf-8')
        
        # 将相对路径转换为绝对路径（相对于项目根目录）
        project_root = os.path.dirname(os.path.dirname(__file__))
        if not os.path.isabs(_lifebook_path):
            _lifebook_path = os.path.normpath(os.path.join(project_root, _lifebook_path))
        if not os.path.isabs(_backup_path):
            _backup_path = os.path.normpath(os.path.join(project_root, _backup_path))
        
        from memory_store.reader import LifeBookReader
        from memory_store.writer import LifeBookWriter
        from memory_store.sqlite_indexer import SqliteIndexer
        
        _reader = LifeBookReader(_lifebook_path, encoding)
        _writer = LifeBookWriter(_lifebook_path, encoding)
        _indexer = SqliteIndexer(_lifebook_path, encoding=encoding)
        
        # 初始化调试日志器
        from memory_store.debug_logger import get_debug_logger
        debug_log_dir = os.path.join(_lifebook_path, "debug_logs")
        get_debug_logger(debug_log_dir)
    except Exception as e:
        print(f"[Web API] 组件初始化失败: {e}")


def get_reader():
    """获取 Reader 实例"""
    init_components()
    return _reader


def get_writer():
    """获取 Writer 实例"""
    init_components()
    return _writer


def get_indexer():
    """获取 Indexer 实例"""
    init_components()
    return _indexer


def get_lifebook_path() -> Optional[str]:
    """获取 LifeBook 路径"""
    init_components()
    return _lifebook_path


def get_backup_path() -> Optional[str]:
    """获取备份路径"""
    init_components()
    return _backup_path
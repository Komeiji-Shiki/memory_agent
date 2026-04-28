"""
配置热重载模块

实现配置文件修改后自动重载，无需重启服务。

特性：
- 文件监听（使用轮询，无需额外依赖）
- 配置验证
- 平滑过渡
- 线程安全
- 事件通知

使用方式：
    from proxy.config_hot_reload import get_hot_config
    
    config_manager = get_hot_config()
    
    # 获取当前配置（始终是最新的）
    config = config_manager.get_config()
    
    # 订阅配置变更事件
    def on_config_changed(new_config, old_config):
        print("配置已更新！")
    
    config_manager.subscribe(on_config_changed)
"""

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# 导入配置验证（如果可用）
try:
    from .config_validator import ConfigValidator, ServerConfig
    HAS_VALIDATOR = True
except ImportError:
    HAS_VALIDATOR = False


@dataclass
class ConfigChangeEvent:
    """配置变更事件"""
    old_config: Dict[str, Any]
    new_config: Dict[str, Any]
    changed_keys: Set[str]
    timestamp: float = field(default_factory=time.time)
    
    def is_changed(self, key: str) -> bool:
        """检查特定键是否变更"""
        return key in self.changed_keys
    
    def get_changed_paths(self) -> List[str]:
        """获取变更的完整路径列表"""
        return sorted(self.changed_keys)


class ConfigFileWatcher:
    """
    配置文件监听器
    
    使用轮询方式监听文件变化，避免引入额外依赖。
    """
    
    def __init__(
        self,
        config_path: str = "config.jsonc",
        poll_interval: float = 1.0,
        on_change: Optional[Callable[[], None]] = None
    ):
        """
        初始化监听器
        
        Args:
            config_path: 配置文件路径
            poll_interval: 轮询间隔（秒）
            on_change: 变更回调函数
        """
        self.config_path = Path(config_path)
        self.poll_interval = poll_interval
        self.on_change = on_change
        
        self._last_modified: float = 0
        self._last_size: int = 0
        self._running = False
        self._watcher_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # 初始化文件状态
        self._update_file_state()
    
    def _update_file_state(self) -> bool:
        """更新文件状态，返回是否有变化"""
        try:
            if not self.config_path.exists():
                return False
            
            stat = self.config_path.stat()
            current_modified = stat.st_mtime
            current_size = stat.st_size
            
            with self._lock:
                modified_changed = current_modified != self._last_modified
                size_changed = current_size != self._last_size
                
                if modified_changed or size_changed:
                    self._last_modified = current_modified
                    self._last_size = current_size
                    return True
            
            return False
            
        except Exception as e:
            print(f"[ConfigWatcher] 检查文件状态失败: {e}")
            return False
    
    def _watch_loop(self):
        """监听循环"""
        while self._running:
            try:
                if self._update_file_state():
                    print(f"[ConfigWatcher] 检测到配置文件变更: {self.config_path}")
                    if self.on_change:
                        try:
                            self.on_change()
                        except Exception as e:
                            print(f"[ConfigWatcher] 变更回调执行失败: {e}")
            except Exception as e:
                print(f"[ConfigWatcher] 监听循环出错: {e}")
            
            time.sleep(self.poll_interval)
    
    def start(self):
        """启动监听"""
        if self._running:
            return
        
        self._running = True
        self._watcher_thread = threading.Thread(
            target=self._watch_loop,
            name="ConfigWatcher",
            daemon=True
        )
        self._watcher_thread.start()
        print(f"[ConfigWatcher] 开始监听配置文件: {self.config_path}")
    
    def stop(self):
        """停止监听"""
        self._running = False
        if self._watcher_thread and self._watcher_thread.is_alive():
            self._watcher_thread.join(timeout=2.0)
        print("[ConfigWatcher] 停止监听")
    
    def force_check(self) -> bool:
        """强制检查文件变化"""
        return self._update_file_state()


class HotConfigManager:
    """
    热配置管理器
    
    管理配置的加载、验证、热重载。
    """
    
    # 需要重启生效的配置项
    RESTART_REQUIRED_KEYS = {
        "host",
        "port",
        "mcp_servers",  # MCP服务器配置变更需要重启
        "graphiti.backend",  # 后端数据库变更需要重启
        "graphiti.kuzu.db_path",  # 数据库路径变更需要重启
    }
    
    def __init__(
        self,
        config_path: str = "config.jsonc",
        auto_reload: bool = True,
        poll_interval: float = 1.0,
        validate_config: bool = True
    ):
        """
        初始化热配置管理器
        
        Args:
            config_path: 配置文件路径
            auto_reload: 是否启用自动重载
            poll_interval: 轮询间隔（秒）
            validate_config: 是否验证配置
        """
        self.config_path = config_path
        self.validate_config = validate_config and HAS_VALIDATOR
        self._config: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._subscribers: List[Callable[[ConfigChangeEvent], None]] = []
        self._watcher: Optional[ConfigFileWatcher] = None
        
        # 初始加载
        self._load_config()
        
        # 启动监听
        if auto_reload:
            self._start_watching(poll_interval)
    
    def _strip_jsonc_comments(self, content: str) -> str:
        """移除 JSONC 注释"""
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
        
        return '\n'.join(lines)
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        default_config = {
            "chat_completions_url": "https://api.deepseek.com/v1/chat/completions",
            "models_url": "https://api.deepseek.com/v1/models",
            "api_key": "",
            "access_keys": [],
            "allow_user_api_key": True,
            "host": "127.0.0.1",
            "port": 8002,
            "debug": False,
            "mcp_enabled": True,
            "auto_execute_mcp_tools": True,
            "max_iterations": 100,
            "keep_tool_results_count": 0,
            "max_retries": 0,
            "system_prompt_enabled": False,
            "system_prompt": "",
        }
        
        try:
            if not os.path.exists(self.config_path):
                print(f"[HotConfig] 配置文件不存在: {self.config_path}，使用默认配置")
                with self._lock:
                    self._config = default_config.copy()
                return self._config
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 移除 JSONC 注释
            content = self._strip_jsonc_comments(content)
            
            # 解析 JSON
            config = json.loads(content)
            
            # 合并默认配置
            merged = default_config.copy()
            merged.update(config)
            
            # 验证配置
            if self.validate_config:
                merged = self._validate_config(merged)
            
            with self._lock:
                old_config = self._config.copy() if self._config else {}
                self._config = merged
            
            print(f"[HotConfig] 配置加载成功: {self.config_path}")
            return merged
            
        except json.JSONDecodeError as e:
            print(f"[HotConfig] JSON 解析错误: {e}")
            # 如果已有配置，保留旧配置
            with self._lock:
                if self._config:
                    return self._config.copy()
                self._config = default_config.copy()
                return self._config
                
        except Exception as e:
            print(f"[HotConfig] 加载配置失败: {e}")
            with self._lock:
                if self._config:
                    return self._config.copy()
                self._config = default_config.copy()
                return self._config
    
    def _validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """验证并修正配置"""
        try:
            if HAS_VALIDATOR:
                validated = ConfigValidator.validate_dict(config)
                print("[HotConfig] 配置验证通过")
                return validated
        except Exception as e:
            print(f"[HotConfig] 配置验证警告: {e}")
        
        return config
    
    def _detect_changes(
        self,
        old_config: Dict[str, Any],
        new_config: Dict[str, Any],
        prefix: str = ""
    ) -> Set[str]:
        """检测配置变化"""
        changes = set()
        
        all_keys = set(old_config.keys()) | set(new_config.keys())
        
        for key in all_keys:
            full_key = f"{prefix}.{key}" if prefix else key
            
            if key not in old_config:
                changes.add(full_key)
            elif key not in new_config:
                changes.add(full_key)
            elif isinstance(old_config[key], dict) and isinstance(new_config[key], dict):
                nested_changes = self._detect_changes(
                    old_config[key], new_config[key], full_key
                )
                changes.update(nested_changes)
            elif old_config[key] != new_config[key]:
                changes.add(full_key)
        
        return changes
    
    def _check_restart_required(self, changed_keys: Set[str]) -> bool:
        """检查变更是否需要重启"""
        for key in changed_keys:
            for restart_key in self.RESTART_REQUIRED_KEYS:
                if key == restart_key or key.startswith(restart_key + "."):
                    return True
        return False
    
    def _on_config_file_changed(self):
        """配置文件变更回调"""
        print("[HotConfig] 检测到配置文件变更，开始重载...")
        
        old_config = self.get_config()
        new_config = self._load_config()
        
        # 检测变化
        changed_keys = self._detect_changes(old_config, new_config)
        
        if not changed_keys:
            print("[HotConfig] 配置内容未发生变化")
            return
        
        print(f"[HotConfig] 变更的配置项: {', '.join(sorted(changed_keys))}")
        
        # 检查是否需要重启
        restart_required = self._check_restart_required(changed_keys)
        if restart_required:
            print("[HotConfig] ⚠️ 警告: 部分配置变更需要重启服务才能生效")
            print(f"[HotConfig] 需要重启的变更: {[k for k in changed_keys if any(k == r or k.startswith(r + '.') for r in self.RESTART_REQUIRED_KEYS)]}")
        
        # 创建变更事件
        event = ConfigChangeEvent(
            old_config=old_config,
            new_config=new_config,
            changed_keys=changed_keys
        )
        
        # 通知订阅者
        self._notify_subscribers(event)
    
    def _start_watching(self, poll_interval: float):
        """启动文件监听"""
        self._watcher = ConfigFileWatcher(
            config_path=self.config_path,
            poll_interval=poll_interval,
            on_change=self._on_config_file_changed
        )
        self._watcher.start()
    
    def _notify_subscribers(self, event: ConfigChangeEvent):
        """通知所有订阅者"""
        for subscriber in self._subscribers:
            try:
                subscriber(event)
            except Exception as e:
                print(f"[HotConfig] 订阅者通知失败: {e}")
    
    # ==================== 公共 API ====================
    
    def get_config(self) -> Dict[str, Any]:
        """
        获取当前配置
        
        Returns:
            当前配置字典（副本，线程安全）
        """
        with self._lock:
            return self._config.copy()
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项
        
        Args:
            key: 配置键（支持点号分隔的路径，如 "graphiti.enabled"）
            default: 默认值
            
        Returns:
            配置值
        """
        config = self.get_config()
        keys = key.split('.')
        
        value = config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def subscribe(self, callback: Callable[[ConfigChangeEvent], None]) -> None:
        """
        订阅配置变更事件
        
        Args:
            callback: 回调函数，接收 ConfigChangeEvent 参数
        """
        self._subscribers.append(callback)
        print(f"[HotConfig] 新订阅者已注册，当前订阅者数: {len(self._subscribers)}")
    
    def unsubscribe(self, callback: Callable[[ConfigChangeEvent], None]) -> bool:
        """
        取消订阅
        
        Args:
            callback: 之前注册的回调函数
            
        Returns:
            是否成功取消
        """
        if callback in self._subscribers:
            self._subscribers.remove(callback)
            print(f"[HotConfig] 订阅者已移除，当前订阅者数: {len(self._subscribers)}")
            return True
        return False
    
    def reload(self) -> bool:
        """
        手动强制重载配置
        
        Returns:
            是否成功
        """
        try:
            self._on_config_file_changed()
            return True
        except Exception as e:
            print(f"[HotConfig] 手动重载失败: {e}")
            return False
    
    def stop(self):
        """停止监听"""
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "config_path": str(self.config_path),
            "subscriber_count": len(self._subscribers),
            "watching": self._watcher is not None and self._watcher._running,
            "config_keys": len(self._config) if self._config else 0,
        }


# ==================== 全局单例 ====================

_hot_config_instance: Optional[HotConfigManager] = None


def get_hot_config(
    config_path: str = "config.jsonc",
    auto_reload: bool = True,
    poll_interval: float = 1.0
) -> HotConfigManager:
    """
    获取全局热配置管理器实例
    
    Args:
        config_path: 配置文件路径
        auto_reload: 是否启用自动重载
        poll_interval: 轮询间隔（秒）
        
    Returns:
        HotConfigManager 实例
    """
    global _hot_config_instance
    
    if _hot_config_instance is None:
        _hot_config_instance = HotConfigManager(
            config_path=config_path,
            auto_reload=auto_reload,
            poll_interval=poll_interval
        )
    
    return _hot_config_instance


def reset_hot_config():
    """重置全局实例（主要用于测试）"""
    global _hot_config_instance
    if _hot_config_instance:
        _hot_config_instance.stop()
        _hot_config_instance = None


# ==================== 便捷函数 ====================

def get_config_value(key: str, default: Any = None) -> Any:
    """
    获取配置值的便捷函数
    
    使用全局实例获取配置值。
    
    Args:
        key: 配置键（支持点号分隔的路径）
        default: 默认值
        
    Returns:
        配置值
    """
    return get_hot_config().get(key, default)


# 兼容性：保持与旧代码兼容
def get_config() -> Dict[str, Any]:
    """
    获取配置的兼容性函数
    
    保持与 proxy.config.get_config() 的兼容性。
    """
    return get_hot_config().get_config()


# ==================== 测试代码 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("Hot Config Manager 测试")
    print("=" * 60)
    
    # 创建测试配置文件
    test_config = {
        "host": "127.0.0.1",
        "port": 8002,
        "debug": False,
        "nested": {
            "key1": "value1",
            "key2": 42
        }
    }
    
    test_path = "test_config.jsonc"
    with open(test_path, 'w', encoding='utf-8') as f:
        json.dump(test_config, f, indent=2)
    
    print(f"\n创建测试配置文件: {test_path}")
    
    # 初始化热配置管理器
    manager = HotConfigManager(test_path, auto_reload=True, poll_interval=0.5)
    
    # 测试订阅
    def on_change(event: ConfigChangeEvent):
        print(f"\n[回调] 配置变更！")
        print(f"  变更项: {event.changed_keys}")
        print(f"  新值 port: {event.new_config.get('port')}")
    
    manager.subscribe(on_change)
    
    # 获取配置
    config = manager.get_config()
    print(f"\n初始配置:")
    print(f"  host: {config.get('host')}")
    print(f"  port: {config.get('port')}")
    print(f"  nested.key1: {manager.get('nested.key1')}")
    
    # 模拟文件修改
    print("\n模拟配置文件修改...")
    test_config["port"] = 8080
    test_config["nested"]["key2"] = 100
    
    with open(test_path, 'w', encoding='utf-8') as f:
        json.dump(test_config, f, indent=2)
    
    # 等待轮询检测
    time.sleep(2)
    
    # 检查新配置
    new_config = manager.get_config()
    print(f"\n更新后的配置:")
    print(f"  port: {new_config.get('port')}")
    print(f"  nested.key2: {manager.get('nested.key2')}")
    
    # 清理
    manager.stop()
    os.remove(test_path)
    
    print("\n测试完成！")
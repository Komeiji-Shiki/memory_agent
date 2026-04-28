"""
Metadata Manager - 元数据管理

管理LifeBook的元数据，包括：
- 上次交互时间
- 统计信息
- 配置状态
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path


class MetadataManager:
    """元数据管理器"""
    
    METADATA_FILE = ".lifebook_metadata.json"
    
    def __init__(self, lifebook_path: str):
        """
        初始化元数据管理器
        
        Args:
            lifebook_path: LifeBook根目录
        """
        self.root_path = Path(lifebook_path)
        self.metadata_file = self.root_path / self.METADATA_FILE
        self._metadata: Optional[Dict[str, Any]] = None
    
    def _load(self) -> Dict[str, Any]:
        """加载元数据"""
        if self._metadata is not None:
            return self._metadata
        
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    self._metadata = json.load(f)
            except Exception:
                self._metadata = self._default_metadata()
        else:
            self._metadata = self._default_metadata()
        
        return self._metadata
    
    def _save(self) -> None:
        """保存元数据"""
        if self._metadata is None:
            return
        
        try:
            self.root_path.mkdir(parents=True, exist_ok=True)
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self._metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Metadata] 保存失败: {e}")
    
    def _default_metadata(self) -> Dict[str, Any]:
        """默认元数据"""
        return {
            "created_at": datetime.now().isoformat(),
            "last_interaction": None,
            "interaction_count": 0,
            "version": "1.0"
        }
    
    # ===== 上次交互时间 =====
    
    def get_last_interaction(self) -> Optional[datetime]:
        """获取上次交互时间"""
        metadata = self._load()
        last = metadata.get("last_interaction")
        if last:
            try:
                return datetime.fromisoformat(last)
            except Exception:
                pass
        return None
    
    def update_last_interaction(self) -> None:
        """更新上次交互时间为现在"""
        metadata = self._load()
        metadata["last_interaction"] = datetime.now().isoformat()
        metadata["interaction_count"] = metadata.get("interaction_count", 0) + 1
        self._save()
    
    # ===== 统计信息 =====
    
    def get_interaction_count(self) -> int:
        """获取交互次数"""
        return self._load().get("interaction_count", 0)
    
    def get_created_at(self) -> Optional[datetime]:
        """获取创建时间"""
        metadata = self._load()
        created = metadata.get("created_at")
        if created:
            try:
                return datetime.fromisoformat(created)
            except Exception:
                pass
        return None
    
    # ===== 自定义数据 =====
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取自定义数据"""
        return self._load().get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """设置自定义数据"""
        metadata = self._load()
        metadata[key] = value
        self._save()
    
    # ===== 完整元数据 =====
    
    def get_all(self) -> Dict[str, Any]:
        """获取所有元数据"""
        return self._load().copy()
    
    def reset(self) -> None:
        """重置元数据"""
        self._metadata = self._default_metadata()
        self._save()


# 全局实例缓存
_managers: Dict[str, MetadataManager] = {}


def get_metadata_manager(lifebook_path: str) -> MetadataManager:
    """获取元数据管理器（单例）"""
    path_key = os.path.abspath(lifebook_path)
    if path_key not in _managers:
        _managers[path_key] = MetadataManager(lifebook_path)
    return _managers[path_key]


# 测试代码已移至 tests/test_memory_store.py
"""
Message Orchestrator - 消息编排器

负责管理和应用消息序列编排规则，支持：
- 伪造 user/assistant 消息
- 可视化拖拽排序
- 预设管理（多套配置切换）
- 模型绑定（不同模型用不同规则）
- 历史回滚
- 导入/导出

## 🎯 核心思路

AI模型的行为很大程度上受到"对话历史"的影响。如果模型看到自己"之前已经"
以某种方式回复过，它会倾向于保持一致性。

伪造Role的原理：
1. 在system提示词之后注入一组伪造的 user → assistant 对话
2. 让AI认为它已经"接受"了某个角色设定并开始扮演
3. 真实用户的对话从第N轮开始，AI会延续伪造历史中的行为模式
"""

import json
import fnmatch
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
import copy


class ComponentType(Enum):
    """
    消息组件类型
    
    ## 缓存优化设计
    
    API prompt caching（如 Claude/Anthropic）基于前缀匹配：
    - 前面的内容相同 → 可以复用缓存
    - 如果前面有变化，后面全部重新计算
    
    因此组件分为两类：
    1. **稳定组件**（放前面，可缓存）：角色设定、记忆库范围、分层记忆、检索结果
    2. **易变组件**（放后面）：当前时间、pending 内容
    
    默认序列顺序：
    system_prompt → prefix_mount → memory_range → layered_memory →
    dynamic_search → tools_hint → suffix_mount →
    [cache_break] → volatile_context → real_messages
    """
    SYSTEM_PROMPT = "system_prompt"       # 客户端发来的system（角色设定）
    FAKE_USER = "fake_user"               # 伪造的用户消息
    FAKE_ASSISTANT = "fake_assistant"     # 伪造的助手回复
    PREFIX_MOUNT = "prefix_mount"         # 前置挂载 (prefix.md)
    MEMORY_RANGE = "memory_range"         # 记忆库范围说明（相对稳定）
    LAYERED_MEMORY = "layered_memory"     # 分层记忆（日记/总结）
    DYNAMIC_SEARCH = "dynamic_search"     # Agent 动态检索结果
    TOOLS_HINT = "tools_hint"             # 工具调用提示词
    SUFFIX_MOUNT = "suffix_mount"         # 后置挂载 (suffix.md)
    # === 以下是易变组件（放在 real_messages 之前）===
    CACHE_BREAK = "cache_break"           # 缓存分隔点（伪造 assistant 确认）
    VOLATILE_CONTEXT = "volatile_context" # 易变上下文（时间 + pending）
    # 保留旧组件（向后兼容，现已合并到 volatile_context）
    TIME_CONTEXT = "time_context"         # [deprecated] 当前时间上下文
    PENDING_MEMORY = "pending_memory"     # [deprecated] 待归档记忆
    CUSTOM_BLOCK = "custom_block"         # 自定义文本块
    REAL_MESSAGES = "real_messages"       # 真实对话历史
    # === 条件挂载（仅对部分模型生效）===
    CONDITIONAL_MOUNT = "conditional_mount"  # 条件额外挂载


class InjectMode(Enum):
    """组件注入模式"""
    APPEND_TO_SYSTEM = "append_to_system"           # 追加到system消息末尾
    STANDALONE_USER = "standalone_user"             # 作为独立的user消息
    STANDALONE_ASSISTANT = "standalone_assistant"   # 作为独立的assistant消息
    PREPEND_TO_FIRST_USER = "prepend_to_first_user" # 追加到第一条真实user消息前


@dataclass
class SequenceComponent:
    """序列中的单个组件"""
    id: str                                    # 唯一标识
    type: str                                  # 组件类型
    content: str = ""                          # 内容（伪造消息/自定义块）
    inject_mode: str = "standalone_user"       # 注入模式
    locked: bool = False                       # 是否锁定（不可移动/删除）
    file_path: str = ""                        # 挂载文件路径
    enabled: bool = True                       # 是否启用
    # 条件挂载专用字段
    match_mode: str = "regex"                  # 匹配模式: "regex" 或 "list"
    model_pattern: str = ""                    # 正则表达式（match_mode=regex 时）
    model_list: List[str] = field(default_factory=list)  # 模型名列表（match_mode=list 时）
    mount_title: str = ""                      # 挂载标题（可选）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {}
        for k, v in asdict(self).items():
            # 始终包含 locked 和 enabled
            if k in ['locked', 'enabled']:
                result[k] = v
            # 对于列表类型，只有非空时才包含
            elif k == 'model_list':
                if v:
                    result[k] = v
            # 其他字段只有有值时才包含
            elif v:
                result[k] = v
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SequenceComponent':
        """从字典创建"""
        return cls(
            id=data.get('id', ''),
            type=data.get('type', ''),
            content=data.get('content', ''),
            inject_mode=data.get('inject_mode', 'standalone_user'),
            locked=data.get('locked', False),
            file_path=data.get('file_path', ''),
            enabled=data.get('enabled', True),
            match_mode=data.get('match_mode', 'regex'),
            model_pattern=data.get('model_pattern', ''),
            model_list=data.get('model_list', []),
            mount_title=data.get('mount_title', '')
        )


@dataclass
class Preset:
    """编排预设"""
    name: str                                  # 预设名称
    description: str = ""                      # 预设描述
    sequence: List[SequenceComponent] = field(default_factory=list)
    created_at: str = ""                       # 创建时间
    updated_at: str = ""                       # 更新时间
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "sequence": [c.to_dict() for c in self.sequence],
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Preset':
        """从字典创建"""
        return cls(
            name=data.get('name', ''),
            description=data.get('description', ''),
            sequence=[SequenceComponent.from_dict(c) for c in data.get('sequence', [])],
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', '')
        )


@dataclass
class HistoryEntry:
    """历史记录条目"""
    timestamp: str
    action: str
    description: str
    snapshot: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HistoryEntry':
        return cls(
            timestamp=data.get('timestamp', ''),
            action=data.get('action', ''),
            description=data.get('description', ''),
            snapshot=data.get('snapshot', {})
        )


class MessageOrchestrator:
    """消息编排器"""
    
    # 新的默认序列（缓存优化版本）
    # 稳定内容在前 → 易变内容在后 → 真实对话
    DEFAULT_SEQUENCE = [
        # ===== 稳定部分（可缓存）=====
        {"id": "sys_prompt", "type": "system_prompt", "locked": True},
        {"id": "prefix_mount", "type": "prefix_mount", "file_path": "lifebook/extra/prefix.md"},
        {"id": "memory_range", "type": "memory_range"},
        {"id": "layered_memory", "type": "layered_memory"},
        {"id": "dynamic_search", "type": "dynamic_search"},
        {"id": "tools_hint", "type": "tools_hint"},
        {"id": "suffix_mount", "type": "suffix_mount", "file_path": "lifebook/extra/suffix.md"},
        # ===== 缓存分隔点 =====
        {"id": "cache_break", "type": "cache_break", "content": "好的，我已了解以上背景信息。"},
        # ===== 易变部分（时间 + pending）=====
        {"id": "volatile_context", "type": "volatile_context"},
        # ===== 真实对话 =====
        {"id": "real_messages", "type": "real_messages", "locked": True}
    ]
    
    # 旧版序列（向后兼容，保留给不需要缓存优化的场景）
    LEGACY_SEQUENCE = [
        {"id": "sys_prompt", "type": "system_prompt", "locked": True},
        {"id": "prefix_mount", "type": "prefix_mount", "file_path": "lifebook/extra/prefix.md"},
        {"id": "time_context", "type": "time_context"},
        {"id": "memory_range", "type": "memory_range"},
        {"id": "layered_memory", "type": "layered_memory"},
        {"id": "dynamic_search", "type": "dynamic_search"},
        {"id": "tools_hint", "type": "tools_hint"},
        {"id": "suffix_mount", "type": "suffix_mount", "file_path": "lifebook/extra/suffix.md"},
        {"id": "real_messages", "type": "real_messages", "locked": True}
    ]
    
    def __init__(self, config_dir: Path):
        """
        初始化编排器
        
        Args:
            config_dir: 配置目录（通常是 lifebook/extra）
        """
        self.config_dir = Path(config_dir)
        self.sequence_file = self.config_dir / "message_sequence.json"
        self.presets_file = self.config_dir / "message_presets.json"
        self.history_file = self.config_dir / "orchestrator_history.json"
        self.prefill_file = self.config_dir / "prefill_config.json"
        
        self.max_history = 20
        
        # 确保目录存在
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载配置
        self._sequence: List[SequenceComponent] = []
        self._presets: Dict[str, Preset] = {}
        self._active_preset: str = "default"
        self._model_bindings: Dict[str, str] = {}
        self._history: List[HistoryEntry] = []
        
        # 预填充配置
        self._prefill_content: str = ""
        self._prefill_model_bindings: Dict[str, bool] = {}  # 模型名 -> 是否启用预填充
        self._prefill_think_tag: str = "</think>"  # 用于分离 reasoning 和正文的标签
        
        self._load_all()
    
    def _load_all(self):
        """加载所有配置"""
        self._load_sequence()
        self._load_presets()
        self._load_history()
        self._load_prefill()
    
    def _load_sequence(self):
        """加载消息序列"""
        if self.sequence_file.exists():
            try:
                with open(self.sequence_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._sequence = [
                    SequenceComponent.from_dict(c) 
                    for c in data.get('sequence', self.DEFAULT_SEQUENCE)
                ]
                self._model_bindings = data.get('model_bindings', {})
                print(f"[Orchestrator] 加载消息序列: {len(self._sequence)} 个组件")
            except Exception as e:
                print(f"[Orchestrator] 加载序列失败: {e}")
                self._sequence = [SequenceComponent.from_dict(c) for c in self.DEFAULT_SEQUENCE]
        else:
            self._sequence = [SequenceComponent.from_dict(c) for c in self.DEFAULT_SEQUENCE]
    
    def _load_presets(self):
        """加载预设"""
        if self.presets_file.exists():
            try:
                with open(self.presets_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._presets = {
                    name: Preset.from_dict(preset)
                    for name, preset in data.get('presets', {}).items()
                }
                self._active_preset = data.get('active_preset', 'default')
                print(f"[Orchestrator] 加载预设: {len(self._presets)} 个")
            except Exception as e:
                print(f"[Orchestrator] 加载预设失败: {e}")
        
        # 确保有默认预设
        if 'default' not in self._presets:
            self._presets['default'] = Preset(
                name="默认配置",
                description="标准记忆增强模式",
                sequence=[SequenceComponent.from_dict(c) for c in self.DEFAULT_SEQUENCE],
                created_at=datetime.now().isoformat()
            )
    
    def _load_history(self):
        """加载历史记录"""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._history = [
                    HistoryEntry.from_dict(h) 
                    for h in data.get('history', [])
                ]
            except Exception as e:
                print(f"[Orchestrator] 加载历史失败: {e}")
    
    def _save_sequence(self):
        """保存消息序列"""
        data = {
            "version": "1.0",
            "description": "消息编排序列 - 可通过Web界面拖拽编辑",
            "sequence": [c.to_dict() for c in self._sequence],
            "model_bindings": self._model_bindings
        }
        with open(self.sequence_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _save_presets(self):
        """保存预设"""
        data = {
            "presets": {name: preset.to_dict() for name, preset in self._presets.items()},
            "active_preset": self._active_preset
        }
        with open(self.presets_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _save_history(self):
        """保存历史记录"""
        data = {
            "max_history": self.max_history,
            "history": [h.to_dict() for h in self._history[-self.max_history:]]
        }
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _load_prefill(self):
        """加载预填充配置"""
        if self.prefill_file.exists():
            try:
                with open(self.prefill_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._prefill_content = data.get('content', '')
                self._prefill_model_bindings = data.get('model_bindings', {})
                self._prefill_think_tag = data.get('think_tag', '</think>')
                if self._prefill_content:
                    print(f"[Orchestrator] 加载预填充配置: {len(self._prefill_content)} 字符")
            except Exception as e:
                print(f"[Orchestrator] 加载预填充失败: {e}")
    
    def _save_prefill(self):
        """保存预填充配置"""
        data = {
            "version": "1.0",
            "description": "预填充配置 - 在用户最后一条消息后插入助手消息",
            "content": self._prefill_content,
            "model_bindings": self._prefill_model_bindings,
            "think_tag": self._prefill_think_tag
        }
        with open(self.prefill_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _add_history(self, action: str, description: str):
        """添加历史记录"""
        entry = HistoryEntry(
            timestamp=datetime.now().isoformat(),
            action=action,
            description=description,
            snapshot={
                "sequence": [c.to_dict() for c in self._sequence],
                "active_preset": self._active_preset
            }
        )
        self._history.append(entry)
        # 限制历史数量
        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history:]
        self._save_history()
    
    # ==================== 公开 API ====================
    
    def get_sequence(self) -> List[Dict[str, Any]]:
        """获取当前消息序列"""
        return [c.to_dict() for c in self._sequence]
    
    def set_sequence(self, sequence: List[Dict[str, Any]], description: str = "更新序列"):
        """设置消息序列"""
        self._sequence = [SequenceComponent.from_dict(c) for c in sequence]
        self._add_history("update_sequence", description)
        self._save_sequence()
    
    def get_presets(self) -> Dict[str, Dict[str, Any]]:
        """获取所有预设"""
        return {name: preset.to_dict() for name, preset in self._presets.items()}
    
    def get_active_preset(self) -> str:
        """获取当前激活的预设名称"""
        return self._active_preset
    
    def load_preset(self, preset_name: str) -> bool:
        """加载预设"""
        if preset_name not in self._presets:
            return False
        
        preset = self._presets[preset_name]
        self._sequence = copy.deepcopy(preset.sequence)
        self._active_preset = preset_name
        
        self._add_history("load_preset", f"切换到预设: {preset.name}")
        self._save_sequence()
        self._save_presets()
        return True
    
    def save_preset(self, preset_name: str, name: str, description: str = "") -> bool:
        """保存当前序列为预设"""
        now = datetime.now().isoformat()
        
        if preset_name in self._presets:
            # 更新现有预设
            self._presets[preset_name].name = name
            self._presets[preset_name].description = description
            self._presets[preset_name].sequence = copy.deepcopy(self._sequence)
            self._presets[preset_name].updated_at = now
        else:
            # 创建新预设
            self._presets[preset_name] = Preset(
                name=name,
                description=description,
                sequence=copy.deepcopy(self._sequence),
                created_at=now,
                updated_at=now
            )
        
        self._active_preset = preset_name
        self._add_history("save_preset", f"保存预设: {name}")
        self._save_presets()
        return True
    
    def delete_preset(self, preset_name: str) -> bool:
        """删除预设"""
        if preset_name == 'default':
            return False  # 不允许删除默认预设
        
        if preset_name in self._presets:
            del self._presets[preset_name]
            if self._active_preset == preset_name:
                self._active_preset = 'default'
            self._add_history("delete_preset", f"删除预设: {preset_name}")
            self._save_presets()
            return True
        return False
    
    def get_model_bindings(self) -> Dict[str, str]:
        """获取模型绑定规则"""
        return self._model_bindings.copy()
    
    def set_model_bindings(self, bindings: Dict[str, str]):
        """设置模型绑定规则"""
        self._model_bindings = bindings
        self._add_history("update_bindings", "更新模型绑定规则")
        self._save_sequence()
    
    def get_preset_for_model(self, model_name: str) -> str:
        """根据模型名称获取对应的预设"""
        for pattern, preset in self._model_bindings.items():
            if fnmatch.fnmatch(model_name.lower(), pattern.lower()):
                return preset
        return self._active_preset
    
    def get_history(self) -> List[Dict[str, Any]]:
        """获取历史记录"""
        return [h.to_dict() for h in reversed(self._history)]
    
    def rollback_to(self, index: int) -> bool:
        """回滚到指定历史版本"""
        if index < 0 or index >= len(self._history):
            return False
        
        # 历史是倒序的，需要转换索引
        actual_index = len(self._history) - 1 - index
        entry = self._history[actual_index]
        
        snapshot = entry.snapshot
        self._sequence = [
            SequenceComponent.from_dict(c) 
            for c in snapshot.get('sequence', [])
        ]
        self._active_preset = snapshot.get('active_preset', 'default')
        
        self._add_history("rollback", f"回滚到: {entry.description}")
        self._save_sequence()
        return True
    
    def clear_history(self):
        """清空历史记录"""
        self._history = []
        self._save_history()
    
    def export_config(self) -> Dict[str, Any]:
        """导出完整配置"""
        return {
            "version": "1.0",
            "export_time": datetime.now().isoformat(),
            "sequence": [c.to_dict() for c in self._sequence],
            "presets": {name: preset.to_dict() for name, preset in self._presets.items()},
            "active_preset": self._active_preset,
            "model_bindings": self._model_bindings
        }
    
    def import_config(self, config: Dict[str, Any]) -> bool:
        """导入配置"""
        try:
            if 'sequence' in config:
                self._sequence = [
                    SequenceComponent.from_dict(c)
                    for c in config['sequence']
                ]
            
            if 'presets' in config:
                self._presets = {
                    name: Preset.from_dict(preset)
                    for name, preset in config['presets'].items()
                }
            
            if 'active_preset' in config:
                self._active_preset = config['active_preset']
            
            if 'model_bindings' in config:
                self._model_bindings = config['model_bindings']
            
            self._add_history("import", f"导入配置 (版本: {config.get('version', 'unknown')})")
            self._save_sequence()
            self._save_presets()
            return True
        except Exception as e:
            print(f"[Orchestrator] 导入失败: {e}")
            return False
    
    # ==================== 预填充 API ====================
    
    def get_prefill_config(self) -> Dict[str, Any]:
        """获取预填充配置"""
        return {
            "content": self._prefill_content,
            "model_bindings": self._prefill_model_bindings,
            "think_tag": self._prefill_think_tag
        }
    
    def set_prefill_config(self, content: str, model_bindings: Dict[str, bool], think_tag: str = "</think>"):
        """
        设置预填充配置
        
        Args:
            content: 预填充内容（将作为 assistant 消息插入）
            model_bindings: 模型绑定 {模型名: 是否启用预填充}
            think_tag: 思考结束标签（如 </think>）
        """
        self._prefill_content = content
        self._prefill_model_bindings = model_bindings
        self._prefill_think_tag = think_tag
        self._save_prefill()
    
    def should_use_prefill(self, model_name: str) -> bool:
        """
        判断指定模型是否应使用预填充
        
        Args:
            model_name: 模型名称
            
        Returns:
            是否启用预填充
        """
        if not self._prefill_content:
            return False
        
        model_lower = model_name.lower()
        
        # 精确匹配
        if model_name in self._prefill_model_bindings:
            return self._prefill_model_bindings[model_name]
        
        # 通配符匹配（支持 * 通配符，转义方括号）
        for pattern, enabled in self._prefill_model_bindings.items():
            pattern_lower = pattern.lower()
            
            # 简单通配符匹配（处理 * 通配符，不使用 fnmatch 避免方括号问题）
            if '*' in pattern_lower:
                # 将 pattern 转换为正则表达式
                import re
                # 转义所有正则特殊字符，然后将 \* 替换为 .*
                regex_pattern = re.escape(pattern_lower).replace(r'\*', '.*')
                if re.match(f'^{regex_pattern}$', model_lower):
                    print(f"[Orchestrator] 预填充匹配成功: {model_name} ~ {pattern}")
                    return enabled
            elif pattern_lower == model_lower:
                return enabled
        
        # 默认不启用
        return False
    
    def get_prefill_content(self) -> str:
        """获取预填充内容"""
        return self._prefill_content
    
    def get_think_tag(self) -> str:
        """获取思考结束标签"""
        return self._prefill_think_tag
    
    # ==================== 消息应用 ====================
    
    def _check_model_match(self, component: SequenceComponent, model_name: str) -> bool:
        """
        检查模型是否匹配条件挂载的条件
        
        Args:
            component: 条件挂载组件
            model_name: 当前模型名称
            
        Returns:
            是否匹配
        """
        if not model_name:
            return False
        
        model_lower = model_name.lower()
        
        if component.match_mode == "list":
            # 精确列表匹配（忽略大小写）
            for m in component.model_list:
                if m.lower() == model_lower:
                    print(f"[Orchestrator] 条件挂载列表匹配成功: {model_name} == {m}")
                    return True
            return False
        else:
            # 正则/通配符匹配
            if not component.model_pattern:
                return False
            try:
                import re
                pattern = component.model_pattern.lower()  # pattern 也转小写
                
                # 检查是否是简单通配符模式（只包含 * 和普通字符）
                # 将通配符 * 转换为正则 .*，同时转义其他特殊字符
                regex_pattern = re.escape(pattern).replace(r'\*', '.*')
                
                matched = bool(re.match(f'^{regex_pattern}$', model_lower))
                
                if matched:
                    print(f"[Orchestrator] 条件挂载正则匹配成功: {model_name} ~ {component.model_pattern}")
                else:
                    print(f"[Orchestrator] 条件挂载正则匹配失败: {model_name} !~ {component.model_pattern} (regex: ^{regex_pattern}$)")
                
                return matched
            except Exception as e:
                print(f"[Orchestrator] 正则匹配错误: {e}")
                return False
    
    def apply_orchestration(
        self,
        messages: List[Dict[str, Any]],
        model_name: str = "",
        fixed_context: str = "",
        dynamic_context: str = "",
        extra_mount_enabled: bool = False,
        prefix_content: str = "",
        suffix_content: str = "",
        time_context: str = "",
        memory_range: str = "",
        tools_hint: str = "",
        pending_context: str = "",
        apply_prefill: bool = True,
        conditional_mount_contents: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """
        应用编排规则到消息列表
        
        ## 缓存优化设计
        
        消息结构（按顺序）：
        1. **稳定部分**（放 system 消息，可获得 API 缓存命中）
           - 角色设定
           - 前置挂载
           - 记忆库范围
           - 分层记忆
           - 动态检索结果
           - 工具调用提示
           - 后置挂载
        
        2. **缓存分隔点**（伪造 assistant 确认）
           - 打断 user 消息的连续合并
           - 确保稳定部分作为独立的缓存前缀
        
        3. **易变部分**（放独立 user 消息）
           - 当前时间上下文
           - 今日 pending 内容
        
        4. **真实对话历史**
        
        5. **预填充**（如果启用）
        
        Args:
            messages: 原始消息列表 [{"role": "...", "content": "..."}]
            model_name: 模型名称（用于模型绑定）
            fixed_context: 固定上下文（分层记忆内容：日记/总结）
            dynamic_context: 动态上下文（Agent检索结果）
            extra_mount_enabled: 是否启用额外挂载
            prefix_content: 前置挂载内容
            suffix_content: 后置挂载内容
            time_context: 当前时间上下文（易变）
            memory_range: 记忆库范围说明（相对稳定）
            tools_hint: 工具调用提示词
            pending_context: 今日 pending 内容（易变）
            apply_prefill: 是否应用预填充
            
        Returns:
            编排后的消息列表
        """
        # 如果有模型绑定，先加载对应预设
        if model_name and self._model_bindings:
            preset_name = self.get_preset_for_model(model_name)
            if preset_name != self._active_preset and preset_name in self._presets:
                sequence = copy.deepcopy(self._presets[preset_name].sequence)
            else:
                sequence = self._sequence
        else:
            sequence = self._sequence
        
        # 分离原始消息
        system_content = ""
        real_messages = []
        
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")
            else:
                real_messages.append(msg.copy())
        
        # 按序列顺序构建消息列表
        raw_result = []
        
        for component in sequence:
            if not component.enabled:
                continue
            
            comp_type = component.type
            
            if comp_type == ComponentType.SYSTEM_PROMPT.value:
                # system = 角色设定
                if system_content:
                    raw_result.append({
                        "role": "system",
                        "content": system_content,
                        "_source": "system"
                    })
            
            elif comp_type == ComponentType.FAKE_USER.value:
                if component.content:
                    raw_result.append({
                        "role": "user",
                        "content": component.content,
                        "_source": "fake"
                    })
            
            elif comp_type == ComponentType.FAKE_ASSISTANT.value:
                if component.content:
                    raw_result.append({
                        "role": "assistant",
                        "content": component.content,
                        "_source": "fake"
                    })
            
            elif comp_type == ComponentType.PREFIX_MOUNT.value:
                if extra_mount_enabled and prefix_content:
                    raw_result.append({
                        "role": "user",
                        "content": f"## 📎 前置挂载\n\n{prefix_content}",
                        "_source": "prefix_mount"
                    })
            
            elif comp_type == ComponentType.CACHE_BREAK.value:
                # 缓存分隔点：插入一个伪造的 assistant 确认消息
                # 这样可以打断 user 消息的连续合并，让前面的稳定内容成为独立的缓存前缀
                cache_break_content = component.content or "好的，我已了解以上背景信息。"
                if cache_break_content:
                    raw_result.append({
                        "role": "assistant",
                        "content": cache_break_content,
                        "_source": "cache_break"
                    })
            
            elif comp_type == ComponentType.VOLATILE_CONTEXT.value:
                # 易变上下文：时间 + pending（合并到一个 user 消息）
                volatile_parts = []
                if time_context:
                    volatile_parts.append(time_context)
                if pending_context:
                    volatile_parts.append(pending_context)
                if volatile_parts:
                    raw_result.append({
                        "role": "user",
                        "content": "\n\n".join(volatile_parts),
                        "_source": "volatile_context"
                    })
            
            elif comp_type == ComponentType.TIME_CONTEXT.value:
                # [向后兼容] 旧版独立时间上下文
                if time_context:
                    raw_result.append({
                        "role": "user",
                        "content": time_context,
                        "_source": "time_context"
                    })
            
            elif comp_type == ComponentType.PENDING_MEMORY.value:
                # [向后兼容] 旧版独立 pending 内容
                if pending_context:
                    raw_result.append({
                        "role": "user",
                        "content": pending_context,
                        "_source": "pending_memory"
                    })
            
            elif comp_type == ComponentType.MEMORY_RANGE.value:
                if memory_range:
                    raw_result.append({
                        "role": "user",
                        "content": memory_range,
                        "_source": "memory_range"
                    })
            
            elif comp_type == ComponentType.LAYERED_MEMORY.value:
                if fixed_context:
                    raw_result.append({
                        "role": "user",
                        "content": fixed_context,
                        "_source": "layered_memory"
                    })
            
            elif comp_type == ComponentType.DYNAMIC_SEARCH.value:
                if dynamic_context:
                    raw_result.append({
                        "role": "user",
                        "content": dynamic_context,
                        "_source": "dynamic_search"
                    })
            
            elif comp_type == ComponentType.TOOLS_HINT.value:
                if tools_hint:
                    raw_result.append({
                        "role": "user",
                        "content": tools_hint,
                        "_source": "tools_hint"
                    })
            
            elif comp_type == ComponentType.SUFFIX_MOUNT.value:
                if extra_mount_enabled and suffix_content:
                    raw_result.append({
                        "role": "user",
                        "content": f"## 📎 后置挂载\n\n{suffix_content}",
                        "_source": "suffix_mount"
                    })
            
            elif comp_type == ComponentType.CUSTOM_BLOCK.value:
                if component.content:
                    # 自定义块根据 inject_mode 决定 role
                    inject_mode = component.inject_mode
                    if inject_mode == InjectMode.STANDALONE_ASSISTANT.value:
                        role = "assistant"
                    else:
                        role = "user"
                    raw_result.append({
                        "role": role,
                        "content": component.content,
                        "_source": "custom"
                    })
            
            elif comp_type == ComponentType.CONDITIONAL_MOUNT.value:
                # 条件额外挂载：仅当模型匹配时生效
                if self._check_model_match(component, model_name):
                    # 获取挂载内容
                    mount_content = ""
                    if conditional_mount_contents and component.id in conditional_mount_contents:
                        mount_content = conditional_mount_contents[component.id]
                    elif component.content:
                        mount_content = component.content
                    elif component.file_path:
                        # 尝试从文件读取
                        try:
                            file_path = Path(self.config_dir).parent.parent / component.file_path
                            if file_path.exists():
                                mount_content = file_path.read_text(encoding='utf-8')
                        except Exception as e:
                            print(f"[Orchestrator] 读取条件挂载文件失败: {e}")
                    
                    if mount_content:
                        title = component.mount_title or "条件挂载"
                        inject_mode = component.inject_mode
                        if inject_mode == InjectMode.STANDALONE_ASSISTANT.value:
                            role = "assistant"
                        else:
                            role = "user"
                        raw_result.append({
                            "role": role,
                            "content": f"## 📎 {title}\n\n{mount_content}",
                            "_source": "conditional_mount"
                        })
            
            elif comp_type == ComponentType.REAL_MESSAGES.value:
                for msg in real_messages:
                    msg_copy = msg.copy()
                    msg_copy["_source"] = "real"
                    raw_result.append(msg_copy)
        
        # 应用预填充：在用户最后一条真实消息后插入 assistant 消息
        if apply_prefill and self.should_use_prefill(model_name) and self._prefill_content:
            # 找到最后一条用户消息的位置
            last_user_idx = -1
            for i in range(len(raw_result) - 1, -1, -1):
                if raw_result[i].get("role") == "user" and raw_result[i].get("_source") == "real":
                    last_user_idx = i
                    break
            
            # 如果找到了用户消息，在其后插入预填充
            if last_user_idx >= 0:
                prefill_msg = {
                    "role": "assistant",
                    "content": self._prefill_content,
                    "_source": "prefill"
                }
                raw_result.insert(last_user_idx + 1, prefill_msg)
        
        # 合并连续的同 role 消息
        result = []
        for msg in raw_result:
            if result and result[-1]["role"] == msg["role"]:
                # 连续相同 role，合并内容
                result[-1]["content"] += "\n\n" + msg["content"]
                # 保留第一个的 _source，或者标记为 merged
                if result[-1].get("_source") != msg.get("_source"):
                    result[-1]["_source"] = "merged"
            else:
                result.append(msg)
        
        return result
    
    def get_available_components(self) -> List[Dict[str, Any]]:
        """
        返回可用组件列表（用于前端渲染）
        
        ## 缓存优化提示
        
        为了让 API 缓存命中（如 Claude prompt caching），建议按以下顺序排列：
        
        **稳定内容（放前面，可缓存）**：
        - system_prompt → prefix_mount → memory_range → layered_memory
        - dynamic_search → tools_hint → suffix_mount
        
        **缓存分隔点**：
        - cache_break（伪造 assistant 确认，打断合并）
        
        **易变内容（放后面）**：
        - volatile_context（时间 + pending）
        - 或分开用：time_context + pending_memory
        
        **真实对话**：
        - real_messages
        """
        return [
            # ===== 稳定组件（放前面，可缓存）=====
            {
                "type": "prefix_mount",
                "name": "前置挂载",
                "icon": "📎",
                "editable": False,
                "deletable": False,
                "category": "stable",
                "description": "prefix.md 文件内容（稳定，可缓存）"
            },
            {
                "type": "memory_range",
                "name": "记忆库范围",
                "icon": "📊",
                "editable": False,
                "deletable": False,
                "category": "stable",
                "description": "记忆库最早/最新日期、日记总数（相对稳定）"
            },
            {
                "type": "layered_memory",
                "name": "分层记忆",
                "icon": "📖",
                "editable": False,
                "deletable": False,
                "category": "stable",
                "description": "日记/周总结/月总结/季度总结（稳定，可缓存）"
            },
            {
                "type": "dynamic_search",
                "name": "动态检索结果",
                "icon": "🔍",
                "editable": False,
                "deletable": False,
                "category": "stable",
                "description": "Agent 搜索到的相关记忆"
            },
            {
                "type": "tools_hint",
                "name": "工具调用提示",
                "icon": "🔧",
                "editable": False,
                "deletable": False,
                "category": "stable",
                "description": "给主模型的工具调用说明（稳定，可缓存）"
            },
            {
                "type": "suffix_mount",
                "name": "后置挂载",
                "icon": "📎",
                "editable": False,
                "deletable": False,
                "category": "stable",
                "description": "suffix.md 文件内容（稳定，可缓存）"
            },
            # ===== 缓存分隔组件 =====
            {
                "type": "cache_break",
                "name": "缓存分隔点",
                "icon": "✂️",
                "editable": True,
                "deletable": True,
                "category": "cache",
                "description": "伪造 assistant 确认，打断消息合并，让前面的内容成为独立的缓存前缀"
            },
            # ===== 易变组件（放后面）=====
            {
                "type": "volatile_context",
                "name": "易变上下文",
                "icon": "⏰",
                "editable": False,
                "deletable": False,
                "category": "volatile",
                "description": "当前时间 + 今日 pending（合并为一个消息，每次都会变化）"
            },
            {
                "type": "time_context",
                "name": "时间上下文",
                "icon": "📅",
                "editable": False,
                "deletable": False,
                "category": "volatile",
                "description": "[可替换为 volatile_context] 当前日期、时间、周数等（每次变化）"
            },
            {
                "type": "pending_memory",
                "name": "待归档记忆",
                "icon": "🗒️",
                "editable": False,
                "deletable": False,
                "category": "volatile",
                "description": "[可替换为 volatile_context] 今日 pending 内容（经常变化）"
            },
            # ===== 伪造消息 =====
            {
                "type": "fake_user",
                "name": "伪造User消息",
                "icon": "👤",
                "editable": True,
                "deletable": True,
                "category": "fake",
                "description": "伪装的用户消息，让AI以为之前已经有过对话"
            },
            {
                "type": "fake_assistant",
                "name": "伪造Assistant消息",
                "icon": "🤖",
                "editable": True,
                "deletable": True,
                "category": "fake",
                "description": "伪装的AI回复，建立行为模式"
            },
            # ===== 自定义 =====
            {
                "type": "custom_block",
                "name": "自定义文本块",
                "icon": "📝",
                "editable": True,
                "deletable": True,
                "category": "custom",
                "description": "自由添加的文本内容"
            },
            # ===== 条件挂载 =====
            {
                "type": "conditional_mount",
                "name": "条件额外挂载",
                "icon": "🎯",
                "editable": True,
                "deletable": True,
                "category": "conditional",
                "description": "仅对匹配的模型生效的额外挂载内容（支持正则或模型列表）"
            }
        ]


# 全局实例
_orchestrator: Optional[MessageOrchestrator] = None


def get_orchestrator(config_dir: Optional[Path] = None) -> MessageOrchestrator:
    """获取全局编排器实例"""
    global _orchestrator
    
    if _orchestrator is None:
        if config_dir is None:
            # 默认路径
            config_dir = Path("lifebook/extra")
        _orchestrator = MessageOrchestrator(config_dir)
    
    return _orchestrator


def reset_orchestrator():
    """重置全局编排器（用于测试）"""
    global _orchestrator
    _orchestrator = None


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("Message Orchestrator 测试")
    print("=" * 60)
    
    # 使用临时目录测试
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        orchestrator = MessageOrchestrator(Path(tmpdir))
        
        # 测试默认序列
        print("\n📋 默认序列:")
        for i, comp in enumerate(orchestrator.get_sequence()):
            print(f"  [{i}] {comp['type']}")
        
        # 测试添加伪造消息
        sequence = orchestrator.get_sequence()
        sequence.insert(1, {
            "id": "fake_1",
            "type": "fake_user",
            "content": "灰魂，你在吗？"
        })
        sequence.insert(2, {
            "id": "fake_2",
            "type": "fake_assistant",
            "content": "在的主人～有什么事吗？😸"
        })
        orchestrator.set_sequence(sequence, "添加伪造消息测试")
        
        print("\n📋 添加伪造消息后:")
        for i, comp in enumerate(orchestrator.get_sequence()):
            print(f"  [{i}] {comp['type']}: {comp.get('content', '')[:30]}")
        
        # 测试应用编排
        test_messages = [
            {"role": "system", "content": "(测试系统提示词)"},
            {"role": "user", "content": "你好呀！"}
        ]
        
        result = orchestrator.apply_orchestration(
            test_messages,
            fixed_context="## 📅 当前时间\n2026-01-22"
        )
        
        print("\n📋 编排结果:")
        for i, msg in enumerate(result):
            content_preview = msg['content'][:50].replace('\n', ' ')
            source = msg.get('_source', 'unknown')
            print(f"  [{i}] {msg['role']} ({source}): {content_preview}...")
        
        # 测试预设
        orchestrator.save_preset("test_preset", "测试预设", "用于测试的预设")
        print(f"\n📋 预设列表: {list(orchestrator.get_presets().keys())}")
        
        # 测试历史
        print(f"\n📋 历史记录: {len(orchestrator.get_history())} 条")
        
        # 测试导出
        export = orchestrator.export_config()
        print(f"\n📋 导出配置: {len(json.dumps(export))} 字符")
        
    print("\n测试完成！ ✅")
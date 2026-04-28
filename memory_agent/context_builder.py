"""
Context Builder - 上下文组装器

负责将记忆上下文注入到消息列表中。

## 📍 插入位置详解

本模块支持5种记忆注入位置，每种适用于不同的场景：

### 1. system_append（默认，推荐）
- **效果**: 在系统提示词末尾追加记忆内容
- **消息结构**: `[{system: 原提示词 + 记忆}, {user}, {assistant}, ...]`
- **适用场景**: 大多数情况，记忆作为系统上下文的补充
- **优点**: 不破坏原有对话结构，记忆权重适中
- **缺点**: 如果系统提示词很长，记忆可能被"淹没"

### 2. system_prepend
- **效果**: 在系统提示词最前面插入记忆内容
- **消息结构**: `[{system: 记忆 + 原提示词}, {user}, {assistant}, ...]`
- **适用场景**: 记忆信息优先级最高，需要模型首先关注
- **优点**: 记忆获得最高注意力权重
- **缺点**: 可能干扰模型对系统角色设定的理解

### 3. after_system
- **效果**: 在系统消息后，以独立的user消息形式插入
- **消息结构**: `[{system}, {user: 记忆}, {assistant: 确认}, {原对话}...]`
- **适用场景**: 需要模拟"先提供背景信息再对话"的场景
- **优点**: 记忆作为独立消息，不影响系统提示；可配置assistant确认
- **缺点**: 增加了消息数量，可能消耗更多token

### 4. before_last_user
- **效果**: 在最后一条用户消息之前插入
- **消息结构**: `[{system}, {...历史对话...}, {user: 记忆}, {user: 当前问题}]`
- **适用场景**: 只为当前问题提供相关记忆，不影响历史对话理解
- **优点**: 记忆与当前问题紧密关联
- **缺点**: 两条连续user消息可能导致某些模型困惑

### 5. replace_system
- **效果**: 完全用记忆内容替换系统提示词
- **消息结构**: `[{system: 记忆}, {user}, {assistant}, ...]`
- **适用场景**: 原系统提示词不重要，或记忆本身包含完整的角色设定
- **优点**: 记忆获得绝对的系统级权重
- **缺点**: 丢失原系统提示词，需谨慎使用

## 🎯 选择建议

| 场景 | 推荐位置 |
|------|----------|
| 普通对话 + 记忆增强 | system_append |
| 记忆信息最重要 | system_prepend |
| 需要模拟多轮引导 | after_system |
| 只增强当前问题 | before_last_user |
| 纯记忆驱动对话 | replace_system |

## 📁 配置方式

在 config.jsonc 中设置：
```json
{
  "context": {
    "insertion_position": "system_append",
    "simple_mode_insertion_position": "before_last_user"
  }
}
```

或在代码中：
```python
config = ContextConfig(
    insertion_position=InsertionPosition.SYSTEM_APPEND
)
```
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from memory_store.reader import LifeBookReader
from memory_store.metadata import MetadataManager
from .message_orchestrator import get_orchestrator, MessageOrchestrator


class InsertionPosition(Enum):
    """
    记忆插入位置枚举
    
    定义记忆内容注入到消息列表的位置策略。
    详细说明见模块文档字符串。
    
    Attributes:
        SYSTEM_PREPEND: 系统提示词最前面（记忆优先级最高）
        SYSTEM_APPEND: 系统提示词末尾（默认，推荐）
        AFTER_SYSTEM: 系统消息后独立插入（模拟多轮引导）
        BEFORE_LAST_USER: 最后用户消息前（只增强当前问题）
        REPLACE_SYSTEM: 完全替换系统提示（谨慎使用）
    """
    SYSTEM_PREPEND = "system_prepend"    # 系统提示词前：高优先级
    SYSTEM_APPEND = "system_append"      # 系统提示词后：默认推荐
    AFTER_SYSTEM = "after_system"        # 系统消息后独立user消息
    BEFORE_LAST_USER = "before_last_user"  # 最后用户消息前
    REPLACE_SYSTEM = "replace_system"    # 替换系统提示词


@dataclass
class ContextConfig:
    """上下文配置"""
    # 插入位置
    insertion_position: InsertionPosition = InsertionPosition.SYSTEM_APPEND
    
    # 格式模板
    prefix: str = "\n\n---\n## 📚 相关记忆\n\n"
    suffix: str = "\n---\n"
    empty_hint: str = "(未找到相关记忆)"
    
    # 确认消息（用于 after_system 和 before_last_user 模式）
    enable_confirmation: bool = False
    assistant_ack: str = "好的，我已了解这些背景信息。"
    
    # ===== 额外挂载配置 =====
    # 可选的自定义永久记忆文件，用于存放角色设定、特殊指令等
    extra_mount_enabled: bool = False
    # 前置挂载：插在系统提示后、所有记忆前面
    extra_mount_prefix_path: str = "lifebook/extra/prefix.md"
    # 后置挂载：插在所有记忆后面
    extra_mount_suffix_path: str = "lifebook/extra/suffix.md"
    
    # ===== 分层记忆配置 =====
    use_layered_memory: bool = True  # 是否启用分层记忆系统
    # 短期记忆：最近N天的日记（完整内容）
    short_term_days: int = 7
    short_term_max_chars: int = 3000  # 每篇日记最大字符数
    
    # 中短期记忆：本月内超过短期天数的周总结
    include_weekly_summaries: bool = True
    weekly_max_chars: int = 1500  # 每个周总结最大字符
    
    # 中期记忆：上个月的月总结
    include_monthly_summaries: bool = True
    monthly_max_chars: int = 2000
    
    # 长期记忆：更早月份的季度总结
    lookback_months: int = 5  # 回溯月份数
    include_quarterly_summaries: bool = True
    quarterly_max_chars: int = 2500
    
    # 旧配置（保持兼容）
    include_recent_days: int = 7
    include_current_weekly: bool = True
    include_current_monthly: bool = True
    
    # Token限制
    max_context_tokens: int = 8000
    max_chars: int = 32000  # 增加到32000以容纳分层记忆
    
    # 禁用截断（完整发送给主模型）
    disable_truncation: bool = False
    
    # 大模型工具提示（可配置）
    tools_hint: str = ""

    # Simple模式专用插入位置
    simple_mode_insertion_position: Optional[str] = None
    
    # 自定义内容（在记忆后插入）- 旧版配置，建议使用 extra_mount
    custom_content_enabled: bool = False
    custom_content: str = ""
    
    # ===== 消息编排器配置 =====
    use_orchestrator: bool = False  # 是否使用消息编排器


@dataclass
class BuiltContext:
    """组装后的上下文"""
    messages: List[Dict[str, Any]]
    memory_content: str
    fixed_context: str
    dynamic_context: str
    total_chars: int


class ContextBuilder:
    """上下文组装器"""
    
    def __init__(
        self,
        reader: LifeBookReader,
        config: Optional[ContextConfig] = None,
        metadata_manager: Optional[MetadataManager] = None
    ):
        """
        初始化组装器
        
        Args:
            reader: LifeBook读取器
            config: 上下文配置
            metadata_manager: 元数据管理器
        """
        self.reader = reader
        self.config = config or ContextConfig()
        self.metadata = metadata_manager
    
    def build(
        self,
        messages: List[Dict[str, Any]],
        dynamic_memory: str = "",
        include_fixed: bool = True,
        override_insertion_position: Optional[str] = None,
        model_name: str = ""
    ) -> BuiltContext:
        """
        组装完整上下文
        
        Args:
            messages: 原始消息列表
            dynamic_memory: 动态记忆内容（Agent检索结果）
            include_fixed: 是否包含固定上下文（最近日记、当前总结）
            override_insertion_position: 覆盖默认的插入位置
            model_name: 模型名称（用于消息编排器的模型绑定）
            
        Returns:
            BuiltContext
        """
        # 获取固定上下文
        fixed_context = ""
        if include_fixed:
            fixed_context = self._build_fixed_context()
        
        # 检查是否使用消息编排器
        if self._should_use_orchestrator():
            return self._build_with_orchestrator(
                messages, fixed_context, dynamic_memory, model_name
            )
        
        # 传统模式：组合记忆内容
        memory_parts = []
        if fixed_context:
            memory_parts.append(fixed_context)
        if dynamic_memory:
            # 包裹动态记忆并注明来源
            wrapped_dynamic = self._wrap_dynamic_memory(dynamic_memory)
            if wrapped_dynamic:  # 只有非空才添加
                memory_parts.append(wrapped_dynamic)
        
        # 添加自定义内容（在记忆后插入）
        if self.config.custom_content_enabled and self.config.custom_content:
            custom_section = f"\n## 📌 附加说明\n\n{self.config.custom_content}"
            memory_parts.append(custom_section)
        
        memory_content = "\n\n".join(memory_parts) if memory_parts else ""
        
        # 格式化
        if memory_content:
            formatted_memory = f"{self.config.prefix}{memory_content}{self.config.suffix}"
        else:
            formatted_memory = f"{self.config.prefix}{self.config.empty_hint}{self.config.suffix}" if self.config.empty_hint else ""
        
        # 裁剪（如果超长且未禁用截断）
        if not self.config.disable_truncation and len(formatted_memory) > self.config.max_chars:
            formatted_memory = self._truncate_memory(formatted_memory, self.config.max_chars)
        
        # 注入消息
        new_messages = self._inject_memory(messages, formatted_memory, override_insertion_position)
        
        return BuiltContext(
            messages=new_messages,
            memory_content=formatted_memory,
            fixed_context=fixed_context,
            dynamic_context=dynamic_memory,
            total_chars=len(formatted_memory)
        )
    
    def _should_use_orchestrator(self) -> bool:
        """
        检查是否应该使用消息编排器
        
        优先从配置文件热读取，这样修改后不需要重启
        """
        try:
            config_path = Path(self.reader.root_path).parent / "config.jsonc"
            
            if not config_path.exists():
                return self.config.use_orchestrator
            
            config = self._load_jsonc_config(config_path)
            if config is None:
                return self.config.use_orchestrator
            
            orchestrator_cfg = config.get("message_orchestrator", {})
            return orchestrator_cfg.get("enabled", False)
            
        except Exception as e:
            print(f"[ContextBuilder] 读取 orchestrator 配置失败: {e}")
            return self.config.use_orchestrator
    
    def _build_with_orchestrator(
        self,
        messages: List[Dict[str, Any]],
        fixed_context: str,
        dynamic_context: str,
        model_name: str
    ) -> BuiltContext:
        """
        使用消息编排器构建上下文
        
        编排器负责消息的排列顺序，这里负责准备各部分内容：
        - time_context: 当前时间上下文
        - memory_range: 记忆库范围
        - fixed_context: 分层记忆（日记/总结）- 不含时间和范围
        - dynamic_context: Agent检索结果
        - tools_hint: 工具调用提示
        - prefix/suffix: 额外挂载
        
        Args:
            messages: 原始消息列表
            fixed_context: 固定上下文（分层记忆，已不含时间和范围）
            dynamic_context: 动态上下文（Agent检索结果）
            model_name: 模型名称
            
        Returns:
            BuiltContext
        """
        try:
            # 获取编排器
            config_dir = Path(self.reader.root_path) / "extra"
            orchestrator = get_orchestrator(config_dir)
            
            # 获取额外挂载内容
            extra_mount_enabled = self._is_extra_mount_enabled()
            prefix_content = ""
            suffix_content = ""
            
            if extra_mount_enabled:
                prefix_content = self._read_extra_mount_file(self.config.extra_mount_prefix_path)
                suffix_content = self._read_extra_mount_file(self.config.extra_mount_suffix_path)
            
            # 获取自定义内容（📌 附加说明）- 这是独立于 extra_mount 的配置
            # 附加到 fixed_context 后面（分层记忆之后），这样不依赖 extra_mount 开关
            custom_content = ""
            if self.config.custom_content_enabled and self.config.custom_content:
                custom_content = f"\n\n## 📌 附加说明\n\n{self.config.custom_content}"
            
            # 把自定义内容附加到固定上下文
            if custom_content:
                fixed_context = fixed_context + custom_content if fixed_context else custom_content
            
            # 包裹动态记忆
            wrapped_dynamic = self._wrap_dynamic_memory(dynamic_context) if dynamic_context else ""
            
            # 构建独立的时间上下文
            now = datetime.now()
            time_context = self._build_time_context_only(now)
            
            # 构建独立的记忆库范围
            memory_range = self._build_memory_range_only()
            
            # 获取工具提示词
            tools_hint = ""
            if self.config.tools_hint:
                tools_hint = self.config.tools_hint
            
            # 获取 pending 内容（易变）
            pending_context = self._build_pending_memory(now)
            
            # 应用编排
            new_messages = orchestrator.apply_orchestration(
                messages,
                model_name=model_name,
                fixed_context=fixed_context,
                dynamic_context=wrapped_dynamic,
                extra_mount_enabled=extra_mount_enabled,
                prefix_content=prefix_content,
                suffix_content=suffix_content,
                time_context=time_context,
                memory_range=memory_range,
                tools_hint=tools_hint,
                pending_context=pending_context  # 新增：传递 pending 内容给编排器
            )
            
            # 清理 _source 标记（对外不暴露）
            clean_messages = []
            for m in new_messages:
                clean_msg = {"role": m["role"], "content": m["content"]}
                clean_messages.append(clean_msg)
            
            # 计算总字符数
            total_chars = sum(len(m.get("content", "")) for m in clean_messages)
            
            # 组合记忆内容（用于返回）
            memory_parts = []
            if fixed_context:
                memory_parts.append(fixed_context)
            if wrapped_dynamic:
                memory_parts.append(wrapped_dynamic)
            memory_content = "\n\n".join(memory_parts)
            
            print(f"[ContextBuilder] 使用编排器构建: {len(clean_messages)} 条消息, {total_chars} 字符")
            
            return BuiltContext(
                messages=clean_messages,
                memory_content=memory_content,
                fixed_context=fixed_context,
                dynamic_context=dynamic_context,
                total_chars=total_chars
            )
            
        except Exception as e:
            print(f"[ContextBuilder] 编排器构建失败，回退到传统模式: {e}")
            import traceback
            traceback.print_exc()
            # 回退到传统模式
            return self._build_legacy(messages, fixed_context, dynamic_context)
    
    def _build_time_context_only(self, now: datetime) -> str:
        """构建纯时间上下文（不含记忆范围）"""
        parts = []
        weekday_names = ['周一','周二','周三','周四','周五','周六','周日']
        
        iso_year, week_num, _ = now.isocalendar()
        quarter = (now.month - 1) // 3 + 1
        
        parts.append("## 📅 当前时间上下文")
        parts.append(f"- 日期：{now.strftime('%Y年%m月%d日')} {weekday_names[now.weekday()]}")
        parts.append(f"- 时间：{now.strftime('%H:%M')}")
        parts.append(f"- 本周：{iso_year}年第{week_num}周（{iso_year}-W{week_num:02d}）")
        parts.append(f"- 本月：{now.year}年{now.month}月")
        parts.append(f"- 本季度：{now.year}年Q{quarter}")
        parts.append(f"- 本年：{now.year}年")
        
        last_interaction = self._get_last_interaction_time()
        if last_interaction:
            time_diff = now - last_interaction
            time_diff_str = self._format_time_diff(time_diff)
            parts.append(f"- 距上次对话：{time_diff_str}")
        
        return "\n".join(parts)
    
    def _build_memory_range_only(self) -> str:
        """构建纯记忆库范围说明"""
        memory_range = self._get_memory_date_range()
        if not memory_range:
            return ""
        
        earliest, latest, diary_count = memory_range
        now = datetime.now()
        
        parts = []
        parts.append("### 📚 记忆库范围")
        parts.append(f"- 最早记录：{earliest}")
        parts.append(f"- 最新记录：{latest}")
        parts.append(f"- 日记总数：{diary_count} 篇")
        
        try:
            earliest_date = datetime.strptime(earliest, '%Y-%m-%d')
            days_running = (now - earliest_date).days
            parts.append(f"- 运行天数：{days_running} 天")
            
            if days_running < 30:
                parts.append(f"- ⚠️ **注意**：记忆系统刚上线不久，{earliest} 之前的事情没有记录！")
        except:
            pass
        
        return "\n".join(parts)
    
    def _build_legacy(
        self,
        messages: List[Dict[str, Any]],
        fixed_context: str,
        dynamic_context: str
    ) -> BuiltContext:
        """传统模式构建（回退用）"""
        memory_parts = []
        if fixed_context:
            memory_parts.append(fixed_context)
        if dynamic_context:
            wrapped_dynamic = self._wrap_dynamic_memory(dynamic_context)
            if wrapped_dynamic:
                memory_parts.append(wrapped_dynamic)
        
        if self.config.custom_content_enabled and self.config.custom_content:
            custom_section = f"\n## 📌 附加说明\n\n{self.config.custom_content}"
            memory_parts.append(custom_section)
        
        memory_content = "\n\n".join(memory_parts) if memory_parts else ""
        
        if memory_content:
            formatted_memory = f"{self.config.prefix}{memory_content}{self.config.suffix}"
        else:
            formatted_memory = ""
        
        if not self.config.disable_truncation and len(formatted_memory) > self.config.max_chars:
            formatted_memory = self._truncate_memory(formatted_memory, self.config.max_chars)
        
        new_messages = self._inject_memory(messages, formatted_memory, None)
        
        return BuiltContext(
            messages=new_messages,
            memory_content=formatted_memory,
            fixed_context=fixed_context,
            dynamic_context=dynamic_context,
            total_chars=len(formatted_memory)
        )
    
    def _wrap_dynamic_memory(self, dynamic_memory: str) -> str:
        """
        包裹动态记忆（检索小模型的输出）并注明来源
        
        Args:
            dynamic_memory: Agent 检索结果
            
        Returns:
            包裹后的内容
        """
        if not dynamic_memory or not dynamic_memory.strip():
            return ""
        
        # 检查是否是"无需检索"类的回复
        skip_phrases = ["无需检索", "无需额外检索", "短期记忆已包含", "未找到相关记忆"]
        for phrase in skip_phrases:
            if phrase in dynamic_memory:
                return ""  # 不需要包裹这类回复
        
        # 用 XML 标签包裹，并注明来源
        wrapped = f"""## 🔍 记忆检索结果

> 📄 来源: 由记忆检索工具（search_memories/read_diary/get_node等）获取

<agent_search_result>
{dynamic_memory}
</agent_search_result>

> _以上内容由记忆检索Agent自动搜索得到，如需修改请使用对应的写入工具_"""
        
        return wrapped
    
    def _read_extra_mount_file(self, file_path: str) -> str:
        """
        读取额外挂载文件内容
        
        Args:
            file_path: 相对于项目根目录的文件路径
            
        Returns:
            文件内容，如果文件不存在或读取失败则返回空字符串
        """
        try:
            # 构建完整路径（相对于项目根目录）
            full_path = Path(self.reader.root_path).parent / file_path
            
            if not full_path.exists():
                return ""
            
            with open(full_path, 'r', encoding=self.reader.encoding) as f:
                content = f.read().strip()
            
            if content:
                print(f"[ContextBuilder] 读取额外挂载文件: {file_path} ({len(content)} 字符)")
            return content
            
        except Exception as e:
            print(f"[ContextBuilder] 读取额外挂载文件失败 {file_path}: {e}")
            return ""
    
    def _is_extra_mount_enabled(self) -> bool:
        """
        动态检查额外挂载是否启用（从配置文件热读取）
        
        这样修改启用状态后不需要重启服务器
        """
        try:
            config_path = Path(self.reader.root_path).parent / "config.jsonc"
            
            if not config_path.exists():
                return self.config.extra_mount_enabled
            
            config = self._load_jsonc_config(config_path)
            if config is None:
                return self.config.extra_mount_enabled
            
            extra_mount = config.get("context", {}).get("extra_mount", {})
            return extra_mount.get("enabled", False)
            
        except Exception as e:
            # 读取失败时使用缓存的配置
            print(f"[ContextBuilder] 动态读取 extra_mount 配置失败: {e}")
            return self.config.extra_mount_enabled
    
    def _load_jsonc_config(self, config_path: Path) -> Optional[dict]:
        """
        安全地加载 JSONC 配置文件
        
        正确处理注释：只移除行首或独立的 // 注释，不影响 URL 中的 //
        """
        try:
            import json
            import re
            
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 移除块注释 /* ... */（跨行）
            content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
            
            # 移除行注释 // ...
            # 但要避免移除 URL 中的 //，所以只匹配：
            # 1. 行首的 // （前面只有空白）
            # 2. 逗号后面的 //
            # 3. 字符串外部的 //（简化处理：只处理明显的行尾注释）
            lines = content.split('\n')
            cleaned_lines = []
            for line in lines:
                # 找到行注释位置（不在字符串内）
                # 简单策略：如果 // 在引号对之外，就认为是注释
                cleaned_line = self._remove_line_comment(line)
                cleaned_lines.append(cleaned_line)
            
            content = '\n'.join(cleaned_lines)
            
            return json.loads(content)
            
        except Exception as e:
            print(f"[ContextBuilder] 解析 JSONC 失败: {e}")
            return None
    
    def _remove_line_comment(self, line: str) -> str:
        """
        移除行中的 // 注释，但保留字符串内的 //
        """
        in_string = False
        escape_next = False
        i = 0
        
        while i < len(line):
            char = line[i]
            
            if escape_next:
                escape_next = False
                i += 1
                continue
            
            if char == '\\':
                escape_next = True
                i += 1
                continue
            
            if char == '"':
                in_string = not in_string
                i += 1
                continue
            
            # 如果不在字符串内，检查是否是注释开始
            if not in_string and i + 1 < len(line) and line[i:i+2] == '//':
                # 找到注释，返回注释前的部分
                return line[:i].rstrip()
            
            i += 1
        
        return line
    
    def _build_fixed_context(self) -> str:
        """
        构建固定记忆上下文（纯分层记忆）
        
        当使用编排器时，此方法只返回分层记忆内容，不含：
        - 时间上下文（由 time_context 组件处理）
        - 记忆范围（由 memory_range 组件处理）
        - 前后置挂载（由 prefix_mount/suffix_mount 组件处理）
        
        传统模式下仍包含所有内容以保持兼容。
        """
        # 检查是否使用编排器
        use_orchestrator = self._should_use_orchestrator()
        
        parts = []
        now = datetime.now()
        
        if not use_orchestrator:
            # 传统模式：包含前置挂载
            extra_mount_enabled = self._is_extra_mount_enabled()
            if extra_mount_enabled:
                prefix_content = self._read_extra_mount_file(self.config.extra_mount_prefix_path)
                if prefix_content:
                    parts.append(f"## 📎 前置挂载\n\n{prefix_content}")
            
            # 传统模式：包含时间上下文
            parts.append(self._build_time_context(now))
        
        # ===== 检查是否启用分层记忆 =====
        if self.config.use_layered_memory:
            # 分层记忆模式
            # 注意：按时间从旧到新排列，LLM对后面的内容注意力更强
            
            # 2. 【最旧】未被周总结覆盖的日记（超过短期天数但无对应周总结）
            unsummarized = self._build_unsummarized_diaries(now)
            if unsummarized:
                parts.append(unsummarized)
            
            # 3. 长期记忆：更早月份的季度总结
            long_term = self._build_quarterly_memory(now)
            if long_term:
                parts.append(long_term)
            
            # 4. 中期记忆：上个月的月总结
            mid_term = self._build_monthly_memory(now)
            if mid_term:
                parts.append(mid_term)
            
            # 5. 中短期记忆：本月的周总结（超过短期天数的部分）
            mid_short_term = self._build_weekly_memory(now)
            if mid_short_term:
                parts.append(mid_short_term)
            
            # 6. 短期记忆：最近N天日记
            short_term = self._build_short_term_memory(now)
            if short_term:
                parts.append(short_term)
            
            # 7. 【最新】今日待归档记录：pending 里的摘要
            # 注意：编排器模式下，pending 由 volatile_context 组件单独处理，这里不包含
            # 传统模式下才包含在 fixed_context 里
            if not use_orchestrator:
                pending_memory = self._build_pending_memory(now)
                if pending_memory:
                    parts.append(pending_memory)
        else:
            # 简单模式：只读取最近日记
            simple_diaries = self._build_simple_recent_diaries(now)
            if simple_diaries:
                parts.append(simple_diaries)
        
        # ===== 后置挂载文件（只在传统模式下处理，编排器模式由组件处理）=====
        if not use_orchestrator:
            extra_mount_enabled = self._is_extra_mount_enabled()
            if extra_mount_enabled:
                suffix_content = self._read_extra_mount_file(self.config.extra_mount_suffix_path)
                if suffix_content:
                    parts.append(f"\n## 📎 后置挂载\n\n{suffix_content}")
        
        return "\n".join(parts)
    
    def _build_simple_recent_diaries(self, now: datetime) -> str:
        """
        简单模式：只读取最近N天日记（兼容旧配置）
        """
        days = self.config.include_recent_days
        if days <= 0:
            return ""
        
        recent_diaries = self.reader.read_recent_diaries(days)
        if not recent_diaries:
            return ""
        
        parts = ["\n## 📝 最近日记"]
        for diary in recent_diaries:
            title = diary.title or diary.date
            content = diary.content[:2000]
            if len(diary.content) > 2000:
                content += "\n... (已截断)"
            parts.append(f"\n### {diary.date} - {title}")
            parts.append(content)
        
        return "\n".join(parts)
    
    def _build_time_context(self, now: datetime) -> str:
        """构建时间上下文"""
        parts = []
        weekday_names = ['周一','周二','周三','周四','周五','周六','周日']
        
        # 使用 ISO 周历：跨年时周数可能属于不同年份
        iso_year, week_num, _ = now.isocalendar()
        quarter = (now.month - 1) // 3 + 1
        
        parts.append("## 📅 当前时间上下文")
        parts.append(f"- 日期：{now.strftime('%Y年%m月%d日')} {weekday_names[now.weekday()]}")
        parts.append(f"- 时间：{now.strftime('%H:%M')}")
        # 使用 ISO 年份显示周数，避免跨年混淆
        parts.append(f"- 本周：{iso_year}年第{week_num}周（{iso_year}-W{week_num:02d}）")
        parts.append(f"- 本月：{now.year}年{now.month}月")
        parts.append(f"- 本季度：{now.year}年Q{quarter}")
        parts.append(f"- 本年：{now.year}年")
        
        last_interaction = self._get_last_interaction_time()
        if last_interaction:
            time_diff = now - last_interaction
            time_diff_str = self._format_time_diff(time_diff)
            parts.append(f"- 距上次对话：{time_diff_str}")
        
        # 添加记忆库时间范围
        memory_range = self._get_memory_date_range()
        if memory_range:
            earliest, latest, diary_count = memory_range
            parts.append("")
            parts.append("### 📚 记忆库范围")
            parts.append(f"- 最早记录：{earliest}")
            parts.append(f"- 最新记录：{latest}")
            parts.append(f"- 日记总数：{diary_count} 篇")
            
            # 计算记忆库运行天数
            try:
                earliest_date = datetime.strptime(earliest, '%Y-%m-%d')
                days_running = (now - earliest_date).days
                parts.append(f"- 运行天数：{days_running} 天")
                
                # 添加明确提示
                if days_running < 30:
                    parts.append(f"- ⚠️ **注意**：记忆系统刚上线不久，{earliest} 之前的事情没有记录！")
            except:
                pass
        
        return "\n".join(parts)
    
    def _get_memory_date_range(self) -> Optional[tuple]:
        """
        获取记忆库的日期范围
        
        Returns:
            (最早日期, 最新日期, 日记总数) 或 None
        """
        try:
            all_diaries = self.reader.list_all_diaries()
            if not all_diaries:
                return None
            
            # list_all_diaries 返回的是按日期排序的列表（最新在前）
            latest = all_diaries[0] if all_diaries else None
            earliest = all_diaries[-1] if all_diaries else None
            
            return (earliest, latest, len(all_diaries))
        except Exception as e:
            print(f"[ContextBuilder] 获取记忆日期范围失败: {e}")
            return None
    
    def _build_short_term_memory(self, now: datetime) -> str:
        """
        构建短期记忆：最近N天的日记（完整内容）
        
        注意：如果某天的日记已被周总结覆盖（且该周总结会被发送），则跳过该日记，
        避免内容重复。
        """
        if self.config.short_term_days <= 0:
            return ""
        
        recent_diaries = self.reader.read_recent_diaries(self.config.short_term_days)
        if not recent_diaries:
            return ""
        
        # 获取已存在的周总结，用于检查日记是否被覆盖
        existing_weekly = self._get_existing_weekly_summaries()
        
        # 计算短期记忆开始日期
        short_term_start = now - timedelta(days=self.config.short_term_days)
        
        # 获取当前周号（当前周的周总结不会发送）
        _, current_week, _ = now.isocalendar()
        
        parts = ["\n## 📝 短期记忆（最近日记）"]
        today = now.strftime('%Y-%m-%d')
        yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
        
        skipped_dates = []  # 记录被跳过的日期
        
        for diary in recent_diaries:
            # 检查是否被周总结覆盖
            try:
                diary_date = datetime.strptime(diary.date, '%Y-%m-%d')
                iso_year, week_num, _ = diary_date.isocalendar()
                week_id = f"{iso_year}-W{week_num:02d}"
                
                # 如果该周有周总结，且不是当前周
                if week_id in existing_weekly and week_num < current_week:
                    # 计算该周的开始日期（周一）
                    week_start = datetime.strptime(f"{iso_year}-W{week_num:02d}-1", "%G-W%V-%u")
                    
                    # 如果周的开始日期在短期记忆之前，说明周总结会被发送
                    # 该日记已被周总结覆盖，跳过
                    if week_start < short_term_start:
                        skipped_dates.append(diary.date)
                        continue
            except Exception:
                pass
            
            title = diary.title or diary.date
            max_chars = self.config.short_term_max_chars
            
            # 标注文件来源
            file_path = f"lifebook/daily/{diary.date}.md"
            
            # 如果禁用截断，直接使用完整内容
            if self.config.disable_truncation:
                parts.append(f"\n### {diary.date} - {title}")
                parts.append(f"> 📄 来源: `{file_path}`")
                parts.append(diary.content)
            # 今天/昨天显示完整，其他显示摘要
            elif diary.date in (today, yesterday):
                content = diary.content[:max_chars]
                if len(diary.content) > max_chars:
                    content += "\n... (已截断)"
                parts.append(f"\n### {diary.date} - {title}")
                parts.append(f"> 📄 来源: `{file_path}`")
                parts.append(content)
            else:
                # 3-7天前：显示较长摘要
                summary_len = min(500, max_chars // 2)
                summary = diary.content.replace("\n", " ")[:summary_len]
                parts.append(f"\n### {diary.date} - {title}")
                parts.append(f"> 📄 来源: `{file_path}`")
                parts.append(f"> {summary}...")
        
        # 如果有被跳过的日期，添加说明
        if skipped_dates:
            parts.append(f"\n> 📌 _注：{', '.join(skipped_dates)} 的日记已在周总结中覆盖，不重复发送_")
        
        return "\n".join(parts)
    
    def _build_pending_memory(self, now: datetime) -> str:
        """
        构建待归档记忆：pending 目录里所有未归档的对话摘要
        
        这些是还没被汇总成正式日记的对话摘要。
        包含所有未归档会话（不只是"今天"），因为熬夜跨日是常见场景。
        """
        try:
            from memory_store.pending_manager import PendingManager
            
            # 获取 lifebook 路径
            lifebook_path = Path(self.reader.root_path)
            pending_mgr = PendingManager(lifebook_path, self.reader.encoding)
            
            # 获取所有未归档会话
            all_sessions = pending_mgr.get_all_sessions()
            
            if not all_sessions:
                return ""
            
            parts = ["\n## 🗒️ 待归档记录"]
            parts.append("> 以下是尚未汇总成日记的对话摘要：\n")
            
            total_summaries = 0
            sessions_by_date = {}
            
            # 按日期分组
            for session in all_sessions:
                if not session.summaries:
                    continue
                    
                session_date = session.start_time.strftime('%Y-%m-%d')
                if session_date not in sessions_by_date:
                    sessions_by_date[session_date] = []
                sessions_by_date[session_date].append(session)
            
            if not sessions_by_date:
                return ""
            
            # 按日期排序（从旧到新）
            for date in sorted(sessions_by_date.keys()):
                sessions = sessions_by_date[date]
                parts.append(f"\n### 📅 {date}")
                
                for session in sessions:
                    # 标注文件来源
                    session_file = f"lifebook/pending/session_{session.session_id}.md"
                    parts.append(f"> 📄 来源: `{session_file}`")
                    
                    # 格式化会话内的摘要
                    for summary in session.summaries:
                        ts = datetime.fromisoformat(summary.timestamp)
                        time_str = ts.strftime('%H:%M')
                        
                        # 每条摘要显示时间和主题
                        parts.append(f"#### {time_str} - {summary.topic}")
                        parts.append(summary.summary)
                        parts.append("")  # 空行分隔
                        
                        total_summaries += 1
            
            if total_summaries == 0:
                return ""
            
            parts.append(f"_（共 {total_summaries} 条待归档记录，尚未汇总成正式日记）_")
            return "\n".join(parts)
            
        except ImportError:
            # pending_manager 模块不可用
            return ""
        except Exception as e:
            print(f"[ContextBuilder] 读取 pending 摘要失败: {e}")
            return ""
    
    def _get_existing_weekly_summaries(self) -> set:
        """获取所有已存在的周总结标识符"""
        try:
            weekly_identifiers = self.reader.list_summaries("weekly")
            return set(weekly_identifiers)
        except Exception:
            return set()
    
    def _get_week_identifier(self, date: datetime) -> str:
        """获取日期对应的周标识符（ISO周历）"""
        iso_year, week_num, _ = date.isocalendar()
        return f"{iso_year}-W{week_num:02d}"
    
    def _build_unsummarized_diaries(self, now: datetime) -> str:
        """
        构建未被周总结覆盖的日记
        
        逻辑：
        1. 获取超过短期天数的所有日记
        2. 检查每个日记对应的周是否有周总结
        3. 如果没有周总结，就包含这个日记
        """
        if self.config.short_term_days <= 0:
            return ""
        
        # 获取所有日记
        all_diaries = self.reader.list_all_diaries()
        if not all_diaries:
            return ""
        
        # 获取已存在的周总结
        existing_weekly = self._get_existing_weekly_summaries()
        
        # 计算短期记忆的截止日期
        short_term_cutoff = now - timedelta(days=self.config.short_term_days)
        short_term_cutoff_str = short_term_cutoff.strftime('%Y-%m-%d')
        
        # 收集未被覆盖的日记
        unsummarized_dates = []
        for date_str in all_diaries:
            # 跳过短期记忆范围内的（已经在短期记忆中发送了）
            if date_str >= short_term_cutoff_str:
                continue
            
            # 解析日期
            try:
                date = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                continue
            
            # 检查这个日期对应的周是否有周总结
            week_id = self._get_week_identifier(date)
            if week_id not in existing_weekly:
                unsummarized_dates.append(date_str)
        
        if not unsummarized_dates:
            return ""
        
        # 按日期排序（从旧到新）
        unsummarized_dates.sort()
        
        parts = ["\n## 📋 未归档日记（无对应周总结）"]
        parts.append(f"> ⚠️ 以下 {len(unsummarized_dates)} 天的日记尚未被周总结覆盖，建议尽快生成周总结\n")
        
        for date_str in unsummarized_dates:
            diary = self.reader.read_diary(date_str)
            if not diary:
                continue
            
            title = diary.title or date_str
            file_path = f"lifebook/daily/{date_str}.md"
            
            # 显示内容（使用短期记忆的截断设置）
            max_chars = self.config.short_term_max_chars
            if self.config.disable_truncation:
                content = diary.content
            else:
                content = diary.content[:max_chars]
                if len(diary.content) > max_chars:
                    content += "\n... (已截断)"
            
            parts.append(f"\n### {date_str} - {title}")
            parts.append(f"> 📄 来源: `{file_path}`")
            parts.append(content)
        
        return "\n".join(parts)
    
    def _build_weekly_memory(self, now: datetime) -> str:
        """
        构建中短期记忆：本月内超过短期天数的周总结
        
        例如：今天是5月25日，短期7天，那么5月18日之前的周总结都要包含
        
        注意：ISO 周历跨年处理
        - 使用 isocalendar() 返回的年份，不要用 now.year
        - 例如：2024年12月31日的 isocalendar() 可能返回 (2025, 1, 2)
        """
        if not self.config.include_weekly_summaries:
            return ""
        
        parts = []
        # 使用 ISO 周历年份，不是日历年份！
        iso_year, current_week, _ = now.isocalendar()
        current_month = now.month
        
        # 计算短期记忆覆盖的最早日期
        short_term_start = now - timedelta(days=self.config.short_term_days)
        short_term_iso_year, short_term_week, _ = short_term_start.isocalendar()
        
        # 获取本月第一天
        month_start = now.replace(day=1)
        month_start_iso_year, month_start_week, _ = month_start.isocalendar()
        
        # 收集需要显示的周总结
        weeks_to_show = []
        
        # 处理跨年情况：如果本月第一天和当前日期在不同ISO年
        if month_start_iso_year != iso_year:
            # 跨年情况：先处理上一年的周（如果有）
            # 例如：1月1日在2024年第52周，但1月6日已经在2025年第2周
            for week_num in range(month_start_week, 53):  # 52或53周
                if (month_start_iso_year, week_num) >= (short_term_iso_year, short_term_week):
                    continue
                identifier = f"{month_start_iso_year}-W{week_num:02d}"
                weekly = self.reader.read_summary("weekly", identifier)
                if weekly:
                    weeks_to_show.append((identifier, weekly))
            
            # 再处理当前年的周
            for week_num in range(1, current_week + 1):
                if (iso_year, week_num) >= (short_term_iso_year, short_term_week):
                    continue
                identifier = f"{iso_year}-W{week_num:02d}"
                weekly = self.reader.read_summary("weekly", identifier)
                if weekly:
                    weeks_to_show.append((identifier, weekly))
        else:
            # 同年情况：正常处理
            for week_offset in range(current_week - month_start_week + 1):
                week_num = month_start_week + week_offset
                
                # 跳过当前周（还在进行中，没有周总结）
                if week_num >= current_week:
                    continue
                
                # 计算这个周的开始日期（周一）
                try:
                    week_start_date = datetime.strptime(f"{iso_year}-W{week_num:02d}-1", "%G-W%V-%u")
                except ValueError:
                    continue
                
                # 只有当周的开始日期在短期记忆范围内时才跳过
                # （即整个周都被短期记忆覆盖）
                if week_start_date >= short_term_start:
                    continue
                
                identifier = f"{iso_year}-W{week_num:02d}"
                weekly = self.reader.read_summary("weekly", identifier)
                if weekly:
                    weeks_to_show.append((identifier, weekly))
        
        if not weeks_to_show:
            return ""
        
        parts.append(f"\n## 📅 中短期记忆（本月周总结）")
        for identifier, weekly in weeks_to_show:
            file_path = f"lifebook/weekly/{identifier}.md"
            # 如果禁用截断，使用完整内容
            if self.config.disable_truncation:
                content = weekly.content
            else:
                content = weekly.content[:self.config.weekly_max_chars]
                if len(weekly.content) > self.config.weekly_max_chars:
                    content += "\n... (已截断)"
            parts.append(f"\n### {identifier}")
            parts.append(f"> 📄 来源: `{file_path}`")
            parts.append(content)
        
        return "\n".join(parts)
    
    def _build_monthly_memory(self, now: datetime) -> str:
        """构建中期记忆：上个月的月总结"""
        if not self.config.include_monthly_summaries:
            return ""
        
        # 计算上个月
        if now.month == 1:
            last_month_year = now.year - 1
            last_month = 12
        else:
            last_month_year = now.year
            last_month = now.month - 1
        
        identifier = f"{last_month_year}-{last_month:02d}"
        monthly = self.reader.read_summary("monthly", identifier)
        
        if not monthly:
            return ""
        
        file_path = f"lifebook/monthly/{identifier}.md"
        # 如果禁用截断，使用完整内容
        if self.config.disable_truncation:
            content = monthly.content
        else:
            content = monthly.content[:self.config.monthly_max_chars]
            if len(monthly.content) > self.config.monthly_max_chars:
                content += "\n... (已截断)"
        
        return f"\n## 📆 中期记忆（上月总结）\n\n### {identifier}\n> 📄 来源: `{file_path}`\n{content}"
    
    def _build_quarterly_memory(self, now: datetime) -> str:
        """
        构建长期记忆：根据回溯月份数加载季度总结
        
        逻辑：计算回溯范围内涉及的季度，排除当前季度和上月所在季度
        """
        if not self.config.include_quarterly_summaries:
            return ""
        
        lookback_months = self.config.lookback_months
        if lookback_months <= 2:
            return ""  # 回溯太短，不需要季度总结
        
        current_quarter = (now.month - 1) // 3 + 1
        current_year = now.year
        
        # 计算回溯起始月
        lookback_start = now - timedelta(days=30 * lookback_months)
        start_quarter = (lookback_start.month - 1) // 3 + 1
        start_year = lookback_start.year
        
        # 计算上个月所在季度（不重复显示）
        if now.month == 1:
            last_month_quarter = 4
            last_month_year = now.year - 1
        else:
            last_month_quarter = ((now.month - 2) // 3) + 1
            last_month_year = now.year
        
        # 收集需要显示的季度
        quarters_to_show = []
        
        # 遍历从回溯起始到上月之间的所有季度
        year = start_year
        quarter = start_quarter
        
        while (year, quarter) < (last_month_year, last_month_quarter):
            # 排除当前季度
            if (year, quarter) != (current_year, current_quarter):
                identifier = f"{year}-Q{quarter}"
                quarterly = self.reader.read_summary("quarterly", identifier)
                if quarterly:
                    quarters_to_show.append((identifier, quarterly))
            
            # 下一个季度
            quarter += 1
            if quarter > 4:
                quarter = 1
                year += 1
        
        if not quarters_to_show:
            return ""
        
        parts = ["\n## 🗂️ 长期记忆（季度总结）"]
        for identifier, quarterly in quarters_to_show:
            file_path = f"lifebook/quarterly/{identifier}.md"
            # 如果禁用截断，使用完整内容
            if self.config.disable_truncation:
                content = quarterly.content
            else:
                content = quarterly.content[:self.config.quarterly_max_chars]
                if len(quarterly.content) > self.config.quarterly_max_chars:
                    content += "\n... (已截断)"
            parts.append(f"\n### {identifier}")
            parts.append(f"> 📄 来源: `{file_path}`")
            parts.append(content)
        
        return "\n".join(parts)
    
    def _get_last_interaction_time(self) -> Optional[datetime]:
        """获取上次对话时间"""
        # 优先使用元数据管理器
        if self.metadata:
            last = self.metadata.get_last_interaction()
            if last:
                return last
        
        # 降级：从最近日记推断
        try:
            recent = self.reader.read_recent_diaries(1)
            if recent:
                last_diary = recent[0]
                # 尝试解析日期
                diary_date = datetime.strptime(last_diary.date, '%Y-%m-%d')
                return diary_date.replace(hour=23, minute=59)
        except Exception:
            pass
        return None
    
    def _format_time_diff(self, delta: timedelta) -> str:
        """格式化时间差为人类可读形式"""
        total_seconds = int(delta.total_seconds())
        
        if total_seconds < 60:
            return "刚刚"
        
        minutes = total_seconds // 60
        if minutes < 60:
            return f"{minutes}分钟"
        
        hours = minutes // 60
        if hours < 24:
            return f"{hours}小时{minutes % 60}分钟" if minutes % 60 else f"{hours}小时"
        
        days = hours // 24
        if days < 7:
            return f"{days}天{hours % 24}小时" if hours % 24 else f"{days}天"
        
        weeks = days // 7
        if weeks < 4:
            return f"{weeks}周{days % 7}天" if days % 7 else f"{weeks}周"
        
        months = days // 30
        if months < 12:
            return f"约{months}个月"
        
        years = months // 12
        return f"约{years}年{months % 12}个月" if months % 12 else f"约{years}年"
    
    def _inject_memory(
        self,
        messages: List[Dict[str, Any]],
        memory_content: str,
        override_position_str: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """将记忆注入消息列表"""
        if not memory_content:
            return [m.copy() for m in messages]
        
        messages = [m.copy() for m in messages]
        
        # 确定插入位置
        if override_position_str:
            try:
                position = InsertionPosition(override_position_str)
                print(f"[上下文注入] 使用覆盖插入位置: {position.value}")
            except ValueError:
                position = self.config.insertion_position
        else:
            position = self.config.insertion_position
        
        if position == InsertionPosition.SYSTEM_PREPEND:
            return self._inject_system_prepend(messages, memory_content)
        
        elif position == InsertionPosition.SYSTEM_APPEND:
            return self._inject_system_append(messages, memory_content)
        
        elif position == InsertionPosition.AFTER_SYSTEM:
            return self._inject_after_system(messages, memory_content)
        
        elif position == InsertionPosition.BEFORE_LAST_USER:
            return self._inject_before_last_user(messages, memory_content)
        
        elif position == InsertionPosition.REPLACE_SYSTEM:
            return self._inject_replace_system(messages, memory_content)
        
        return messages
    
    def _inject_system_prepend(
        self,
        messages: List[Dict[str, Any]],
        memory_content: str
    ) -> List[Dict[str, Any]]:
        """在系统提示词最前面插入"""
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = memory_content + "\n\n" + messages[0]["content"]
        else:
            messages.insert(0, {"role": "system", "content": memory_content})
        return messages
    
    def _inject_system_append(
        self,
        messages: List[Dict[str, Any]],
        memory_content: str
    ) -> List[Dict[str, Any]]:
        """在系统提示词末尾插入"""
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = messages[0]["content"] + memory_content
        else:
            messages.insert(0, {"role": "system", "content": memory_content})
        return messages
    
    def _inject_after_system(
        self,
        messages: List[Dict[str, Any]],
        memory_content: str
    ) -> List[Dict[str, Any]]:
        """在系统消息后独立插入"""
        insert_idx = 1 if messages and messages[0].get("role") == "system" else 0
        
        # 插入记忆消息
        messages.insert(insert_idx, {
            "role": "user",
            "content": f"[系统注入的相关记忆]\n{memory_content}"
        })
        
        # 可选：添加确认
        if self.config.enable_confirmation:
            messages.insert(insert_idx + 1, {
                "role": "assistant",
                "content": self.config.assistant_ack
            })
        
        return messages
    
    def _inject_before_last_user(
        self,
        messages: List[Dict[str, Any]],
        memory_content: str
    ) -> List[Dict[str, Any]]:
        """在最后一条用户消息前插入"""
        # 找到最后一条用户消息
        last_user_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_idx = i
                break
        
        if last_user_idx == -1:
            # 没有用户消息，降级为 system_append
            return self._inject_system_append(messages, memory_content)
        
        # 在最后用户消息前插入
        messages.insert(last_user_idx, {
            "role": "user",
            "content": f"[相关记忆]\n{memory_content}"
        })
        
        if self.config.enable_confirmation:
            messages.insert(last_user_idx + 1, {
                "role": "assistant",
                "content": self.config.assistant_ack
            })
        
        return messages
    
    def _inject_replace_system(
        self,
        messages: List[Dict[str, Any]],
        memory_content: str
    ) -> List[Dict[str, Any]]:
        """完全替换系统提示"""
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = memory_content
        else:
            messages.insert(0, {"role": "system", "content": memory_content})
        return messages
    
    def _truncate_memory(self, content: str, max_chars: int) -> str:
        """裁剪记忆内容"""
        if len(content) <= max_chars:
            return content
        
        # 保留前面的内容，末尾添加提示
        truncated = content[:max_chars - 50]
        return truncated + "\n\n...(记忆内容已截断)"
    
    def build_for_main_model(
        self,
        messages: List[Dict[str, Any]],
        agent_result: Any,  # AgentResult
        include_fixed: bool = True
    ) -> BuiltContext:
        """
        为主模型构建上下文
        
        Args:
            messages: 原始消息
            agent_result: Agent检索结果
            include_fixed: 是否包含固定上下文
            
        Returns:
            BuiltContext
        """
        # 从Agent结果提取动态记忆
        dynamic_memory = ""
        if agent_result and agent_result.success:
            dynamic_memory = agent_result.content
        
        return self.build(messages, dynamic_memory, include_fixed)
    
    def get_memory_tools_prompt(
        self,
        enable_write: bool = False,
        custom_hint: str = "",
        include_graphiti: bool = False,
        use_xml_tools: bool = False
    ) -> str:
        """
        获取给大模型的记忆工具说明
        
        Args:
            enable_write: 是否包含写入工具说明
            custom_hint: 自定义提示（来自配置）
            include_graphiti: 是否包含 Graphiti 工具说明
            use_xml_tools: 是否使用 XML 工具调用格式
            
        Returns:
            工具提示文本
        """
        # 如果有自定义提示，使用自定义的
        if custom_hint:
            prompt = f"\n## 📚 记忆说明\n\n{custom_hint}"
        else:
            prompt = """
## 📚 记忆说明

### 已提供的信息（无需调用工具获取）：
1. **短期记忆**：上方已包含当前时间、最近日记完整内容（今天/昨天）、本周/本月总结
2. **长期记忆**：如果上方"相关记忆"部分有Agent检索的内容，那就是全部相关记忆

### ⚠️ 关键规则：
- 如果上方**没有**"Agent检索结果"或显示"暂无相关记忆"，说明**长期记忆库中没有与当前问题相关的内容**
- 这种情况下**不要**再调用工具尝试搜索 —— 因为已经搜过了
- **短期记忆（最近日记）已经附带**，不需要再重复获取"""
        
        if use_xml_tools:
            prompt += """

## 🔧 可用工具

当你需要调用工具时，使用以下格式（必须使用 <<<tool_call>>> 标记）：

### 📊 概览工具（推荐优先使用）
```
<<<tool_call>>>
name: get_memory_overview
arguments: {}
<<</tool_call>>>
```
> 一次获取记忆系统全貌：所有节点、日记统计、标签、人物。做任何管理操作前建议先调用。

```
<<<tool_call>>>
name: list_nodes
arguments: {"type": "all"}
<<</tool_call>>>
```
> 列出所有节点，可按类型过滤（人物/地点/事物/概念/all）

### 🔍 查询工具
```
<<<tool_call>>>
name: search_memories
arguments: {"query": "搜索关键词"}
<<</tool_call>>>
```

```
<<<tool_call>>>
name: read_diary
arguments: {"date": "2025-12-25"}
<<</tool_call>>>
```

```
<<<tool_call>>>
name: get_node
arguments: {"name": "某人"}
<<</tool_call>>>
```

```
<<<tool_call>>>
name: list_all_people
arguments: {}
<<</tool_call>>>
```

```
<<<tool_call>>>
name: list_all_tags
arguments: {}
<<</tool_call>>>
```"""
            
            if enable_write:
                prompt += """

### ✏️ 写入工具
```
<<<tool_call>>>
name: add_to_diary
arguments: {"content": "要添加的内容", "date": "2025-12-29"}
<<</tool_call>>>
```

```
<<<tool_call>>>
name: create_node
arguments: {"name": "小明", "type": "人物", "content": "节点内容"}
<<</tool_call>>>
```
⚠️ 注意：`name` 只填节点名称（如"小明"），不要带类型前缀

```
<<<tool_call>>>
name: update_node
arguments: {"name": "小明", "content": "要追加的内容"}
<<</tool_call>>>
```

### 🗑️ 删除工具
```
<<<tool_call>>>
name: delete_node
arguments: {"name": "测试节点", "confirm": true}
<<</tool_call>>>
```
⚠️ 必须设置 `confirm: true` 才会执行删除

### 🕸️ 知识图谱工具（参考 MCP memory 设计）
```
<<<tool_call>>>
name: read_graph
arguments: {}
<<</tool_call>>>
```
> 读取整个知识图谱（所有节点及其关系）

```
<<<tool_call>>>
name: add_observations
arguments: {"observations": [{"name": "某人", "contents": ["喜欢咖啡", "每周健身三次"]}]}
<<</tool_call>>>
```
> 向节点添加观察（离散事实）

```
<<<tool_call>>>
name: create_relations
arguments: {"relations": [{"from": "小明", "to": "小红", "relation_type": "朋友"}]}
<<</tool_call>>>
```
> 创建节点之间的关系"""
            
            prompt += """

### ⚠️ 调用规则：
1. 工具调用必须在正文之外单独输出，不要混在回复内容里
2. 可以一次调用多个工具（多个 `<<<tool_call>>>` 块）
3. 工具结果会在下一轮显示，然后你再根据结果回复
4. 不需要重复获取已提供的信息（时间、最近日记等）
5. **管理任务建议**：先用 `get_memory_overview` 了解全貌，再做具体操作"""
            
            if include_graphiti:
                prompt += """

### 🔗 Graphiti 时序图谱工具

```
<<<tool_call>>>
name: graphiti_search
arguments: {"query": "主人开发的项目"}
<<</tool_call>>>
```
> 混合搜索：语义 + 关键词 + 图遍历，适合复杂问题

```
<<<tool_call>>>
name: graphiti_temporal
arguments: {"entity": "LifeBook项目", "time_point": "2025-03"}
<<</tool_call>>>
```
> 时间点查询：该实体在指定时间的状态

```
<<<tool_call>>>
name: graphiti_multi_hop
arguments: {"start_entity": "主人", "max_hops": 2}
<<</tool_call>>>
```
> 多跳查询：沿关系边遍历

```
<<<tool_call>>>
name: graphiti_get_stats
arguments: {}
<<</tool_call>>>
```
> 获取 Graphiti 统计信息

⚠️ **Graphiti 工具与传统工具选择**：
- 精确关键词 → search_memories
- 语义/多跳 → graphiti_search
- 历史状态 → graphiti_temporal"""
            
            return prompt
        
        # 原生工具调用模式下不再注入工具说明文本，交由 tool schema 表达
        return prompt
        
        if enable_write:
            prompt += """

### ✏️ 可写工具
- 日记：`add_to_diary`
- 节点：`create_node`、`update_node`、`delete_node`
- 图谱：`add_observations`、`create_relations`

### 写入注意
- `create_node.name` 只填节点名称，不要带类型前缀
- `delete_node` 必须带 `confirm: true` 才会执行"""
        
        if include_graphiti:
            prompt += """

### 🔗 Graphiti 时序图谱工具
- `graphiti_search`：语义 + 关键词 + 图遍历
- `graphiti_temporal`：查询指定时间点状态
- `graphiti_multi_hop`：沿关系边多跳遍历
- `graphiti_get_stats`：获取统计信息

### Graphiti 选择建议
- 精确关键词 → `search_memories`
- 语义/多跳 → `graphiti_search`
- 历史状态 → `graphiti_temporal`"""
        
        return prompt


# 便捷函数
def create_context_builder(
    lifebook_path: str,
    config: Optional[ContextConfig] = None
) -> ContextBuilder:
    """创建上下文组装器"""
    reader = LifeBookReader(lifebook_path)
    return ContextBuilder(reader, config)


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("Context Builder 测试")
    print("=" * 60)
    
    # 模拟测试（不需要实际文件）
    config = ContextConfig(
        insertion_position=InsertionPosition.SYSTEM_APPEND,
        include_recent_days=0,  # 测试时不读取文件
        include_current_weekly=False,
        include_current_monthly=False
    )
    
    # 测试各种插入位置
    test_messages = [
        {"role": "system", "content": "你是一个助手。"},
        {"role": "user", "content": "之前的问题"},
        {"role": "assistant", "content": "之前的回答"},
        {"role": "user", "content": "现在的问题"}
    ]
    
    test_memory = "这是检索到的记忆内容。\n\n- 2025-12-29: 和小明喝咖啡\n- 2025-12-28: 学习编程"
    
    print("\n原始消息:")
    for i, m in enumerate(test_messages):
        print(f"  [{i}] {m['role']}: {m['content'][:30]}...")
    
    # 测试不同插入位置
    for position in InsertionPosition:
        config.insertion_position = position
        
        # 创建一个模拟的 reader
        class MockReader:
            def read_recent_diaries(self, days): return []
            def read_current_weekly(self): return None
            def read_current_monthly(self): return None
        
        builder = ContextBuilder(MockReader(), config)
        result = builder.build(test_messages, test_memory, include_fixed=False)
        
        print(f"\n📍 {position.value}:")
        for i, m in enumerate(result.messages):
            content = m['content'][:50].replace('\n', ' ')
            print(f"  [{i}] {m['role']}: {content}...")
    
    print("\n测试完成!")
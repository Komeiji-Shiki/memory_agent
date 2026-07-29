"""
Memory Agent 提示词模板

从 context_builder.py 外置的提示词常量，便于统一维护和调整。
注意：这些文本直接影响模型行为，修改时需实测验证。
"""

# 默认记忆说明（无自定义提示时使用）
MEMORY_TOOLS_PROMPT_BASE = """
## 📚 记忆说明

### 已提供的信息（无需调用工具获取）：
1. **短期记忆**：上方已包含当前时间、最近日记完整内容（今天/昨天）、本周/本月总结
2. **长期记忆**：如果上方"相关记忆"部分有Agent检索的内容，那就是全部相关记忆

### ⚠️ 关键规则：
- 如果上方**没有**"Agent检索结果"或显示"暂无相关记忆"，说明**长期记忆库中没有与当前问题相关的内容**
- 这种情况下**不要**再调用工具尝试搜索 —— 因为已经搜过了
- **短期记忆（最近日记）已经附带**，不需要再重复获取"""


# XML 工具调用格式：只读工具说明
XML_TOOLS_PROMPT_READ = """

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


# XML 工具调用格式：写入工具说明（enable_write 时追加）
XML_TOOLS_PROMPT_WRITE = """

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


# XML 工具调用格式：调用规则
XML_TOOLS_PROMPT_RULES = """

### ⚠️ 调用规则：
1. 工具调用必须在正文之外单独输出，不要混在回复内容里
2. 可以一次调用多个工具（多个 `<<<tool_call>>>` 块）
3. 工具结果会在下一轮显示，然后你再根据结果回复
4. 不需要重复获取已提供的信息（时间、最近日记等）
5. **管理任务建议**：先用 `get_memory_overview` 了解全貌，再做具体操作"""


# XML 工具调用格式：Graphiti 工具说明（include_graphiti 时追加）
XML_TOOLS_PROMPT_GRAPHITI = """

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

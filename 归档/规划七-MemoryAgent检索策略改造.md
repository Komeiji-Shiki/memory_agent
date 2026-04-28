# 🔄 Memory Agent 检索策略分析

## ✅ 现有 Agent 已经很强了

### 当前实现的优势

经过重新审视，当前的 `memory_agent/agent.py` 实现已经足够好：

```python
# 当前循环逻辑 - 依赖 deepseek-reasoner 的强大推理能力
while iteration < self.config.max_iterations:  # 实际配置是 30 次
    response = self.client.chat.completions.create(...)
    
    if finish_reason == "stop" or not message.tool_calls:
        return result  # 模型自己判断何时停止
    
    # 工具调用结果会保留在消息上下文中
    # 模型可以看到之前找到了什么
    for tc in message.tool_calls:
        result = self.memory_tools.call_tool(...)
        messages.append({"role": "tool", ...})  # ← 上下文中
    
    iteration += 1
```

### ✅ 为什么不需要 MemR3 式改造

| 担心的问题 | 实际情况 | 原因 |
|-----------|---------|------|
| "无反思机制" | **不需要** | deepseek-reasoner 有思维链，自己会反思 |
| "不知道已找到什么" | **模型知道** | tool call 结果在消息上下文中 |
| "固定迭代次数" | **配置是30次** | 且模型会自己判断提前停止 |
| "不会调整关键词" | **模型会调整** | 这是 GPT5/Claude4 级别的模型 |
| "依赖LLM判断" | **这是优势** | 强模型的判断比硬编码规则更灵活 |

### 🎯 deepseek-reasoner 的能力

**场景1：多部分问题**
```
用户：去年我做LifeBook时遇到了什么问题？后来怎么解决的？

deepseek-reasoner 实际行为（思维链）：
├── [思考] 用户问了两个问题：1.问题 2.解决方案
├── 搜索 "LifeBook 问题"
├── 找到：工具调用兼容性问题
├── [思考] 还需要找解决方案
├── 搜索 "LifeBook 工具调用 解决方案"
├── 找到：添加了XML解析器
└── 输出完整结果
```

**场景2：关键词调整**
```
用户：主人最近在学什么？

deepseek-reasoner 实际行为：
├── [思考] "学习"可能有多种表述
├── 搜索 "主人 学习"  → 没结果
├── [思考] 换个词试试
├── 搜索 "主人 研究" → 找到！
└── 输出结果
```

**关键点**：这是 **GPT5/Claude4 级别的模型**，不需要硬编码反思逻辑

---

---

## 🎯 真正需要改进的是底层存储

Agent 检索逻辑不需要大改，**需要改进的是底层**：

### 当前瓶颈

```
┌─────────────────────────────────────────────────────────┐
│                    Memory Agent                          │
│           (deepseek-reasoner 已经很强)                   │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│                  存储层 ← 这里需要改进                   │
│                                                         │
│   ❌ 关系查询：遍历所有 Markdown 文件 O(n)              │
│   ❌ 时序查询：完全不支持                               │
│   ❌ 多跳查询：不支持                                   │
│   ✅ 关键词搜索：SQLite 倒排索引（OK）                  │
│   ✅ 语义搜索：RAG 向量（OK）                           │
└─────────────────────────────────────────────────────────┘
```

### 真正的改进方向

| 层级 | 当前 | 改进方向 | 优先级 |
|------|------|----------|--------|
| Agent 逻辑 | deepseek-reasoner | **不改** | - |
| 图存储 | 遍历 Markdown | **Graphiti/Neo4j** | ⭐⭐⭐ |
| 时序查询 | 无 | **Bi-Temporal 模型** | ⭐⭐⭐ |
| 混合检索 | 分离的索引 | **Graphiti 一体化** | ⭐⭐ |

---

## 📝 可选的小改进

虽然 Agent 逻辑不需要大改，但有一些**可选的小优化**：

### 1. 给模型更多的图查询工具

当前模型只能用 `search_memories` / `rag_search` 这种"搜"的方式。

如果有 Graphiti，可以新增：
- `graph_query` - 关系查询（"谁创建了LifeBook"）
- `find_path` - 多跳路径（"灰魂和DeepSeek之间有什么联系"）
- `temporal_snapshot` - 时间点查询（"2025年3月时项目是什么状态"）

**这不是改 Agent 逻辑，而是给 Agent 更多工具**

### 2. 可选的 Evidence-Gap Tracker（用于可视化）

不是给模型用，而是给**用户看**：
- 在 Web 管理面板显示 Agent 找到了什么
- 调试时方便追踪检索过程

```python
# 只用于可视化，不影响 Agent 决策
class EvidenceTracker:
    """仅用于追踪和可视化"""
    
    def log_evidence(self, source: str, content: str):
        """记录发现的证据"""
        pass
    
    def get_visualization_data(self) -> dict:
        """返回可视化数据"""
        return {
            "found": self.found_items,
            "queries": self.query_history,
            "timeline": self.timeline
        }
```

---

## 🎯 结论

| 组件 | 需要改吗？ | 原因 |
|------|-----------|------|
| **Agent 检索逻辑** | ❌ 不需要 | deepseek-reasoner 已经够聪明 |
| **存储层** | ✅ 需要 | 图查询/时序查询能力缺失 |
| **工具集** | ✅ 可扩展 | 加图查询工具给 Agent 用 |
| **可视化** | ✅ 可选 | 方便调试和用户理解 |

### 优先级

1. **⭐⭐⭐ Graphiti 存储层整合** - 给 Agent 更强的底层能力
2. **⭐⭐ 图查询工具** - 新增工具扩展 Agent 能力
3. **⭐ 检索可视化** - 可选的 UI 改进

---

## 🔧 兼容性方案

### 方案A：完全替换（推荐）

```python
# memory_router.py 修改

# 原来
from memory_agent.agent import MemoryAgent, AgentConfig
agent = MemoryAgent(tools, config)
result = agent.retrieve(query, context)

# 改为
from memory_agent.memr3_agent import MemR3Agent, MemR3Config
agent = MemR3Agent(tools, config)
result = agent.retrieve(query, context)
```

### 方案B：配置切换

```jsonc
// config.jsonc
{
    "memory_agent": {
        "strategy": "memr3",  // "simple" | "memr3"
        "memr3": {
            "max_retrieves": 4,
            "max_reflects": 2
        }
    }
}
```

```python
# memory_agent/__init__.py
def get_agent(tools, config):
    if config.get("strategy") == "memr3":
        return MemR3Agent(tools, config["memr3"])
    else:
        return MemoryAgent(tools, config)  # 兼容旧版
```

---

## 📅 实施步骤

| 步骤 | 任务 | 天数 |
|------|------|------|
| 1 | 创建 `evidence_tracker.py` | 0.5 |
| 2 | 创建 `router.py` | 0.5 |
| 3 | 创建 `memr3_agent.py` | 1-2 |
| 4 | 修改 `memory_router.py` 使用新 Agent | 0.5 |
| 5 | 测试 + 调优 | 1-2 |
| **总计** | | **4-5天** |

---

## 🧪 测试用例

```python
# tests/test_memr3_agent.py

def test_multi_part_question():
    """测试多部分问题"""
    agent = MemR3Agent(tools, config)
    
    # 这种问题需要多次检索
    result = agent.retrieve(
        "去年做LifeBook时遇到的问题和解决方案"
    )
    
    # 应该至少有2条证据（问题+方案）
    assert len(result.tracker.known) >= 2
    # 应该经历 Retrieve → Reflect → Retrieve 流程
    assert "reflect" in result.states_visited

def test_early_stop():
    """测试早停机制"""
    agent = MemR3Agent(tools, config)
    
    # 简单问题应该快速结束
    result = agent.retrieve("灰魂是谁")
    
    # 一次检索就够
    assert result.iterations <= 2
    assert result.success

def test_gap_tracking():
    """测试缺口追踪"""
    tracker = EvidenceGapTracker(original_query="xxx")
    tracker.add_gap("问题是什么")
    tracker.add_gap("解决方案")
    
    # 添加包含"问题"的证据
    tracker.add_evidence(Evidence(
        content="工具调用兼容性问题",
        source="diary:2025-03-15",
        relevance=0.9
    ))
    
    # "问题"缺口应该被填补
    assert "问题是什么" not in tracker.missing
    assert "解决方案" in tracker.missing  # 还缺这个
```

---

*文档创建时间：2026-01-22*
*作者：灰魂* 😸
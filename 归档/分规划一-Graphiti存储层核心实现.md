# 🔧 分规划一：Graphiti 存储层核心实现

## 📋 概述

本分规划对应总规划的 **Phase 1.1-1.2**，是整个 Graphiti 时序知识图谱改造的基础。

**目标**：实现 Graphiti 适配器核心功能，使系统能够：
1. 初始化 Kuzu 嵌入式图数据库
2. 添加 Episode（对话/日记/节点）
3. 执行混合搜索（语义 + BM25）
4. 支持时间点查询（Bi-Temporal）

**预计工期**：3-4 天

---

## ✅ 任务清单

### 1. 环境准备 (0.5天)

- [ ] **1.1 安装依赖**
  ```bash
  pip install graphiti-core>=0.17.0
  pip install kuzu>=0.11.2
  ```
  
- [ ] **1.2 更新 requirements.txt**
  ```txt
  # Graphiti 时序知识图谱
  graphiti-core>=0.17.0
  kuzu>=0.11.2
  ```

- [ ] **1.3 验证安装**
  ```python
  # 快速验证脚本
  from graphiti_core import Graphiti
  from graphiti_core.driver.kuzu_driver import KuzuDriver
  print("Graphiti 安装成功！")
  ```

### 2. 配置文件扩展 (0.5天)

- [ ] **2.1 扩展 config.jsonc**
  
  在现有配置文件中添加 `graphiti` 配置块：
  
  ```jsonc
  {
      "graphiti": {
          "enabled": true,
          "backend": "kuzu",
          
          "kuzu": {
              "db_path": "./lifebook/.graphiti.kuzu"
          },
          
          "llm": {
              "base_url": null,
              "api_key": "${OPENAI_API_KEY}",
              "model": "gpt-4o-mini",
              "small_model": "gpt-4o-mini",
              "embedding_model": "text-embedding-3-small",
              "embedding_dim": 1536
          },
          
          "reranker": {
              "enabled": false,
              "model": "gpt-4o-mini"
          },
          
          "search": {
              "sim_min_score": 0.4,
              "mmr_lambda": 0.5,
              "reranker_min_score": 0.3
          },
          
          "group_id": {
              "strategy": "single",
              "default": "lifebook"
          },
          
          "retrieval": {
              "strategy": "simple",
              "default_limit": 10,
              "include_edges": true,
              "include_nodes": true
          },
          
          "sync": {
              "index_conversations": true
          }
      }
  }
  ```

- [ ] **2.2 更新 config.jsonc.example**

### 3. GraphitiAdapter 核心实现 (2天)

- [ ] **3.1 创建目录结构**
  ```
  memory_store/
  └── graphiti_adapter.py  # 新增
  ```

- [ ] **3.2 实现 EpisodeType 枚举**
  ```python
  class EpisodeType(Enum):
      DIARY = "diary"        # 日记：高信息密度
      NODE = "node"          # 节点：结构化实体
      CONVERSATION = "conv"  # 对话：需要价值过滤
  ```

- [ ] **3.3 实现 GroupIdStrategy 类**
  - 支持 single/user/project 三种策略
  - 用于多用户/多项目隔离

- [ ] **3.4 实现 GraphitiAdapter 异步类**
  
  核心方法：
  | 方法 | 功能 | 优先级 |
  |------|------|--------|
  | `initialize()` | 初始化 Kuzu + LLM + Embedder | 🔴 高 |
  | `add_episode()` | 添加 Episode 到图谱 | 🔴 高 |
  | `search()` | 混合搜索 | 🔴 高 |
  | `temporal_query()` | 时间点查询 | 🟡 中 |
  | `sync_from_markdown()` | 从 MD 同步 | 🟡 中 |
  | `close()` | 关闭连接 | 🟢 低 |

- [ ] **3.5 实现 GraphitiSyncAdapter 同步包装器**
  - 为非异步上下文提供同步调用接口

- [ ] **3.6 实现内容价值评估**
  ```python
  def _estimate_content_value(self, content: str) -> float:
      """估算内容价值（0-1），用于过滤低价值对话"""
  ```

### 4. 基础测试 (0.5天)

- [ ] **4.1 创建测试脚本**
  ```
  tests/
  └── test_graphiti_adapter.py  # 新增
  ```

- [ ] **4.2 测试用例**
  
  | 测试 | 预期结果 |
  |------|---------|
  | 初始化 Kuzu | `.graphiti.kuzu/` 目录创建 |
  | 添加 3 条日记 | 无错误 |
  | 搜索 "主人" | 返回相关结果 |
  | 时间点查询 | 返回历史状态 |

- [ ] **4.3 验证 Structured Output 兼容性**
  - 测试主人的 API 聚合服务是否支持 `response_format`

---

## 📁 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `requirements.txt` | 修改 | 添加 graphiti-core, kuzu |
| `config.jsonc` | 修改 | 添加 graphiti 配置块 |
| `config.jsonc.example` | 修改 | 同步示例配置 |
| `memory_store/graphiti_adapter.py` | 新增 | 核心适配器 |
| `tests/test_graphiti_adapter.py` | 新增 | 测试脚本 |

---

## 🎯 验收标准

### MVP 验收（Day 2）

```python
# 能够运行以下代码无错误
from memory_store.graphiti_adapter import GraphitiAdapter, EpisodeType

adapter = GraphitiAdapter(config["graphiti"], "./lifebook")
await adapter.initialize()

# 添加一条日记
await adapter.add_episode(
    content="今天学习了 Graphiti 框架",
    source="diary:2026-01-22",
    episode_type=EpisodeType.DIARY
)

# 搜索
results = await adapter.search("Graphiti")
print(results)  # 应返回刚添加的日记

await adapter.close()
```

### 完整验收（Day 4）

| 功能 | 验收标准 |
|------|---------|
| Kuzu 初始化 | 数据库文件正确创建 |
| Episode 添加 | 日记/节点/对话均可添加 |
| 混合搜索 | 返回相关结果，分数合理 |
| 时间点查询 | 能查询历史状态 |
| 配置热加载 | 修改配置后无需重启 |

---

## ⚠️ 风险与应对

### 风险1：Structured Output 不兼容

**现象**：实体抽取时 LLM 返回非 JSON 格式

**应对**：
```python
# 在 GraphitiAdapter 中添加降级逻辑
try:
    result = await self.llm.generate_structured(prompt, schema)
except StructuredOutputNotSupported:
    # 降级为普通生成 + JSON 修复
    raw = await self.llm.generate(prompt + "\n请用JSON格式输出")
    result = self._parse_json_with_repair(raw, schema)
```

### 风险2：Kuzu 驱动问题

**现象**：Kuzu 相关错误

**应对**：
- 保留 Neo4j 配置作为备选
- 错误日志详细记录
- 快速切换机制

### 风险3：中文实体抽取效果差

**现象**：人名/项目名被错误拆分

**应对**：
```python
# 添加中文处理规则到 prompt
CHINESE_ENTITY_RULES = """
【中文处理规则】
1. 人名保持完整："张三"、"主人"是一个实体
2. 项目名保持完整："LifeBook记忆系统"是一个实体
"""
```

---

## 📅 时间安排

| 日期 | 任务 | 产出 |
|------|------|------|
| Day 1 上午 | 1.1-1.3 环境准备 | 依赖安装成功 |
| Day 1 下午 | 2.1-2.2 配置扩展 | config.jsonc 更新 |
| Day 2 | 3.1-3.3 核心类实现 | EpisodeType, GroupIdStrategy |
| Day 3 | 3.4-3.5 Adapter 实现 | GraphitiAdapter 核心功能 |
| Day 4 上午 | 3.6 价值评估 + 4.1-4.3 测试 | 测试通过 |
| Day 4 下午 | 缓冲 + 文档 | 完成分规划一 |

---

## 🔗 后续规划

完成本分规划后，将进入：

1. **分规划二：Graphiti 工具集成**
   - graphiti_tools.py 实现
   - 与 memory_agent 集成
   - graphiti_search / graphiti_temporal 工具

2. **分规划三：原始对话保留机制**
   - ConversationMatcher
   - ConversationLogger
   - 与 proxy/routes/chat.py 集成

---

*创建时间：2026-01-22*
*作者：灰魂* 😸
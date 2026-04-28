# Memory Enhanced - 增强型记忆服务 v2.0

基于Google Gemini Embedding的智能记忆系统，支持语义搜索和轻量级浏览。

## ✨ 功能特性

### 1️⃣ 智能RAG搜索
- 🔍 **三种搜索模式**: 语义/关键词/混合搜索
- 🧠 使用Google Gemini `gemini-embedding-001` 模型
- 📊 自动按相关度排序结果
- ⚡ 语义理解，比关键词搜索更智能

### 2️⃣ 轻量级名称列表
- 📝 只返回实体名称，不包含详细内容
- 💰 Token消耗极低（<200 tokens）
- 🚀 快速浏览所有记忆

### 3️⃣ 按需获取详情
- 👀 先浏览名称列表
- 🎯 再选择性获取感兴趣的详情
- 💎 完美控制Token消耗

### 4️⃣ 关系搜索 🆕
- 🔗 查找实体的所有关系
- ↔️ 支持双向关系查找
- 🌐 快速了解实体连接

### 5️⃣ 性能优化 🚀
-  **二进制缓存**: 使用Pickle格式，文件减少60%，速度提升3-5倍
- 🔄 **批量向量化**: 批量处理，速度提升5-10倍
- ➕ **增量更新**: 只为新增实体生成向量，启动快如闪电
- ⚙️ **配置系统**: 集中管理所有配置项

## 📦 安装依赖

```bash
pip install google-generativeai numpy
```

## 🔑 配置API Key

### 方法1：修改config.json（推荐）
```json
{
  "env": {
    "GEMINI_API_KEY": "你的Gemini API Key"
  }
}
```

### 方法2：系统环境变量
```bash
# Windows
set GEMINI_API_KEY=你的key

# Linux/Mac
export GEMINI_API_KEY=你的key
```

### 获取Gemini API Key
1. 访问：https://makersuite.google.com/app/apikey
2. 登录Google账号
3. 创建API Key
4. 免费额度：60次/分钟

## 🛠️ 可用工具

### 1. `rag_search` - 智能RAG搜索 ⭐

**用途**：支持多种搜索模式的智能搜索

**参数**：
```json
{
  "query": "用户喜欢什么？",
  "top_k": 5,
  "search_mode": "semantic"  // "semantic"(语义) | "keyword"(关键词) | "hybrid"(混合)
}
```

**搜索模式说明**：
- `semantic` (默认): 语义向量搜索，最智能但需要API
- `keyword`: 关键词匹配，最快无需API
- `hybrid`: 混合搜索，覆盖面最广

**返回示例**：
```json
{
  "query": "用户喜欢什么？",
  "total_results": 3,
  "results": [
    {
      "name": "用户偏好",
      "entityType": "preferences",
      "observations": ["喜欢猫", "爱喝咖啡", "喜欢科幻电影"],
      "relevance_score": 0.87,
      "search_method": "semantic"  // 或 "keyword", "hybrid_semantic", "hybrid_keyword"
    }
  ]
}
```

**优势**：
- 🧠 语义理解："喜欢什么" 能匹配到 "偏好"、"爱好"、"兴趣"
- 📊 自动排序：按相关度智能排序
- 💰 Token友好：只返回最相关的top_k个
- 🔀 灵活切换：支持三种搜索模式

---

### 2. `list_entity_names` - 轻量级名称列表

**用途**：快速浏览所有记忆，不读取详细内容

**参数**：
```json
{
  "entity_type": "person"  // 可选，过滤类型
}
```

**返回示例**：
```json
{
  "total": 128,
  "entity_types": ["person", "project", "preferences"],
  "entities": [
    {"name": "张三", "type": "person", "observation_count": 5},
    {"name": "项目A", "type": "project", "observation_count": 3},
    {"name": "用户偏好", "type": "preferences", "observation_count": 10}
  ]
}
```

**Token消耗**：
- 100个实体 ≈ 200-300 tokens
- vs read_graph ≈ 5000+ tokens

---

### 3. `get_entity_detail` - 按需获取详情

**用途**：获取单个实体的完整信息

**参数**：
```json
{
  "name": "张三"
}
```

**返回示例**：
```json
{
  "name": "张三",
  "entityType": "person",
  "observations": [
    "软件工程师",
    "喜欢Python",
    "住在北京",
    "养了一只猫"
  ],
  "observation_count": 4
}
```

---

### 4. `search_relations` - 关系搜索 🆕

**用途**：搜索与实体相关的所有关系

**参数**：
```json
{
  "entity_name": "张三"
}
```

**返回示例**：
```json
{
  "entity": "张三",
  "total_relations": 3,
  "relations": [
    {
      "type": "relation",
      "from": "张三",
      "to": "ABC公司",
      "relationType": "works_at"
    },
    {
      "type": "relation",
      "from": "张三",
      "to": "李四",
      "relationType": "knows"
    }
  ]
}
```

## 🎯 使用场景

### 场景1：语义搜索
```
用户问："我之前提到过什么爱好？"

AI调用：rag_search({"query": "用户爱好兴趣", "top_k": 3})

结果：即使记忆中没有"爱好"这个词，也能通过语义匹配到
     "喜欢"、"偏好"等相关记忆
```

### 场景2：轻量级浏览
```
用户问："我记了多少东西？"

AI调用：list_entity_names()

结果：返回所有实体名称和数量，Token消耗<300
```

### 场景3：两步查询
```
步骤1：list_entity_names({"entity_type": "person"})
       → 看到有["张三", "李四", "王五"]

步骤2：get_entity_detail({"name": "张三"})
       → 只获取张三的详细信息

总Token：<500（vs read_graph的5000+）
```

## 📊 与原版Memory对比

| 功能 | 原版Memory | Memory Enhanced |
|------|-----------|----------------|
| 关键词搜索 | ✅ search_nodes | ✅ 降级支持 |
| 语义搜索 | ❌ | ✅ Gemini RAG |
| 轻量列表 | ❌ | ✅ list_entity_names |
| 按需详情 | ❌ | ✅ get_entity_detail |
| Token控制 | ⚠️ 依赖AI | ✅ 主动控制 |
| 读取全部 | ⚠️ read_graph | ❌ 已禁用 |

## ⚙️ 技术实现

### 向量化流程
```
实体文本："张三 (person): 软件工程师 | 喜欢Python"
    ↓
Gemini Embedding API (gemini-embedding-001)
    ↓
768维向量：[0.123, -0.456, 0.789, ...]
    ↓
存储在内存中（self.entity_embeddings）
```

### 搜索流程
```
用户查询："用户喜欢什么？"
    ↓
Gemini Embedding API (task_type=retrieval_query)
    ↓
查询向量：[0.321, -0.654, 0.987, ...]
    ↓
计算余弦相似度（与所有实体向量）
    ↓
排序并返回top_k
```

### 降级策略
```
如果Gemini API失败或未配置：
    ↓
自动降级为关键词搜索
    ↓
确保服务可用性
```

## 🔧 数据存储

**文件位置**：`memory.jsonl`（与官方Memory兼容）

**格式**：
```jsonl
{"type":"entity","name":"张三","entityType":"person","observations":["工程师"]}
{"type":"relation","from":"张三","to":"ABC公司","relationType":"works_at"}
```

**向量索引**：存储在内存中，启动时自动构建

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install google-generativeai numpy

# 2. 配置API Key（在config.json中）
"GEMINI_API_KEY": "你的key"

# 3. 启用服务（在enabled.txt中添加）
echo "memory_enhanced" >> mcp_servers/enabled.txt

# 4. 重启代理
python proxy_server.py
```

## 📝 注意事项

1. **API配额**：Gemini免费版60次/分钟，足够个人使用
2. **首次启动**：需要为所有实体生成向量，可能需要几秒钟
3. **内存占用**：向量存储在内存中，1000个实体约占用10MB
4. **兼容性**：读取标准memory.jsonl文件，与官方Memory兼容

## 🆚 何时使用

**使用Memory Enhanced**：
- ✅ 需要语义理解搜索
- ✅ 记忆数量较多（>100条）
- ✅ 需要严格控制Token

**使用官方Memory**：
- ✅ 记忆数量很少（<50条）
- ✅ 只需要精确名称匹配
- ✅ 不想配置额外API

## 🎁 额外功能

- **自动降级**：Gemini不可用时自动切换关键词搜索
- **类型过滤**：list_entity_names支持按类型过滤
- **相关度分数**：rag_search返回匹配度评分
- **搜索方法标记**：显示使用的搜索方式（gemini/keyword）

## 📚 相关链接

- Google Gemini API: https://ai.google.dev/
- Gemini Embedding文档: https://ai.google.dev/docs/embeddings_guide
- MCP协议: https://modelcontextprotocol.io/
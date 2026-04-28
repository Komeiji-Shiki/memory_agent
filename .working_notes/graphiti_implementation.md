# 🗒️ Graphiti 实现工作笔记

> 此文档记录 Graphiti 时序知识图谱改造的关键信息，避免重复读取

## 📋 当前进度

### 已完成 ✅
1. **requirements.txt** - 添加了 graphiti-core, kuzu, pydantic, python-dateutil
2. **config.jsonc** - 添加了完整的 graphiti 配置块（第213行之后）
3. **memory_store/graphiti_adapter.py** - 核心适配器已实现（约900行）

### 待完成 ⏳
1. 创建测试脚本 `tests/test_graphiti_adapter.py`
2. 更新 `config.jsonc.example` 同步配置

---

## 🔧 关键实现细节

### GraphitiAdapter 核心类

位置: `memory_store/graphiti_adapter.py`

**主要类:**
- `EpisodeType` - 枚举: DIARY, NODE, CONVERSATION
- `GraphitiConfig` - 完整配置数据类
- `GraphitiAdapter` - 异步适配器（核心）
- `GraphitiSyncAdapter` - 同步包装器
- `ContentValueEstimator` - 内容价值评估器

**主要方法:**
```python
# 初始化
await adapter.initialize()

# 添加内容
await adapter.add_episode(content, source, EpisodeType.DIARY)
await adapter.add_diary(date, content)
await adapter.add_node_content(node_name, content)
await adapter.add_conversation(session_id, turn_id, user_msg, ai_msg)

# 搜索
results = await adapter.search(query, num_results=10)
results = await adapter.search_advanced(query)  # 返回完整结果

# 时序查询
result = await adapter.temporal_query(entity_name, time_point)

# 同步
synced = await adapter.sync_from_markdown(include_diaries=True)

# 关闭
await adapter.close()
```

---

## 📁 Graphiti 源码关键路径

位置: `graphiti-main/graphiti_core/`

### 核心文件
- `graphiti.py` - Graphiti 主类，add_episode, search, search_ 方法
- `nodes.py` - EpisodeType(message/json/text), EntityNode, EpisodicNode
- `edges.py` - EntityEdge（包含 fact, valid_at, invalid_at）

### Driver
- `driver/kuzu_driver.py` - Kuzu 嵌入式图数据库驱动
- `driver/neo4j_driver.py` - Neo4j 驱动

### LLM Client
- `llm_client/openai_generic_client.py` - 支持自定义 base_url
- `llm_client/config.py` - LLMConfig(api_key, model, base_url, temperature, max_tokens, small_model)

### Embedder
- `embedder/openai.py` - OpenAIEmbedder, OpenAIEmbedderConfig(api_key, embedding_model, embedding_dim, base_url)

### Search
- `search/search_config.py` - SearchConfig, EdgeSearchConfig, NodeSearchConfig
- `search/search_config_recipes.py` - 预设配置如 COMBINED_HYBRID_SEARCH_CROSS_ENCODER

---

## ⚙️ config.jsonc 中的 graphiti 配置结构

```jsonc
{
    "graphiti": {
        "enabled": false,
        "backend": "kuzu",  // kuzu | neo4j
        
        "kuzu": { "db_path": "./lifebook/.graphiti.kuzu" },
        
        "neo4j": {
            "uri": "bolt://localhost:7687",
            "username": "neo4j",
            "password": "",
            "database": "lifebook"
        },
        
        "llm": {
            "base_url": null,  // 自定义 API 地址
            "api_key": "",
            "model": "gpt-4o-mini",
            "small_model": "gpt-4o-mini",
            "temperature": 1.0,
            "max_tokens": 16384
        },
        
        "embedding": {
            "base_url": null,
            "api_key": "",
            "model": "text-embedding-3-small",
            "dim": 1536
        },
        
        "reranker": { "enabled": false, "model": "gpt-4o-mini" },
        
        "search": {
            "edge_methods": ["cosine_similarity", "bm25"],
            "node_methods": ["cosine_similarity", "bm25"],
            "sim_min_score": 0.4,
            "mmr_lambda": 0.5,
            "reranker_min_score": 0.3
        },
        
        "group_id": {
            "strategy": "single",  // single | user | project
            "default": "lifebook"
        },
        
        "episode_types": {
            "diary": { "priority": "high", "extract_entities": true },
            "node": { "priority": "medium", "extract_entities": true },
            "conversation": {
                "priority": "low",
                "extract_entities": true,
                "min_value_threshold": 0.3
            }
        },
        
        "retrieval": {
            "strategy": "simple",  // simple | iterative
            "max_iterations": 3,
            "default_limit": 10,
            "include_edges": true,
            "include_nodes": true
        },
        
        "sync": { "index_conversations": true, "auto_sync_markdown": false },
        
        "performance": {
            "max_concurrent_queries": 1,
            "semaphore_limit": 10,
            "retry_on_rate_limit": true,
            "max_retries": 3
        }
    }
}
```

---

## 🧪 测试脚本模板

```python
# tests/test_graphiti_adapter.py
import asyncio
from memory_store.graphiti_adapter import (
    GraphitiAdapter, EpisodeType, GraphitiConfig
)

async def test_basic():
    config = {
        "graphiti": {
            "enabled": True,
            "backend": "kuzu",
            "kuzu": {"db_path": "./test_graphiti.kuzu"},
            "llm": {
                "api_key": "your-key",
                "model": "gpt-4o-mini"
            }
        }
    }
    
    async with GraphitiAdapter.create(config, "./lifebook") as adapter:
        # 添加日记
        uuid = await adapter.add_diary("2026-01-22", "今天测试了 Graphiti")
        print(f"Added episode: {uuid}")
        
        # 搜索
        results = await adapter.search("Graphiti")
        print(f"Found {len(results)} results")

if __name__ == "__main__":
    asyncio.run(test_basic())
```

---

## 📦 依赖版本

```txt
graphiti-core>=0.17.0
kuzu>=0.11.2
pydantic>=2.0
python-dateutil>=2.8
```

---

## ⚠️ 注意事项

1. **Structured Output**: Graphiti 需要 LLM 支持 `response_format: { type: "json_schema" }`
2. **Kuzu 路径**: 使用相对路径时会基于 lifebook_path 解析
3. **EpisodeType 映射**: 
   - DIARY → text
   - NODE → json  
   - CONVERSATION → message
4. **价值评估**: 对话类型会通过 `ContentValueEstimator` 过滤低价值内容

---

## 🔗 相关文件

- 总规划: `总规划-Graphiti时序知识图谱改造.md`
- 分规划: `分规划一-Graphiti存储层核心实现.md`
- 核心代码: `memory_store/graphiti_adapter.py`
- 配置文件: `config.jsonc`

---

*更新时间: 2026-01-22*
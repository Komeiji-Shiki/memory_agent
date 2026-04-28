#!/usr/bin/env python3
"""
Memory增强版MCP服务器
- 使用Google Gemini Embedding进行RAG向量搜索
- 添加轻量级名称列表
- 保持与官方Memory的兼容性
"""

import json
import sys
import os
import asyncio
import pickle
import time
from typing import List, Dict, Any, Optional
import numpy as np
from dataclasses import dataclass, field

# Google Gemini API
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("警告: google-generativeai未安装，请运行: pip install google-generativeai", file=sys.stderr)


@dataclass
class Config:
    """服务器配置"""
    memory_file_path: str = "memory.jsonl"
    embeddings_cache_file: str = ""
    gemini_api_key: str = ""
    similarity_threshold: float = 0.3
    batch_size: int = 50
    cache_enabled: bool = True
    use_binary_cache: bool = True  # 使用二进制缓存格式
    
    def __post_init__(self):
        """初始化后处理"""
        # 从环境变量读取所有配置
        self.memory_file_path = os.getenv('MEMORY_FILE_PATH') or self.memory_file_path
        self.gemini_api_key = os.getenv('GEMINI_API_KEY') or self.gemini_api_key
        
        # 读取可选配置
        if os.getenv('MEMORY_BATCH_SIZE'):
            self.batch_size = int(os.getenv('MEMORY_BATCH_SIZE'))
        
        if os.getenv('MEMORY_SIMILARITY_THRESHOLD'):
            self.similarity_threshold = float(os.getenv('MEMORY_SIMILARITY_THRESHOLD'))
        
        if os.getenv('MEMORY_CACHE_ENABLED'):
            self.cache_enabled = os.getenv('MEMORY_CACHE_ENABLED').lower() == 'true'
        
        if os.getenv('MEMORY_USE_BINARY_CACHE'):
            self.use_binary_cache = os.getenv('MEMORY_USE_BINARY_CACHE').lower() == 'true'
        
        # 自动生成缓存文件路径
        if not self.embeddings_cache_file:
            if self.use_binary_cache:
                self.embeddings_cache_file = self.memory_file_path + ".embeddings.pkl"
            else:
                self.embeddings_cache_file = self.memory_file_path + ".embeddings.json"
        
        # 打印配置信息
        print(f"📋 配置信息:", file=sys.stderr)
        print(f"  批次大小: {self.batch_size}", file=sys.stderr)
        print(f"  相似度阈值: {self.similarity_threshold}", file=sys.stderr)
        print(f"  缓存格式: {'二进制(Pickle)' if self.use_binary_cache else 'JSON'}", file=sys.stderr)
    
    @classmethod
    def from_env(cls):
        """从环境变量创建配置"""
        return cls()


@dataclass
class Entity:
    name: str
    entity_type: str
    observations: List[str]


class MemoryStore:
    """内存存储（基于JSONL文件）+ Gemini向量索引"""
    
    def __init__(self, config: Config = None):
        """初始化存储
        
        Args:
            config: 配置对象，如果为None则从环境变量创建
        """
        self.config = config or Config.from_env()
        self.entities: Dict[str, Entity] = {}
        self.relations: List[Dict] = []
        self.entity_embeddings: Dict[str, List[float]] = {}  # 存储向量
        
        # 配置Gemini
        if GEMINI_AVAILABLE and self.config.gemini_api_key:
            genai.configure(api_key=self.config.gemini_api_key)
            print(f"✓ Gemini API已配置", file=sys.stderr)
        else:
            print(f"✗ Gemini API未配置（需要GEMINI_API_KEY环境变量）", file=sys.stderr)
        
        self._last_modified_time = 0
        self._load()
    
    def _check_and_reload(self):
        """检查文件是否更新并重新加载"""
        if not os.path.exists(self.config.memory_file_path):
            return
            
        try:
            mtime = os.path.getmtime(self.config.memory_file_path)
            if mtime > self._last_modified_time:
                print(f"检测到文件更新，正在重新加载...", file=sys.stderr)
                self._load()
        except Exception as e:
            print(f"检查文件更新失败: {e}", file=sys.stderr)

    def _load_embeddings_cache(self) -> bool:
        """加载向量缓存（支持二进制和JSON格式）
        
        注意：此方法只检查缓存是否存在且有效，不检查时间戳。
        增量更新逻辑由 _incremental_update_embeddings() 处理。
        """
        if not self.config.cache_enabled:
            return False
            
        if not os.path.exists(self.config.embeddings_cache_file):
            return False
            
        try:
            # 加载缓存（不检查时间戳，让增量更新处理差异）
            if self.config.use_binary_cache:
                with open(self.config.embeddings_cache_file, 'rb') as f:
                    cache_data = pickle.load(f)
                    self.entity_embeddings = cache_data.get('embeddings', {})
                    print(f"✓ 已从二进制缓存加载 {len(self.entity_embeddings)} 个向量", file=sys.stderr)
            else:
                with open(self.config.embeddings_cache_file, 'r', encoding='utf-8') as f:
                    self.entity_embeddings = json.load(f)
                    print(f"✓ 已从JSON缓存加载 {len(self.entity_embeddings)} 个向量", file=sys.stderr)
            
            return True
        except Exception as e:
            print(f"加载向量缓存失败: {e}", file=sys.stderr)
            return False

    def _save_embeddings_cache(self):
        """保存向量缓存（支持二进制和JSON格式）"""
        if not self.config.cache_enabled:
            return
            
        try:
            if self.config.use_binary_cache:
                cache_data = {
                    'embeddings': self.entity_embeddings,
                    'version': '1.0',
                    'timestamp': time.time()
                }
                with open(self.config.embeddings_cache_file, 'wb') as f:
                    pickle.dump(cache_data, f)
                print(f"✓ 向量缓存已保存 (二进制格式)", file=sys.stderr)
            else:
                with open(self.config.embeddings_cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.entity_embeddings, f)
                print(f"✓ 向量缓存已保存 (JSON格式)", file=sys.stderr)
        except Exception as e:
            print(f"保存向量缓存失败: {e}", file=sys.stderr)

    def _load(self):
        """从文件加载"""
        if not os.path.exists(self.config.memory_file_path):
            return
        
        try:
            self._last_modified_time = os.path.getmtime(self.config.memory_file_path)
        except:
            pass

        # 清空现有数据以确保数据一致性
        self.entities = {}
        self.relations = []
        
        with open(self.config.memory_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    if data.get('type') == 'entity':
                        self.entities[data['name']] = Entity(
                            name=data['name'],
                            entity_type=data.get('entityType', 'unknown'),
                            observations=data.get('observations', [])
                        )
                    elif data.get('type') == 'relation':
                        self.relations.append(data)
                except:
                    continue
        
        print(f"✓ 已加载 {len(self.entities)} 个实体", file=sys.stderr)
        
        # 构建或加载向量索引
        if GEMINI_AVAILABLE and self.config.gemini_api_key:
            cache_loaded = self._load_embeddings_cache()
            
            if cache_loaded:
                # 缓存加载成功，执行增量更新（处理新增/删除的实体）
                self._incremental_update_embeddings()
            else:
                # 缓存不存在或损坏，全量重建
                self.entity_embeddings = {}
                self._build_embeddings_batch()
                self._save_embeddings_cache()
    
    def _get_entity_text(self, entity: Entity) -> str:
        """获取实体的文本表示"""
        return f"{entity.name} ({entity.entity_type}): {' | '.join(entity.observations)}"
    
    def _embed_single_entity(self, name: str, entity: Entity) -> bool:
        """为单个实体生成向量"""
        try:
            text = self._get_entity_text(entity)
            embedding = genai.embed_content(
                model="models/gemini-embedding-001",
                content=text,
                task_type="retrieval_document"
            )
            self.entity_embeddings[name] = embedding['embedding']
            return True
        except Exception as e:
            print(f"✗ 向量化失败 {name}: {e}", file=sys.stderr)
            return False
    
    def _build_embeddings_batch(self):
        """批量构建Gemini向量索引"""
        if not self.entities:
            return
        
        entities_list = list(self.entities.items())
        total = len(entities_list)
        batch_size = self.config.batch_size
        
        print(f"正在批量生成 {total} 个实体的向量 (批次大小: {batch_size})...", file=sys.stderr)
        
        success_count = 0
        for i in range(0, total, batch_size):
            batch = entities_list[i:i+batch_size]
            batch_texts = [self._get_entity_text(entity) for name, entity in batch]
            
            try:
                # Gemini 批量请求
                for j, (name, entity) in enumerate(batch):
                    text = batch_texts[j]
                    embedding = genai.embed_content(
                        model="models/gemini-embedding-001",
                        content=text,
                        task_type="retrieval_document"
                    )
                    self.entity_embeddings[name] = embedding['embedding']
                    success_count += 1
                
                print(f"  批次 {i//batch_size + 1}/{(total + batch_size - 1)//batch_size} 完成", file=sys.stderr)
                
            except Exception as e:
                print(f"  批次失败，降级为逐个处理: {e}", file=sys.stderr)
                # 降级为单个处理
                for name, entity in batch:
                    if self._embed_single_entity(name, entity):
                        success_count += 1
        
        print(f"✓ 向量索引构建完成: {success_count}/{total} 个实体", file=sys.stderr)
    
    def _incremental_update_embeddings(self):
        """增量更新向量（只为新增实体生成向量）"""
        new_entities = set(self.entities.keys()) - set(self.entity_embeddings.keys())
        removed_entities = set(self.entity_embeddings.keys()) - set(self.entities.keys())
        
        # 清理已删除实体的向量
        if removed_entities:
            for name in removed_entities:
                del self.entity_embeddings[name]
            print(f"✓ 清理了 {len(removed_entities)} 个已删除实体的向量", file=sys.stderr)
        
        # 为新增实体生成向量
        if new_entities:
            print(f"发现 {len(new_entities)} 个新实体，正在生成向量...", file=sys.stderr)
            success_count = 0
            for name in new_entities:
                entity = self.entities[name]
                if self._embed_single_entity(name, entity):
                    success_count += 1
            
            print(f"✓ 新增向量: {success_count}/{len(new_entities)}", file=sys.stderr)
            
            # 保存更新后的缓存
            if success_count > 0:
                self._save_embeddings_cache()
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
    
    def rag_search(self, query: str, top_k: int = 5, search_mode: str = "semantic") -> List[Dict]:
        """RAG搜索（支持多种搜索模式）
        
        Args:
            query: 搜索查询
            top_k: 返回结果数量
            search_mode: 搜索模式 - "semantic"(语义), "keyword"(关键词), "hybrid"(混合)
        """
        self._check_and_reload()
        
        if search_mode == "keyword":
            return self._keyword_search(query, top_k)
        elif search_mode == "hybrid":
            return self._hybrid_search(query, top_k)
        else:  # semantic
            return self._semantic_search(query, top_k)
    
    def _semantic_search(self, query: str, top_k: int) -> List[Dict]:
        """纯语义向量搜索"""
        if not GEMINI_AVAILABLE or not self.config.gemini_api_key:
            print("降级为关键词搜索（Gemini未配置）", file=sys.stderr)
            return self._keyword_search(query, top_k)
        
        if not self.entity_embeddings:
            print("向量索引为空，使用关键词搜索", file=sys.stderr)
            return self._keyword_search(query, top_k)
        
        try:
            # 向量化查询
            query_embedding = genai.embed_content(
                model="models/gemini-embedding-001",
                content=query,
                task_type="retrieval_query"
            )
            query_vec = query_embedding['embedding']
            
            # 计算所有实体的相似度
            similarities = {}
            for name, entity_vec in self.entity_embeddings.items():
                sim = self._cosine_similarity(query_vec, entity_vec)
                similarities[name] = sim
            
            # 排序并获取top_k
            sorted_entities = sorted(
                similarities.items(),
                key=lambda x: x[1],
                reverse=True
            )[:top_k]
            
            # 构建结果
            results = []
            for name, score in sorted_entities:
                if score > self.config.similarity_threshold:
                    entity = self.entities[name]
                    results.append({
                        "name": name,
                        "entityType": entity.entity_type,
                        "observations": entity.observations,
                        "relevance_score": float(score),
                        "search_method": "semantic"
                    })
            
            return results
        
        except Exception as e:
            print(f"语义搜索失败，降级为关键词: {e}", file=sys.stderr)
            return self._keyword_search(query, top_k)
    
    def _hybrid_search(self, query: str, top_k: int) -> List[Dict]:
        """混合搜索（语义 + 关键词）"""
        # 获取语义搜索结果
        semantic_results = self._semantic_search(query, top_k * 2)
        # 获取关键词搜索结果
        keyword_results = self._keyword_search(query, top_k * 2)
        
        # 合并结果（使用字典去重）
        merged = {}
        
        # 语义结果权重更高
        for result in semantic_results:
            name = result['name']
            merged[name] = result.copy()
            merged[name]['search_method'] = 'hybrid_semantic'
        
        # 添加关键词结果
        for result in keyword_results:
            name = result['name']
            if name not in merged:
                merged[name] = result.copy()
                merged[name]['search_method'] = 'hybrid_keyword'
                merged[name]['relevance_score'] = 0.5  # 给关键词结果一个基础分数
        
        # 按相关度排序并返回top_k
        results = sorted(
            merged.values(),
            key=lambda x: x.get('relevance_score', 0),
            reverse=True
        )[:top_k]
        
        return results
    
    def _keyword_search(self, query: str, top_k: int) -> List[Dict]:
        """简单关键词搜索（降级方案）"""
        results = []
        query_lower = query.lower()
        
        for name, entity in self.entities.items():
            text = self._get_entity_text(entity).lower()
            if query_lower in text:
                results.append({
                    "name": name,
                    "entityType": entity.entity_type,
                    "observations": entity.observations,
                    "search_method": "keyword"
                })
                if len(results) >= top_k:
                    break
        
        return results
    
    def list_entity_names(self, entity_type: Optional[str] = None) -> List[Dict]:
        """只返回实体名称（轻量级）"""
        self._check_and_reload()
        results = []
        for name, entity in self.entities.items():
            if entity_type and entity.entity_type != entity_type:
                continue
            results.append({
                "name": name,
                "type": entity.entity_type,
                "observation_count": len(entity.observations)
            })
        return sorted(results, key=lambda x: x['name'])
    
    def get_entity(self, name: str) -> Optional[Entity]:
        """获取单个实体"""
        self._check_and_reload()
        return self.entities.get(name)
    
    def search_relations(self, entity_name: str) -> List[Dict]:
        """搜索与实体相关的所有关系"""
        self._check_and_reload()
        relations = []
        for rel in self.relations:
            if rel.get('from') == entity_name or rel.get('to') == entity_name:
                relations.append(rel)
        return relations


class MemoryEnhancedServer:
    """增强型Memory MCP服务器"""
    
    def __init__(self):
        self.store = MemoryStore()
        self.tools = [
            {
                "name": "rag_search",
                "description": "⭐推荐⭐ 使用Google Gemini向量相似度搜索最相关的记忆（支持语义/关键词/混合搜索）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询，可以是自然语言问题或关键词"
                        },
                        "top_k": {
                            "type": "number",
                            "description": "返回最相关的K个结果，默认5",
                            "default": 5
                        },
                        "search_mode": {
                            "type": "string",
                            "description": "搜索模式: 'semantic'(语义,默认), 'keyword'(关键词), 'hybrid'(混合)",
                            "default": "semantic",
                            "enum": ["semantic", "keyword", "hybrid"]
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "list_entity_names",
                "description": "⭐推荐⭐ 列出所有实体的名称列表（不包含详细内容，适合快速浏览，Token消耗极低，应优先使用此工具而不是read_graph）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_type": {
                            "type": "string",
                            "description": "过滤特定类型的实体（可选），如'person'、'project'等"
                        }
                    }
                }
            },
            {
                "name": "get_entity_detail",
                "description": "根据名称获取实体的完整详细内容（先用list_entity_names查看所有名称，再用此工具获取感兴趣的详情）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "实体名称（从list_entity_names获取）"
                        }
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "search_relations",
                "description": "搜索与指定实体相关的所有关系",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_name": {
                            "type": "string",
                            "description": "实体名称"
                        }
                    },
                    "required": ["entity_name"]
                }
            }
        ]
    
    async def handle_list_tools(self) -> Dict:
        """返回工具列表"""
        return {"tools": self.tools}
    
    async def handle_call_tool(self, name: str, arguments: Dict) -> Dict:
        """处理工具调用"""
        if name == "rag_search":
            results = self.store.rag_search(
                arguments["query"],
                arguments.get("top_k", 5),
                arguments.get("search_mode", "semantic")
            )
            
            summary = {
                "query": arguments["query"],
                "total_results": len(results),
                "results": results
            }
            
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps(summary, ensure_ascii=False, indent=2)
                }]
            }
        
        elif name == "list_entity_names":
            results = self.store.list_entity_names(
                arguments.get("entity_type")
            )
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "total": len(results),
                        "entity_types": list(set(r['type'] for r in results)),
                        "entities": results
                    }, ensure_ascii=False, indent=2)
                }]
            }
        
        elif name == "get_entity_detail":
            entity_name = arguments["name"]
            entity = self.store.get_entity(entity_name)
            if entity:
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({
                            "name": entity.name,
                            "entityType": entity.entity_type,
                            "observations": entity.observations,
                            "observation_count": len(entity.observations)
                        }, ensure_ascii=False, indent=2)
                    }]
                }
            else:
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({
                            "error": f"实体不存在: {entity_name}",
                            "suggestion": "使用list_entity_names查看所有可用实体"
                        }, ensure_ascii=False)
                    }],
                    "isError": True
                }
        
        elif name == "search_relations":
            entity_name = arguments["entity_name"]
            relations = self.store.search_relations(entity_name)
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "entity": entity_name,
                        "total_relations": len(relations),
                        "relations": relations
                    }, ensure_ascii=False, indent=2)
                }]
            }
        
        return {
            "content": [{"type": "text", "text": f"未知工具: {name}"}],
            "isError": True
        }
    
    async def handle_message(self, message: Dict) -> Dict:
        """处理MCP消息"""
        method = message.get("method")
        
        if method == "tools/list":
            return await self.handle_list_tools()
        elif method == "tools/call":
            params = message.get("params", {})
            return await self.handle_call_tool(
                params.get("name"),
                params.get("arguments", {})
            )
        elif method == "initialize":
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "memory-enhanced-gemini",
                    "version": "1.0.0"
                }
            }
        else:
            return {"error": f"未知方法: {method}"}
    
    async def run(self):
        """运行服务器"""
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                
                message = json.loads(line)
                response = await self.handle_message(message)
                
                rpc_response = {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "result": response
                }
                
                print(json.dumps(rpc_response), flush=True)
            
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": message.get("id") if 'message' in locals() else None,
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }
                print(json.dumps(error_response), flush=True)


if __name__ == "__main__":
    server = MemoryEnhancedServer()
    asyncio.run(server.run())
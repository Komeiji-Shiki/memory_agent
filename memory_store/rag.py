"""
RAG Module - 向量检索增强生成

使用SiliconFlow Embedding API进行语义搜索：
1. 将记忆内容向量化
2. 存储向量到SQLite数据库
3. 语义相似度搜索

配置：
- SILICONFLOW_API_KEY: API密钥
- SILICONFLOW_MODEL: 嵌入模型（默认 Qwen/Qwen3-Embedding-8B）
- SILICONFLOW_URL: API地址

特性：
- API调用失败自动重试（指数退避）
- SQLite存储（高效处理大数据量）
- 基于内容hash的增量更新
- 相对路径存储（支持U盘盘符变化）
"""

import os
import json
import hashlib
import time
import random
import logging
import sqlite3
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import requests


@dataclass
class RAGConfig:
    """RAG配置"""
    api_key: str = ""
    model: str = "Qwen/Qwen3-Embedding-8B"
    base_url: str = "https://api.siliconflow.cn/v1/embeddings"
    chunk_size: int = 500  # 文本分块大小
    chunk_overlap: int = 50  # 块重叠
    top_k: int = 5  # 返回结果数
    similarity_threshold: float = 0.3  # 相似度阈值
    enabled: bool = True


@dataclass
class VectorEntry:
    """向量索引条目"""
    id: str  # 唯一ID（基于内容hash）
    file_path: str  # 来源文件（相对路径）
    chunk_index: int  # 块索引
    content: str  # 原始文本内容
    metadata: Dict[str, Any]  # 元数据（日期、类型等）
    embedding: List[float]  # 向量
    created_at: str  # 创建时间


class RAGSQLiteStorage:
    """RAG SQLite存储后端"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 向量表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vectors (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT,
                embedding_blob BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_path ON vectors(file_path)')
        
        # 元数据表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        logging.debug(f"[RAG] SQLite数据库初始化完成: {self.db_path}")
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """获取元数据"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM metadata WHERE key = ?', (key,))
        row = cursor.fetchone()
        conn.close()
        if row:
            try:
                return json.loads(row[0])
            except:
                return row[0]
        return default
    
    def set_metadata(self, key: str, value: Any):
        """设置元数据"""
        conn = self._get_conn()
        cursor = conn.cursor()
        value_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        cursor.execute(
            'INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)',
            (key, value_str)
        )
        conn.commit()
        conn.close()
    
    def get_all_metadata(self) -> Dict[str, Any]:
        """获取所有元数据"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT key, value FROM metadata')
        rows = cursor.fetchall()
        conn.close()
        
        result = {}
        for key, value in rows:
            try:
                result[key] = json.loads(value)
            except:
                result[key] = value
        return result
    
    def save_entry(self, entry: VectorEntry):
        """保存向量条目"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # 将向量转为bytes存储
        embedding_blob = np.array(entry.embedding, dtype=np.float32).tobytes()
        metadata_json = json.dumps(entry.metadata, ensure_ascii=False)
        
        cursor.execute('''
            INSERT OR REPLACE INTO vectors 
            (id, file_path, chunk_index, content, metadata_json, embedding_blob, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            entry.id,
            entry.file_path,
            entry.chunk_index,
            entry.content,
            metadata_json,
            embedding_blob,
            entry.created_at
        ))
        
        conn.commit()
        conn.close()
    
    def save_entries_batch(self, entries: List[VectorEntry]):
        """批量保存向量条目"""
        if not entries:
            return
            
        conn = self._get_conn()
        cursor = conn.cursor()
        
        data = []
        for entry in entries:
            embedding_blob = np.array(entry.embedding, dtype=np.float32).tobytes()
            metadata_json = json.dumps(entry.metadata, ensure_ascii=False)
            data.append((
                entry.id,
                entry.file_path,
                entry.chunk_index,
                entry.content,
                metadata_json,
                embedding_blob,
                entry.created_at
            ))
        
        cursor.executemany('''
            INSERT OR REPLACE INTO vectors 
            (id, file_path, chunk_index, content, metadata_json, embedding_blob, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', data)
        
        conn.commit()
        conn.close()
    
    def get_entry(self, entry_id: str) -> Optional[VectorEntry]:
        """获取单个条目"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM vectors WHERE id = ?', (entry_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_entry(row)
        return None
    
    def get_all_entries(self) -> Dict[str, VectorEntry]:
        """获取所有条目"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM vectors')
        rows = cursor.fetchall()
        conn.close()
        
        entries = {}
        for row in rows:
            entry = self._row_to_entry(row)
            entries[entry.id] = entry
        return entries
    
    def _row_to_entry(self, row) -> VectorEntry:
        """将数据库行转为VectorEntry"""
        embedding = np.frombuffer(row[5], dtype=np.float32).tolist()
        metadata = json.loads(row[4]) if row[4] else {}
        
        return VectorEntry(
            id=row[0],
            file_path=row[1],
            chunk_index=row[2],
            content=row[3],
            metadata=metadata,
            embedding=embedding,
            created_at=row[6]
        )
    
    def delete_entry(self, entry_id: str):
        """删除单个条目"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM vectors WHERE id = ?', (entry_id,))
        conn.commit()
        conn.close()
    
    def delete_by_file(self, file_path: str) -> int:
        """删除指定文件的所有条目"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM vectors WHERE file_path = ?', (file_path,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted
    
    def entry_exists(self, entry_id: str) -> bool:
        """检查条目是否存在"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM vectors WHERE id = ? LIMIT 1', (entry_id,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    
    def get_entry_count(self) -> int:
        """获取条目总数"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM vectors')
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def get_all_file_paths(self) -> set:
        """获取所有文件路径"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT file_path FROM vectors')
        paths = {row[0] for row in cursor.fetchall()}
        conn.close()
        return paths
    
    def clear_all(self):
        """清空所有数据"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM vectors')
        cursor.execute('DELETE FROM metadata')
        conn.commit()
        conn.close()


class RAGIndex:
    """RAG向量索引"""
    
    def __init__(
        self,
        lifebook_path: str,
        config: Optional[RAGConfig] = None,
        encoding: str = "utf-8"
    ):
        """
        初始化RAG索引
        
        Args:
            lifebook_path: LifeBook根目录
            config: RAG配置
            encoding: 文件编码
        """
        self.lifebook_path = Path(lifebook_path)
        self.config = config or RAGConfig()
        self.encoding = encoding
        
        # 索引存储路径
        self.index_dir = self.lifebook_path / ".rag_index"
        self.db_path = self.index_dir / "vectors.db"
        self.legacy_vectors_path = self.index_dir / "vectors.json"
        self.legacy_meta_path = self.index_dir / "metadata.json"
        
        # 确保目录存在
        self.index_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化SQLite存储
        self.storage = RAGSQLiteStorage(str(self.db_path))
        
        # 检查是否需要迁移
        self._migrate_from_json_if_needed()
        
        # 内存缓存（用于搜索加速）
        self._entries_cache: Optional[Dict[str, VectorEntry]] = None
        self._cache_valid = False
    
    def _migrate_from_json_if_needed(self):
        """从JSON迁移到SQLite（如果需要）"""
        if not self.legacy_vectors_path.exists():
            return
        
        # 检查是否已迁移
        if self.storage.get_metadata("migrated_from_json"):
            return
        
        logging.info("[RAG] 检测到旧版JSON索引，开始迁移到SQLite...")
        
        try:
            # 加载旧的vectors.json
            with open(self.legacy_vectors_path, "r", encoding=self.encoding) as f:
                data = json.load(f)
            
            entries = []
            converted_paths = 0
            for entry_data in data:
                # 转换绝对路径为相对路径
                old_path = entry_data.get("file_path", "")
                if old_path and (old_path.startswith("/") or (len(old_path) > 1 and old_path[1] == ":")):
                    # 这是绝对路径，需要转换
                    new_path = self._convert_absolute_to_relative(old_path)
                    entry_data["file_path"] = new_path
                    converted_paths += 1
                
                entry = VectorEntry(**entry_data)
                entries.append(entry)
            
            # 批量保存到SQLite
            self.storage.save_entries_batch(entries)
            
            # 迁移元数据（需要转换files_mtime的key）
            if self.legacy_meta_path.exists():
                with open(self.legacy_meta_path, "r", encoding=self.encoding) as f:
                    old_meta = json.load(f)
                
                # 转换files_mtime中的绝对路径key
                if "files_mtime" in old_meta:
                    new_files_mtime = {}
                    for old_key, mtime in old_meta["files_mtime"].items():
                        if old_key.startswith("/") or (len(old_key) > 1 and old_key[1] == ":"):
                            new_key = self._convert_absolute_to_relative(old_key)
                        else:
                            new_key = old_key
                        new_files_mtime[new_key] = mtime
                    old_meta["files_mtime"] = new_files_mtime
                
                for key, value in old_meta.items():
                    self.storage.set_metadata(key, value)
            
            # 标记已迁移
            self.storage.set_metadata("migrated_from_json", True)
            self.storage.set_metadata("migration_time", datetime.now().isoformat())
            
            # 备份旧文件
            backup_dir = self.index_dir / "json_backup"
            backup_dir.mkdir(exist_ok=True)
            
            import shutil
            shutil.move(str(self.legacy_vectors_path), str(backup_dir / "vectors.json"))
            if self.legacy_meta_path.exists():
                shutil.move(str(self.legacy_meta_path), str(backup_dir / "metadata.json"))
            
            logging.info(f"[RAG] 迁移完成，共迁移 {len(entries)} 条向量，转换了 {converted_paths} 个绝对路径，旧文件已备份")
            
        except Exception as e:
            logging.error(f"[RAG] 迁移失败: {e}")
    
    def _convert_absolute_to_relative(self, abs_path: str) -> str:
        """将绝对路径转换为相对路径（用于迁移）"""
        try:
            path = Path(abs_path)
            # 尝试找到lifebook目录的位置
            parts = path.parts
            for i, part in enumerate(parts):
                if part.lower() == "lifebook":
                    # 返回lifebook之后的相对路径
                    rel_parts = parts[i+1:]
                    return "/".join(rel_parts)
            # 如果找不到lifebook，返回文件名
            return path.name
        except:
            return Path(abs_path).name
    
    def _invalidate_cache(self):
        """使缓存失效"""
        self._cache_valid = False
        self._entries_cache = None
    
    def _ensure_cache(self):
        """确保缓存有效"""
        if not self._cache_valid:
            self._entries_cache = self.storage.get_all_entries()
            self._cache_valid = True
    
    @property
    def entries(self) -> Dict[str, VectorEntry]:
        """获取所有条目（带缓存）"""
        self._ensure_cache()
        return self._entries_cache
    
    def get_embedding(
        self,
        text: str,
        max_retries: int = 3,
        base_delay: float = 1.0
    ) -> Optional[List[float]]:
        """
        获取文本的向量嵌入（带重试机制）
        
        Args:
            text: 输入文本
            max_retries: 最大重试次数
            base_delay: 基础延迟时间（秒），使用指数退避
            
        Returns:
            向量列表，失败返回None
        """
        if not self.config.api_key:
            logging.warning("[RAG] 未配置API Key")
            return None
        
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.config.model,
            "input": text[:2000],  # 限制长度避免超出API限制
            "encoding_format": "float"
        }
        
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    # 指数退避 + 随机抖动
                    delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logging.debug(f"[RAG] 重试第 {attempt} 次，等待 {delay:.2f} 秒...")
                    time.sleep(delay)
                
                response = requests.post(
                    self.config.base_url,
                    headers=headers,
                    json=payload,
                    timeout=30
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if "data" in data and len(data["data"]) > 0:
                        embedding = data["data"][0]["embedding"]
                        if attempt > 0:
                            logging.debug(f"[RAG] 嵌入成功（重试 {attempt} 次后）: 维度={len(embedding)}")
                        return embedding
                    else:
                        logging.warning(f"[RAG] API返回数据异常: {data}")
                        return None
                
                elif response.status_code == 429:
                    # 速率限制，需要重试
                    logging.warning(f"[RAG] 触发速率限制 (429)，将重试...")
                    last_error = f"速率限制 (429)"
                    continue
                
                elif response.status_code >= 500:
                    # 服务器错误，可重试
                    logging.warning(f"[RAG] 服务器错误 ({response.status_code})，将重试...")
                    last_error = f"服务器错误 ({response.status_code})"
                    continue
                
                else:
                    # 其他错误（如401、400），不重试
                    logging.error(f"[RAG] API错误: 状态码={response.status_code}, 响应: {response.text}")
                    return None
                    
            except requests.exceptions.Timeout:
                logging.warning(f"[RAG] 请求超时，将重试...")
                last_error = "请求超时"
                continue
                
            except requests.exceptions.ConnectionError as ce:
                logging.warning(f"[RAG] 连接错误: {ce}，将重试...")
                last_error = f"连接错误: {ce}"
                continue
                
            except requests.exceptions.RequestException as re:
                logging.warning(f"[RAG] 网络请求异常: {re}")
                last_error = str(re)
                continue
                
            except Exception as e:
                logging.error(f"[RAG] 获取嵌入时发生未知错误: {type(e).__name__}: {e}", exc_info=True)
                return None
        
        # 所有重试都失败
        logging.error(f"[RAG] 嵌入请求失败，已重试 {max_retries} 次。最后错误: {last_error}")
        return None
    
    def get_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """批量获取向量嵌入"""
        results = []
        for text in texts:
            embedding = self.get_embedding(text)
            results.append(embedding)
        return results
    
    def _chunk_text(self, text: str) -> List[str]:
        """将文本分块"""
        if len(text) <= self.config.chunk_size:
            return [text]
        
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.config.chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start = end - self.config.chunk_overlap
        
        return chunks
    
    def _to_relative_path(self, file_path: str) -> str:
        """将绝对路径转换为相对于lifebook的路径（解决U盘盘符变化问题）"""
        try:
            abs_path = Path(file_path).resolve()
            lifebook_abs = self.lifebook_path.resolve()
            rel_path = abs_path.relative_to(lifebook_abs)
            return str(rel_path).replace("\\", "/")  # 统一使用正斜杠
        except ValueError:
            # 如果不是lifebook子路径，返回原路径的文件名部分
            return str(Path(file_path).name)
    
    def _compute_id(self, file_path: str, chunk_index: int, content: str) -> str:
        """计算条目ID（基于内容hash，确保内容变化时ID也变化）"""
        # 使用相对路径计算ID，避免盘符变化影响
        rel_path = self._to_relative_path(file_path)
        content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
        hash_input = f"{rel_path}:{chunk_index}:{content_hash}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:16]
    
    def _compute_content_hash(self, content: str) -> str:
        """计算内容hash（用于增量更新判断）"""
        return hashlib.md5(content.encode()).hexdigest()
    
    def index_file(self, file_path: str, content: str, metadata: Dict[str, Any] = None) -> int:
        """
        索引单个文件
        
        Args:
            file_path: 文件路径
            content: 文件内容
            metadata: 元数据
            
        Returns:
            新增的向量数量
        """
        if not self.config.enabled:
            logging.debug(f"[RAG] index_file 跳过: RAG未启用")
            return 0
        
        metadata = metadata or {}
        chunks = self._chunk_text(content)
        added = 0
        
        # 使用相对路径存储（解决U盘盘符变化问题）
        rel_path = self._to_relative_path(file_path)
        
        logging.debug(f"[RAG] 准备索引文件: {rel_path}, 内容长度: {len(content)}, 分块数量: {len(chunks)}")
        
        if not chunks:
            logging.warning(f"[RAG] 文件分块结果为空: {rel_path}")
            return 0
        
        new_entries = []
        for i, chunk in enumerate(chunks):
            entry_id = self._compute_id(file_path, i, chunk)
            
            # 跳过已存在的条目
            if self.storage.entry_exists(entry_id):
                logging.debug(f"[RAG] 块{i}: 已存在，跳过")
                continue
            
            # 获取向量
            logging.debug(f"[RAG] 块{i}: 正在获取嵌入...")
            embedding = self.get_embedding(chunk)
            if embedding is None:
                logging.warning(f"[RAG] 块{i}: 获取嵌入失败")
                continue
            
            # 创建条目 - 使用相对路径
            entry = VectorEntry(
                id=entry_id,
                file_path=rel_path,
                chunk_index=i,
                content=chunk,
                metadata=metadata,
                embedding=embedding,
                created_at=datetime.now().isoformat()
            )
            
            new_entries.append(entry)
            added += 1
        
        if new_entries:
            self.storage.save_entries_batch(new_entries)
            self._invalidate_cache()
            logging.info(f"[RAG] 索引文件 {rel_path}: 新增 {added} 个向量")
        
        return added
    
    def remove_file(self, file_path: str) -> int:
        """移除文件的所有向量"""
        # 转换为相对路径进行匹配
        rel_path = self._to_relative_path(file_path)
        deleted = self.storage.delete_by_file(rel_path)
        
        if deleted > 0:
            self._invalidate_cache()
        
        return deleted
    
    def search(
        self,
        query: str,
        top_k: int = None,
        filter_type: str = None,
        date_start: str = None,
        date_end: str = None
    ) -> List[Tuple[VectorEntry, float]]:
        """
        语义搜索
        
        Args:
            query: 查询文本
            top_k: 返回数量
            filter_type: 筛选类型（diary, node, summary等）
            date_start: 开始日期
            date_end: 结束日期
            
        Returns:
            [(VectorEntry, 相似度分数), ...]
        """
        entries = self.entries
        if not entries:
            return []
        
        # 获取查询向量
        query_embedding = self.get_embedding(query)
        if query_embedding is None:
            return []
        
        query_vec = np.array(query_embedding)
        
        # 计算相似度
        results = []
        for entry in entries.values():
            # 应用过滤器
            if filter_type:
                entry_type = entry.metadata.get("type", "")
                if filter_type not in entry_type:
                    continue
            
            if date_start or date_end:
                entry_date = entry.metadata.get("date", "")
                if entry_date:
                    if date_start and entry_date < date_start:
                        continue
                    if date_end and entry_date > date_end:
                        continue
            
            # 计算余弦相似度
            entry_vec = np.array(entry.embedding)
            similarity = np.dot(query_vec, entry_vec) / (
                np.linalg.norm(query_vec) * np.linalg.norm(entry_vec) + 1e-8
            )
            
            if similarity >= self.config.similarity_threshold:
                results.append((entry, float(similarity)))
        
        # 排序
        results.sort(key=lambda x: x[1], reverse=True)
        
        # 限制数量
        k = top_k or self.config.top_k
        return results[:k]
    
    def rebuild_index(self, incremental: bool = True) -> Dict[str, Any]:
        """
        扫描文件并更新索引
        
        Args:
            incremental: 是否使用增量更新（默认True）。False表示清空重来。
        """
        logging.info(f"[RAG] 开始{'增量' if incremental else '全量'}更新索引...")
        
        if not self.config.enabled:
            return {"success": False, "message": "RAG未启用"}
        
        stats = {
            "diaries": 0,
            "nodes": 0,
            "summaries": 0,
            "added_vectors": 0,
            "removed_files": 0,
            "skipped_files": 0,
            "errors": []
        }
        
        if not incremental:
            logging.info(f"[RAG] 清空现有索引 (原条目数: {self.storage.get_entry_count()})")
            self.storage.clear_all()
            self._invalidate_cache()
        
        # 获取files_mtime元数据
        files_mtime = self.storage.get_metadata("files_mtime", {})
        
        import builtins
        all_found_files = set()

        # 1. 扫描日记
        daily_dir = self.lifebook_path / "daily"
        if daily_dir.exists():
            for md_path in daily_dir.glob("*.md"):
                # 使用相对路径作为key（解决U盘盘符变化问题）
                rel_key = self._to_relative_path(str(md_path))
                all_found_files.add(rel_key)
                
                mtime = os.path.getmtime(md_path)
                if incremental and files_mtime.get(rel_key) == mtime:
                    stats["skipped_files"] += 1
                    continue

                try:
                    with builtins.open(str(md_path), "r", encoding=self.encoding) as f:
                        content = f.read()
                    self.remove_file(str(md_path))
                    count = self.index_file(str(md_path), content, {"type": "diary", "date": md_path.stem})
                    files_mtime[rel_key] = mtime
                    stats["diaries"] += 1
                    stats["added_vectors"] += count
                except Exception as e:
                    logging.error(f"[RAG] 索引日记失败 {md_path.name}: {e}")
                    stats["errors"].append(f"日记 {md_path.name}: {e}")
        
        # 2. 扫描节点
        nodes_dir = self.lifebook_path / "nodes"
        if nodes_dir.exists():
            for md_path in nodes_dir.glob("*.md"):
                # 使用相对路径作为key
                rel_key = self._to_relative_path(str(md_path))
                all_found_files.add(rel_key)
                
                mtime = os.path.getmtime(md_path)
                if incremental and files_mtime.get(rel_key) == mtime:
                    stats["skipped_files"] += 1
                    continue

                try:
                    with builtins.open(str(md_path), "r", encoding=self.encoding) as f:
                        content = f.read()
                    self.remove_file(str(md_path))
                    
                    name = md_path.stem
                    node_type = "node"
                    for t in ["人物", "地点", "事物", "概念"]:
                        if name.startswith(f"{t}-"):
                            node_type = f"node_{t}"
                            break
                    
                    count = self.index_file(str(md_path), content, {"type": node_type, "name": name})
                    files_mtime[rel_key] = mtime
                    stats["nodes"] += 1
                    stats["added_vectors"] += count
                except Exception as e:
                    logging.error(f"[RAG] 索引节点失败 {md_path.name}: {e}")
                    stats["errors"].append(f"节点 {md_path.name}: {e}")
        
        # 3. 扫描总结
        for summary_type in ["weekly", "monthly", "quarterly", "yearly"]:
            summary_dir = self.lifebook_path / summary_type
            if summary_dir.exists():
                for md_path in summary_dir.glob("*.md"):
                    if md_path.name == ".gitkeep": continue
                    # 使用相对路径作为key
                    rel_key = self._to_relative_path(str(md_path))
                    all_found_files.add(rel_key)
                    
                    mtime = os.path.getmtime(md_path)
                    if incremental and files_mtime.get(rel_key) == mtime:
                        stats["skipped_files"] += 1
                        continue

                    try:
                        with builtins.open(str(md_path), "r", encoding=self.encoding) as f:
                            content = f.read()
                        self.remove_file(str(md_path))
                        count = self.index_file(str(md_path), content, {"type": f"summary_{summary_type}", "identifier": md_path.stem})
                        files_mtime[rel_key] = mtime
                        stats["summaries"] += 1
                        stats["added_vectors"] += count
                    except Exception as e:
                        logging.error(f"[RAG] 索引总结失败 {md_path.name}: {e}")
                        stats["errors"].append(f"总结 {md_path.name}: {e}")
        
        # 4. 彻底清理已删除的文件
        indexed_files_in_db = self.storage.get_all_file_paths()
        indexed_files_in_mtime = set(files_mtime.keys())
        all_indexed_files = indexed_files_in_db | indexed_files_in_mtime
        
        for file_path in all_indexed_files:
            if file_path not in all_found_files:
                logging.debug(f"[RAG] 检测到过时索引，正在清理: {file_path}")
                self.storage.delete_by_file(file_path)
                if file_path in files_mtime:
                    del files_mtime[file_path]
                stats["removed_files"] += 1
        
        # 保存元数据
        self.storage.set_metadata("files_mtime", files_mtime)
        self.storage.set_metadata("last_updated", datetime.now().isoformat())
        self.storage.set_metadata("model", self.config.model)
        self.storage.set_metadata("version", "2.0")
        
        self._invalidate_cache()
        
        # 添加当前总向量数
        stats["total_vectors"] = self.storage.get_entry_count()
        
        msg = f"索引更新完成：新增 {stats['added_vectors']} 向量，跳过 {stats['skipped_files']} 文件"
        if stats["removed_files"] > 0:
            msg += f"，清理 {stats['removed_files']} 个删除的文件"
            
        logging.info(f"[RAG] {msg}")
        return {
            "success": True,
            "message": msg,
            "stats": stats
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计"""
        entries = self.entries
        type_counts = {}
        for entry in entries.values():
            entry_type = entry.metadata.get("type", "unknown")
            type_counts[entry_type] = type_counts.get(entry_type, 0) + 1
        
        return {
            "enabled": self.config.enabled,
            "model": self.config.model,
            "total_entries": len(entries),
            "by_type": type_counts,
            "chunk_size": self.config.chunk_size,
            "top_k": self.config.top_k,
            "last_updated": self.storage.get_metadata("last_updated", ""),
            "storage": "sqlite"
        }


class RAGSearcher:
    """RAG搜索器（供Agent调用）"""
    
    def __init__(self, rag_index: RAGIndex):
        self.index = rag_index
    
    def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        filter_type: str = None
    ) -> str:
        """
        语义搜索记忆
        
        Args:
            query: 搜索查询
            top_k: 返回数量
            filter_type: 类型过滤
            
        Returns:
            格式化的搜索结果
        """
        results = self.index.search(query, top_k=top_k, filter_type=filter_type)
        
        if not results:
            return "未找到语义相关的记忆。"
        
        output = f"找到 {len(results)} 条语义相关记忆：\n\n"
        
        for i, (entry, score) in enumerate(results, 1):
            entry_type = entry.metadata.get("type", "unknown")
            date = entry.metadata.get("date", "")
            
            output += f"**{i}. [{entry_type}]** "
            if date:
                output += f"({date}) "
            output += f"相似度: {score:.2f}\n"
            
            # 显示内容预览
            preview = entry.content[:200].replace("\n", " ")
            output += f"> {preview}...\n\n"
        
        return output


# 全局实例
_rag_index: Optional[RAGIndex] = None


def init_rag(lifebook_path: str, config: Optional[RAGConfig] = None) -> RAGIndex:
    """初始化RAG索引"""
    global _rag_index
    _rag_index = RAGIndex(lifebook_path, config)
    return _rag_index


def get_rag_index() -> Optional[RAGIndex]:
    """获取RAG索引"""
    return _rag_index


# 测试代码已移至 tests/test_memory_store.py
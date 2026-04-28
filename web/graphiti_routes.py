"""
Graphiti 时序知识图谱 API 路由

提供：
- /graphiti/config - 配置管理
- /graphiti/stats - 状态统计
- /graphiti/token-usage - Token 使用量追踪
- /graphiti/sync - Markdown 同步（支持暂停/停止/继续）
- /graphiti/rebuild - 索引重建
- /graphiti/search - 测试搜索
- /graphiti/graph-data - 图谱可视化数据
"""

import os
import logging
import threading
import time
from datetime import datetime, date
from enum import Enum
from typing import Dict, Any, Optional, List
from flask import Blueprint, request, jsonify
from .core import load_config, save_config, invalidate_config_cache, get_lifebook_path

logger = logging.getLogger(__name__)

# 创建蓝图
graphiti_bp = Blueprint('graphiti_api', __name__)

# ========== 全局状态 ==========

# Graphiti 适配器实例（延迟初始化）
_graphiti_adapter = None

# Token 使用量追踪器
_token_tracker: Optional['TokenUsageTracker'] = None


class TokenUsageTracker:
    """
    Token 使用量追踪器
    
    追踪每日 LLM Token 使用量，用于成本控制和预警
    """
    
    def __init__(self, daily_limit: int = 100000):
        self.daily_limit = daily_limit
        self._usage: Dict[str, Dict[str, int]] = {}  # date -> {operation: tokens}
    
    def record(self, tokens: int, operation: str = "unknown"):
        """记录 Token 使用"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self._usage:
            self._usage[today] = {}
        
        if operation not in self._usage[today]:
            self._usage[today][operation] = 0
        
        self._usage[today][operation] += tokens
        
        total = self.get_today_total()
        logger.debug(f"[Token] {operation}: +{tokens}, 今日累计: {total}")
        
        # 超限警告
        if total > self.daily_limit * 0.8:
            logger.warning(f"[Token] 今日用量已达 {total}/{self.daily_limit} (80%)")
    
    def get_today_total(self) -> int:
        """获取今日总使用量"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self._usage:
            return 0
        return sum(self._usage[today].values())
    
    def get_today_breakdown(self) -> Dict[str, int]:
        """获取今日分类使用量"""
        today = datetime.now().strftime("%Y-%m-%d")
        return self._usage.get(today, {}).copy()
    
    def can_proceed(self) -> bool:
        """检查是否可以继续（未超限）"""
        return self.get_today_total() < self.daily_limit
    
    def set_daily_limit(self, limit: int):
        """更新每日限额"""
        self.daily_limit = limit


# ========== 同步任务管理器 ==========

class SyncStatus(Enum):
    """同步状态枚举"""
    IDLE = "idle"           # 空闲
    RUNNING = "running"     # 运行中
    PAUSED = "paused"       # 已暂停
    STOPPING = "stopping"   # 正在停止
    COMPLETED = "completed" # 已完成
    FAILED = "failed"       # 失败


class SyncTaskManager:
    """
    同步任务管理器
    
    支持暂停/停止/继续同步操作
    """
    
    def __init__(self):
        self.status = SyncStatus.IDLE
        self.progress = {
            "current_file": "",
            "current_index": 0,
            "total_files": 0,
            "synced_diaries": 0,
            "synced_nodes": 0,
            "failed_files": [],
            "start_time": None,
            "end_time": None,
            "error": None
        }
        self._lock = threading.Lock()
        self._pause_event = threading.Event()
        self._pause_event.set()  # 初始为非暂停状态
        self._stop_flag = False
        self._thread: Optional[threading.Thread] = None
    
    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self.status in (SyncStatus.RUNNING, SyncStatus.PAUSED, SyncStatus.STOPPING)
    
    def start(self, adapter, lifebook_path: str, include_diaries: bool = True, include_nodes: bool = True) -> bool:
        """启动同步任务"""
        with self._lock:
            if self.is_running():
                logger.warning("[同步] 任务已在运行中，拒绝重复启动")
                return False
            
            self.status = SyncStatus.RUNNING
            self._stop_flag = False
            self._pause_event.set()
            self.progress = {
                "current_file": "",
                "current_index": 0,
                "total_files": 0,
                "synced_diaries": 0,
                "synced_nodes": 0,
                "failed_files": [],
                "start_time": datetime.now().isoformat(),
                "end_time": None,
                "error": None
            }
        
        logger.info("=" * 50)
        logger.info("[同步] 🚀 同步任务启动")
        logger.info(f"[同步] 📁 LifeBook 路径: {lifebook_path}")
        logger.info(f"[同步] 📅 同步日记: {'是' if include_diaries else '否'}")
        logger.info(f"[同步] 📦 同步节点: {'是' if include_nodes else '否'}")
        
        # 在后台线程执行同步
        self._thread = threading.Thread(
            target=self._sync_worker,
            args=(adapter, lifebook_path, include_diaries, include_nodes),
            daemon=True
        )
        self._thread.start()
        return True
    
    def pause(self) -> bool:
        """暂停同步"""
        with self._lock:
            if self.status != SyncStatus.RUNNING:
                return False
            self._pause_event.clear()
            self.status = SyncStatus.PAUSED
            logger.info("[同步] ⏸️  同步已暂停")
            return True
    
    def resume(self) -> bool:
        """继续同步"""
        with self._lock:
            if self.status != SyncStatus.PAUSED:
                return False
            self._pause_event.set()
            self.status = SyncStatus.RUNNING
            logger.info("[同步] ▶️  同步已继续")
            return True
    
    def stop(self) -> bool:
        """停止同步"""
        with self._lock:
            if not self.is_running():
                return False
            self._stop_flag = True
            self._pause_event.set()  # 解除暂停以便退出
            self.status = SyncStatus.STOPPING
            logger.info("[同步] ⏹️  正在停止同步...")
            return True
    
    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        with self._lock:
            return {
                "status": self.status.value,
                "is_running": self.is_running(),
                "can_pause": self.status == SyncStatus.RUNNING,
                "can_resume": self.status == SyncStatus.PAUSED,
                "can_stop": self.status in (SyncStatus.RUNNING, SyncStatus.PAUSED),
                **self.progress
            }
    
    def _sync_worker(self, adapter, lifebook_path: str, include_diaries: bool, include_nodes: bool):
        """同步工作线程"""
        import asyncio
        from pathlib import Path
        from memory_store.graphiti_adapter import EpisodeType
        
        try:
            # 收集要同步的文件
            files_to_sync = []
            
            if include_diaries:
                daily_dir = Path(lifebook_path) / "daily"
                if daily_dir.exists():
                    files_to_sync.extend([
                        ("diary", f) for f in sorted(daily_dir.glob("*.md"))
                    ])
            
            if include_nodes:
                nodes_dir = Path(lifebook_path) / "nodes"
                if nodes_dir.exists():
                    files_to_sync.extend([
                        ("node", f) for f in nodes_dir.glob("*.md")
                    ])
            
            with self._lock:
                self.progress["total_files"] = len(files_to_sync)
            
            logger.info(f"[同步] 📊 找到 {len(files_to_sync)} 个文件待同步")
            
            if not files_to_sync:
                logger.info("[同步] ✅ 没有文件需要同步")
                with self._lock:
                    self.status = SyncStatus.COMPLETED
                    self.progress["end_time"] = datetime.now().isoformat()
                return
            
            # 创建事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                for idx, (file_type, file_path) in enumerate(files_to_sync):
                    # 检查停止标志
                    if self._stop_flag:
                        logger.info(f"[同步] ⏹️  用户停止，已同步 {self.progress['synced_diaries']} 日记, {self.progress['synced_nodes']} 节点")
                        with self._lock:
                            self.status = SyncStatus.IDLE
                            self.progress["end_time"] = datetime.now().isoformat()
                        return
                    
                    # 等待暂停解除
                    self._pause_event.wait()
                    
                    # 再次检查停止标志
                    if self._stop_flag:
                        logger.info(f"[同步] ⏹️  用户停止，已同步 {self.progress['synced_diaries']} 日记, {self.progress['synced_nodes']} 节点")
                        with self._lock:
                            self.status = SyncStatus.IDLE
                            self.progress["end_time"] = datetime.now().isoformat()
                        return
                    
                    # 更新进度
                    with self._lock:
                        self.progress["current_file"] = file_path.name
                        self.progress["current_index"] = idx + 1
                    
                    # 打印进度（每10个文件或最后一个）
                    if (idx + 1) % 10 == 0 or idx == len(files_to_sync) - 1:
                        logger.info(f"[同步] 📝 进度: {idx + 1}/{len(files_to_sync)} - {file_path.name}")
                    
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        
                        if file_type == "diary":
                            date_str = file_path.stem
                            try:
                                timestamp = datetime.strptime(date_str, "%Y-%m-%d")
                            except ValueError:
                                timestamp = datetime.now()
                            
                            # 调用适配器的异步方法
                            loop.run_until_complete(
                                adapter._async_adapter.add_episode(
                                    content=content,
                                    source=f"diary:{date_str}",
                                    episode_type=EpisodeType.DIARY,
                                    timestamp=timestamp,
                                )
                            )
                            with self._lock:
                                self.progress["synced_diaries"] += 1
                        else:
                            loop.run_until_complete(
                                adapter._async_adapter.add_episode(
                                    content=content,
                                    source=f"node:{file_path.stem}",
                                    episode_type=EpisodeType.NODE,
                                )
                            )
                            with self._lock:
                                self.progress["synced_nodes"] += 1
                                    
                    except Exception as e:
                        logger.error(f"[同步] ❌ 同步文件失败 {file_path.name}: {e}")
                        with self._lock:
                            self.progress["failed_files"].append({
                                "file": file_path.name,
                                "error": str(e)
                            })
                
                # 循环结束，同步完成
                with self._lock:
                    self.status = SyncStatus.COMPLETED
                    self.progress["end_time"] = datetime.now().isoformat()
                
                logger.info("=" * 50)
                logger.info("[同步] ✅ 同步完成!")
                logger.info(f"[同步] 📅 日记: {self.progress['synced_diaries']} 个")
                logger.info(f"[同步] 📦 节点: {self.progress['synced_nodes']} 个")
                if self.progress['failed_files']:
                    logger.warning(f"[同步] ❌ 失败: {len(self.progress['failed_files'])} 个")
                logger.info("=" * 50)
                    
            finally:
                loop.close()
                
        except Exception as e:
            logger.error(f"[同步] ❌ 同步任务异常: {e}", exc_info=True)
            with self._lock:
                self.status = SyncStatus.FAILED
                self.progress["error"] = str(e)
                self.progress["end_time"] = datetime.now().isoformat()


# 全局同步任务管理器
_sync_manager: Optional[SyncTaskManager] = None


def get_sync_manager() -> SyncTaskManager:
    """获取同步任务管理器"""
    global _sync_manager
    if _sync_manager is None:
        _sync_manager = SyncTaskManager()
    return _sync_manager


def get_token_tracker() -> TokenUsageTracker:
    """获取或创建 Token 追踪器"""
    global _token_tracker
    if _token_tracker is None:
        config = load_config()
        graphiti_config = config.get("graphiti", {})
        perf_config = graphiti_config.get("performance", {})
        daily_limit = perf_config.get("daily_token_limit", 100000)
        _token_tracker = TokenUsageTracker(daily_limit)
    return _token_tracker


def get_graphiti_adapter():
    """
    获取 Graphiti 适配器实例（延迟初始化）
    
    如果 Graphiti 未启用或初始化失败，返回 None
    """
    global _graphiti_adapter
    
    config = load_config()
    graphiti_config = config.get("graphiti", {})
    
    if not graphiti_config.get("enabled", False):
        logger.debug("[Graphiti] 配置中 enabled=False，跳过初始化")
        return None
    
    if _graphiti_adapter is not None:
        return _graphiti_adapter
    
    # 尝试初始化
    try:
        from memory_store.graphiti_adapter import GraphitiSyncAdapter
        lifebook_path = get_lifebook_path()
        logger.info(f"[Graphiti] 正在初始化适配器...")
        # 注意：传递完整配置，因为 GraphitiConfig.from_dict 期望 config["graphiti"] 格式
        _graphiti_adapter = GraphitiSyncAdapter(config, lifebook_path)
        _graphiti_adapter.initialize()
        logger.info("[Graphiti] ✅ 适配器初始化成功")
        return _graphiti_adapter
    except ImportError as e:
        logger.warning(f"[Graphiti] ⚠️ 模块未安装: {e}")
        return None
    except Exception as e:
        logger.error(f"[Graphiti] ❌ 初始化失败: {e}", exc_info=True)
        return None


def invalidate_graphiti_adapter():
    """使 Graphiti 适配器失效（配置更改时调用）"""
    global _graphiti_adapter
    if _graphiti_adapter is not None:
        try:
            _graphiti_adapter.close()
        except Exception:
            pass
        _graphiti_adapter = None


# ========== 配置 API ==========

@graphiti_bp.route('/graphiti/config', methods=['GET'])
def get_graphiti_config():
    """获取 Graphiti 配置"""
    try:
        config = load_config()
        graphiti_config = config.get("graphiti", get_default_graphiti_config())
        
        # 安全处理：隐藏敏感信息
        safe_config = _mask_sensitive_config(graphiti_config)
        
        return jsonify(safe_config)
    except Exception as e:
        logger.error(f"获取 Graphiti 配置失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/config', methods=['POST'])
def save_graphiti_config():
    """保存 Graphiti 配置"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "配置数据为空"}), 400
        
        config = load_config()
        
        # 如果没有 graphiti 配置，使用默认值
        if "graphiti" not in config:
            config["graphiti"] = get_default_graphiti_config()
        
        # 深度合并配置
        _deep_merge(config["graphiti"], data)
        
        save_config(config)
        invalidate_config_cache()
        
        # 如果启用状态变化，重新初始化适配器
        invalidate_graphiti_adapter()
        
        logger.info("[Graphiti] ✅ 配置已保存")
        
        return jsonify({
            "success": True,
            "message": "Graphiti 配置已保存"
        })
    except Exception as e:
        logger.error(f"保存 Graphiti 配置失败: {e}")
        return jsonify({"error": str(e)}), 500


# ========== 状态 API ==========

@graphiti_bp.route('/graphiti/stats', methods=['GET'])
def get_graphiti_stats():
    """获取 Graphiti 状态和统计信息"""
    try:
        config = load_config()
        graphiti_config = config.get("graphiti", {})
        
        # 基础信息
        stats = {
            "enabled": graphiti_config.get("enabled", False),
            "backend": graphiti_config.get("backend", "kuzu"),
            "status": "disabled"
        }
        
        if not stats["enabled"]:
            return jsonify(stats)
        
        # 尝试获取适配器状态
        adapter = get_graphiti_adapter()
        if adapter is None:
            stats["status"] = "unavailable"
            stats["error"] = "适配器初始化失败或模块未安装"
            return jsonify(stats)
        
        stats["status"] = "running"
        
        # 尝试获取图谱统计
        try:
            # 这些是占位符，实际实现需要 Graphiti 适配器提供
            # TODO: 当 GraphitiAdapter 实现后，调用真实方法
            stats["entity_count"] = 0
            stats["edge_count"] = 0
            stats["episode_count"] = 0
            
            # 检查 Kuzu 数据库目录
            lifebook_path = get_lifebook_path()
            if lifebook_path:
                kuzu_path = graphiti_config.get("kuzu", {}).get(
                    "db_path",
                    os.path.join(lifebook_path, ".graphiti.kuzu")
                )
                if os.path.exists(kuzu_path):
                    stats["kuzu_db_exists"] = True
                    stats["kuzu_db_size"] = _get_dir_size(kuzu_path)
                else:
                    stats["kuzu_db_exists"] = False
        except Exception as e:
            logger.warning(f"获取图谱统计失败: {e}")
        
        return jsonify(stats)
    except Exception as e:
        logger.error(f"获取 Graphiti 状态失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/token-usage', methods=['GET'])
def get_token_usage():
    """获取今日 Token 使用量"""
    try:
        tracker = get_token_tracker()
        
        config = load_config()
        graphiti_config = config.get("graphiti", {})
        perf_config = graphiti_config.get("performance", {})
        daily_limit = perf_config.get("daily_token_limit", 100000)
        
        # 同步更新限额
        tracker.set_daily_limit(daily_limit)
        
        used = tracker.get_today_total()
        breakdown = tracker.get_today_breakdown()
        
        return jsonify({
            "used": used,
            "limit": daily_limit,
            "remaining": max(0, daily_limit - used),
            "percent": round(used / daily_limit * 100, 1) if daily_limit > 0 else 0,
            "breakdown": breakdown,
            "can_proceed": tracker.can_proceed()
        })
    except Exception as e:
        logger.error(f"获取 Token 使用量失败: {e}")
        return jsonify({"error": str(e)}), 500


# ========== 同步 API ==========

@graphiti_bp.route('/graphiti/sync', methods=['POST'])
def sync_to_graphiti():
    """
    从 Markdown 同步到 Graphiti（后台任务）
    
    请求体参数：
    - include_diaries: bool (默认 True) - 是否同步日记
    - include_nodes: bool (默认 True) - 是否同步节点
    """
    try:
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用"}), 500
        
        sync_manager = get_sync_manager()
        
        # 检查是否已有任务在运行
        if sync_manager.is_running():
            return jsonify({
                "error": "同步任务正在进行中",
                "status": sync_manager.get_status()
            }), 409
        
        # 获取参数
        data = request.get_json() or {}
        include_diaries = data.get("include_diaries", True)
        include_nodes = data.get("include_nodes", True)
        
        lifebook_path = get_lifebook_path()
        if not lifebook_path:
            return jsonify({"error": "LifeBook 路径未配置"}), 500
        
        # 启动后台同步
        success = sync_manager.start(
            adapter=adapter,
            lifebook_path=lifebook_path,
            include_diaries=include_diaries,
            include_nodes=include_nodes
        )
        
        if success:
            logger.info("[API] POST /graphiti/sync -> 同步任务已启动")
            return jsonify({
                "success": True,
                "message": "同步任务已启动",
                "status": sync_manager.get_status()
            })
        else:
            logger.error("[API] POST /graphiti/sync -> 启动失败")
            return jsonify({"error": "启动同步任务失败"}), 500
            
    except Exception as e:
        logger.error(f"同步到 Graphiti 失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/sync/status', methods=['GET'])
def get_sync_status():
    """获取同步任务状态"""
    try:
        sync_manager = get_sync_manager()
        return jsonify(sync_manager.get_status())
    except Exception as e:
        logger.error(f"获取同步状态失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/sync/pause', methods=['POST'])
def pause_sync():
    """暂停同步任务"""
    try:
        sync_manager = get_sync_manager()
        if sync_manager.pause():
            return jsonify({
                "success": True,
                "message": "同步任务已暂停",
                "status": sync_manager.get_status()
            })
        else:
            return jsonify({
                "error": "无法暂停：当前状态不允许暂停",
                "status": sync_manager.get_status()
            }), 400
    except Exception as e:
        logger.error(f"暂停同步失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/sync/resume', methods=['POST'])
def resume_sync():
    """继续同步任务"""
    try:
        sync_manager = get_sync_manager()
        if sync_manager.resume():
            return jsonify({
                "success": True,
                "message": "同步任务已继续",
                "status": sync_manager.get_status()
            })
        else:
            return jsonify({
                "error": "无法继续：当前状态不允许继续",
                "status": sync_manager.get_status()
            }), 400
    except Exception as e:
        logger.error(f"继续同步失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/sync/stop', methods=['POST'])
def stop_sync():
    """停止同步任务"""
    try:
        sync_manager = get_sync_manager()
        if sync_manager.stop():
            return jsonify({
                "success": True,
                "message": "同步任务正在停止",
                "status": sync_manager.get_status()
            })
        else:
            return jsonify({
                "error": "无法停止：当前没有运行中的任务",
                "status": sync_manager.get_status()
            }), 400
    except Exception as e:
        logger.error(f"停止同步失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/rebuild', methods=['POST'])
def rebuild_graphiti_index():
    """重建 Graphiti 索引（清空并重新构建，使用后台任务支持暂停/停止）"""
    try:
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        # 确认操作
        data = request.get_json() or {}
        if not data.get("confirm", False):
            return jsonify({
                "error": "需要确认操作",
                "message": "请在请求中包含 confirm: true 以确认重建索引"
            }), 400
        
        sync_manager = get_sync_manager()
        
        # 检查是否已有任务在运行
        if sync_manager.is_running():
            return jsonify({
                "error": "已有同步任务在运行中",
                "status": sync_manager.get_status()
            }), 409
        
        # 1. 关闭现有连接
        invalidate_graphiti_adapter()
        
        # 2. 删除现有数据库
        lifebook_path = get_lifebook_path()
        if lifebook_path:
            kuzu_path = config.get("graphiti", {}).get("kuzu", {}).get(
                "db_path",
                os.path.join(lifebook_path, ".graphiti.kuzu")
            )
            if os.path.exists(kuzu_path):
                import shutil
                if os.path.isdir(kuzu_path):
                    shutil.rmtree(kuzu_path)
                else:
                    os.remove(kuzu_path)
                logger.info(f"[重建] 🗑️ 已删除 Kuzu 数据库: {kuzu_path}")
        
        # 3. 重新初始化适配器并启动后台同步
        adapter = get_graphiti_adapter()
        if adapter:
            # 使用 SyncTaskManager 支持暂停/停止
            success = sync_manager.start(
                adapter=adapter,
                lifebook_path=lifebook_path,
                include_diaries=True,
                include_nodes=True
            )
            
            if success:
                logger.info("[重建] 🚀 索引已清空，后台同步任务已启动")
                return jsonify({
                    "success": True,
                    "message": "索引已清空，后台同步任务已启动",
                    "status": sync_manager.get_status()
                })
            else:
                return jsonify({"error": "启动同步任务失败"}), 500
        
        logger.info("[重建] ✅ 索引已清空，适配器不可用")
        return jsonify({
            "success": True,
            "message": "索引已清空，Graphiti 适配器不可用"
        })
        
    except Exception as e:
        logger.error(f"重建 Graphiti 索引失败: {e}")
        return jsonify({"error": str(e)}), 500


# ========== 简单节点同步（无 LLM）API ==========

@graphiti_bp.route('/graphiti/sync-nodes-simple', methods=['POST'])
def sync_nodes_simple():
    """
    一键同步已有节点（不使用 LLM）
    
    直接从 LifeBook nodes/*.md 读取节点并创建到 Graphiti，
    不进行 LLM 抽取，速度快且无 Token 消耗。
    """
    try:
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用"}), 500
        
        lifebook_path = get_lifebook_path()
        if not lifebook_path:
            return jsonify({"error": "LifeBook 路径未配置"}), 500
        
        from pathlib import Path
        import asyncio
        import re
        from graphiti_core.nodes import EntityNode
        from datetime import datetime
        
        nodes_dir = Path(lifebook_path) / "nodes"
        if not nodes_dir.exists():
            return jsonify({"error": "nodes 目录不存在", "synced_count": 0})
        
        # 获取所有节点文件
        node_files = list(nodes_dir.glob("*.md"))
        if not node_files:
            return jsonify({"success": True, "message": "没有节点文件", "synced_count": 0})
        
        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        synced_count = 0
        failed_files = []
        
        try:
            driver = adapter._async_adapter._driver
            embedder = adapter._async_adapter._embedder
            
            # 获取 group_id
            graphiti_config = config.get("graphiti", {})
            group_id = graphiti_config.get("group_id", {}).get("default", "lifebook")
            
            for node_file in node_files:
                try:
                    content = node_file.read_text(encoding="utf-8")
                    
                    # 从文件名获取节点名称
                    node_name = node_file.stem
                    
                    # 尝试从 YAML frontmatter 提取更多信息
                    labels = []
                    summary = content
                    
                    # 解析 YAML frontmatter
                    if content.startswith("---"):
                        parts = content.split("---", 2)
                        if len(parts) >= 3:
                            frontmatter = parts[1].strip()
                            body = parts[2].strip()
                            
                            # 提取 type/tags 作为 labels
                            for line in frontmatter.split("\n"):
                                if line.startswith("type:"):
                                    type_val = line.split(":", 1)[1].strip().strip('"\'')
                                    if type_val:
                                        labels.append(type_val)
                                elif line.startswith("tags:"):
                                    # tags 可能是列表格式
                                    tags_str = line.split(":", 1)[1].strip()
                                    if tags_str.startswith("["):
                                        # [tag1, tag2] 格式
                                        tags = re.findall(r'[\w\u4e00-\u9fff]+', tags_str)
                                        labels.extend(tags)
                            
                            # 使用 body 作为 summary
                            summary = body[:500] if len(body) > 500 else body
                    else:
                        # 没有 frontmatter，使用内容前 500 字符
                        summary = content[:500] if len(content) > 500 else content
                    
                    # 检查是否已存在同名节点
                    existing = None
                    try:
                        existing_nodes = loop.run_until_complete(
                            EntityNode.get_by_group_ids(driver, [group_id], limit=1000)
                        )
                        for n in existing_nodes:
                            if n.name == node_name:
                                existing = n
                                break
                    except Exception:
                        pass
                    
                    if existing:
                        # 更新现有节点
                        existing.summary = summary
                        if labels:
                            existing.labels = list(set(existing.labels + labels))
                        loop.run_until_complete(existing.save(driver))
                        logger.debug(f"[同步节点] 更新: {node_name}")
                    else:
                        # 创建新节点
                        node = EntityNode(
                            name=node_name,
                            summary=summary,
                            labels=labels if labels else ["节点"],
                            group_id=group_id,
                            created_at=datetime.now(),
                        )
                        
                        # 生成 embedding
                        loop.run_until_complete(node.generate_name_embedding(embedder))
                        
                        # 保存
                        loop.run_until_complete(node.save(driver))
                        logger.debug(f"[同步节点] 创建: {node_name}")
                    
                    synced_count += 1
                    
                except Exception as e:
                    logger.error(f"[同步节点] 失败 {node_file.name}: {e}")
                    failed_files.append({"file": node_file.name, "error": str(e)})
        finally:
            loop.close()
        
        logger.info(f"[同步节点] 完成：{synced_count} 个节点，{len(failed_files)} 个失败")
        
        return jsonify({
            "success": True,
            "message": f"同步完成：{synced_count} 个节点",
            "synced_count": synced_count,
            "failed_count": len(failed_files),
            "failed_files": failed_files[:10]  # 只返回前 10 个失败
        })
        
    except Exception as e:
        logger.error(f"简单节点同步失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ========== 图谱可视化 API ==========

@graphiti_bp.route('/graphiti/graph-data', methods=['GET'])
def get_graph_data():
    """获取图谱可视化数据"""
    try:
        limit = request.args.get("limit", 100, type=int)
        
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用", "nodes": [], "edges": []})
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用", "nodes": [], "edges": []})
        
        # 获取图谱数据
        try:
            # 尝试调用适配器的 get_graph_data 方法
            if hasattr(adapter, 'get_graph_data'):
                data = adapter.get_graph_data(limit=limit)
                return jsonify({
                    "success": True,
                    "nodes": data.get("nodes", []),
                    "edges": data.get("edges", []),
                    "node_count": len(data.get("nodes", [])),
                    "edge_count": len(data.get("edges", []))
                })
            else:
                # 如果适配器没有该方法，尝试直接查询
                nodes = []
                edges = []
                
                # 尝试获取所有实体节点
                if hasattr(adapter, 'graphiti') and adapter.graphiti:
                    try:
                        import asyncio
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        # 使用搜索获取一些节点
                        search_result = loop.run_until_complete(
                            adapter.graphiti.search(
                                query="*",
                                num_results=limit
                            )
                        )
                        
                        # 解析搜索结果
                        seen_nodes = set()
                        for r in search_result:
                            # 添加节点
                            if hasattr(r, 'source_node') and r.source_node:
                                node = r.source_node
                                if node.uuid not in seen_nodes:
                                    seen_nodes.add(node.uuid)
                                    nodes.append({
                                        "uuid": node.uuid,
                                        "name": node.name,
                                        "type": getattr(node, 'label_type', 'Entity'),
                                        "summary": getattr(node, 'summary', '')
                                    })
                            
                            if hasattr(r, 'target_node') and r.target_node:
                                node = r.target_node
                                if node.uuid not in seen_nodes:
                                    seen_nodes.add(node.uuid)
                                    nodes.append({
                                        "uuid": node.uuid,
                                        "name": node.name,
                                        "type": getattr(node, 'label_type', 'Entity'),
                                        "summary": getattr(node, 'summary', '')
                                    })
                            
                            # 添加边
                            if hasattr(r, 'uuid'):
                                edges.append({
                                    "uuid": r.uuid,
                                    "source_uuid": getattr(r, 'source_node_uuid', ''),
                                    "target_uuid": getattr(r, 'target_node_uuid', ''),
                                    "name": getattr(r, 'name', ''),
                                    "fact": getattr(r, 'fact', '')
                                })
                        
                        loop.close()
                    except Exception as e:
                        logger.warning(f"获取图谱数据失败: {e}")
                
                return jsonify({
                    "success": True,
                    "nodes": nodes,
                    "edges": edges,
                    "node_count": len(nodes),
                    "edge_count": len(edges)
                })
                
        except Exception as e:
            logger.error(f"获取图谱数据失败: {e}")
            return jsonify({"error": str(e), "nodes": [], "edges": []})
        
    except Exception as e:
        logger.error(f"获取图谱可视化数据失败: {e}")
        return jsonify({"error": str(e), "nodes": [], "edges": []}), 500


# ========== 搜索测试 API ==========

@graphiti_bp.route('/graphiti/search', methods=['POST'])
def graphiti_search():
    """测试 Graphiti 搜索"""
    try:
        data = request.get_json()
        query = data.get("query", "")
        num_results = data.get("num_results", 10)
        
        if not query:
            return jsonify({"error": "查询不能为空"}), 400
        
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用"}), 500
        
        raw_results = adapter.search(query, num_results=num_results)
        
        # 将 SearchResult 对象转换为前端期望的字典格式
        results = []
        for r in raw_results:
            result_dict = {
                "uuid": getattr(r, 'uuid', ''),
                "content": getattr(r, 'content', ''),
                "score": getattr(r, 'score', 1.0),
                "source": getattr(r, 'source', ''),
                "type": getattr(r, 'result_type', 'edge'),  # 前端用 type，后端用 result_type
                "valid_at": r.valid_at.isoformat() if getattr(r, 'valid_at', None) else None,
                "invalid_at": r.invalid_at.isoformat() if getattr(r, 'invalid_at', None) else None,
            }
            # 合并 metadata
            if hasattr(r, 'metadata') and r.metadata:
                result_dict.update(r.metadata)
            results.append(result_dict)
        
        return jsonify({
            "success": True,
            "query": query,
            "results": results,
            "count": len(results)
        })
        
    except Exception as e:
        logger.error(f"Graphiti 搜索失败: {e}")
        return jsonify({"error": str(e)}), 500


# ========== 对话保留 API ==========

@graphiti_bp.route('/graphiti/conversation-logger/config', methods=['GET'])
def get_conversation_logger_config():
    """获取对话保留配置"""
    try:
        config = load_config()
        conv_config = config.get("conversation_logger", get_default_conversation_logger_config())
        return jsonify(conv_config)
    except Exception as e:
        logger.error(f"获取对话保留配置失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/conversation-logger/config', methods=['POST'])
def save_conversation_logger_config():
    """保存对话保留配置"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "配置数据为空"}), 400
        
        config = load_config()
        
        if "conversation_logger" not in config:
            config["conversation_logger"] = get_default_conversation_logger_config()
        
        _deep_merge(config["conversation_logger"], data)
        
        save_config(config)
        invalidate_config_cache()
        
        return jsonify({
            "success": True,
            "message": "对话保留配置已保存"
        })
    except Exception as e:
        logger.error(f"保存对话保留配置失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/conversations', methods=['GET'])
def list_conversations():
    """列出最近的对话记录"""
    try:
        days = request.args.get("days", 7, type=int)
        
        lifebook_path = get_lifebook_path()
        if not lifebook_path:
            return jsonify({"error": "LifeBook 路径未配置"}), 500
        
        conv_dir = os.path.join(lifebook_path, "conversations")
        if not os.path.exists(conv_dir):
            return jsonify({"conversations": [], "total": 0})
        
        import json
        from datetime import timedelta
        
        cutoff = datetime.now() - timedelta(days=days)
        conversations = []
        
        for filename in sorted(os.listdir(conv_dir), reverse=True):
            if not filename.endswith(".jsonl"):
                continue
            
            filepath = os.path.join(conv_dir, filename)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime < cutoff:
                    continue
                
                # 读取文件头
                header = None
                footer = None
                turn_count = 0
                
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            record = json.loads(line)
                            if record.get("type") == "header":
                                header = record
                            elif record.get("type") == "footer":
                                footer = record
                            elif record.get("type") == "turn":
                                turn_count += 1
                        except json.JSONDecodeError:
                            continue
                
                conversations.append({
                    "session_id": filename.replace(".jsonl", ""),
                    "filename": filename,
                    "start_time": header.get("start_time") if header else None,
                    "end_time": footer.get("end_time") if footer else None,
                    "turn_count": turn_count,
                    "model": header.get("model") if header else None,
                    "file_size": os.path.getsize(filepath)
                })
                
            except Exception as e:
                logger.warning(f"读取对话文件 {filename} 失败: {e}")
                continue
        
        return jsonify({
            "conversations": conversations,
            "total": len(conversations)
        })
        
    except Exception as e:
        logger.error(f"列出对话记录失败: {e}")
        return jsonify({"error": str(e)}), 500


# ========== 辅助函数 ==========

def get_default_graphiti_config() -> Dict[str, Any]:
    """获取默认 Graphiti 配置"""
    return {
        "enabled": False,
        "backend": "kuzu",
        "kuzu": {
            "db_path": "./lifebook/.graphiti.kuzu"
        },
        "neo4j": {
            "uri": "bolt://localhost:7687",
            "username": "neo4j",
            "password": "",
            "database": "lifebook"
        },
        "llm": {
            "base_url": None,
            "api_key": "",
            "model": "gpt-4o-mini",
            "small_model": "gpt-4o-mini"
        },
        "embedding": {
            "base_url": None,
            "api_key": "",
            "model": "text-embedding-3-small",
            "dim": 1536
        },
        "reranker": {
            "enabled": True,
            "model": "gpt-4o-mini"
        },
        "search": {
            "edge_methods": ["cosine_similarity", "bm25"],
            "node_methods": ["cosine_similarity", "bm25"],
            "edge_reranker": "cross_encoder",
            "node_reranker": "rrf",
            "sim_min_score": 0.4,
            "mmr_lambda": 0.5,
            "reranker_min_score": 0.3
        },
        "group_id": {
            "strategy": "single",
            "default": "lifebook"
        },
        "retrieval": {
            "strategy": "auto",
            "max_iterations": 3,
            "min_evidence_count": 2,
            "default_limit": 10,
            "include_edges": True,
            "include_nodes": True
        },
        "performance": {
            "semaphore_limit": 10,
            "daily_token_limit": 100000,
            "retry_on_rate_limit": True,
            "max_retries": 3
        },
        "sync": {
            "mode": "dual_write",
            "index_conversations": True
        }
    }


def get_default_conversation_logger_config() -> Dict[str, Any]:
    """获取默认对话保留配置"""
    return {
        "enabled": True,
        "session_timeout_minutes": 30,
        "prefix_match_threshold": 0.7,
        "max_turns_per_file": 100,
        "index_to_graphiti": True
    }


def _mask_sensitive_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    处理敏感配置信息
    
    注意：API Key 不再遮蔽，直接返回原值，方便用户查看和复制
    只有 Neo4j 密码保持遮蔽
    """
    import copy
    safe = copy.deepcopy(config)
    
    # Neo4j 密码保持遮蔽
    if "neo4j" in safe and "password" in safe["neo4j"]:
        if safe["neo4j"]["password"]:
            safe["neo4j"]["password"] = "***"
    
    # LLM API Key 和 Embedding API Key 不再遮蔽，原样返回
    
    return safe


def _deep_merge(base: Dict, updates: Dict) -> Dict:
    """深度合并字典"""
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _get_dir_size(path: str) -> int:
    """获取文件或目录大小（字节）"""
    if os.path.isfile(path):
        return os.path.getsize(path)
    
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total += os.path.getsize(fp)
    return total


# ========== 节点 CRUD API ==========

@graphiti_bp.route('/graphiti/nodes/<uuid>', methods=['GET'])
def get_graphiti_node(uuid: str):
    """获取 Graphiti 节点详情"""
    try:
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用"}), 500
        
        import asyncio
        from graphiti_core.nodes import EntityNode
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            driver = adapter._async_adapter._driver
            node = loop.run_until_complete(EntityNode.get_by_uuid(driver, uuid))
            
            # 同时获取相关的边
            from graphiti_core.edges import EntityEdge
            edges = loop.run_until_complete(EntityEdge.get_by_node_uuid(driver, uuid))
            
            return jsonify({
                "success": True,
                "node": {
                    "uuid": node.uuid,
                    "name": node.name,
                    "summary": node.summary,
                    "labels": node.labels,
                    "group_id": node.group_id,
                    "created_at": node.created_at.isoformat() if node.created_at else None,
                    "attributes": node.attributes,
                },
                "edges": [
                    {
                        "uuid": e.uuid,
                        "name": e.name,
                        "fact": e.fact,
                        "source_node_uuid": e.source_node_uuid,
                        "target_node_uuid": e.target_node_uuid,
                        "valid_at": e.valid_at.isoformat() if e.valid_at else None,
                        "invalid_at": e.invalid_at.isoformat() if e.invalid_at else None,
                    }
                    for e in edges
                ],
                "edge_count": len(edges),
            })
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"获取节点失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/nodes/<uuid>', methods=['PUT'])
def update_graphiti_node(uuid: str):
    """更新 Graphiti 节点"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求数据为空"}), 400
        
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用"}), 500
        
        import asyncio
        from graphiti_core.nodes import EntityNode
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            driver = adapter._async_adapter._driver
            embedder = adapter._async_adapter._embedder
            
            # 获取现有节点
            node = loop.run_until_complete(EntityNode.get_by_uuid(driver, uuid))
            
            # 更新字段
            if "name" in data:
                node.name = data["name"]
                # 重新生成 embedding
                loop.run_until_complete(node.generate_name_embedding(embedder))
            if "summary" in data:
                node.summary = data["summary"]
            if "labels" in data:
                node.labels = data["labels"]
            if "attributes" in data:
                node.attributes = data["attributes"]
            
            # 保存
            loop.run_until_complete(node.save(driver))
            
            logger.info(f"[Graphiti] 节点已更新: {uuid}")
            
            return jsonify({
                "success": True,
                "message": "节点更新成功",
                "node": {
                    "uuid": node.uuid,
                    "name": node.name,
                    "summary": node.summary,
                    "labels": node.labels,
                }
            })
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"更新节点失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/nodes/<uuid>', methods=['DELETE'])
def delete_graphiti_node(uuid: str):
    """删除 Graphiti 节点"""
    try:
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用"}), 500
        
        import asyncio
        from graphiti_core.nodes import EntityNode
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            driver = adapter._async_adapter._driver
            
            # 获取节点
            node = loop.run_until_complete(EntityNode.get_by_uuid(driver, uuid))
            
            # 删除节点（会自动删除相关边）
            loop.run_until_complete(node.delete(driver))
            
            logger.info(f"[Graphiti] 节点已删除: {uuid}")
            
            return jsonify({
                "success": True,
                "message": "节点删除成功",
            })
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"删除节点失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/nodes', methods=['POST'])
def create_graphiti_node():
    """创建 Graphiti 节点"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求数据为空"}), 400
        
        name = data.get("name")
        if not name:
            return jsonify({"error": "节点名称不能为空"}), 400
        
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用"}), 500
        
        import asyncio
        from graphiti_core.nodes import EntityNode
        from datetime import datetime
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            driver = adapter._async_adapter._driver
            embedder = adapter._async_adapter._embedder
            
            # 获取 group_id
            graphiti_config = config.get("graphiti", {})
            group_id = graphiti_config.get("group_id", {}).get("default", "lifebook")
            
            # 创建节点
            node = EntityNode(
                name=name,
                summary=data.get("summary", ""),
                labels=data.get("labels", []),
                group_id=group_id,
                attributes=data.get("attributes", {}),
                created_at=datetime.now(),
            )
            
            # 生成 embedding
            loop.run_until_complete(node.generate_name_embedding(embedder))
            
            # 保存
            loop.run_until_complete(node.save(driver))
            
            logger.info(f"[Graphiti] 节点已创建: {node.uuid}")
            
            return jsonify({
                "success": True,
                "message": "节点创建成功",
                "node": {
                    "uuid": node.uuid,
                    "name": node.name,
                    "summary": node.summary,
                    "labels": node.labels,
                }
            })
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"创建节点失败: {e}")
        return jsonify({"error": str(e)}), 500


# ========== 边 CRUD API ==========

@graphiti_bp.route('/graphiti/edges/<uuid>', methods=['GET'])
def get_graphiti_edge(uuid: str):
    """获取 Graphiti 边详情"""
    try:
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用"}), 500
        
        import asyncio
        from graphiti_core.edges import EntityEdge
        from graphiti_core.nodes import EntityNode
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            driver = adapter._async_adapter._driver
            edge = loop.run_until_complete(EntityEdge.get_by_uuid(driver, uuid))
            
            # 获取源节点和目标节点信息
            source_node = None
            target_node = None
            try:
                source_node = loop.run_until_complete(EntityNode.get_by_uuid(driver, edge.source_node_uuid))
            except Exception:
                pass
            try:
                target_node = loop.run_until_complete(EntityNode.get_by_uuid(driver, edge.target_node_uuid))
            except Exception:
                pass
            
            return jsonify({
                "success": True,
                "edge": {
                    "uuid": edge.uuid,
                    "name": edge.name,
                    "fact": edge.fact,
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                    "group_id": edge.group_id,
                    "episodes": edge.episodes,
                    "created_at": edge.created_at.isoformat() if edge.created_at else None,
                    "valid_at": edge.valid_at.isoformat() if edge.valid_at else None,
                    "invalid_at": edge.invalid_at.isoformat() if edge.invalid_at else None,
                    "expired_at": edge.expired_at.isoformat() if edge.expired_at else None,
                    "attributes": edge.attributes,
                },
                "source_node": {
                    "uuid": source_node.uuid,
                    "name": source_node.name,
                } if source_node else None,
                "target_node": {
                    "uuid": target_node.uuid,
                    "name": target_node.name,
                } if target_node else None,
            })
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"获取边失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/edges/<uuid>', methods=['PUT'])
def update_graphiti_edge(uuid: str):
    """更新 Graphiti 边"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求数据为空"}), 400
        
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用"}), 500
        
        import asyncio
        from graphiti_core.edges import EntityEdge
        from datetime import datetime
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            driver = adapter._async_adapter._driver
            embedder = adapter._async_adapter._embedder
            
            # 获取现有边
            edge = loop.run_until_complete(EntityEdge.get_by_uuid(driver, uuid))
            
            # 更新字段
            if "name" in data:
                edge.name = data["name"]
            if "fact" in data:
                edge.fact = data["fact"]
                # 重新生成 embedding
                loop.run_until_complete(edge.generate_embedding(embedder))
            if "valid_at" in data:
                edge.valid_at = datetime.fromisoformat(data["valid_at"]) if data["valid_at"] else None
            if "invalid_at" in data:
                edge.invalid_at = datetime.fromisoformat(data["invalid_at"]) if data["invalid_at"] else None
            if "attributes" in data:
                edge.attributes = data["attributes"]
            
            # 保存
            loop.run_until_complete(edge.save(driver))
            
            logger.info(f"[Graphiti] 边已更新: {uuid}")
            
            return jsonify({
                "success": True,
                "message": "边更新成功",
                "edge": {
                    "uuid": edge.uuid,
                    "name": edge.name,
                    "fact": edge.fact,
                }
            })
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"更新边失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/edges/<uuid>', methods=['DELETE'])
def delete_graphiti_edge(uuid: str):
    """删除 Graphiti 边"""
    try:
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用"}), 500
        
        import asyncio
        from graphiti_core.edges import EntityEdge
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            driver = adapter._async_adapter._driver
            
            # 获取边
            edge = loop.run_until_complete(EntityEdge.get_by_uuid(driver, uuid))
            
            # 删除边
            loop.run_until_complete(edge.delete(driver))
            
            logger.info(f"[Graphiti] 边已删除: {uuid}")
            
            return jsonify({
                "success": True,
                "message": "边删除成功",
            })
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"删除边失败: {e}")
        return jsonify({"error": str(e)}), 500


@graphiti_bp.route('/graphiti/edges', methods=['POST'])
def create_graphiti_edge():
    """创建 Graphiti 边"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求数据为空"}), 400
        
        source_node_uuid = data.get("source_node_uuid")
        target_node_uuid = data.get("target_node_uuid")
        name = data.get("name")
        fact = data.get("fact")
        
        if not all([source_node_uuid, target_node_uuid, name, fact]):
            return jsonify({"error": "缺少必要字段: source_node_uuid, target_node_uuid, name, fact"}), 400
        
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用"}), 400
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用"}), 500
        
        import asyncio
        from graphiti_core.edges import EntityEdge
        from graphiti_core.nodes import EntityNode
        from datetime import datetime
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            driver = adapter._async_adapter._driver
            embedder = adapter._async_adapter._embedder
            
            # 验证源节点和目标节点存在
            try:
                loop.run_until_complete(EntityNode.get_by_uuid(driver, source_node_uuid))
            except Exception:
                return jsonify({"error": f"源节点不存在: {source_node_uuid}"}), 400
            
            try:
                loop.run_until_complete(EntityNode.get_by_uuid(driver, target_node_uuid))
            except Exception:
                return jsonify({"error": f"目标节点不存在: {target_node_uuid}"}), 400
            
            # 获取 group_id
            graphiti_config = config.get("graphiti", {})
            group_id = graphiti_config.get("group_id", {}).get("default", "lifebook")
            
            # 解析时间
            valid_at = None
            invalid_at = None
            if data.get("valid_at"):
                valid_at = datetime.fromisoformat(data["valid_at"])
            if data.get("invalid_at"):
                invalid_at = datetime.fromisoformat(data["invalid_at"])
            
            # 创建边
            edge = EntityEdge(
                name=name,
                fact=fact,
                source_node_uuid=source_node_uuid,
                target_node_uuid=target_node_uuid,
                group_id=group_id,
                created_at=datetime.now(),
                valid_at=valid_at,
                invalid_at=invalid_at,
                episodes=[],
                attributes=data.get("attributes", {}),
            )
            
            # 生成 embedding
            loop.run_until_complete(edge.generate_embedding(embedder))
            
            # 保存
            loop.run_until_complete(edge.save(driver))
            
            logger.info(f"[Graphiti] 边已创建: {edge.uuid}")
            
            return jsonify({
                "success": True,
                "message": "边创建成功",
                "edge": {
                    "uuid": edge.uuid,
                    "name": edge.name,
                    "fact": edge.fact,
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                }
            })
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"创建边失败: {e}")
        return jsonify({"error": str(e)}), 500


# ========== 节点列表 API ==========

@graphiti_bp.route('/graphiti/nodes', methods=['GET'])
def list_graphiti_nodes():
    """获取 Graphiti 节点列表"""
    try:
        limit = request.args.get("limit", 50, type=int)
        
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用", "nodes": []})
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用", "nodes": []})
        
        import asyncio
        from graphiti_core.nodes import EntityNode
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            driver = adapter._async_adapter._driver
            
            # 获取 group_id
            graphiti_config = config.get("graphiti", {})
            group_id = graphiti_config.get("group_id", {}).get("default", "lifebook")
            
            try:
                nodes = loop.run_until_complete(
                    EntityNode.get_by_group_ids(driver, [group_id], limit=limit)
                )
            except Exception:
                nodes = []
            
            return jsonify({
                "success": True,
                "nodes": [
                    {
                        "uuid": n.uuid,
                        "name": n.name,
                        "summary": n.summary,
                        "labels": n.labels,
                        "group_id": n.group_id,
                        "created_at": n.created_at.isoformat() if n.created_at else None,
                    }
                    for n in nodes
                ],
                "count": len(nodes),
            })
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"获取节点列表失败: {e}")
        return jsonify({"error": str(e), "nodes": []}), 500


@graphiti_bp.route('/graphiti/edges', methods=['GET'])
def list_graphiti_edges():
    """获取 Graphiti 边列表"""
    try:
        limit = request.args.get("limit", 50, type=int)
        
        config = load_config()
        if not config.get("graphiti", {}).get("enabled", False):
            return jsonify({"error": "Graphiti 未启用", "edges": []})
        
        adapter = get_graphiti_adapter()
        if adapter is None:
            return jsonify({"error": "Graphiti 适配器不可用", "edges": []})
        
        import asyncio
        from graphiti_core.edges import EntityEdge
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            driver = adapter._async_adapter._driver
            
            # 获取 group_id
            graphiti_config = config.get("graphiti", {})
            group_id = graphiti_config.get("group_id", {}).get("default", "lifebook")
            
            try:
                edges = loop.run_until_complete(
                    EntityEdge.get_by_group_ids(driver, [group_id], limit=limit)
                )
            except Exception:
                edges = []
            
            return jsonify({
                "success": True,
                "edges": [
                    {
                        "uuid": e.uuid,
                        "name": e.name,
                        "fact": e.fact,
                        "source_node_uuid": e.source_node_uuid,
                        "target_node_uuid": e.target_node_uuid,
                        "valid_at": e.valid_at.isoformat() if e.valid_at else None,
                        "invalid_at": e.invalid_at.isoformat() if e.invalid_at else None,
                    }
                    for e in edges
                ],
                "count": len(edges),
            })
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"获取边列表失败: {e}")
        return jsonify({"error": str(e), "edges": []}), 500
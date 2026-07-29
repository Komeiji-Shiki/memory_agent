"""
Graphiti 同步基础设施

从 graphiti_routes.py 拆分出来的非路由部分：
- TokenUsageTracker: 每日 LLM Token 用量追踪
- SyncStatus / SyncTaskManager: Markdown 批量同步任务（支持暂停/停止/继续）
- get_graphiti_adapter / invalidate_graphiti_adapter: 适配器获取
  （委托 memory_store 的进程级共享单例，与 Agent 工具共用同一个 Kuzu 连接）
"""

import logging
import threading
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional

from .core import load_config, get_lifebook_path

logger = logging.getLogger(__name__)


# ========== Token 使用量追踪 ==========

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
                        adapter.run_coro(
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
                        adapter.run_coro(
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


        except Exception as e:
            logger.error(f"[同步] ❌ 同步任务异常: {e}", exc_info=True)
            with self._lock:
                self.status = SyncStatus.FAILED
                self.progress["error"] = str(e)
                self.progress["end_time"] = datetime.now().isoformat()


# ========== 全局实例 ==========

_sync_manager: Optional[SyncTaskManager] = None
_token_tracker: Optional[TokenUsageTracker] = None


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


# ========== 适配器获取（进程级共享） ==========

def get_graphiti_adapter():
    """
    获取 Graphiti 适配器实例。

    委托 memory_store 的进程级共享单例——web 管理面板与 Agent 工具
    共用同一个 GraphitiSyncAdapter，避免对同一 Kuzu 数据库开多个连接。

    如果 Graphiti 未启用或初始化失败，返回 None。
    """
    try:
        from memory_store.graphiti_adapter import get_shared_sync_adapter
        config = load_config()
        lifebook_path = get_lifebook_path()
        return get_shared_sync_adapter(config, lifebook_path)
    except ImportError as e:
        logger.warning(f"[Graphiti] ⚠️ 模块未安装: {e}")
        return None
    except Exception as e:
        logger.error(f"[Graphiti] ❌ 初始化失败: {e}", exc_info=True)
        return None


def invalidate_graphiti_adapter():
    """使 Graphiti 适配器失效（配置更改时调用，下次获取时按新配置重建）"""
    try:
        from memory_store.graphiti_adapter import invalidate_shared_sync_adapter
        invalidate_shared_sync_adapter()
    except ImportError:
        pass

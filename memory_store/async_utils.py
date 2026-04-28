"""
异步工具模块

提供异步优化的工具函数和装饰器。
"""

import asyncio
import logging
from typing import List, Dict, Any, Callable, Awaitable, Optional
from concurrent.futures import ThreadPoolExecutor
from functools import wraps


async def parallel_tasks(
    tasks: List[Callable[[], Any]],
    max_workers: int = 5
) -> List[Any]:
    """
    并行执行多个任务
    
    Args:
        tasks: 任务函数列表
        max_workers: 最大并发数
        
    Returns:
        任务结果列表
    """
    loop = asyncio.get_event_loop()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [loop.run_in_executor(executor, task) for task in tasks]
        results = await asyncio.gather(*futures, return_exceptions=True)
    
    # 过滤异常
    clean_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logging.warning(f"并行任务 {i} 失败: {result}")
        else:
            clean_results.append(result)
    
    return clean_results


async def warmup_cache_async(
    queries: List[str],
    search_fn: Callable[[str], List[Dict]],
    cache_set_fn: Callable[[str, List[Dict]], None],
    max_concurrent: int = 3
) -> Dict[str, int]:
    """
    异步预热缓存
    
    Args:
        queries: 查询列表
        search_fn: 搜索函数
        cache_set_fn: 缓存设置函数
        max_concurrent: 最大并发数
        
    Returns:
        {query: result_count} 预热结果
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results = {}
    
    async def _warmup_single(query: str) -> None:
        async with semaphore:
            try:
                # 在线程池中执行同步搜索
                loop = asyncio.get_event_loop()
                search_results = await loop.run_in_executor(None, search_fn, query)
                
                if search_results:
                    cache_set_fn(query, search_results)
                    results[query] = len(search_results)
                else:
                    results[query] = 0
            except Exception as e:
                logging.warning(f"Cache warmup failed for '{query}': {e}")
                results[query] = -1
    
    # 创建所有任务
    tasks = [_warmup_single(q) for q in queries]
    await asyncio.gather(*tasks)
    
    return results


def async_retry(
    max_retries: int = 3,
    delay: float = 1.0,
    exceptions: tuple = (Exception,)
):
    """
    异步重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 重试间隔（秒）
        exceptions: 需要捕获的异常类型
    """
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        raise
                    logging.warning(f"Attempt {attempt + 1} failed: {e}, retrying...")
                    await asyncio.sleep(delay * (2 ** attempt))  # 指数退避
            
        return wrapper
    return decorator


class AsyncBatchProcessor:
    """异步批处理器"""
    
    def __init__(
        self,
        batch_size: int = 10,
        max_workers: int = 5,
        delay_between_batches: float = 0.1
    ):
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.delay = delay_between_batches
    
    async def process(
        self,
        items: List[Any],
        process_fn: Callable[[Any], Awaitable[Any]]
    ) -> List[Any]:
        """
        批量处理项目
        
        Args:
            items: 要处理的项目列表
            process_fn: 异步处理函数
            
        Returns:
            处理结果列表
        """
        results = []
        
        for i in range(0, len(items), self.batch_size):
            batch = items[i:i + self.batch_size]
            
            # 处理批次
            batch_tasks = [process_fn(item) for item in batch]
            batch_results = await asyncio.gather(
                *batch_tasks,
                return_exceptions=True
            )
            
            # 收集结果
            for result in batch_results:
                if not isinstance(result, Exception):
                    results.append(result)
            
            # 批次间延迟
            if i + self.batch_size < len(items):
                await asyncio.sleep(self.delay)
        
        return results


# 全局线程池
_global_executor: Optional[ThreadPoolExecutor] = None


def get_executor(max_workers: int = 10) -> ThreadPoolExecutor:
    """获取全局线程池"""
    global _global_executor
    if _global_executor is None:
        _global_executor = ThreadPoolExecutor(max_workers=max_workers)
    return _global_executor


def shutdown_executor():
    """关闭全局线程池"""
    global _global_executor
    if _global_executor:
        _global_executor.shutdown(wait=True)
        _global_executor = None
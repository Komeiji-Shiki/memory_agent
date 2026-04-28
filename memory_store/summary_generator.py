"""
Summary Generator - 自动生成周/月/季总结

支持：
- 周总结：汇总指定周的日记
- 月总结：汇总指定月的日记或周总结
- 季度总结：汇总指定季度的月总结
"""

import os
import time
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import httpx
from openai import OpenAI

from memory_store.reader import LifeBookReader
from memory_store.writer import LifeBookWriter
from memory_store.debug_logger import get_debug_logger


@dataclass
class SummaryConfig:
    """总结生成配置"""
    model: str = "deepseek-chat"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    
    # 重试配置
    enable_retry: bool = True  # 是否启用重试
    max_retries: int = 3  # 最大重试次数
    base_delay: float = 1.0  # 基础延迟（秒）
    max_delay: float = 30.0  # 最大延迟（秒）
    
    weekly_prompt: str = """请根据以下一周的日记内容，生成一份周度总结。

要求：
1. 用**第三人称**撰写，称用户为「用户」，称AI为「助手」
2. **只记录内容，不进行评价，不进行不必要的情感升华**
3. **只记录完整内容，不在记录后进行总结性归纳**
4. 按时间顺序列出本周的事件和对话内容
5. 详细记录，不遗漏可能有用的细节
6. 500-800字

示例格式：
「本周用户和助手讨论了...用户提到...助手帮助用户完成了...」

日记内容：
{diary_content}

请生成周总结（第三人称）："""

    monthly_prompt: str = """请根据以下内容，生成一份月度总结。

要求：
1. 用**第三人称**撰写，称用户为「用户」，称AI为「助手」
2. **只记录内容，不进行评价，不进行不必要的情感升华**
3. **只记录完整内容，不在记录后进行总结性归纳**
4. 按时间顺序整理本月的主要事件和对话
5. 详细记录，不遗漏可能有用的细节
6. 800-1200字

示例格式：
「本月用户和助手...用户在X日提到...」

内容：
{content}

请生成月度总结（第三人称）："""

    quarterly_prompt: str = """请根据以下季度的月总结，生成一份季度总结。

要求：
1. 用**第三人称**撰写，称用户为「用户」，称AI为「助手」
2. **只记录内容，不进行评价，不进行不必要的情感升华**
3. **只记录完整内容，不在记录后进行总结性归纳**
4. 按时间顺序整理本季度的主要事件
5. 详细记录重要的人、事、项目
6. 1000-1500字

示例格式：
「本季度用户和助手...」

月总结内容：
{content}

请生成季度总结（第三人称）："""


class SummaryGenerator:
    """总结生成器"""
    
    def __init__(
        self,
        lifebook_path: str,
        config: Optional[SummaryConfig] = None,
        encoding: str = "utf-8"
    ):
        self.lifebook_path = lifebook_path
        self.config = config or SummaryConfig()
        self.encoding = encoding
        
        self.reader = LifeBookReader(lifebook_path, encoding)
        self.writer = LifeBookWriter(lifebook_path, encoding)
    
    def generate_weekly(self, identifier: str) -> Dict[str, Any]:
        """
        生成周总结
        
        Args:
            identifier: 周标识符，如 "2025-W52"
            
        Returns:
            {"success": bool, "content": str, "message": str}
        """
        try:
            # 解析周标识符
            year, week = self._parse_week_identifier(identifier)
            
            # 获取该周的日期范围
            start_date, end_date = self._get_week_date_range(year, week)
            
            # 读取该周的日记
            diaries = self.reader.read_diaries_range(
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d")
            )
            
            if not diaries:
                return {
                    "success": False,
                    "content": "",
                    "message": f"未找到 {identifier} 的日记"
                }
            
            # 组装日记内容
            diary_content = self._format_diaries(diaries)
            
            # 调用 AI 生成
            prompt = self.config.weekly_prompt.format(diary_content=diary_content)
            
            # 记录调试日志
            get_debug_logger().log_summary_generate(
                model=self.config.model,
                prompt=prompt,
                summary_type="weekly",
                identifier=identifier,
                extra={"diary_count": len(diaries)}
            )
            
            summary = self._call_ai(prompt)
            
            if not summary:
                return {
                    "success": False,
                    "content": "",
                    "message": "AI 生成失败"
                }
            
            # 添加标题
            summary_with_title = f"# {year}年第{week}周总结\n\n{summary}"
            
            # 保存
            self.writer.create_summary("weekly", identifier, summary_with_title)
            
            return {
                "success": True,
                "content": summary_with_title,
                "message": f"周总结 {identifier} 生成成功"
            }
            
        except Exception as e:
            return {
                "success": False,
                "content": "",
                "message": f"生成失败: {str(e)}"
            }
    
    def generate_monthly(self, identifier: str, use_weekly: bool = True) -> Dict[str, Any]:
        """
        生成月总结
        
        Args:
            identifier: 月标识符，如 "2025-12"
            use_weekly: 是否使用周总结（否则使用日记）
            
        Returns:
            {"success": bool, "content": str, "message": str}
        """
        try:
            # 解析月标识符
            year, month = self._parse_month_identifier(identifier)
            
            content_parts = []
            
            if use_weekly:
                # 获取该月的周总结
                weeks = self._get_month_weeks(year, month)
                for week_id in weeks:
                    weekly = self.reader.read_summary("weekly", week_id)
                    if weekly:
                        content_parts.append(f"## {week_id}\n{weekly.content}")
            
            # 如果没有周总结，使用日记
            if not content_parts:
                start_date = datetime(year, month, 1)
                if month == 12:
                    end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
                else:
                    end_date = datetime(year, month + 1, 1) - timedelta(days=1)
                
                diaries = self.reader.read_diaries_range(
                    start_date.strftime("%Y-%m-%d"),
                    end_date.strftime("%Y-%m-%d")
                )
                
                if diaries:
                    content_parts.append(self._format_diaries(diaries))
            
            if not content_parts:
                return {
                    "success": False,
                    "content": "",
                    "message": f"未找到 {identifier} 的相关内容"
                }
            
            # 调用 AI 生成
            content = "\n\n".join(content_parts)
            prompt = self.config.monthly_prompt.format(content=content)
            
            # 记录调试日志
            get_debug_logger().log_summary_generate(
                model=self.config.model,
                prompt=prompt,
                summary_type="monthly",
                identifier=identifier,
                extra={"use_weekly": use_weekly}
            )
            
            summary = self._call_ai(prompt)
            
            if not summary:
                return {
                    "success": False,
                    "content": "",
                    "message": "AI 生成失败"
                }
            
            # 添加标题
            summary_with_title = f"# {year}年{month}月总结\n\n{summary}"
            
            # 保存
            self.writer.create_summary("monthly", identifier, summary_with_title)
            
            return {
                "success": True,
                "content": summary_with_title,
                "message": f"月总结 {identifier} 生成成功"
            }
            
        except Exception as e:
            return {
                "success": False,
                "content": "",
                "message": f"生成失败: {str(e)}"
            }
    
    def generate_quarterly(self, identifier: str) -> Dict[str, Any]:
        """
        生成季度总结
        
        Args:
            identifier: 季度标识符，如 "2025-Q4"
            
        Returns:
            {"success": bool, "content": str, "message": str}
        """
        try:
            # 解析季度标识符
            year, quarter = self._parse_quarter_identifier(identifier)
            
            # 获取该季度的月份
            months = self._get_quarter_months(quarter)
            
            content_parts = []
            for month in months:
                month_id = f"{year}-{month:02d}"
                monthly = self.reader.read_summary("monthly", month_id)
                if monthly:
                    content_parts.append(f"## {month_id}\n{monthly.content}")
            
            if not content_parts:
                return {
                    "success": False,
                    "content": "",
                    "message": f"未找到 {identifier} 的月总结"
                }
            
            # 调用 AI 生成
            content = "\n\n".join(content_parts)
            prompt = self.config.quarterly_prompt.format(content=content)
            
            # 记录调试日志
            get_debug_logger().log_summary_generate(
                model=self.config.model,
                prompt=prompt,
                summary_type="quarterly",
                identifier=identifier,
                extra={"months_count": len(content_parts)}
            )
            
            summary = self._call_ai(prompt)
            
            if not summary:
                return {
                    "success": False,
                    "content": "",
                    "message": "AI 生成失败"
                }
            
            # 添加标题
            summary_with_title = f"# {year}年Q{quarter}总结\n\n{summary}"
            
            # 保存
            self.writer.create_summary("quarterly", identifier, summary_with_title)
            
            return {
                "success": True,
                "content": summary_with_title,
                "message": f"季度总结 {identifier} 生成成功"
            }
            
        except Exception as e:
            return {
                "success": False,
                "content": "",
                "message": f"生成失败: {str(e)}"
            }
    
    def _call_ai(self, prompt: str) -> Optional[str]:
        """
        调用 AI 生成（支持重试）
        
        重试策略：
        - 启用时使用指数退避 + 随机抖动
        - 仅对可重试错误（429、5xx、网络错误）重试
        - 不可重试错误（401、400等）立即失败
        """
        # 创建不带代理的客户端，避免系统代理设置导致的兼容性问题
        client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            http_client=httpx.Client(proxy=None)
        )
        
        max_attempts = self.config.max_retries + 1 if self.config.enable_retry else 1
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                # 非首次尝试时等待
                if attempt > 0:
                    delay = min(
                        self.config.base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5),
                        self.config.max_delay
                    )
                    print(f"[总结生成] 重试 {attempt}/{self.config.max_retries}，等待 {delay:.1f}s...")
                    time.sleep(delay)
                
                response = client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=2000,
                    temperature=0.7
                )
                
                return response.choices[0].message.content
                
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                
                # 判断是否可重试
                is_retryable = any(x in error_str for x in [
                    '429', 'rate limit', 'too many requests',
                    '500', '502', '503', '504',
                    'timeout', 'connection', 'network'
                ])
                
                if not is_retryable or not self.config.enable_retry:
                    print(f"[总结生成] AI 调用失败（不可重试）: {e}")
                    return None
                
                print(f"[总结生成] AI 调用失败（可重试）: {e}")
        
        print(f"[总结生成] 达到最大重试次数 ({self.config.max_retries})，最后错误: {last_error}")
        return None
    
    def _format_diaries(self, diaries) -> str:
        """格式化日记列表"""
        parts = []
        for diary in diaries:
            parts.append(f"### {diary.date}\n{diary.content}")
        return "\n\n".join(parts)
    
    def _parse_week_identifier(self, identifier: str) -> tuple:
        """解析周标识符 (2025-W52) -> (2025, 52)"""
        parts = identifier.split("-W")
        return int(parts[0]), int(parts[1])
    
    def _parse_month_identifier(self, identifier: str) -> tuple:
        """解析月标识符 (2025-12) -> (2025, 12)"""
        parts = identifier.split("-")
        return int(parts[0]), int(parts[1])
    
    def _parse_quarter_identifier(self, identifier: str) -> tuple:
        """解析季度标识符 (2025-Q4) -> (2025, 4)"""
        parts = identifier.split("-Q")
        return int(parts[0]), int(parts[1])
    
    def _get_week_date_range(self, year: int, week: int) -> tuple:
        """获取 ISO 周的日期范围"""
        # ISO 周的第一天是周一
        jan_4 = datetime(year, 1, 4)
        week_1_start = jan_4 - timedelta(days=jan_4.weekday())
        
        week_start = week_1_start + timedelta(weeks=week - 1)
        week_end = week_start + timedelta(days=6)
        
        return week_start, week_end
    
    def _get_month_weeks(self, year: int, month: int) -> List[str]:
        """获取指定月份包含的 ISO 周"""
        weeks = set()
        
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1) - timedelta(days=1)
        
        current = start_date
        while current <= end_date:
            iso_year, iso_week, _ = current.isocalendar()
            weeks.add(f"{iso_year}-W{iso_week:02d}")
            current += timedelta(days=1)
        
        return sorted(list(weeks))
    
    def _get_quarter_months(self, quarter: int) -> List[int]:
        """获取季度包含的月份"""
        return [(quarter - 1) * 3 + i for i in range(1, 4)]
    
    def get_missing_summaries(self, lookback_months: int = 6) -> Dict[str, List[str]]:
        """
        获取缺失的总结
        
        Returns:
            {"weekly": [...], "monthly": [...], "quarterly": [...]}
        """
        now = datetime.now()
        missing = {"weekly": [], "monthly": [], "quarterly": []}
        
        # 检查周总结（过去的周）
        current_week = now.isocalendar()[1]
        for i in range(1, lookback_months * 4):  # 约每月4周
            check_date = now - timedelta(weeks=i)
            year, week, _ = check_date.isocalendar()
            identifier = f"{year}-W{week:02d}"
            
            if not self.reader.read_summary("weekly", identifier):
                # 检查是否有该周的日记
                start, end = self._get_week_date_range(year, week)
                diaries = self.reader.read_diaries_range(
                    start.strftime("%Y-%m-%d"),
                    end.strftime("%Y-%m-%d")
                )
                if diaries:  # 有日记但没有总结
                    missing["weekly"].append(identifier)
        
        # 检查月总结（过去的月，只检测有内容可总结的）
        for i in range(1, lookback_months + 1):
            check_date = now - timedelta(days=30 * i)
            year = check_date.year
            month = check_date.month
            identifier = f"{year}-{month:02d}"
            
            if not self.reader.read_summary("monthly", identifier):
                # 检查该月是否有日记或周总结
                has_content = False
                
                # 检查周总结
                weeks = self._get_month_weeks(year, month)
                for week_id in weeks:
                    if self.reader.read_summary("weekly", week_id):
                        has_content = True
                        break
                
                # 检查日记
                if not has_content:
                    start_date = datetime(year, month, 1)
                    if month == 12:
                        end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
                    else:
                        end_date = datetime(year, month + 1, 1) - timedelta(days=1)
                    
                    diaries = self.reader.read_diaries_range(
                        start_date.strftime("%Y-%m-%d"),
                        end_date.strftime("%Y-%m-%d")
                    )
                    if diaries:
                        has_content = True
                
                if has_content:
                    missing["monthly"].append(identifier)
        
        # 检查季度总结（过去的季度，只检测有月总结可汇总的）
        current_quarter = (now.month - 1) // 3 + 1
        for i in range(1, (lookback_months // 3) + 1):
            check_month = now.month - i * 3
            check_year = now.year
            while check_month <= 0:
                check_month += 12
                check_year -= 1
            
            q = (check_month - 1) // 3 + 1
            identifier = f"{check_year}-Q{q}"
            
            if not self.reader.read_summary("quarterly", identifier):
                # 检查该季度是否有月总结
                has_monthly = False
                months = self._get_quarter_months(q)
                for m in months:
                    month_id = f"{check_year}-{m:02d}"
                    if self.reader.read_summary("monthly", month_id):
                        has_monthly = True
                        break
                
                if has_monthly:
                    missing["quarterly"].append(identifier)
        
        return missing


# 便捷函数
def create_summary_generator(lifebook_path: str, config: Dict[str, Any]) -> SummaryGenerator:
    """从配置字典创建总结生成器"""
    summary_config = SummaryConfig(
        model=config.get("model", "deepseek-chat"),
        api_key=config.get("api_key", ""),
        base_url=config.get("base_url", "https://api.deepseek.com/v1"),
        weekly_prompt=config.get("weekly_prompt", SummaryConfig.weekly_prompt),
        monthly_prompt=config.get("monthly_prompt", SummaryConfig.monthly_prompt),
        quarterly_prompt=config.get("quarterly_prompt", SummaryConfig.quarterly_prompt),
        # 重试配置
        enable_retry=config.get("enable_retry", True),
        max_retries=config.get("max_retries", 3),
        base_delay=config.get("base_delay", 1.0),
        max_delay=config.get("max_delay", 30.0)
    )
    return SummaryGenerator(lifebook_path, summary_config)
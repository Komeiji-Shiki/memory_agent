"""
ContextBuilder 测试

重点覆盖 _build_quarterly_memory 的行为：
- 季度总结存在时按原逻辑渲染
- 季度总结缺失时回退读取该季度内存在的月总结
- 回退内容整体共享 quarterly_max_chars 预算
- 完全无数据时返回空字符串
"""

import os
import shutil
import tempfile
from datetime import datetime


def _make_lifebook(test_dir: str):
    """创建 lifebook 目录结构"""
    for sub in ["daily", "weekly", "monthly", "quarterly", "yearly", "nodes"]:
        os.makedirs(os.path.join(test_dir, sub), exist_ok=True)


def _write_summary(test_dir: str, summary_type: str, identifier: str, content: str):
    path = os.path.join(test_dir, summary_type, f"{identifier}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _make_builder(test_dir: str, **config_overrides):
    from memory_store.reader import LifeBookReader
    from memory_agent.context_builder import ContextBuilder, ContextConfig

    config = ContextConfig(lookback_months=5, **config_overrides)
    return ContextBuilder(LifeBookReader(test_dir), config=config)


# 固定测试时间：2026-02-15
# - 回溯 5 个月 -> lookback_start 约 2025-09-18 -> 起始季度 2025-Q3
# - 上月 2026-01 所在季度 2026-Q1（遍历终点，不含）
# - 实际遍历：2025-Q3、2025-Q4
NOW = datetime(2026, 2, 15)


def test_quarterly_summary_present():
    """季度总结存在时，按原逻辑渲染，不触发回退"""
    test_dir = tempfile.mkdtemp()
    try:
        _make_lifebook(test_dir)
        _write_summary(test_dir, "quarterly", "2025-Q3", "Q3季度总结内容ABC")

        builder = _make_builder(test_dir)
        result = builder._build_quarterly_memory(NOW)

        assert "2025-Q3" in result
        assert "Q3季度总结内容ABC" in result
        assert "lifebook/quarterly/2025-Q3.md" in result
        assert "缺少季度总结" not in result
    finally:
        shutil.rmtree(test_dir)
    print("test_quarterly_summary_present 通过!")


def test_fallback_to_monthly_when_quarterly_missing():
    """季度总结缺失时，回退到该季度内存在的月总结"""
    test_dir = tempfile.mkdtemp()
    try:
        _make_lifebook(test_dir)
        # 2025-Q4 无季度总结，但有 10 月和 12 月的月总结（11 月缺失）
        _write_summary(test_dir, "monthly", "2025-10", "十月总结内容XYZ")
        _write_summary(test_dir, "monthly", "2025-12", "十二月总结内容QWE")

        builder = _make_builder(test_dir)
        result = builder._build_quarterly_memory(NOW)

        # 回退标注与季度标识
        assert "2025-Q4" in result
        assert "缺少季度总结" in result
        # 存在的月总结被渲染，来源指向 monthly 目录
        assert "十月总结内容XYZ" in result
        assert "十二月总结内容QWE" in result
        assert "lifebook/monthly/2025-10.md" in result
        assert "lifebook/monthly/2025-12.md" in result
        # 缺失的 11 月不应出现
        assert "2025-11" not in result
    finally:
        shutil.rmtree(test_dir)
    print("test_fallback_to_monthly_when_quarterly_missing 通过!")


def test_fallback_budget_truncation():
    """回退内容整体共享 quarterly_max_chars 预算，超出截断、耗尽即停"""
    test_dir = tempfile.mkdtemp()
    try:
        _make_lifebook(test_dir)
        _write_summary(test_dir, "monthly", "2025-10", "A" * 200)
        _write_summary(test_dir, "monthly", "2025-11", "B" * 200)

        builder = _make_builder(test_dir, quarterly_max_chars=50)
        result = builder._build_quarterly_memory(NOW)

        # 第一份月总结被截断
        assert "A" * 50 in result
        assert "A" * 51 not in result
        assert "... (已截断)" in result
        # 预算耗尽后第二份不再渲染
        assert "B" not in result
    finally:
        shutil.rmtree(test_dir)
    print("test_fallback_budget_truncation 通过!")


def test_fallback_no_truncation_when_disabled():
    """disable_truncation 开启时，回退内容不受预算限制"""
    test_dir = tempfile.mkdtemp()
    try:
        _make_lifebook(test_dir)
        _write_summary(test_dir, "monthly", "2025-10", "A" * 200)
        _write_summary(test_dir, "monthly", "2025-11", "B" * 200)

        builder = _make_builder(
            test_dir, quarterly_max_chars=50, disable_truncation=True
        )
        result = builder._build_quarterly_memory(NOW)

        assert "A" * 200 in result
        assert "B" * 200 in result
        assert "... (已截断)" not in result
    finally:
        shutil.rmtree(test_dir)
    print("test_fallback_no_truncation_when_disabled 通过!")


def test_empty_when_nothing_exists():
    """季度总结和月总结都不存在时，返回空字符串"""
    test_dir = tempfile.mkdtemp()
    try:
        _make_lifebook(test_dir)

        builder = _make_builder(test_dir)
        result = builder._build_quarterly_memory(NOW)

        assert result == ""
    finally:
        shutil.rmtree(test_dir)
    print("test_empty_when_nothing_exists 通过!")


def test_mixed_quarterly_and_fallback():
    """一个季度有总结、另一个季度回退，两者共存"""
    test_dir = tempfile.mkdtemp()
    try:
        _make_lifebook(test_dir)
        _write_summary(test_dir, "quarterly", "2025-Q3", "Q3季度总结内容")
        _write_summary(test_dir, "monthly", "2025-11", "十一月总结内容")

        builder = _make_builder(test_dir)
        result = builder._build_quarterly_memory(NOW)

        # Q3 正常渲染在前，Q4 回退渲染在后
        assert "Q3季度总结内容" in result
        assert "十一月总结内容" in result
        assert result.index("Q3季度总结内容") < result.index("十一月总结内容")
        # 只有 Q4 带回退标注
        assert result.count("缺少季度总结") == 1
    finally:
        shutil.rmtree(test_dir)
    print("test_mixed_quarterly_and_fallback 通过!")


if __name__ == "__main__":
    test_quarterly_summary_present()
    test_fallback_to_monthly_when_quarterly_missing()
    test_fallback_budget_truncation()
    test_fallback_no_truncation_when_disabled()
    test_empty_when_nothing_exists()
    test_mixed_quarterly_and_fallback()
    print("\n所有 ContextBuilder 测试通过!")

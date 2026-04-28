"""
Graphiti 适配器测试

测试 GraphitiAdapter 的核心功能：
1. 初始化和关闭
2. Episode 添加（日记/节点/对话）
3. 混合搜索
4. 时序查询
5. Markdown 同步

运行方式：
    python tests/test_graphiti_adapter.py
    
    # 或使用 pytest
    pytest tests/test_graphiti_adapter.py -v
"""

import asyncio
import os
import sys
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory_store.graphiti_adapter import (
    GraphitiAdapter,
    GraphitiSyncAdapter,
    GraphitiConfig,
    EpisodeType,
    ContentValueEstimator,
    SearchResult,
    TemporalQueryResult,
)


# ============================================================
# 测试配置
# ============================================================

def get_test_config(temp_dir: str, enabled: bool = True) -> Dict[str, Any]:
    """生成测试配置"""
    return {
        "graphiti": {
            "enabled": enabled,
            "backend": "kuzu",
            "kuzu": {
                "db_path": os.path.join(temp_dir, ".graphiti.kuzu")
            },
            "llm": {
                "base_url": os.environ.get("OPENAI_BASE_URL"),
                "api_key": os.environ.get("OPENAI_API_KEY", "test-key"),
                "model": "gpt-4o-mini",
                "small_model": "gpt-4o-mini",
                "temperature": 1.0,
                "max_tokens": 8192,
            },
            "embedding": {
                "base_url": os.environ.get("OPENAI_BASE_URL"),
                "api_key": os.environ.get("OPENAI_API_KEY", "test-key"),
                "model": "text-embedding-3-small",
                "dim": 1536,
            },
            "reranker": {
                "enabled": False,
            },
            "search": {
                "sim_min_score": 0.3,
            },
            "group_id": {
                "strategy": "single",
                "default": "test-lifebook",
            },
            "episode_types": {
                "conversation": {
                    "min_value_threshold": 0.3,
                }
            },
            "retrieval": {
                "strategy": "simple",
                "default_limit": 10,
            },
            "performance": {
                "max_concurrent_queries": 1,
            },
        }
    }


# ============================================================
# 单元测试：配置解析
# ============================================================

def test_config_parsing():
    """测试配置解析"""
    print("\n=== 测试配置解析 ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        config = get_test_config(temp_dir)
        graphiti_config = GraphitiConfig.from_dict(config, temp_dir)
        
        assert graphiti_config.enabled == True
        assert graphiti_config.backend == "kuzu"
        assert "graphiti.kuzu" in graphiti_config.kuzu_db_path
        assert graphiti_config.llm.model == "gpt-4o-mini"
        assert graphiti_config.embedding.dim == 1536
        assert graphiti_config.group_id.default == "test-lifebook"
        
        print("✓ 配置解析正确")
        print(f"  - backend: {graphiti_config.backend}")
        print(f"  - kuzu_path: {graphiti_config.kuzu_db_path}")
        print(f"  - llm_model: {graphiti_config.llm.model}")


def test_episode_type_mapping():
    """测试 Episode 类型映射"""
    print("\n=== 测试 Episode 类型映射 ===")
    
    assert EpisodeType.DIARY.to_graphiti_type() == "text"
    assert EpisodeType.NODE.to_graphiti_type() == "json"
    assert EpisodeType.CONVERSATION.to_graphiti_type() == "message"
    
    print("✓ EpisodeType 映射正确")


def test_group_id_strategy():
    """测试 Group ID 策略"""
    print("\n=== 测试 Group ID 策略 ===")
    
    from memory_store.graphiti_adapter import GroupIdStrategy
    
    # 单用户策略
    strategy = GroupIdStrategy(strategy="single", default="lifebook")
    assert strategy.get_group_id() == "lifebook"
    assert strategy.get_group_id(user_id="123") == "lifebook"
    
    # 用户隔离策略
    strategy = GroupIdStrategy(
        strategy="user",
        default="lifebook",
        user_template="user_{user_id}"
    )
    assert strategy.get_group_id(user_id="123") == "user_123"
    assert strategy.get_group_id() == "lifebook"  # 无 user_id 时用默认值
    
    print("✓ GroupIdStrategy 工作正确")


# ============================================================
# 单元测试：内容价值评估
# ============================================================

def test_content_value_estimator():
    """测试内容价值评估器"""
    print("\n=== 测试内容价值评估 ===")
    
    estimator = ContentValueEstimator(min_threshold=0.3)
    
    # 高价值内容
    high_value = "今天完成了 LifeBook 项目的 Graphiti 集成开发，实现了时序知识图谱功能。"
    score = estimator.estimate(high_value)
    print(f"  高价值内容得分: {score:.2f}")
    assert score > 0.5, f"期望 > 0.5, 实际 {score}"
    
    # 低价值内容
    low_value = "哈哈"
    score = estimator.estimate(low_value)
    print(f"  低价值内容得分: {score:.2f}")
    assert score < 0.3, f"期望 < 0.3, 实际 {score}"
    
    # 中等价值
    medium_value = "今天天气不错"
    score = estimator.estimate(medium_value)
    print(f"  中等价值内容得分: {score:.2f}")
    
    # should_index 测试
    assert estimator.should_index(high_value, EpisodeType.CONVERSATION) == True
    assert estimator.should_index(low_value, EpisodeType.CONVERSATION) == False
    assert estimator.should_index(low_value, EpisodeType.DIARY) == True  # 日记总是索引
    
    print("✓ ContentValueEstimator 工作正确")


# ============================================================
# 集成测试：适配器基本功能
# ============================================================

async def test_adapter_initialization():
    """测试适配器初始化"""
    print("\n=== 测试适配器初始化 ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # 创建 lifebook 目录结构
        lifebook_path = os.path.join(temp_dir, "lifebook")
        os.makedirs(os.path.join(lifebook_path, "daily"), exist_ok=True)
        os.makedirs(os.path.join(lifebook_path, "nodes"), exist_ok=True)
        
        config = get_test_config(temp_dir, enabled=False)  # 禁用以避免需要真实 API
        
        adapter = GraphitiAdapter.from_config(config, lifebook_path)
        
        assert adapter.is_enabled == False
        assert adapter.is_initialized == False
        
        # 禁用状态下初始化应该跳过
        await adapter.initialize()
        assert adapter.is_initialized == False
        
        print("✓ 禁用状态下适配器行为正确")
        
        # 测试 stats
        stats = await adapter.get_stats()
        assert stats["enabled"] == False
        assert stats["initialized"] == False
        print(f"  stats: {stats}")


async def test_adapter_with_mock():
    """测试适配器（模拟模式）"""
    print("\n=== 测试适配器模拟模式 ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        lifebook_path = os.path.join(temp_dir, "lifebook")
        os.makedirs(os.path.join(lifebook_path, "daily"), exist_ok=True)
        
        # 创建测试日记
        diary_path = os.path.join(lifebook_path, "daily", "2026-01-22.md")
        with open(diary_path, "w", encoding="utf-8") as f:
            f.write("# 2026-01-22\n\n今天测试了 Graphiti 适配器功能。")
        
        config = get_test_config(temp_dir, enabled=False)
        adapter = GraphitiAdapter.from_config(config, lifebook_path)
        
        # 测试搜索（禁用状态应返回空）
        results = await adapter.search("Graphiti")
        assert results == []
        print("✓ 禁用状态搜索返回空列表")
        
        # 测试时序查询
        result = await adapter.temporal_query("主人", datetime.now())
        assert result.facts_count == 0
        print("✓ 禁用状态时序查询返回空结果")


# ============================================================
# 集成测试：完整流程（需要真实 API）
# ============================================================

async def test_full_integration():
    """
    完整集成测试
    
    需要设置环境变量：
    - OPENAI_API_KEY: OpenAI API 密钥
    - OPENAI_BASE_URL: （可选）自定义 API 地址
    """
    print("\n=== 完整集成测试 ===")
    
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("⚠️ 跳过：未设置 OPENAI_API_KEY 环境变量")
        return
    
    with tempfile.TemporaryDirectory() as temp_dir:
        lifebook_path = os.path.join(temp_dir, "lifebook")
        os.makedirs(os.path.join(lifebook_path, "daily"), exist_ok=True)
        os.makedirs(os.path.join(lifebook_path, "nodes"), exist_ok=True)
        
        config = get_test_config(temp_dir, enabled=True)
        
        print("  初始化适配器...")
        
        try:
            async with GraphitiAdapter.create(config, lifebook_path) as adapter:
                print("✓ 适配器初始化成功")
                
                # 添加日记
                print("  添加测试日记...")
                uuid = await adapter.add_diary(
                    "2026-01-22",
                    "今天完成了 Graphiti 适配器的开发，实现了时序知识图谱功能。"
                )
                print(f"✓ 日记已添加: {uuid}")
                
                # 添加对话
                print("  添加测试对话...")
                uuid = await adapter.add_conversation(
                    session_id="test_session",
                    turn_id=1,
                    user_message="Graphiti 是什么？",
                    assistant_message="Graphiti 是一个时序知识图谱框架。"
                )
                print(f"✓ 对话已添加: {uuid}")
                
                # 搜索
                print("  执行搜索...")
                results = await adapter.search("Graphiti", num_results=5)
                print(f"✓ 搜索完成，找到 {len(results)} 条结果")
                for i, r in enumerate(results[:3]):
                    print(f"    {i+1}. [{r.score:.2f}] {r.content[:50]}...")
                
                # 时序查询
                print("  执行时序查询...")
                result = await adapter.temporal_query(
                    "Graphiti",
                    datetime.now()
                )
                print(f"✓ 时序查询完成，找到 {result.facts_count} 条事实")
                
                # 获取统计
                stats = await adapter.get_stats()
                print(f"  统计: {stats}")
                
        except ImportError as e:
            print(f"⚠️ 跳过：Graphiti 未安装 - {e}")
        except Exception as e:
            print(f"✗ 测试失败: {e}")
            raise


# ============================================================
# 同步适配器测试
# ============================================================

def test_sync_adapter():
    """测试同步适配器"""
    print("\n=== 测试同步适配器 ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        lifebook_path = os.path.join(temp_dir, "lifebook")
        os.makedirs(lifebook_path, exist_ok=True)
        
        config = get_test_config(temp_dir, enabled=False)
        
        adapter = GraphitiSyncAdapter(config, lifebook_path)
        
        assert adapter.is_enabled == False
        
        # 使用上下文管理器
        with adapter:
            results = adapter.search("test")
            assert results == []
        
        print("✓ 同步适配器工作正确")


# ============================================================
# 主函数
# ============================================================

async def run_async_tests():
    """运行异步测试"""
    await test_adapter_initialization()
    await test_adapter_with_mock()
    await test_full_integration()


def main():
    """主测试入口"""
    print("=" * 60)
    print("Graphiti 适配器测试")
    print("=" * 60)
    
    # 单元测试
    test_config_parsing()
    test_episode_type_mapping()
    test_group_id_strategy()
    test_content_value_estimator()
    test_sync_adapter()
    
    # 异步测试
    asyncio.run(run_async_tests())
    
    print("\n" + "=" * 60)
    print("所有测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
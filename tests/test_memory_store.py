"""
Memory Store 测试

从 memory_store/ 各模块移出的测试代码：
- reader.py
- writer.py
- indexer.py
- metadata.py
- rag.py
"""

import os
import tempfile
import shutil


def test_reader():
    """测试 LifeBook Reader"""
    from memory_store.reader import LifeBookReader
    
    test_dir = tempfile.mkdtemp()
    print(f"Reader 测试目录: {test_dir}")
    
    # 创建目录结构
    os.makedirs(os.path.join(test_dir, "daily"))
    os.makedirs(os.path.join(test_dir, "weekly"))
    os.makedirs(os.path.join(test_dir, "nodes"))
    
    # 创建测试日记
    diary_content = """---
title: 测试日记
date: 2025-12-29
---

# 今天的记录

今天和[[小明]]一起去了咖啡厅 #社交 #咖啡

聊了很多有趣的话题。
"""
    with open(os.path.join(test_dir, "daily", "2025-12-29.md"), "w", encoding="utf-8") as f:
        f.write(diary_content)
    
    # 测试读取
    reader = LifeBookReader(test_dir)
    
    diary = reader.read_diary("2025-12-29")
    if diary:
        print(f"\n日记标题: {diary.title}")
        print(f"标签: {diary.tags}")
        print(f"链接: {diary.links}")
    
    # 清理
    shutil.rmtree(test_dir)
    print("Reader 测试完成!")


def test_writer():
    """测试 LifeBook Writer"""
    from memory_store.writer import LifeBookWriter
    
    test_dir = tempfile.mkdtemp()
    print(f"\nWriter 测试目录: {test_dir}")
    
    writer = LifeBookWriter(test_dir)
    
    # 测试创建日记
    success = writer.create_diary(
        "2025-12-29",
        "今天天气很好，出去散步了。\n\n遇到了[[小明]]，聊了很久。",
        title="美好的一天",
        tags=["日常", "社交"]
    )
    print(f"创建日记: {'成功' if success else '失败'}")
    
    # 测试追加内容
    success = writer.append_to_diary(
        "2025-12-29",
        "晚上看了一部电影 #娱乐"
    )
    print(f"追加日记: {'成功' if success else '失败'}")
    
    # 测试创建节点
    success = writer.create_node(
        "小明",
        "人物",
        "大学同学，很有趣的人。\n\n## 联系方式\n电话：123456",
        tags=["朋友", "同学"]
    )
    print(f"创建节点: {'成功' if success else '失败'}")
    
    # 显示创建的文件
    print("\n创建的文件:")
    for root, dirs, files in os.walk(test_dir):
        for f in files:
            print(f"  {os.path.join(root, f)}")
    
    # 清理
    shutil.rmtree(test_dir)
    print("Writer 测试完成!")


def test_indexer():
    """测试 SQLite Memory Indexer"""
    from memory_store.sqlite_indexer import SqliteIndexer
    
    test_dir = tempfile.mkdtemp()
    print(f"\nSQLite Indexer 测试目录: {test_dir}")
    
    # 创建测试数据
    daily_dir = os.path.join(test_dir, "daily")
    os.makedirs(daily_dir)
    
    # 创建测试日记
    diary_content = """# 2025-12-29

今天和[[小明]]去了咖啡厅 #社交 #咖啡

讨论了Python编程和人工智能。
"""
    with open(os.path.join(daily_dir, "2025-12-29.md"), "w", encoding="utf-8") as f:
        f.write(diary_content)
    
    # 测试索引
    indexer = SqliteIndexer(test_dir)
    indexer.rebuild_index()
    
    # 获取统计信息
    stats = indexer.get_stats()
    print(f"索引文件数: {stats['total_files']}")
    print(f"关键词数: {stats['total_keywords']}")
    print(f"标签: {indexer.get_all_tags()}")
    print(f"人物: {indexer.get_all_people()}")
    
    # 测试搜索
    results = indexer.search("咖啡厅")
    print(f"搜索 '咖啡厅': 找到 {len(results)} 条结果")
    
    # 清理
    shutil.rmtree(test_dir)
    print("SQLite Indexer 测试完成!")


def test_metadata():
    """测试 Metadata Manager"""
    from memory_store.metadata import MetadataManager
    
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MetadataManager(tmpdir)
        
        print("\n初始状态:")
        print(f"  上次交互: {manager.get_last_interaction()}")
        print(f"  交互次数: {manager.get_interaction_count()}")
        
        # 更新
        manager.update_last_interaction()
        
        print("\n更新后:")
        print(f"  上次交互: {manager.get_last_interaction()}")
        print(f"  交互次数: {manager.get_interaction_count()}")
        
        # 自定义数据
        manager.set("custom_key", {"foo": "bar"})
        print(f"  自定义数据: {manager.get('custom_key')}")
        
        print("Metadata 测试完成!")


def test_rag():
    """测试 RAG 模块"""
    from memory_store.rag import RAGConfig
    
    print("\nRAG模块测试")
    print("=" * 40)
    
    # 测试配置
    config = RAGConfig(
        api_key="test-key",
        model="test-model",
        base_url="https://api.test.com",
        enabled=False
    )
    
    print(f"RAG 配置创建成功")
    print(f"  模型: {config.model}")
    print(f"  启用: {config.enabled}")
    print(f"  Top-K: {config.top_k}")
    
    print("RAG 测试完成!")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Memory Store 模块测试")
    print("=" * 60)
    
    test_reader()
    test_writer()
    test_indexer()
    test_metadata()
    test_rag()
    
    print("\n" + "=" * 60)
    print("所有测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
"""
Memory Tools 测试文件

从 memory_agent/tools.py 移出的测试代码
"""

import tempfile
import shutil
import sys
from pathlib import Path

# 添加项目根目录到 sys.path（测试文件的标准做法）
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from memory_agent.tools import MemoryTools


def test_memory_tools():
    """测试记忆工具的基本功能"""
    
    # 创建测试环境
    test_dir = tempfile.mkdtemp()
    print(f"测试目录: {test_dir}")
    
    try:
        # 初始化工具
        tools = MemoryTools(test_dir, enable_write=True)
        
        # 测试创建日记
        result = tools.call_tool("add_to_diary", {
            "content": "今天测试了记忆工具，效果不错！\n\n遇到了[[小明]]。",
            "date": "2025-12-29"
        })
        print(f"\n创建日记: {result}")
        assert "✓" in result, "创建日记失败"
        
        # 测试读取日记
        result = tools.call_tool("read_diary", {"date": "2025-12-29"})
        print(f"\n读取日记:\n{result}")
        assert "2025-12-29" in result, "读取日记失败"
        
        # 测试创建节点
        result = tools.call_tool("create_node", {
            "name": "小明",
            "type": "人物",
            "content": "好朋友，喜欢编程。",
            "tags": ["朋友"]
        })
        print(f"\n创建节点: {result}")
        assert "✓" in result, "创建节点失败"
        
        # 测试获取上下文
        result = tools.call_tool("get_current_context", {})
        print(f"\n当前上下文:\n{result}")
        assert "今天" in result, "获取上下文失败"
        
        # 显示 OpenAI 格式工具
        print("\nOpenAI 格式工具:")
        for tool in tools.get_openai_tools(include_write=True):
            print(f"  - {tool['function']['name']}: {tool['function']['description'][:50]}...")
        
        print("\n✅ 所有测试通过!")
        
    finally:
        # 清理
        shutil.rmtree(test_dir)
        print("测试清理完成")


def test_search_tools():
    """测试搜索工具"""
    test_dir = tempfile.mkdtemp()
    
    try:
        tools = MemoryTools(test_dir, enable_write=True)
        
        # 先创建一些测试数据
        tools.call_tool("add_to_diary", {
            "content": "今天去了#公园 散步，遇到了[[小红]]。天气很好，心情愉快。",
            "date": "2025-12-28"
        })
        
        tools.call_tool("add_to_diary", {
            "content": "继续在家编程，完成了#Python 项目。",
            "date": "2025-12-29"
        })
        
        # 测试搜索
        result = tools.call_tool("search_memories", {
            "query": "编程",
            "limit": 5
        })
        print(f"\n搜索'编程':\n{result}")
        
        # 测试列出最近日记
        result = tools.call_tool("list_recent", {"days": 7})
        print(f"\n最近7天日记:\n{result}")
        
        print("\n✅ 搜索测试通过!")
        
    finally:
        shutil.rmtree(test_dir)


def test_edit_tools():
    """测试编辑工具"""
    test_dir = tempfile.mkdtemp()
    
    try:
        tools = MemoryTools(test_dir, enable_write=True)
        
        # 创建日记
        tools.call_tool("add_to_diary", {
            "content": "今天天气晴朗，心情不错。",
            "date": "2025-12-30"
        })
        
        # 测试编辑日记
        result = tools.call_tool("edit_diary", {
            "date": "2025-12-30",
            "search": "心情不错",
            "replace": "心情非常好"
        })
        print(f"\n编辑日记: {result}")
        assert "✓" in result, "编辑日记失败"
        
        # 验证编辑结果
        result = tools.call_tool("read_diary", {"date": "2025-12-30"})
        assert "心情非常好" in result, "编辑未生效"
        print("编辑验证通过")
        
        print("\n✅ 编辑测试通过!")
        
    finally:
        shutil.rmtree(test_dir)


if __name__ == "__main__":
    print("=" * 60)
    print("Memory Tools 测试套件")
    print("=" * 60)
    
    print("\n--- 基本功能测试 ---")
    test_memory_tools()
    
    print("\n--- 搜索功能测试 ---")
    test_search_tools()
    
    print("\n--- 编辑功能测试 ---")
    test_edit_tools()
    
    print("\n" + "=" * 60)
    print("所有测试完成!")
    print("=" * 60)
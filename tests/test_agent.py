"""
Memory Agent 测试

从 memory_agent/agent.py 移出的测试代码
"""

import tempfile
import shutil
import os


def test_agent_initialization():
    """测试 Agent 初始化"""
    from memory_agent.tools import MemoryTools
    from memory_agent.agent import MemoryAgent, AgentConfig
    
    print("=" * 60)
    print("Memory Agent 测试")
    print("=" * 60)
    
    # 创建测试环境
    test_dir = tempfile.mkdtemp()
    print(f"\n测试目录: {test_dir}")
    
    # 创建测试数据
    daily_dir = os.path.join(test_dir, "daily")
    nodes_dir = os.path.join(test_dir, "nodes")
    os.makedirs(daily_dir)
    os.makedirs(nodes_dir)
    
    # 创建测试日记
    with open(os.path.join(daily_dir, "2025-12-29.md"), "w", encoding="utf-8") as f:
        f.write("""# 2025-12-29 日记

今天和[[小明]]一起去了咖啡厅 #社交 #咖啡

聊了关于人工智能的话题，非常有趣。小明推荐了一本书《深度学习》。
""")
    
    with open(os.path.join(daily_dir, "2025-12-28.md"), "w", encoding="utf-8") as f:
        f.write("""# 2025-12-28 日记

学习了Python编程 #学习 #编程

完成了一个记忆管理项目的初步设计。
""")
    
    # 创建人物节点
    with open(os.path.join(nodes_dir, "人物-小明.md"), "w", encoding="utf-8") as f:
        f.write("""# 小明

> 类型：人物

大学同学，对AI和深度学习很感兴趣。

#朋友 #同学
""")
    
    # 初始化工具
    tools = MemoryTools(test_dir, enable_write=True)
    tools.indexer.rebuild_index()
    
    # 注意：实际测试需要配置有效的API Key
    print("\n[模拟测试] Agent已初始化")
    print("实际使用需要配置 AgentConfig 中的 api_key")
    
    # 显示可用工具
    print("\n可用工具:")
    for tool in tools.get_openai_tools(include_write=True):
        print(f"  - {tool['function']['name']}")
    
    # 测试直接工具调用
    print("\n测试直接工具调用:")
    result = tools.call_tool("search_memories", {"query": "小明"})
    print(result)
    
    # 清理
    shutil.rmtree(test_dir)
    print("\n测试完成!")


if __name__ == "__main__":
    test_agent_initialization()
"""
Memory Router 测试

从 memory_router.py 移出的测试代码
"""

import os
import shutil


def test_memory_router():
    """测试 Memory Router 路由功能"""
    from memory_router import MemoryRouter
    
    print("=" * 60)
    print("Memory Router 测试")
    print("=" * 60)
    
    # 模拟配置
    config = {
        "memory_enabled": True,
        "lifebook": {
            "root_path": "./lifebook_test",
            "encoding": "utf-8"
        },
        "memory_agent": {
            "model": "deepseek-reasoner",
            "api_key": "test-key"
        },
        "model_routes": {
            "claude-3-5-sonnet": {"base_url": "...", "api_key": "..."},
            "gpt-4o": {"base_url": "...", "api_key": "..."},
            "_default": {"use_user_key": True}
        },
        "memory_manager": {
            "model_ids": ["memory-manager", "memory-agent"]
        },
        "context": {
            "insertion_position": "system_append"
        }
    }
    
    router = MemoryRouter(config)
    
    # 测试路由
    test_models = [
        "claude-3-5-sonnet-memory",
        "gpt-4o-memory",
        "memory-manager",
        "deepseek-v3",
        "unknown-model"
    ]
    
    print("\n路由测试:")
    for model in test_models:
        result = router.route(model)
        print(f"  {model} -> mode={result.mode}, base={result.base_model}, write={result.enable_write}")
    
    # 显示虚拟模型
    print("\n虚拟模型列表:")
    for m in router.get_virtual_models()[:10]:
        print(f"  - {m['id']} ({m['owned_by']})")
    
    # 清理测试目录
    if os.path.exists("./lifebook_test"):
        shutil.rmtree("./lifebook_test")
    
    print("\n测试完成!")


if __name__ == "__main__":
    test_memory_router()
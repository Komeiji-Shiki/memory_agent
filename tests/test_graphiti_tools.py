"""
Graphiti 工具测试

测试 Graphiti 工具定义和处理函数的正确性。
"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from dataclasses import dataclass

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory_agent.graphiti_tools import (
    GRAPHITI_TOOLS_DEFINITIONS,
    GraphitiToolHandlers,
    GraphitiToolResult,
    get_graphiti_tools_list,
    is_graphiti_tool
)


class TestGraphitiToolDefinitions:
    """测试工具定义"""
    
    def test_definitions_exist(self):
        """测试定义存在"""
        assert GRAPHITI_TOOLS_DEFINITIONS is not None
        assert len(GRAPHITI_TOOLS_DEFINITIONS) > 0
    
    def test_all_tools_have_required_fields(self):
        """所有必需字段都存在"""
        required_fields = ["name", "description", "parameters"]
        
        for tool_name, defn in GRAPHITI_TOOLS_DEFINITIONS.items():
            for field in required_fields:
                assert field in defn, f"工具 {tool_name} 缺少字段 {field}"
            
            # 检查参数结构
            params = defn["parameters"]
            assert params.get("type") == "object", f"工具 {tool_name} 参数类型不是 object"
            assert "properties" in params, f"工具 {tool_name} 缺少 properties"
            assert "required" in params, f"工具 {tool_name} 缺少 required"
    
    def test_tool_names_match(self):
        """工具名称匹配"""
        for tool_name, defn in GRAPHITI_TOOLS_DEFINITIONS.items():
            assert defn["name"] == tool_name, f"工具名称不匹配: {tool_name} vs {defn['name']}"
    
    def test_graphiti_search_definition(self):
        """测试 graphiti_search 定义"""
        defn = GRAPHITI_TOOLS_DEFINITIONS.get("graphiti_search")
        assert defn is not None
        
        params = defn["parameters"]
        props = params["properties"]
        
        assert "query" in props
        assert "num_results" in props
        assert "include_edges" in props
        assert "include_nodes" in props
        
        assert "query" in params["required"]
    
    def test_graphiti_temporal_definition(self):
        """测试 graphiti_temporal 定义"""
        defn = GRAPHITI_TOOLS_DEFINITIONS.get("graphiti_temporal")
        assert defn is not None
        
        params = defn["parameters"]
        props = params["properties"]
        
        assert "entity" in props
        assert "time_point" in props
        assert "num_results" in props
        
        assert "entity" in params["required"]
        assert "time_point" in params["required"]
    
    def test_graphiti_add_definition(self):
        """测试 graphiti_add 定义"""
        defn = GRAPHITI_TOOLS_DEFINITIONS.get("graphiti_add")
        assert defn is not None
        
        params = defn["parameters"]
        props = params["properties"]
        
        assert "content" in props
        assert "source" in props
        
        assert "content" in params["required"]


class TestGraphitiToolHandlers:
    """测试工具处理函数"""
    
    @pytest.fixture
    def mock_adapter(self):
        """创建 mock 适配器"""
        adapter = Mock()
        adapter.search = Mock(return_value=[])
        adapter.temporal_query = Mock(return_value=Mock(facts=[]))
        adapter.add_episode = Mock(return_value="test-uuid-12345678")
        adapter.get_stats = Mock(return_value={
            "enabled": True,
            "initialized": True,
            "backend": "kuzu",
            "db_path": "./test.kuzu",
            "llm_model": "gpt-4o-mini",
            "embedding_model": "text-embedding-3-small",
            "reranker_enabled": False
        })
        return adapter
    
    @pytest.fixture
    def handlers(self, mock_adapter, tmp_path):
        """创建处理器实例"""
        return GraphitiToolHandlers(mock_adapter, str(tmp_path))
    
    def test_handlers_init(self, handlers, mock_adapter):
        """测试处理器初始化"""
        assert handlers.adapter == mock_adapter
        assert handlers._initialized == False
    
    def test_ensure_initialized(self, handlers, mock_adapter):
        """测试初始化确保"""
        mock_adapter.initialize = Mock()
        
        result = handlers._ensure_initialized()
        
        assert result == True
        assert handlers._initialized == True
        mock_adapter.initialize.assert_called_once()
    
    def test_graphiti_search_empty_results(self, handlers, mock_adapter):
        """测试搜索无结果"""
        mock_adapter.search.return_value = []
        
        result = handlers.graphiti_search("测试查询")
        
        assert "未找到" in result
        mock_adapter.search.assert_called_once()
    
    def test_graphiti_search_with_results(self, handlers, mock_adapter):
        """测试搜索有结果"""
        @dataclass
        class MockSearchResult:
            uuid: str = "uuid-1"
            content: str = "这是测试内容"
            score: float = 0.95
            source: str = "test-source"
            result_type: str = "edge"
            valid_at: datetime = None
            invalid_at: datetime = None
        
        mock_adapter.search.return_value = [MockSearchResult()]
        
        result = handlers.graphiti_search("测试查询")
        
        assert "Graphiti 搜索结果" in result
        assert "这是测试内容" in result
        assert "0.95" in result
    
    def test_graphiti_temporal_invalid_date(self, handlers):
        """测试时间查询-无效日期格式"""
        result = handlers.graphiti_temporal("测试实体", "invalid-date")
        
        assert "时间格式错误" in result
    
    def test_graphiti_temporal_valid_date(self, handlers, mock_adapter):
        """测试时间查询-有效日期"""
        mock_result = Mock()
        mock_result.facts = [
            {"fact": "测试事实", "valid_from": "2025-01-01", "valid_to": "持续中", "relation": "测试关系"}
        ]
        mock_adapter.temporal_query.return_value = mock_result
        
        result = handlers.graphiti_temporal("测试实体", "2025-06-15")
        
        assert "时间点查询" in result
        assert "测试事实" in result
    
    def test_graphiti_add_success(self, handlers, mock_adapter):
        """测试添加知识成功"""
        mock_adapter.add_episode.return_value = "test-uuid-12345678"
        
        # Mock EpisodeType
        with patch('memory_agent.graphiti_tools.GraphitiToolHandlers._ensure_initialized', return_value=True):
            handlers._initialized = True
            
            # 需要 mock EpisodeType 的导入
            with patch.dict('sys.modules', {'memory_store.graphiti_adapter': Mock()}):
                from memory_store import graphiti_adapter
                graphiti_adapter.EpisodeType = Mock()
                graphiti_adapter.EpisodeType.CONVERSATION = "conv"
                
                result = handlers.graphiti_add("测试内容")
                
                assert "已添加到 Graphiti" in result or "test-uuid" in result
    
    def test_graphiti_get_stats(self, handlers, mock_adapter):
        """测试获取统计信息"""
        result = handlers.graphiti_get_stats()
        
        assert "统计信息" in result
        assert "✓ 已启用" in result
        assert "kuzu" in result
    
    def test_graphiti_multi_hop_empty(self, handlers, mock_adapter):
        """测试多跳查询无结果"""
        mock_adapter.search.return_value = []
        
        result = handlers.graphiti_multi_hop("测试实体")
        
        assert "未找到" in result


class TestConvenienceFunctions:
    """测试便捷函数"""
    
    def test_get_graphiti_tools_list(self):
        """测试获取工具列表"""
        tools = get_graphiti_tools_list()
        
        assert isinstance(tools, list)
        assert len(tools) > 0
        assert "graphiti_search" in tools
        assert "graphiti_temporal" in tools
    
    def test_is_graphiti_tool_positive(self):
        """测试是 Graphiti 工具"""
        assert is_graphiti_tool("graphiti_search") == True
        assert is_graphiti_tool("graphiti_temporal") == True
        assert is_graphiti_tool("graphiti_add") == True
    
    def test_is_graphiti_tool_negative(self):
        """测试不是 Graphiti 工具"""
        assert is_graphiti_tool("search_memories") == False
        assert is_graphiti_tool("read_diary") == False
        assert is_graphiti_tool("random_tool") == False


class TestMemoryToolsIntegration:
    """测试与 MemoryTools 的集成（需要 mock）"""
    
    @pytest.fixture
    def tmp_lifebook(self, tmp_path):
        """创建临时 lifebook 目录"""
        (tmp_path / "nodes").mkdir()
        (tmp_path / "daily").mkdir()
        return tmp_path
    
    def test_graphiti_disabled_by_default(self, tmp_lifebook):
        """测试 Graphiti 默认禁用"""
        from memory_agent.tools import MemoryTools
        
        tools = MemoryTools(
            lifebook_path=str(tmp_lifebook),
            enable_write=False
        )
        
        assert tools.graphiti_enabled == False
        assert tools.graphiti_handlers is None
    
    def test_graphiti_tools_not_registered_when_disabled(self, tmp_lifebook):
        """测试禁用时工具不注册"""
        from memory_agent.tools import MemoryTools
        
        tools = MemoryTools(
            lifebook_path=str(tmp_lifebook),
            enable_write=False
        )
        
        tool_names = list(tools.tools.keys())
        graphiti_tools = [name for name in tool_names if name.startswith("graphiti_")]
        
        assert len(graphiti_tools) == 0
    
    @patch('memory_agent.tools.GraphitiSyncAdapter')
    @patch('memory_agent.tools.GraphitiToolHandlers')
    def test_graphiti_tools_registered_when_enabled(self, mock_handlers_cls, mock_adapter_cls, tmp_lifebook):
        """测试启用时工具注册"""
        from memory_agent.tools import MemoryTools
        
        # Mock adapter 和 handlers
        mock_adapter = Mock()
        mock_adapter_cls.return_value = mock_adapter
        
        mock_handlers = Mock()
        mock_handlers.graphiti_search = Mock()
        mock_handlers.graphiti_temporal = Mock()
        mock_handlers.graphiti_add = Mock()
        mock_handlers.graphiti_multi_hop = Mock()
        mock_handlers.graphiti_sync_node = Mock()
        mock_handlers.graphiti_get_stats = Mock()
        mock_handlers_cls.return_value = mock_handlers
        
        graphiti_config = {
            "enabled": True,
            "backend": "kuzu",
            "kuzu": {"db_path": str(tmp_lifebook / ".graphiti.kuzu")}
        }
        
        # 由于 GraphitiSyncAdapter 可能没有安装，这里只测试逻辑
        # 实际测试需要完整的 graphiti-core 安装
        try:
            tools = MemoryTools(
                lifebook_path=str(tmp_lifebook),
                enable_write=True,
                graphiti_config=graphiti_config
            )
            
            # 如果成功初始化，检查工具是否注册
            if tools.graphiti_enabled:
                tool_names = list(tools.tools.keys())
                graphiti_tools = [name for name in tool_names if name.startswith("graphiti_")]
                assert len(graphiti_tools) > 0
        except Exception as e:
            # 如果 graphiti-core 未安装，跳过
            pytest.skip(f"Graphiti 依赖未安装: {e}")


class TestOpenAIToolFormat:
    """测试 OpenAI 工具格式转换"""
    
    @pytest.fixture
    def tmp_lifebook(self, tmp_path):
        """创建临时 lifebook 目录"""
        (tmp_path / "nodes").mkdir()
        (tmp_path / "daily").mkdir()
        return tmp_path
    
    def test_tool_format_structure(self):
        """测试工具格式结构"""
        from memory_agent.graphiti_tools import GRAPHITI_TOOLS_DEFINITIONS
        
        for tool_name, defn in GRAPHITI_TOOLS_DEFINITIONS.items():
            # 模拟 OpenAI 格式转换
            openai_format = {
                "type": "function",
                "function": {
                    "name": defn["name"],
                    "description": defn["description"],
                    "parameters": defn["parameters"]
                }
            }
            
            # 验证结构
            assert openai_format["type"] == "function"
            assert "function" in openai_format
            assert openai_format["function"]["name"] == tool_name
            assert len(openai_format["function"]["description"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
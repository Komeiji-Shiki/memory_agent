"""MCP wrapper: 让 MCPManager 能通过 `python server.py` 启动 Bing 搜索服务"""
import sys
import os

# 确保包目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_server_bing.server import server  # noqa: E402

if __name__ == "__main__":
    server.run()
else:
    server.run()
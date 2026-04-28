# Standalone Memory MCP（独立记忆 MCP 桥接器）

这个目录提供一个**独立的 MCP Server（stdio）**，用于把当前项目的记忆系统工具映射为标准 MCP 工具，供任意外部客户端接入。

- 不依赖本项目的 `mcp_servers/` 自动发现机制
- 直接复用现有记忆能力（`MemoryTools` 全量工具）
- 可给 Claude Code / 其他 MCP 客户端直接配置

---

## 1. 作用范围

本桥接器会暴露当前记忆系统可用工具（取决于配置）：

- 搜索类：`search_memories`, `rag_search`, `graphiti_search` ...
- 读取类：`read_diary`, `get_node`, `read_graph`, `get_memory_overview` ...
- 写入类（可开关）：`add_to_diary`, `create_node`, `update_node`, `create_relations` ...

工具列表由运行时配置决定，例如：

- `rag.enabled=true` 且配置了 `rag.api_key` 时才会出现 `rag_search`
- `graphiti.enabled=true` 时才会出现 `graphiti_*` 工具
- `--enable-write=false` 时不会暴露写入类工具

---

## 2. 启动方式（手动）

在项目根目录执行：

```bash
python standalone_memory_mcp/server.py --project-root . --config ./config.jsonc --enable-write true
```

参数说明：

- `--project-root`: 记忆项目根目录（默认自动推断为当前仓库根）
- `--config`: 配置文件路径（默认 `<project-root>/config.jsonc`）
- `--enable-write`: 是否暴露写入工具（`true/false`，默认 `true`）

---

## 3. Claude Code 配置示例

在 Claude Code 的 MCP 配置中添加（示意）：

```json
{
  "mcpServers": {
    "lifebook-memory": {
      "command": "python",
      "args": [
        "I:/api/memory/standalone_memory_mcp/server.py",
        "--project-root",
        "I:/api/memory",
        "--config",
        "I:/api/memory/config.jsonc",
        "--enable-write",
        "true"
      ]
    }
  }
}
```

> 如果你不希望外部项目写入记忆，把 `--enable-write` 改成 `false`。

---

## 4. 通用 MCP 客户端配置示例（stdio）

```json
{
  "mcpServers": {
    "lifebook-memory": {
      "command": "python",
      "args": [
        "I:/api/memory/standalone_memory_mcp/server.py",
        "--project-root",
        "I:/api/memory",
        "--config",
        "I:/api/memory/config.jsonc",
        "--enable-write",
        "true"
      ]
    }
  }
}
```

---

## 5. 设计说明

- 服务协议：JSON-RPC over stdio（MCP 常规模式）
- 支持方法：
  - `initialize`
  - `notifications/initialized`
  - `tools/list`
  - `tools/call`
- 所有工具调用最终转发到现有 `MemoryTools.call_tool(...)`

---

## 6. 常见问题

### Q1: 外部客户端看不到某些工具？
检查 `config.jsonc` 中对应模块是否启用：
- RAG 工具：`rag.enabled` + `rag.api_key`
- Graphiti 工具：`graphiti.enabled`

### Q2: 是否一定要用本项目环境？
建议使用本项目 Python 环境（依赖齐全），否则可能缺少 `openai`、`numpy`、`graphiti-core` 等依赖。

### Q3: 可以只读吗？
可以，设置 `--enable-write false` 即可，仅暴露读/检索工具。
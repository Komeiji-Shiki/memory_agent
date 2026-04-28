# 配置热重载使用指南

## 概述

LifeBook Memory Agent 现在支持配置热重载，修改配置文件后**无需重启服务**即可生效。

## 功能特性

- 🔄 **自动重载**: 监听配置文件变化，自动应用新配置
- ⚡ **即时生效**: 大部分配置变更立即可用
- 🔒 **安全验证**: 配置变更前自动验证格式
- 📢 **变更通知**: 支持订阅配置变更事件
- 🛡️ **脱敏保护**: API 密钥等敏感信息自动脱敏

## 支持热重载的配置项

以下配置项修改后**无需重启**即可生效：

| 配置项 | 说明 |
|--------|------|
| `debug` | 调试模式 |
| `max_iterations` | 最大迭代次数 |
| `keep_tool_results_count` | 保留工具结果数 |
| `max_retries` | 最大重试次数 |
| `system_prompt` | 系统提示词 |
| `system_prompt_enabled` | 是否启用系统提示词 |
| `auto_execute_mcp_tools` | 自动执行 MCP 工具 |
| `model_routes` | 模型路由配置 |
| `graphiti.*` | Graphiti 相关配置（除后端数据库） |
| `memory_agent.*` | 记忆代理配置 |

## 需要重启的配置项

以下配置项修改后**需要重启服务**才能生效：

| 配置项 | 说明 |
|--------|------|
| `host` | 监听主机 |
| `port` | 监听端口 |
| `mcp_servers` | MCP 服务器配置 |
| `graphiti.backend` | 图数据库后端 |
| `graphiti.kuzu.db_path` | Kuzu 数据库路径 |

## 使用方法

### 1. 自动热重载（默认）

配置文件修改后自动检测并应用：

```python
from proxy.config import get_config

# 获取配置（始终是最新的）
config = get_config()

# 获取特定配置项（支持点号路径）
port = get_config_value("port", 8003)
graphiti_enabled = get_config_value("graphiti.enabled", False)
```

### 2. 手动重载

通过 API 手动触发配置重载：

```bash
# 重载配置
curl -X POST http://localhost:8003/api/memory/config/reload

# 查看配置状态
curl http://localhost:8003/api/memory/config/status

# 查看当前配置（默认脱敏）
curl http://localhost:8003/api/memory/config

# 查看当前配置（明文，调试用）
curl "http://localhost:8003/api/memory/config?reveal_secrets=1"
```

### 3. 订阅配置变更

在代码中监听配置变更事件：

```python
from proxy.config import subscribe_config_changes

def on_config_changed(event):
    print(f"配置已变更: {event.changed_keys}")
    print(f"新配置: {event.new_config}")

# 订阅变更通知
subscribe_config_changes(on_config_changed)
```

### 4. 在代理中使用

DeepSeekProxy 已自动集成配置热重载：

```python
from proxy.deepseek_proxy import DeepSeekProxy

proxy = DeepSeekProxy(api_key="your-key")

# 当配置变更时，代理会自动：
# - 重新初始化 OpenAI 客户端（如果相关配置变更）
# - 记录配置变更日志
```

## API 端点

### GET /api/memory/config

获取当前配置（敏感信息已脱敏）

**响应示例：**
```json
{
  "success": true,
  "config": {
    "host": "0.0.0.0",
    "port": 8003,
    "api_key": "sk****key",
    "debug": false
  }
}
```

### POST /api/memory/config/reload

手动触发配置重载

**响应示例：**
```json
{
  "success": true,
  "message": "配置已重新加载"
}
```

### GET /api/memory/config/status

获取配置热重载状态

**响应示例：**
```json
{
  "success": true,
  "status": {
    "config_exists": true
  }
}
```

### GET /api/memory/config/model_routes

获取当前模型路由配置（默认脱敏，可用于前端模型路由管理页面）

**响应示例：**
```json
{
  "success": true,
  "value": {
    "deepseek-chat": {
      "base_url": "https://api.deepseek.com/v1",
      "actual_model": "deepseek-chat",
      "thinking_mode": true,
      "api_key": "sk****key"
    }
  }
}
```

## 实现原理

### 文件监听

使用轮询方式监听配置文件变化：

```python
class ConfigFileWatcher:
    def _watch_loop(self):
        while self._running:
            if self._file_changed():
                self._on_change()
            time.sleep(1.0)  # 轮询间隔
```

### 配置验证

使用 Pydantic 验证配置格式：

```python
from proxy.config_validator import ConfigValidator

# 验证并修正配置
validated_config = ConfigValidator.validate_dict(config)
```

### 变更检测

递归检测配置变化：

```python
def _detect_changes(old_config, new_config):
    changes = set()
    # 递归比较两个字典
    # 返回变更的键路径集合
    return changes
```

## 注意事项

1. **轮询间隔**: 默认每秒检查一次文件变化，可在初始化时调整
2. **并发安全**: 配置读取是线程安全的，使用读写锁保护
3. **错误处理**: 配置文件格式错误时会保留旧配置
4. **日志记录**: 配置变更会记录在日志中，便于追踪

## 故障排查

### 配置未生效

1. 检查配置文件路径是否正确
2. 查看日志是否有错误信息
3. 手动调用 [`POST /api/memory/config/reload`](web/config_routes.py:149) 测试

### 热重载不工作

1. 检查 `proxy/config_hot_reload.py` 是否存在
2. 查看启动日志是否显示 "开始监听配置文件"
3. 检查文件权限是否正确

### 配置验证失败

1. 检查 JSON 语法是否正确（可使用 JSONC 注释）
2. 查看 [`GET /api/memory/config/status`](web/config_routes.py:162) 与服务日志中的错误信息
3. 参考 [`config.jsonc.example`](config.jsonc.example) 检查配置项

## 示例：动态调整日志级别

```python
# 在配置文件中
{
    "debug": false,  // 改为 true 启用调试模式
    "log_level": "INFO"  // 可动态调整为 DEBUG/INFO/WARNING/ERROR
}
```

修改保存后，无需重启服务，日志级别立即生效！
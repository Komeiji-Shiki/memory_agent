# LifeBook Memory Agent 快速启动指南 🐱

## 1. 安装依赖

```bash
pip install -r requirements.txt
```

需要的包：
- `flask`, `flask-cors` - Web服务器
- `jieba` - 中文分词（记忆索引）
- `pyyaml` - YAML解析（Markdown frontmatter）
- `requests` - HTTP客户端

## 2. 配置 API Key

编辑 `config.jsonc`，至少需要配置：

```jsonc
{
    // 主API Key（用于默认请求转发）
    "api_key": "你的DeepSeek API Key",
    
    // 记忆Agent使用的Key（留空则用上面的api_key）
    "memory_agent": {
        "api_key": "",  // 留空即可
        // ...
    }
}
```

### 如果要使用其他模型（可选）

```jsonc
"model_routes": {
    "claude-3-5-sonnet": {
        "api_key": "你的Anthropic Key",
        // ...
    },
    "gpt-4o": {
        "api_key": "你的OpenAI Key",
        // ...
    }
}
```

## 3. 启动服务器

```bash
python proxy_server.py
```

默认监听：`http://0.0.0.0:8003`

管理面板：`http://127.0.0.1:8003/lifebook-admin`

## 4. 使用方式

### 记忆增强模式

在任何支持 OpenAI API 的客户端中，可以使用以下模型后缀：

#### `-memory`：标准记忆增强
```
模型: claude-3-5-sonnet-memory
模型: gpt-4o-memory
模型: deepseek-v3-memory
```

流程：
1. 小模型 Agent 检索相关记忆
2. 组装上下文注入到消息中
3. 主模型生成回复
4. 主模型如有需要，可继续调用记忆工具补充查询

#### `-memory-simple`：简化记忆增强
```
模型: claude-3-5-sonnet-memory-simple
模型: gpt-4o-memory-simple
```

流程：
1. 小模型 Agent 检索相关记忆
2. 组装上下文注入到消息中
3. 主模型直接基于增强上下文回复
4. **主模型不能继续调用记忆工具**

适合希望回复更稳定、更少额外工具调用的场景。

#### `-record`：只记录不检索
```
模型: claude-3-5-sonnet-record
模型: gpt-4o-record
```

流程：
1. 不进行 Agent 检索
2. 注入固定记忆（如最近日记、总结）
3. 主模型直接回复
4. 对话结束后自动生成摘要并写入 pending 暂存区

适合追求低延迟，但仍希望保留后续总结能力的场景。

#### `-log`：只写原始对话日志
```
模型: claude-3-5-sonnet-log
模型: gpt-4o-log
```

流程：
1. 不进行 Agent 检索
2. 注入固定记忆（如最近日记、总结）
3. 主模型直接回复
4. 仅保存原始对话到 JSONL，不触发对话后总结

适合只想保留原始会话记录、不想额外消耗总结模型调用的场景。

#### `-log-write`：日志模式 + 主模型可直接操作记忆
```
模型: claude-3-5-sonnet-log-write
模型: gpt-4o-log-write
```

流程：
1. 不进行 Agent 检索
2. 注入固定记忆（如最近日记、总结）
3. 主模型可直接调用记忆读写工具
4. 仅保存原始对话到 JSONL，不触发对话后总结

适合希望保留 [`-log`](memory_router.py:445) 的低开销日志策略，但又想让主模型直接读写记忆库的场景。

### 记忆管理模式

使用特定模型 ID 直接管理记忆：

```
模型: memory-manager
模型: memory-agent
模型: lifebook
```

此模式下可以：
- 搜索、读取记忆
- **写入**新日记、节点
- 直接整理和维护记忆库内容

### 直接透传模式

使用不带后缀的模型名，直接转发到后端：

```
模型: deepseek-v3
模型: claude-3-5-sonnet
```

此模式下不会进行记忆检索、固定记忆注入或记忆管理。

## 5. 目录结构

```
lifebook/
├── daily/           # 每日日记 (YYYY-MM-DD.md)
├── weekly/          # 周总结 (YYYY-WNN.md)
├── monthly/         # 月总结 (YYYY-MM.md)
├── quarterly/       # 季度总结
├── yearly/          # 年度总结
└── nodes/           # 知识节点
    ├── 人物-*.md
    ├── 概念-*.md
    └── ...
```

## 6. Web管理API（可选）

启用后可通过HTTP接口管理记忆：

```
GET  /api/memory/diaries      # 列出日记
GET  /api/memory/diary/2025-12-29  # 获取日记
POST /api/memory/search       # 搜索记忆
POST /api/memory/backup       # 创建备份
GET  /api/memory/stats        # 统计信息
```

## 7. 备份

### 命令行备份

```bash
python web/backup.py backup ./lifebook -o ./backups
```

### 恢复

```bash
python web/backup.py restore ./backups/lifebook_backup_xxx.zip ./lifebook_restored
```

---

## 常见问题

### Q: 需要什么Python版本？
A: Python 3.8+

### Q: jieba安装失败？
A: Windows用户可能需要：`pip install jieba --user`

### Q: 记忆没有被检索到？
A: 
1. 检查 `lifebook/` 目录下是否有.md文件
2. 运行 `POST /api/memory/rebuild-index` 重建索引

### Q: 如何禁用记忆功能？
A: 在 `config.jsonc` 中设置 `"memory_enabled": false`

---

*Made with 💜 by 灰魂* 😸
# Memory Enhanced 安装指南

## 📦 快速安装（3步搞定）

### 步骤1：安装Python依赖

```bash
pip install google-generativeai numpy
```

### 步骤2：配置Gemini API Key

#### 获取API Key
1. 访问：https://makersuite.google.com/app/apikey
2. 登录Google账号
3. 点击「Create API Key」
4. 复制生成的key

#### 配置Key
编辑 `mcp_servers/memory_enhanced/config.json`：

```json
{
  "env": {
    "GEMINI_API_KEY": "粘贴你的API Key"
  }
}
```

### 步骤3：重启代理服务器

```bash
python proxy_server.py
```

**完成！** 🎉

---

## ✅ 验证安装

启动后应该看到：

```
从 mcp_servers 目录加载了 5 个服务配置
...
STDIO MCP 服务器 memory_enhanced 已启动，注册了 3 个工具
...
MCP 工具: 10+ 个可用
```

---

## 🔧 常见问题

### Q1: 提示"google-generativeai未安装"

**解决**：
```bash
pip install google-generativeai
```

如果还是不行：
```bash
pip install --upgrade google-generativeai
```

### Q2: 提示"Gemini API未配置"

**原因**：config.json中的API Key未设置

**解决**：检查config.json中的`GEMINI_API_KEY`是否填写

### Q3: 提示"API请求失败"

**可能原因**：
1. API Key错误 → 重新检查key
2. 网络问题 → 检查能否访问Google服务
3. 配额用完 → 免费版60次/分钟，等待一分钟

**临时方案**：服务会自动降级为关键词搜索

### Q4: 服务启动慢

**正常现象**：首次启动需要为所有实体生成向量

- 100个实体 ≈ 5-10秒
- 1000个实体 ≈ 30-60秒

后续启动会快很多（向量已缓存在内存）

---

## 🌐 网络问题

### 国内访问Google API

如果无法直接访问，可以：

1. **使用代理**
```bash
# Windows
set HTTP_PROXY=http://127.0.0.1:7890
set HTTPS_PROXY=http://127.0.0.1:7890

# Linux/Mac
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

2. **或者暂时禁用（使用关键词搜索）**
```json
{
  "env": {
    "GEMINI_API_KEY": ""  // 留空，自动降级
  }
}
```

---

## 📊 性能优化

### 减少向量化开销

如果实体很多（>1000），可以：

1. **分批处理**：服务会自动分批，无需手动处理

2. **定期清理**：删除不需要的旧实体
```python
# 使用官方memory工具清理
delete_entities(["旧实体1", "旧实体2"])
```

3. **使用类型过滤**：查询时指定entity_type
```json
{
  "entity_type": "person"  // 只搜索人物
}
```

---

## 🔄 与官方Memory共存

可以同时启用两个服务：

```
mcp_servers/
├── memory/          # 官方版本
├── memory_enhanced/ # 增强版本
```

在`enabled.txt`中：
```
memory
memory_enhanced
```

**使用场景**：
- 写入：用官方memory的create_entities等
- 读取：用memory_enhanced的rag_search

---

## 📝 测试连接

创建测试文件 `test_gemini.py`：

```python
import google.generativeai as genai
import os

# 设置API Key
genai.configure(api_key="你的key")

# 测试embedding
result = genai.embed_content(
    model="models/gemini-embedding-001",
    content="测试文本",
    task_type="retrieval_document"
)

print("✓ Gemini连接成功！")
print(f"向量维度: {len(result['embedding'])}")
```

运行：
```bash
python test_gemini.py
```

如果成功，说明API配置正确！

---

## 🎯 下一步

1. 查看 [README.md](README.md) 了解功能
2. 尝试使用 `rag_search` 工具
3. 用 `list_entity_names` 浏览记忆

祝使用愉快！🚀
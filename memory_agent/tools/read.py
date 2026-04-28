"""
Read Tools - 只读工具模块
"""

from datetime import datetime
from typing import List, Dict, Any
from .base import ToolCategory, ToolDefinition


class ReadToolsMixin:
    """只读工具 Mixin"""
    
    def _register_read_tools(self):
        """注册只读工具"""
        # 读取日记
        self.tools["read_diary"] = ToolDefinition(
            name="read_diary",
            description="读取指定日期的日记完整内容。",
            parameters={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期，格式 YYYY-MM-DD"
                    }
                },
                "required": ["date"]
            },
            category=ToolCategory.READ,
            handler=self._read_diary
        )
        
        # 读取总结
        self.tools["read_summary"] = ToolDefinition(
            name="read_summary",
            description="读取周/月/季/年总结。",
            parameters={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["weekly", "monthly", "quarterly", "yearly"],
                        "description": "总结类型"
                    },
                    "identifier": {
                        "type": "string",
                        "description": "标识符，如 2025-W01、2025-01、2025-Q1、2025"
                    }
                },
                "required": ["type", "identifier"]
            },
            category=ToolCategory.READ,
            handler=self._read_summary
        )
        
        # 获取节点
        self.tools["get_node"] = ToolDefinition(
            name="get_node",
            description="获取人物/地点/事物/概念节点的详细信息。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "节点名称"
                    }
                },
                "required": ["name"]
            },
            category=ToolCategory.READ,
            handler=self._get_node
        )
        
        # 列出节点
        self.tools["list_nodes"] = ToolDefinition(
            name="list_nodes",
            description="列出所有节点。",
            parameters={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["all", "人物", "地点", "事物", "概念"],
                        "description": "节点类型筛选",
                        "default": "all"
                    }
                }
            },
            category=ToolCategory.READ,
            handler=self._list_nodes
        )
        
        # 列出最近日记
        self.tools["list_recent"] = ToolDefinition(
            name="list_recent",
            description="列出最近N天的日记。",
            parameters={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "天数，默认7天",
                        "default": 7
                    }
                }
            },
            category=ToolCategory.READ,
            handler=self._list_recent
        )
        
        # 获取当前时间上下文
        self.tools["get_current_context"] = ToolDefinition(
            name="get_current_context",
            description="获取当前时间上下文信息。",
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.READ,
            handler=self._get_current_context
        )
        
        # 列出所有标签
        self.tools["list_all_tags"] = ToolDefinition(
            name="list_all_tags",
            description="列出所有标签。",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制",
                        "default": 20
                    }
                }
            },
            category=ToolCategory.READ,
            handler=self._list_all_tags
        )
        
        # 列出所有人物
        self.tools["list_all_people"] = ToolDefinition(
            name="list_all_people",
            description="列出所有人物。",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制",
                        "default": 20
                    }
                }
            },
            category=ToolCategory.READ,
            handler=self._list_all_people
        )
        
        # 获取记忆概览
        self.tools["get_memory_overview"] = ToolDefinition(
            name="get_memory_overview",
            description="获取记忆系统的全局概览。",
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.READ,
            handler=self._get_memory_overview
        )
        
        # 读取知识图谱
        self.tools["read_graph"] = ToolDefinition(
            name="read_graph",
            description="读取知识图谱（包含节点关系和反向链接）。",
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.READ,
            handler=self._read_graph
        )
        
        # 读取所有节点内容
        self.tools["read_all_nodes"] = ToolDefinition(
            name="read_all_nodes",
            description="一键读取所有节点的完整内容。",
            parameters={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["all", "人物", "地点", "事物", "概念"],
                        "description": "节点类型筛选",
                        "default": "all"
                    },
                    "max_content_length": {
                        "type": "integer",
                        "description": "内容最大长度，0表示不限制",
                        "default": 0
                    }
                }
            },
            category=ToolCategory.READ,
            handler=self._read_all_nodes
        )
    
    def _read_diary(self, date: str) -> str:
        """读取日记"""
        try:
            diary = self.reader.read_diary(date)
            if diary:
                output = f"# {date} 的日记\\n\\n"
                output += diary.content
                if diary.tags:
                    output += f"\\n\\n标签: {', '.join(f'#{t}' for t in diary.tags)}"
                return output
            else:
                return f"未找到 {date} 的日记。"
        except Exception as e:
            return f"读取日记出错: {str(e)}"
    
    def _read_summary(self, type: str, identifier: str) -> str:
        """读取总结"""
        try:
            summary = self.reader.read_summary(type, identifier)
            if summary:
                output = f"# {type} 总结: {identifier}\\n\\n"
                output += summary.content
                return output
            else:
                return f"未找到 {type} 总结 {identifier}。"
        except Exception as e:
            return f"读取总结出错: {str(e)}"
    
    def _get_node(self, name: str) -> str:
        """获取节点"""
        try:
            node = self.reader.read_node(name)
            if node:
                output = f"# {node.name}\\n\\n"
                output += f"类型: {node.type}\\n"
                if node.tags:
                    output += f"标签: {', '.join(f'#{t}' for t in node.tags)}\\n"
                output += f"\\n{node.content}"
                if node.links:
                    output += f"\\n\\n关联: {', '.join(f'[[{l}]]' for l in node.links)}"
                return output
            else:
                return f"未找到节点 [[{name}]]。"
        except Exception as e:
            return f"获取节点出错: {str(e)}"
    
    def _list_nodes(self, type: str = "all") -> str:
        """列出节点"""
        from pathlib import Path
        
        try:
            nodes_dir = Path(self.lifebook_path) / "nodes"
            if not nodes_dir.exists():
                return "节点目录不存在。"
            
            nodes_by_type = {"人物": [], "地点": [], "事物": [], "概念": []}
            
            for file in nodes_dir.glob("*.md"):
                name = file.stem
                for t in ["人物", "地点", "事物", "概念"]:
                    if name.startswith(f"{t}-"):
                        node_name = name[len(t)+1:]
                        nodes_by_type[t].append(node_name)
                        break
            
            if type != "all":
                if type in nodes_by_type:
                    nodes_by_type = {type: nodes_by_type[type]}
                else:
                    return f"未知类型：{type}"
            
            total = sum(len(v) for v in nodes_by_type.values())
            if total == 0:
                return "暂无节点。"
            
            output = f"📋 节点列表（共 {total} 个）：\\n\\n"
            for t, nodes in nodes_by_type.items():
                if nodes:
                    output += f"### {t}（{len(nodes)}个）\\n"
                    for n in sorted(nodes):
                        output += f"  - [[{n}]]\\n"
                    output += "\\n"
            
            return output
            
        except Exception as e:
            return f"列出节点出错: {str(e)}"
    
    def _list_recent(self, days: int = 7) -> str:
        """列出最近日记"""
        try:
            diaries = self.reader.read_recent_diaries(days)
            if not diaries:
                return f"最近{days}天没有日记记录。"
            
            output = f"最近{days}天的日记：\\n\\n"
            for diary in diaries:
                output += f"- {diary.date}\\n"
            
            return output
            
        except Exception as e:
            return f"列出日记出错: {str(e)}"
    
    def _get_current_context(self) -> str:
        """获取当前时间上下文"""
        try:
            now = datetime.now()
            iso_cal = now.isocalendar()
            iso_year = iso_cal[0]
            iso_week = iso_cal[1]
            
            weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            
            output = "📆 当前时间上下文：\\n\\n"
            output += f"今天: {now.strftime('%Y-%m-%d')} ({weekday_names[now.weekday()]})\\n"
            
            week_str = f"{iso_year}-W{iso_week:02d}"
            if iso_year != now.year:
                output += f"本周: {week_str}（注：按ISO周历属于{iso_year}年）\\n"
            else:
                output += f"本周: {week_str}\\n"
            
            output += f"本月: {now.strftime('%Y-%m')}\\n"
            output += f"本季度: {now.year}-Q{(now.month - 1) // 3 + 1}\\n"
            output += f"本年: {now.year}\\n"
            
            today_diary = self.reader.read_diary(now.strftime("%Y-%m-%d"))
            if today_diary:
                output += f"\\n✓ 今天已有日记记录"
            else:
                output += f"\\n✗ 今天尚无日记记录"
            
            return output
            
        except Exception as e:
            return f"获取时间上下文出错: {str(e)}"
    
    def _list_all_tags(self, limit: int = 20) -> str:
        """列出所有标签"""
        try:
            tags = self.indexer.get_all_tags()[:limit]
            
            if not tags:
                return "暂无标签记录。"
            
            output = f"🏷️ 标签列表（前{len(tags)}个）：\\n\\n"
            for tag, count in tags:
                output += f"  #{tag}: {count}次\\n"
            
            return output
            
        except Exception as e:
            return f"列出标签出错: {str(e)}"
    
    def _list_all_people(self, limit: int = 20) -> str:
        """列出所有人物"""
        try:
            people = self.indexer.get_all_people()[:limit]
            
            if not people:
                return "暂无人物记录。"
            
            output = f"👥 人物列表（前{len(people)}个）：\\n\\n"
            for person, count in people:
                output += f"  [[{person}]]: 出现{count}次\\n"
            
            return output
            
        except Exception as e:
            return f"列出人物出错: {str(e)}"
    
    def _get_memory_overview(self) -> str:
        """获取记忆系统概览"""
        from pathlib import Path
        
        try:
            output = "# 📚 记忆系统概览\\n\\n"
            
            # 节点统计
            nodes_dir = Path(self.lifebook_path) / "nodes"
            nodes_count = {"人物": 0, "地点": 0, "事物": 0, "概念": 0}
            all_nodes = []
            
            if nodes_dir.exists():
                for file in nodes_dir.glob("*.md"):
                    name = file.stem
                    for t in ["人物", "地点", "事物", "概念"]:
                        if name.startswith(f"{t}-"):
                            nodes_count[t] += 1
                            all_nodes.append((t, name[len(t)+1:]))
                            break
            
            output += "## 节点概览\\n\\n"
            for t, count in nodes_count.items():
                if count > 0:
                    output += f"- **{t}**: {count}个\\n"
            
            if all_nodes:
                output += "\\n### 完整节点列表\\n"
                for t, name in sorted(all_nodes):
                    output += f"- [{t}] [[{name}]]\\n"
            else:
                output += "\\n*暂无节点*\\n"
            
            # 日记统计
            daily_dir = Path(self.lifebook_path) / "daily"
            diary_count = 0
            recent_diaries = []
            
            if daily_dir.exists():
                diary_files = sorted(daily_dir.glob("*.md"), reverse=True)
                diary_count = len(diary_files)
                for f in diary_files[:5]:
                    recent_diaries.append(f.stem)
            
            output += f"\\n## 日记概览\\n\\n"
            output += f"- **总日记数**: {diary_count}篇\\n"
            if recent_diaries:
                output += f"- **最近日记**: {', '.join(recent_diaries)}\\n"
            
            # 标签统计
            tags = self.indexer.get_all_tags()[:10]
            if tags:
                output += f"\\n## 热门标签（前10）\\n\\n"
                for tag, count in tags:
                    output += f"- #{tag}: {count}次\\n"
            
            # 人物统计
            people = self.indexer.get_all_people()[:10]
            if people:
                output += f"\\n## 常提及人物（前10）\\n\\n"
                for person, count in people:
                    output += f"- [[{person}]]: {count}次\\n"
            
            return output
            
        except Exception as e:
            return f"获取概览出错: {str(e)}"
    
    def _read_graph(self) -> str:
        """读取知识图谱"""
        from pathlib import Path
        
        try:
            output = "# 🕸️ 知识图谱\\n\\n"
            
            nodes_dir = Path(self.lifebook_path) / "nodes"
            if not nodes_dir.exists():
                return "知识图谱为空。"
            
            entities = []
            relations = []
            node_name_map = {}
            
            for file in nodes_dir.glob("*.md"):
                name = file.stem
                node_type = None
                node_name = None
                
                for t in ["人物", "地点", "事物", "概念"]:
                    if name.startswith(f"{t}-"):
                        node_type = t
                        node_name = name[len(t)+1:]
                        break
                
                if not node_type or not node_name:
                    continue
                
                node = self.reader.read_node(node_name)
                if node:
                    entity = {
                        "name": node_name,
                        "type": node_type,
                        "links": node.links,
                        "backlinks": []
                    }
                    node_name_map[node_name] = len(entities)
                    entities.append(entity)
                    
                    for link in node.links:
                        relations.append({
                            "from": node_name,
                            "to": link,
                            "type": "关联"
                        })
            
            # 计算反向链接
            for entity in entities:
                for link in entity["links"]:
                    if link in node_name_map:
                        target_idx = node_name_map[link]
                        if entity["name"] not in entities[target_idx]["backlinks"]:
                            entities[target_idx]["backlinks"].append(entity["name"])
            
            output += f"## 实体（{len(entities)}个）\\n\\n"
            for e in entities:
                output += f"### [{e['type']}] {e['name']}\\n"
                if e['links']:
                    output += f"链接（指向）: {', '.join(f'[[{l}]]' for l in e['links'])}\\n"
                if e['backlinks']:
                    output += f"被链接（来自）: {', '.join(f'[[{l}]]' for l in e['backlinks'])}\\n"
                output += "\\n"
            
            # 去重关系
            seen = set()
            unique_relations = []
            for r in relations:
                key = (r['from'], r['to'])
                if key not in seen and (r['to'], r['from']) not in seen:
                    seen.add(key)
                    unique_relations.append(r)
            
            output += f"## 关系（{len(unique_relations)}个）\\n\\n"
            for r in unique_relations:
                output += f"- [[{r['from']}]] --{r['type']}--> [[{r['to']}]]\\n"
            
            return output
            
        except Exception as e:
            return f"读取图谱出错: {str(e)}"
    
    def _read_all_nodes(self, type: str = "all", max_content_length: int = 0) -> str:
        """读取所有节点内容"""
        from pathlib import Path
        
        try:
            nodes_dir = Path(self.lifebook_path) / "nodes"
            if not nodes_dir.exists():
                return "节点目录不存在。"
            
            nodes_by_type = {"人物": [], "地点": [], "事物": [], "概念": []}
            
            for file in nodes_dir.glob("*.md"):
                name = file.stem
                for t in ["人物", "地点", "事物", "概念"]:
                    if name.startswith(f"{t}-"):
                        node_name = name[len(t)+1:]
                        nodes_by_type[t].append(node_name)
                        break
            
            if type != "all":
                if type in nodes_by_type:
                    nodes_by_type = {type: nodes_by_type[type]}
                else:
                    return f"未知类型：{type}"
            
            total = sum(len(v) for v in nodes_by_type.values())
            if total == 0:
                return "暂无节点。"
            
            output = f"# 📖 所有节点内容（共 {total} 个）\\n\\n"
            
            for node_type, node_names in nodes_by_type.items():
                if not node_names:
                    continue
                
                output += f"## {node_type}（{len(node_names)}个）\\n\\n"
                
                for node_name in sorted(node_names):
                    node = self.reader.read_node(node_name)
                    if node:
                        output += f"### 📌 {node_name}\\n\\n"
                        
                        content = node.content
                        if max_content_length > 0 and len(content) > max_content_length:
                            content = content[:max_content_length] + f"\\n... (已截断)"
                        
                        output += content + "\\n"
                        
                        if node.tags:
                            output += f"\\n标签: {', '.join(f'#{t}' for t in node.tags)}\\n"
                        if node.links:
                            output += f"关联: {', '.join(f'[[{l}]]' for l in node.links)}\\n"
                        
                        output += "\\n---\\n\\n"
            
            return output
            
        except Exception as e:
            return f"读取节点出错: {str(e)}"
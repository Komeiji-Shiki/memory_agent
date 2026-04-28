"""
Write Tools - 写入工具模块
"""

import os
from typing import List, Dict, Any
from .base import ToolCategory, ToolDefinition


class WriteToolsMixin:
    """写入工具 Mixin"""
    
    def _register_write_tools(self):
        """注册写入工具"""
        if not self.enable_write:
            return
        
        # 添加到日记
        self.tools["add_to_diary"] = ToolDefinition(
            name="add_to_diary",
            description="向日记追加内容。",
            parameters={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要添加的内容"
                    },
                    "date": {
                        "type": "string",
                        "description": "日期 YYYY-MM-DD，默认今天"
                    },
                    "section": {
                        "type": "string",
                        "description": "节标题（可选）"
                    }
                },
                "required": ["content"]
            },
            category=ToolCategory.WRITE,
            handler=self._add_to_diary
        )
        
        # 创建节点
        self.tools["create_node"] = ToolDefinition(
            name="create_node",
            description="创建新的人物/地点/事物/概念节点。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "节点名称"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["人物", "地点", "事物", "概念"],
                        "description": "节点类型"
                    },
                    "content": {
                        "type": "string",
                        "description": "节点内容"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签列表（可选）"
                    }
                },
                "required": ["name", "type", "content"]
            },
            category=ToolCategory.WRITE,
            handler=self._create_node
        )
        
        # 更新节点
        self.tools["update_node"] = ToolDefinition(
            name="update_node",
            description="更新节点内容。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "节点名称"
                    },
                    "content": {
                        "type": "string",
                        "description": "要追加的内容"
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["append", "replace"],
                        "description": "更新模式",
                        "default": "append"
                    }
                },
                "required": ["name", "content"]
            },
            category=ToolCategory.WRITE,
            handler=self._update_node
        )
        
        # 创建总结
        self.tools["create_summary"] = ToolDefinition(
            name="create_summary",
            description="创建周/月/季/年总结。",
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
                        "description": "标识符，如 2025-W01"
                    },
                    "content": {
                        "type": "string",
                        "description": "总结内容"
                    },
                    "title": {
                        "type": "string",
                        "description": "标题（可选）"
                    }
                },
                "required": ["type", "identifier", "content"]
            },
            category=ToolCategory.WRITE,
            handler=self._create_summary
        )
        
        # 删除节点
        self.tools["delete_node"] = ToolDefinition(
            name="delete_node",
            description="删除节点（需要确认）。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "节点名称"
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "确认删除",
                        "default": False
                    }
                },
                "required": ["name"]
            },
            category=ToolCategory.WRITE,
            handler=self._delete_node
        )
        
        # 删除总结
        self.tools["delete_summary"] = ToolDefinition(
            name="delete_summary",
            description="删除总结（需要确认）。",
            parameters={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "总结类型"
                    },
                    "identifier": {
                        "type": "string",
                        "description": "标识符"
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "确认删除",
                        "default": False
                    }
                },
                "required": ["type", "identifier"]
            },
            category=ToolCategory.WRITE,
            handler=self._delete_summary
        )
        
        # 添加观察
        self.tools["add_observations"] = ToolDefinition(
            name="add_observations",
            description="向节点添加离散事实观察。",
            parameters={
                "type": "object",
                "properties": {
                    "observations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "节点名称"},
                                "contents": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "观察内容列表"
                                }
                            },
                            "required": ["name", "contents"]
                        }
                    }
                },
                "required": ["observations"]
            },
            category=ToolCategory.WRITE,
            handler=self._add_observations
        )
        
        # 创建关系
        self.tools["create_relations"] = ToolDefinition(
            name="create_relations",
            description="创建节点之间的关系。",
            parameters={
                "type": "object",
                "properties": {
                    "relations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string", "description": "源节点"},
                                "to": {"type": "string", "description": "目标节点"},
                                "relation_type": {
                                    "type": "string",
                                    "description": "关系类型，如'朋友'、'同事'、'创建'"
                                }
                            },
                            "required": ["from", "to", "relation_type"]
                        }
                    }
                },
                "required": ["relations"]
            },
            category=ToolCategory.WRITE,
            handler=self._create_relations
        )
    
    def _add_to_diary(self, content: str, date: str = None, section: str = None) -> str:
        """添加到日记"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        try:
            from datetime import datetime
            
            if date is None:
                date = datetime.now().strftime("%Y-%m-%d")
            
            formatted = content
            if section:
                formatted = f"\\n## {section}\\n\\n{content}\\n"
            
            success = self.writer.append_to_diary(date, formatted)
            
            if success:
                file_path = os.path.join(self.lifebook_path, "daily", f"{date}.md")
                self.indexer.index_file(file_path)
                return f"✓ 已添加到 {date} 的日记"
            else:
                return "✗ 添加失败"
                
        except Exception as e:
            return f"添加日记出错: {str(e)}"
    
    def _create_node(
        self,
        name: str,
        type: str,
        content: str,
        tags: List[str] = None
    ) -> str:
        """创建节点"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        try:
            success = self.writer.create_node(
                name=name,
                node_type=type,
                content=content,
                tags=tags or []
            )
            
            if success:
                file_path = os.path.join(self.lifebook_path, "nodes", f"{type}-{name}.md")
                self.indexer.index_file(file_path)
                return f"✓ 已创建 {type} 节点 [[{name}]]"
            else:
                return f"✗ 节点 [[{name}]] 已存在或创建失败"
                
        except Exception as e:
            return f"创建节点出错: {str(e)}"
    
    def _update_node(
        self,
        name: str,
        content: str,
        mode: str = "append"
    ) -> str:
        """更新节点"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        try:
            success = self.writer.update_node(name, content, mode=mode)
            
            if success:
                return f"✓ 已更新节点 [[{name}]] ({mode}模式)"
            else:
                return f"✗ 节点 [[{name}]] 不存在或更新失败"
                
        except Exception as e:
            return f"更新节点出错: {str(e)}"
    
    def _create_summary(
        self,
        type: str,
        identifier: str,
        content: str,
        title: str = None
    ) -> str:
        """创建总结"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        try:
            success = self.writer.create_summary(type, identifier, content, title)
            
            if success:
                file_path = os.path.join(self.lifebook_path, type, f"{identifier}.md")
                self.indexer.index_file(file_path)
                return f"✓ 已创建 {type} 总结 {identifier}"
            else:
                return f"✗ 总结创建失败"
                
        except Exception as e:
            return f"创建总结出错: {str(e)}"
    
    def _delete_node(self, name: str, confirm: bool = False) -> str:
        """删除节点"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        if not confirm:
            return f"⚠️ 删除操作需要确认。请设置 confirm=true 来确认删除节点 [[{name}]]。"
        
        from pathlib import Path
        
        try:
            nodes_dir = Path(self.lifebook_path) / "nodes"
            found_file = None
            node_type = None
            
            # 尝试不同格式
            names_to_try = [name]
            for t in ["人物", "地点", "事物", "概念"]:
                if name.startswith(f"{t}-"):
                    stripped = name[len(t)+1:]
                    if stripped not in names_to_try:
                        names_to_try.append(stripped)
                    break
            
            for try_name in names_to_try:
                for t in ["人物", "地点", "事物", "概念"]:
                    file_path = nodes_dir / f"{t}-{try_name}.md"
                    if file_path.exists():
                        found_file = file_path
                        node_type = t
                        break
                if found_file:
                    break
            
            if not found_file:
                return f"✗ 未找到节点 [[{name}]]"
            
            found_file.unlink()
            self.indexer.rebuild_index()
            return f"✓ 已永久删除 {node_type} 节点 [[{name}]]"
            
        except Exception as e:
            return f"删除节点出错: {str(e)}"
    
    def _delete_summary(self, type: str, identifier: str, confirm: bool = False) -> str:
        """删除总结"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        if not confirm:
            return f"⚠️ 删除操作需要确认。请设置 confirm=true 来确认删除 {type} 总结 {identifier}。"
        
        from pathlib import Path
        
        try:
            summary_file = Path(self.lifebook_path) / type / f"{identifier}.md"
            
            if not summary_file.exists():
                return f"✗ 未找到 {type} 总结 {identifier}"
            
            summary_file.unlink()
            self.indexer.rebuild_index()
            return f"✓ 已永久删除 {type} 总结 {identifier}"
            
        except Exception as e:
            return f"删除总结出错: {str(e)}"
    
    def _add_observations(self, observations: List[Dict[str, Any]]) -> str:
        """添加观察"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        try:
            results = []
            
            for obs in observations:
                name = obs.get("name", "")
                contents = obs.get("contents", [])
                
                if not name or not contents:
                    continue
                
                node = self.reader.read_node(name)
                if not node:
                    results.append(f"✗ 节点 [[{name}]] 不存在")
                    continue
                
                obs_content = "\\n\\n## 观察记录\\n\\n"
                for content in contents:
                    obs_content += f"- {content}\\n"
                
                success = self.writer.update_node(name, obs_content, mode="append")
                if success:
                    results.append(f"✓ 向 [[{name}]] 添加了 {len(contents)} 条观察")
                else:
                    results.append(f"✗ 更新 [[{name}]] 失败")
            
            return "\\n".join(results) if results else "没有添加任何观察"
            
        except Exception as e:
            return f"添加观察出错: {str(e)}"
    
    def _create_relations(self, relations: List[Dict[str, Any]]) -> str:
        """创建关系"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        try:
            results = []
            
            for rel in relations:
                from_node = rel.get("from", "")
                to_node = rel.get("to", "")
                relation_type = rel.get("relation_type", "关联")
                
                if not from_node or not to_node:
                    continue
                
                node_from = self.reader.read_node(from_node)
                node_to = self.reader.read_node(to_node)
                
                errors = []
                if not node_from:
                    errors.append(f"[[{from_node}]]")
                if not node_to:
                    errors.append(f"[[{to_node}]]")
                
                if errors:
                    results.append(f"✗ 节点不存在: {', '.join(errors)}")
                    continue
                
                # 在 from_node 添加链接
                link_content = f"\\n\\n### 关联：{relation_type}\\n\\n- [[{to_node}]]（{relation_type}）\\n"
                self.writer.update_node(from_node, link_content, mode="append")
                
                # 在 to_node 添加反向链接
                reverse_content = f"\\n\\n### 被关联\\n\\n- [[{from_node}]]（{relation_type} 的对象）\\n"
                self.writer.update_node(to_node, reverse_content, mode="append")
                
                results.append(f"✓ 创建关系: [[{from_node}]] --{relation_type}--> [[{to_node}]]")
            
            return "\\n".join(results) if results else "没有创建任何关系"
            
        except Exception as e:
            return f"创建关系出错: {str(e)}"
"""
Edit Tools - 编辑工具模块

提供类似 apply_diff 的精确编辑功能。
"""

import re
from pathlib import Path
from typing import Optional
from .base import ToolCategory, ToolDefinition


class EditToolsMixin:
    """编辑工具 Mixin"""
    
    def _register_edit_tools(self):
        """注册编辑工具"""
        if not self.enable_write:
            return
        
        # 编辑日记
        self.tools["edit_diary"] = ToolDefinition(
            name="edit_diary",
            description="精确编辑日记内容（类似 apply_diff）。使用 search 和 replace 进行精确替换。",
            parameters={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期 YYYY-MM-DD"
                    },
                    "search": {
                        "type": "string",
                        "description": "要查找的内容（原文片段）"
                    },
                    "replace": {
                        "type": "string",
                        "description": "替换为的内容"
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "是否替换所有匹配项",
                        "default": False
                    }
                },
                "required": ["date", "search", "replace"]
            },
            category=ToolCategory.WRITE,
            handler=self._edit_diary
        )
        
        # 重写日记
        self.tools["rewrite_diary"] = ToolDefinition(
            name="rewrite_diary",
            description="完全重写日记正文，保留 frontmatter。",
            parameters={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期 YYYY-MM-DD"
                    },
                    "content": {
                        "type": "string",
                        "description": "新正文内容"
                    },
                    "title": {
                        "type": "string",
                        "description": "新标题（可选）"
                    }
                },
                "required": ["date", "content"]
            },
            category=ToolCategory.WRITE,
            handler=self._rewrite_diary
        )
        
        # 编辑节点
        self.tools["edit_node"] = ToolDefinition(
            name="edit_node",
            description="精确编辑节点内容（类似 apply_diff）。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "节点名称"
                    },
                    "search": {
                        "type": "string",
                        "description": "要查找的内容"
                    },
                    "replace": {
                        "type": "string",
                        "description": "替换为的内容"
                    }
                },
                "required": ["name", "search", "replace"]
            },
            category=ToolCategory.WRITE,
            handler=self._edit_node
        )
        
        # 编辑总结
        self.tools["edit_summary"] = ToolDefinition(
            name="edit_summary",
            description="精确编辑总结内容（类似 apply_diff）。",
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
                    "search": {
                        "type": "string",
                        "description": "要查找的内容"
                    },
                    "replace": {
                        "type": "string",
                        "description": "替换为的内容"
                    }
                },
                "required": ["type", "identifier", "search", "replace"]
            },
            category=ToolCategory.WRITE,
            handler=self._edit_summary
        )
    
    def _edit_diary(
        self,
        date: str,
        search: str,
        replace: str,
        replace_all: bool = False
    ) -> str:
        """编辑日记"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        diary_file = Path(self.lifebook_path) / "daily" / f"{date}.md"
        
        if not diary_file.exists():
            return f"✗ 未找到 {date} 的日记"
        
        try:
            content = diary_file.read_text(encoding=self.encoding)
            
            if search not in content:
                preview = content[:500] + "..." if len(content) > 500 else content
                return f"✗ 未找到要替换的内容。\\n\\n日记内容预览:\\n```\\n{preview}\\n```"
            
            if replace_all:
                new_content = content.replace(search, replace)
                match_count = content.count(search)
            else:
                new_content = content.replace(search, replace, 1)
                match_count = 1
            
            if new_content == content:
                return "✗ 替换未生效（内容相同）"
            
            diary_file.write_text(new_content, encoding=self.encoding)
            self.indexer.index_file(str(diary_file))
            
            if replace == "":
                action = "删除"
                detail = f"已删除 {len(search) * match_count} 个字符"
            elif search == "":
                action = "插入"
                detail = f"已插入 {len(replace)} 个字符"
            else:
                action = "替换"
                if replace_all and match_count > 1:
                    detail = f"已替换全部 {match_count} 处匹配"
                else:
                    detail = f"已将匹配的 {len(search)} 个字符替换为 {len(replace)} 个字符"
            
            return f"✓ {date} 日记编辑成功：{detail}。"
            
        except Exception as e:
            return f"✗ 编辑日记失败: {str(e)}"
    
    def _rewrite_diary(self, date: str, content: str, title: Optional[str] = None) -> str:
        """重写日记"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        diary_file = Path(self.lifebook_path) / "daily" / f"{date}.md"
        
        if not diary_file.exists():
            return f"✗ 未找到 {date} 的日记"
        
        try:
            old_content = diary_file.read_text(encoding=self.encoding)
            
            # 解析 frontmatter
            frontmatter = ""
            body_start = 0
            
            if old_content.startswith("---"):
                end_match = re.search(r'\n---\s*\n', old_content[3:])
                if end_match:
                    frontmatter_end = 3 + end_match.end()
                    frontmatter = old_content[:frontmatter_end]
                    body_start = frontmatter_end
            
            if not frontmatter:
                frontmatter = f"""---\ndate: {date}\n---\n\n"""
            
            # 更新标题
            if title:
                if 'title:' in frontmatter:
                    frontmatter = re.sub(r'title:.*\n', f'title: {title}\n', frontmatter)
                else:
                    frontmatter = re.sub(r'(date:.*\n)', f'\\1title: {title}\n', frontmatter)
            
            new_content = frontmatter + content
            if not new_content.endswith('\n'):
                new_content += '\n'
            
            diary_file.write_text(new_content, encoding=self.encoding)
            self.indexer.index_file(str(diary_file))
            
            old_body = old_content[body_start:]
            old_len = len(old_body.strip())
            new_len = len(content.strip())
            
            return f"✓ {date} 日记已重写！\\n  - 原正文: {old_len} 字符\\n  - 新正文: {new_len} 字符"
            
        except Exception as e:
            return f"✗ 重写日记失败: {str(e)}"
    
    def _edit_node(self, name: str, search: str, replace: str) -> str:
        """编辑节点"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        nodes_dir = Path(self.lifebook_path) / "nodes"
        found_file = None
        
        for t in ["人物", "地点", "事物", "概念"]:
            file_path = nodes_dir / f"{t}-{name}.md"
            if file_path.exists():
                found_file = file_path
                break
        
        if not found_file:
            return f"✗ 未找到节点 [[{name}]]"
        
        try:
            content = found_file.read_text(encoding=self.encoding)
            
            if search not in content:
                preview = content[:500] + "..." if len(content) > 500 else content
                return f"✗ 未找到要替换的内容。\\n\\n当前节点内容预览:\\n```\\n{preview}\\n```"
            
            new_content = content.replace(search, replace, 1)
            
            if new_content == content:
                return "✗ 替换未生效（内容相同）"
            
            found_file.write_text(new_content, encoding=self.encoding)
            self.indexer.index_file(str(found_file))
            
            if replace == "":
                action = "删除"
                detail = f"已移除 {len(search)} 个字符"
            elif search == "":
                action = "插入"
                detail = f"已插入 {len(replace)} 个字符"
            else:
                action = "替换"
                detail = f"已将 {len(search)} 个字符替换为 {len(replace)} 个字符"
            
            return f"✓ 节点 [[{name}]] 编辑成功：{detail}。"
            
        except Exception as e:
            return f"✗ 编辑节点失败: {str(e)}"
    
    def _edit_summary(
        self,
        type: str,
        identifier: str,
        search: str,
        replace: str
    ) -> str:
        """编辑总结"""
        if not self.writer:
            return "错误：写入功能未启用"
        
        summary_file = Path(self.lifebook_path) / type / f"{identifier}.md"
        
        if not summary_file.exists():
            return f"✗ 未找到 {type} 总结 {identifier}"
        
        try:
            content = summary_file.read_text(encoding=self.encoding)
            
            if search not in content:
                preview = content[:500] + "..." if len(content) > 500 else content
                return f"✗ 未找到要替换的内容。\\n\\n当前内容预览:\\n```\\n{preview}\\n```"
            
            new_content = content.replace(search, replace, 1)
            
            if new_content == content:
                return "✗ 替换未生效（内容相同）"
            
            summary_file.write_text(new_content, encoding=self.encoding)
            self.indexer.index_file(str(summary_file))
            
            if replace == "":
                action = "删除"
                detail = f"已移除 {len(search)} 个字符"
            elif search == "":
                action = "插入"
                detail = f"已插入 {len(replace)} 个字符"
            else:
                action = "替换"
                detail = f"已将 {len(search)} 个字符替换为 {len(replace)} 个字符"
            
            return f"✓ {type} 总结 {identifier} 编辑成功：{detail}。"
            
        except Exception as e:
            return f"✗ 编辑总结失败: {str(e)}"
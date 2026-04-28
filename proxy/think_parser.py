"""
Think Tag Parser - 流式思维标签解析器

用于解析模型输出中的 <think>...</think> 标签：
- 检测到 </think> 之前的内容作为 reasoning_content
- </think> 之后的内容作为正文 content

支持流式场景的缓冲机制：
- 检测到 `<` 时进入缓冲模式
- 如果后续字符组成 `/think>`，则标记思考结束
- 如果不匹配则将缓冲内容全部放出
"""

from typing import Tuple, Optional, Generator, Dict, Any
from dataclasses import dataclass, field


@dataclass
class ThinkParserState:
    """解析器状态"""
    in_thinking: bool = True  # 是否在思考区域内
    buffer: str = ""  # 缓冲区
    think_ended: bool = False  # 是否已检测到 </think>
    tag_to_match: str = "</think>"  # 要匹配的结束标签
    match_pos: int = 0  # 当前匹配位置


class StreamThinkParser:
    """
    流式思维标签解析器
    
    用法：
    ```python
    parser = StreamThinkParser(think_tag="</think>")
    
    for chunk in stream:
        reasoning, content = parser.process(chunk)
        if reasoning:
            yield {"reasoning_content": reasoning}
        if content:
            yield {"content": content}
    
    # 处理残余缓冲
    reasoning, content = parser.flush()
    ```
    """
    
    def __init__(self, think_tag: str = "</think>"):
        """
        初始化解析器
        
        Args:
            think_tag: 思考结束标签，默认 "</think>"
        """
        self.think_tag = think_tag.lower()
        self.state = ThinkParserState(tag_to_match=self.think_tag)
    
    def reset(self):
        """重置解析器状态"""
        self.state = ThinkParserState(tag_to_match=self.think_tag)
    
    def process(self, text: str) -> Tuple[str, str]:
        """
        处理一段文本
        
        Args:
            text: 输入文本片段
            
        Returns:
            (reasoning_content, content) 元组
            - 如果在思考区域内，reasoning_content 有值，content 为空
            - 如果已结束思考，reasoning_content 为空，content 有值
            - 边界情况可能两者都有值
        """
        if not text:
            return "", ""
        
        # 如果已经结束思考，直接返回正文
        if self.state.think_ended:
            return "", text
        
        reasoning_out = ""
        content_out = ""
        
        # 将缓冲区内容和新输入合并处理
        combined = self.state.buffer + text
        self.state.buffer = ""
        
        i = 0
        while i < len(combined):
            char = combined[i]
            char_lower = char.lower()
            
            # 检查是否在匹配结束标签
            if self.state.match_pos > 0:
                expected_char = self.think_tag[self.state.match_pos]
                
                if char_lower == expected_char:
                    self.state.match_pos += 1
                    self.state.buffer += char
                    
                    # 完全匹配成功
                    if self.state.match_pos >= len(self.think_tag):
                        # 思考结束，清空缓冲区（不输出结束标签）
                        self.state.buffer = ""
                        self.state.match_pos = 0
                        self.state.think_ended = True
                        self.state.in_thinking = False
                        
                        # 剩余部分作为正文
                        if i + 1 < len(combined):
                            content_out += combined[i + 1:]
                        return reasoning_out, content_out
                else:
                    # 匹配失败，将缓冲区内容放出
                    reasoning_out += self.state.buffer
                    self.state.buffer = ""
                    self.state.match_pos = 0
                    
                    # 重新检查当前字符是否是 '<'
                    if char == '<':
                        self.state.buffer = char
                        self.state.match_pos = 1
                    else:
                        reasoning_out += char
                
                i += 1
                continue
            
            # 检查是否开始匹配 '<'
            if char == '<':
                # 检查是否可能是结束标签的开始
                if self.think_tag.startswith('<'):
                    self.state.buffer = char
                    self.state.match_pos = 1
                else:
                    reasoning_out += char
            else:
                reasoning_out += char
            
            i += 1
        
        return reasoning_out, content_out
    
    def flush(self) -> Tuple[str, str]:
        """
        刷新缓冲区，处理残余内容
        
        Returns:
            (reasoning_content, content) 元组
        """
        if self.state.buffer:
            # 缓冲区有内容说明匹配未完成，作为 reasoning 输出
            if self.state.think_ended:
                result = ("", self.state.buffer)
            else:
                result = (self.state.buffer, "")
            self.state.buffer = ""
            return result
        return "", ""
    
    def is_thinking_ended(self) -> bool:
        """检查思考是否已结束"""
        return self.state.think_ended


def create_stream_parser(think_tag: str = "</think>") -> StreamThinkParser:
    """创建流式解析器实例"""
    return StreamThinkParser(think_tag)


def parse_think_content(text: str, think_tag: str = "</think>") -> Tuple[str, str]:
    """
    一次性解析完整文本
    
    Args:
        text: 完整文本
        think_tag: 思考结束标签
        
    Returns:
        (reasoning_content, content) 元组
    """
    tag_lower = think_tag.lower()
    text_lower = text.lower()
    
    idx = text_lower.find(tag_lower)
    if idx >= 0:
        reasoning = text[:idx]
        content = text[idx + len(think_tag):]
        return reasoning, content
    else:
        # 没找到结束标签，全部作为 reasoning
        return text, ""


# 便捷函数：处理流式 chunk
def process_stream_chunk(
    chunk_data: Dict[str, Any],
    parser: StreamThinkParser,
    reasoning_key: str = "reasoning_content",
    content_key: str = "content"
) -> Dict[str, Any]:
    """
    处理流式 SSE chunk 数据
    
    Args:
        chunk_data: 原始 chunk 数据（已解析的 JSON）
        parser: 解析器实例
        reasoning_key: 输出的 reasoning 字段名
        content_key: 输出的 content 字段名
        
    Returns:
        处理后的 chunk 数据
    """
    if "choices" not in chunk_data or not chunk_data["choices"]:
        return chunk_data
    
    choice = chunk_data["choices"][0]
    delta = choice.get("delta", {})
    
    # 获取原始内容
    original_content = delta.get("content", "")
    original_reasoning = delta.get("reasoning_content", "")
    
    # 如果已经有 reasoning_content，说明模型原生支持，不需要解析
    if original_reasoning:
        return chunk_data
    
    # 解析 content
    if original_content:
        reasoning, content = parser.process(original_content)
        
        # 构建新的 delta
        new_delta = {}
        if reasoning:
            new_delta[reasoning_key] = reasoning
        if content:
            new_delta[content_key] = content
        
        # 更新 chunk
        if new_delta:
            chunk_data = chunk_data.copy()
            chunk_data["choices"] = [choice.copy()]
            chunk_data["choices"][0]["delta"] = new_delta
        else:
            # 没有输出，返回空 delta
            chunk_data = chunk_data.copy()
            chunk_data["choices"] = [choice.copy()]
            chunk_data["choices"][0]["delta"] = {}
    
    return chunk_data


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("Think Parser 测试")
    print("=" * 60)
    
    # 测试1：完整文本解析
    print("\n测试1：完整文本解析")
    text = "让我思考一下...\n分析问题...\n</think>这是我的回答。"
    reasoning, content = parse_think_content(text)
    print(f"Reasoning: {reasoning[:50]}...")
    print(f"Content: {content}")
    
    # 测试2：流式解析
    print("\n测试2：流式解析")
    chunks = ["让我", "思考", "...</", "think>", "这是回答"]
    parser = StreamThinkParser()
    
    for chunk in chunks:
        r, c = parser.process(chunk)
        print(f"Chunk '{chunk}' -> reasoning='{r}', content='{c}'")
    
    r, c = parser.flush()
    print(f"Flush -> reasoning='{r}', content='{c}'")
    
    # 测试3：边界情况 - 单字符流
    print("\n测试3：单字符流")
    parser2 = StreamThinkParser()
    text2 = "Hi</think>OK"
    for char in text2:
        r, c = parser2.process(char)
        if r or c:
            print(f"'{char}' -> r='{r}', c='{c}'")
    r, c = parser2.flush()
    if r or c:
        print(f"Flush -> r='{r}', c='{c}'")
    
    print("\n测试完成！[OK]")
"""
Anthropic/Gemini 原生格式端点的共用工具

负责解析内部 OpenAI SSE 流与拆解 Flask 视图返回值。
"""

import json


def iter_openai_sse(raw_iter):
    """解析内部 OpenAI SSE 流，逐个产出 JSON payload

    Args:
        raw_iter: 内部 Response 的原始迭代器（str 或 bytes 片段）

    Yields:
        dict: 解析出的 chunk payload；遇到 [DONE] 时产出 None
    """
    buffer = ''
    for piece in raw_iter:
        if isinstance(piece, bytes):
            piece = piece.decode('utf-8', errors='replace')
        buffer += piece
        while '\n\n' in buffer:
            event_text, buffer = buffer.split('\n\n', 1)
            for line in event_text.splitlines():
                line = line.strip()
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if payload == '[DONE]':
                    yield None
                else:
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        pass


def unwrap_response(resp):
    """拆解 Flask 视图返回值（Response 或 (Response, status) 元组）

    Returns:
        (response, status_code)
    """
    if isinstance(resp, tuple):
        return resp[0], resp[1]
    return resp, getattr(resp, 'status_code', 200)

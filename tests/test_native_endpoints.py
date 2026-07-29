"""Anthropic/Gemini 原生格式端点转换层测试

只测纯转换函数与流式状态机，不涉及网络请求。
"""

import json

from proxy.routes.anthropic import (
    anthropic_to_openai_request,
    openai_to_anthropic_response,
    openai_stream_to_anthropic,
)
from proxy.routes.gemini import (
    gemini_to_openai_request,
    openai_to_gemini_response,
    openai_stream_to_gemini,
)
from proxy.routes.native_utils import iter_openai_sse, unwrap_response


def sse(payload):
    """构造一条内部 OpenAI SSE 文本（前缀拼接构造）"""
    return 'da' + 'ta: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'


DONE_LINE = 'da' + 'ta: [DONE]\n\n'


def _chunk(delta, finish=None, usage=None):
    c = {'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
    if usage:
        c['usage'] = usage
    return c


# ==================== native_utils ====================

def test_iter_openai_sse_basic():
    chunks = [sse({'a': 1}), sse({'b': 2}), DONE_LINE]
    out = list(iter_openai_sse(iter(chunks)))
    assert out[0] == {'a': 1}
    assert out[1] == {'b': 2}
    assert out[2] is None


def test_iter_openai_sse_split_pieces():
    full = sse({'x': 'y'})
    pieces = [full[:5], full[5:12], full[12:]]
    out = list(iter_openai_sse(iter(pieces)))
    assert out == [{'x': 'y'}]


def test_iter_openai_sse_skips_bad_json():
    bad = 'da' + 'ta: {broken\n\n'
    out = list(iter_openai_sse(iter([bad, sse({'ok': 1})])))
    assert out == [{'ok': 1}]


def test_unwrap_response_tuple():
    resp, status = unwrap_response(('resp', 401))
    assert resp == 'resp'
    assert status == 401


# ==================== Anthropic ====================

def test_anthropic_request_basic():
    body = {
        'model': 'test-model',
        'max_tokens': 100,
        'system': 'sys prompt',
        'messages': [
            {'role': 'user', 'content': 'hello'},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': 'hi'}]},
        ],
        'temperature': 0.5,
        'stop_sequences': ['END'],
        'stream': True,
    }
    data = anthropic_to_openai_request(body)
    assert data['model'] == 'test-model'
    assert data['max_tokens'] == 100
    assert data['temperature'] == 0.5
    assert data['stop'] == ['END']
    assert data['stream'] is True
    assert data['messages'][0] == {'role': 'system', 'content': 'sys prompt'}
    assert data['messages'][1] == {'role': 'user', 'content': 'hello'}
    assert data['messages'][2]['role'] == 'assistant'
    assert data['messages'][2]['content'] == 'hi'


def test_anthropic_request_tools_and_results():
    body = {
        'model': 'm',
        'max_tokens': 10,
        'messages': [
            {'role': 'user', 'content': 'q'},
            {'role': 'assistant', 'content': [
                {'type': 'tool_use', 'id': 'tu_1', 'name': 'fn', 'input': {'k': 'v'}},
            ]},
            {'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': 'tu_1', 'content': 'result text'},
            ]},
        ],
        'tools': [{'name': 'fn', 'description': 'd', 'input_schema': {'type': 'object'}}],
        'tool_choice': {'type': 'any'},
    }
    data = anthropic_to_openai_request(body)
    tc_msg = data['messages'][1]
    assert tc_msg['tool_calls'][0]['function']['name'] == 'fn'
    assert json.loads(tc_msg['tool_calls'][0]['function']['arguments']) == {'k': 'v'}
    tool_msg = data['messages'][2]
    assert tool_msg['role'] == 'tool'
    assert tool_msg['tool_call_id'] == 'tu_1'
    assert tool_msg['content'] == 'result text'
    assert data['tools'][0]['function']['name'] == 'fn'
    assert data['tool_choice'] == 'required'


def test_anthropic_response_blocks():
    resp = {
        'choices': [{
            'message': {
                'role': 'assistant',
                'content': 'answer',
                'reasoning_content': 'thinking...',
                'tool_calls': [{'id': 'c1', 'function': {'name': 'fn', 'arguments': '{"a": 1}'}}],
            },
            'finish_reason': 'tool_calls',
        }],
        'usage': {'prompt_tokens': 5, 'completion_tokens': 7},
    }
    out = openai_to_anthropic_response(resp, 'm')
    types = [b['type'] for b in out['content']]
    assert types == ['thinking', 'text', 'tool_use']
    assert out['content'][2]['input'] == {'a': 1}
    assert out['stop_reason'] == 'tool_use'
    assert out['usage'] == {'input_tokens': 5, 'output_tokens': 7}
    assert out['model'] == 'm'


def test_anthropic_stream_state_machine():
    raw = [
        sse(_chunk({'reasoning_content': 'think'})),
        sse(_chunk({'content': 'hel'})),
        sse(_chunk({'content': 'lo'})),
        sse(_chunk({}, finish='stop', usage={'completion_tokens': 3})),
        DONE_LINE,
    ]
    events = list(openai_stream_to_anthropic(iter(raw), 'm'))
    text = ''.join(events)
    names = []
    for ev in events:
        for ln in ev.splitlines():
            if ln.startswith('event:'):
                names.append(ln.split(':', 1)[1].strip())
    assert names[0] == 'message_start'
    assert names[-2] == 'message_delta'
    assert names[-1] == 'message_stop'
    # thinking 块 + text 块各开一次
    assert names.count('content_block_start') == 2
    assert names.count('content_block_stop') == 2
    assert 'thinking_delta' in text
    assert 'text_delta' in text
    assert 'end_turn' in text


# ==================== Gemini ====================

def test_gemini_request_basic():
    body = {
        'systemInstruction': {'parts': [{'text': 'sys'}]},
        'contents': [
            {'role': 'user', 'parts': [{'text': 'hello'}]},
            {'role': 'model', 'parts': [{'text': 'hi'}]},
        ],
        'generationConfig': {
            'temperature': 0.7,
            'topP': 0.9,
            'maxOutputTokens': 128,
            'stopSequences': ['X'],
        },
    }
    data = gemini_to_openai_request(body, 'g-model', False)
    assert data['model'] == 'g-model'
    assert data['stream'] is False
    assert data['messages'][0] == {'role': 'system', 'content': 'sys'}
    assert data['messages'][1] == {'role': 'user', 'content': 'hello'}
    assert data['messages'][2]['role'] == 'assistant'
    assert data['temperature'] == 0.7
    assert data['top_p'] == 0.9
    assert data['max_tokens'] == 128
    assert data['stop'] == ['X']


def test_gemini_request_tools():
    body = {
        'contents': [{'role': 'user', 'parts': [{'text': 'q'}]}],
        'tools': [{'functionDeclarations': [
            {'name': 'fn', 'description': 'd', 'parameters': {'type': 'object'}},
        ]}],
    }
    data = gemini_to_openai_request(body, 'm', True)
    assert data['stream'] is True
    assert data['tools'][0]['function']['name'] == 'fn'


def test_gemini_response():
    resp = {
        'choices': [{
            'message': {'role': 'assistant', 'content': 'ans', 'reasoning_content': 'r'},
            'finish_reason': 'length',
        }],
        'usage': {'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': 3},
    }
    out = openai_to_gemini_response(resp, 'm')
    cand = out['candidates'][0]
    assert cand['finishReason'] == 'MAX_TOKENS'
    parts = cand['content']['parts']
    assert parts[0] == {'text': 'r', 'thought': True}
    assert parts[1] == {'text': 'ans'}
    assert out['usageMetadata']['totalTokenCount'] == 3


def test_gemini_stream():
    raw = [
        sse(_chunk({'content': 'a'})),
        sse(_chunk({'content': 'b'})),
        sse(_chunk({}, finish='stop',
                   usage={'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': 3})),
        DONE_LINE,
    ]
    lines = list(openai_stream_to_gemini(iter(raw), 'm'))
    payloads = [json.loads(ln.split(':', 1)[1]) for ln in lines]
    assert payloads[0]['candidates'][0]['content']['parts'][0]['text'] == 'a'
    assert payloads[1]['candidates'][0]['content']['parts'][0]['text'] == 'b'
    final = payloads[-1]
    assert final['candidates'][0]['finishReason'] == 'STOP'
    assert final['usageMetadata']['totalTokenCount'] == 3

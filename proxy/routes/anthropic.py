"""
Anthropic Messages API 兼容端点

提供 POST /v1/messages：接受 Anthropic 原生请求格式，
转换为 OpenAI chat.completions 格式复用现有处理管线（含记忆路由/MCP/模型路由），
再把响应转换回 Anthropic 格式（非流式 message 对象 / 流式事件序列）。
"""

import json
import uuid
import logging

from flask import Blueprint, request, Response, jsonify, stream_with_context

from .native_utils import iter_openai_sse, unwrap_response

anthropic_bp = Blueprint('anthropic', __name__)

_SSE_DATA = 'data: '

_STOP_REASON_MAP = {
    'stop': 'end_turn',
    'length': 'max_tokens',
    'tool_calls': 'tool_use',
}

_ERROR_TYPE_MAP = {
    400: 'invalid_request_error',
    401: 'authentication_error',
    403: 'permission_error',
    404: 'not_found_error',
    429: 'rate_limit_error',
    500: 'api_error',
}


# ==================== 请求转换 ====================

def _tool_result_to_text(block):
    """把 tool_result block 的 content 转成纯文本"""
    content = block.get('content', '')
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text':
                parts.append(item.get('text', ''))
    return '\n'.join(parts)


def anthropic_to_openai_request(body):
    """Anthropic Messages 请求体 -> OpenAI chat.completions 请求体"""
    messages = []

    system = body.get('system')
    if system:
        if isinstance(system, list):
            system = '\n'.join(
                b.get('text', '') for b in system if isinstance(b, dict)
            )
        if system:
            messages.append({'role': 'system', 'content': system})

    for msg in body.get('messages', []) or []:
        role = msg.get('role', 'user')
        content = msg.get('content', '')

        if isinstance(content, str):
            messages.append({'role': role, 'content': content})
            continue

        texts = []
        thinking_parts = []
        images = []
        tool_calls = []
        tool_results = []
        for block in content or []:
            if not isinstance(block, dict):
                continue
            btype = block.get('type')
            if btype == 'text':
                texts.append(block.get('text', ''))
            elif btype == 'thinking':
                thinking_parts.append(block.get('thinking', ''))
            elif btype == 'image':
                src = block.get('source', {})
                if src.get('type') == 'base64':
                    media = src.get('media_type', 'image/png')
                    data_uri = 'data:' + media + ';base64,' + src.get('data', '')
                    images.append({'type': 'image_url', 'image_url': {'url': data_uri}})
            elif btype == 'tool_use':
                tool_calls.append({
                    'id': block.get('id', ''),
                    'type': 'function',
                    'function': {
                        'name': block.get('name', ''),
                        'arguments': json.dumps(block.get('input', {}), ensure_ascii=False),
                    },
                })
            elif btype == 'tool_result':
                tool_results.append({
                    'role': 'tool',
                    'tool_call_id': block.get('tool_use_id', ''),
                    'content': _tool_result_to_text(block),
                })

        # tool_result 作为独立 tool 消息（先于同轮文本）
        messages.extend(tool_results)

        text_content = '\n'.join(t for t in texts if t)
        if role == 'assistant':
            out = {'role': 'assistant', 'content': text_content}
            if thinking_parts:
                out['reasoning_content'] = '\n'.join(thinking_parts)
            if tool_calls:
                out['tool_calls'] = tool_calls
            if text_content or tool_calls or thinking_parts:
                messages.append(out)
        else:
            if images:
                parts = []
                if text_content:
                    parts.append({'type': 'text', 'text': text_content})
                parts.extend(images)
                messages.append({'role': 'user', 'content': parts})
            elif text_content:
                messages.append({'role': 'user', 'content': text_content})

    data = {
        'model': body.get('model', ''),
        'messages': messages,
        'stream': bool(body.get('stream', False)),
    }

    if body.get('max_tokens') is not None:
        data['max_tokens'] = body['max_tokens']
    if body.get('temperature') is not None:
        data['temperature'] = body['temperature']
    if body.get('top_p') is not None:
        data['top_p'] = body['top_p']
    if body.get('stop_sequences'):
        data['stop'] = body['stop_sequences']

    tools = body.get('tools')
    if tools:
        data['tools'] = [
            {
                'type': 'function',
                'function': {
                    'name': t.get('name', ''),
                    'description': t.get('description', ''),
                    'parameters': t.get('input_schema', {'type': 'object'}),
                },
            }
            for t in tools
            if isinstance(t, dict)
        ]

    tool_choice = body.get('tool_choice')
    if isinstance(tool_choice, dict) and data.get('tools'):
        tc_type = tool_choice.get('type')
        if tc_type == 'any':
            data['tool_choice'] = 'required'
        elif tc_type == 'tool':
            data['tool_choice'] = {
                'type': 'function',
                'function': {'name': tool_choice.get('name', '')},
            }
        else:
            data['tool_choice'] = 'auto'

    return data


# ==================== 响应转换 ====================

def openai_to_anthropic_response(resp, model):
    """OpenAI 非流式响应 -> Anthropic message 对象"""
    choice = (resp.get('choices') or [{}])[0]
    msg = choice.get('message', {})
    content = []

    reasoning = msg.get('reasoning_content')
    if reasoning:
        content.append({'type': 'thinking', 'thinking': reasoning, 'signature': ''})

    text = msg.get('content')
    if text:
        content.append({'type': 'text', 'text': text})

    for tc in msg.get('tool_calls') or []:
        fn = tc.get('function', {})
        try:
            args = json.loads(fn.get('arguments') or '{}')
        except json.JSONDecodeError:
            args = {}
        content.append({
            'type': 'tool_use',
            'id': tc.get('id', ''),
            'name': fn.get('name', ''),
            'input': args,
        })

    usage = resp.get('usage') or {}
    return {
        'id': 'msg_' + uuid.uuid4().hex[:24],
        'type': 'message',
        'role': 'assistant',
        'model': model,
        'content': content,
        'stop_reason': _STOP_REASON_MAP.get(choice.get('finish_reason'), 'end_turn'),
        'stop_sequence': None,
        'usage': {
            'input_tokens': usage.get('prompt_tokens', 0),
            'output_tokens': usage.get('completion_tokens', 0),
        },
    }


def _event(name, payload):
    """构造一条 Anthropic SSE 事件文本"""
    return 'event: ' + name + '\n' + _SSE_DATA + json.dumps(payload, ensure_ascii=False) + '\n\n'


def openai_stream_to_anthropic(raw_iter, model):
    """内部 OpenAI SSE 流 -> Anthropic 事件流

    状态机：reasoning_content 映射 thinking 块，content 映射 text 块，
    块切换时补 content_block_stop / content_block_start。
    """
    msg_id = 'msg_' + uuid.uuid4().hex[:24]
    yield _event('message_start', {
        'type': 'message_start',
        'message': {
            'id': msg_id,
            'type': 'message',
            'role': 'assistant',
            'model': model,
            'content': [],
            'stop_reason': None,
            'stop_sequence': None,
            'usage': {'input_tokens': 0, 'output_tokens': 0},
        },
    })

    block_index = -1
    block_type = None  # None | 'thinking' | 'text'
    finish_reason = None
    usage = {}

    for chunk in iter_openai_sse(raw_iter):
        if chunk is None:
            break
        if 'error' in chunk:
            err_msg = chunk['error'].get('message', 'upstream error') if isinstance(chunk['error'], dict) else str(chunk['error'])
            yield _event('error', {'type': 'error', 'error': {'type': 'api_error', 'message': err_msg}})
            break
        if chunk.get('usage'):
            usage = chunk['usage']
        choices = chunk.get('choices') or []
        if not choices:
            continue
        choice = choices[0]
        if choice.get('finish_reason'):
            finish_reason = choice['finish_reason']
        delta = choice.get('delta') or {}
        r_delta = delta.get('reasoning_content') or delta.get('reasoning')
        c_delta = delta.get('content')

        if r_delta:
            if block_type != 'thinking':
                if block_type is not None:
                    yield _event('content_block_stop', {'type': 'content_block_stop', 'index': block_index})
                block_index += 1
                block_type = 'thinking'
                yield _event('content_block_start', {
                    'type': 'content_block_start',
                    'index': block_index,
                    'content_block': {'type': 'thinking', 'thinking': ''},
                })
            yield _event('content_block_delta', {
                'type': 'content_block_delta',
                'index': block_index,
                'delta': {'type': 'thinking_delta', 'thinking': r_delta},
            })

        if c_delta:
            if block_type != 'text':
                if block_type is not None:
                    yield _event('content_block_stop', {'type': 'content_block_stop', 'index': block_index})
                block_index += 1
                block_type = 'text'
                yield _event('content_block_start', {
                    'type': 'content_block_start',
                    'index': block_index,
                    'content_block': {'type': 'text', 'text': ''},
                })
            yield _event('content_block_delta', {
                'type': 'content_block_delta',
                'index': block_index,
                'delta': {'type': 'text_delta', 'text': c_delta},
            })

    if block_type is not None:
        yield _event('content_block_stop', {'type': 'content_block_stop', 'index': block_index})

    yield _event('message_delta', {
        'type': 'message_delta',
        'delta': {
            'stop_reason': _STOP_REASON_MAP.get(finish_reason, 'end_turn'),
            'stop_sequence': None,
        },
        'usage': {'output_tokens': (usage or {}).get('completion_tokens', 0)},
    })
    yield _event('message_stop', {'type': 'message_stop'})


# ==================== 路由 ====================

def _extract_auth_header():
    """Anthropic 客户端用 x-api-key 头；也兼容 Authorization Bearer"""
    key = request.headers.get('x-api-key', '') or ''
    if not key:
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            key = auth[7:]
    return 'Bearer ' + key if key else ''


@anthropic_bp.route('/v1/messages', methods=['POST'])
def anthropic_messages():
    """Anthropic Messages API 兼容端点"""
    from .chat import handle_chat_data

    body = request.get_json(silent=True) or {}
    model = body.get('model', '')
    stream = bool(body.get('stream', False))

    try:
        openai_body = anthropic_to_openai_request(body)
    except Exception as e:
        logging.warning('[Anthropic端点] 请求转换失败: %s', e, exc_info=True)
        return jsonify({
            'type': 'error',
            'error': {'type': 'invalid_request_error', 'message': str(e)},
        }), 400

    inner, status = unwrap_response(handle_chat_data(openai_body, _extract_auth_header()))

    if status != 200:
        err = (inner.get_json(silent=True) or {}).get('error', {})
        return jsonify({
            'type': 'error',
            'error': {
                'type': _ERROR_TYPE_MAP.get(status, 'api_error'),
                'message': err.get('message', 'upstream error'),
            },
        }), status

    if stream:
        return Response(
            stream_with_context(openai_stream_to_anthropic(inner.response, model)),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    resp_json = inner.get_json(silent=True) or {}
    return jsonify(openai_to_anthropic_response(resp_json, model))

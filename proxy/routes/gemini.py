"""
Google Gemini generateContent API 兼容端点

提供：
- POST /v1beta/models/<model>:generateContent        非流式
- POST /v1beta/models/<model>:streamGenerateContent  流式（SSE）
- GET  /v1beta/models                                 模型列表

接受 Gemini 原生请求格式，转换为 OpenAI chat.completions 格式
复用现有处理管线，再把响应转换回 Gemini 格式。
"""

import json
import logging

from flask import Blueprint, request, Response, jsonify, stream_with_context

from .native_utils import iter_openai_sse, unwrap_response

gemini_bp = Blueprint('gemini', __name__)

_SSE_DATA = 'data: '

_FINISH_MAP = {
    'stop': 'STOP',
    'length': 'MAX_TOKENS',
    'tool_calls': 'STOP',
    'content_filter': 'SAFETY',
}


# ==================== 请求转换 ====================

def gemini_to_openai_request(body, model, stream):
    """Gemini generateContent 请求体 -> OpenAI chat.completions 请求体"""
    messages = []

    si = body.get('systemInstruction') or body.get('system_instruction')
    if isinstance(si, dict):
        text = '\n'.join(
            p.get('text', '') for p in si.get('parts', []) or [] if isinstance(p, dict)
        )
        if text:
            messages.append({'role': 'system', 'content': text})

    for content in body.get('contents', []) or []:
        if not isinstance(content, dict):
            continue
        role = 'assistant' if content.get('role') == 'model' else 'user'
        texts = []
        images = []
        tool_calls = []
        tool_msgs = []
        for part in content.get('parts', []) or []:
            if not isinstance(part, dict):
                continue
            if 'text' in part:
                texts.append(part.get('text') or '')
            elif 'inlineData' in part or 'inline_data' in part:
                blob = part.get('inlineData') or part.get('inline_data') or {}
                mime = blob.get('mimeType') or blob.get('mime_type') or 'image/png'
                data_uri = 'data:' + mime + ';base64,' + (blob.get('data') or '')
                images.append({'type': 'image_url', 'image_url': {'url': data_uri}})
            elif 'functionCall' in part:
                fc = part.get('functionCall') or {}
                tool_calls.append({
                    'id': 'call_' + fc.get('name', 'fn'),
                    'type': 'function',
                    'function': {
                        'name': fc.get('name', ''),
                        'arguments': json.dumps(fc.get('args', {}), ensure_ascii=False),
                    },
                })
            elif 'functionResponse' in part:
                fr = part.get('functionResponse') or {}
                tool_msgs.append({
                    'role': 'tool',
                    'tool_call_id': 'call_' + fr.get('name', 'fn'),
                    'content': json.dumps(fr.get('response', {}), ensure_ascii=False),
                })

        messages.extend(tool_msgs)
        text_content = '\n'.join(t for t in texts if t)
        if role == 'assistant':
            out = {'role': 'assistant', 'content': text_content}
            if tool_calls:
                out['tool_calls'] = tool_calls
            if text_content or tool_calls:
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

    data = {'model': model, 'messages': messages, 'stream': stream}

    gc = body.get('generationConfig') or body.get('generation_config') or {}
    if gc.get('temperature') is not None:
        data['temperature'] = gc['temperature']
    if gc.get('topP') is not None:
        data['top_p'] = gc['topP']
    if gc.get('maxOutputTokens') is not None:
        data['max_tokens'] = gc['maxOutputTokens']
    if gc.get('stopSequences'):
        data['stop'] = gc['stopSequences']

    tools = []
    for t in body.get('tools', []) or []:
        if not isinstance(t, dict):
            continue
        for fd in t.get('functionDeclarations', []) or []:
            if not isinstance(fd, dict):
                continue
            tools.append({
                'type': 'function',
                'function': {
                    'name': fd.get('name', ''),
                    'description': fd.get('description', ''),
                    'parameters': fd.get('parameters', {'type': 'object'}),
                },
            })
    if tools:
        data['tools'] = tools

    return data


# ==================== 响应转换 ====================

def _openai_msg_to_gemini_parts(msg):
    """OpenAI message -> Gemini parts（reasoning 映射 thought part）"""
    parts = []
    if msg.get('reasoning_content'):
        parts.append({'text': msg['reasoning_content'], 'thought': True})
    if msg.get('content'):
        parts.append({'text': msg['content']})
    for tc in msg.get('tool_calls') or []:
        fn = tc.get('function', {})
        try:
            args = json.loads(fn.get('arguments') or '{}')
        except json.JSONDecodeError:
            args = {}
        parts.append({'functionCall': {'name': fn.get('name', ''), 'args': args}})
    return parts or [{'text': ''}]


def _usage_metadata(usage):
    usage = usage or {}
    return {
        'promptTokenCount': usage.get('prompt_tokens', 0),
        'candidatesTokenCount': usage.get('completion_tokens', 0),
        'totalTokenCount': usage.get('total_tokens', 0),
    }


def openai_to_gemini_response(resp, model):
    """OpenAI 非流式响应 -> Gemini GenerateContentResponse"""
    choice = (resp.get('choices') or [{}])[0]
    msg = choice.get('message', {})
    return {
        'candidates': [{
            'content': {'parts': _openai_msg_to_gemini_parts(msg), 'role': 'model'},
            'finishReason': _FINISH_MAP.get(choice.get('finish_reason'), 'STOP'),
            'index': 0,
        }],
        'usageMetadata': _usage_metadata(resp.get('usage')),
        'modelVersion': model,
    }


def _sse_line(payload):
    return _SSE_DATA + json.dumps(payload, ensure_ascii=False) + '\n\n'


def openai_stream_to_gemini(raw_iter, model):
    """内部 OpenAI SSE 流 -> Gemini SSE 流"""
    finish_reason = None
    usage = {}

    for chunk in iter_openai_sse(raw_iter):
        if chunk is None:
            break
        if 'error' in chunk:
            err_msg = chunk['error'].get('message', 'upstream error') if isinstance(chunk['error'], dict) else str(chunk['error'])
            yield _sse_line({'error': {'code': 500, 'message': err_msg, 'status': 'INTERNAL'}})
            return
        if chunk.get('usage'):
            usage = chunk['usage']
        choices = chunk.get('choices') or []
        if not choices:
            continue
        choice = choices[0]
        if choice.get('finish_reason'):
            finish_reason = choice['finish_reason']
        delta = choice.get('delta') or {}
        parts = []
        r_delta = delta.get('reasoning_content') or delta.get('reasoning')
        if r_delta:
            parts.append({'text': r_delta, 'thought': True})
        if delta.get('content'):
            parts.append({'text': delta['content']})
        if parts:
            yield _sse_line({
                'candidates': [{'content': {'parts': parts, 'role': 'model'}, 'index': 0}],
                'modelVersion': model,
            })

    yield _sse_line({
        'candidates': [{
            'content': {'parts': [], 'role': 'model'},
            'finishReason': _FINISH_MAP.get(finish_reason, 'STOP'),
            'index': 0,
        }],
        'usageMetadata': _usage_metadata(usage),
        'modelVersion': model,
    })


# ==================== 路由 ====================

def _extract_auth_header():
    """Gemini 客户端用 ?key= 查询参数或 x-goog-api-key 头"""
    key = request.args.get('key', '') or request.headers.get('x-goog-api-key', '')
    return 'Bearer ' + key if key else ''


@gemini_bp.route('/v1beta/models/<path:model_action>', methods=['POST'])
def gemini_generate(model_action):
    """Gemini generateContent / streamGenerateContent 兼容端点"""
    from .chat import handle_chat_data

    model, sep, action = model_action.rpartition(':')
    if not sep:
        return jsonify({'error': {'code': 400, 'message': 'missing action, expected model:generateContent', 'status': 'INVALID_ARGUMENT'}}), 400
    if action not in ('generateContent', 'streamGenerateContent'):
        return jsonify({'error': {'code': 404, 'message': 'unknown action: ' + action, 'status': 'NOT_FOUND'}}), 404

    stream = action == 'streamGenerateContent'
    body = request.get_json(silent=True) or {}

    try:
        openai_body = gemini_to_openai_request(body, model, stream)
    except Exception as e:
        logging.warning('[Gemini端点] 请求转换失败: %s', e, exc_info=True)
        return jsonify({'error': {'code': 400, 'message': str(e), 'status': 'INVALID_ARGUMENT'}}), 400

    inner, status = unwrap_response(handle_chat_data(openai_body, _extract_auth_header()))

    if status != 200:
        err = (inner.get_json(silent=True) or {}).get('error', {})
        grpc_status = 'UNAUTHENTICATED' if status == 401 else 'INTERNAL'
        return jsonify({'error': {'code': status, 'message': err.get('message', 'upstream error'), 'status': grpc_status}}), status

    if stream:
        return Response(
            stream_with_context(openai_stream_to_gemini(inner.response, model)),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    resp_json = inner.get_json(silent=True) or {}
    return jsonify(openai_to_gemini_response(resp_json, model))


@gemini_bp.route('/v1beta/models', methods=['GET'])
def gemini_list_models():
    """Gemini 模型列表兼容端点（从 model_routes 生成）"""
    from ..config import get_config

    config = get_config()
    routes = config.get('model_routes', {}) or {}
    models = []
    for name in routes:
        if name == '_default':
            continue
        models.append({
            'name': 'models/' + name,
            'displayName': name,
            'supportedGenerationMethods': ['generateContent', 'streamGenerateContent'],
        })
    return jsonify({'models': models})

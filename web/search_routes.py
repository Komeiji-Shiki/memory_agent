"""
全局搜索 API 路由

提供跨来源聚合搜索：
- 关键词索引（indexer.search）
- 节点（名称/内容/标签匹配）
- 对话内容（遍历 JSONL 原始对话）
- RAG 语义搜索（可选，需启用）
- Graphiti 图谱搜索（可选，需启用）

各来源并行执行、独立容错：单一来源失败只影响该分类，不影响整体响应。
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request, jsonify

from .errors import handle_api_exception
from .core import get_reader, get_indexer, load_config

logger = logging.getLogger(__name__)

search_bp = Blueprint('search_api', __name__)

# 对话搜索的文件数上限（防止极端情况下遍历过多文件）
MAX_CONV_FILES = 200


def _make_snippet(text: str, query: str, context: int = 60) -> str:
    """提取命中位置的上下文片段"""
    idx = text.casefold().find(query.casefold())
    if idx < 0:
        return text[:context * 2]
    start = max(0, idx - context)
    end = min(len(text), idx + len(query) + context)
    prefix = '...' if start > 0 else ''
    suffix = '...' if end < len(text) else ''
    return f"{prefix}{text[start:end]}{suffix}"


def _search_keyword(query: str, limit: int) -> dict:
    """关键词索引搜索"""
    indexer = get_indexer()
    if not indexer:
        return {"error": "索引组件未初始化"}
    results = indexer.search(query=query, limit=limit)
    return {"results": results, "total": len(results)}


def _search_nodes(query: str, limit: int) -> dict:
    """节点搜索（名称/内容/标签匹配）"""
    reader = get_reader()
    if not reader:
        return {"error": "读取组件未初始化"}

    q = query.casefold()
    results = []
    for name in reader.list_nodes():
        if len(results) >= limit:
            break
        node = reader.read_node(name)
        if not node:
            continue

        name_hit = q in node.name.casefold()
        tag_hit = any(q in (t or '').casefold() for t in (node.tags or []))
        content_hit = q in (node.content or '').casefold()
        if not (name_hit or tag_hit or content_hit):
            continue

        results.append({
            "name": node.name,
            "type": node.type,
            "tags": node.tags or [],
            "matched": "name" if name_hit else ("tag" if tag_hit else "content"),
            "snippet": _make_snippet(node.content or '', query) if content_hit else (node.content or '')[:120],
        })

    return {"results": results, "total": len(results)}


def _search_conversations(query: str, limit: int, days: int) -> dict:
    """对话内容搜索（遍历原始 JSONL）"""
    from .conversation_routes import get_conversations_dir, _collect_conversation_files
    from memory_store.conversation_logger import ConversationFileReader

    conv_dir = get_conversations_dir()
    if not conv_dir or not conv_dir.exists():
        return {"results": [], "total": 0}

    q = query.casefold()
    reader = ConversationFileReader()
    results = []

    files = _collect_conversation_files(conv_dir, None, days)[:MAX_CONV_FILES]
    for f, date_str in files:
        if len(results) >= limit:
            break
        try:
            conv = reader.read_conversation(f)
        except Exception:
            continue

        for turn in conv.turns:
            if len(results) >= limit:
                break
            for role, text in (("user", turn.user), ("assistant", turn.assistant)):
                if text and q in text.casefold():
                    results.append({
                        "session_id": f.stem,
                        "date": date_str,
                        "timestamp": turn.timestamp.isoformat() if turn.timestamp else None,
                        "role": role,
                        "snippet": _make_snippet(text, query),
                    })
                    break  # 每轮最多记一条

    return {"results": results, "total": len(results)}


def _search_rag(query: str, limit: int) -> dict:
    """RAG 语义搜索（未启用时跳过）"""
    from .rag_routes import _get_rag_index

    rag = _get_rag_index()
    if not rag:
        return {"skipped": True, "reason": "RAG 未启用或未配置 API Key"}

    raw = rag.search(query, top_k=limit)
    results = []
    for entry, score in raw:
        results.append({
            "content": entry.content,
            "similarity": round(score, 4),
            "metadata": entry.metadata,
        })
    return {"results": results, "total": len(results)}


def _search_graphiti(query: str, limit: int) -> dict:
    """Graphiti 图谱搜索（未启用时跳过）"""
    config = load_config()
    if not config.get("graphiti", {}).get("enabled", False):
        return {"skipped": True, "reason": "Graphiti 未启用"}

    from .graphiti_routes import get_graphiti_adapter
    adapter = get_graphiti_adapter()
    if adapter is None:
        return {"error": "Graphiti 适配器不可用"}

    raw_results = adapter.search(query, num_results=limit)
    results = []
    for r in raw_results:
        results.append({
            "content": getattr(r, 'content', ''),
            "score": getattr(r, 'score', 1.0),
            "source": getattr(r, 'source', ''),
            "type": getattr(r, 'result_type', 'edge'),
        })
    return {"results": results, "total": len(results)}


@search_bp.route('/search/global', methods=['GET', 'POST'])
def global_search():
    """全局聚合搜索"""
    try:
        if request.method == 'POST':
            data = request.get_json() or {}
        else:
            data = {
                'query': request.args.get('q', ''),
                'limit': request.args.get('limit', 20, type=int),
                'days': request.args.get('days', 30, type=int),
                'include_rag': request.args.get('include_rag', 'false').lower() == 'true',
                'include_graphiti': request.args.get('include_graphiti', 'false').lower() == 'true',
            }

        query = (data.get('query') or '').strip()
        if not query:
            return jsonify({"error": "缺少查询内容"}), 400

        limit = int(data.get('limit', 20))
        days = int(data.get('days', 30))
        include_rag = bool(data.get('include_rag', False))
        include_graphiti = bool(data.get('include_graphiti', False))

        # 并行执行各来源，独立容错
        def safe(fn, *args):
            try:
                return fn(*args)
            except Exception as e:
                logger.warning("[全局搜索] %s 失败: %s", fn.__name__, e)
                return {"error": str(e)}

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {
                'keyword': pool.submit(safe, _search_keyword, query, limit),
                'nodes': pool.submit(safe, _search_nodes, query, limit),
                'conversations': pool.submit(safe, _search_conversations, query, limit, days),
            }
            if include_rag:
                futures['rag'] = pool.submit(safe, _search_rag, query, limit)
            if include_graphiti:
                futures['graphiti'] = pool.submit(safe, _search_graphiti, query, limit)

            sections = {key: fut.result() for key, fut in futures.items()}

        if not include_rag:
            sections['rag'] = {"skipped": True, "reason": "未勾选"}
        if not include_graphiti:
            sections['graphiti'] = {"skipped": True, "reason": "未勾选"}

        return jsonify({"query": query, **sections})

    except Exception as e:
        return handle_api_exception(e, __name__)

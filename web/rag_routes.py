"""
RAG 语义搜索 API 路由
"""

from flask import Blueprint, request, jsonify
from .core import load_config, save_config, get_lifebook_path

# 创建蓝图
rag_bp = Blueprint('rag_api', __name__)

# RAG索引（延迟初始化）
_rag_index = None


def _get_rag_index():
    """获取RAG索引"""
    global _rag_index
    
    if _rag_index is None:
        lifebook_path = get_lifebook_path()
        config = load_config()
        rag_cfg = config.get('rag', {})
        
        if not rag_cfg.get('enabled'):
            print(f"[RAG] 未启用")
            return None
        
        if not rag_cfg.get('api_key'):
            print(f"[RAG] 未配置API Key")
            return None
        
        from memory_store.rag import RAGIndex, RAGConfig
        
        rag_config = RAGConfig(
            api_key=rag_cfg.get('api_key', ''),
            model=rag_cfg.get('model', 'Qwen/Qwen3-Embedding-8B'),
            base_url=rag_cfg.get('base_url', 'https://api.siliconflow.cn/v1/embeddings'),
            chunk_size=rag_cfg.get('chunk_size', 500),
            chunk_overlap=rag_cfg.get('chunk_overlap', 50),
            top_k=rag_cfg.get('top_k', 5),
            similarity_threshold=rag_cfg.get('similarity_threshold', 0.3),
            enabled=True
        )
        
        print(f"[RAG] 初始化索引，路径: {lifebook_path}")
        _rag_index = RAGIndex(lifebook_path, rag_config)
    
    return _rag_index


@rag_bp.route('/rag/stats', methods=['GET'])
def get_rag_stats():
    """获取RAG索引统计"""
    try:
        rag = _get_rag_index()
        if not rag:
            return jsonify({
                "enabled": False,
                "message": "RAG未启用或未配置API Key"
            })
        
        stats = rag.get_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@rag_bp.route('/rag/search', methods=['GET', 'POST'])
def rag_search():
    """RAG语义搜索"""
    try:
        rag = _get_rag_index()
        if not rag:
            return jsonify({"error": "RAG未启用或未配置API Key"}), 400
        
        if request.method == 'POST':
            data = request.get_json()
        else:
            data = {
                'query': request.args.get('q', ''),
                'top_k': request.args.get('top_k', 5, type=int),
                'filter_type': request.args.get('type')
            }
        
        query = data.get('query', '')
        if not query:
            return jsonify({"error": "缺少查询内容"}), 400
        
        top_k = data.get('top_k', 5)
        filter_type = data.get('filter_type')
        
        results = rag.search(query, top_k=top_k, filter_type=filter_type)
        
        formatted = []
        for entry, score in results:
            formatted.append({
                "id": entry.id,
                "file_path": entry.file_path,
                "content": entry.content,
                "metadata": entry.metadata,
                "similarity": round(score, 4),
                "created_at": entry.created_at
            })
        
        return jsonify({
            "query": query,
            "results": formatted,
            "total": len(formatted)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@rag_bp.route('/rag/rebuild', methods=['POST'])
def rebuild_rag_index():
    """重建RAG索引"""
    try:
        rag = _get_rag_index()
        if not rag:
            return jsonify({"error": "RAG未启用或未配置API Key"}), 400
        
        incremental = request.args.get('incremental', 'true').lower() == 'true'
        result = rag.rebuild_index(incremental=incremental)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@rag_bp.route('/rag/config', methods=['GET'])
def get_rag_config():
    """获取RAG配置"""
    try:
        config = load_config()
        rag_cfg = config.get('rag', {})
        
        api_key = rag_cfg.get('api_key', '')
        masked_key = api_key[:8] + '****' + api_key[-4:] if len(api_key) > 12 else '****'
        
        return jsonify({
            "enabled": rag_cfg.get('enabled', False),
            "api_key": masked_key,
            "api_key_masked": masked_key,
            "has_api_key": bool(api_key),
            "model": rag_cfg.get('model', 'Qwen/Qwen3-Embedding-8B'),
            "base_url": rag_cfg.get('base_url', 'https://api.siliconflow.cn/v1/embeddings'),
            "chunk_size": rag_cfg.get('chunk_size', 500),
            "chunk_overlap": rag_cfg.get('chunk_overlap', 50),
            "top_k": rag_cfg.get('top_k', 5),
            "similarity_threshold": rag_cfg.get('similarity_threshold', 0.3)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@rag_bp.route('/rag/config', methods=['POST', 'PUT'])
def save_rag_config():
    """保存RAG配置"""
    try:
        data = request.get_json()
        config = load_config()
        
        if 'rag' not in config:
            config['rag'] = {}
        
        if 'enabled' in data:
            config['rag']['enabled'] = bool(data['enabled'])
        
        # 严格校验 API Key 更新
        if 'api_key' in data:
            new_key = str(data['api_key']).strip()
            if new_key and '****' not in new_key and len(new_key) > 10:
                config['rag']['api_key'] = new_key
                print(f"[RAG] API Key 已更新")
            else:
                print(f"[RAG] 忽略无效或重复的 API Key 提交")
                
        if 'model' in data:
            config['rag']['model'] = data['model']
        if 'base_url' in data:
            config['rag']['base_url'] = data['base_url']
        if 'chunk_size' in data:
            config['rag']['chunk_size'] = int(data['chunk_size'])
        if 'chunk_overlap' in data:
            config['rag']['chunk_overlap'] = int(data['chunk_overlap'])
        if 'top_k' in data:
            config['rag']['top_k'] = int(data['top_k'])
        if 'similarity_threshold' in data:
            config['rag']['similarity_threshold'] = float(data['similarity_threshold'])
        
        save_config(config)
        
        # 重置RAG索引
        global _rag_index
        _rag_index = None
        
        return jsonify({"success": True, "message": "RAG配置已保存，需要重建索引生效"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
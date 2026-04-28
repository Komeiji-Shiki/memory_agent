"""
日记 API 路由
"""

from flask import Blueprint, request, jsonify
from .core import get_reader, get_writer, get_indexer

# 创建蓝图
diary_bp = Blueprint('diary_api', __name__)


@diary_bp.route('/diaries', methods=['GET'])
def list_diaries():
    """获取日记列表"""
    reader = get_reader()
    
    if not reader:
        return jsonify({"error": "组件未初始化"}), 500
    
    limit = request.args.get('limit', 30, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    all_dates = reader.list_all_diaries()
    total = len(all_dates)
    dates = all_dates[offset:offset + limit]
    
    diaries = []
    for date in dates:
        diary = reader.read_diary(date)
        if diary:
            diaries.append({
                "date": date,
                "title": diary.title,
                "preview": diary.content[:150] + "..." if len(diary.content) > 150 else diary.content,
                "tags": diary.tags
            })
    
    return jsonify({
        "total": total,
        "offset": offset,
        "limit": limit,
        "diaries": diaries
    })


@diary_bp.route('/diary/<date>', methods=['GET'])
def get_diary(date: str):
    """获取指定日期日记"""
    reader = get_reader()
    
    if not reader:
        return jsonify({"error": "组件未初始化"}), 500
    
    diary = reader.read_diary(date)
    
    if not diary:
        return jsonify({"error": f"未找到 {date} 的日记"}), 404
    
    return jsonify({
        "date": diary.date,
        "title": diary.title,
        "content": diary.content,
        "tags": diary.tags,
        "links": diary.links,
        "file_path": diary.file_path
    })


@diary_bp.route('/diary/<date>', methods=['POST', 'PUT'])
def save_diary(date: str):
    """创建或更新日记"""
    reader = get_reader()
    writer = get_writer()
    indexer = get_indexer()
    
    if not writer:
        return jsonify({"error": "组件未初始化"}), 500
    
    data = request.get_json()
    content = data.get('content', '')
    title = data.get('title')
    tags = data.get('tags', [])
    
    if request.method == 'POST':
        section = data.get('section')
        success = writer.append_to_diary(date, content, section)
    else:
        success = writer.update_diary(date, content, title, tags)
    
    if success:
        file_path = str(reader.daily_dir / f"{date}.md")
        indexer.index_file(file_path)
        return jsonify({"success": True, "message": f"日记 {date} 已保存"})
    else:
        return jsonify({"error": "保存失败"}), 500


# ==================== 节点接口 ====================

@diary_bp.route('/nodes', methods=['GET'])
def list_nodes():
    """获取节点列表"""
    reader = get_reader()
    
    if not reader:
        return jsonify({"error": "组件未初始化"}), 500
    
    node_type = request.args.get('type')
    nodes = reader.list_nodes(node_type)
    
    result = []
    for name in nodes:
        node = reader.read_node(name)
        if node:
            result.append({
                "name": node.name,
                "type": node.type,
                "preview": node.content[:100] + "..." if len(node.content) > 100 else node.content,
                "tags": node.tags
            })
    
    return jsonify({"nodes": result, "total": len(result)})


@diary_bp.route('/node/<name>', methods=['GET'])
def get_node(name: str):
    """获取节点详情"""
    reader = get_reader()
    
    if not reader:
        return jsonify({"error": "组件未初始化"}), 500
    
    node = reader.read_node(name)
    
    if not node:
        return jsonify({"error": f"未找到节点 {name}"}), 404
    
    return jsonify({
        "name": node.name,
        "type": node.type,
        "content": node.content,
        "tags": node.tags,
        "links": node.links,
        "file_path": node.file_path
    })


@diary_bp.route('/node', methods=['POST'])
def create_node():
    """创建新节点"""
    writer = get_writer()
    indexer = get_indexer()
    
    if not writer:
        return jsonify({"error": "组件未初始化"}), 500
    
    data = request.get_json()
    name = data.get('name')
    node_type = data.get('type', '事物')
    content = data.get('content', '')
    tags = data.get('tags', [])
    
    if not name:
        return jsonify({"error": "缺少节点名称"}), 400
    
    success = writer.create_node(name, node_type, content, tags)
    
    if success:
        # 写入后立即更新索引，保证 search_memories 结果一致
        if indexer:
            try:
                file_path = str(writer.nodes_dir / f"{node_type}-{name}.md")
                indexer.index_file(file_path)
                
                # 新增人物节点会影响人物识别缓存（[[小明]] 无前缀链接识别）
                if node_type == "人物" and hasattr(indexer, "invalidate_people_cache"):
                    indexer.invalidate_people_cache()
            except Exception:
                pass
        
        return jsonify({"success": True, "message": f"节点 {name} 已创建"})
    else:
        return jsonify({"error": "创建失败，可能已存在"}), 500


@diary_bp.route('/node/<name>', methods=['PUT'])
def update_node_api(name: str):
    """更新节点（支持内容和标签）"""
    writer = get_writer()
    reader = get_reader()
    indexer = get_indexer()
    
    if not writer:
        return jsonify({"error": "组件未初始化"}), 500
    
    # 先读取现有节点获取类型
    node = reader.read_node(name)
    if not node:
        return jsonify({"error": f"节点 {name} 不存在"}), 404
    
    data = request.get_json()
    content = data.get('content', node.content)
    tags = data.get('tags', node.tags)
    
    # 使用 create_node 的 overwrite 模式来更新节点（保留类型）
    success = writer.create_node(
        name=name,
        node_type=node.type,
        content=content,
        tags=tags,
        overwrite=True
    )
    
    if success:
        # 更新索引
        if indexer:
            indexer.index_file(node.file_path)
        return jsonify({"success": True, "message": f"节点 {name} 已更新"})
    else:
        return jsonify({"error": "更新失败"}), 500


# ==================== 搜索接口 ====================

@diary_bp.route('/search', methods=['GET', 'POST'])
def search():
    """搜索记忆"""
    indexer = get_indexer()
    
    if not indexer:
        return jsonify({"error": "组件未初始化"}), 500
    
    if request.method == 'POST':
        data = request.get_json()
    else:
        data = {
            'query': request.args.get('q', ''),
            'tags': request.args.getlist('tag'),
            'people': request.args.getlist('person'),
            'date_start': request.args.get('date_start'),
            'date_end': request.args.get('date_end'),
            'limit': request.args.get('limit', 20, type=int)
        }
    
    results = indexer.search(
        query=data.get('query', ''),
        tags=data.get('tags'),
        people=data.get('people'),
        date_start=data.get('date_start'),
        date_end=data.get('date_end'),
        limit=data.get('limit', 20)
    )
    
    return jsonify({
        "query": data.get('query', ''),
        "results": results,
        "total": len(results)
    })


# ==================== 统计接口 ====================

@diary_bp.route('/stats', methods=['GET'])
def get_stats():
    """获取统计信息"""
    from .core import get_lifebook_path
    
    indexer = get_indexer()
    lifebook_path = get_lifebook_path()
    
    if not indexer:
        return jsonify({"diary_count": 0, "tag_count": 0, "people_count": 0, "interaction_count": 0})
    
    raw_stats = indexer.get_stats()
    
    # 映射字段名
    stats = {
        'diary_count': raw_stats.get('by_type', {}).get('diary', 0),
        'tag_count': raw_stats.get('total_tags', 0),
        'people_count': raw_stats.get('total_people', 0),
        'total_files': raw_stats.get('total_files', 0),
        'total_keywords': raw_stats.get('total_keywords', 0),
        'by_type': raw_stats.get('by_type', {}),
        'last_updated': raw_stats.get('last_updated', ''),
        'all_tags': indexer.get_all_tags()[:20],
        'all_people': indexer.get_all_people()[:20]
    }
    
    # 添加元数据信息
    try:
        from memory_store.metadata import MetadataManager
        metadata = MetadataManager(lifebook_path)
        stats['interaction_count'] = metadata.get_interaction_count()
        last = metadata.get_last_interaction()
        if last:
            stats['last_interaction'] = last.strftime('%Y-%m-%d %H:%M')
    except Exception:
        stats['interaction_count'] = 0
    
    return jsonify(stats)


@diary_bp.route('/tags', methods=['GET'])
def list_tags():
    """获取所有标签"""
    indexer = get_indexer()
    if not indexer:
        return jsonify({"tags": []})
    tags = indexer.get_all_tags()
    return jsonify({"tags": [{"name": t, "count": c} for t, c in tags]})


@diary_bp.route('/people', methods=['GET'])
def list_people():
    """获取所有人物"""
    indexer = get_indexer()
    if not indexer:
        return jsonify({"people": []})
    people = indexer.get_all_people()
    return jsonify({"people": [{"name": p, "count": c} for p, c in people]})


# ==================== 管理接口 ====================

@diary_bp.route('/rebuild-index', methods=['POST'])
def rebuild_index():
    """重建索引"""
    indexer = get_indexer()
    
    if not indexer:
        return jsonify({"error": "组件未初始化"}), 500
    
    try:
        indexer.rebuild_index()
        return jsonify({
            "success": True,
            "message": "索引重建完成",
            "stats": indexer.get_stats()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
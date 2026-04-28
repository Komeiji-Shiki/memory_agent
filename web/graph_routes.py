"""
Graph Routes - 知识图谱 API

提供知识图谱可视化所需的接口：
- GET /graph - 获取完整图谱数据
- GET /graph/node/<node_id> - 获取节点详情
- GET /graph/neighbors/<node_id> - 获取节点邻居
- POST /graph/relation - 创建关系
- DELETE /graph/relation - 删除关系
- PUT /graph/node/<node_id> - 编辑节点
"""

import re
from pathlib import Path
from flask import Blueprint, jsonify, request

from .core import get_reader, get_writer, get_lifebook_path, get_indexer

graph_bp = Blueprint('graph', __name__)


def _get_node_color(node_type: str) -> str:
    """根据节点类型返回颜色"""
    colors = {
        "人物": "#4CAF50",  # 绿色
        "地点": "#2196F3",  # 蓝色
        "事物": "#FF9800",  # 橙色
        "概念": "#9C27B0",  # 紫色
    }
    return colors.get(node_type, "#607D8B")  # 默认灰色


def _get_node_icon(node_type: str) -> str:
    """根据节点类型返回图标"""
    icons = {
        "人物": "👤",
        "地点": "📍",
        "事物": "📦",
        "概念": "💡",
    }
    return icons.get(node_type, "📌")


def _extract_observations(content: str) -> list:
    """从节点内容中提取观察（列表项）"""
    observations = []
    for line in content.split("\n"):
        line = line.strip()
        # 匹配 - 开头但不是链接的行
        if line.startswith("- ") and not line.startswith("- [["):
            obs = line[2:].strip()
            if obs:
                observations.append(obs)
    return observations[:10]  # 最多返回10条


def _extract_all_links_with_context(content: str) -> list:
    """
    从节点内容中提取所有 [[链接]]，包括关联类型和方向
    
    返回: [(target_name, relation_type, is_backlink), ...]
    """
    import re
    
    links = []
    current_section = None
    current_relation_type = "关联"
    is_in_backlink_section = False
    
    for line in content.split("\n"):
        line_stripped = line.strip()
        
        # 检测章节标题
        if line_stripped.startswith("### 关联："):
            current_section = "relation"
            current_relation_type = line_stripped[7:].strip()
            is_in_backlink_section = False
        elif line_stripped.startswith("### 被关联"):
            current_section = "backlink"
            is_in_backlink_section = True
        elif line_stripped.startswith("###") or line_stripped.startswith("## "):
            current_section = None
            is_in_backlink_section = False
            current_relation_type = "关联"
        
        # 提取链接
        if "[[" in line and "]]" in line:
            # 使用正则提取所有 [[xxx]] 格式的链接
            matches = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', line)
            for target in matches:
                # 尝试从括号中提取关系类型
                relation = current_relation_type
                
                # 匹配 [[xxx]]（关系类型）格式
                paren_match = re.search(r'\[\[' + re.escape(target) + r'\]\].*?（([^）]+)）', line)
                if paren_match:
                    paren_content = paren_match.group(1)
                    # 如果是"xxx 的对象"格式，提取 xxx 作为关系类型
                    if " 的对象" in paren_content:
                        relation = paren_content.replace(" 的对象", "")
                    elif paren_content:
                        relation = paren_content
                
                links.append((target, relation, is_in_backlink_section))
    
    return links


def _extract_relations(content: str) -> list:
    """
    从节点内容中提取关系信息（只提取主动关系，忽略被关联）
    
    格式示例：
    ### 关联：开发
    - [[LifeBook Memory Agent]]（开发）
    
    "被关联" 部分会被忽略，因为主动方节点会生成正确方向的边
    
    返回: [(target_name, relation_type), ...]
    """
    relations = []
    current_relation_type = "关联"
    in_passive_section = False  # 是否在"被关联"区域
    
    for line in content.split("\n"):
        line = line.strip()
        
        # 检测关系类型标题
        if line.startswith("### 关联："):
            current_relation_type = line[7:].strip()
            in_passive_section = False
        elif line.startswith("### 被关联"):
            # 跳过被关联区域，避免重复边
            in_passive_section = True
            continue
        elif line.startswith("###"):
            # 其他标题，重置状态
            in_passive_section = False
            current_relation_type = "关联"
        
        # 跳过被关联区域的内容
        if in_passive_section:
            continue
        
        # 提取链接和关系：- [[xxx]]（关系）
        if line.startswith("- [[") and "]]" in line:
            # 提取链接名称
            start = line.find("[[") + 2
            end = line.find("]]")
            if start > 1 and end > start:
                target = line[start:end]
                
                # 尝试提取括号中的关系类型
                relation = current_relation_type
                paren_start = line.find("（", end)
                paren_end = line.find("）", end)
                if paren_start > 0 and paren_end > paren_start:
                    paren_content = line[paren_start+1:paren_end]
                    # 忽略 "xxx 的对象" 这种被动格式
                    if paren_content and " 的对象" not in paren_content:
                        relation = paren_content
                
                relations.append((target, relation))
    
    return relations


@graph_bp.route('/graph')
def get_graph():
    """
    获取完整知识图谱数据（包含反向链接统计）
    
    返回格式:
    {
        "nodes": [
            {"id": "人物-主人", "name": "主人", "type": "人物", "color": "#4CAF50", "icon": "👤",
             "observations": 5, "links_count": 3, "backlinks_count": 2}
        ],
        "edges": [
            {"from": "人物-主人", "to": "事物-LifeBook", "relation": "创建"}
        ],
        "stats": {"total_nodes": 10, "total_edges": 15}
    }
    """
    try:
        lifebook_path = get_lifebook_path()
        reader = get_reader()
        nodes_dir = Path(lifebook_path) / "nodes"
        
        if not nodes_dir.exists():
            return jsonify({
                "nodes": [],
                "edges": [],
                "stats": {"total_nodes": 0, "total_edges": 0}
            })
        
        nodes = []
        edges = []
        node_ids = set()  # 用于验证边的目标节点是否存在
        node_id_to_index = {}  # node_id -> index in nodes list
        
        # 第一遍：收集所有节点
        for file in nodes_dir.glob("*.md"):
            name = file.stem
            node_type = None
            node_name = None
            
            for t in ["人物", "地点", "事物", "概念", "事件"]:
                if name.startswith(f"{t}-"):
                    node_type = t
                    node_name = name[len(t)+1:]
                    break
            
            if not node_type or not node_name:
                continue
            
            node_id = name  # 完整文件名作为ID
            node_ids.add(node_id)
            
            # 读取节点内容
            node = reader.read_node(node_name)
            if node:
                observations = _extract_observations(node.content)
                
                node_data = {
                    "id": node_id,
                    "name": node_name,
                    "type": node_type,
                    "color": _get_node_color(node_type),
                    "icon": _get_node_icon(node_type),
                    "observations": len(observations),
                    "tags": node.tags[:5] if node.tags else [],
                    "links_count": len(node.links) if node.links else 0,
                    "backlinks_count": 0,  # 将在第二遍计算
                    "_links": node.links or []  # 临时存储，用于计算反向链接
                }
                node_id_to_index[node_id] = len(nodes)
                nodes.append(node_data)
                
                # 收集边（关系）- 使用增强的关系提取，包括被关联区域
                all_links = _extract_all_links_with_context(node.content)
                for target_name, relation_type, is_backlink in all_links:
                    # 尝试匹配目标节点ID
                    target_id = None
                    for t in ["人物", "地点", "事物", "概念", "事件"]:
                        possible_id = f"{t}-{target_name}"
                        if possible_id in node_ids or (nodes_dir / f"{possible_id}.md").exists():
                            target_id = possible_id
                            break
                    
                    if not target_id:
                        # 直接使用链接名（可能是完整ID）
                        if target_name in node_ids or (nodes_dir / f"{target_name}.md").exists():
                            target_id = target_name
                    
                    if target_id:
                        # 根据是否是被关联区域决定边的方向
                        if is_backlink:
                            # 被关联区域：目标节点 -> 当前节点
                            from_id = target_id
                            to_id = node_id
                        else:
                            # 正常关联：当前节点 -> 目标节点
                            from_id = node_id
                            to_id = target_id
                        
                        # 避免重复边（方向+关系类型）
                        edge_key = (from_id, to_id, relation_type)
                        existing_edges = {(e["from"], e["to"], e["relation"]) for e in edges}
                        if edge_key not in existing_edges:
                            edges.append({
                                "from": from_id,
                                "to": to_id,
                                "relation": relation_type
                            })
        
        # 第二遍：计算反向链接数量
        for node_data in nodes:
            for link in node_data.get("_links", []):
                # 查找被链接的节点
                target_id = None
                for t in ["人物", "地点", "事物", "概念", "事件"]:
                    possible_id = f"{t}-{link}"
                    if possible_id in node_id_to_index:
                        target_id = possible_id
                        break
                
                if not target_id and link in node_id_to_index:
                    target_id = link
                
                if target_id and target_id in node_id_to_index:
                    target_idx = node_id_to_index[target_id]
                    nodes[target_idx]["backlinks_count"] += 1
        
        # 清理临时字段
        for node_data in nodes:
            if "_links" in node_data:
                del node_data["_links"]
        
        # 调试：统计每个节点的边数
        from collections import defaultdict
        edge_count = defaultdict(lambda: {"out": 0, "in": 0})
        for e in edges:
            edge_count[e["from"]]["out"] += 1
            edge_count[e["to"]]["in"] += 1
        
        return jsonify({
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "by_type": {
                    "人物": sum(1 for n in nodes if n["type"] == "人物"),
                    "地点": sum(1 for n in nodes if n["type"] == "地点"),
                    "事物": sum(1 for n in nodes if n["type"] == "事物"),
                    "概念": sum(1 for n in nodes if n["type"] == "概念"),
                    "事件": sum(1 for n in nodes if n["type"] == "事件"),
                },
                # 调试信息
                "debug_edge_counts": {k: v for k, v in edge_count.items() if "灰魂" in k}
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@graph_bp.route('/graph/node/<path:node_id>')
def get_node_detail(node_id: str):
    """
    获取单个节点的详细信息（包含反向链接）
    
    Args:
        node_id: 节点ID（如 "人物-主人"）
    """
    try:
        lifebook_path = get_lifebook_path()
        reader = get_reader()
        nodes_dir = Path(lifebook_path) / "nodes"
        
        # 解析节点ID
        node_type = None
        node_name = node_id
        for t in ["人物", "地点", "事物", "概念", "事件"]:
            if node_id.startswith(f"{t}-"):
                node_type = t
                node_name = node_id[len(t)+1:]
                break
        
        # 读取节点
        node = reader.read_node(node_name)
        if not node:
            return jsonify({"error": f"节点 {node_id} 不存在"}), 404
        
        observations = _extract_observations(node.content)
        
        # 计算反向链接：查找所有链接到此节点的其他节点
        # 使用更直接的方式：检查文件内容中是否包含 [[目标节点名]] 或 [[目标节点ID]]
        backlinks = []
        
        # 可能的链接格式
        link_patterns = [
            f"[[{node_name}]]",  # [[灰魂]]
            f"[[{node_id}]]",   # [[人物-灰魂]]
        ]
        
        for file in nodes_dir.glob("*.md"):
            other_id = file.stem
            if other_id == node_id:
                continue
            
            # 解析其他节点
            other_type = None
            other_name = other_id
            for t in ["人物", "地点", "事物", "概念", "事件"]:
                if other_id.startswith(f"{t}-"):
                    other_type = t
                    other_name = other_id[len(t)+1:]
                    break
            
            if not other_type:
                continue
            
            try:
                # 直接读取文件内容
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 提取所有链接
                all_links = _extract_all_links_with_context(content)
                
                # 只查找 ACTIVE 链接（关联区域），不查找 PASSIVE 链接（被关联区域）
                # 因为"被关联"区域的 [[目标]] 表示"目标链接到我"，不是"我链接到目标"
                found_active_link = False
                relation_type = "关联"
                
                for target, rel, is_backlink in all_links:
                    if (target == node_name or target == node_id) and not is_backlink:
                        # 只有在"关联"区域（非被关联）的链接才算真正的链接
                        relation_type = rel
                        found_active_link = True
                        break
                
                if found_active_link:
                    backlinks.append({
                        "id": other_id,
                        "name": other_name,
                        "type": other_type,
                        "icon": _get_node_icon(other_type),
                        "color": _get_node_color(other_type),
                        "relation": relation_type
                    })
            except Exception as e:
                # 跳过读取失败的文件
                continue
        
        return jsonify({
            "id": node_id,
            "name": node_name,
            "type": node.type,
            "color": _get_node_color(node.type),
            "icon": _get_node_icon(node.type),
            "content": node.content,
            "observations": observations,
            "tags": node.tags,
            "links": node.links,
            "backlinks": backlinks  # 反向链接列表
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@graph_bp.route('/graph/neighbors/<path:node_id>')
def get_node_neighbors(node_id: str):
    """
    获取节点的一度关联节点
    
    Args:
        node_id: 节点ID
    """
    try:
        lifebook_path = get_lifebook_path()
        reader = get_reader()
        nodes_dir = Path(lifebook_path) / "nodes"
        
        # 解析节点ID获取节点名
        node_name = node_id
        for t in ["人物", "地点", "事物", "概念"]:
            if node_id.startswith(f"{t}-"):
                node_name = node_id[len(t)+1:]
                break
        
        # 读取当前节点
        node = reader.read_node(node_name)
        if not node:
            return jsonify({"error": f"节点 {node_id} 不存在"}), 404
        
        neighbors = []
        neighbor_ids = set()
        
        # 获取当前节点链接的目标节点
        if node.links:
            for link in node.links:
                for t in ["人物", "地点", "事物", "概念"]:
                    possible_id = f"{t}-{link}"
                    if (nodes_dir / f"{possible_id}.md").exists():
                        if possible_id not in neighbor_ids:
                            neighbor_ids.add(possible_id)
                            target_node = reader.read_node(link)
                            if target_node:
                                neighbors.append({
                                    "id": possible_id,
                                    "name": link,
                                    "type": t,
                                    "color": _get_node_color(t),
                                    "icon": _get_node_icon(t),
                                    "direction": "outgoing"
                                })
                        break
        
        # 查找链接到当前节点的其他节点（反向链接）
        for file in nodes_dir.glob("*.md"):
            other_id = file.stem
            if other_id == node_id or other_id in neighbor_ids:
                continue
            
            # 解析其他节点
            other_type = None
            other_name = other_id
            for t in ["人物", "地点", "事物", "概念"]:
                if other_id.startswith(f"{t}-"):
                    other_type = t
                    other_name = other_id[len(t)+1:]
                    break
            
            if not other_type:
                continue
            
            other_node = reader.read_node(other_name)
            if other_node and other_node.links:
                # 检查是否链接到当前节点
                if node_name in other_node.links or node_id in other_node.links:
                    if other_id not in neighbor_ids:
                        neighbor_ids.add(other_id)
                        neighbors.append({
                            "id": other_id,
                            "name": other_name,
                            "type": other_type,
                            "color": _get_node_color(other_type),
                            "icon": _get_node_icon(other_type),
                            "direction": "incoming"
                        })
        
        return jsonify({
            "node_id": node_id,
            "neighbors": neighbors,
            "total": len(neighbors)
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 编辑功能 ====================

@graph_bp.route('/graph/relation', methods=['POST'])
def create_relation():
    """
    创建节点间关系
    
    请求体:
    {
        "from_node": "人物-主人",
        "to_node": "事物-LifeBook Memory Agent",
        "relation_type": "开发"
    }
    """
    try:
        data = request.get_json()
        from_node = data.get('from_node')
        to_node = data.get('to_node')
        relation_type = data.get('relation_type', '关联')
        
        if not from_node or not to_node:
            return jsonify({"error": "缺少必要参数"}), 400
        
        lifebook_path = get_lifebook_path()
        nodes_dir = Path(lifebook_path) / "nodes"
        
        # 解析源节点
        from_type = None
        from_name = from_node
        for t in ["人物", "地点", "事物", "概念", "事件"]:
            if from_node.startswith(f"{t}-"):
                from_type = t
                from_name = from_node[len(t)+1:]
                break
        
        # 解析目标节点
        to_type = None
        to_name = to_node
        for t in ["人物", "地点", "事物", "概念", "事件"]:
            if to_node.startswith(f"{t}-"):
                to_type = t
                to_name = to_node[len(t)+1:]
                break
        
        # 检查源节点是否存在
        from_file = nodes_dir / f"{from_node}.md"
        if not from_file.exists():
            return jsonify({"error": f"源节点 {from_node} 不存在"}), 404
        
        # 检查目标节点是否存在
        to_file = nodes_dir / f"{to_node}.md"
        if not to_file.exists():
            return jsonify({"error": f"目标节点 {to_node} 不存在"}), 404
        
        # 读取源节点内容
        with open(from_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查关系是否已存在
        relation_pattern = f"### 关联：{relation_type}"
        link_pattern = f"- [[{to_name}]]"
        
        if relation_pattern in content and link_pattern in content:
            return jsonify({"error": "关系已存在"}), 400
        
        # 添加关系
        new_relation = f"\n\n### 关联：{relation_type}\n\n- [[{to_name}]]（{relation_type}）"
        new_content = content.rstrip() + new_relation
        
        with open(from_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        # 在目标节点添加被关联（可选的反向引用）
        with open(to_file, 'r', encoding='utf-8') as f:
            to_content = f.read()
        
        back_ref = f"\n\n### 被关联\n\n- [[{from_name}]]（{relation_type} 的对象）"
        
        # 检查是否已有被关联区域
        if "### 被关联" not in to_content:
            to_content = to_content.rstrip() + back_ref
        else:
            # 在已有的被关联区域后追加
            back_link = f"\n- [[{from_name}]]（{relation_type} 的对象）"
            # 找到被关联区域的末尾
            lines = to_content.split("\n")
            insert_idx = len(lines)
            in_back_section = False
            for i, line in enumerate(lines):
                if line.strip().startswith("### 被关联"):
                    in_back_section = True
                elif in_back_section and line.strip().startswith("###"):
                    insert_idx = i
                    break
            
            if in_back_section:
                lines.insert(insert_idx, f"- [[{from_name}]]（{relation_type} 的对象）")
                to_content = "\n".join(lines)
        
        with open(to_file, 'w', encoding='utf-8') as f:
            f.write(to_content)
        
        return jsonify({
            "success": True,
            "message": f"已创建关系: {from_name} --{relation_type}--> {to_name}"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@graph_bp.route('/graph/relation', methods=['PUT'])
def update_relation():
    """
    更新节点间关系（修改关系类型）
    
    请求体:
    {
        "from_node": "人物-主人",
        "to_node": "事物-LifeBook Memory Agent",
        "old_relation": "有",
        "new_relation": "设计"
    }
    """
    try:
        data = request.get_json()
        from_node = data.get('from_node')
        to_node = data.get('to_node')
        old_relation = data.get('old_relation', '关联')
        new_relation = data.get('new_relation')
        
        if not from_node or not to_node or not new_relation:
            return jsonify({"error": "缺少必要参数"}), 400
        
        lifebook_path = get_lifebook_path()
        nodes_dir = Path(lifebook_path) / "nodes"
        
        # 解析节点名称
        from_name = from_node
        to_name = to_node
        for t in ["人物", "地点", "事物", "概念", "事件"]:
            if from_node.startswith(f"{t}-"):
                from_name = from_node[len(t)+1:]
            if to_node.startswith(f"{t}-"):
                to_name = to_node[len(t)+1:]
        
        # 读取源节点
        from_file = nodes_dir / f"{from_node}.md"
        if not from_file.exists():
            return jsonify({"error": f"源节点 {from_node} 不存在"}), 404
        
        with open(from_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 替换关系类型
        # 1. 替换 "### 关联：旧关系" -> "### 关联：新关系"
        content = content.replace(f"### 关联：{old_relation}", f"### 关联：{new_relation}")
        
        # 2. 替换 "[[目标]]（旧关系）" -> "[[目标]]（新关系）"
        content = content.replace(f"[[{to_name}]]（{old_relation}）", f"[[{to_name}]]（{new_relation}）")
        
        with open(from_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # 同时更新目标节点的被关联引用
        to_file = nodes_dir / f"{to_node}.md"
        if to_file.exists():
            with open(to_file, 'r', encoding='utf-8') as f:
                to_content = f.read()
            
            # 替换 "[[来源]]（旧关系 的对象）" -> "[[来源]]（新关系 的对象）"
            to_content = to_content.replace(
                f"[[{from_name}]]（{old_relation} 的对象）",
                f"[[{from_name}]]（{new_relation} 的对象）"
            )
            
            with open(to_file, 'w', encoding='utf-8') as f:
                f.write(to_content)
        
        return jsonify({
            "success": True,
            "message": f"已将关系 {from_name} --{old_relation}--> {to_name} 修改为 --{new_relation}-->"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@graph_bp.route('/graph/relation', methods=['DELETE'])
def delete_relation():
    """
    删除节点间关系
    
    请求体:
    {
        "from_node": "人物-主人",
        "to_node": "事物-LifeBook Memory Agent",
        "relation_type": "开发"
    }
    """
    try:
        data = request.get_json()
        from_node = data.get('from_node')
        to_node = data.get('to_node')
        relation_type = data.get('relation_type')
        
        if not from_node or not to_node:
            return jsonify({"error": "缺少必要参数"}), 400
        
        lifebook_path = get_lifebook_path()
        nodes_dir = Path(lifebook_path) / "nodes"
        
        # 解析节点名称
        from_name = from_node
        to_name = to_node
        for t in ["人物", "地点", "事物", "概念", "事件"]:
            if from_node.startswith(f"{t}-"):
                from_name = from_node[len(t)+1:]
            if to_node.startswith(f"{t}-"):
                to_name = to_node[len(t)+1:]
        
        # 读取源节点
        from_file = nodes_dir / f"{from_node}.md"
        if not from_file.exists():
            return jsonify({"error": f"源节点 {from_node} 不存在"}), 404
        
        with open(from_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 删除关系行
        lines = content.split("\n")
        new_lines = []
        skip_section = False
        section_to_skip = f"### 关联：{relation_type}" if relation_type else None
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # 检测是否是要删除的关系区域
            if section_to_skip and line.strip() == section_to_skip:
                # 检查下一行是否是目标链接
                if i + 2 < len(lines) and f"[[{to_name}]]" in lines[i + 2]:
                    # 跳过这整个区域（标题 + 空行 + 链接）
                    i += 3
                    # 跳过后面的空行
                    while i < len(lines) and not lines[i].strip():
                        i += 1
                    continue
            
            # 直接匹配链接行（不考虑区域）
            if f"[[{to_name}]]" in line and (not relation_type or relation_type in line):
                i += 1
                continue
            
            new_lines.append(line)
            i += 1
        
        new_content = "\n".join(new_lines)
        
        with open(from_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        # 同时删除目标节点的被关联引用
        to_file = nodes_dir / f"{to_node}.md"
        if to_file.exists():
            with open(to_file, 'r', encoding='utf-8') as f:
                to_content = f.read()
            
            # 删除包含源节点的被关联行
            to_lines = to_content.split("\n")
            to_new_lines = [l for l in to_lines if f"[[{from_name}]]" not in l]
            to_new_content = "\n".join(to_new_lines)
            
            with open(to_file, 'w', encoding='utf-8') as f:
                f.write(to_new_content)
        
        return jsonify({
            "success": True,
            "message": f"已删除关系: {from_name} --{relation_type or '关联'}--> {to_name}"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@graph_bp.route('/graph/node/<path:node_id>', methods=['DELETE'])
def delete_node_api(node_id: str):
    """删除节点"""
    try:
        lifebook_path = get_lifebook_path()
        nodes_dir = Path(lifebook_path) / "nodes"
        
        file_path = nodes_dir / f"{node_id}.md"
        if not file_path.exists():
            return jsonify({"error": f"节点 {node_id} 不存在"}), 404
        
        # 解析节点名称
        node_name = node_id
        for t in ["人物", "地点", "事物", "概念", "事件"]:
            if node_id.startswith(f"{t}-"):
                node_name = node_id[len(t)+1:]
                break
        
        # 删除文件
        file_path.unlink()
        
        # 清理其他节点中对该节点的引用
        for other_file in nodes_dir.glob("*.md"):
            try:
                with open(other_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if f"[[{node_name}]]" in content or f"[[{node_id}]]" in content:
                    # 删除包含该节点的链接行
                    lines = content.split("\n")
                    new_lines = [l for l in lines if f"[[{node_name}]]" not in l and f"[[{node_id}]]" not in l]
                    new_content = "\n".join(new_lines)
                    
                    with open(other_file, 'w', encoding='utf-8') as f:
                        f.write(new_content)
            except Exception:
                pass
        
        return jsonify({
            "success": True,
            "message": f"已删除节点 {node_id} 及其关联引用"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
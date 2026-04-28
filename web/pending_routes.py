"""
待处理摘要 API 路由
"""

from flask import Blueprint, request, jsonify
from .core import load_config, save_config, get_lifebook_path

# 创建蓝图
pending_bp = Blueprint('pending_api', __name__)


def _get_pending_manager():
    """获取待处理摘要管理器"""
    lifebook_path = get_lifebook_path()
    config = load_config()
    pending_cfg = config.get('pending', {})
    sleep_gap = pending_cfg.get('sleep_gap_hours', 6)
    
    from memory_store.pending_manager import PendingManager
    return PendingManager(lifebook_path, sleep_gap_hours=sleep_gap)


@pending_bp.route('/pending', methods=['GET'])
def get_pending_summaries():
    """获取待处理摘要/会话信息"""
    try:
        pending_mgr = _get_pending_manager()
        session_id = request.args.get('session_id')
        date = request.args.get('date')
        
        if session_id:
            sessions = pending_mgr.get_all_sessions()
            session = next((s for s in sessions if s.session_id == session_id), None)
            
            if not session:
                return jsonify({"error": f"会话 {session_id} 不存在"}), 404
            
            return jsonify({
                "session_id": session.session_id,
                "start_time": session.start_time.isoformat(),
                "end_time": session.end_time.isoformat(),
                "summaries": [
                    {
                        "timestamp": s.timestamp,
                        "topic": s.topic,
                        "summary": s.summary,
                        "tool_calls": s.tool_calls,
                        "raw_turns": s.raw_turns
                    } for s in session.summaries
                ],
                "count": len(session.summaries)
            })
            
        elif date:
            summaries = pending_mgr.get_pending_for_date(date)
            return jsonify({
                "date": date,
                "summaries": [
                    {
                        "timestamp": s.timestamp,
                        "topic": s.topic,
                        "summary": s.summary,
                        "tool_calls": s.tool_calls,
                        "raw_turns": s.raw_turns
                    } for s in summaries
                ],
                "count": len(summaries)
            })
        else:
            stats = pending_mgr.get_stats()
            return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pending_bp.route('/pending/sessions', methods=['GET'])
def get_pending_sessions():
    """获取所有待处理会话"""
    try:
        pending_mgr = _get_pending_manager()
        ready_only = request.args.get('ready_only', 'true').lower() == 'true'
        
        if ready_only:
            sessions = pending_mgr.get_pending_sessions(exclude_active=True)
        else:
            sessions = pending_mgr.get_all_sessions()
        
        result = []
        for session in sessions:
            duration = session.end_time - session.start_time
            duration_mins = int(duration.total_seconds() / 60)
            
            result.append({
                "session_id": session.session_id,
                "start_time": session.start_time.isoformat(),
                "end_time": session.end_time.isoformat(),
                "date": session.start_time.strftime("%Y-%m-%d"),
                "duration_minutes": duration_mins,
                "summary_count": len(session.summaries),
                "topics": [s.topic for s in session.summaries],
                "is_ready": session in pending_mgr.get_pending_sessions(exclude_active=True)
            })
        
        return jsonify({
            "sessions": result,
            "total": len(result),
            "ready_count": sum(1 for s in result if s.get("is_ready"))
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pending_bp.route('/pending/consolidate', methods=['POST'])
def consolidate_pending():
    """将待处理摘要汇总成日记"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        date = data.get('date')
        
        if not session_id and not date:
            return jsonify({"error": "缺少 session_id 或 date 参数"}), 400
        
        pending_mgr = _get_pending_manager()
        
        config = load_config()
        agent_cfg = config.get('memory_agent', {})
        summary_cfg = config.get('auto_summary', {})
        pending_cfg = config.get('pending', {})
        
        model = data.get('model') or summary_cfg.get('model') or agent_cfg.get('model', 'deepseek-chat')
        api_key = summary_cfg.get('api_key') or agent_cfg.get('api_key') or config.get('api_key', '')
        base_url = summary_cfg.get('base_url') or agent_cfg.get('base_url', 'https://api.deepseek.com/v1')
        custom_prompt = data.get('prompt', '')
        
        consolidate_prompt = pending_cfg.get('consolidate_prompt', '')
        merge_prompt = pending_cfg.get('merge_prompt', '')
        
        if session_id:
            sessions = pending_mgr.get_all_sessions()
            session = next((s for s in sessions if s.session_id == session_id), None)
            
            if not session:
                return jsonify({"error": f"会话 {session_id} 不存在"}), 404
            
            result = pending_mgr.consolidate_session(
                session=session,
                model=model,
                api_key=api_key,
                base_url=base_url,
                custom_prompt=custom_prompt,
                consolidate_prompt=consolidate_prompt,
                merge_prompt=merge_prompt
            )
        else:
            result = pending_mgr.consolidate_to_diary(
                date=date,
                model=model,
                api_key=api_key,
                base_url=base_url,
                custom_prompt=custom_prompt
            )
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pending_bp.route('/pending/consolidate-with-tools', methods=['POST'])
def consolidate_with_tools():
    """使用工具调用汇总（支持日记+节点）"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        mode = data.get('mode', 'both')  # diary_only, nodes_only, both
        
        if not session_id:
            return jsonify({"error": "缺少 session_id 参数"}), 400
        
        pending_mgr = _get_pending_manager()
        
        sessions = pending_mgr.get_all_sessions()
        session = next((s for s in sessions if s.session_id == session_id), None)
        
        if not session:
            return jsonify({"error": f"会话 {session_id} 不存在"}), 404
        
        config = load_config()
        agent_cfg = config.get('memory_agent', {})
        summary_cfg = config.get('auto_summary', {})
        pending_cfg = config.get('pending', {})
        
        model = data.get('model') or summary_cfg.get('model') or agent_cfg.get('model', 'deepseek-chat')
        api_key = summary_cfg.get('api_key') or agent_cfg.get('api_key') or config.get('api_key', '')
        base_url = summary_cfg.get('base_url') or agent_cfg.get('base_url', 'https://api.deepseek.com/v1')
        
        # 获取提示词配置
        consolidate_prompt = pending_cfg.get('consolidate_with_tools_prompt', '')
        
        result = pending_mgr.consolidate_with_tools(
            session=session,
            model=model,
            api_key=api_key,
            base_url=base_url,
            mode=mode,
            consolidate_prompt=consolidate_prompt,
            max_iterations=data.get('max_iterations', 10)
        )
        
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@pending_bp.route('/pending/direct-convert', methods=['POST'])
def direct_convert_pending():
    """直接转换摘要为日记（不使用LLM）"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({"error": "缺少 session_id 参数"}), 400
        
        pending_mgr = _get_pending_manager()
        
        sessions = pending_mgr.get_all_sessions()
        session = next((s for s in sessions if s.session_id == session_id), None)
        
        if not session:
            return jsonify({"error": f"会话 {session_id} 不存在"}), 404
        
        result = pending_mgr.direct_convert_session(session)
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pending_bp.route('/pending/dates', methods=['GET'])
def get_pending_dates():
    """获取有待处理摘要的日期列表"""
    try:
        pending_mgr = _get_pending_manager()
        include_today = request.args.get('include_today', 'false').lower() == 'true'
        dates = pending_mgr.get_pending_dates(include_today=include_today)
        return jsonify({"dates": dates})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pending_bp.route('/pending/archived', methods=['GET'])
def get_archived_sessions():
    """获取已归档的会话列表"""
    try:
        pending_mgr = _get_pending_manager()
        sessions = pending_mgr.get_archived_sessions()
        
        result = []
        for session in sessions:
            duration = session.end_time - session.start_time
            duration_mins = int(duration.total_seconds() / 60)
            
            result.append({
                "session_id": session.session_id,
                "start_time": session.start_time.isoformat(),
                "end_time": session.end_time.isoformat(),
                "date": session.start_time.strftime("%Y-%m-%d"),
                "duration_minutes": duration_mins,
                "summary_count": len(session.summaries),
                "topics": [s.topic for s in session.summaries],
                "is_archived": True
            })
        
        return jsonify({
            "sessions": result,
            "total": len(result)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pending_bp.route('/pending/archived/<session_id>', methods=['GET'])
def get_archived_session_detail(session_id: str):
    """获取单个归档会话的详细信息"""
    try:
        pending_mgr = _get_pending_manager()
        sessions = pending_mgr.get_archived_sessions()
        session = next((s for s in sessions if s.session_id == session_id), None)
        
        if not session:
            return jsonify({"error": f"归档会话 {session_id} 不存在"}), 404
        
        return jsonify({
            "session_id": session.session_id,
            "start_time": session.start_time.isoformat(),
            "end_time": session.end_time.isoformat(),
            "summaries": [
                {
                    "timestamp": s.timestamp,
                    "topic": s.topic,
                    "summary": s.summary,
                    "tool_calls": s.tool_calls,
                    "raw_turns": s.raw_turns
                } for s in session.summaries
            ],
            "count": len(session.summaries),
            "is_archived": True
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pending_bp.route('/pending/restore/<session_id>', methods=['POST'])
def restore_archived_session(session_id: str):
    """恢复已归档的会话"""
    try:
        pending_mgr = _get_pending_manager()
        success = pending_mgr.restore_session(session_id)
        
        if success:
            return jsonify({
                "success": True,
                "message": f"会话 {session_id} 已恢复到待处理列表",
                "session_id": session_id
            })
        else:
            return jsonify({"error": f"恢复会话 {session_id} 失败，可能不存在"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pending_bp.route('/pending/consolidate-all', methods=['POST'])
def consolidate_all_pending():
    """智能汇总所有准备好的会话"""
    try:
        pending_mgr = _get_pending_manager()
        ready_sessions = pending_mgr.get_pending_sessions(exclude_active=True)
        
        if not ready_sessions:
            return jsonify({
                "success": True,
                "message": "没有准备好的会话需要汇总（当前会话可能仍在进行中）",
                "results": []
            })
        
        config = load_config()
        agent_cfg = config.get('memory_agent', {})
        summary_cfg = config.get('auto_summary', {})
        pending_cfg = config.get('pending', {})
        
        model = summary_cfg.get('model') or agent_cfg.get('model', 'deepseek-chat')
        api_key = summary_cfg.get('api_key') or agent_cfg.get('api_key') or config.get('api_key', '')
        base_url = summary_cfg.get('base_url') or agent_cfg.get('base_url', 'https://api.deepseek.com/v1')
        
        consolidate_prompt = pending_cfg.get('consolidate_prompt', '')
        merge_prompt = pending_cfg.get('merge_prompt', '')
        
        results = pending_mgr.consolidate_all_ready(
            model=model,
            api_key=api_key,
            base_url=base_url,
            consolidate_prompt=consolidate_prompt,
            merge_prompt=merge_prompt
        )
        
        success_count = sum(1 for r in results if r.get('success'))
        
        return jsonify({
            "success": True,
            "message": f"已处理 {len(results)} 个会话，成功 {success_count} 个",
            "results": results
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pending_bp.route('/pending/config', methods=['GET'])
def get_pending_config():
    """获取待处理摘要配置"""
    try:
        config = load_config()
        pending_cfg = config.get('pending', {})
        
        default_consolidate_prompt = """请将以下一个"清醒周期"内的多次对话摘要整合成一篇流畅的日记。

要求：
1. 用第一人称（"我"）撰写
2. 按时间顺序组织，但要自然衔接
3. 提炼主要事件和收获
4. 保持日记风格，不要太像工作报告
5. 保留重要的人名、项目名等细节
6. 适当加入情感和反思

对话摘要：
{content}

请生成整合后的日记："""

        default_merge_prompt = """请将以下新的对话摘要整合到现有日记中，生成一篇完整的日记。

现有日记内容：
{existing_content}

---

新的对话摘要：
{content}

要求：
1. 用第一人称（"我"）撰写
2. 按时间顺序组织，自然衔接现有内容和新内容
3. 不要有重复，保持流畅
4. 保留重要的人名、项目名等细节
5. 输出完整的日记（不是只输出新增部分）

请生成整合后的完整日记："""

        default_consolidate_with_tools_prompt = """## 可用工具

### 节点创建/更新
- **create_node(name, type, content, tags?)** - 直接创建新节点
  - type: "人物" | "地点" | "事物" | "概念"
  - ⚠️ 直接调用！无需先查询是否存在。如已存在会返回提示。
  
- **update_node(name, content, mode?)** - 更新现有节点内容
  - mode: "append"(追加) | "replace"(替换)，默认 append
  
- **add_observations(observations)** - 批量添加观察事实
  - 格式: [{"name": "节点名", "contents": ["观察1", "观察2"]}]

### 关系创建
- **create_relations(relations)** - 创建节点间关系
  - 格式: [{"from": "节点A", "to": "节点B", "relation_type": "关系类型"}]
  - 关系类型示例: "使用", "创建", "属于", "包含", "喜欢"

### 查询（可选）
- **list_nodes(type?)** - 列出现有节点概览
- **get_node(name)** - 获取节点详情

## ⚠️ 重要提示
1. **直接创建**：无需先 get_node 检查，直接 create_node。已存在会提示。
2. **批量操作**：尽量一次调用处理多个，避免逐个查询。
3. **只记重要的**：只记录对话中真正有价值、值得长期保存的实体。

---

## 对话摘要
{content}

---

## 任务

### 1. 提取节点
直接用 create_node 创建新实体。对已有实体用 add_observations 补充。可用 create_relations 建立关系。

### 2. 生成日记
用第三人称撰写，称用户为「主人」，AI为「灰魂」。按时间顺序组织。

完成工具调用后，输出日记内容。"""
        
        return jsonify({
            "sleep_gap_hours": pending_cfg.get('sleep_gap_hours', 6),
            "auto_consolidate": pending_cfg.get('auto_consolidate', False),
            "consolidate_prompt": pending_cfg.get('consolidate_prompt') or default_consolidate_prompt,
            "merge_prompt": pending_cfg.get('merge_prompt') or default_merge_prompt,
            "consolidate_with_tools_prompt": pending_cfg.get('consolidate_with_tools_prompt') or default_consolidate_with_tools_prompt,
            "using_defaults": {
                "consolidate": not pending_cfg.get('consolidate_prompt'),
                "merge": not pending_cfg.get('merge_prompt'),
                "consolidate_with_tools": not pending_cfg.get('consolidate_with_tools_prompt')
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pending_bp.route('/pending/config', methods=['POST', 'PUT'])
def save_pending_config():
    """保存待处理摘要配置"""
    try:
        data = request.get_json()
        config = load_config()
        
        if 'pending' not in config:
            config['pending'] = {}
        
        if 'sleep_gap_hours' in data:
            config['pending']['sleep_gap_hours'] = float(data['sleep_gap_hours'])
        if 'auto_consolidate' in data:
            config['pending']['auto_consolidate'] = bool(data['auto_consolidate'])
        if 'consolidate_prompt' in data:
            config['pending']['consolidate_prompt'] = data['consolidate_prompt']
        if 'merge_prompt' in data:
            config['pending']['merge_prompt'] = data['merge_prompt']
        if 'consolidate_with_tools_prompt' in data:
            config['pending']['consolidate_with_tools_prompt'] = data['consolidate_with_tools_prompt']
        
        save_config(config)
        
        return jsonify({"success": True, "message": "配置已保存"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
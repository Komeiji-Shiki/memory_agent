"""
对话管理 API 路由

提供原始对话的管理接口：
- 列出对话会话
- 查看对话详情
- 删除对话
- 总结对话为日记
- 访问对话中的图片

对话存储在 lifebook/conversations/ 目录下，格式为 JSONL
"""

import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from flask import Blueprint, request, jsonify, send_file, abort

from .core import get_lifebook_path, load_config, save_config
from memory_store.conversation_logger import (
    ConversationLogger, ConversationFileReader, ConversationData
)

logger = logging.getLogger(__name__)

# 创建蓝图
conversation_bp = Blueprint('conversation_api', __name__)


def get_conversation_logger() -> Optional[ConversationLogger]:
    """获取对话记录器实例"""
    lifebook_path = get_lifebook_path()
    if not lifebook_path:
        return None
    
    config = load_config()
    return ConversationLogger(lifebook_path, config)


def get_conversations_dir() -> Optional[Path]:
    """获取对话目录"""
    lifebook_path = get_lifebook_path()
    if not lifebook_path:
        return None
    return Path(lifebook_path) / "conversations"


# ==================== LLM 总结辅助 ====================

# 默认提示词
DEFAULT_SINGLE_CONV_PROMPT = """请将以下对话内容总结为简洁的日记条目。

要求：
1. 以第三人称撰写，称用户为「主人」，AI为「灰魂」
2. 提炼主要话题和关键信息
3. 保留重要细节（人名、项目名、具体数据等）
4. 100-500字，内容丰富时可更长

<conversation>
{conversation}
</conversation>

请输出日记内容："""

DEFAULT_DAY_DIARY_PROMPT = """请将以下 {date} 一天中的所有对话总结为一篇完整的日记。

要求：
1. 以第三人称撰写，称用户为「主人」，AI为「灰魂」
2. 按时间顺序组织，标明每部分时间（24小时制）
3. 提炼主要事件和关键信息
4. 不遗漏重要细节
5. 尽可能详细但不杂乱
6. 只记录内容，不进行不必要的情感升华

<conversations>
{conversations}
</conversations>

请以第三人称输出日记："""


def _get_conv_diary_config() -> Dict[str, Any]:
    """获取对话→日记总结的配置（带回退链）"""
    config = load_config()
    conv_cfg = config.get('conversation_diary', {})
    agent_cfg = config.get('memory_agent', {})
    summary_cfg = config.get('auto_summary', {})

    return {
        'model': conv_cfg.get('model') or summary_cfg.get('model') or agent_cfg.get('model', 'deepseek-chat'),
        'api_key': (conv_cfg.get('api_key') or summary_cfg.get('api_key')
                    or agent_cfg.get('api_key') or config.get('api_key', '')),
        'base_url': (conv_cfg.get('base_url') or summary_cfg.get('base_url')
                     or agent_cfg.get('base_url', 'https://api.deepseek.com/v1')),
        'single_prompt': conv_cfg.get('single_prompt', ''),
        'day_prompt': conv_cfg.get('day_prompt', ''),
        'max_tokens': conv_cfg.get('max_tokens', 8192),
        'temperature': conv_cfg.get('temperature', 1),
    }


def _call_summary_llm(user_message: str, llm_config: Dict[str, Any]) -> str:
    """调用 LLM 生成总结"""
    from openai import OpenAI
    import httpx

    client = OpenAI(
        api_key=llm_config['api_key'],
        base_url=llm_config['base_url'],
        http_client=httpx.Client(proxy=None),
    )

    response = client.chat.completions.create(
        model=llm_config['model'],
        messages=[{"role": "user", "content": user_message}],
        max_tokens=llm_config.get('max_tokens', 8192),
        temperature=llm_config.get('temperature', 1),
    )

    usage = response.usage
    if usage:
        logger.info(
            f"[对话→日记] Token消耗: prompt={usage.prompt_tokens}, "
            f"completion={usage.completion_tokens}, total={usage.total_tokens}"
        )

    return response.choices[0].message.content or ""


def _format_conversation_text(conv: ConversationData, max_chars: int = 50000) -> str:
    """将对话数据格式化为 LLM 可读的文本"""
    lines = []
    if conv.header:
        lines.append(f"会话开始: {conv.header.start_time.strftime('%Y-%m-%d %H:%M')}")
        if conv.header.model:
            lines.append(f"模型: {conv.header.model}")
        lines.append("")

    for turn in conv.turns:
        time_str = turn.timestamp.strftime('%H:%M')
        user_text = turn.user
        assistant_text = turn.assistant
        # 截断过长的单条消息
        if len(user_text) > 8000:
            user_text = user_text[:3000] + f"\n...(省略{len(user_text)-6000}字)...\n" + user_text[-3000:]
        if len(assistant_text) > 8000:
            assistant_text = assistant_text[:3000] + f"\n...(省略{len(assistant_text)-6000}字)...\n" + assistant_text[-3000:]
        lines.append(f"[{time_str}] 用户: {user_text}")
        lines.append(f"[{time_str}] 助手: {assistant_text}")
        lines.append("")

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars // 2] + f"\n\n...(对话过长，省略中间部分)...\n\n" + result[-max_chars // 2:]
    return result


def _is_date_dir(name: str) -> bool:
    """检查目录名是否为日期格式 (YYYY-MM-DD)"""
    if len(name) != 10:
        return False
    try:
        datetime.strptime(name, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _collect_conversation_files(conv_dir: Path, date_filter: Optional[str] = None, days: int = 30) -> List[tuple]:
    """
    收集对话文件（支持日期子目录结构）
    
    Returns:
        List of (file_path, date_str) tuples
    """
    cutoff = datetime.now() - timedelta(days=days)
    files_with_date = []
    
    # 1. 收集日期子目录中的文件 (新结构: conversations/2026-01-22/*.jsonl)
    for date_dir in conv_dir.iterdir():
        if date_dir.is_dir() and _is_date_dir(date_dir.name):
            dir_date_str = date_dir.name
            try:
                dir_date = datetime.strptime(dir_date_str, "%Y-%m-%d")
                
                # 日期过滤
                if date_filter:
                    if dir_date_str != date_filter:
                        continue
                elif dir_date.date() < cutoff.date():
                    continue
                
                for f in date_dir.glob("*.jsonl"):
                    files_with_date.append((f, dir_date_str))
            except ValueError:
                continue
    
    # 2. 兼容旧的扁平结构 (旧结构: conversations/2026-01-22_HHMMSS_xxx.jsonl)
    for f in conv_dir.glob("*.jsonl"):
        if f.is_file():
            try:
                # 从文件名提取日期 (格式: YYYY-MM-DD_HHMMSS_xxx.jsonl)
                date_part = f.stem.split('_')[0]
                file_date = datetime.strptime(date_part, '%Y-%m-%d')
                
                if date_filter:
                    if date_part != date_filter:
                        continue
                elif file_date.date() < cutoff.date():
                    continue
                
                files_with_date.append((f, date_part))
            except (ValueError, IndexError):
                continue
    
    # 按修改时间排序（最新的在前）
    files_with_date.sort(key=lambda x: x[0].stat().st_mtime, reverse=True)
    
    return files_with_date


# ==================== 列表接口 ====================

@conversation_bp.route('/conversations', methods=['GET'])
def list_conversation_sessions():
    """
    获取对话列表（支持日期子目录结构）
    
    Query Parameters:
        - days: 回溯天数（默认30）
        - date: 指定日期 (YYYY-MM-DD)
        - limit: 限制数量（默认50）
        - offset: 偏移量（默认0）
    """
    conv_dir = get_conversations_dir()
    if not conv_dir or not conv_dir.exists():
        return jsonify({"conversations": [], "total": 0})
    
    days = request.args.get('days', 30, type=int)
    date_filter = request.args.get('date')
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    reader = ConversationFileReader()
    conversations = []
    
    # 收集对话文件
    all_files = _collect_conversation_files(conv_dir, date_filter, days)
    total = len(all_files)
    
    # 分页
    paged_files = all_files[offset:offset + limit]
    
    for f, date_str in paged_files:
        try:
            conv = reader.read_conversation(f)
            if conv.header:
                # 基本信息
                info = {
                    "session_id": f.stem,
                    "file_name": f.name,
                    "file_path": str(f.relative_to(conv_dir)),
                    "date": date_str,
                    "start_time": conv.header.start_time.isoformat() if conv.header else None,
                    "end_time": conv.footer.end_time.isoformat() if conv.footer else None,
                    "turn_count": len(conv.turns),
                    "model": conv.header.model if conv.header else None,
                    "fingerprint": conv.header.fingerprint[:8] + "..." if conv.header and conv.header.fingerprint else None
                }
                
                # 消息预览
                if conv.turns:
                    first_turn = conv.turns[0]
                    last_turn = conv.turns[-1]
                    info["first_message"] = {
                        "user": first_turn.user[:150] + "..." if len(first_turn.user) > 150 else first_turn.user,
                        "timestamp": first_turn.timestamp.isoformat()
                    }
                    if len(conv.turns) > 1:
                        info["last_message"] = {
                            "user": last_turn.user[:100] + "..." if len(last_turn.user) > 100 else last_turn.user,
                            "assistant": last_turn.assistant[:100] + "..." if len(last_turn.assistant) > 100 else last_turn.assistant,
                            "timestamp": last_turn.timestamp.isoformat()
                        }
                
                conversations.append(info)
        except Exception as e:
            logger.warning(f"读取对话文件失败 {f.name}: {e}")
            continue
    
    return jsonify({
        "conversations": conversations,
        "total": total,
        "offset": offset,
        "limit": limit
    })


@conversation_bp.route('/conversations/dates', methods=['GET'])
def list_conv_dates():
    """
    获取有对话记录的日期列表（支持日期子目录结构）
    
    返回按日期分组的统计信息
    """
    conv_dir = get_conversations_dir()
    if not conv_dir or not conv_dir.exists():
        return jsonify({"dates": []})
    
    # 按日期分组统计
    date_stats: Dict[str, Dict[str, Any]] = {}
    
    # 1. 统计日期子目录中的文件
    for date_dir in conv_dir.iterdir():
        if date_dir.is_dir() and _is_date_dir(date_dir.name):
            date_str = date_dir.name
            if date_str not in date_stats:
                date_stats[date_str] = {
                    "date": date_str,
                    "count": 0,
                    "total_turns": 0
                }
            
            for f in date_dir.glob("*.jsonl"):
                date_stats[date_str]["count"] += 1
                
                # 快速统计轮次
                try:
                    turn_count = 0
                    with open(f, 'r', encoding='utf-8') as file:
                        for line in file:
                            if '"type": "turn"' in line:
                                turn_count += 1
                    date_stats[date_str]["total_turns"] += turn_count
                except Exception:
                    pass
    
    # 2. 兼容旧的扁平结构
    for f in conv_dir.glob("*.jsonl"):
        if f.is_file():
            try:
                date_part = f.stem.split('_')[0]
                if not _is_date_dir(date_part):
                    continue
                    
                if date_part not in date_stats:
                    date_stats[date_part] = {
                        "date": date_part,
                        "count": 0,
                        "total_turns": 0
                    }
                
                date_stats[date_part]["count"] += 1
                
                # 快速统计轮次
                turn_count = 0
                with open(f, 'r', encoding='utf-8') as file:
                    for line in file:
                        if '"type": "turn"' in line:
                            turn_count += 1
                date_stats[date_part]["total_turns"] += turn_count
                
            except (ValueError, IndexError):
                continue
    
    # 排序并转为列表
    dates = sorted(date_stats.values(), key=lambda x: x["date"], reverse=True)
    
    return jsonify({"dates": dates})


# ==================== 详情接口 ====================

def _find_conversation_file(conv_dir: Path, session_id: str) -> Optional[Path]:
    """
    查找对话文件（支持日期子目录结构）
    
    Args:
        conv_dir: 对话目录
        session_id: 会话ID
    
    Returns:
        文件路径或 None
    """
    # 1. 在日期子目录中查找
    for date_dir in conv_dir.iterdir():
        if date_dir.is_dir() and _is_date_dir(date_dir.name):
            # 精确匹配
            conv_file = date_dir / f"{session_id}.jsonl"
            if conv_file.exists():
                return conv_file
            
            # 模糊匹配
            matches = list(date_dir.glob(f"*{session_id}*.jsonl"))
            if matches:
                return matches[0]
    
    # 2. 兼容旧的扁平结构
    conv_file = conv_dir / f"{session_id}.jsonl"
    if conv_file.exists():
        return conv_file
    
    # 3. 模糊匹配旧结构
    matches = list(conv_dir.glob(f"{session_id}*.jsonl"))
    if matches:
        return matches[0]
    
    return None


@conversation_bp.route('/conversation/<session_id>', methods=['GET'])
def get_conversation(session_id: str):
    """
    获取对话详情（支持日期子目录结构）
    
    Args:
        session_id: 会话ID（文件名，不含 .jsonl）
    """
    conv_dir = get_conversations_dir()
    if not conv_dir:
        return jsonify({"error": "对话目录未配置"}), 500
    
    # 查找对话文件
    conv_file = _find_conversation_file(conv_dir, session_id)
    if not conv_file:
        return jsonify({"error": f"未找到对话: {session_id}"}), 404
    
    reader = ConversationFileReader()
    conv = reader.read_conversation(conv_file)
    
    if not conv.header:
        return jsonify({"error": "对话文件格式错误"}), 500
    
    # 构建响应
    turns = []
    for turn in conv.turns:
        turn_data = {
            "turn_id": turn.turn_id,
            "timestamp": turn.timestamp.isoformat(),
            "user": turn.user,
            "assistant": turn.assistant,
            "model": turn.model,
            "metadata": turn.metadata
        }
        # 添加图片信息
        if hasattr(turn, 'images') and turn.images:
            turn_data["images"] = turn.images
        turns.append(turn_data)
    
    return jsonify({
        "session_id": conv_file.stem,
        "file_path": str(conv_file),
        "header": {
            "start_time": conv.header.start_time.isoformat(),
            "model": conv.header.model,
            "fingerprint": conv.header.fingerprint,
            "system_prompt_preview": conv.header.system_prompt_preview,
            "client_session_id": conv.header.client_session_id
        },
        "turns": turns,
        "footer": {
            "end_time": conv.footer.end_time.isoformat() if conv.footer else None,
            "turn_count": conv.footer.turn_count if conv.footer else len(turns)
        } if conv.footer else None
    })


@conversation_bp.route('/conversations/day/<date>', methods=['GET'])
def get_day_timeline(date: str):
    """
    获取指定日期的全天对话时间线
    
    Args:
        date: 日期字符串 (YYYY-MM-DD)
    """
    conv_dir = get_conversations_dir()
    if not conv_dir:
        return jsonify({"error": "对话目录未配置"}), 500
    
    # 收集该日期的所有文件
    all_files = _collect_conversation_files(conv_dir, date_filter=date)
    if not all_files:
        return jsonify({"date": date, "turns": [], "total_turns": 0})
    
    reader = ConversationFileReader()
    all_turns = []
    sessions_info = {}
    
    for f, _ in all_files:
        try:
            conv = reader.read_conversation(f)
            if not conv.turns:
                continue
                
            session_id = f.stem
            sessions_info[session_id] = {
                "model": conv.header.model if conv.header else "未知",
                "start_time": conv.header.start_time.isoformat() if conv.header else None
            }
            
            for turn in conv.turns:
                turn_data = {
                    "session_id": session_id,
                    "turn_id": turn.turn_id,
                    "timestamp": turn.timestamp.isoformat(),
                    "user": turn.user,
                    "assistant": turn.assistant,
                    "model": turn.model,
                    "metadata": turn.metadata,
                    "images": getattr(turn, 'images', [])
                }
                all_turns.append(turn_data)
        except Exception as e:
            logger.warning(f"读取对话文件失败 {f.name}: {e}")
            continue
            
    # 按时间戳排序
    all_turns.sort(key=lambda x: x["timestamp"])
    
    return jsonify({
        "date": date,
        "total_turns": len(all_turns),
        "sessions": sessions_info,
        "turns": all_turns
    })


# ==================== 删除接口 ====================

@conversation_bp.route('/conversation/<session_id>', methods=['DELETE'])
def delete_conversation(session_id: str):
    """
    删除对话（支持日期子目录结构）
    
    Args:
        session_id: 会话ID
    """
    conv_dir = get_conversations_dir()
    if not conv_dir:
        return jsonify({"error": "对话目录未配置"}), 500
    
    conv_file = _find_conversation_file(conv_dir, session_id)
    if not conv_file:
        return jsonify({"error": f"未找到对话: {session_id}"}), 404
    
    try:
        # 备份到 .deleted 目录（软删除）
        deleted_dir = conv_dir / ".deleted"
        deleted_dir.mkdir(exist_ok=True)
        
        import shutil
        backup_path = deleted_dir / f"{session_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jsonl"
        shutil.move(str(conv_file), str(backup_path))
        
        logger.info(f"对话已删除: {session_id} -> {backup_path}")
        
        return jsonify({
            "success": True,
            "message": f"对话 {session_id} 已删除",
            "backup_path": str(backup_path)
        })
    except Exception as e:
        logger.error(f"删除对话失败: {e}")
        return jsonify({"error": str(e)}), 500


# ==================== 总结为日记 ====================

@conversation_bp.route('/conversation/<session_id>/summarize', methods=['POST'])
def summarize_conversation(session_id: str):
    """
    总结对话并保存为日记（调用 LLM）
    
    Request Body:
        - manual_summary: 手动摘要（可选，如不提供则调用 LLM）
        - custom_prompt: 自定义提示词（可选，仅本次生效）
        - target_date: 目标日期（可选，默认为对话日期）
        - append: 是否追加到现有日记（默认true）
        - preview_only: 仅预览不保存（默认false）
    """
    conv_dir = get_conversations_dir()
    if not conv_dir:
        return jsonify({"error": "对话目录未配置"}), 500
    
    # 查找对话
    conv_file = _find_conversation_file(conv_dir, session_id)
    if not conv_file:
        return jsonify({"error": f"未找到对话: {session_id}"}), 404
    
    reader = ConversationFileReader()
    conv = reader.read_conversation(conv_file)
    
    if not conv.turns:
        return jsonify({"error": "对话无内容"}), 400
    
    data = request.get_json() or {}
    manual_summary = data.get('manual_summary')
    custom_prompt = data.get('custom_prompt')
    target_date = data.get('target_date') or conv_file.stem.split('_')[0]
    append_mode = data.get('append', True)
    preview_only = data.get('preview_only', False)
    
    try:
        if manual_summary:
            summary = manual_summary
        else:
            # 调用 LLM 自动总结
            summary = _auto_summarize_conversation(conv, custom_prompt=custom_prompt)
        
        if preview_only:
            return jsonify({
                "success": True,
                "preview": True,
                "summary": summary,
                "target_date": target_date
            })
        
        # 保存到日记
        from .core import get_writer
        writer = get_writer()
        
        if not writer:
            return jsonify({"error": "写入器未初始化"}), 500
        
        # 格式化日记内容
        formatted_content = _format_diary_entry(conv, summary)
        
        if append_mode:
            success = writer.append_to_diary(target_date, formatted_content, section="对话记录")
        else:
            success = writer.update_diary(target_date, formatted_content)
        
        if success:
            return jsonify({
                "success": True,
                "message": f"对话已总结到日记 {target_date}",
                "summary_preview": summary[:300] + "..." if len(summary) > 300 else summary,
                "target_date": target_date
            })
        else:
            return jsonify({"error": "保存日记失败"}), 500
            
    except Exception as e:
        logger.error(f"总结对话失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@conversation_bp.route('/conversations/batch-summarize', methods=['POST'])
def batch_summarize_conv():
    """
    批量总结对话为日记（逐个对话总结后合并）
    
    Request Body:
        - date: 目标日期
        - session_ids: 指定的会话ID列表（可选）
        - custom_prompt: 自定义提示词（可选）
    """
    data = request.get_json() or {}
    target_date = data.get('date')
    session_ids = data.get('session_ids', [])
    custom_prompt = data.get('custom_prompt')
    
    if not target_date:
        return jsonify({"error": "缺少 date 参数"}), 400
    
    conv_dir = get_conversations_dir()
    if not conv_dir:
        return jsonify({"error": "对话目录未配置"}), 500
    
    reader = ConversationFileReader()
    from .core import get_writer
    writer = get_writer()
    
    if not writer:
        return jsonify({"error": "写入器未初始化"}), 500
    
    # 收集要处理的对话
    conv_files = []
    if session_ids:
        for sid in session_ids:
            f = _find_conversation_file(conv_dir, sid)
            if f:
                conv_files.append(f)
    else:
        date_dir = conv_dir / target_date
        if date_dir.exists() and date_dir.is_dir():
            conv_files.extend(date_dir.glob("*.jsonl"))
        conv_files.extend([f for f in conv_dir.glob(f"{target_date}*.jsonl") if f.is_file()])
    
    if not conv_files:
        return jsonify({"error": f"未找到 {target_date} 的对话"}), 404
    
    conv_files.sort()
    
    diary_parts = []
    processed_count = 0
    
    for conv_file in conv_files:
        try:
            conv = reader.read_conversation(conv_file)
            if conv.turns:
                summary = _auto_summarize_conversation(conv, custom_prompt=custom_prompt)
                entry = _format_diary_entry(conv, summary)
                diary_parts.append(entry)
                processed_count += 1
        except Exception as e:
            logger.warning(f"处理对话失败 {conv_file.name}: {e}")
    
    if not diary_parts:
        return jsonify({"error": "无有效对话可总结"}), 400
    
    combined_content = "\n\n---\n\n".join(diary_parts)
    success = writer.append_to_diary(target_date, combined_content, section="对话记录")
    
    if success:
        return jsonify({
            "success": True,
            "message": f"已将 {processed_count} 个对话总结到日记 {target_date}",
            "processed_count": processed_count,
            "target_date": target_date
        })
    else:
        return jsonify({"error": "保存日记失败"}), 500


@conversation_bp.route('/conversations/day/<date>/summarize', methods=['POST'])
def summarize_day_to_diary(date: str):
    """
    将指定日期的全部对话一次性发给 LLM，总结为一篇完整日记
    
    与 batch-summarize 的区别：
    - batch-summarize 逐个对话总结再拼接
    - 此接口将全天对话合并后一次性发给 LLM，生成一篇连贯的日记
    
    Request Body:
        - custom_prompt: 自定义提示词（可选，仅本次生效）
        - preview_only: 仅预览不保存（默认false）
        - append: 追加到现有日记（默认true），false则覆盖
    """
    conv_dir = get_conversations_dir()
    if not conv_dir:
        return jsonify({"error": "对话目录未配置"}), 500
    
    data = request.get_json() or {}
    custom_prompt = data.get('custom_prompt')
    preview_only = data.get('preview_only', False)
    append_mode = data.get('append', True)
    
    # 收集该日期的所有对话文件
    all_files = _collect_conversation_files(conv_dir, date_filter=date)
    if not all_files:
        return jsonify({"error": f"未找到 {date} 的对话记录"}), 404
    
    reader = ConversationFileReader()
    conversations = []
    total_turns = 0
    
    for f, _ in all_files:
        try:
            conv = reader.read_conversation(f)
            if conv.turns:
                conversations.append(conv)
                total_turns += len(conv.turns)
        except Exception as e:
            logger.warning(f"读取对话文件失败 {f.name}: {e}")
    
    if not conversations:
        return jsonify({"error": "无有效对话可总结"}), 400
    
    # 按时间排序（按第一轮的时间戳）
    conversations.sort(key=lambda c: c.turns[0].timestamp if c.turns else datetime.min)
    
    try:
        # 格式化全天对话文本
        conv_texts = []
        for conv in conversations:
            conv_texts.append(_format_conversation_text(conv))
        combined_text = "\n\n--- 下一个对话会话 ---\n\n".join(conv_texts)
        
        # 获取配置
        llm_config = _get_conv_diary_config()
        
        # 构建 prompt
        prompt_template = custom_prompt or llm_config.get('day_prompt') or DEFAULT_DAY_DIARY_PROMPT
        user_message = prompt_template.replace('{conversations}', combined_text).replace('{date}', date)
        
        logger.info(f"[对话→日记] 总结 {date}: {len(conversations)} 个会话, {total_turns} 轮, "
                     f"模型={llm_config['model']}")
        
        # 调用 LLM
        diary_content = _call_summary_llm(user_message, llm_config)
        
        if not diary_content.strip():
            return jsonify({"error": "LLM 返回空内容"}), 500
        
        if preview_only:
            return jsonify({
                "success": True,
                "preview": True,
                "diary_content": diary_content,
                "target_date": date,
                "stats": {
                    "conversations": len(conversations),
                    "total_turns": total_turns,
                    "model": llm_config['model']
                }
            })
        
        # 保存到日记
        from .core import get_writer
        writer = get_writer()
        if not writer:
            return jsonify({"error": "写入器未初始化"}), 500
        
        if append_mode:
            success = writer.append_to_diary(date, diary_content, section="对话记录")
        else:
            success = writer.update_diary(date, diary_content)
        
        if success:
            return jsonify({
                "success": True,
                "message": f"已将 {date} 的 {len(conversations)} 个对话总结为日记",
                "diary_preview": diary_content[:500] + "..." if len(diary_content) > 500 else diary_content,
                "target_date": date,
                "stats": {
                    "conversations": len(conversations),
                    "total_turns": total_turns,
                    "model": llm_config['model']
                }
            })
        else:
            return jsonify({"error": "保存日记失败"}), 500
            
    except Exception as e:
        logger.error(f"[对话→日记] 总结 {date} 失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ==================== 统计接口 ====================

@conversation_bp.route('/conversations/stats', methods=['GET'])
def get_conv_stats():
    """获取对话统计信息（支持日期子目录结构）"""
    conv_dir = get_conversations_dir()
    if not conv_dir or not conv_dir.exists():
        return jsonify({
            "total_conversations": 0,
            "total_turns": 0,
            "date_range": None
        })
    
    all_files = []
    dates = set()
    
    # 1. 收集日期子目录中的文件
    for date_dir in conv_dir.iterdir():
        if date_dir.is_dir() and _is_date_dir(date_dir.name):
            dates.add(date_dir.name)
            all_files.extend(date_dir.glob("*.jsonl"))
    
    # 2. 兼容旧的扁平结构
    for f in conv_dir.glob("*.jsonl"):
        if f.is_file():
            all_files.append(f)
            try:
                date_part = f.stem.split('_')[0]
                if _is_date_dir(date_part):
                    dates.add(date_part)
            except:
                pass
    
    total_conversations = len(all_files)
    total_turns = 0
    
    for f in all_files:
        try:
            with open(f, 'r', encoding='utf-8') as file:
                for line in file:
                    if '"type": "turn"' in line:
                        total_turns += 1
        except:
            continue
    
    date_range = None
    if dates:
        sorted_dates = sorted(dates)
        date_range = {
            "earliest": sorted_dates[0],
            "latest": sorted_dates[-1]
        }
    
    # 今日统计
    today = datetime.now().strftime('%Y-%m-%d')
    today_files = []
    
    # 检查今天的子目录
    today_dir = conv_dir / today
    if today_dir.exists() and today_dir.is_dir():
        today_files.extend(today_dir.glob("*.jsonl"))
    
    # 兼容旧结构
    today_files.extend([f for f in conv_dir.glob(f"{today}*.jsonl") if f.is_file()])
    
    today_turns = 0
    for f in today_files:
        try:
            with open(f, 'r', encoding='utf-8') as file:
                for line in file:
                    if '"type": "turn"' in line:
                        today_turns += 1
        except:
            continue
    
    return jsonify({
        "total_conversations": total_conversations,
        "total_turns": total_turns,
        "date_range": date_range,
        "today": {
            "conversations": len(today_files),
            "turns": today_turns
        }
    })


# ==================== 辅助函数 ====================

def _auto_summarize_conversation(conv: ConversationData, custom_prompt: str = None) -> str:
    """
    自动总结对话（调用 LLM，失败时回退到简单提取）
    
    Args:
        conv: 对话数据
        custom_prompt: 自定义提示词（可选，仅本次生效）
    """
    if not conv.turns:
        return "（空对话）"
    
    try:
        llm_config = _get_conv_diary_config()
        conv_text = _format_conversation_text(conv)
        
        prompt_template = custom_prompt or llm_config.get('single_prompt') or DEFAULT_SINGLE_CONV_PROMPT
        user_message = prompt_template.replace('{conversation}', conv_text)
        
        logger.info(f"[对话→日记] 单对话 LLM 总结, 轮次={len(conv.turns)}, 模型={llm_config['model']}")
        
        result = _call_summary_llm(user_message, llm_config)
        if result.strip():
            return result
        
        logger.warning("[对话→日记] LLM 返回空内容，回退到简单提取")
    except Exception as e:
        logger.warning(f"[对话→日记] LLM 总结失败，回退到简单提取: {e}")
    
    # 回退：简单提取
    first_user_msg = conv.turns[0].user
    topic = first_user_msg[:100] + "..." if len(first_user_msg) > 100 else first_user_msg
    turn_count = len(conv.turns)
    duration = ""
    if conv.header and conv.footer:
        try:
            delta = conv.footer.end_time - conv.header.start_time
            if delta.seconds > 3600:
                duration = f"（持续 {delta.seconds // 3600} 小时）"
            elif delta.seconds > 60:
                duration = f"（持续 {delta.seconds // 60} 分钟）"
        except Exception:
            pass
    return f"与AI进行了 {turn_count} 轮对话{duration}，话题：{topic}"


def _format_diary_entry(conv: ConversationData, summary: str) -> str:
    """
    格式化日记条目
    """
    if not conv.header:
        return summary
    
    # 时间范围
    time_str = conv.header.start_time.strftime('%H:%M')
    if conv.footer:
        time_str += f" - {conv.footer.end_time.strftime('%H:%M')}"
    
    # 模型信息
    model = conv.header.model or "未知模型"
    
    # 格式化
    entry = f"### 🗣️ 对话 ({time_str})\n\n"
    entry += f"**模型**: {model} | **轮次**: {len(conv.turns)}\n\n"
    entry += f"{summary}\n"
    
    # 可选：添加关键对话摘录
    if len(conv.turns) <= 3:
        entry += "\n**对话摘录:**\n"
        for turn in conv.turns:
            user_preview = turn.user[:200] + "..." if len(turn.user) > 200 else turn.user
            assistant_preview = turn.assistant[:300] + "..." if len(turn.assistant) > 300 else turn.assistant
            entry += f"\n> 👤 {user_preview}\n>\n> 🤖 {assistant_preview}\n"
    
    return entry


# ==================== 图片访问接口 ====================

@conversation_bp.route('/conversations/image/<path:image_path>', methods=['GET'])
def get_conversation_image(image_path: str):
    """
    获取对话中的图片
    
    Args:
        image_path: 图片相对路径 (例如: 2026-01-23/images/turn_1_1_abc12345.png)
    """
    conv_dir = get_conversations_dir()
    if not conv_dir:
        abort(404, "对话目录未配置")
    
    # 构建完整路径
    full_path = conv_dir / image_path
    
    # 安全检查：确保路径在 conversations 目录内
    try:
        full_path = full_path.resolve()
        conv_dir_resolved = conv_dir.resolve()
        
        if not str(full_path).startswith(str(conv_dir_resolved)):
            logger.warning(f"非法图片路径访问尝试: {image_path}")
            abort(403, "禁止访问")
    except Exception as e:
        logger.error(f"路径解析失败: {e}")
        abort(400, "路径无效")
    
    if not full_path.exists():
        abort(404, "图片不存在")
    
    if not full_path.is_file():
        abort(400, "不是文件")
    
    # 检查文件扩展名
    allowed_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
    if full_path.suffix.lower() not in allowed_extensions:
        abort(400, "不支持的文件类型")
    
    # 返回图片
    mimetype = f'image/{full_path.suffix[1:].lower()}'
    if full_path.suffix.lower() == '.jpg':
        mimetype = 'image/jpeg'
    
    return send_file(full_path, mimetype=mimetype)


# ==================== 总结配置接口 ====================

@conversation_bp.route('/conversations/diary-config', methods=['GET'])
def get_conv_diary_config():
    """获取对话→日记总结配置"""
    try:
        config = load_config()
        conv_cfg = config.get('conversation_diary', {})
        resolved = _get_conv_diary_config()
        
        return jsonify({
            "model": resolved['model'],
            "api_key_set": bool(resolved['api_key']),
            "base_url": resolved['base_url'],
            "single_prompt": conv_cfg.get('single_prompt') or DEFAULT_SINGLE_CONV_PROMPT,
            "day_prompt": conv_cfg.get('day_prompt') or DEFAULT_DAY_DIARY_PROMPT,
            "max_tokens": resolved['max_tokens'],
            "temperature": resolved['temperature'],
            "using_defaults": {
                "single_prompt": not conv_cfg.get('single_prompt'),
                "day_prompt": not conv_cfg.get('day_prompt'),
                "model": not conv_cfg.get('model'),
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@conversation_bp.route('/conversations/diary-config', methods=['POST', 'PUT'])
def save_conv_diary_config():
    """保存对话→日记总结配置"""
    try:
        data = request.get_json()
        config = load_config()
        
        if 'conversation_diary' not in config:
            config['conversation_diary'] = {}
        
        cfg = config['conversation_diary']
        for key in ('model', 'api_key', 'base_url', 'single_prompt', 'day_prompt'):
            if key in data:
                cfg[key] = data[key]
        for key in ('max_tokens',):
            if key in data:
                cfg[key] = int(data[key])
        for key in ('temperature',):
            if key in data:
                cfg[key] = float(data[key])
        
        save_config(config)
        
        return jsonify({"success": True, "message": "对话→日记总结配置已保存"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
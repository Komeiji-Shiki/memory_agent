"""
Orchestrator Routes - 消息编排 API

提供以下接口：
- GET  /api/memory/orchestrator/sequence     - 获取当前消息序列
- PUT  /api/memory/orchestrator/sequence     - 保存消息序列
- POST /api/memory/orchestrator/preview      - 预览消息结构
- GET  /api/memory/orchestrator/presets      - 获取预设列表
- POST /api/memory/orchestrator/preset/load  - 加载预设
- POST /api/memory/orchestrator/preset/save  - 保存预设
- DELETE /api/memory/orchestrator/preset/<name> - 删除预设
- GET  /api/memory/orchestrator/bindings     - 获取模型绑定
- PUT  /api/memory/orchestrator/bindings     - 设置模型绑定
- GET  /api/memory/orchestrator/history      - 获取历史记录
- POST /api/memory/orchestrator/rollback     - 回滚到历史版本
- DELETE /api/memory/orchestrator/history    - 清空历史
- GET  /api/memory/orchestrator/export       - 导出配置
- POST /api/memory/orchestrator/import       - 导入配置
- POST /api/memory/orchestrator/test         - 测试发送
- GET  /api/memory/orchestrator/components   - 获取可用组件
- GET  /api/memory/orchestrator/prefill      - 获取预填充配置
- PUT  /api/memory/orchestrator/prefill      - 设置预填充配置
"""

from flask import Blueprint, jsonify, request
from pathlib import Path
import json

from memory_agent.message_orchestrator import get_orchestrator, MessageOrchestrator
from .core import get_lifebook_path, load_config

orchestrator_bp = Blueprint('orchestrator', __name__)


def _get_orchestrator() -> MessageOrchestrator:
    """获取编排器实例"""
    lifebook_path = get_lifebook_path()
    config_dir = Path(lifebook_path) / "extra"
    return get_orchestrator(config_dir)


@orchestrator_bp.route('/orchestrator/enabled', methods=['GET'])
def get_enabled():
    """获取消息编排器启用状态"""
    try:
        from .core import load_config
        config = load_config()
        orchestrator_cfg = config.get("message_orchestrator", {})
        enabled = orchestrator_cfg.get("enabled", False)
        
        return jsonify({
            "success": True,
            "enabled": enabled
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/enabled', methods=['PUT'])
def set_enabled():
    """设置消息编排器启用状态"""
    try:
        data = request.json or {}
        enabled = data.get('enabled', False)
        
        from .core import load_config, save_config
        config = load_config()
        
        # 确保 message_orchestrator 配置存在
        if "message_orchestrator" not in config:
            config["message_orchestrator"] = {}
        
        config["message_orchestrator"]["enabled"] = enabled
        save_config(config)
        
        return jsonify({
            "success": True,
            "enabled": enabled,
            "message": f"消息编排器已{'启用' if enabled else '禁用'}"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/sequence', methods=['GET'])
def get_sequence():
    """获取当前消息序列"""
    try:
        orchestrator = _get_orchestrator()
        return jsonify({
            "success": True,
            "sequence": orchestrator.get_sequence(),
            "active_preset": orchestrator.get_active_preset(),
            "available_components": orchestrator.get_available_components()
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/sequence', methods=['PUT'])
def save_sequence():
    """保存消息序列"""
    try:
        data = request.json or {}
        sequence = data.get('sequence', [])
        description = data.get('description', '更新序列')
        
        if not sequence:
            return jsonify({"success": False, "error": "序列不能为空"}), 400
        
        # 验证序列
        if not _validate_sequence(sequence):
            return jsonify({"success": False, "error": "序列格式无效"}), 400
        
        orchestrator = _get_orchestrator()
        orchestrator.set_sequence(sequence, description)
        
        return jsonify({
            "success": True,
            "message": "序列已保存"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/preview', methods=['POST'])
def preview_sequence():
    """预览消息结构"""
    try:
        data = request.json or {}
        # 允许空数组，不使用默认值
        test_messages = data.get('test_messages', [])
        full_preview = data.get('full_preview', False)
        model_name = data.get('model', '')
        
        orchestrator = _get_orchestrator()
        
        # 获取实际的记忆内容（如果需要完整预览）
        fixed_context = ""
        dynamic_context = ""
        prefix_content = ""
        suffix_content = ""
        extra_mount_enabled = False
        time_context = ""
        memory_range = ""
        tools_hint = ""
        pending_context = ""  # 新增：pending 内容
        
        if full_preview:
            # 从 context_builder 获取实际内容
            try:
                from memory_agent.context_builder import create_context_builder
                from .core import get_lifebook_path, load_config
                from datetime import datetime
                
                lifebook_path = get_lifebook_path()
                config = load_config()
                
                builder = create_context_builder(lifebook_path)
                fixed_context = builder._build_fixed_context()
                
                # 生成时间上下文
                now = datetime.now()
                time_context = builder._build_time_context_only(now)
                
                # 生成记忆范围
                memory_range = builder._build_memory_range_only()
                
                # 生成 pending 内容
                pending_context = builder._build_pending_memory(now)
                
                # 获取工具提示
                tools_hint = config.get('context', {}).get('main_model_tools_hint', '')
                
                # 获取额外挂载
                extra_cfg = config.get('context', {}).get('extra_mount', {})
                extra_mount_enabled = extra_cfg.get('enabled', False)
                
                if extra_mount_enabled:
                    prefix_path = Path(lifebook_path).parent / extra_cfg.get('prefix_path', 'lifebook/extra/prefix.md')
                    suffix_path = Path(lifebook_path).parent / extra_cfg.get('suffix_path', 'lifebook/extra/suffix.md')
                    
                    if prefix_path.exists():
                        prefix_content = prefix_path.read_text(encoding='utf-8')
                    if suffix_path.exists():
                        suffix_content = suffix_path.read_text(encoding='utf-8')
            except Exception as e:
                print(f"[Orchestrator] 获取完整预览内容失败: {e}")
                import traceback
                traceback.print_exc()
        else:
            # 简单预览模式 - 使用占位符显示结构
            from datetime import datetime
            now = datetime.now()
            time_context = f"📅 当前时间: {now.strftime('%Y-%m-%d %H:%M')} 星期{['一','二','三','四','五','六','日'][now.weekday()]}"
            memory_range = "📊 记忆库范围: 2025-12-29 ~ 2026-01-21 (共 24 条日记)"
            fixed_context = "📖 [分层记忆内容将在此显示：日记/周总结/月总结/季度总结]"
            dynamic_context = "🔍 [Agent 动态检索结果将在此显示]"
            tools_hint = "🔧 [工具调用提示词将在此显示]"
            prefix_content = "[前置挂载 prefix.md 内容]"
            suffix_content = "[后置挂载 suffix.md 内容]"
            pending_context = "🗒️ [今日待归档记录将在此显示]"  # 新增占位符
            extra_mount_enabled = True  # 简单预览时总是显示挂载占位符
        
        # 应用编排
        orchestrated = orchestrator.apply_orchestration(
            test_messages,
            model_name=model_name,
            fixed_context=fixed_context,
            dynamic_context=dynamic_context,
            extra_mount_enabled=extra_mount_enabled,
            prefix_content=prefix_content,
            suffix_content=suffix_content,
            time_context=time_context,
            memory_range=memory_range,
            tools_hint=tools_hint,
            pending_context=pending_context  # 新增：传递 pending
        )
        
        # 统计
        total_chars = sum(len(m.get('content', '')) for m in orchestrated)
        estimated_tokens = total_chars // 4  # 粗略估计
        
        # 构建预览结果
        preview_messages = []
        for i, m in enumerate(orchestrated):
            content = m.get('content', '')
            preview = content[:200] + "..." if len(content) > 200 else content
            
            preview_messages.append({
                "index": i,
                "role": m.get('role', 'unknown'),
                "preview": preview if not full_preview else content,
                "source": m.get('_source', 'original'),
                "char_count": len(content)
            })
        
        return jsonify({
            "success": True,
            "original_count": len(test_messages),
            "orchestrated_count": len(orchestrated),
            "total_chars": total_chars,
            "estimated_tokens": estimated_tokens,
            "messages": preview_messages
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/presets', methods=['GET'])
def get_presets():
    """获取预设列表"""
    try:
        orchestrator = _get_orchestrator()
        presets = orchestrator.get_presets()
        active = orchestrator.get_active_preset()
        
        # 简化返回数据
        preset_list = []
        for name, preset in presets.items():
            preset_list.append({
                "id": name,
                "name": preset.get('name', name),
                "description": preset.get('description', ''),
                "is_active": name == active,
                "component_count": len(preset.get('sequence', [])),
                "created_at": preset.get('created_at', ''),
                "updated_at": preset.get('updated_at', '')
            })
        
        return jsonify({
            "success": True,
            "presets": preset_list,
            "active_preset": active
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/preset/load', methods=['POST'])
def load_preset():
    """加载预设"""
    try:
        data = request.json or {}
        preset_name = data.get('preset_name', '')
        
        if not preset_name:
            return jsonify({"success": False, "error": "预设名称不能为空"}), 400
        
        orchestrator = _get_orchestrator()
        success = orchestrator.load_preset(preset_name)
        
        if success:
            return jsonify({
                "success": True,
                "message": f"已切换到预设: {preset_name}",
                "sequence": orchestrator.get_sequence()
            })
        else:
            return jsonify({"success": False, "error": "预设不存在"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/preset/save', methods=['POST'])
def save_preset():
    """保存预设"""
    try:
        data = request.json or {}
        preset_id = data.get('preset_id', '')
        name = data.get('name', '')
        description = data.get('description', '')
        
        if not preset_id or not name:
            return jsonify({"success": False, "error": "预设ID和名称不能为空"}), 400
        
        orchestrator = _get_orchestrator()
        success = orchestrator.save_preset(preset_id, name, description)
        
        if success:
            return jsonify({
                "success": True,
                "message": f"预设已保存: {name}"
            })
        else:
            return jsonify({"success": False, "error": "保存失败"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/preset/<preset_name>', methods=['DELETE'])
def delete_preset(preset_name: str):
    """删除预设"""
    try:
        if preset_name == 'default':
            return jsonify({"success": False, "error": "不能删除默认预设"}), 400
        
        orchestrator = _get_orchestrator()
        success = orchestrator.delete_preset(preset_name)
        
        if success:
            return jsonify({
                "success": True,
                "message": f"预设已删除: {preset_name}"
            })
        else:
            return jsonify({"success": False, "error": "预设不存在"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/bindings', methods=['GET'])
def get_bindings():
    """获取模型绑定"""
    try:
        orchestrator = _get_orchestrator()
        bindings = orchestrator.get_model_bindings()
        presets = orchestrator.get_presets()
        
        return jsonify({
            "success": True,
            "bindings": bindings,
            "available_presets": list(presets.keys())
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/bindings', methods=['PUT'])
def set_bindings():
    """设置模型绑定"""
    try:
        data = request.json or {}
        bindings = data.get('bindings', {})
        
        orchestrator = _get_orchestrator()
        orchestrator.set_model_bindings(bindings)
        
        return jsonify({
            "success": True,
            "message": "模型绑定已更新"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/history', methods=['GET'])
def get_history():
    """获取历史记录"""
    try:
        orchestrator = _get_orchestrator()
        history = orchestrator.get_history()
        
        # 简化返回数据（不包含完整快照）
        history_list = []
        for i, entry in enumerate(history):
            history_list.append({
                "index": i,
                "timestamp": entry.get('timestamp', ''),
                "action": entry.get('action', ''),
                "description": entry.get('description', '')
            })
        
        return jsonify({
            "success": True,
            "history": history_list,
            "total": len(history_list)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/rollback', methods=['POST'])
def rollback():
    """回滚到历史版本"""
    try:
        data = request.json or {}
        index = data.get('index', -1)
        
        if index < 0:
            return jsonify({"success": False, "error": "无效的历史索引"}), 400
        
        orchestrator = _get_orchestrator()
        success = orchestrator.rollback_to(index)
        
        if success:
            return jsonify({
                "success": True,
                "message": "已回滚到指定版本",
                "sequence": orchestrator.get_sequence()
            })
        else:
            return jsonify({"success": False, "error": "回滚失败"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/history', methods=['DELETE'])
def clear_history():
    """清空历史记录"""
    try:
        orchestrator = _get_orchestrator()
        orchestrator.clear_history()
        
        return jsonify({
            "success": True,
            "message": "历史记录已清空"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/export', methods=['GET'])
def export_config():
    """导出配置"""
    try:
        orchestrator = _get_orchestrator()
        config = orchestrator.export_config()
        
        return jsonify({
            "success": True,
            "config": config
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/import', methods=['POST'])
def import_config():
    """导入配置"""
    try:
        data = request.json or {}
        config = data.get('config', {})
        
        if not config:
            return jsonify({"success": False, "error": "配置不能为空"}), 400
        
        orchestrator = _get_orchestrator()
        success = orchestrator.import_config(config)
        
        if success:
            return jsonify({
                "success": True,
                "message": "配置已导入",
                "sequence": orchestrator.get_sequence()
            })
        else:
            return jsonify({"success": False, "error": "导入失败"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/test', methods=['POST'])
def test_send():
    """测试发送消息"""
    try:
        data = request.json or {}
        test_message = data.get('message', '你好')
        model = data.get('model', '')
        
        if not model:
            return jsonify({"success": False, "error": "请指定测试模型"}), 400
        
        orchestrator = _get_orchestrator()
        config = load_config()
        
        # 构建测试消息 - 使用通用占位符或尝试从配置获取
        system_content = "(测试系统提示词)"
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": test_message}
        ]
        
        # 获取实际记忆内容
        fixed_context = ""
        try:
            from memory_agent.context_builder import create_context_builder
            lifebook_path = get_lifebook_path()
            builder = create_context_builder(lifebook_path)
            fixed_context = builder._build_fixed_context()
        except Exception as e:
            print(f"[Orchestrator] 获取记忆内容失败: {e}")
        
        # 应用编排
        orchestrated = orchestrator.apply_orchestration(
            messages,
            model_name=model,
            fixed_context=fixed_context
        )
        
        # 清理 _source 标记
        clean_messages = []
        for m in orchestrated:
            clean_msg = {"role": m["role"], "content": m["content"]}
            clean_messages.append(clean_msg)
        
        # 发送到模型
        import time
        start_time = time.time()
        
        try:
            from proxy.model_router import ModelRouter
            router = ModelRouter(config)
            
            # 使用内部模型（不加 -memory 后缀）
            base_model = model.replace('-memory', '')
            
            response = router.chat_completion(
                model=base_model,
                messages=clean_messages,
                stream=False
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            # 提取回复内容
            if response and 'choices' in response and response['choices']:
                content = response['choices'][0].get('message', {}).get('content', '')
                usage = response.get('usage', {})
                
                return jsonify({
                    "success": True,
                    "response": content,
                    "usage": {
                        "prompt_tokens": usage.get('prompt_tokens', 0),
                        "completion_tokens": usage.get('completion_tokens', 0),
                        "total_tokens": usage.get('total_tokens', 0)
                    },
                    "latency_ms": latency_ms,
                    "orchestrated_count": len(orchestrated),
                    "model": base_model
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "模型返回格式异常",
                    "raw_response": response
                }), 500
                
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"调用模型失败: {str(e)}"
            }), 500
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/components', methods=['GET'])
def get_components():
    """获取可用组件列表"""
    try:
        orchestrator = _get_orchestrator()
        components = orchestrator.get_available_components()
        
        return jsonify({
            "success": True,
            "components": components
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/prefill', methods=['GET'])
def get_prefill():
    """获取预填充配置"""
    try:
        orchestrator = _get_orchestrator()
        prefill_config = orchestrator.get_prefill_config()
        
        return jsonify({
            "success": True,
            "prefill": prefill_config
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@orchestrator_bp.route('/orchestrator/prefill', methods=['PUT'])
def set_prefill():
    """设置预填充配置"""
    try:
        data = request.json or {}
        content = data.get('content', '')
        model_bindings = data.get('model_bindings', {})
        think_tag = data.get('think_tag', '</think>')
        
        orchestrator = _get_orchestrator()
        orchestrator.set_prefill_config(content, model_bindings, think_tag)
        
        return jsonify({
            "success": True,
            "message": "预填充配置已保存"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _validate_sequence(sequence: list) -> bool:
    """验证序列格式"""
    if not isinstance(sequence, list):
        return False
    
    required_types = {'system_prompt', 'real_messages'}
    found_types = set()
    
    for item in sequence:
        if not isinstance(item, dict):
            return False
        if 'type' not in item or 'id' not in item:
            return False
        found_types.add(item['type'])
    
    # 必须包含 system_prompt 和 real_messages
    return required_types.issubset(found_types)
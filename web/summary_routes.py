"""
总结生成 API 路由
"""

from flask import Blueprint, request, jsonify
from .core import load_config, save_config, get_lifebook_path, get_reader

# 创建蓝图
summary_bp = Blueprint('summary_api', __name__)

# 总结生成器（延迟初始化）
_summary_generator = None
_summary_config = None


def _get_summary_generator():
    """获取总结生成器"""
    global _summary_generator, _summary_config
    
    if _summary_generator is None:
        lifebook_path = get_lifebook_path()
        config = load_config()
        
        summary_cfg = config.get('auto_summary', {})
        agent_cfg = config.get('memory_agent', {})
        
        from memory_store.summary_generator import SummaryGenerator, SummaryConfig
        
        _summary_config = SummaryConfig(
            model=summary_cfg.get('model', agent_cfg.get('model', 'deepseek-chat')),
            api_key=summary_cfg.get('api_key') or agent_cfg.get('api_key') or config.get('api_key', ''),
            base_url=summary_cfg.get('base_url') or agent_cfg.get('base_url', 'https://api.deepseek.com/v1'),
            weekly_prompt=summary_cfg.get('weekly_prompt', ''),
            monthly_prompt=summary_cfg.get('monthly_prompt', ''),
            quarterly_prompt=summary_cfg.get('quarterly_prompt', '')
        )
        
        _summary_generator = SummaryGenerator(lifebook_path, _summary_config)
    
    return _summary_generator


@summary_bp.route('/summary/generate', methods=['POST'])
def generate_summary():
    """生成总结"""
    try:
        data = request.get_json()
        summary_type = data.get('type')
        identifier = data.get('identifier')
        
        if not summary_type or not identifier:
            return jsonify({"error": "缺少 type 或 identifier"}), 400
        
        if summary_type not in ('weekly', 'monthly', 'quarterly'):
            return jsonify({"error": "type 必须是 weekly/monthly/quarterly"}), 400
        
        generator = _get_summary_generator()
        
        # 临时覆盖配置
        if data.get('model'):
            generator.config.model = data['model']
        if data.get('prompt'):
            if summary_type == 'weekly':
                generator.config.weekly_prompt = data['prompt']
            elif summary_type == 'monthly':
                generator.config.monthly_prompt = data['prompt']
            elif summary_type == 'quarterly':
                generator.config.quarterly_prompt = data['prompt']
        
        # 生成
        if summary_type == 'weekly':
            result = generator.generate_weekly(identifier)
        elif summary_type == 'monthly':
            result = generator.generate_monthly(identifier)
        else:
            result = generator.generate_quarterly(identifier)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@summary_bp.route('/summary/retry-last', methods=['POST'])
def retry_last_summary():
    """手动重试最后一次对话的总结功能"""
    try:
        from memory_router import get_memory_router
        router = get_memory_router()
        
        if not router:
            return jsonify({"error": "路由器未初始化"}), 500
            
        last_conv = router.get_last_conversation()
        if last_conv is None:
            return jsonify({"error": "没有可重试的对话记录（可能已过期或服务器重启后缓存清空）"}), 404

        messages, response_content, main_reasoning = last_conv
        
        summary = router.summarize_and_save(
            messages=messages,
            response_content=response_content,
            async_mode=False,
            main_model_reasoning=main_reasoning
        )
        
        if summary:
            return jsonify({
                "success": True,
                "message": "重试总结成功，已存入待处理",
                "summary_preview": summary[:200] + "..." if len(summary) > 200 else summary
            })
        else:
            return jsonify({
                "success": False,
                "message": "重试总结完成，但模型判断不值得记录或执行失败"
            })
            
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@summary_bp.route('/summary/missing', methods=['GET'])
def get_missing_summaries():
    """获取缺失的总结列表"""
    try:
        lookback = request.args.get('lookback', 6, type=int)
        generator = _get_summary_generator()
        missing = generator.get_missing_summaries(lookback)
        return jsonify(missing)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@summary_bp.route('/summary/config', methods=['GET'])
def get_summary_config():
    """获取总结生成配置"""
    try:
        config = load_config()
        summary_cfg = config.get('auto_summary', {})
        agent_cfg = config.get('memory_agent', {})
        
        # 默认提示词
        default_weekly = """请根据以下一周的日记内容，生成一份简洁的周度总结。

要求：
1. 用第一人称（"我"）撰写
2. 突出本周重要事件、进展、心情变化
3. 提炼关键收获或反思
4. 保持简洁，500字左右

日记内容：
{diary_content}

请生成周总结："""

        default_monthly = """请根据以下内容，生成一份月度总结。

要求：
1. 用第一人称（"我"）撰写
2. 总结本月主要事件和进展
3. 分析本月的成就和不足
4. 展望下月计划（如有）
5. 800字左右

内容：
{content}

请生成月度总结："""

        default_quarterly = """请根据以下季度的月总结，生成一份季度总结。

要求：
1. 用第一人称（"我"）撰写
2. 回顾本季度的主要成就和变化
3. 提炼重要的人、事、成长
4. 总结教训和经验
5. 1000字左右

月总结内容：
{content}

请生成季度总结："""
        
        return jsonify({
            "model": summary_cfg.get('model', agent_cfg.get('model', 'deepseek-chat')),
            "weekly_prompt": summary_cfg.get('weekly_prompt') or default_weekly,
            "monthly_prompt": summary_cfg.get('monthly_prompt') or default_monthly,
            "quarterly_prompt": summary_cfg.get('quarterly_prompt') or default_quarterly,
            "enable_retry": summary_cfg.get('enable_retry', True),
            "max_retries": summary_cfg.get('max_retries', 3),
            "base_delay": summary_cfg.get('base_delay', 1.0),
            "max_delay": summary_cfg.get('max_delay', 30.0),
            "using_defaults": {
                "weekly": not summary_cfg.get('weekly_prompt'),
                "monthly": not summary_cfg.get('monthly_prompt'),
                "quarterly": not summary_cfg.get('quarterly_prompt')
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@summary_bp.route('/summary/config', methods=['POST', 'PUT'])
def save_summary_config():
    """保存总结生成配置"""
    try:
        data = request.get_json()
        config = load_config()
        
        if 'auto_summary' not in config:
            config['auto_summary'] = {}
        
        if 'model' in data:
            config['auto_summary']['model'] = data['model']
        if 'weekly_prompt' in data:
            config['auto_summary']['weekly_prompt'] = data['weekly_prompt']
        if 'monthly_prompt' in data:
            config['auto_summary']['monthly_prompt'] = data['monthly_prompt']
        if 'quarterly_prompt' in data:
            config['auto_summary']['quarterly_prompt'] = data['quarterly_prompt']
        
        if 'enable_retry' in data:
            config['auto_summary']['enable_retry'] = data['enable_retry']
        if 'max_retries' in data:
            config['auto_summary']['max_retries'] = data['max_retries']
        if 'base_delay' in data:
            config['auto_summary']['base_delay'] = data['base_delay']
        if 'max_delay' in data:
            config['auto_summary']['max_delay'] = data['max_delay']
        
        save_config(config)
        
        # 重置生成器
        global _summary_generator
        _summary_generator = None
        
        return jsonify({"success": True, "message": "配置已保存"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@summary_bp.route('/summaries', methods=['GET'])
def list_summaries():
    """列出所有总结"""
    reader = get_reader()
    
    if not reader:
        return jsonify({"error": "组件未初始化"}), 500
    
    summary_type = request.args.get('type', 'all')
    
    result = {}
    types_to_check = ['weekly', 'monthly', 'quarterly', 'yearly'] if summary_type == 'all' else [summary_type]
    
    for t in types_to_check:
        identifiers = reader.list_summaries(t)
        summaries = []
        for ident in identifiers[:20]:
            summary = reader.read_summary(t, ident)
            if summary:
                summaries.append({
                    "identifier": ident,
                    "title": summary.title,
                    "preview": summary.content[:150] + "..." if len(summary.content) > 150 else summary.content
                })
        result[t] = summaries
    
    return jsonify(result)
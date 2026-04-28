/**
 * Admin Config - 配置设置
 */

async function loadConfig() {
    try {
        const data = await apiCall('/config?reveal_secrets=1');
        if (data && data.config) {
            const cfg = data.config;
            
            // 1. 基本设置
            document.getElementById('cfg-api-key').value = cfg.api_key || '';
            document.getElementById('cfg-port').value = cfg.port || 8003;
            document.getElementById('cfg-host').value = cfg.host || '0.0.0.0';
            document.getElementById('cfg-memory-enabled').checked = cfg.memory_enabled !== false;
            document.getElementById('cfg-mcp-enabled').checked = cfg.mcp_enabled === true;
            document.getElementById('cfg-max-retries').value = cfg.max_retries || 0;
            document.getElementById('cfg-keep-tool-results').value = cfg.keep_tool_results_count || 0;

            // 2. Agent设置
            if (cfg.memory_agent) {
                const ma = cfg.memory_agent;
                document.getElementById('cfg-agent-model').value = ma.model || 'deepseek-reasoner';
                document.getElementById('cfg-agent-url').value = ma.base_url || 'https://api.deepseek.com/v1';
                document.getElementById('cfg-agent-key').value = ma.api_key || '';
                document.getElementById('cfg-agent-max-iter').value = ma.max_iterations || 30;
                document.getElementById('cfg-agent-timeout').value = ma.timeout || 60;
                document.getElementById('cfg-agent-prompt').value = ma.system_prompt || '';
                document.getElementById('cfg-agent-query-instruction').value = ma.query_instruction || '';
            }
            
            // 3. 上下文设置
            if (cfg.context) {
                const ctx = cfg.context;
                document.getElementById('cfg-insertion-position').value = ctx.insertion_position || 'system_append';
                document.getElementById('cfg-recent-days').value = ctx.recent_days || 7;
                document.getElementById('cfg-max-context-tokens').value = ctx.max_context_tokens || 8000;
                
                if (ctx.layered_memory) {
                    const layer = ctx.layered_memory;
                    document.getElementById('cfg-layer-enabled').checked = layer.enabled !== false;
                    document.getElementById('cfg-max-chars-diary').value = layer.short_term?.max_chars_per_entry || 3000;
                    document.getElementById('cfg-max-chars-weekly').value = layer.weekly?.max_chars || 1500;
                    document.getElementById('cfg-max-chars-monthly').value = layer.monthly?.max_chars || 2000;
                    document.getElementById('cfg-max-chars-quarterly').value = layer.quarterly?.max_chars || 2500;
                }
                
                // 自定义内容
                if (ctx.custom_content) {
                    document.getElementById('cfg-custom-content-enabled').checked = ctx.custom_content.enabled === true;
                    document.getElementById('cfg-custom-content').value = ctx.custom_content.content || '';
                }
            }
            
            // 4. 主模型工具
            if (cfg.main_model_memory_tools) {
                const mmt = cfg.main_model_memory_tools;
                document.getElementById('cfg-main-model-tools').checked = mmt.enabled !== false;
                document.getElementById('cfg-main-model-write').checked = mmt.include_write_tools === true;
                document.getElementById('cfg-main-tools-hint').value = mmt.tools_hint || '';
            }
            
            // 5. 对话后总结
            if (cfg.post_conversation) {
                const post = cfg.post_conversation;
                document.getElementById('cfg-post-enabled').checked = post.enabled !== false;
                document.getElementById('cfg-post-auto').checked = post.auto_summarize !== false;
                document.getElementById('cfg-post-model').value = post.summarize_model || 'deepseek-chat';
                document.getElementById('cfg-post-min-msgs').value = post.min_messages || 2;
                document.getElementById('cfg-post-pending-max').value = post.pending_preview_max_chars || 200;
                document.getElementById('cfg-post-prompt').value = post.summarize_prompt || '';
                document.getElementById('cfg-post-suffix').value = post.summarize_suffix || '';
                const postUrlEl = document.getElementById('cfg-post-url');
                if (postUrlEl) postUrlEl.value = post.base_url || '';
                const postKeyEl = document.getElementById('cfg-post-key');
                if (postKeyEl) postKeyEl.value = post.api_key || '';
                
                // 高级 LLM 参数
                document.getElementById('cfg-post-max-tokens-normal').value = post.max_tokens_normal || 1500;
                document.getElementById('cfg-post-max-tokens-reasoner').value = post.max_tokens_reasoner || 3000;
                document.getElementById('cfg-post-temperature').value = post.temperature ?? 0.3;
                document.getElementById('cfg-post-top-p').value = post.top_p ?? '';
                document.getElementById('cfg-post-max-context-chars').value = post.max_context_chars || 100000;
            }

            // 6. DeepSeek Thinking 模式
            if (cfg.deepseek_thinking_mode) {
                document.getElementById('cfg-thinking-enabled').checked = cfg.deepseek_thinking_mode.enabled !== false;
                document.getElementById('cfg-thinking-auto').checked = cfg.deepseek_thinking_mode.auto_detect !== false;
            }
            
            showToast('配置已加载', 'success');
        } else if (data && data.error) {
            showToast('加载配置失败: ' + data.error, 'error');
        }
    } catch (e) {
        showToast('加载配置失败: ' + e.message, 'error');
    }
}

async function saveConfig() {
    const config = {
        api_key: document.getElementById('cfg-api-key').value,
        port: parseInt(document.getElementById('cfg-port').value) || 8003,
        host: document.getElementById('cfg-host').value,
        memory_enabled: document.getElementById('cfg-memory-enabled').checked,
        mcp_enabled: document.getElementById('cfg-mcp-enabled').checked,
        max_retries: parseInt(document.getElementById('cfg-max-retries').value) || 0,
        keep_tool_results_count: parseInt(document.getElementById('cfg-keep-tool-results').value) || 0,
        log_level: document.getElementById('cfg-log-level').value || 'INFO',
        memory_agent: {
            model: document.getElementById('cfg-agent-model').value,
            base_url: document.getElementById('cfg-agent-url').value,
            api_key: document.getElementById('cfg-agent-key').value,
            max_iterations: parseInt(document.getElementById('cfg-agent-max-iter').value) || 30,
            timeout: parseInt(document.getElementById('cfg-agent-timeout').value) || 60,
            system_prompt: document.getElementById('cfg-agent-prompt').value,
            query_instruction: document.getElementById('cfg-agent-query-instruction').value
        },
        context: {
            insertion_position: document.getElementById('cfg-insertion-position').value,
            recent_days: parseInt(document.getElementById('cfg-recent-days').value) || 7,
            max_context_tokens: parseInt(document.getElementById('cfg-max-context-tokens').value) || 8000,
            layered_memory: {
                enabled: document.getElementById('cfg-layer-enabled').checked,
                short_term: { max_chars_per_entry: parseInt(document.getElementById('cfg-max-chars-diary').value) || 3000 },
                weekly: { enabled: true, max_chars: parseInt(document.getElementById('cfg-max-chars-weekly').value) || 1500 },
                monthly: { enabled: true, max_chars: parseInt(document.getElementById('cfg-max-chars-monthly').value) || 2000 },
                quarterly: { enabled: true, max_chars: parseInt(document.getElementById('cfg-max-chars-quarterly').value) || 2500 }
            },
            custom_content: {
                enabled: document.getElementById('cfg-custom-content-enabled').checked,
                content: document.getElementById('cfg-custom-content').value
            }
        },
        main_model_memory_tools: {
            enabled: document.getElementById('cfg-main-model-tools').checked,
            include_write_tools: document.getElementById('cfg-main-model-write').checked,
            tools_hint: document.getElementById('cfg-main-tools-hint').value
        },
        post_conversation: {
            enabled: document.getElementById('cfg-post-enabled').checked,
            auto_summarize: document.getElementById('cfg-post-auto').checked,
            summarize_model: document.getElementById('cfg-post-model').value,
            min_messages: parseInt(document.getElementById('cfg-post-min-msgs').value) || 2,
            pending_preview_max_chars: parseInt(document.getElementById('cfg-post-pending-max').value) || 200,
            summarize_prompt: document.getElementById('cfg-post-prompt').value,
            summarize_suffix: document.getElementById('cfg-post-suffix').value,
            base_url: document.getElementById('cfg-post-url')?.value || '',
            api_key: document.getElementById('cfg-post-key')?.value || '',
            // 高级 LLM 参数
            max_tokens_normal: parseInt(document.getElementById('cfg-post-max-tokens-normal').value) || 1500,
            max_tokens_reasoner: parseInt(document.getElementById('cfg-post-max-tokens-reasoner').value) || 3000,
            temperature: parseFloat(document.getElementById('cfg-post-temperature').value) || 0.3,
            top_p: document.getElementById('cfg-post-top-p').value ? parseFloat(document.getElementById('cfg-post-top-p').value) : null,
            max_context_chars: parseInt(document.getElementById('cfg-post-max-context-chars').value) || 100000
        },
        deepseek_thinking_mode: {
            enabled: document.getElementById('cfg-thinking-enabled').checked,
            auto_detect: document.getElementById('cfg-thinking-auto').checked
        }
    };
    
    try {
        const result = await apiCall('/config', 'POST', config);
        if (result && result.success) {
            showToast('配置已保存（部分设置需要重启服务器生效）', 'success');
        } else {
            showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}
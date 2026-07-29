/**
 * 系统设置页
 * - 基本设置 / DeepSeek Thinking / 记忆 Agent / 上下文 / 对话后总结 / 对话保留
 * - 修复：log_level 加载回填（旧版保存时会误重置为 INFO）
 * - 修复：temperature 为 0 时不再被当成默认值覆盖
 * - 不再打开页面自动 rebuild-index
 */

import { apiCall } from '../core/api.js';
import { showToast, bindActions, delegate } from '../core/ui.js';
import { markDirty, clearDirty, isDirty } from '../core/store.js';

const DIRTY_MAIN = 'config:main';
const DIRTY_LOGGER = 'config:logger';

let rootEl = null;
let loaded = false;

export const configPage = {
    id: 'config',
    title: '系统设置',
    icon: '⚙️',
    group: 'settings',

    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="page-header">
                <h2>⚙️ 系统设置</h2>
                <p>编辑代理服务、记忆 Agent、上下文与总结行为</p>
            </div>

            <div class="card">
                <div class="card-header"><h3>基本设置</h3></div>
                <div class="form-group">
                    <label class="form-label">主 API Key (DeepSeek)</label>
                    <div class="input-with-btn">
                        <input type="password" id="cfg-api-key" class="form-input" placeholder="sk-...">
                        <button class="btn btn-sm" data-action="toggle-pw" data-target="cfg-api-key">👁️</button>
                    </div>
                    <div class="form-hint">用于记忆 Agent（deepseek-reasoner）和默认请求</div>
                </div>
                <div class="form-row cols-3">
                    <div class="form-group">
                        <label class="form-label">最大重试次数</label>
                        <input type="number" id="cfg-max-retries" class="form-input" value="0" min="0" max="10">
                        <div class="form-hint">LLM 调用失败重试次数，0 = 不重试</div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">监听端口</label>
                        <input type="number" id="cfg-port" class="form-input" value="8003">
                    </div>
                    <div class="form-group">
                        <label class="form-label">监听地址</label>
                        <select id="cfg-host" class="form-select">
                            <option value="127.0.0.1">127.0.0.1 (仅本机)</option>
                            <option value="0.0.0.0" selected>0.0.0.0 (允许局域网)</option>
                        </select>
                    </div>
                </div>
                <div class="form-row cols-3">
                    <div class="form-group">
                        <label class="checkbox-label"><input type="checkbox" id="cfg-memory-enabled" checked>启用记忆增强功能</label>
                    </div>
                    <div class="form-group">
                        <label class="checkbox-label"><input type="checkbox" id="cfg-mcp-enabled">启用 MCP 功能（记忆模式下自动禁用）</label>
                    </div>
                    <div class="form-group">
                        <label class="form-label">日志级别</label>
                        <select id="cfg-log-level" class="form-select">
                            <option value="DEBUG">DEBUG - 详细调试信息</option>
                            <option value="INFO" selected>INFO - 重要状态变更</option>
                            <option value="WARNING">WARNING - 警告信息</option>
                            <option value="ERROR">ERROR - 仅错误信息</option>
                        </select>
                        <div class="form-hint">重启后生效</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>🧠 DeepSeek Thinking 模式</h3></div>
                <div class="alert alert-info">
                    <span>💡</span>
                    <div>DeepSeek 模型需要在工具调用消息中包含 <code>reasoning_content</code> 字段，但 Claude 等模型不支持。建议启用<strong>自动检测</strong>，按模型名称自动判断。</div>
                </div>
                <div class="form-row cols-2">
                    <div class="form-group">
                        <label class="checkbox-label"><input type="checkbox" id="cfg-thinking-enabled" checked>启用 Thinking 模式</label>
                        <div class="form-hint">为工具调用消息添加 reasoning_content 字段</div>
                    </div>
                    <div class="form-group">
                        <label class="checkbox-label"><input type="checkbox" id="cfg-thinking-auto" checked>自动检测模型类型</label>
                        <div class="form-hint">只对 DeepSeek/Reasoner 模型添加此字段（推荐）</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>记忆 Agent 设置</h3></div>
                <div class="form-row cols-2">
                    <div class="form-group">
                        <label class="form-label">Agent 模型</label>
                        <input type="text" id="cfg-agent-model" class="form-input" value="deepseek-reasoner">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Agent API 地址</label>
                        <input type="text" id="cfg-agent-url" class="form-input" value="https://api.deepseek.com/v1">
                    </div>
                </div>
                <div class="form-row cols-2">
                    <div class="form-group">
                        <label class="form-label">Agent API Key (可选)</label>
                        <div class="input-with-btn">
                            <input type="password" id="cfg-agent-key" class="form-input" placeholder="留空则使用主 Key">
                            <button class="btn btn-sm" data-action="toggle-pw" data-target="cfg-agent-key">👁️</button>
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">最大迭代 / 超时(s)</label>
                        <div class="input-with-btn">
                            <input type="number" id="cfg-agent-max-iter" class="form-input" value="30" title="最大迭代步数">
                            <input type="number" id="cfg-agent-timeout" class="form-input" value="60" title="超时秒数">
                        </div>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Agent 系统提示词 (System Prompt)</label>
                    <textarea id="cfg-agent-prompt" class="form-input" rows="7" placeholder="你是记忆检索助手..."></textarea>
                    <div class="form-hint">Agent 负责执行 search_memories 检索任务，提示词决定检索质量</div>
                </div>
                <div class="form-group">
                    <label class="form-label">查询指示 (Query Instruction)</label>
                    <textarea id="cfg-agent-query-instruction" class="form-input" rows="4" placeholder="附加在每次查询时的指示..."></textarea>
                    <div class="form-hint">每次调用 Agent 时，在用户查询前附加此指示，引导搜索行为</div>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>上下文设置</h3></div>
                <div class="form-row cols-2">
                    <div class="form-group">
                        <label class="form-label">记忆插入位置</label>
                        <select id="cfg-insertion-position" class="form-select">
                            <option value="system_prepend">系统提示词最前面</option>
                            <option value="system_append" selected>系统提示词末尾（推荐）</option>
                            <option value="after_system">系统消息后独立插入</option>
                            <option value="before_last_user">最后用户消息前</option>
                            <option value="replace_system">替换系统提示</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">工具结果保留数</label>
                        <input type="number" id="cfg-keep-tool-results" class="form-input" value="3">
                    </div>
                </div>
                <div class="form-row cols-2">
                    <div class="form-group">
                        <label class="form-label">最近日记天数</label>
                        <input type="number" id="cfg-recent-days" class="form-input" value="7">
                    </div>
                    <div class="form-group">
                        <label class="form-label">最大上下文 Token</label>
                        <input type="number" id="cfg-max-context-tokens" class="form-input" value="8000">
                    </div>
                </div>
                <div class="form-row cols-3">
                    <div class="form-group">
                        <label class="checkbox-label"><input type="checkbox" id="cfg-main-model-tools" checked>允许主模型调用记忆工具</label>
                    </div>
                    <div class="form-group">
                        <label class="checkbox-label"><input type="checkbox" id="cfg-main-model-write" checked>允许主模型写入记忆</label>
                    </div>
                    <div class="form-group">
                        <label class="checkbox-label"><input type="checkbox" id="cfg-layer-enabled" checked>启用分层记忆过滤</label>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">给主模型的工具调用建议 (Tools Hint)</label>
                    <textarea id="cfg-main-tools-hint" class="form-input" rows="3" placeholder="上面已经为你检索了相关记忆..."></textarea>
                    <div class="form-hint">追加到系统提示词末尾，告诉主模型何时动用记忆工具</div>
                </div>

                <h4 style="margin: 20px 0 10px; color: var(--accent);">📌 自定义内容插入</h4>
                <div class="form-group">
                    <label class="checkbox-label"><input type="checkbox" id="cfg-custom-content-enabled">启用自定义内容插入</label>
                    <div class="form-hint">在记忆内容后插入自定义文本（角色设定、特殊指令等），以「📌 附加说明」形式追加</div>
                </div>
                <div class="form-group">
                    <textarea id="cfg-custom-content" class="form-input" rows="5" placeholder="在这里输入想要插入的内容..."></textarea>
                </div>

                <h4 style="margin: 20px 0 10px; color: var(--accent);">✂️ 分层记忆截断（字符数）</h4>
                <div class="form-row cols-4">
                    <div class="form-group">
                        <label class="form-label">单条日记</label>
                        <input type="number" id="cfg-max-chars-diary" class="form-input" value="3000">
                    </div>
                    <div class="form-group">
                        <label class="form-label">周总结</label>
                        <input type="number" id="cfg-max-chars-weekly" class="form-input" value="1500">
                    </div>
                    <div class="form-group">
                        <label class="form-label">月总结</label>
                        <input type="number" id="cfg-max-chars-monthly" class="form-input" value="2000">
                    </div>
                    <div class="form-group">
                        <label class="form-label">季度总结</label>
                        <input type="number" id="cfg-max-chars-quarterly" class="form-input" value="2500">
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>📝 对话后总结（自动记日记）</h3></div>
                <div class="form-row cols-2">
                    <div class="form-group">
                        <label class="checkbox-label"><input type="checkbox" id="cfg-post-enabled" checked>启用对话总结功能</label>
                    </div>
                    <div class="form-group">
                        <label class="checkbox-label"><input type="checkbox" id="cfg-post-auto" checked>对话后自动生成摘要并暂存 (Pending)</label>
                    </div>
                </div>
                <div class="form-row cols-3">
                    <div class="form-group">
                        <label class="form-label">总结模型</label>
                        <input type="text" id="cfg-post-model" class="form-input" value="deepseek-chat">
                    </div>
                    <div class="form-group">
                        <label class="form-label">最小触发消息数</label>
                        <input type="number" id="cfg-post-min-msgs" class="form-input" value="2">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Pending 预览字数限制</label>
                        <input type="number" id="cfg-post-pending-max" class="form-input" value="200">
                    </div>
                </div>

                <div class="collapsible">
                    <div class="collapsible-header">
                        <span>⚙️ 高级 LLM 参数</span>
                        <span class="collapsible-toggle">▼</span>
                    </div>
                    <div class="collapsible-content">
                        <div class="alert alert-info">
                            <span>💡</span>
                            <div><strong>max_tokens</strong>：限制输出长度 | <strong>temperature</strong>：0=确定性，1=创造性 | <strong>top_p</strong>：核采样参数</div>
                        </div>
                        <div class="form-row cols-4">
                            <div class="form-group">
                                <label class="form-label">Max Tokens (普通模型)</label>
                                <input type="number" id="cfg-post-max-tokens-normal" class="form-input" value="1500" min="100" max="16000">
                            </div>
                            <div class="form-group">
                                <label class="form-label">Max Tokens (Reasoner)</label>
                                <input type="number" id="cfg-post-max-tokens-reasoner" class="form-input" value="3000" min="100" max="32000">
                            </div>
                            <div class="form-group">
                                <label class="form-label">Temperature</label>
                                <input type="number" id="cfg-post-temperature" class="form-input" value="0.3" step="0.1" min="0" max="2">
                            </div>
                            <div class="form-group">
                                <label class="form-label">Top P</label>
                                <input type="number" id="cfg-post-top-p" class="form-input" placeholder="留空不设置" step="0.1" min="0" max="1">
                            </div>
                        </div>
                        <div class="form-group">
                            <label class="form-label">最大上下文字符数</label>
                            <input type="number" id="cfg-post-max-context-chars" class="form-input" value="100000" min="10000" max="500000" style="width: 200px;">
                            <div class="form-hint">对话内容超过此长度时截断，默认 100000</div>
                        </div>
                    </div>
                </div>

                <div class="form-row cols-2" style="margin-top: 15px;">
                    <div class="form-group">
                        <label class="form-label">总结 Base URL（可选）</label>
                        <input type="text" id="cfg-post-url" class="form-input" placeholder="留空 = 跟随模型路由/Agent">
                        <div class="form-hint">仅影响「对话后总结」调用</div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">总结 API Key（可选）</label>
                        <div class="input-with-btn">
                            <input type="password" id="cfg-post-key" class="form-input" placeholder="留空 = 跟随模型路由/Agent">
                            <button class="btn btn-sm" data-action="toggle-pw" data-target="cfg-post-key">👁️</button>
                        </div>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">总结提示词 (Prompt)</label>
                    <textarea id="cfg-post-prompt" class="form-input" rows="7" placeholder="不填则使用系统默认"></textarea>
                </div>
                <div class="form-group">
                    <label class="form-label">对话后额外提示 (Suffix)</label>
                    <textarea id="cfg-post-suffix" class="form-input" rows="3" placeholder="请分析上述对话内容，然后调用 record_summary 工具..."></textarea>
                    <div class="form-hint">追加在对话内容后，用于强调"分析当前对话"并调用工具</div>
                </div>
            </div>

            <div class="card" id="conv-logger-card">
                <div class="card-header">
                    <h3>💬 对话保留机制</h3>
                    <button class="btn btn-sm btn-success" data-action="save-logger">💾 保存对话保留设置</button>
                </div>
                <div class="alert alert-info">
                    <span>💡</span>
                    <div>原始对话完整保存到 <code>lifebook/conversations/</code>，用于日记生成重试、历史查阅、Graphiti 索引。</div>
                </div>
                <div class="form-group">
                    <label class="checkbox-label"><input type="checkbox" id="cfg-conv-enabled" checked>启用原始对话保留</label>
                </div>
                <div class="form-row cols-3">
                    <div class="form-group">
                        <label class="form-label">会话超时（分钟）</label>
                        <input type="number" id="cfg-conv-timeout" class="form-input" value="30" min="5" max="120">
                        <div class="form-hint">超时无新消息则视为新会话</div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">前缀匹配阈值</label>
                        <input type="number" id="cfg-conv-threshold" class="form-input" value="0.7" step="0.1" min="0.5" max="1">
                        <div class="form-hint">判断是否是续写</div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">单文件最大轮次</label>
                        <input type="number" id="cfg-conv-max-turns" class="form-input" value="100" min="10" max="500">
                    </div>
                </div>
            </div>

            <div style="display: flex; gap: 10px; margin-bottom: 40px;">
                <button class="btn btn-primary" data-action="reload">🔄 重新加载</button>
                <button class="btn btn-success" data-action="save">💾 保存配置</button>
            </div>
        `;

        bindActions(container, {
            'toggle-pw': (target) => {
                const input = container.querySelector('#' + target.dataset.target);
                if (input) input.type = input.type === 'password' ? 'text' : 'password';
            },
            'reload': () => { loadMainConfig(); loadLoggerConfig(); },
            'save': saveMainConfig,
            'save-logger': saveLoggerConfig,
        });

        // 脏数据跟踪：区分主配置与对话保留
        delegate(container, 'input', '.form-input, .form-select, input[type="checkbox"]', (e, target) => {
            if (target.closest('#conv-logger-card')) {
                markDirty(DIRTY_LOGGER, '对话保留设置');
            } else {
                markDirty(DIRTY_MAIN, '系统设置');
            }
        });
    },

    onEnter() {
        // 有未保存修改时不覆盖编辑中的内容
        if (!loaded || !isDirty()) {
            loadMainConfig();
            loadLoggerConfig();
        }
    },
};

// ===== 主配置 =====

async function loadMainConfig() {
    const data = await apiCall('/config?reveal_secrets=1');
    if (!data || data.error || !data.config) {
        showToast('加载配置失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }
    const cfg = data.config;

    setVal('cfg-api-key', cfg.api_key);
    setVal('cfg-port', cfg.port ?? 8003);
    setVal('cfg-host', cfg.host || '0.0.0.0');
    setChecked('cfg-memory-enabled', cfg.memory_enabled !== false);
    setChecked('cfg-mcp-enabled', cfg.mcp_enabled === true);
    setVal('cfg-max-retries', cfg.max_retries ?? 0);
    setVal('cfg-keep-tool-results', cfg.keep_tool_results_count ?? 0);
    // 修复：回填日志级别（旧版遗漏，导致保存时被重置为 INFO）
    setVal('cfg-log-level', cfg.log_level || 'INFO');

    const ma = cfg.memory_agent || {};
    setVal('cfg-agent-model', ma.model || 'deepseek-reasoner');
    setVal('cfg-agent-url', ma.base_url || 'https://api.deepseek.com/v1');
    setVal('cfg-agent-key', ma.api_key);
    setVal('cfg-agent-max-iter', ma.max_iterations ?? 30);
    setVal('cfg-agent-timeout', ma.timeout ?? 60);
    setVal('cfg-agent-prompt', ma.system_prompt);
    setVal('cfg-agent-query-instruction', ma.query_instruction);

    const ctx = cfg.context || {};
    setVal('cfg-insertion-position', ctx.insertion_position || 'system_append');
    setVal('cfg-recent-days', ctx.recent_days ?? 7);
    setVal('cfg-max-context-tokens', ctx.max_context_tokens ?? 8000);
    const layer = ctx.layered_memory || {};
    setChecked('cfg-layer-enabled', layer.enabled !== false);
    setVal('cfg-max-chars-diary', layer.short_term?.max_chars_per_entry ?? 3000);
    setVal('cfg-max-chars-weekly', layer.weekly?.max_chars ?? 1500);
    setVal('cfg-max-chars-monthly', layer.monthly?.max_chars ?? 2000);
    setVal('cfg-max-chars-quarterly', layer.quarterly?.max_chars ?? 2500);
    const custom = ctx.custom_content || {};
    setChecked('cfg-custom-content-enabled', custom.enabled === true);
    setVal('cfg-custom-content', custom.content);

    const mmt = cfg.main_model_memory_tools || {};
    setChecked('cfg-main-model-tools', mmt.enabled !== false);
    setChecked('cfg-main-model-write', mmt.include_write_tools === true);
    setVal('cfg-main-tools-hint', mmt.tools_hint);

    const post = cfg.post_conversation || {};
    setChecked('cfg-post-enabled', post.enabled !== false);
    setChecked('cfg-post-auto', post.auto_summarize !== false);
    setVal('cfg-post-model', post.summarize_model || 'deepseek-chat');
    setVal('cfg-post-min-msgs', post.min_messages ?? 2);
    setVal('cfg-post-pending-max', post.pending_preview_max_chars ?? 200);
    setVal('cfg-post-prompt', post.summarize_prompt);
    setVal('cfg-post-suffix', post.summarize_suffix);
    setVal('cfg-post-url', post.base_url);
    setVal('cfg-post-key', post.api_key);
    setVal('cfg-post-max-tokens-normal', post.max_tokens_normal ?? 1500);
    setVal('cfg-post-max-tokens-reasoner', post.max_tokens_reasoner ?? 3000);
    setVal('cfg-post-temperature', post.temperature ?? 0.3);
    setVal('cfg-post-top-p', post.top_p ?? '');
    setVal('cfg-post-max-context-chars', post.max_context_chars ?? 100000);

    const think = cfg.deepseek_thinking_mode || {};
    setChecked('cfg-thinking-enabled', think.enabled !== false);
    setChecked('cfg-thinking-auto', think.auto_detect !== false);

    loaded = true;
    clearDirty(DIRTY_MAIN);
    showToast('配置已加载', 'success');
}

async function saveMainConfig() {
    const config = {
        api_key: getVal('cfg-api-key'),
        port: intVal('cfg-port', 8003),
        host: getVal('cfg-host'),
        memory_enabled: getChecked('cfg-memory-enabled'),
        mcp_enabled: getChecked('cfg-mcp-enabled'),
        max_retries: intVal('cfg-max-retries', 0),
        keep_tool_results_count: intVal('cfg-keep-tool-results', 0),
        log_level: getVal('cfg-log-level') || 'INFO',
        memory_agent: {
            model: getVal('cfg-agent-model'),
            base_url: getVal('cfg-agent-url'),
            api_key: getVal('cfg-agent-key'),
            max_iterations: intVal('cfg-agent-max-iter', 30),
            timeout: intVal('cfg-agent-timeout', 60),
            system_prompt: getVal('cfg-agent-prompt'),
            query_instruction: getVal('cfg-agent-query-instruction'),
        },
        context: {
            insertion_position: getVal('cfg-insertion-position'),
            recent_days: intVal('cfg-recent-days', 7),
            max_context_tokens: intVal('cfg-max-context-tokens', 8000),
            layered_memory: {
                enabled: getChecked('cfg-layer-enabled'),
                short_term: { max_chars_per_entry: intVal('cfg-max-chars-diary', 3000) },
                weekly: { enabled: true, max_chars: intVal('cfg-max-chars-weekly', 1500) },
                monthly: { enabled: true, max_chars: intVal('cfg-max-chars-monthly', 2000) },
                quarterly: { enabled: true, max_chars: intVal('cfg-max-chars-quarterly', 2500) },
            },
            custom_content: {
                enabled: getChecked('cfg-custom-content-enabled'),
                content: getVal('cfg-custom-content'),
            },
        },
        main_model_memory_tools: {
            enabled: getChecked('cfg-main-model-tools'),
            include_write_tools: getChecked('cfg-main-model-write'),
            tools_hint: getVal('cfg-main-tools-hint'),
        },
        post_conversation: {
            enabled: getChecked('cfg-post-enabled'),
            auto_summarize: getChecked('cfg-post-auto'),
            summarize_model: getVal('cfg-post-model'),
            min_messages: intVal('cfg-post-min-msgs', 2),
            pending_preview_max_chars: intVal('cfg-post-pending-max', 200),
            summarize_prompt: getVal('cfg-post-prompt'),
            summarize_suffix: getVal('cfg-post-suffix'),
            base_url: getVal('cfg-post-url'),
            api_key: getVal('cfg-post-key'),
            max_tokens_normal: intVal('cfg-post-max-tokens-normal', 1500),
            max_tokens_reasoner: intVal('cfg-post-max-tokens-reasoner', 3000),
            temperature: floatVal('cfg-post-temperature', 0.3),
            top_p: getVal('cfg-post-top-p') === '' ? null : floatVal('cfg-post-top-p', null),
            max_context_chars: intVal('cfg-post-max-context-chars', 100000),
        },
        deepseek_thinking_mode: {
            enabled: getChecked('cfg-thinking-enabled'),
            auto_detect: getChecked('cfg-thinking-auto'),
        },
    };

    const result = await apiCall('/config', 'POST', config);
    if (result && result.success) {
        clearDirty(DIRTY_MAIN);
        showToast('配置已保存（部分设置需要重启服务器生效）', 'success');
    } else {
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

// ===== 对话保留配置 =====

async function loadLoggerConfig() {
    const config = await apiCall('/graphiti/conversation-logger/config');
    if (!config || config.error) return;
    setChecked('cfg-conv-enabled', config.enabled !== false);
    setVal('cfg-conv-timeout', config.session_timeout_minutes ?? 30);
    setVal('cfg-conv-threshold', config.prefix_match_threshold ?? 0.7);
    setVal('cfg-conv-max-turns', config.max_turns_per_file ?? 100);
    clearDirty(DIRTY_LOGGER);
}

async function saveLoggerConfig() {
    const config = {
        enabled: getChecked('cfg-conv-enabled'),
        session_timeout_minutes: intVal('cfg-conv-timeout', 30),
        prefix_match_threshold: floatVal('cfg-conv-threshold', 0.7),
        max_turns_per_file: intVal('cfg-conv-max-turns', 100),
    };
    const result = await apiCall('/graphiti/conversation-logger/config', 'POST', config);
    if (result && result.success) {
        clearDirty(DIRTY_LOGGER);
        showToast('对话保留配置已保存', 'success');
    } else {
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

// ===== 表单工具 =====

function el(id) { return rootEl.querySelector('#' + id); }
function getVal(id) { return el(id)?.value ?? ''; }
function getChecked(id) { return el(id)?.checked === true; }
function setVal(id, value) { const e = el(id); if (e) e.value = value ?? ''; }
function setChecked(id, checked) { const e = el(id); if (e) e.checked = checked; }

function intVal(id, fallback) {
    const n = parseInt(getVal(id), 10);
    return Number.isFinite(n) ? n : fallback;
}

function floatVal(id, fallback) {
    const n = parseFloat(getVal(id));
    return Number.isFinite(n) ? n : fallback;
}

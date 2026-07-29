/**
 * 调试日志页
 * - LLM 调用日志列表（类型过滤/数量限制/统计卡）
 * - 日志详情弹窗（system prompt / prompt / messages / response）
 * - 复制完整 Prompt、清空日志、添加测试日志
 * - 重试最后一次对话总结
 */

import { apiCall } from '../core/api.js';
import {
    showToast, showModal, closeModal, confirmDialog,
    escapeHtml, spinnerHtml, emptyHtml, errorHtml, bindActions,
} from '../core/ui.js';

let rootEl = null;

const TYPE_META = {
    search_agent: { emoji: '🔍', label: '搜索Agent', color: 'var(--accent)' },
    post_conversation: { emoji: '💬', label: '对话后总结', color: '#a78bfa' },
    summary_generate: { emoji: '📝', label: '总结生成', color: 'var(--success)' },
    pending_consolidate: { emoji: '📦', label: '待处理汇总', color: 'var(--warning)' },
};

const CODE_BLOCK_STYLE = 'padding: 10px 12px; background: var(--surface-2); border: 1px solid var(--line-weak); border-radius: 6px; white-space: pre-wrap; word-break: break-word; font-size: 0.82rem; line-height: 1.55;';

export const debugPage = {
    id: 'debug',
    title: '调试日志',
    icon: '🔧',
    group: 'ops',

    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="page-header">
                <h2>🔧 调试日志</h2>
                <p>LLM 调用的提示词与响应记录</p>
            </div>

            <div class="card">
                <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                    <select id="debug-log-type" class="form-select" style="width: auto;">
                        <option value="">全部类型</option>
                        <option value="search_agent">🔍 搜索Agent</option>
                        <option value="post_conversation">💬 对话后总结</option>
                        <option value="summary_generate">📝 总结生成</option>
                        <option value="pending_consolidate">📦 待处理汇总</option>
                    </select>
                    <select id="debug-log-limit" class="form-select" style="width: auto;">
                        <option value="20">最近 20 条</option>
                        <option value="50" selected>最近 50 条</option>
                        <option value="100">最近 100 条</option>
                    </select>
                    <button class="btn btn-sm btn-primary" data-action="refresh-logs">🔄 刷新</button>
                    <button class="btn btn-sm btn-danger" data-action="clear-logs">🗑️ 清空日志</button>
                    <span style="flex: 1;"></span>
                    <button class="btn btn-sm btn-warning" data-action="retry-last" title="把最后一次对话重新发给总结模型">♻️ 重试最后总结</button>
                    <button class="btn btn-sm" data-action="add-test-log">🧪 添加测试日志</button>
                </div>
            </div>

            <div id="debug-stats" style="margin-bottom: 20px;"></div>

            <div class="card">
                <div class="card-header"><h3>📜 日志列表</h3></div>
                <div id="debug-logs-list">${spinnerHtml()}</div>
            </div>
        `;

        bindActions(container, {
            'refresh-logs': loadDebugLogs,
            'clear-logs': clearDebugLogs,
            'retry-last': retryLastSummary,
            'add-test-log': addTestLog,
            'open-log': (t) => showLogDetail(parseInt(t.dataset.index)),
        });

        container.querySelector('#debug-log-type').addEventListener('change', loadDebugLogs);
        container.querySelector('#debug-log-limit').addEventListener('change', loadDebugLogs);
    },

    onEnter() {
        loadDebugLogs();
    },
};

async function loadDebugLogs() {
    const container = rootEl.querySelector('#debug-logs-list');
    const statsContainer = rootEl.querySelector('#debug-stats');
    container.innerHTML = spinnerHtml();

    const logType = rootEl.querySelector('#debug-log-type').value;
    const limit = rootEl.querySelector('#debug-log-limit').value;

    let endpoint = `/debug/logs?limit=${encodeURIComponent(limit)}`;
    if (logType) endpoint += `&type=${encodeURIComponent(logType)}`;

    const data = await apiCall(endpoint);
    if (!data || data.error) {
        container.innerHTML = errorHtml('加载失败: ' + (data?.error || '未知错误'));
        return;
    }

    // 统计卡
    const stats = data.stats || {};
    statsContainer.innerHTML = `
    <div class="stats-grid" style="margin-bottom: 0;">
        <div class="stat-card">
            <div class="stat-card-label">📊 总日志数</div>
            <div class="stat-card-value">${stats.total || 0}</div>
            <div class="stat-card-detail">/ ${stats.max_logs || 100} 条上限</div>
        </div>
        <div class="stat-card">
            <div class="stat-card-label">🔍 搜索Agent</div>
            <div class="stat-card-value">${stats.by_type?.search_agent || 0}</div>
            <div class="stat-card-detail">条记录</div>
        </div>
        <div class="stat-card">
            <div class="stat-card-label">📝 总结生成</div>
            <div class="stat-card-value">${stats.by_type?.summary_generate || 0}</div>
            <div class="stat-card-detail">条记录</div>
        </div>
        <div class="stat-card">
            <div class="stat-card-label">📦 待处理汇总</div>
            <div class="stat-card-value">${stats.by_type?.pending_consolidate || 0}</div>
            <div class="stat-card-detail">条记录</div>
        </div>
    </div>`;

    // 日志列表
    const logs = data.logs || [];
    if (logs.length === 0) {
        container.innerHTML = emptyHtml('暂无日志记录');
        return;
    }

    container.innerHTML = logs.map((log, index) => {
        const timeStr = new Date(log.timestamp).toLocaleString('zh-CN');
        const typeInfo = TYPE_META[log.log_type] || { emoji: '❓', label: log.log_type, color: 'var(--text-dim)' };

        const extraInfo = [];
        if (log.extra) {
            if (log.extra.summary_type) extraInfo.push(`类型: ${log.extra.summary_type}`);
            if (log.extra.identifier) extraInfo.push(`标识: ${log.extra.identifier}`);
            if (log.extra.session_id) extraInfo.push(`会话: ${log.extra.session_id}`);
            if (log.extra.query) extraInfo.push(`查询: ${log.extra.query.substring(0, 30)}...`);
        }

        return `
        <div class="list-item" data-action="open-log" data-index="${index}" style="cursor: pointer; border-left: 4px solid ${typeInfo.color};">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; flex-wrap: wrap; gap: 6px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="color: ${typeInfo.color}; font-weight: 700;">${typeInfo.emoji} ${escapeHtml(typeInfo.label)}</span>
                    <span class="badge badge-info">${escapeHtml(log.model || '-')}</span>
                </div>
                <span class="text-dim" style="font-size: 0.8rem;">${escapeHtml(timeStr)}</span>
            </div>
            ${extraInfo.length ? `<div class="text-dim" style="font-size: 0.8rem; margin-bottom: 6px;">${extraInfo.map((info) => escapeHtml(info)).join(' <span style="opacity: 0.3;">|</span> ')}</div>` : ''}
            <div style="font-size: 0.85rem; max-height: 60px; overflow: hidden; opacity: 0.8;">${escapeHtml((log.prompt || '').substring(0, 200))}</div>
        </div>`;
    }).join('');
}

async function showLogDetail(index) {
    const log = await apiCall(`/debug/logs/${index}`);
    if (!log || log.error) {
        showToast('加载失败: ' + (log?.error || '未知错误'), 'error');
        return;
    }

    const timeStr = new Date(log.timestamp).toLocaleString('zh-CN');
    const typeInfo = TYPE_META[log.log_type] || { emoji: '❓', label: log.log_type };

    let bodyHtml = `
        <div style="display: flex; gap: 20px; margin-bottom: 20px; align-items: center; background: var(--surface-2); padding: 15px; border-radius: 8px; flex-wrap: wrap;">
            <div><span class="text-dim">时间：</span><strong>${escapeHtml(timeStr)}</strong></div>
            <div><span class="text-dim">模型：</span><span class="badge badge-info">${escapeHtml(log.model || '-')}</span></div>
        </div>`;

    const section = (title, content, extraStyle = '') => `
        <div style="margin-bottom: 18px;">
            <div style="font-weight: 600; color: var(--accent); margin-bottom: 8px;">${title}</div>
            <div style="${CODE_BLOCK_STYLE} ${extraStyle}">${content}</div>
        </div>`;

    if (log.extra && Object.keys(log.extra).length > 0) {
        bodyHtml += section('📋 额外信息', escapeHtml(JSON.stringify(log.extra, null, 2)), 'max-height: 200px; overflow-y: auto;');
    }
    if (log.system_prompt) {
        bodyHtml += section('🤖 系统提示词 (System Prompt)', escapeHtml(log.system_prompt, true), 'max-height: 300px; overflow-y: auto;');
    }
    if (log.prompt) {
        bodyHtml += section('💬 提示词内容 (Prompt)', escapeHtml(log.prompt, true), 'max-height: 500px; overflow-y: auto;');
    }
    if (log.messages && log.messages.length > 0) {
        bodyHtml += section(`📨 完整消息列表 (${log.messages.length} 条)`, escapeHtml(JSON.stringify(log.messages, null, 2)), 'max-height: 400px; overflow-y: auto;');
    }
    if (log.response) {
        bodyHtml += section('✅ 模型响应', escapeHtml(log.response, true), 'max-height: 400px; overflow-y: auto; color: var(--success);');
    }

    const modal = showModal(`${typeInfo.emoji} ${escapeHtml(typeInfo.label)} 详情`, bodyHtml, {
        size: 'xlarge',
        footer: `
            <button class="btn btn-primary" data-act="copy">📋 复制完整 Prompt</button>
            <button class="btn" data-modal-close>关闭</button>
        `,
    });

    modal.querySelector('[data-act="copy"]').addEventListener('click', () => copyDebugLog(log));
}

async function copyDebugLog(log) {
    try {
        let text = `=== ${log.log_type} ===\n`;
        text += `时间: ${log.timestamp}\n`;
        text += `模型: ${log.model}\n\n`;
        if (log.system_prompt) {
            text += `=== System Prompt ===\n${log.system_prompt}\n\n`;
        }
        text += `=== Prompt ===\n${log.prompt || ''}\n`;

        await navigator.clipboard.writeText(text);
        showToast('提示词已复制到剪贴板', 'success');
    } catch {
        showToast('复制失败', 'error');
    }
}

async function clearDebugLogs() {
    const ok = await confirmDialog('确定要清空所有调试日志吗？', { danger: true, okText: '清空' });
    if (!ok) return;

    const data = await apiCall('/debug/logs', 'DELETE');
    if (data && data.success) {
        showToast('日志已清空', 'success');
        loadDebugLogs();
    } else {
        showToast('清空失败: ' + (data?.error || '未知错误'), 'error');
    }
}

async function retryLastSummary() {
    const ok = await confirmDialog('确定要重试最后一次对话的总结吗？\n\n这会把刚刚的对话内容和主模型的思考过程一起发给总结模型。', { okText: '重试' });
    if (!ok) return;

    showToast('正在重试总结...', 'info');
    const data = await apiCall('/summary/retry-last', 'POST');
    if (data && data.success) {
        showToast(data.message, 'success');
    } else {
        showToast('总结失败: ' + (data?.message || data?.error || '未知错误'), 'warning');
    }
}

async function addTestLog() {
    const data = await apiCall('/debug/test', 'POST');
    if (data && data.success) {
        showToast('测试日志已添加，刷新查看', 'success');
        loadDebugLogs();
    } else {
        showToast('添加失败: ' + (data?.error || '未知错误'), 'error');
    }
}

/**
 * 记忆库页
 * - 待处理会话（睡眠分割）：列表 / 汇总 / 汇总+节点 / 直接转换 / 查看 / 配置
 * - 已归档会话：列表 / 恢复 / 查看
 * - 最近日记：列表 / 查看
 * - 节点管理：列表 / 类型过滤 / 新建 / 查看 / 编辑
 * - 关键词搜索、索引重建
 */

import { apiCall } from '../core/api.js';
import {
    showToast, showModal, closeModal, confirmDialog,
    escapeHtml, escapeAttr, spinnerHtml, emptyHtml, bindActions,
} from '../core/ui.js';

const NODE_TYPE_ICONS = { '人物': '👤', '地点': '📍', '事物': '📦', '概念': '💡', '事件': '📅' };

let rootEl = null;

export const memoryPage = {
    id: 'memory',
    title: '记忆库',
    icon: '🧠',
    group: 'memory',

    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="page-header">
                <h2>🧠 记忆库</h2>
                <p>管理待处理会话、日记、节点和索引</p>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>📋 待处理会话（智能分割）</h3>
                    <div class="card-actions">
                        <button class="btn btn-sm btn-success" data-action="consolidate-all">🚀 智能汇总</button>
                        <button class="btn btn-sm" data-action="refresh-pending">🔄 刷新</button>
                    </div>
                </div>
                <div class="alert alert-info">
                    <span>💡</span>
                    <div>系统检测<strong>睡眠间隔</strong>自动划分"清醒周期"，每个会话汇总时生成独立日记。<strong style="color: var(--success);">绿色</strong> = 已结束（可汇总） | <strong style="color: var(--accent);">蓝色</strong> = 进行中</div>
                </div>

                <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 15px; padding: 12px; background: var(--surface-2); border-radius: 8px; flex-wrap: wrap;">
                    <span class="text-dim">⏰ 睡眠间隔阈值：</span>
                    <input type="number" id="sleep-gap-hours" class="form-input" style="width: 80px;" value="6" min="1" max="24" step="0.5">
                    <span class="text-dim">小时</span>
                    <button class="btn btn-sm" data-action="save-sleep-gap">保存</button>
                    <span class="text-dim" style="font-size: 0.8rem; margin-left: auto;">超过此时间无对话则视为"睡眠"</span>
                </div>

                <div class="collapsible">
                    <div class="collapsible-header">
                        <span>📝 汇总提示词配置</span>
                        <span class="collapsible-toggle">▼</span>
                    </div>
                    <div class="collapsible-content">
                        <div class="form-group">
                            <label class="form-label">新建日记提示词（无现有日记时使用）</label>
                            <textarea id="pending-consolidate-prompt" class="form-input" rows="8" placeholder="留空使用默认"></textarea>
                            <div class="form-hint">变量：{content} = 对话摘要内容</div>
                        </div>
                        <div class="form-group">
                            <label class="form-label">合并日记提示词（当天已有日记时使用）</label>
                            <textarea id="pending-merge-prompt" class="form-input" rows="8" placeholder="留空使用默认"></textarea>
                            <div class="form-hint">变量：{existing_content} = 现有日记内容，{content} = 新摘要内容</div>
                        </div>
                        <div class="form-group">
                            <label class="form-label">🔧 汇总+节点提示词（工具调用模式）</label>
                            <textarea id="pending-tools-prompt" class="form-input" rows="10" placeholder="留空使用默认"></textarea>
                            <div class="form-hint">用于"汇总+节点"模式。变量：{content}。⚠️ 提示词需包含工具使用说明，引导 LLM 调用 create_node 等工具</div>
                        </div>
                        <button class="btn btn-success" data-action="save-pending-prompts">💾 保存提示词</button>
                    </div>
                </div>

                <div id="pending-stats" style="margin-top: 15px;">${spinnerHtml()}</div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>📦 已归档会话（已汇总）</h3>
                    <button class="btn btn-sm" data-action="refresh-archived">🔄 刷新</button>
                </div>
                <div class="alert alert-info">
                    <span>💡</span>
                    <div>已汇总成日记并归档的会话。汇总效果不满意时可以<strong>恢复</strong>到待处理列表重新汇总。</div>
                </div>
                <div id="archived-sessions">${spinnerHtml()}</div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>📖 最近日记</h3>
                    <button class="btn btn-sm btn-primary" data-action="refresh-diaries">🔄 刷新</button>
                </div>
                <div id="recent-diaries">${spinnerHtml()}</div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>📦 节点管理</h3>
                    <div class="card-actions">
                        <select id="node-type-filter" class="form-select" style="width: 130px;">
                            <option value="">全部类型</option>
                            <option value="人物">👤 人物</option>
                            <option value="地点">📍 地点</option>
                            <option value="事物">📦 事物</option>
                            <option value="概念">💡 概念</option>
                            <option value="事件">📅 事件</option>
                        </select>
                        <button class="btn btn-sm btn-success" data-action="create-node">✨ 新建节点</button>
                        <button class="btn btn-sm" data-action="refresh-nodes">🔄 刷新</button>
                    </div>
                </div>
                <div id="nodes-list">${spinnerHtml()}</div>
            </div>

            <div class="card">
                <div class="card-header"><h3>🔍 搜索记忆</h3></div>
                <div class="input-with-btn" style="margin-bottom: 15px;">
                    <input type="text" id="memory-search-query" class="form-input" placeholder="输入搜索关键词...">
                    <button class="btn btn-primary" data-action="search-memories">🔍 搜索</button>
                </div>
                <div id="memory-search-results"></div>
            </div>

            <div class="card">
                <div class="card-header"><h3>🗂️ 索引管理</h3></div>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <button class="btn btn-primary" data-action="rebuild-index">🔄 重建索引</button>
                    <span id="index-status" class="text-dim"></span>
                </div>
            </div>
        `;

        bindActions(container, {
            'consolidate-all': consolidateAll,
            'refresh-pending': loadPendingStats,
            'save-sleep-gap': saveSleepGap,
            'save-pending-prompts': savePendingPrompts,
            'refresh-archived': loadArchivedSessions,
            'refresh-diaries': loadRecentDiaries,
            'refresh-nodes': () => loadNodes(),
            'create-node': showCreateNodeDialog,
            'search-memories': searchMemories,
            'rebuild-index': rebuildIndex,
            // 列表内动态按钮
            'view-diary': (t) => viewDiary(t.dataset.date),
            'view-node': (t) => viewNode(t.dataset.name),
            'edit-node': (t) => editNode(t.dataset.name),
            'consolidate-session': (t) => consolidateSession(t.dataset.id),
            'consolidate-options': (t) => showConsolidateOptions(t.dataset.id),
            'direct-convert': (t) => directConvert(t.dataset.id),
            'view-session': (t) => viewSession(t.dataset.id),
            'restore-session': (t) => restoreSession(t.dataset.id),
            'view-archived': (t) => viewArchivedSession(t.dataset.id),
        });

        container.querySelector('#node-type-filter').addEventListener('change', (e) => loadNodes(e.target.value));
        container.querySelector('#memory-search-query').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') searchMemories();
        });
    },

    onEnter() {
        loadPendingStats();
        loadArchivedSessions();
        loadRecentDiaries();
        loadNodes(rootEl.querySelector('#node-type-filter').value);
    },
};

// ===== 待处理会话 =====

function fmtSessionTime(session) {
    const start = new Date(session.start_time);
    const end = new Date(session.end_time);
    const timeOpts = { hour: '2-digit', minute: '2-digit' };
    return {
        date: start.toLocaleDateString('zh-CN'),
        range: `${start.toLocaleTimeString('zh-CN', timeOpts)} ~ ${end.toLocaleTimeString('zh-CN', timeOpts)}`,
    };
}

function topicsLine(session) {
    const topics = (session.topics || []).slice(0, 3).map((t) => escapeHtml(t)).join('、');
    const more = (session.topics || []).length > 3 ? ` +${session.topics.length - 3}` : '';
    return topics + more;
}

async function loadPendingStats() {
    const container = rootEl.querySelector('#pending-stats');
    container.innerHTML = spinnerHtml();

    // 配置回填
    const configData = await apiCall('/pending/config');
    if (configData && !configData.error) {
        if (configData.sleep_gap_hours) rootEl.querySelector('#sleep-gap-hours').value = configData.sleep_gap_hours;
        rootEl.querySelector('#pending-consolidate-prompt').value = configData.consolidate_prompt || '';
        rootEl.querySelector('#pending-merge-prompt').value = configData.merge_prompt || '';
        rootEl.querySelector('#pending-tools-prompt').value = configData.consolidate_with_tools_prompt || '';
    }

    const data = await apiCall('/pending/sessions?ready_only=false');
    if (!data || data.error) {
        container.innerHTML = `<p style="color: var(--danger);">加载失败: ${escapeHtml(data?.error || '未知错误')}</p>`;
        return;
    }
    if (!data.sessions || data.sessions.length === 0) {
        container.innerHTML = '<p style="color: var(--success);">✅ 没有待处理的会话</p>';
        return;
    }

    let html = `
        <div style="display: flex; gap: 20px; margin-bottom: 15px;">
            <div style="background: var(--surface-2); padding: 10px 15px; border-radius: 8px;">
                <span class="text-dim">总会话：</span><strong style="color: var(--accent);">${data.total}</strong>
            </div>
            <div style="background: var(--surface-2); padding: 10px 15px; border-radius: 8px;">
                <span class="text-dim">可汇总：</span><strong style="color: var(--success);">${data.ready_count}</strong>
            </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 15px;">`;

    for (const session of data.sessions) {
        const isReady = session.is_ready;
        const t = fmtSessionTime(session);
        const sid = escapeAttr(session.session_id);
        html += `
            <div style="background: var(--surface-2); padding: 15px; border-radius: 8px; border-left: 3px solid ${isReady ? 'var(--success)' : 'var(--accent)'};">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <span style="font-weight: 600; color: var(--accent);">🕐 ${escapeHtml(t.date)}</span>
                    ${isReady ? '<span class="badge badge-success">可汇总</span>' : '<span class="badge badge-info">进行中</span>'}
                </div>
                <div class="text-dim" style="font-size: 0.85rem; margin-bottom: 8px;">
                    ${escapeHtml(t.range)} | ${session.duration_minutes} 分钟 | ${session.summary_count} 条摘要
                </div>
                <div class="text-dim" style="font-size: 0.8rem; margin-bottom: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    📝 ${topicsLine(session)}
                </div>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    ${isReady ? `<button class="btn btn-sm btn-success" data-action="consolidate-session" data-id="${sid}" title="使用 LLM 整理成流畅日记">🤖 汇总</button>` : ''}
                    ${isReady ? `<button class="btn btn-sm btn-primary" data-action="consolidate-options" data-id="${sid}" title="汇总并提取节点">🔧 汇总+节点</button>` : ''}
                    ${isReady ? `<button class="btn btn-sm btn-warning" data-action="direct-convert" data-id="${sid}" title="直接转换摘要，不经过 LLM">⚡ 直接转换</button>` : ''}
                    <button class="btn btn-sm" data-action="view-session" data-id="${sid}">查看</button>
                </div>
            </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

async function saveSleepGap() {
    const sleepGap = parseFloat(rootEl.querySelector('#sleep-gap-hours').value);
    const result = await apiCall('/pending/config', 'POST', { sleep_gap_hours: sleepGap });
    if (result && result.success) {
        showToast('睡眠间隔配置已保存', 'success');
        loadPendingStats();
    } else {
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

async function savePendingPrompts() {
    const result = await apiCall('/pending/config', 'POST', {
        consolidate_prompt: rootEl.querySelector('#pending-consolidate-prompt').value,
        merge_prompt: rootEl.querySelector('#pending-merge-prompt').value,
        consolidate_with_tools_prompt: rootEl.querySelector('#pending-tools-prompt').value,
    });
    if (result && result.success) {
        showToast('汇总提示词已保存', 'success');
    } else {
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

async function consolidateSession(sessionId) {
    const ok = await confirmDialog(`确定要将会话 ${sessionId} 汇总成日记吗？`, { okText: '汇总' });
    if (!ok) return;
    showToast('正在汇总...', 'info');
    const result = await apiCall('/pending/consolidate', 'POST', { session_id: sessionId });
    if (result && result.success) {
        showToast(result.message || '汇总完成', 'success');
        loadPendingStats();
        loadRecentDiaries();
    } else {
        showToast(result?.message || result?.error || '汇总失败', 'error');
    }
}

function showConsolidateOptions(sessionId) {
    const modal = showModal('🔧 选择汇总模式', `
        <p class="text-dim" style="margin-bottom: 16px;">会话 ${escapeHtml(sessionId)}</p>
        <div style="display: flex; flex-direction: column; gap: 12px;">
            <button class="btn btn-success" data-mode="both" style="padding: 14px; text-align: left; display: block;">
                <strong>📝 日记 + 🔧 节点</strong><br>
                <span style="font-size: 0.85rem; opacity: 0.8;">生成日记的同时提取/更新知识节点</span>
            </button>
            <button class="btn" data-mode="diary_only" style="padding: 14px; text-align: left; display: block;">
                <strong>📝 仅日记</strong><br>
                <span style="font-size: 0.85rem; opacity: 0.8;">只生成日记，不处理节点（和普通汇总一样）</span>
            </button>
            <button class="btn" data-mode="nodes_only" style="padding: 14px; text-align: left; display: block;">
                <strong>🔧 仅节点</strong><br>
                <span style="font-size: 0.85rem; opacity: 0.8;">只提取/更新节点，不生成日记（会话不会归档）</span>
            </button>
        </div>`);
    modal.querySelectorAll('[data-mode]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const mode = btn.dataset.mode;
            closeModal();
            consolidateWithTools(sessionId, mode);
        });
    });
}

async function consolidateWithTools(sessionId, mode) {
    const modeNames = { both: '日记+节点', diary_only: '仅日记', nodes_only: '仅节点' };
    showToast(`正在执行${modeNames[mode]}汇总...可能需要较长时间`, 'info', 6000);
    const result = await apiCall('/pending/consolidate-with-tools', 'POST', { session_id: sessionId, mode });
    if (result && result.success) {
        let message = result.message || '汇总完成';
        if (result.tool_calls && result.tool_calls.length > 0) {
            message += `（工具调用: ${result.tool_calls.map((tc) => tc.name).join(', ')}）`;
        }
        showToast(message, 'success', 6000);
        loadPendingStats();
        loadRecentDiaries();
    } else {
        showToast(result?.message || result?.error || '汇总失败', 'error');
    }
}

async function directConvert(sessionId) {
    const ok = await confirmDialog(
        `确定要直接转换会话 ${sessionId} 吗？\n\n⚡ 直接转换会保留摘要原文，不经过 LLM 润色，适合摘要质量已经很好的情况。`,
        { okText: '直接转换' }
    );
    if (!ok) return;
    showToast('正在直接转换...', 'info');
    const result = await apiCall('/pending/direct-convert', 'POST', { session_id: sessionId });
    if (result && result.success) {
        showToast(result.message || '转换完成', 'success');
        loadPendingStats();
        loadRecentDiaries();
    } else {
        showToast(result?.message || result?.error || '转换失败', 'error');
    }
}

async function consolidateAll() {
    const ok = await confirmDialog(
        '确定要智能汇总所有已结束的会话吗？\n\n系统会自动识别"睡眠间隔"，每个清醒周期生成独立日记。',
        { okText: '开始汇总' }
    );
    if (!ok) return;
    showToast('正在智能汇总...可能需要一些时间', 'info', 6000);
    const result = await apiCall('/pending/consolidate-all', 'POST', {});
    if (result && result.success) {
        showToast(result.message || '汇总完成', 'success');
        loadPendingStats();
        loadRecentDiaries();
    } else {
        showToast(result?.message || result?.error || '汇总失败', 'error');
    }
}

function summariesHtml(summaries, borderColor = 'var(--accent)') {
    if (!summaries || summaries.length === 0) return emptyHtml('无摘要');
    return summaries.map((s) => `
        <div style="background: var(--surface-2); padding: 12px; margin-bottom: 10px; border-radius: 6px; border-left: 3px solid ${borderColor};">
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                <span style="font-weight: 600;">${escapeHtml((s.timestamp || '').substring(11, 16))} - ${escapeHtml(s.topic || '')}</span>
                <span class="text-dim" style="font-size: 0.8rem;">${s.raw_turns || 0} 轮对话</span>
            </div>
            <p class="text-dim" style="margin: 0; font-size: 0.9rem;">${escapeHtml(s.summary || '')}</p>
            ${s.tool_calls && s.tool_calls.length > 0 ? `<div style="margin-top: 8px; font-size: 0.75rem; color: var(--accent);">🔧 ${s.tool_calls.map((t) => escapeHtml(t)).join(', ')}</div>` : ''}
        </div>`).join('');
}

async function viewSession(sessionId) {
    const data = await apiCall(`/pending?session_id=${encodeURIComponent(sessionId)}`);
    if (!data || data.error) {
        showToast('加载失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }
    const start = new Date(data.start_time);
    const end = new Date(data.end_time);
    showModal(`🕐 会话 ${escapeHtml(sessionId)}`, `
        <p class="text-dim" style="margin-bottom: 15px;">
            ${start.toLocaleString('zh-CN')} ~ ${end.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} · 共 ${data.count} 条摘要
        </p>
        ${summariesHtml(data.summaries)}`, { size: 'large' });
}

// ===== 已归档会话 =====

async function loadArchivedSessions() {
    const container = rootEl.querySelector('#archived-sessions');
    container.innerHTML = spinnerHtml();
    const data = await apiCall('/pending/archived');
    if (!data || data.error) {
        container.innerHTML = `<p style="color: var(--danger);">加载失败: ${escapeHtml(data?.error || '未知错误')}</p>`;
        return;
    }
    if (!data.sessions || data.sessions.length === 0) {
        container.innerHTML = emptyHtml('没有已归档的会话');
        return;
    }
    let html = `<p class="text-dim" style="margin-bottom: 15px;">共 ${data.total} 个已归档会话</p>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 15px;">`;
    for (const session of data.sessions) {
        const t = fmtSessionTime(session);
        const sid = escapeAttr(session.session_id);
        html += `
            <div style="background: var(--surface-2); padding: 15px; border-radius: 8px; border-left: 3px solid var(--text-dim); opacity: 0.85;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <span class="text-dim" style="font-weight: 600;">📦 ${escapeHtml(t.date)}</span>
                    <span class="badge" style="background: var(--surface); color: var(--text-dim);">已归档</span>
                </div>
                <div class="text-dim" style="font-size: 0.85rem; margin-bottom: 8px;">
                    ${escapeHtml(t.range)} | ${session.duration_minutes} 分钟 | ${session.summary_count} 条摘要
                </div>
                <div class="text-dim" style="font-size: 0.8rem; margin-bottom: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    📝 ${topicsLine(session)}
                </div>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-sm btn-warning" data-action="restore-session" data-id="${sid}">🔄 恢复</button>
                    <button class="btn btn-sm" data-action="view-archived" data-id="${sid}">查看</button>
                </div>
            </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

async function restoreSession(sessionId) {
    const ok = await confirmDialog(`确定要将会话 ${sessionId} 恢复到待处理列表吗？\n恢复后可以重新汇总。`, { okText: '恢复' });
    if (!ok) return;
    const result = await apiCall(`/pending/restore/${encodeURIComponent(sessionId)}`, 'POST');
    if (result && result.success) {
        showToast(result.message || '会话已恢复', 'success');
        loadArchivedSessions();
        loadPendingStats();
    } else {
        showToast(result?.message || result?.error || '恢复失败', 'error');
    }
}

async function viewArchivedSession(sessionId) {
    const data = await apiCall(`/pending/archived/${encodeURIComponent(sessionId)}`);
    if (!data || data.error) {
        showToast('加载失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }
    const start = new Date(data.start_time);
    const end = new Date(data.end_time);
    showModal(`📦 已归档会话 ${escapeHtml(sessionId)}`, `
        <p class="text-dim" style="margin-bottom: 15px;">
            ${start.toLocaleString('zh-CN')} ~ ${end.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} · 共 ${data.count} 条摘要
        </p>
        ${summariesHtml(data.summaries, 'var(--text-dim)')}`, { size: 'large' });
}

// ===== 日记 =====

async function loadRecentDiaries() {
    const container = rootEl.querySelector('#recent-diaries');
    container.innerHTML = spinnerHtml();
    const data = await apiCall('/diaries?limit=10');
    if (data && data.diaries && data.diaries.length > 0) {
        let html = '<table class="table"><thead><tr><th>日期</th><th>标题</th><th>标签</th><th>操作</th></tr></thead><tbody>';
        for (const d of data.diaries) {
            const tags = (d.tags || []).map((t) => `<span class="badge badge-info">#${escapeHtml(t)}</span>`).join(' ');
            html += `<tr>
                <td>${escapeHtml(d.date)}</td>
                <td>${escapeHtml(d.title) || '-'}</td>
                <td>${tags || '-'}</td>
                <td><button class="btn btn-sm btn-primary" data-action="view-diary" data-date="${escapeAttr(d.date)}">📖 查看</button></td>
            </tr>`;
        }
        html += '</tbody></table>';
        container.innerHTML = html;
    } else {
        container.innerHTML = emptyHtml('暂无日记');
    }
}

async function viewDiary(date) {
    const data = await apiCall(`/diary/${encodeURIComponent(date)}`);
    if (!data || data.error) {
        showToast('加载日记失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }
    const tags = (data.tags || []).map((t) => `<span class="badge badge-info">#${escapeHtml(t)}</span>`).join(' ') || '无';
    const links = (data.links || []).map((l) => `<span class="badge">${escapeHtml(l)}</span>`).join(' ') || '无';
    showModal('📅 日记详情', `
        <div style="margin-bottom: 15px; line-height: 2;">
            <strong>📅 日期：</strong>${escapeHtml(data.date)}<br>
            <strong>📝 标题：</strong>${escapeHtml(data.title) || '无标题'}<br>
            <strong>🏷️ 标签：</strong>${tags}<br>
            <strong>🔗 链接：</strong>${links}
        </div>
        <div style="background: var(--surface-2); padding: 15px; border-radius: 8px; max-height: 420px; overflow-y: auto; white-space: pre-wrap; font-family: monospace; font-size: 0.88rem;">${escapeHtml(data.content)}</div>`,
        { size: 'large' });
}

// ===== 节点管理 =====

async function loadNodes(type = '') {
    const container = rootEl.querySelector('#nodes-list');
    container.innerHTML = spinnerHtml();
    const url = type ? `/nodes?type=${encodeURIComponent(type)}` : '/nodes';
    const data = await apiCall(url);
    if (data && data.nodes && data.nodes.length > 0) {
        let html = '<table class="table"><thead><tr><th>类型</th><th>名称</th><th>标签</th><th>操作</th></tr></thead><tbody>';
        for (const n of data.nodes) {
            const icon = NODE_TYPE_ICONS[n.type] || '📌';
            const tags = (n.tags || []).slice(0, 3).map((t) => `<span class="badge badge-info">#${escapeHtml(t)}</span>`).join(' ');
            html += `<tr>
                <td>${icon} ${escapeHtml(n.type)}</td>
                <td>${escapeHtml(n.name)}</td>
                <td>${tags || '-'}</td>
                <td style="white-space: nowrap;">
                    <button class="btn btn-sm btn-primary" data-action="view-node" data-name="${escapeAttr(n.name)}">📖 查看</button>
                    <button class="btn btn-sm" data-action="edit-node" data-name="${escapeAttr(n.name)}">✏️ 编辑</button>
                </td>
            </tr>`;
        }
        html += '</tbody></table>';
        container.innerHTML = html;
    } else {
        container.innerHTML = emptyHtml('暂无节点');
    }
}

async function viewNode(name) {
    const data = await apiCall(`/node/${encodeURIComponent(name)}`);
    if (!data || data.error) {
        showToast('加载节点失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }
    const icon = NODE_TYPE_ICONS[data.type] || '📌';
    const tags = (data.tags || []).map((t) => `<span class="badge badge-info">#${escapeHtml(t)}</span>`).join(' ') || '无';
    const links = (data.links || []).map((l) => `<span class="badge">${escapeHtml(l)}</span>`).join(' ') || '无';
    const modal = showModal('📦 节点详情', `
        <div style="margin-bottom: 15px; line-height: 2;">
            <strong>${icon} 类型：</strong>${escapeHtml(data.type)}<br>
            <strong>📝 名称：</strong>${escapeHtml(data.name)}<br>
            <strong>🏷️ 标签：</strong>${tags}<br>
            <strong>🔗 链接：</strong>${links}
        </div>
        <div style="background: var(--surface-2); padding: 15px; border-radius: 8px; max-height: 420px; overflow-y: auto; white-space: pre-wrap; font-family: monospace; font-size: 0.88rem;">${escapeHtml(data.content)}</div>`,
        {
            size: 'large',
            footer: '<button class="btn btn-primary" data-act="edit">✏️ 编辑此节点</button>',
        });
    modal.querySelector('[data-act="edit"]').addEventListener('click', () => {
        closeModal();
        editNode(data.name);
    });
}

async function editNode(name) {
    const data = await apiCall(`/node/${encodeURIComponent(name)}`);
    if (!data || data.error) {
        showToast('加载节点失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }
    const icon = NODE_TYPE_ICONS[data.type] || '📌';
    const modal = showModal('✏️ 编辑节点', `
        <div style="margin-bottom: 15px;"><strong>${icon} ${escapeHtml(data.type)} - ${escapeHtml(data.name)}</strong></div>
        <div class="form-group">
            <label class="form-label">标签（逗号分隔）</label>
            <input type="text" id="edit-node-tags" class="form-input" value="${escapeAttr((data.tags || []).join(', '))}">
        </div>
        <div class="form-group">
            <label class="form-label">内容</label>
            <textarea id="edit-node-content" class="form-input" style="min-height: 300px; font-family: monospace;">${escapeHtml(data.content)}</textarea>
        </div>`,
        {
            size: 'large',
            footer: `<button class="btn" data-modal-close>取消</button>
                     <button class="btn btn-success" data-act="save">💾 保存</button>`,
        });
    modal.querySelector('[data-act="save"]').addEventListener('click', async () => {
        const content = modal.querySelector('#edit-node-content').value;
        const tags = modal.querySelector('#edit-node-tags').value.split(',').map((t) => t.trim()).filter(Boolean);
        const result = await apiCall(`/node/${encodeURIComponent(name)}`, 'PUT', { content, tags });
        if (result && result.success) {
            showToast('节点保存成功', 'success');
            closeModal();
            loadNodes(rootEl.querySelector('#node-type-filter').value);
        } else {
            showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
        }
    });
}

function showCreateNodeDialog() {
    const modal = showModal('✨ 创建新节点', `
        <div class="form-row cols-2">
            <div class="form-group">
                <label class="form-label">节点类型</label>
                <select id="new-node-type" class="form-select">
                    <option value="人物">👤 人物</option>
                    <option value="地点">📍 地点</option>
                    <option value="事物">📦 事物</option>
                    <option value="概念">💡 概念</option>
                    <option value="事件">📅 事件</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label">节点名称</label>
                <input type="text" id="new-node-name" class="form-input" placeholder="输入节点名称">
            </div>
        </div>
        <div class="form-group">
            <label class="form-label">标签（逗号分隔）</label>
            <input type="text" id="new-node-tags" class="form-input" placeholder="标签1, 标签2">
        </div>
        <div class="form-group">
            <label class="form-label">内容</label>
            <textarea id="new-node-content" class="form-input" style="min-height: 200px; font-family: monospace;" placeholder="节点内容..."></textarea>
        </div>`,
        {
            size: 'large',
            footer: `<button class="btn" data-modal-close>取消</button>
                     <button class="btn btn-success" data-act="create">✨ 创建</button>`,
        });
    modal.querySelector('[data-act="create"]').addEventListener('click', async () => {
        const name = modal.querySelector('#new-node-name').value.trim();
        if (!name) {
            showToast('请输入节点名称', 'error');
            return;
        }
        const result = await apiCall('/node', 'POST', {
            name,
            type: modal.querySelector('#new-node-type').value,
            content: modal.querySelector('#new-node-content').value,
            tags: modal.querySelector('#new-node-tags').value.split(',').map((t) => t.trim()).filter(Boolean),
        });
        if (result && result.success) {
            showToast('节点创建成功', 'success');
            closeModal();
            loadNodes(rootEl.querySelector('#node-type-filter').value);
        } else {
            showToast('创建失败: ' + (result?.error || '未知错误'), 'error');
        }
    });
}

// ===== 搜索 / 索引 =====

async function searchMemories() {
    const query = rootEl.querySelector('#memory-search-query').value.trim();
    if (!query) return;
    const container = rootEl.querySelector('#memory-search-results');
    container.innerHTML = spinnerHtml('搜索中...');
    const data = await apiCall('/search', 'POST', { query });
    if (data && data.results && data.results.length > 0) {
        container.innerHTML = data.results.map((r) => `
            <div style="padding: 10px; border-bottom: 1px solid var(--line-weak);">
                <strong>${escapeHtml(r.file)}</strong> <span class="badge badge-info">${escapeHtml(r.type)}</span>
                <p class="text-dim" style="margin-top: 5px;">${escapeHtml(r.snippet || '')}</p>
            </div>`).join('');
    } else {
        container.innerHTML = emptyHtml('未找到结果');
    }
}

async function rebuildIndex() {
    const statusEl = rootEl.querySelector('#index-status');
    statusEl.innerHTML = '<span class="spinner"></span> 重建中...';
    const data = await apiCall('/rebuild-index', 'POST');
    if (data && data.success) {
        statusEl.innerHTML = '<span style="color: var(--success);">✅ 索引重建完成</span>';
        showToast('索引重建完成', 'success');
    } else {
        statusEl.innerHTML = '<span style="color: var(--danger);">❌ 重建失败</span>';
        showToast('索引重建失败: ' + (data?.error || '未知错误'), 'error');
    }
}

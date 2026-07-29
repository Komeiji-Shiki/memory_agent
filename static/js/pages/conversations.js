/**
 * 对话管理页
 * - 统计卡 / 有记录的日期列表（快速总结、导出）
 * - 对话列表（天数筛选、分页、详情弹窗）
 * - 单对话与全天总结为日记（预览/确认两段式）、逐会话批量总结
 * - 图片灯箱、导出 Markdown、总结提示词配置
 * 修复：天数筛选双重绑定（旧 HTML onchange 调用了 graphiti 的坏函数）；
 *      temperature 保存时 parseFloat NaN 未兜底的问题。
 */

import { API_BASE, apiCall } from '../core/api.js';
import {
    showToast, showModal, closeModal, confirmDialog,
    escapeHtml, escapeAttr, spinnerHtml, emptyHtml, errorHtml,
    bindActions, downloadText,
} from '../core/ui.js';
import { markDirty, clearDirty, isDirty } from '../core/store.js';

let rootEl = null;
let currentPage = 0;
let listLoaded = false;   // 首次进入自动加载一次，之后保留用户的翻页/过滤状态
const PAGE_SIZE = 20;
const DIRTY_KEY = 'convdiary-config';

export const conversationsPage = {
    id: 'conversations',
    title: '对话管理',
    icon: '💬',
    group: 'memory',

    render(container) {
        rootEl = container;
        const today = new Date().toISOString().split('T')[0];

        container.innerHTML = `
            <div class="page-header">
                <h2>💬 对话管理</h2>
                <p>原始对话记录的浏览、总结与导出</p>
            </div>

            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-card-label">💬 总会话数</div>
                    <div class="stat-card-value" id="conv-stat-total">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label">🔄 总轮次</div>
                    <div class="stat-card-value" id="conv-stat-total-turns">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label">📅 今日会话</div>
                    <div class="stat-card-value" id="conv-stat-today">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label">📝 今日轮次</div>
                    <div class="stat-card-value" id="conv-stat-today-turns">--</div>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>📅 有记录的日期</h3>
                    <button class="btn btn-sm" data-action="refresh-dates">🔄 刷新</button>
                </div>
                <div id="conv-dates-list" style="display: flex; flex-wrap: wrap; gap: 8px;">${spinnerHtml()}</div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>💬 对话列表</h3>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <select id="conv-days-filter" class="form-select" style="width: auto;">
                            <option value="7">最近 7 天</option>
                            <option value="30" selected>最近 30 天</option>
                            <option value="90">最近 90 天</option>
                            <option value="365">最近一年</option>
                        </select>
                        <button class="btn btn-sm btn-primary" data-action="refresh-list">🔄 刷新</button>
                    </div>
                </div>
                <div id="day-timeline-entry" style="display: none; margin-bottom: 12px;">
                    <button class="btn btn-primary" data-action="show-timeline">📜 查看全天时间线 <span id="day-timeline-date"></span></button>
                </div>
                <div id="conv-list">${spinnerHtml()}</div>
                <div id="conv-pagination" style="display: flex; gap: 10px; align-items: center; justify-content: center; margin-top: 12px;"></div>
            </div>

            <div class="card">
                <div class="card-header"><h3>📝 按天总结为日记</h3></div>
                <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
                    <input type="date" id="conv-batch-date" class="form-input" value="${today}" style="width: auto;">
                    <label class="checkbox-label"><input type="checkbox" id="conv-day-append" checked>追加模式（保留已有日记内容）</label>
                    <button class="btn btn-primary" data-action="preview-day">👁️ 预览总结</button>
                    <button class="btn btn-success" data-action="summarize-day">📝 直接总结保存</button>
                    <button class="btn" data-action="batch-summarize" title="将该日每个会话分别总结后写入日记">📚 逐会话总结</button>
                </div>
                <div id="conv-batch-status" class="text-dim" style="margin-top: 10px;"></div>
                <div id="conv-day-preview" style="display: none; margin-top: 15px; padding: 15px; background: var(--surface-2); border-radius: 8px;">
                    <div id="conv-day-preview-stats" class="text-dim" style="margin-bottom: 10px; font-size: 0.85rem;"></div>
                    <div id="conv-day-preview-content" style="white-space: pre-wrap; line-height: 1.7; font-size: 0.9rem; max-height: 400px; overflow-y: auto;"></div>
                    <div style="margin-top: 12px; display: flex; gap: 10px;">
                        <button class="btn btn-success" data-action="confirm-day">✅ 确认保存</button>
                        <button class="btn" data-action="close-day-preview">关闭预览</button>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>⚙️ 总结提示词配置</h3></div>
                <div id="convdiary-config-form">
                    <div class="form-row cols-3">
                        <div class="form-group">
                            <label for="cfg-convdiary-model">总结模型（留空使用默认）</label>
                            <input type="text" id="cfg-convdiary-model" placeholder="留空使用系统默认">
                        </div>
                        <div class="form-group">
                            <label for="cfg-convdiary-base-url">API URL（留空使用默认）</label>
                            <input type="text" id="cfg-convdiary-base-url" placeholder="留空使用系统默认">
                        </div>
                        <div class="form-group">
                            <label for="cfg-convdiary-api-key">API Key（留空使用默认）</label>
                            <input type="password" id="cfg-convdiary-api-key" placeholder="留空使用系统默认" autocomplete="new-password">
                        </div>
                    </div>
                    <div class="form-row cols-3">
                        <div class="form-group">
                            <label for="cfg-convdiary-max-tokens">最大 Tokens</label>
                            <input type="number" id="cfg-convdiary-max-tokens" min="256" step="256" value="65535">
                        </div>
                        <div class="form-group">
                            <label for="cfg-convdiary-temperature">Temperature</label>
                            <input type="number" id="cfg-convdiary-temperature" min="0" max="2" step="0.1" value="1">
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="cfg-convdiary-single-prompt">单对话总结提示词</label>
                        <textarea id="cfg-convdiary-single-prompt" rows="5"></textarea>
                    </div>
                    <div class="form-group">
                        <label for="cfg-convdiary-day-prompt">全天总结提示词</label>
                        <textarea id="cfg-convdiary-day-prompt" rows="5"></textarea>
                    </div>
                </div>
                <button class="btn btn-success" data-action="save-diary-config">💾 保存配置</button>
            </div>
        `;

        bindActions(container, {
            'refresh-dates': loadDates,
            'refresh-list': () => { currentPage = 0; loadList(); },
            'show-timeline': showDayTimeline,
            'filter-date': (t) => filterByDate(t.dataset.date),
            'quick-summarize-day': (t) => quickSummarizeDay(t.dataset.date),
            'export-day': (t) => exportDayTimeline(t.dataset.date),
            'open-detail': (t) => showConversationDetail(t.dataset.id),
            'summarize-conv': (t) => summarizeConversation(t.dataset.id),
            'delete-conv': (t) => deleteConversation(t.dataset.id),
            'goto-page': (t) => { currentPage = parseInt(t.dataset.page); loadList(); },
            'preview-day': previewDaySummary,
            'summarize-day': summarizeDayToDiary,
            'batch-summarize': batchSummarize,
            'confirm-day': confirmDaySummary,
            'close-day-preview': closeDayPreview,
            'save-diary-config': saveDiaryConfig,
            'open-image': (t) => openImageLightbox(t.dataset.src),
        });

        // 天数筛选：单一绑定（修复旧版双重绑定 bug）
        container.querySelector('#conv-days-filter').addEventListener('change', () => {
            currentPage = 0;
            loadList();
        });

        const configForm = container.querySelector('#convdiary-config-form');
        configForm.addEventListener('input', () => markDirty(DIRTY_KEY, '对话总结配置'));
        configForm.addEventListener('change', () => markDirty(DIRTY_KEY, '对话总结配置'));
    },

    onEnter() {
        loadStats();
        loadDates();
        if (!listLoaded) loadList();
        if (!isDirty(DIRTY_KEY)) {
            loadDiaryConfig();
        }
    },
};

function imageUrl(imgPath) {
    return `${API_BASE}/conversations/image/${imgPath}`;
}

// ===== 统计 =====

async function loadStats() {
    const data = await apiCall('/conversations/stats');
    if (!data || data.error) return;

    rootEl.querySelector('#conv-stat-total').textContent = data.total_conversations || 0;
    rootEl.querySelector('#conv-stat-total-turns').textContent = data.total_turns || 0;
    if (data.today) {
        rootEl.querySelector('#conv-stat-today').textContent = data.today.conversations || 0;
        rootEl.querySelector('#conv-stat-today-turns').textContent = data.today.turns || 0;
    }
}

// ===== 日期列表 =====

async function loadDates() {
    const container = rootEl.querySelector('#conv-dates-list');
    container.innerHTML = spinnerHtml();

    const data = await apiCall('/conversations/dates');
    if (!data || data.error) {
        container.innerHTML = errorHtml('加载失败: ' + (data?.error || '未知错误'));
        return;
    }
    if (!data.dates || data.dates.length === 0) {
        container.innerHTML = emptyHtml('暂无对话记录');
        return;
    }

    container.innerHTML = data.dates.slice(0, 30).map((d) => {
        const dateAttr = escapeAttr(d.date);
        return `
        <div style="display: inline-flex; align-items: stretch; gap: 2px;">
            <button class="btn btn-sm" data-action="filter-date" data-date="${dateAttr}"
                    style="display: flex; flex-direction: column; align-items: center; min-width: 70px; border-radius: 6px 0 0 6px;">
                <span style="font-weight: 600;">${escapeHtml(d.date.slice(5))}</span>
                <span style="font-size: 0.7rem;" class="text-dim">${d.count}个 / ${d.total_turns}轮</span>
            </button>
            <button class="btn btn-sm btn-success" data-action="quick-summarize-day" data-date="${dateAttr}"
                    title="将 ${dateAttr} 的对话总结为日记" style="padding: 4px 6px; border-radius: 0; font-size: 0.75rem;">📝</button>
            <button class="btn btn-sm" data-action="export-day" data-date="${dateAttr}"
                    title="导出 ${dateAttr} 的对话为 Markdown" style="padding: 4px 6px; border-radius: 0 6px 6px 0; font-size: 0.75rem;">📄</button>
        </div>`;
    }).join('');
}

function filterByDate(date) {
    rootEl.querySelector('#conv-batch-date').value = date;
    loadList(date);
}

// ===== 对话列表 =====

async function loadList(dateFilter = null) {
    listLoaded = true;
    const container = rootEl.querySelector('#conv-list');
    const timelineEntry = rootEl.querySelector('#day-timeline-entry');
    container.innerHTML = spinnerHtml();

    // 按日期过滤时显示全天时间线入口
    timelineEntry.style.display = dateFilter ? 'block' : 'none';
    if (dateFilter) {
        timelineEntry.dataset.date = dateFilter;
        rootEl.querySelector('#day-timeline-date').textContent = `(${dateFilter})`;
    }

    const days = rootEl.querySelector('#conv-days-filter').value || 30;
    const endpoint = dateFilter
        ? `/conversations?date=${encodeURIComponent(dateFilter)}&limit=100`
        : `/conversations?days=${days}&limit=${PAGE_SIZE}&offset=${currentPage * PAGE_SIZE}`;

    const data = await apiCall(endpoint);
    if (!data || data.error) {
        container.innerHTML = errorHtml('加载失败: ' + (data?.error || '未知错误'));
        return;
    }
    if (!data.conversations || data.conversations.length === 0) {
        container.innerHTML = emptyHtml('暂无对话记录');
        renderPagination(0, 0);
        return;
    }

    container.innerHTML = data.conversations.map(renderConversationItem).join('');
    renderPagination(dateFilter ? 0 : data.total, dateFilter ? 0 : data.offset);
}

function renderConversationItem(conv) {
    const startTime = conv.start_time ? new Date(conv.start_time).toLocaleString('zh-CN') : '--';
    const firstMsg = conv.first_message?.user || '无内容';
    const idAttr = escapeAttr(conv.session_id);

    return `
    <div class="list-item" data-action="open-detail" data-id="${idAttr}" style="cursor: pointer;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div>
                <span class="badge badge-info">${conv.turn_count}轮</span>
                <span style="margin-left: 10px; font-weight: 500;">${escapeHtml(conv.date || conv.session_id.split('_')[0])}</span>
            </div>
            <div style="display: flex; gap: 8px;">
                <button class="btn btn-sm btn-success" data-action="summarize-conv" data-id="${idAttr}">📝 总结</button>
                <button class="btn btn-sm btn-danger" data-action="delete-conv" data-id="${idAttr}">🗑️</button>
            </div>
        </div>
        <div class="text-dim" style="display: flex; gap: 15px; font-size: 0.82rem; margin-bottom: 6px; flex-wrap: wrap;">
            <span>🕐 ${escapeHtml(startTime)}</span>
            <span>🤖 ${escapeHtml(conv.model || '未知')}</span>
            <span>🔑 ${escapeHtml(conv.fingerprint || '--')}</span>
        </div>
        <div style="font-size: 0.88rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(firstMsg)}</div>
    </div>`;
}

function renderPagination(total, offset) {
    const container = rootEl.querySelector('#conv-pagination');
    const totalPages = Math.ceil(total / PAGE_SIZE);
    const page = Math.floor(offset / PAGE_SIZE);

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    let html = '';
    if (page > 0) {
        html += `<button class="btn btn-sm" data-action="goto-page" data-page="${page - 1}">◀ 上一页</button>`;
    }
    html += `<span class="text-dim">第 ${page + 1} / ${totalPages} 页</span>`;
    if (page < totalPages - 1) {
        html += `<button class="btn btn-sm" data-action="goto-page" data-page="${page + 1}">下一页 ▶</button>`;
    }
    container.innerHTML = html;
}

// ===== 轮次渲染（详情与时间线共用） =====

function renderImages(images, small = false) {
    if (!images || images.length === 0) return '';
    const size = small
        ? 'max-width: 70px; max-height: 50px;'
        : 'max-width: 100px; max-height: 70px;';
    return `
    <div style="margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px;">
        ${images.map((imgPath) => `
            <img src="${escapeAttr(imageUrl(imgPath))}" alt="对话图片"
                 data-action="open-image" data-src="${escapeAttr(imageUrl(imgPath))}"
                 style="${size} border-radius: 6px; border: 1px solid var(--line-weak); cursor: pointer; object-fit: cover;"
                 onerror="this.style.display='none';">
        `).join('')}
    </div>`;
}

function renderThinking(turn, compact = false) {
    const reasoning = turn.metadata?.reasoning_content;
    if (!reasoning) return '';
    const maxH = compact ? 120 : 180;
    return `
    <div style="margin-bottom: 10px; padding: 8px 10px; background: rgba(120, 100, 60, 0.15); border-radius: 6px; border-left: 3px solid #a08050;">
        <div style="display: flex; align-items: center; gap: 5px; margin-bottom: 5px; font-size: 0.8rem;">
            <span>💭</span><strong style="color: #b89860;">思考过程</strong>
        </div>
        <div style="padding: 6px 8px; background: rgba(0,0,0,0.2); border-radius: 4px; white-space: pre-wrap; max-height: ${maxH}px; overflow-y: auto; font-size: 0.8rem; line-height: 1.5; opacity: 0.75;">${escapeHtml(reasoning)}</div>
    </div>`;
}

function renderTurnBlock(turn, opts = {}) {
    const header = opts.headerHtml || '';
    return `
    <div style="margin-bottom: 16px; padding: 12px; background: var(--surface-2); border-radius: 8px;">
        ${header}
        <div style="margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 4px; margin-bottom: 5px; font-size: 0.82rem;">
                <span>👤</span><strong style="color: #7090a0;">用户</strong>
            </div>
            <div style="padding: 8px 10px; background: rgba(70, 100, 120, 0.25); border-radius: 6px; border-left: 2px solid #5080a0; white-space: pre-wrap; max-height: 250px; overflow-y: auto; font-size: 0.88rem; line-height: 1.6;">${escapeHtml(turn.user)}</div>
            ${renderImages(turn.images, opts.compact)}
        </div>
        ${renderThinking(turn, opts.compact)}
        <div>
            <div style="display: flex; align-items: center; gap: 4px; margin-bottom: 5px; margin-left: 15px; font-size: 0.82rem;">
                <span>🤖</span><strong style="color: #70a070;">助手</strong>
            </div>
            <div style="margin-left: 15px; padding: 8px 10px; background: rgba(80, 100, 80, 0.2); border-radius: 6px; border-left: 2px solid #608060; white-space: pre-wrap; max-height: 300px; overflow-y: auto; font-size: 0.88rem; line-height: 1.6;">${escapeHtml(turn.assistant)}</div>
        </div>
    </div>`;
}

// ===== 对话详情 =====

async function showConversationDetail(sessionId) {
    const data = await apiCall(`/conversation/${encodeURIComponent(sessionId)}`);
    if (!data || data.error) {
        showToast('加载对话详情失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }

    const turnsHtml = data.turns.map((turn) => renderTurnBlock(turn, {
        headerHtml: `
        <div style="display: flex; justify-content: space-between; margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--line-weak);">
            <span class="badge badge-info" style="font-size: 0.75rem;">轮次 ${turn.turn_id}</span>
            <span class="text-dim" style="font-size: 0.78rem;">🕐 ${new Date(turn.timestamp).toLocaleString('zh-CN')}</span>
        </div>`,
    })).join('');

    const headerInfo = `
    <div style="margin-bottom: 15px; padding: 12px; background: var(--surface-2); border-radius: 8px;">
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; font-size: 0.9rem;">
            <div><span class="text-dim">会话ID：</span><br><strong style="font-size: 0.8rem;">${escapeHtml(data.session_id)}</strong></div>
            <div><span class="text-dim">模型：</span><br><strong>${escapeHtml(data.header?.model || '未知')}</strong></div>
            <div><span class="text-dim">轮次：</span><br><strong>${data.turns.length} 轮</strong></div>
        </div>
        ${data.header?.system_prompt_preview ? `
        <div style="margin-top: 12px;">
            <span class="text-dim" style="font-size: 0.85rem;">系统提示词预览：</span>
            <div style="margin-top: 4px; padding: 8px; background: var(--surface-2); border: 1px solid var(--line-weak); border-radius: 5px; font-size: 0.8rem; max-height: 80px; overflow-y: auto;">${escapeHtml(data.header.system_prompt_preview)}</div>
        </div>` : ''}
    </div>`;

    const modal = showModal('💬 对话详情', headerInfo + turnsHtml, {
        size: 'xlarge',
        footer: `
            <button class="btn btn-primary" data-act="export">📄 导出MD</button>
            <button class="btn" data-act="preview">👁️ 预览总结</button>
            <button class="btn btn-success" data-act="summarize">📝 总结为日记</button>
            <button class="btn btn-danger" data-act="delete">🗑️ 删除</button>
            <button class="btn" data-modal-close>关闭</button>
        `,
    });

    bindActions(modal, {
        'open-image': (t) => openImageLightbox(t.dataset.src),
    });
    modal.querySelector('[data-act="export"]').addEventListener('click', () => exportConversation(sessionId));
    modal.querySelector('[data-act="preview"]').addEventListener('click', () => previewConversationSummary(sessionId));
    modal.querySelector('[data-act="summarize"]').addEventListener('click', () => {
        closeModal();
        summarizeConversation(sessionId);
    });
    modal.querySelector('[data-act="delete"]').addEventListener('click', () => {
        closeModal();
        deleteConversation(sessionId);
    });
}

// ===== 单对话总结 =====

async function summarizeConversation(sessionId) {
    const ok = await confirmDialog('将此对话通过 LLM 总结为日记并保存吗？\n\n如需先查看总结内容，请使用详情弹窗中的「预览总结」。', { okText: '总结并保存' });
    if (!ok) return;

    showToast('正在调用 LLM 生成总结...', 'info');
    const data = await apiCall(`/conversation/${encodeURIComponent(sessionId)}/summarize`, 'POST', { append: true });
    if (data && !data.error) {
        showToast(`✅ 已总结到日记 ${data.target_date}`, 'success');
    } else {
        showToast('总结失败: ' + (data?.error || '未知错误'), 'error');
    }
}

async function previewConversationSummary(sessionId) {
    showToast('正在调用 LLM 预览总结...', 'info');
    const data = await apiCall(`/conversation/${encodeURIComponent(sessionId)}/summarize`, 'POST', { preview_only: true });
    if (!data || data.error) {
        showToast('预览失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }

    const modal = showModal('👁️ 总结预览', `
        <div style="padding: 15px; background: var(--surface-2); border-radius: 8px; white-space: pre-wrap; line-height: 1.7; font-size: 0.9rem;">${escapeHtml(data.summary)}</div>
        <div class="text-dim" style="margin-top: 10px; font-size: 0.8rem;">目标日期: ${escapeHtml(data.target_date)}</div>
    `, {
        size: 'large',
        footer: `
            <button class="btn btn-success" data-act="confirm">✅ 确认保存</button>
            <button class="btn" data-modal-close>关闭</button>
        `,
    });

    modal.querySelector('[data-act="confirm"]').addEventListener('click', async () => {
        showToast('正在保存...', 'info');
        const result = await apiCall(`/conversation/${encodeURIComponent(sessionId)}/summarize`, 'POST', {
            append: true,
            target_date: data.target_date,
        });
        if (result && !result.error) {
            showToast(`✅ 已保存到日记 ${result.target_date}`, 'success');
            closeModal();
        } else {
            showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
        }
    });
}

async function deleteConversation(sessionId) {
    const ok = await confirmDialog('确定要删除此对话吗？（会备份到 .deleted 目录）', { danger: true, okText: '删除' });
    if (!ok) return;

    const data = await apiCall(`/conversation/${encodeURIComponent(sessionId)}`, 'DELETE');
    if (data && !data.error) {
        showToast('✅ 对话已删除', 'success');
        loadList();
        loadStats();
    } else {
        showToast('删除失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 全天时间线 =====

async function showDayTimeline() {
    const date = rootEl.querySelector('#day-timeline-entry').dataset.date;
    if (!date) return;

    showToast(`正在加载 ${date} 的全天时间线...`, 'info');
    const data = await apiCall(`/conversations/day/${encodeURIComponent(date)}`);
    if (!data || data.error) {
        showToast('加载时间线失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }
    if (!data.turns || data.turns.length === 0) {
        showToast('该日无对话记录', 'warning');
        return;
    }

    const turnsHtml = data.turns.map((turn) => renderTurnBlock(turn, {
        compact: true,
        headerHtml: `
        <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px dashed var(--line-weak);">
            <span class="text-dim">🕒 ${new Date(turn.timestamp).toLocaleTimeString('zh-CN')}</span>
            <a href="#" data-action="goto-session" data-id="${escapeAttr(turn.session_id)}" style="color: #7090a0;">查看完整会话 →</a>
        </div>`,
    })).join('');

    const statsHtml = `
    <div style="margin-bottom: 15px; padding: 12px; background: var(--surface-2); border-radius: 8px; text-align: center;">
        <div class="text-dim" style="display: flex; justify-content: center; gap: 25px; font-size: 0.9rem;">
            <span>💬 共 <strong style="color: #70a070;">${data.total_turns}</strong> 轮对话</span>
            <span>📂 跨越 <strong style="color: #7090a0;">${Object.keys(data.sessions || {}).length}</strong> 个独立会话</span>
        </div>
    </div>`;

    const modal = showModal(`📅 全天对话时间线 (${escapeHtml(date)})`, statsHtml + turnsHtml, {
        size: 'xlarge',
        footer: `
            <button class="btn btn-primary" data-act="export">📄 导出MD</button>
            <button class="btn btn-success" data-act="summarize">📝 总结为日记</button>
            <button class="btn" data-modal-close>关闭</button>
        `,
    });

    bindActions(modal, {
        'open-image': (t) => openImageLightbox(t.dataset.src),
        'goto-session': (t) => showConversationDetail(t.dataset.id),
    });
    modal.querySelector('[data-act="export"]').addEventListener('click', () => exportDayTimeline(date));
    modal.querySelector('[data-act="summarize"]').addEventListener('click', () => {
        closeModal();
        rootEl.querySelector('#conv-batch-date').value = date;
        previewDaySummary();
    });
}

// ===== 全天总结 =====

function setBatchStatus(text, color) {
    const statusEl = rootEl.querySelector('#conv-batch-status');
    statusEl.textContent = text;
    statusEl.style.color = color || '';
}

async function previewDaySummary() {
    const date = rootEl.querySelector('#conv-batch-date').value;
    if (!date) {
        showToast('请选择日期', 'error');
        return;
    }

    setBatchStatus('正在调用 LLM 生成预览...', 'var(--accent)');
    const appendMode = rootEl.querySelector('#conv-day-append').checked;

    const data = await apiCall(`/conversations/day/${encodeURIComponent(date)}/summarize`, 'POST', {
        preview_only: true,
        append: appendMode,
    });
    if (!data || data.error) {
        setBatchStatus('❌ ' + (data?.error || '预览失败'), 'var(--danger)');
        showToast('预览失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }

    const previewEl = rootEl.querySelector('#conv-day-preview');
    previewEl.style.display = 'block';
    previewEl.dataset.date = date;
    rootEl.querySelector('#conv-day-preview-content').textContent = data.diary_content;

    const stats = data.stats || {};
    rootEl.querySelector('#conv-day-preview-stats').textContent =
        `📊 ${stats.conversations || '?'} 个会话 · ${stats.total_turns || '?'} 轮对话 · 模型: ${stats.model || '?'}`;

    setBatchStatus('✅ 预览已生成', 'var(--success)');
}

async function confirmDaySummary() {
    const date = rootEl.querySelector('#conv-day-preview').dataset.date;
    if (!date) {
        showToast('没有预览数据', 'error');
        return;
    }

    setBatchStatus('正在保存日记...', 'var(--accent)');
    const appendMode = rootEl.querySelector('#conv-day-append').checked;

    const data = await apiCall(`/conversations/day/${encodeURIComponent(date)}/summarize`, 'POST', { append: appendMode });
    if (data && !data.error) {
        showToast(`✅ ${data.message}`, 'success');
        setBatchStatus(`✅ ${data.message}`, 'var(--success)');
        closeDayPreview();
    } else {
        setBatchStatus('❌ ' + (data?.error || '保存失败'), 'var(--danger)');
        showToast('保存失败: ' + (data?.error || '未知错误'), 'error');
    }
}

async function summarizeDayToDiary() {
    const date = rootEl.querySelector('#conv-batch-date').value;
    if (!date) {
        showToast('请选择日期', 'error');
        return;
    }

    const ok = await confirmDialog(`确定要将 ${date} 的所有对话通过 LLM 总结为日记吗？`, { okText: '总结' });
    if (!ok) return;

    setBatchStatus('正在调用 LLM 总结...', 'var(--accent)');
    const appendMode = rootEl.querySelector('#conv-day-append').checked;

    const data = await apiCall(`/conversations/day/${encodeURIComponent(date)}/summarize`, 'POST', { append: appendMode });
    if (data && !data.error) {
        setBatchStatus(`✅ ${data.message}`, 'var(--success)');
        showToast(`✅ ${data.message}`, 'success');
    } else {
        setBatchStatus('❌ ' + (data?.error || '总结失败'), 'var(--danger)');
        showToast('总结失败: ' + (data?.error || '未知错误'), 'error');
    }
}

async function batchSummarize() {
    const date = rootEl.querySelector('#conv-batch-date').value;
    if (!date) {
        showToast('请选择日期', 'error');
        return;
    }

    const ok = await confirmDialog(`确定要将 ${date} 的所有对话逐个总结为日记吗？`, { okText: '开始' });
    if (!ok) return;

    setBatchStatus('正在处理...', 'var(--accent)');
    const data = await apiCall('/conversations/batch-summarize', 'POST', { date });
    if (data && !data.error) {
        setBatchStatus(`✅ 已处理 ${data.processed_count} 个对话`, 'var(--success)');
        showToast(`✅ 已将 ${data.processed_count} 个对话总结到日记 ${data.target_date}`, 'success');
    } else {
        setBatchStatus('❌ ' + (data?.error || '批量总结失败'), 'var(--danger)');
        showToast('批量总结失败: ' + (data?.error || '未知错误'), 'error');
    }
}

function quickSummarizeDay(date) {
    rootEl.querySelector('#conv-batch-date').value = date;
    previewDaySummary();
}

function closeDayPreview() {
    rootEl.querySelector('#conv-day-preview').style.display = 'none';
}

// ===== 总结配置 =====

async function loadDiaryConfig() {
    const data = await apiCall('/conversations/diary-config');
    if (!data || data.error) return;

    rootEl.querySelector('#cfg-convdiary-model').value = data.using_defaults?.model ? '' : (data.model || '');
    rootEl.querySelector('#cfg-convdiary-base-url').value = data.base_url || '';
    rootEl.querySelector('#cfg-convdiary-api-key').value = data.api_key || '';
    rootEl.querySelector('#cfg-convdiary-max-tokens').value = data.max_tokens || 65535;
    rootEl.querySelector('#cfg-convdiary-temperature').value = data.temperature ?? 1;
    // 始终显示实际值（含默认值），方便基于默认提示词修改
    rootEl.querySelector('#cfg-convdiary-single-prompt').value = data.single_prompt || '';
    rootEl.querySelector('#cfg-convdiary-day-prompt').value = data.day_prompt || '';

    const singleEl = rootEl.querySelector('#cfg-convdiary-single-prompt');
    const dayEl = rootEl.querySelector('#cfg-convdiary-day-prompt');
    singleEl.title = data.using_defaults?.single_prompt ? '当前显示的是系统默认提示词，修改后保存即可覆盖' : '已自定义';
    dayEl.title = data.using_defaults?.day_prompt ? '当前显示的是系统默认提示词，修改后保存即可覆盖' : '已自定义';
}

async function saveDiaryConfig() {
    const tempVal = parseFloat(rootEl.querySelector('#cfg-convdiary-temperature').value);
    const payload = {
        model: rootEl.querySelector('#cfg-convdiary-model').value.trim(),
        base_url: rootEl.querySelector('#cfg-convdiary-base-url').value.trim(),
        api_key: rootEl.querySelector('#cfg-convdiary-api-key').value.trim(),
        max_tokens: parseInt(rootEl.querySelector('#cfg-convdiary-max-tokens').value) || 65535,
        temperature: Number.isNaN(tempVal) ? 1 : tempVal, // 修复：NaN 兜底（0 是合法值）
        single_prompt: rootEl.querySelector('#cfg-convdiary-single-prompt').value,
        day_prompt: rootEl.querySelector('#cfg-convdiary-day-prompt').value,
    };

    const data = await apiCall('/conversations/diary-config', 'POST', payload);
    if (data && !data.error) {
        clearDirty(DIRTY_KEY);
        showToast('✅ 配置已保存', 'success');
        loadDiaryConfig();
    } else {
        showToast('保存配置失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 图片灯箱 =====

function openImageLightbox(imgSrc) {
    const lightbox = document.createElement('div');
    lightbox.style.cssText = `
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
        background: rgba(0, 0, 0, 0.9); display: flex; align-items: center;
        justify-content: center; z-index: 10000; cursor: zoom-out;
    `;
    lightbox.addEventListener('click', () => lightbox.remove());

    const img = document.createElement('img');
    img.src = imgSrc;
    img.style.cssText = 'max-width: 90vw; max-height: 90vh; border-radius: 8px; box-shadow: 0 10px 50px rgba(0,0,0,0.5); object-fit: contain;';
    img.addEventListener('click', (e) => e.stopPropagation());

    const closeBtn = document.createElement('button');
    closeBtn.textContent = '✕';
    closeBtn.style.cssText = `
        position: absolute; top: 20px; right: 30px; background: rgba(255,255,255,0.2);
        border: none; color: white; font-size: 24px; width: 40px; height: 40px;
        border-radius: 50%; cursor: pointer;
    `;
    closeBtn.addEventListener('click', () => lightbox.remove());

    lightbox.appendChild(img);
    lightbox.appendChild(closeBtn);
    document.body.appendChild(lightbox);

    const escHandler = (e) => {
        if (e.key === 'Escape') {
            lightbox.remove();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
}

// ===== 导出 Markdown =====

async function exportConversation(sessionId) {
    showToast('正在生成 Markdown...', 'info');
    const data = await apiCall(`/conversation/${encodeURIComponent(sessionId)}`);
    if (!data || data.error) {
        showToast('导出失败: ' + (data?.error || '加载对话失败'), 'error');
        return;
    }

    let md = `# 对话记录\n\n`;
    md += `- **会话ID**: ${data.session_id}\n`;
    md += `- **模型**: ${data.header?.model || '未知'}\n`;
    md += `- **轮次**: ${data.turns.length} 轮\n`;
    md += `- **时间**: ${data.turns[0]?.timestamp ? new Date(data.turns[0].timestamp).toLocaleString('zh-CN') : '--'}\n\n`;

    if (data.header?.system_prompt_preview) {
        md += `## 系统提示词\n\n\`\`\`\n${data.header.system_prompt_preview}\n\`\`\`\n\n`;
    }
    md += `---\n\n`;

    for (const turn of data.turns) {
        md += `## 轮次 ${turn.turn_id}\n\n`;
        md += `*${new Date(turn.timestamp).toLocaleString('zh-CN')}*\n\n`;
        md += `### 👤 用户\n\n${turn.user}\n\n`;
        if (turn.images && turn.images.length > 0) {
            md += `**附图**: ${turn.images.map((p) => `\`${p}\``).join(', ')}\n\n`;
        }
        if (turn.metadata?.reasoning_content) {
            md += `### 💭 思考过程\n\n> ${turn.metadata.reasoning_content.split('\n').join('\n> ')}\n\n`;
        }
        md += `### 🤖 助手\n\n${turn.assistant}\n\n---\n\n`;
    }

    downloadText(`conversation_${sessionId}.md`, md, 'text/markdown');
    showToast('✅ Markdown 已导出', 'success');
}

async function exportDayTimeline(date) {
    showToast('正在生成 Markdown...', 'info');
    const data = await apiCall(`/conversations/day/${encodeURIComponent(date)}`);
    if (!data || data.error) {
        showToast('导出失败: ' + (data?.error || '加载时间线失败'), 'error');
        return;
    }

    let md = `# ${date} 对话时间线\n\n`;
    md += `- **总轮次**: ${data.total_turns} 轮\n`;
    md += `- **独立会话**: ${Object.keys(data.sessions || {}).length} 个\n\n---\n\n`;

    for (const turn of data.turns) {
        const time = new Date(turn.timestamp).toLocaleTimeString('zh-CN');
        md += `## ${time}\n\n`;
        md += `*会话: ${turn.session_id}*\n\n`;
        md += `### 👤 用户\n\n${turn.user}\n\n`;
        if (turn.images && turn.images.length > 0) {
            md += `**附图**: ${turn.images.map((p) => `\`${p}\``).join(', ')}\n\n`;
        }
        if (turn.metadata?.reasoning_content) {
            md += `### 💭 思考过程\n\n> ${turn.metadata.reasoning_content.split('\n').join('\n> ')}\n\n`;
        }
        md += `### 🤖 助手\n\n${turn.assistant}\n\n---\n\n`;
    }

    downloadText(`timeline_${date}.md`, md, 'text/markdown');
    showToast('✅ Markdown 已导出', 'success');
}

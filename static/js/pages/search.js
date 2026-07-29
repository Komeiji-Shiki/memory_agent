/**
 * 全局搜索页（新增，体验功能 H）
 * - 统一入口：跨关键词索引 / 节点 / 对话内容聚合搜索
 * - 可选叠加 RAG 语义搜索与 Graphiti 图谱搜索
 * - 命中关键词 <mark> 高亮
 * 后端：POST /search/global（并行聚合，各来源独立容错）
 */

import { apiCall } from '../core/api.js';
import { showToast, escapeHtml, spinnerHtml, bindActions } from '../core/ui.js';
import { navigate } from '../core/router.js';
import { loadPref, savePref } from '../core/store.js';

let rootEl = null;
let lastQuery = '';

export const searchPage = {
    id: 'search',
    title: '全局搜索',
    icon: '🔍',
    group: 'memory',

    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="page-header">
                <h2>🔍 全局搜索</h2>
                <p>跨日记、节点、对话的统一检索</p>
            </div>

            <div class="search-hero">
                <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                    <input type="text" id="global-search-input" class="form-input" placeholder="搜索关键词、人物、事件..."
                           style="flex: 1; min-width: 260px; font-size: 1.05rem; padding: 12px 16px;">
                    <button class="btn btn-primary" data-action="do-search" style="padding: 12px 24px;">🔍 搜索</button>
                </div>
                <div style="display: flex; gap: 18px; margin-top: 12px; flex-wrap: wrap; align-items: center;">
                    <span class="text-dim" style="font-size: 0.85rem;">默认搜索：关键词索引 / 节点 / 对话内容</span>
                    <label class="checkbox-label"><input type="checkbox" id="search-include-rag">🔮 叠加 RAG 语义搜索</label>
                    <label class="checkbox-label"><input type="checkbox" id="search-include-graphiti">⏳ 叠加 Graphiti 图谱</label>
                </div>
            </div>

            <div id="global-search-results" style="margin-top: 20px;"></div>
        `;

        bindActions(container, {
            'do-search': doSearch,
            'goto-node': () => navigate('memory'),
            'goto-conversation': () => navigate('conversations'),
        });

        const input = container.querySelector('#global-search-input');
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') doSearch();
        });

        // 记住可选项偏好
        container.querySelector('#search-include-rag').checked = loadPref('search.includeRag', false);
        container.querySelector('#search-include-graphiti').checked = loadPref('search.includeGraphiti', false);
    },

    onEnter() {
        rootEl.querySelector('#global-search-input').focus();
    },
};

/** 转义正则元字符 */
function escapeRegExp(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** 高亮命中关键词（先 HTML 转义再插入 <mark>） */
function highlight(text, query) {
    const escaped = escapeHtml(text || '');
    if (!query) return escaped;
    const pattern = new RegExp(escapeRegExp(escapeHtml(query)), 'gi');
    return escaped.replace(pattern, (m) => `<mark>${m}</mark>`);
}

async function doSearch() {
    const query = rootEl.querySelector('#global-search-input').value.trim();
    if (!query) {
        showToast('请输入搜索内容', 'error');
        return;
    }

    const includeRag = rootEl.querySelector('#search-include-rag').checked;
    const includeGraphiti = rootEl.querySelector('#search-include-graphiti').checked;
    savePref('search.includeRag', includeRag);
    savePref('search.includeGraphiti', includeGraphiti);

    lastQuery = query;
    const container = rootEl.querySelector('#global-search-results');
    container.innerHTML = spinnerHtml('搜索中...');

    const data = await apiCall('/search/global', 'POST', {
        query,
        limit: 20,
        days: 30,
        include_rag: includeRag,
        include_graphiti: includeGraphiti,
    });

    if (!data || data.error) {
        container.innerHTML = `<div class="alert alert-danger"><span>❌</span><div>${escapeHtml(data?.error || '搜索失败')}</div></div>`;
        return;
    }

    let html = '';
    html += renderSection('🔑 关键词索引', data.keyword, renderKeywordItem);
    html += renderSection('📌 节点', data.nodes, renderNodeItem);
    html += renderSection('💬 对话内容', data.conversations, renderConversationItem);
    html += renderSection('🔮 RAG 语义', data.rag, renderRagItem);
    html += renderSection('⏳ Graphiti 图谱', data.graphiti, renderGraphitiItem);

    if (!html.trim()) {
        html = '<p class="text-dim" style="text-align: center; padding: 40px;">所有来源均无结果</p>';
    }
    container.innerHTML = html;
}

function renderSection(title, section, itemRenderer) {
    if (!section || section.skipped) return '';

    let body;
    if (section.error) {
        body = `<div class="alert alert-danger"><span>❌</span><div>${escapeHtml(section.error)}</div></div>`;
    } else if (!section.results || section.results.length === 0) {
        body = '<p class="text-dim">无结果</p>';
    } else {
        body = section.results.map(itemRenderer).join('');
    }

    const count = section.total ?? 0;
    return `
    <div class="card">
        <div class="card-header">
            <h3>${title} <span class="badge badge-info">${count}</span></h3>
        </div>
        ${body}
    </div>`;
}

function renderKeywordItem(r) {
    return `
    <div style="padding: 10px; border-bottom: 1px solid var(--line-weak);">
        <strong>${escapeHtml(r.file || '')}</strong> <span class="badge badge-info">${escapeHtml(r.type || '')}</span>
        <p class="text-dim" style="margin-top: 5px;">${highlight(r.snippet || '', lastQuery)}</p>
    </div>`;
}

function renderNodeItem(r) {
    const tagsHtml = (r.tags || []).map((t) => `<span class="badge">#${escapeHtml(t)}</span>`).join(' ');
    return `
    <div style="padding: 10px; border-bottom: 1px solid var(--line-weak); cursor: pointer;" data-action="goto-node" title="前往记忆库页查看">
        <strong>${highlight(r.name || '', lastQuery)}</strong>
        <span class="badge badge-info">${escapeHtml(r.type || '')}</span>
        ${tagsHtml}
        <p class="text-dim" style="margin-top: 5px;">${highlight(r.snippet || '', lastQuery)}</p>
    </div>`;
}

function renderConversationItem(r) {
    const time = r.timestamp ? new Date(r.timestamp).toLocaleString('zh-CN') : r.date || '';
    const roleLabel = r.role === 'user' ? '👤 用户' : '🤖 助手';
    return `
    <div style="padding: 10px; border-bottom: 1px solid var(--line-weak); cursor: pointer;" data-action="goto-conversation" title="前往对话管理页查看">
        <span class="badge badge-info">${roleLabel}</span>
        <span class="text-dim" style="font-size: 0.82rem; margin-left: 8px;">🕐 ${escapeHtml(time)}</span>
        <span class="text-dim" style="font-size: 0.82rem; margin-left: 8px;">${escapeHtml(r.session_id || '')}</span>
        <p style="margin-top: 5px;">${highlight(r.snippet || '', lastQuery)}</p>
    </div>`;
}

function renderRagItem(r) {
    const similarity = ((r.similarity || 0) * 100).toFixed(1);
    const type = r.metadata?.type || '';
    const date = r.metadata?.date || '';
    return `
    <div style="padding: 10px; border-bottom: 1px solid var(--line-weak);">
        ${type ? `<span class="badge badge-info">${escapeHtml(type)}</span>` : ''}
        ${date ? `<span class="text-dim" style="font-size: 0.82rem; margin-left: 8px;">${escapeHtml(date)}</span>` : ''}
        <span style="float: right; color: var(--accent); font-weight: 600;">相似度 ${similarity}%</span>
        <p style="margin-top: 5px; clear: both;">${highlight(r.content || '', lastQuery)}</p>
    </div>`;
}

function renderGraphitiItem(r) {
    const icon = r.type === 'edge' ? '🔗' : '📦';
    const score = r.score ? `(${r.score.toFixed(3)})` : '';
    return `
    <div style="padding: 10px; border-bottom: 1px solid var(--line-weak);">
        <span>${icon}</span>
        ${r.source ? `<span style="color: var(--accent); margin-left: 6px;">[${escapeHtml(r.source)}]</span>` : ''}
        <span class="text-dim" style="font-size: 0.82rem; margin-left: 6px;">${score}</span>
        <p style="margin-top: 5px;">${highlight(r.content || '', lastQuery)}</p>
    </div>`;
}

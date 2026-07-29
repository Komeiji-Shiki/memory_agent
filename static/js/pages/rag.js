/**
 * RAG 配置页
 * - 索引状态统计（向量总数/嵌入模型/最后更新/类型分布）
 * - 重建索引（支持增量/完全重建）
 * - RAG 配置（API Key 掩码保护，接入全局脏跟踪）
 * - 语义搜索测试
 */

import { apiCall } from '../core/api.js';
import { showToast, confirmDialog, escapeHtml, spinnerHtml, errorHtml, bindActions } from '../core/ui.js';
import { markDirty, clearDirty, isDirty } from '../core/store.js';

let rootEl = null;
const DIRTY_KEY = 'rag-config';

export const ragPage = {
    id: 'rag',
    title: 'RAG 配置',
    icon: '🔮',
    group: 'settings',

    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="page-header">
                <h2>🔮 RAG 配置</h2>
                <p>语义向量索引与检索配置</p>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>📊 索引状态</h3>
                    <button class="btn btn-sm" data-action="refresh-stats">🔄 刷新</button>
                </div>
                <div id="rag-stats">${spinnerHtml()}</div>
                <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-top: 15px; padding-top: 15px; border-top: 1px solid var(--line-weak);">
                    <button class="btn btn-warning" data-action="rebuild-index">🔨 重建索引</button>
                    <label class="checkbox-label"><input type="checkbox" id="rag-rebuild-full">完全重建（默认增量）</label>
                    <span id="rag-rebuild-status" class="text-dim"></span>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>⚙️ RAG 配置</h3></div>
                <div id="rag-config-form">
                    <div class="form-row cols-2">
                        <div class="form-group">
                            <label class="checkbox-label" style="margin-top: 24px;">
                                <input type="checkbox" id="cfg-rag-enabled">启用 RAG 语义检索
                            </label>
                        </div>
                        <div class="form-group">
                            <label for="cfg-rag-api-key">API Key</label>
                            <input type="password" id="cfg-rag-api-key" placeholder="sk-..." autocomplete="off">
                        </div>
                    </div>
                    <div class="form-row cols-2">
                        <div class="form-group">
                            <label for="cfg-rag-model">嵌入模型</label>
                            <input type="text" id="cfg-rag-model" placeholder="Qwen/Qwen3-Embedding-8B">
                        </div>
                        <div class="form-group">
                            <label for="cfg-rag-url">Embedding API 地址</label>
                            <input type="text" id="cfg-rag-url" placeholder="https://api.siliconflow.cn/v1/embeddings">
                        </div>
                    </div>
                    <div class="form-row cols-4">
                        <div class="form-group">
                            <label for="cfg-rag-chunk-size">分块大小</label>
                            <input type="number" id="cfg-rag-chunk-size" min="100" max="2000" value="500">
                        </div>
                        <div class="form-group">
                            <label for="cfg-rag-chunk-overlap">分块重叠</label>
                            <input type="number" id="cfg-rag-chunk-overlap" min="0" max="500" value="50">
                        </div>
                        <div class="form-group">
                            <label for="cfg-rag-top-k">Top K</label>
                            <input type="number" id="cfg-rag-top-k" min="1" max="50" value="5">
                        </div>
                        <div class="form-group">
                            <label for="cfg-rag-threshold">相似度阈值</label>
                            <input type="number" id="cfg-rag-threshold" min="0" max="1" step="0.05" value="0.3">
                        </div>
                    </div>
                </div>
                <div style="margin-top: 12px;">
                    <button class="btn btn-success" data-action="save-config">💾 保存配置</button>
                    <span class="text-dim" style="margin-left: 10px;">修改配置后需要重建索引生效</span>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>🔍 语义搜索测试</h3></div>
                <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                    <input type="text" id="rag-search-query" class="form-input" placeholder="输入语义查询内容..." style="flex: 1; min-width: 240px;">
                    <select id="rag-search-type" class="form-select" style="width: auto;">
                        <option value="">全部类型</option>
                        <option value="diary">📔 日记</option>
                        <option value="node">📌 节点</option>
                        <option value="summary">📝 总结</option>
                    </select>
                    <button class="btn btn-primary" data-action="rag-search">🔍 搜索</button>
                </div>
                <div id="rag-search-results" style="margin-top: 15px;"></div>
            </div>
        `;

        bindActions(container, {
            'refresh-stats': loadRagStats,
            'rebuild-index': rebuildRagIndex,
            'save-config': saveRagConfig,
            'rag-search': ragSearch,
        });

        container.querySelector('#rag-search-query').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') ragSearch();
        });

        const configForm = container.querySelector('#rag-config-form');
        configForm.addEventListener('input', () => markDirty(DIRTY_KEY, 'RAG 配置'));
        configForm.addEventListener('change', () => markDirty(DIRTY_KEY, 'RAG 配置'));
    },

    onEnter() {
        loadRagStats();
        if (!isDirty(DIRTY_KEY)) {
            loadRagConfig();
        }
    },
};

async function loadRagStats() {
    const container = rootEl.querySelector('#rag-stats');
    container.innerHTML = spinnerHtml();

    const data = await apiCall('/rag/stats');
    if (!data || data.error) {
        container.innerHTML = errorHtml('加载失败: ' + (data?.error || '未知错误'));
        return;
    }

    if (!data.enabled) {
        container.innerHTML = `
            <div class="alert alert-warning">
                <span>⚠️</span>
                <div>RAG 未启用或未配置 API Key。请在下方配置后启用。</div>
            </div>`;
        return;
    }

    let html = `
        <div class="stats-grid" style="margin-bottom: 0;">
            <div class="stat-card">
                <div class="stat-card-label">📊 向量总数</div>
                <div class="stat-card-value">${data.total_entries || 0}</div>
                <div class="stat-card-detail">条向量</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-label">🤖 嵌入模型</div>
                <div class="stat-card-value" style="font-size: 1rem;">${escapeHtml(data.model || '-')}</div>
                <div class="stat-card-detail">Embedding</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-label">⏰ 最后更新</div>
                <div class="stat-card-value" style="font-size: 1rem;">${data.last_updated ? escapeHtml(data.last_updated.substring(0, 10)) : '-'}</div>
                <div class="stat-card-detail">${data.last_updated ? escapeHtml(data.last_updated.substring(11, 16)) : ''}</div>
            </div>
        </div>`;

    if (data.by_type && Object.keys(data.by_type).length > 0) {
        html += '<div style="margin-top: 15px;"><strong class="text-dim">按类型分布：</strong>';
        html += '<div style="display: flex; gap: 10px; margin-top: 8px; flex-wrap: wrap;">';
        for (const [type, count] of Object.entries(data.by_type)) {
            html += `<span class="badge badge-info">${escapeHtml(type)}: ${count}</span>`;
        }
        html += '</div></div>';
    }

    container.innerHTML = html;
}

async function loadRagConfig() {
    const data = await apiCall('/rag/config');
    if (!data || data.error) {
        console.error('加载 RAG 配置失败:', data?.error);
        return;
    }
    rootEl.querySelector('#cfg-rag-enabled').checked = data.enabled === true;
    rootEl.querySelector('#cfg-rag-api-key').value = data.has_api_key ? '********' : '';
    rootEl.querySelector('#cfg-rag-model').value = data.model || 'Qwen/Qwen3-Embedding-8B';
    rootEl.querySelector('#cfg-rag-url').value = data.base_url || 'https://api.siliconflow.cn/v1/embeddings';
    rootEl.querySelector('#cfg-rag-chunk-size').value = data.chunk_size ?? 500;
    rootEl.querySelector('#cfg-rag-chunk-overlap').value = data.chunk_overlap ?? 50;
    rootEl.querySelector('#cfg-rag-top-k').value = data.top_k ?? 5;
    rootEl.querySelector('#cfg-rag-threshold').value = data.similarity_threshold ?? 0.3;
}

async function saveRagConfig() {
    const apiKey = rootEl.querySelector('#cfg-rag-api-key').value.trim();

    const config = {
        enabled: rootEl.querySelector('#cfg-rag-enabled').checked,
        model: rootEl.querySelector('#cfg-rag-model').value.trim(),
        base_url: rootEl.querySelector('#cfg-rag-url').value.trim(),
        chunk_size: parseInt(rootEl.querySelector('#cfg-rag-chunk-size').value) || 500,
        chunk_overlap: parseInt(rootEl.querySelector('#cfg-rag-chunk-overlap').value) || 50,
        top_k: parseInt(rootEl.querySelector('#cfg-rag-top-k').value) || 5,
        similarity_threshold: parseFloat(rootEl.querySelector('#cfg-rag-threshold').value) || 0.3,
    };

    // 掩码值不提交，后端会保留原 key
    if (apiKey && apiKey !== '********') {
        config.api_key = apiKey;
    }

    const result = await apiCall('/rag/config', 'POST', config);
    if (result && result.success) {
        clearDirty(DIRTY_KEY);
        showToast(result.message || 'RAG 配置已保存（需要重建索引生效）', 'success');
        loadRagStats();
        loadRagConfig();
    } else {
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

async function rebuildRagIndex() {
    const full = rootEl.querySelector('#rag-rebuild-full').checked;
    const modeDesc = full ? '完全重建（重新向量化所有内容）' : '增量重建（仅处理新增/变更内容）';
    const ok = await confirmDialog(`确定要${modeDesc}吗？\n\n向量化需要调用嵌入 API，可能需要几分钟时间。`, { okText: '开始重建' });
    if (!ok) return;

    const status = rootEl.querySelector('#rag-rebuild-status');
    status.innerHTML = '<span class="spinner"></span> 重建中...请耐心等待';

    const result = await apiCall(`/rag/rebuild?incremental=${full ? 'false' : 'true'}`, 'POST');
    if (result && result.success) {
        const stats = result.stats || {};
        status.innerHTML = `<span style="color: var(--success);">✅ 完成！日记 ${stats.diaries || 0} 个，节点 ${stats.nodes || 0} 个，总结 ${stats.summaries || 0} 个，共 ${stats.total_vectors || 0} 个向量</span>`;
        showToast('索引重建完成', 'success');
        loadRagStats();
    } else {
        const errorMsg = result?.message || result?.error || '重建失败';
        status.innerHTML = `<span style="color: var(--danger);">❌ ${escapeHtml(errorMsg)}</span>`;
        showToast(errorMsg, 'error');
    }
}

async function ragSearch() {
    const query = rootEl.querySelector('#rag-search-query').value.trim();
    if (!query) {
        showToast('请输入查询内容', 'error');
        return;
    }

    const filterType = rootEl.querySelector('#rag-search-type').value;
    const container = rootEl.querySelector('#rag-search-results');
    container.innerHTML = spinnerHtml('搜索中...');

    const payload = { query, top_k: 10 };
    if (filterType) payload.filter_type = filterType;

    const data = await apiCall('/rag/search', 'POST', payload);
    if (data && data.error) {
        container.innerHTML = `<div class="alert alert-danger"><span>❌</span><div>${escapeHtml(data.error)}</div></div>`;
        return;
    }
    if (!data || !data.results || data.results.length === 0) {
        container.innerHTML = '<p class="text-dim">未找到语义相关的内容</p>';
        return;
    }

    let html = `<p class="text-dim" style="margin-bottom: 15px;">找到 ${data.total || 0} 条语义相关结果：</p>`;
    for (const r of data.results) {
        const similarity = ((r.similarity || 0) * 100).toFixed(1);
        const typeLabel = r.metadata?.type || 'unknown';
        const date = r.metadata?.date || '';
        const simColor = r.similarity > 0.7 ? 'var(--success)' :
                         r.similarity > 0.5 ? 'var(--accent)' : 'var(--text-dim)';

        html += `
        <div style="background: var(--surface-2); padding: 15px; margin-bottom: 12px; border-radius: 8px; border-left: 3px solid ${simColor};">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <div>
                    <span class="badge badge-info">${escapeHtml(typeLabel)}</span>
                    ${date ? `<span style="margin-left: 8px;" class="text-dim">${escapeHtml(date)}</span>` : ''}
                </div>
                <span style="color: ${simColor}; font-weight: 600;">相似度 ${similarity}%</span>
            </div>
            <p style="margin: 0; line-height: 1.6; font-size: 0.9rem;">${escapeHtml(r.content || '')}</p>
        </div>`;
    }
    container.innerHTML = html;
}

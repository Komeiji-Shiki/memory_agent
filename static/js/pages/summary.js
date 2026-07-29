/**
 * 总结页
 * - 缺失检测（周/月/季，快速生成）
 * - 手动生成（类型/标识符自动预填/模型与提示词临时覆盖）
 * - 总结配置（模型/三级提示词/重试策略，接入全局脏跟踪）
 * - 已有总结列表（含 yearly，若有数据）
 */

import { apiCall } from '../core/api.js';
import { showToast, escapeHtml, escapeAttr, spinnerHtml, emptyHtml, errorHtml, bindActions } from '../core/ui.js';
import { markDirty, clearDirty, isDirty } from '../core/store.js';

let rootEl = null;
const DIRTY_KEY = 'summary-config';

const TYPE_META = {
    weekly:    { name: '周总结',   emoji: '📅', hint: '格式：2025-W52（年份-W周数）' },
    monthly:   { name: '月总结',   emoji: '📆', hint: '格式：2025-12（年份-月份）' },
    quarterly: { name: '季度总结', emoji: '🗂️', hint: '格式：2025-Q4（年份-Q季度）' },
    yearly:    { name: '年总结',   emoji: '📚', hint: '格式：2025（年份）' },
};

export const summaryPage = {
    id: 'summary',
    title: '总结',
    icon: '📝',
    group: 'memory',

    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="page-header">
                <h2>📝 总结</h2>
                <p>周期性总结的检测、生成与配置</p>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>🔍 缺失检测</h3>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <select id="missing-lookback" class="form-select" style="width: auto;">
                            <option value="3">回看 3 个周期</option>
                            <option value="6" selected>回看 6 个周期</option>
                            <option value="12">回看 12 个周期</option>
                        </select>
                        <button class="btn btn-sm" data-action="check-missing">🔄 重新检测</button>
                    </div>
                </div>
                <div id="missing-summaries">${spinnerHtml()}</div>
            </div>

            <div class="card">
                <div class="card-header"><h3>✍️ 手动生成</h3></div>
                <div class="form-row cols-3">
                    <div class="form-group">
                        <label for="summary-type">总结类型</label>
                        <select id="summary-type">
                            <option value="weekly">📅 周总结</option>
                            <option value="monthly">📆 月总结</option>
                            <option value="quarterly">🗂️ 季度总结</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="summary-identifier">标识符</label>
                        <input type="text" id="summary-identifier" placeholder="如 2025-W52">
                        <small id="identifier-hint" class="text-dim"></small>
                    </div>
                    <div class="form-group">
                        <label for="summary-model">模型（可选）</label>
                        <input type="text" id="summary-model" placeholder="留空使用配置中的模型">
                    </div>
                </div>
                <div class="form-group">
                    <label for="summary-prompt">提示词（可选，临时覆盖本次生成）</label>
                    <textarea id="summary-prompt" rows="3" placeholder="留空使用配置中的提示词"></textarea>
                </div>
                <div style="display: flex; gap: 12px; align-items: center;">
                    <button class="btn btn-primary" data-action="generate-summary">🚀 生成总结</button>
                    <span id="generate-status" class="text-dim"></span>
                </div>
            </div>

            <div class="card" id="summary-result-card" style="display: none;">
                <div class="card-header"><h3>📄 生成结果</h3></div>
                <pre id="summary-result" style="white-space: pre-wrap; word-break: break-word;"></pre>
            </div>

            <div class="card">
                <div class="card-header"><h3>⚙️ 总结配置</h3></div>
                <div id="summary-config-form">
                    <div class="form-row cols-3">
                        <div class="form-group">
                            <label for="cfg-summary-model">总结模型</label>
                            <input type="text" id="cfg-summary-model" placeholder="deepseek-chat">
                        </div>
                        <div class="form-group">
                            <label for="cfg-summary-base-url">API URL</label>
                            <input type="text" id="cfg-summary-base-url" placeholder="留空使用记忆代理配置">
                        </div>
                        <div class="form-group">
                            <label for="cfg-summary-api-key">API Key</label>
                            <input type="password" id="cfg-summary-api-key" placeholder="留空使用记忆代理配置" autocomplete="new-password">
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="cfg-weekly-prompt">周总结提示词 <span id="badge-weekly-default" class="badge" style="display: none;">当前为默认</span></label>
                        <textarea id="cfg-weekly-prompt" rows="5"></textarea>
                    </div>
                    <div class="form-group">
                        <label for="cfg-monthly-prompt">月总结提示词 <span id="badge-monthly-default" class="badge" style="display: none;">当前为默认</span></label>
                        <textarea id="cfg-monthly-prompt" rows="5"></textarea>
                    </div>
                    <div class="form-group">
                        <label for="cfg-quarterly-prompt">季度总结提示词 <span id="badge-quarterly-default" class="badge" style="display: none;">当前为默认</span></label>
                        <textarea id="cfg-quarterly-prompt" rows="5"></textarea>
                    </div>
                    <div class="form-row cols-4">
                        <div class="form-group">
                            <label class="checkbox-label" style="margin-top: 24px;">
                                <input type="checkbox" id="cfg-summary-retry" checked>失败自动重试
                            </label>
                        </div>
                        <div class="form-group">
                            <label for="cfg-summary-max-retries">最大重试次数</label>
                            <input type="number" id="cfg-summary-max-retries" min="0" max="10" value="3">
                        </div>
                        <div class="form-group">
                            <label for="cfg-summary-base-delay">基础延迟（秒）</label>
                            <input type="number" id="cfg-summary-base-delay" min="0" step="0.5" value="1">
                        </div>
                        <div class="form-group">
                            <label for="cfg-summary-max-delay">最大延迟（秒）</label>
                            <input type="number" id="cfg-summary-max-delay" min="0" step="1" value="30">
                        </div>
                    </div>
                </div>
                <div style="margin-top: 12px;">
                    <button class="btn btn-success" data-action="save-summary-config">💾 保存配置</button>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>🗃️ 已有总结</h3>
                    <button class="btn btn-sm" data-action="refresh-summaries">🔄 刷新</button>
                </div>
                <div id="existing-summaries">${spinnerHtml()}</div>
            </div>
        `;

        bindActions(container, {
            'check-missing': checkMissingSummaries,
            'generate-summary': generateSummary,
            'quick-generate': (t) => quickGenerate(t.dataset.type, t.dataset.id),
            'save-summary-config': saveSummaryConfig,
            'refresh-summaries': loadExistingSummaries,
        });

        container.querySelector('#summary-type').addEventListener('change', updateSummaryIdentifier);
        container.querySelector('#missing-lookback').addEventListener('change', checkMissingSummaries);

        const configForm = container.querySelector('#summary-config-form');
        configForm.addEventListener('input', () => markDirty(DIRTY_KEY, '总结配置'));
        configForm.addEventListener('change', () => markDirty(DIRTY_KEY, '总结配置'));

        updateSummaryIdentifier();
    },

    onEnter() {
        checkMissingSummaries();
        loadExistingSummaries();
        if (!isDirty(DIRTY_KEY)) {
            loadSummaryConfig();
        }
    },
};

/** 根据类型预填上一周期标识符与格式提示（ISO 周计算与旧版一致） */
function updateSummaryIdentifier() {
    const type = rootEl.querySelector('#summary-type').value;
    const input = rootEl.querySelector('#summary-identifier');
    const hint = rootEl.querySelector('#identifier-hint');

    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth() + 1;
    const quarter = Math.ceil(month / 3);

    // ISO 周数
    const d = new Date(now);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() + 3 - (d.getDay() + 6) % 7);
    const week1 = new Date(d.getFullYear(), 0, 4);
    const weekNum = 1 + Math.round(((d - week1) / 86400000 - 3 + (week1.getDay() + 6) % 7) / 7);

    if (type === 'weekly') {
        const lastWeek = weekNum > 1 ? weekNum - 1 : 52;
        const lastWeekYear = weekNum > 1 ? year : year - 1;
        input.value = `${lastWeekYear}-W${String(lastWeek).padStart(2, '0')}`;
    } else if (type === 'monthly') {
        const lastMonth = month > 1 ? month - 1 : 12;
        const lastMonthYear = month > 1 ? year : year - 1;
        input.value = `${lastMonthYear}-${String(lastMonth).padStart(2, '0')}`;
    } else {
        const lastQ = quarter > 1 ? quarter - 1 : 4;
        const lastQYear = quarter > 1 ? year : year - 1;
        input.value = `${lastQYear}-Q${lastQ}`;
    }
    hint.textContent = TYPE_META[type].hint;
}

async function checkMissingSummaries() {
    const container = rootEl.querySelector('#missing-summaries');
    const lookback = rootEl.querySelector('#missing-lookback').value;
    container.innerHTML = spinnerHtml('检测中...');

    const data = await apiCall(`/summary/missing?lookback=${encodeURIComponent(lookback)}`);
    if (!data || data.error) {
        container.innerHTML = errorHtml('检测失败: ' + (data?.error || '未知错误'));
        return;
    }

    let html = '<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px;">';
    for (const type of ['weekly', 'monthly', 'quarterly']) {
        const meta = TYPE_META[type];
        html += `<div><h4 style="color: var(--accent); margin-bottom: 10px;">${meta.emoji} ${meta.name}</h4>`;
        const items = data[type] || [];
        if (items.length > 0) {
            for (const id of items) {
                html += `<div style="display: flex; justify-content: space-between; align-items: center; padding: 5px 0; border-bottom: 1px solid var(--line-weak);">
                    <span>${escapeHtml(id)}</span>
                    <button class="btn btn-sm btn-primary" data-action="quick-generate" data-type="${type}" data-id="${escapeAttr(id)}">生成</button>
                </div>`;
            }
        } else {
            html += '<p style="color: var(--success);">✅ 无缺失</p>';
        }
        html += '</div>';
    }
    html += '</div>';
    container.innerHTML = html;
}

async function quickGenerate(type, identifier) {
    rootEl.querySelector('#summary-type').value = type;
    rootEl.querySelector('#summary-identifier').value = identifier;
    rootEl.querySelector('#identifier-hint').textContent = TYPE_META[type].hint;
    await generateSummary();
}

async function generateSummary() {
    const type = rootEl.querySelector('#summary-type').value;
    const identifier = rootEl.querySelector('#summary-identifier').value.trim();
    const model = rootEl.querySelector('#summary-model').value.trim();
    const prompt = rootEl.querySelector('#summary-prompt').value;

    if (!identifier) {
        showToast('请输入标识符', 'error');
        return;
    }

    const status = rootEl.querySelector('#generate-status');
    status.innerHTML = '<span class="spinner"></span> 生成中...（可能需要30秒）';

    const payload = { type, identifier };
    if (model) payload.model = model;
    if (prompt) payload.prompt = prompt;

    const result = await apiCall('/summary/generate', 'POST', payload);
    if (result && result.success) {
        status.innerHTML = '<span style="color: var(--success);">✅ 生成成功</span>';
        showToast(result.message || '生成成功', 'success');

        const resultCard = rootEl.querySelector('#summary-result-card');
        resultCard.style.display = 'block';
        rootEl.querySelector('#summary-result').textContent = result.content || '';

        loadExistingSummaries();
        checkMissingSummaries();
    } else {
        const errorMsg = result?.message || result?.error || '未知错误';
        status.innerHTML = `<span style="color: var(--danger);">❌ ${escapeHtml(errorMsg)}</span>`;
        showToast(errorMsg, 'error');
    }
}

async function loadSummaryConfig() {
    const data = await apiCall('/summary/config');
    if (!data || data.error) {
        console.error('加载总结配置失败:', data?.error);
        return;
    }
    rootEl.querySelector('#cfg-summary-model').value = data.model || 'deepseek-chat';
    rootEl.querySelector('#cfg-summary-base-url').value = data.base_url || '';
    rootEl.querySelector('#cfg-summary-api-key').value = data.api_key || '';
    rootEl.querySelector('#cfg-weekly-prompt').value = data.weekly_prompt || '';
    rootEl.querySelector('#cfg-monthly-prompt').value = data.monthly_prompt || '';
    rootEl.querySelector('#cfg-quarterly-prompt').value = data.quarterly_prompt || '';

    rootEl.querySelector('#cfg-summary-retry').checked = data.enable_retry !== false;
    rootEl.querySelector('#cfg-summary-max-retries').value = data.max_retries ?? 3;
    rootEl.querySelector('#cfg-summary-base-delay').value = data.base_delay ?? 1.0;
    rootEl.querySelector('#cfg-summary-max-delay').value = data.max_delay ?? 30;

    const defaults = data.using_defaults || {};
    for (const type of ['weekly', 'monthly', 'quarterly']) {
        const badge = rootEl.querySelector(`#badge-${type}-default`);
        if (badge) badge.style.display = defaults[type] ? '' : 'none';
    }
}

async function saveSummaryConfig() {
    const config = {
        model: rootEl.querySelector('#cfg-summary-model').value.trim(),
        base_url: rootEl.querySelector('#cfg-summary-base-url').value.trim(),
        api_key: rootEl.querySelector('#cfg-summary-api-key').value.trim(),
        weekly_prompt: rootEl.querySelector('#cfg-weekly-prompt').value,
        monthly_prompt: rootEl.querySelector('#cfg-monthly-prompt').value,
        quarterly_prompt: rootEl.querySelector('#cfg-quarterly-prompt').value,
        enable_retry: rootEl.querySelector('#cfg-summary-retry').checked,
        max_retries: parseInt(rootEl.querySelector('#cfg-summary-max-retries').value) || 3,
        base_delay: parseFloat(rootEl.querySelector('#cfg-summary-base-delay').value) || 1.0,
        max_delay: parseFloat(rootEl.querySelector('#cfg-summary-max-delay').value) || 30,
    };

    const result = await apiCall('/summary/config', 'POST', config);
    if (result && result.success) {
        clearDirty(DIRTY_KEY);
        showToast('总结配置已保存', 'success');
        loadSummaryConfig();
    } else {
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

async function loadExistingSummaries() {
    const container = rootEl.querySelector('#existing-summaries');
    container.innerHTML = spinnerHtml();

    const data = await apiCall('/summaries');
    if (!data || data.error) {
        container.innerHTML = errorHtml('加载失败: ' + (data?.error || '未知错误'));
        return;
    }

    // yearly 仅在有数据时展示，其余三类固定展示
    const types = ['weekly', 'monthly', 'quarterly'];
    if (data.yearly && data.yearly.length > 0) types.push('yearly');

    let html = `<div style="display: grid; grid-template-columns: repeat(${types.length}, 1fr); gap: 20px;">`;
    for (const type of types) {
        const meta = TYPE_META[type];
        html += `<div><h4 style="color: var(--accent); margin-bottom: 10px;">${meta.emoji} ${meta.name}</h4>`;
        const items = data[type] || [];
        if (items.length > 0) {
            for (const s of items) {
                html += `<div style="padding: 8px; margin-bottom: 8px; background: var(--surface-2); border-radius: 6px; border: 1px solid var(--line-weak);">
                    <div style="font-weight: 600; color: var(--accent); margin-bottom: 4px;">${escapeHtml(s.identifier)}</div>
                    <div style="font-size: 0.8rem; color: var(--text-dim);">${escapeHtml(s.preview || '')}</div>
                </div>`;
            }
        } else {
            html += '<p class="text-dim">暂无</p>';
        }
        html += '</div>';
    }
    html += '</div>';
    container.innerHTML = html;
}

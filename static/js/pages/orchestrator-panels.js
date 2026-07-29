/**
 * 消息编排 — 辅助面板模块
 * - 预设管理（保存/加载/删除）
 * - 模型绑定（通配符 → 预设）
 * - 历史记录与回滚
 * - 导入 / 导出配置
 * - 测试发送
 * - Prefill 预填充配置
 * 依赖 orchestrator-sequence.js 的 state 与刷新函数（单向依赖）。
 */

import { apiCall } from '../core/api.js';
import {
    showToast, showModal, closeModal, confirmDialog,
    escapeHtml, escapeAttr, spinnerHtml, bindActions, downloadText,
} from '../core/ui.js';
import { markDirty, clearDirty } from '../core/store.js';
import { state, renderSequence, initSortable, updatePreview } from './orchestrator-sequence.js';

let rootEl = null;

export function initPanelsModule(container) {
    rootEl = container;

    bindActions(container, {
        'save-preset-dialog': showSavePresetDialog,
        'delete-preset': deleteCurrentPreset,
        'load-preset': (t) => loadPreset(t.dataset.id),
        'add-binding': addNewBinding,
        'remove-binding': (t) => removeBinding(t.dataset.pattern),
        'save-bindings': saveBindings,
        'rollback-to': (t) => rollbackTo(parseInt(t.dataset.index)),
        'clear-history': clearHistory,
        'export-config': exportConfig,
        'import-config': triggerImportConfig,
        'test-send': testSend,
        'save-prefill': savePrefill,
    });

    // 序列保存成功后刷新历史
    document.addEventListener('orchestrator:sequence-saved', () => loadHistory());

    // Prefill 表单脏跟踪
    const prefillFields = ['#prefill-content', '#prefill-think-tag', '#prefill-model-bindings'];
    prefillFields.forEach((sel) => {
        container.querySelector(sel).addEventListener('input', () => markDirty('orchestrator-prefill', '预填充配置'));
    });
}

// ===== 预设管理 =====

export async function loadPresets() {
    const data = await apiCall('/orchestrator/presets');
    if (data && data.success) {
        state.presets = data.presets || [];
        state.activePreset = data.active_preset || 'default';
        renderPresets();
    }
}

function renderPresets() {
    const container = rootEl.querySelector('#orchestrator-presets');
    const presets = state.presets;
    const active = state.activePreset;

    let html = `
    <div class="preset-selector">
        <select id="preset-select" class="form-select" style="flex: 1;">
            ${presets.map((p) => `<option value="${escapeAttr(p.id)}" ${p.id === active ? 'selected' : ''}>${escapeHtml(p.name)}</option>`).join('')}
        </select>
        <button class="btn btn-sm btn-success" data-action="save-preset-dialog">💾 保存为预设</button>
        <button class="btn btn-sm btn-danger" data-action="delete-preset">🗑️ 删除</button>
    </div>
    <div class="preset-list">`;

    presets.forEach((p) => {
        html += `
        <div class="preset-item ${p.id === active ? 'active' : ''}" data-action="load-preset" data-id="${escapeAttr(p.id)}">
            <div class="preset-info">
                <span class="preset-name">${escapeHtml(p.name)}</span>
                <span class="preset-desc">${escapeHtml(p.description || '')}</span>
            </div>
            <div class="preset-meta">
                ${p.component_count} 组件
                ${p.is_active ? '<span class="badge badge-success">当前</span>' : ''}
            </div>
        </div>`;
    });
    html += '</div>';
    container.innerHTML = html;

    container.querySelector('#preset-select').addEventListener('change', (e) => loadPreset(e.target.value));
}

async function loadPreset(presetId) {
    const result = await apiCall('/orchestrator/preset/load', 'POST', { preset_name: presetId });
    if (result && result.success) {
        state.sequence = result.sequence || [];
        state.activePreset = presetId;
        renderSequence();
        initSortable();
        renderPresets();
        updatePreview();
        showToast(result.message, 'success');
    } else {
        showToast(result?.error || '加载预设失败', 'error');
    }
}

function showSavePresetDialog() {
    const modal = showModal('💾 保存预设', `
        <div class="form-group">
            <label>预设ID（唯一标识）</label>
            <input type="text" id="new-preset-id" placeholder="my_preset" value="${escapeAttr(state.activePreset)}">
        </div>
        <div class="form-group">
            <label>预设名称</label>
            <input type="text" id="new-preset-name" placeholder="我的预设">
        </div>
        <div class="form-group">
            <label>描述</label>
            <input type="text" id="new-preset-desc" placeholder="可选描述...">
        </div>
    `, {
        footer: `
            <button class="btn" data-modal-close>取消</button>
            <button class="btn btn-success" data-act="save">💾 保存</button>
        `,
    });

    modal.querySelector('#new-preset-name').focus();
    modal.querySelector('[data-act="save"]').addEventListener('click', async () => {
        const presetId = modal.querySelector('#new-preset-id').value.trim();
        const name = modal.querySelector('#new-preset-name').value.trim();
        const description = modal.querySelector('#new-preset-desc').value.trim();

        if (!presetId || !name) {
            showToast('请填写预设ID和名称', 'error');
            return;
        }

        const result = await apiCall('/orchestrator/preset/save', 'POST', {
            preset_id: presetId, name, description,
        });
        if (result && result.success) {
            closeModal();
            loadPresets();
            showToast(result.message, 'success');
        } else {
            showToast(result?.error || '保存失败', 'error');
        }
    });
}

async function deleteCurrentPreset() {
    const active = state.activePreset;
    if (active === 'default') {
        showToast('不能删除默认预设', 'error');
        return;
    }

    const ok = await confirmDialog(`确定删除预设 "${active}"？`, { danger: true, okText: '删除' });
    if (!ok) return;

    const result = await apiCall(`/orchestrator/preset/${encodeURIComponent(active)}`, 'DELETE');
    if (result && result.success) {
        loadPresets();
        const { loadSequence } = await import('./orchestrator-sequence.js');
        loadSequence();
        showToast(result.message, 'success');
    } else {
        showToast(result?.error || '删除失败', 'error');
    }
}

// ===== 模型绑定 =====

export async function loadBindings() {
    const data = await apiCall('/orchestrator/bindings');
    if (data && data.success) {
        state.bindings = data.bindings || {};
        renderBindings(data.available_presets || []);
    }
}

function renderBindings(availablePresets) {
    const container = rootEl.querySelector('#orchestrator-bindings');

    let html = `
    <div class="bindings-list">
        <div class="bindings-header">
            <span>模型匹配模式</span>
            <span>使用预设</span>
            <span></span>
        </div>`;

    Object.entries(state.bindings).forEach(([pattern, preset]) => {
        html += `
        <div class="binding-row" data-pattern="${escapeAttr(pattern)}">
            <input type="text" class="binding-pattern" value="${escapeAttr(pattern)}" placeholder="claude-*">
            <select class="binding-preset">
                ${availablePresets.map((p) => `<option value="${escapeAttr(p)}" ${p === preset ? 'selected' : ''}>${escapeHtml(p)}</option>`).join('')}
            </select>
            <button class="btn btn-sm btn-danger" data-action="remove-binding" data-pattern="${escapeAttr(pattern)}">🗑️</button>
        </div>`;
    });

    html += `
    </div>
    <div style="margin-top: 10px; display: flex; gap: 10px;">
        <button class="btn btn-sm" data-action="add-binding">➕ 添加规则</button>
        <button class="btn btn-sm btn-success" data-action="save-bindings">💾 保存绑定</button>
    </div>
    <small class="text-dim" style="display: block; margin-top: 10px;">
        使用通配符匹配模型名称，如 <code>claude-*</code> 匹配所有 Claude 模型。越靠前的规则优先级越高。
    </small>`;

    container.innerHTML = html;
}

function localPresetIds() {
    const ids = state.presets.map((p) => p.id);
    if (!ids.includes('default')) ids.unshift('default');
    return ids;
}

function syncBindingsFromDom() {
    // 保留 DOM 中的编辑值到本地状态（避免增删行时丢失未保存的修改）
    const newBindings = {};
    rootEl.querySelectorAll('.binding-row').forEach((row) => {
        const pattern = row.querySelector('.binding-pattern').value.trim();
        const preset = row.querySelector('.binding-preset').value;
        if (pattern) newBindings[pattern] = preset;
    });
    state.bindings = newBindings;
}

function addNewBinding() {
    syncBindingsFromDom();
    state.bindings['new-pattern-' + Date.now()] = 'default';
    renderBindings(localPresetIds());
    markDirty('orchestrator-bindings', '模型绑定');
}

function removeBinding(pattern) {
    syncBindingsFromDom();
    delete state.bindings[pattern];
    renderBindings(localPresetIds());
    markDirty('orchestrator-bindings', '模型绑定');
}

async function saveBindings() {
    syncBindingsFromDom();

    const result = await apiCall('/orchestrator/bindings', 'PUT', { bindings: state.bindings });
    if (result && result.success) {
        clearDirty('orchestrator-bindings');
        showToast('模型绑定已保存', 'success');
    } else {
        showToast(result?.error || '保存失败', 'error');
    }
}

// ===== 历史回滚 =====

export async function loadHistory() {
    const data = await apiCall('/orchestrator/history');
    if (data && data.success) {
        state.history = data.history || [];
        renderHistory();
    }
}

function renderHistory() {
    const container = rootEl.querySelector('#orchestrator-history');
    const history = state.history;

    if (history.length === 0) {
        container.innerHTML = '<p class="text-dim">暂无历史记录</p>';
        return;
    }

    const actionIcons = {
        update_sequence: '📝', load_preset: '📂', save_preset: '💾',
        delete_preset: '🗑️', update_bindings: '🔗', rollback: '⏪', import: '📥',
    };

    let html = '<div class="history-list">';
    history.forEach((entry, idx) => {
        const time = entry.timestamp ? new Date(entry.timestamp).toLocaleString('zh-CN') : '--';
        const icon = actionIcons[entry.action] || '📋';
        html += `
        <div class="history-item">
            <div class="history-info">
                <span class="history-icon">${icon}</span>
                <span class="history-desc">${escapeHtml(entry.description)}</span>
                <span class="history-time">${escapeHtml(time)}</span>
            </div>
            <button class="btn btn-sm" data-action="rollback-to" data-index="${idx}">恢复</button>
        </div>`;
    });
    html += '</div>';
    html += '<button class="btn btn-sm btn-danger" data-action="clear-history" style="margin-top: 10px;">🗑️ 清空历史</button>';

    container.innerHTML = html;
}

async function rollbackTo(index) {
    const ok = await confirmDialog('确定要恢复到此版本？当前未保存的更改将丢失。', { okText: '恢复' });
    if (!ok) return;

    const result = await apiCall('/orchestrator/rollback', 'POST', { index });
    if (result && result.success) {
        state.sequence = result.sequence || [];
        renderSequence();
        initSortable();
        updatePreview();
        loadHistory();
        showToast(result.message, 'success');
    } else {
        showToast(result?.error || '回滚失败', 'error');
    }
}

async function clearHistory() {
    const ok = await confirmDialog('确定要清空所有历史记录？', { danger: true, okText: '清空' });
    if (!ok) return;

    const result = await apiCall('/orchestrator/history', 'DELETE');
    if (result && result.success) {
        state.history = [];
        renderHistory();
        showToast(result.message, 'success');
    } else {
        showToast(result?.error || '清空失败', 'error');
    }
}

// ===== 导入 / 导出 =====

async function exportConfig() {
    const result = await apiCall('/orchestrator/export');
    if (result && result.success) {
        downloadText(
            `orchestrator_config_${new Date().toISOString().slice(0, 10)}.json`,
            JSON.stringify(result.config, null, 2),
            'application/json'
        );
        showToast('配置已导出', 'success');
    } else {
        showToast(result?.error || '导出失败', 'error');
    }
}

function triggerImportConfig() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        try {
            const text = await file.text();
            const config = JSON.parse(text);

            const result = await apiCall('/orchestrator/import', 'POST', { config });
            if (result && result.success) {
                state.sequence = result.sequence || [];
                renderSequence();
                initSortable();
                loadPresets();
                loadBindings();
                loadHistory();
                updatePreview();
                showToast(result.message, 'success');
            } else {
                showToast(result?.error || '导入失败', 'error');
            }
        } catch (err) {
            showToast('导入失败: ' + err.message, 'error');
        }
    };
    input.click();
}

// ===== 测试发送 =====

async function testSend() {
    const model = rootEl.querySelector('#test-model').value.trim();
    const message = rootEl.querySelector('#test-message').value.trim();
    const resultContainer = rootEl.querySelector('#test-result');

    if (!model) {
        showToast('请输入测试模型', 'error');
        return;
    }
    if (!message) {
        showToast('请输入测试消息', 'error');
        return;
    }

    resultContainer.innerHTML = spinnerHtml('发送中...');

    const result = await apiCall('/orchestrator/test', 'POST', { model, message });
    if (result && result.success) {
        resultContainer.innerHTML = `
        <div class="test-result-success">
            <h4>🤖 模型回复：</h4>
            <div class="test-response">${escapeHtml(result.response, true)}</div>
            <div class="test-meta">
                📊 Token: prompt ${result.usage?.prompt_tokens || 0} + completion ${result.usage?.completion_tokens || 0} = ${result.usage?.total_tokens || 0}
                | ⏱️ ${result.latency_ms || 0}ms
                | 📝 ${result.orchestrated_count || 0} 条编排消息
            </div>
        </div>`;
    } else {
        resultContainer.innerHTML = `<div class="test-result-error">❌ ${escapeHtml(result?.error || '未知错误')}</div>`;
    }
}

// ===== Prefill 预填充 =====

export async function loadPrefill() {
    const data = await apiCall('/orchestrator/prefill');
    if (!data || !data.success) return;

    const prefill = data.prefill || {};
    rootEl.querySelector('#prefill-content').value = prefill.content || '';
    rootEl.querySelector('#prefill-think-tag').value = prefill.think_tag || '</think>';

    const bindings = prefill.model_bindings || {};
    const enabledModels = Object.entries(bindings)
        .filter(([, enabled]) => enabled)
        .map(([model]) => model);
    rootEl.querySelector('#prefill-model-bindings').value = enabledModels.join('\n');
}

async function savePrefill() {
    const content = rootEl.querySelector('#prefill-content').value;
    const thinkTag = rootEl.querySelector('#prefill-think-tag').value || '</think>';
    const bindingsText = rootEl.querySelector('#prefill-model-bindings').value;

    const modelBindings = {};
    bindingsText.split('\n').forEach((line) => {
        const model = line.trim();
        if (model) modelBindings[model] = true;
    });

    const result = await apiCall('/orchestrator/prefill', 'PUT', {
        content,
        model_bindings: modelBindings,
        think_tag: thinkTag,
    });
    if (result && result.success) {
        clearDirty('orchestrator-prefill');
        showToast('预填充配置已保存', 'success');
    } else {
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

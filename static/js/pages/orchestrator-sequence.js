/**
 * 消息编排 — 序列模块
 * - 启用开关、序列渲染与拖拽排序（Sortable.js）
 * - 组件面板（添加组件，可编辑组件立即打开编辑）
 * - 编辑弹窗（普通组件 / 条件挂载特殊表单）
 * - 预览（结构/完整两种模式，输入区固定不重建）
 * 序列保存成功后派发 'orchestrator:sequence-saved' 事件（panels 模块据此刷新历史）。
 */

import { apiCall } from '../core/api.js';
import {
    showToast, showModal, closeModal, confirmDialog,
    escapeHtml, escapeAttr, spinnerHtml, bindActions, delegate,
} from '../core/ui.js';

let rootEl = null;

export const state = {
    sequence: [],
    availableComponents: [],
    presets: [],
    activePreset: 'default',
    bindings: {},
    history: [],
    sortableInstance: null,
};

export function initSequenceModule(container) {
    rootEl = container;

    bindActions(container.querySelector('#orchestrator-sequence').parentElement, {
        'edit-item': (t) => editSequenceItem(t.dataset.id),
        'delete-item': (t) => deleteSequenceItem(t.dataset.id),
        'toggle-item': (t) => toggleItemEnabled(t.dataset.id),
        'add-component': (t) => addComponent(t.dataset.type),
    });

    const previewPanel = container.querySelector('#orchestrator-preview').parentElement;
    bindActions(previewPanel, {
        'clear-preview-inputs': clearPreviewInputs,
        'refresh-preview': () => updatePreview(isFullPreview()),
        'toggle-msg': (t) => t.previousElementSibling.classList.toggle('collapsed'),
    });
    container.querySelectorAll('input[name="preview-mode"]').forEach((radio) => {
        radio.addEventListener('change', () => updatePreview(isFullPreview()));
    });

    container.querySelector('#orchestrator-enabled').addEventListener('change', toggleEnabled);
}

function isFullPreview() {
    return rootEl.querySelector('input[name="preview-mode"]:checked')?.value === 'full';
}

// ===== 启用开关 =====

export async function loadEnabled() {
    const data = await apiCall('/orchestrator/enabled');
    if (data && data.success) {
        rootEl.querySelector('#orchestrator-enabled').checked = data.enabled;
        updateStatusDisplay(data.enabled);
    }
}

async function toggleEnabled() {
    const checkbox = rootEl.querySelector('#orchestrator-enabled');
    const enabled = checkbox.checked;

    const result = await apiCall('/orchestrator/enabled', 'PUT', { enabled });
    if (result && result.success) {
        updateStatusDisplay(enabled);
        showToast(enabled ? '消息编排器已启用' : '消息编排器已禁用', 'success');
    } else {
        checkbox.checked = !enabled;
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

function updateStatusDisplay(enabled) {
    rootEl.querySelector('#orchestrator-status').innerHTML = enabled
        ? '<span style="color: var(--success);">✅ 已启用，-memory/-record 模式将使用编排序列</span>'
        : '<span class="text-dim">⬜ 已禁用，使用传统上下文注入方式</span>';
}

// ===== 序列管理 =====

export async function loadSequence() {
    const container = rootEl.querySelector('#orchestrator-sequence');
    container.innerHTML = spinnerHtml();

    const data = await apiCall('/orchestrator/sequence');
    if (data && data.success) {
        state.sequence = data.sequence || [];
        state.availableComponents = data.available_components || [];
        state.activePreset = data.active_preset || 'default';

        renderSequence();
        renderComponentPalette();
        initSortable();
        updatePreview(isFullPreview());
    } else {
        container.innerHTML = `<p style="color: var(--danger);">加载失败: ${escapeHtml(data?.error || '未知错误')}</p>`;
    }
}

export function renderSequence() {
    const container = rootEl.querySelector('#orchestrator-sequence');
    const sequence = state.sequence;

    if (sequence.length === 0) {
        container.innerHTML = '<p class="text-dim">序列为空</p>';
        return;
    }

    let html = '';
    sequence.forEach((item, idx) => {
        const icon = getComponentIcon(item.type);
        const label = getComponentLabel(item.type);
        const isEditable = isComponentEditable(item.type);
        const isDeletable = isComponentDeletable(item.type) && !item.locked;
        const isLocked = item.locked;
        const desc = getComponentDescription(item.type);
        const idAttr = escapeAttr(item.id);

        let previewText = '';
        if (item.type === 'conditional_mount') {
            const matchInfo = item.match_mode === 'list'
                ? `列表: ${(item.model_list || []).slice(0, 3).join(', ')}${(item.model_list || []).length > 3 ? '...' : ''}`
                : `正则: ${item.model_pattern || '(未设置)'}`;
            previewText = `[${item.mount_title || '未命名'}] ${matchInfo}`;
        } else if (item.content) {
            previewText = item.content.substring(0, 60) + (item.content.length > 60 ? '...' : '');
        } else if (desc && !isEditable) {
            previewText = desc;
        }

        html += `
        <div class="sequence-item ${isLocked ? 'locked' : ''} ${item.enabled === false ? 'disabled' : ''}"
             data-id="${idAttr}" data-index="${idx}">
            <span class="drag-handle">${isLocked ? '🔒' : '☰'}</span>
            <span class="item-icon">${icon}</span>
            <div class="item-content">
                <span class="item-label">${escapeHtml(label)}</span>
                ${previewText ? `<div class="item-preview">${escapeHtml(previewText, true)}</div>` : ''}
                ${item.inject_mode && isEditable ? `<span class="inject-mode-badge">${escapeHtml(item.inject_mode)}</span>` : ''}
            </div>
            <div class="item-actions">
                ${!isLocked && isEditable ? `<button class="btn btn-sm" data-action="edit-item" data-id="${idAttr}" title="编辑">✏️</button>` : ''}
                ${isDeletable ? `<button class="btn btn-sm btn-danger" data-action="delete-item" data-id="${idAttr}" title="删除">🗑️</button>` : ''}
                <button class="btn btn-sm" data-action="toggle-item" data-id="${idAttr}" title="${item.enabled !== false ? '禁用' : '启用'}">
                    ${item.enabled !== false ? '✅' : '⬜'}
                </button>
            </div>
        </div>`;
    });

    container.innerHTML = html;
}

function renderComponentPalette() {
    const container = rootEl.querySelector('#component-palette');
    let html = '';
    state.availableComponents.forEach((comp) => {
        html += `
        <button class="component-btn" data-action="add-component" data-type="${escapeAttr(comp.type)}" title="${escapeAttr(comp.description || '')}">
            ${escapeHtml(comp.icon)} ${escapeHtml(comp.name)}
        </button>`;
    });
    container.innerHTML = html;
}

export function initSortable() {
    const container = rootEl.querySelector('#orchestrator-sequence');

    if (state.sortableInstance) {
        state.sortableInstance.destroy();
        state.sortableInstance = null;
    }
    if (typeof Sortable === 'undefined') {
        console.warn('[Orchestrator] Sortable.js 未加载');
        return;
    }

    state.sortableInstance = new Sortable(container, {
        animation: 150,
        handle: '.drag-handle',
        filter: '.locked',
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        dragClass: 'sortable-drag',
        onEnd(evt) {
            const item = state.sequence.splice(evt.oldIndex, 1)[0];
            state.sequence.splice(evt.newIndex, 0, item);
            saveSequence('拖拽排序');
            updatePreview(isFullPreview());
        },
    });
}

function addComponent(type) {
    const component = state.availableComponents.find((c) => c.type === type);
    if (!component) return;

    const newItem = {
        id: `${type}_${Date.now()}`,
        type,
        content: type.startsWith('fake_') || type === 'custom_block' || type === 'conditional_mount' ? '' : undefined,
        inject_mode: 'standalone_user',
        enabled: true,
    };
    if (type === 'conditional_mount') {
        newItem.match_mode = 'regex';
        newItem.model_pattern = '';
        newItem.model_list = [];
        newItem.mount_title = '';
    }

    // 插入到 real_messages 之前
    const realMsgIdx = state.sequence.findIndex((s) => s.type === 'real_messages');
    if (realMsgIdx > 0) {
        state.sequence.splice(realMsgIdx, 0, newItem);
    } else {
        state.sequence.push(newItem);
    }

    renderSequence();
    initSortable();

    if (component.editable) {
        editSequenceItem(newItem.id);
    } else {
        saveSequence(`添加 ${component.name}`);
        updatePreview(isFullPreview());
    }
}

export async function saveSequence(description = '更新序列') {
    const result = await apiCall('/orchestrator/sequence', 'PUT', {
        sequence: state.sequence,
        description,
    });
    if (result && result.success) {
        showToast('序列已保存', 'success');
        document.dispatchEvent(new CustomEvent('orchestrator:sequence-saved'));
    } else {
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

// ===== 编辑弹窗 =====

function editSequenceItem(id) {
    const item = state.sequence.find((s) => s.id === id);
    if (!item) return;

    if (item.type === 'conditional_mount') {
        editConditionalMountItem(item);
        return;
    }

    const label = getComponentLabel(item.type);
    const icon = getComponentIcon(item.type);

    const modal = showModal(`${icon} 编辑 ${escapeHtml(label)}`, `
        <div class="form-group">
            <label>内容</label>
            <textarea id="edit-item-content" rows="15" style="min-height: 350px; font-size: 14px;" placeholder="输入消息内容...">${escapeHtml(item.content || '')}</textarea>
        </div>
        <div class="form-group">
            <label>注入模式</label>
            <select id="edit-item-inject-mode">
                <option value="standalone_user" ${item.inject_mode === 'standalone_user' ? 'selected' : ''}>独立 User 消息</option>
                <option value="standalone_assistant" ${item.inject_mode === 'standalone_assistant' ? 'selected' : ''}>独立 Assistant 消息</option>
                <option value="append_to_system" ${item.inject_mode === 'append_to_system' ? 'selected' : ''}>追加到 System</option>
            </select>
            <small class="text-dim">💡 提示：对于 cache_break 组件，建议使用 "独立 Assistant 消息"</small>
        </div>
    `, {
        size: 'large',
        footer: `
            <button class="btn" data-modal-close>取消</button>
            <button class="btn btn-success" data-act="save">💾 保存</button>
        `,
    });

    modal.querySelector('#edit-item-content').focus();
    modal.querySelector('[data-act="save"]').addEventListener('click', () => {
        item.content = modal.querySelector('#edit-item-content').value;
        item.inject_mode = modal.querySelector('#edit-item-inject-mode').value;
        closeModal();
        renderSequence();
        initSortable();
        saveSequence(`编辑 ${getComponentLabel(item.type)}`);
        updatePreview(isFullPreview());
    });
}

function editConditionalMountItem(item) {
    const label = getComponentLabel(item.type);
    const icon = getComponentIcon(item.type);
    const modelListText = (item.model_list || []).join('\n');

    const modal = showModal(`${icon} 编辑 ${escapeHtml(label)}`, `
        <div class="alert alert-info" style="margin-bottom: 15px;">
            <span>💡</span>
            <div>
                条件挂载仅对匹配的模型生效。支持两种匹配模式：<br>
                <strong>正则模式</strong>：使用正则表达式或通配符（如 <code>claude-*</code>）<br>
                <strong>列表模式</strong>：直接列出模型名称（每行一个）
            </div>
        </div>
        <div class="form-group">
            <label>挂载标题（显示在内容前）</label>
            <input type="text" id="edit-mount-title" value="${escapeAttr(item.mount_title || '')}" placeholder="例如：Claude 专用提示">
        </div>
        <div class="form-group">
            <label>匹配模式</label>
            <select id="edit-match-mode">
                <option value="regex" ${item.match_mode !== 'list' ? 'selected' : ''}>正则/通配符模式</option>
                <option value="list" ${item.match_mode === 'list' ? 'selected' : ''}>模型列表模式</option>
            </select>
        </div>
        <div id="regex-mode-input" class="form-group" style="${item.match_mode === 'list' ? 'display: none;' : ''}">
            <label>模型匹配正则/通配符</label>
            <input type="text" id="edit-model-pattern" value="${escapeAttr(item.model_pattern || '')}" placeholder="例如：claude-* 或 .*sonnet.*">
            <small class="text-dim">支持 * 通配符（匹配任意字符）或完整正则表达式</small>
        </div>
        <div id="list-mode-input" class="form-group" style="${item.match_mode !== 'list' ? 'display: none;' : ''}">
            <label>模型列表（每行一个）</label>
            <textarea id="edit-model-list" rows="4" placeholder="claude-sonnet-4&#10;claude-opus-4&#10;gemini-2.0-flash">${escapeHtml(modelListText)}</textarea>
            <small class="text-dim">精确匹配模型名称，忽略大小写</small>
        </div>
        <div class="form-group">
            <label>挂载内容</label>
            <textarea id="edit-item-content" rows="12" style="min-height: 250px; font-size: 14px;" placeholder="输入要挂载的内容...">${escapeHtml(item.content || '')}</textarea>
        </div>
        <div class="form-group">
            <label>注入模式</label>
            <select id="edit-item-inject-mode">
                <option value="standalone_user" ${item.inject_mode === 'standalone_user' ? 'selected' : ''}>独立 User 消息</option>
                <option value="standalone_assistant" ${item.inject_mode === 'standalone_assistant' ? 'selected' : ''}>独立 Assistant 消息</option>
            </select>
        </div>
    `, {
        size: 'large',
        footer: `
            <button class="btn" data-modal-close>取消</button>
            <button class="btn btn-success" data-act="save">💾 保存</button>
        `,
    });

    modal.querySelector('#edit-mount-title').focus();
    modal.querySelector('#edit-match-mode').addEventListener('change', (e) => {
        const isList = e.target.value === 'list';
        modal.querySelector('#regex-mode-input').style.display = isList ? 'none' : '';
        modal.querySelector('#list-mode-input').style.display = isList ? '' : 'none';
    });

    modal.querySelector('[data-act="save"]').addEventListener('click', () => {
        item.mount_title = modal.querySelector('#edit-mount-title').value.trim();
        item.match_mode = modal.querySelector('#edit-match-mode').value;
        item.model_pattern = modal.querySelector('#edit-model-pattern').value.trim();
        item.model_list = modal.querySelector('#edit-model-list').value
            .split('\n').map((s) => s.trim()).filter((s) => s.length > 0);
        item.content = modal.querySelector('#edit-item-content').value;
        item.inject_mode = modal.querySelector('#edit-item-inject-mode').value;

        closeModal();
        renderSequence();
        initSortable();
        saveSequence(`编辑条件挂载: ${item.mount_title || '未命名'}`);
        updatePreview(isFullPreview());
    });
}

async function deleteSequenceItem(id) {
    const item = state.sequence.find((s) => s.id === id);
    if (!item) return;

    const ok = await confirmDialog(`确定删除 "${getComponentLabel(item.type)}"？`, { danger: true, okText: '删除' });
    if (!ok) return;

    state.sequence = state.sequence.filter((s) => s.id !== id);
    renderSequence();
    initSortable();
    saveSequence(`删除 ${getComponentLabel(item.type)}`);
    updatePreview(isFullPreview());
}

function toggleItemEnabled(id) {
    const item = state.sequence.find((s) => s.id === id);
    if (!item) return;

    item.enabled = !(item.enabled !== false);
    renderSequence();
    initSortable();
    saveSequence(`${item.enabled ? '启用' : '禁用'} ${getComponentLabel(item.type)}`);
    updatePreview(isFullPreview());
}

// ===== 预览 =====

function getPreviewTestMessages() {
    const messages = [];
    const systemVal = rootEl.querySelector('#preview-system-content').value.trim();
    const userVal = rootEl.querySelector('#preview-user-content').value.trim();
    if (systemVal) messages.push({ role: 'system', content: systemVal });
    if (userVal) messages.push({ role: 'user', content: userVal });
    return messages;
}

function clearPreviewInputs() {
    rootEl.querySelector('#preview-system-content').value = '';
    rootEl.querySelector('#preview-user-content').value = '';
    updatePreview(isFullPreview());
}

export async function updatePreview(fullPreview = false) {
    const container = rootEl.querySelector('#orchestrator-preview');
    container.innerHTML = spinnerHtml('生成预览...');

    const result = await apiCall('/orchestrator/preview', 'POST', {
        test_messages: getPreviewTestMessages(),
        full_preview: fullPreview,
    });

    if (!result || !result.success) {
        container.innerHTML = `<p style="color: var(--danger);">预览失败: ${escapeHtml(result?.error || '未知错误')}</p>`;
        return;
    }

    let html = `
    <div class="preview-stats">
        <span>📊 ${result.orchestrated_count} 条消息</span>
        <span>📝 ${result.total_chars} 字符</span>
        <span>🎯 ~${result.estimated_tokens} tokens</span>
    </div>
    <div class="preview-list">`;

    if (result.messages.length === 0) {
        html += '<p class="text-dim" style="padding: 10px;">（无消息，请在上方输入测试内容或启用完整预览）</p>';
    } else {
        for (const msg of result.messages) {
            const sourceLabel = getSourceLabel(msg.source);
            const isExpandable = msg.char_count > 200;
            html += `
            <div class="preview-msg ${msg.role}">
                <div class="preview-msg-header">
                    <span class="msg-index">[${msg.index}]</span>
                    <span class="msg-role">${escapeHtml(msg.role)}</span>
                    <span class="msg-source">${escapeHtml(sourceLabel)}</span>
                    <span class="msg-chars">${msg.char_count} 字符</span>
                </div>
                <div class="preview-msg-content ${isExpandable && !fullPreview ? 'collapsed' : ''}">
                    ${escapeHtml(msg.preview, true)}
                </div>
                ${isExpandable && !fullPreview ? '<button class="btn btn-sm" data-action="toggle-msg">展开/收起</button>' : ''}
            </div>`;
        }
    }
    html += '</div>';
    container.innerHTML = html;
}

// ===== 组件元数据 =====

export function getComponentIcon(type) {
    const icons = {
        system_prompt: '📋', fake_user: '👤', fake_assistant: '🤖',
        prefix_mount: '📎', time_context: '📅', memory_range: '📊',
        layered_memory: '📖', dynamic_search: '🔍', tools_hint: '🔧',
        suffix_mount: '📎', custom_block: '📝', real_messages: '💬',
        cache_break: '✂️', volatile_context: '⏰', pending_memory: '🗒️',
        conditional_mount: '🎯',
    };
    return icons[type] || '❓';
}

export function getComponentLabel(type) {
    const labels = {
        system_prompt: 'System Prompt',
        fake_user: '伪造 User 消息',
        fake_assistant: '伪造 Assistant 消息',
        prefix_mount: '前置挂载 (prefix.md)',
        time_context: '时间上下文',
        memory_range: '记忆库范围',
        layered_memory: '分层记忆',
        dynamic_search: '动态检索结果',
        tools_hint: '工具调用提示',
        suffix_mount: '后置挂载 (suffix.md)',
        custom_block: '自定义文本块',
        real_messages: '真实对话历史',
        cache_break: '缓存分隔点',
        volatile_context: '易变上下文 (时间+pending)',
        pending_memory: '待归档记忆',
        conditional_mount: '条件额外挂载',
    };
    return labels[type] || type;
}

function isComponentEditable(type) {
    return ['fake_user', 'fake_assistant', 'custom_block', 'cache_break', 'conditional_mount'].includes(type);
}

function isComponentDeletable(type) {
    return !['system_prompt', 'real_messages'].includes(type);
}

function getSourceLabel(source) {
    const labels = {
        fake: '伪造', layered_memory: '记忆', dynamic_search: '检索',
        prefix_mount: '前置', suffix_mount: '后置', custom: '自定义',
        real: '真实', original: '原始', cache_break: '分隔',
        volatile_context: '易变', pending_memory: 'pending',
        time_context: '时间', memory_range: '范围', tools_hint: '工具',
        system: 'system', merged: '合并', conditional_mount: '条件挂载',
    };
    return labels[source] || source;
}

function getComponentDescription(type) {
    const descriptions = {
        system_prompt: '客户端发来的角色设定',
        prefix_mount: 'prefix.md 文件内容（稳定，可缓存）',
        memory_range: '记忆库日期范围和统计（相对稳定）',
        layered_memory: '日记/周总结/月总结/季度总结（稳定，可缓存）',
        dynamic_search: 'Agent 检索到的相关记忆',
        tools_hint: '给主模型的工具调用说明',
        suffix_mount: 'suffix.md 文件内容（稳定，可缓存）',
        cache_break: '伪造 assistant 确认，打断消息合并',
        volatile_context: '当前时间 + 今日 pending（每次变化，不缓存）',
        time_context: '当前日期、时间、周数等（每次变化）',
        pending_memory: '今日待归档记录（经常变化）',
        real_messages: '用户实际的对话历史',
        fake_user: '伪装的用户消息',
        fake_assistant: '伪装的 AI 回复',
        custom_block: '自定义文本内容',
        conditional_mount: '仅对匹配模型生效的额外挂载',
    };
    return descriptions[type] || '';
}

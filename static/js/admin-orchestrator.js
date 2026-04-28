/**
 * 消息编排器 (Message Orchestrator) 管理模块
 * 
 * 功能：
 * - 拖拽排序消息组件
 * - 预设管理（保存/加载/删除）
 * - 模型绑定配置
 * - 导入/导出配置
 * - 历史回滚
 * - 测试发送
 * - 完整预览
 */

// ==================== 全局状态 ====================

let orchestratorState = {
    sequence: [],
    availableComponents: [],
    presets: [],
    activePreset: 'default',
    bindings: {},
    history: [],
    sortableInstance: null
};

// ==================== 页面初始化 ====================

async function loadOrchestratorPage() {
    await Promise.all([
        loadOrchestratorEnabled(),
        loadOrchestratorSequence(),
        loadOrchestratorPresets(),
        loadOrchestratorBindings(),
        loadOrchestratorHistory(),
        loadPrefillConfig()
    ]);
}

// ==================== 启用开关 ====================

async function loadOrchestratorEnabled() {
    try {
        const data = await apiCall('/orchestrator/enabled');
        if (data.success) {
            const checkbox = document.getElementById('orchestrator-enabled');
            if (checkbox) {
                checkbox.checked = data.enabled;
            }
            updateOrchestratorStatusDisplay(data.enabled);
        }
    } catch (e) {
        console.error('加载编排器启用状态失败:', e);
    }
}

async function toggleOrchestratorEnabled() {
    const checkbox = document.getElementById('orchestrator-enabled');
    const enabled = checkbox ? checkbox.checked : false;
    
    try {
        const result = await apiCall('/orchestrator/enabled', 'PUT', { enabled });
        if (result.success) {
            updateOrchestratorStatusDisplay(enabled);
            showToast(enabled ? '消息编排器已启用' : '消息编排器已禁用', 'success');
        } else {
            // 恢复原状态
            if (checkbox) checkbox.checked = !enabled;
            showToast('保存失败: ' + result.error, 'error');
        }
    } catch (e) {
        if (checkbox) checkbox.checked = !enabled;
        showToast('保存失败: ' + e.message, 'error');
    }
}

function updateOrchestratorStatusDisplay(enabled) {
    const statusEl = document.getElementById('orchestrator-status');
    if (statusEl) {
        if (enabled) {
            statusEl.innerHTML = '<span style="color: var(--success);">✅ 消息编排器已启用，-memory/-record 模式将使用编排序列</span>';
        } else {
            statusEl.innerHTML = '<span style="color: var(--text-dim);">⬜ 消息编排器已禁用，使用传统上下文注入方式</span>';
        }
    }
}

// ==================== 序列管理 ====================

async function loadOrchestratorSequence() {
    const container = document.getElementById('orchestrator-sequence');
    if (!container) return;
    
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    try {
        const data = await apiCall('/orchestrator/sequence');
        
        if (data.success) {
            orchestratorState.sequence = data.sequence || [];
            orchestratorState.availableComponents = data.available_components || [];
            orchestratorState.activePreset = data.active_preset || 'default';
            
            renderSequence();
            renderComponentPalette();
            initSortable();
            updatePreview();
        } else {
            container.innerHTML = `<p class="error">加载失败: ${data.error}</p>`;
        }
    } catch (e) {
        container.innerHTML = `<p class="error">加载失败: ${e.message}</p>`;
    }
}

function renderSequence() {
    const container = document.getElementById('orchestrator-sequence');
    if (!container) return;
    
    const sequence = orchestratorState.sequence;
    
    if (sequence.length === 0) {
        container.innerHTML = '<p style="color: var(--text-dim);">序列为空</p>';
        return;
    }
    
    let html = '';
    sequence.forEach((item, idx) => {
        const icon = getComponentIcon(item.type);
        const label = getComponentLabel(item.type);
        const isEditable = isComponentEditable(item.type);
        const isDeletable = isComponentDeletable(item.type) && !item.locked;
        const isLocked = item.locked;
        
        // 获取组件描述（用于非编辑组件）
        const desc = getComponentDescription(item.type);
        
        // 显示内容或描述
        let previewText = '';
        if (item.type === 'conditional_mount') {
            // 条件挂载显示特殊信息
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
             data-id="${escapeAttrValue(item.id)}"
             data-index="${idx}">
            <span class="drag-handle">${isLocked ? '🔒' : '☰'}</span>
            <span class="item-icon">${icon}</span>
            <div class="item-content">
                <span class="item-label">${escapeHtml(label)}</span>
                ${previewText ? `<div class="item-preview">${escapeHtml(previewText, true)}</div>` : ''}
                ${item.inject_mode && isEditable ? `<span class="inject-mode-badge">${escapeHtml(item.inject_mode)}</span>` : ''}
            </div>
            <div class="item-actions">
                ${!isLocked && isEditable ? `<button class="btn btn-sm" onclick="editSequenceItem('${escapeAttr(item.id)}')" title="编辑">✏️</button>` : ''}
                ${isDeletable ? `<button class="btn btn-sm btn-danger" onclick="deleteSequenceItem('${escapeAttr(item.id)}')" title="删除">🗑️</button>` : ''}
                <button class="btn btn-sm" onclick="toggleItemEnabled('${escapeAttr(item.id)}')" title="${item.enabled !== false ? '禁用' : '启用'}">
                    ${item.enabled !== false ? '✅' : '⬜'}
                </button>
            </div>
        </div>`;
    });
    
    container.innerHTML = html;
}

function renderComponentPalette() {
    const container = document.getElementById('component-palette');
    if (!container) return;
    
    const components = orchestratorState.availableComponents;
    
    let html = '';
    components.forEach(comp => {
        html += `
        <button class="component-btn" onclick="addComponent('${escapeAttr(comp.type)}')" title="${escapeAttrValue(comp.description || '')}">
            ${escapeHtml(comp.icon)} ${escapeHtml(comp.name)}
        </button>`;
    });
    
    container.innerHTML = html;
}

function initSortable() {
    const container = document.getElementById('orchestrator-sequence');
    if (!container) return;
    
    // 如果已有实例，先销毁
    if (orchestratorState.sortableInstance) {
        orchestratorState.sortableInstance.destroy();
    }
    
    // 检查 Sortable 是否可用
    if (typeof Sortable === 'undefined') {
        console.warn('[Orchestrator] Sortable.js 未加载');
        return;
    }
    
    orchestratorState.sortableInstance = new Sortable(container, {
        animation: 150,
        handle: '.drag-handle',
        filter: '.locked',
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        dragClass: 'sortable-drag',
        onEnd: function(evt) {
            // 重新排序数组
            const item = orchestratorState.sequence.splice(evt.oldIndex, 1)[0];
            orchestratorState.sequence.splice(evt.newIndex, 0, item);
            saveSequence('拖拽排序');
            updatePreview();
        }
    });
}

function addComponent(type) {
    const component = orchestratorState.availableComponents.find(c => c.type === type);
    if (!component) return;
    
    const newItem = {
        id: `${type}_${Date.now()}`,
        type: type,
        content: type.startsWith('fake_') || type === 'custom_block' || type === 'conditional_mount' ? '' : undefined,
        inject_mode: 'standalone_user',
        enabled: true
    };
    
    // 条件挂载需要额外的字段
    if (type === 'conditional_mount') {
        newItem.match_mode = 'regex';
        newItem.model_pattern = '';
        newItem.model_list = [];
        newItem.mount_title = '';
    }
    
    // 插入到 real_messages 之前
    const realMsgIdx = orchestratorState.sequence.findIndex(s => s.type === 'real_messages');
    if (realMsgIdx > 0) {
        orchestratorState.sequence.splice(realMsgIdx, 0, newItem);
    } else {
        orchestratorState.sequence.push(newItem);
    }
    
    renderSequence();
    initSortable();
    
    // 如果是可编辑的，立即打开编辑
    if (component.editable) {
        editSequenceItem(newItem.id);
    } else {
        saveSequence(`添加 ${component.name}`);
        updatePreview();
    }
}

function editSequenceItem(id) {
    const item = orchestratorState.sequence.find(s => s.id === id);
    if (!item) return;
    
    const label = getComponentLabel(item.type);
    const icon = getComponentIcon(item.type);
    
    // 条件挂载使用特殊的编辑界面
    if (item.type === 'conditional_mount') {
        editConditionalMountItem(id, item);
        return;
    }
    
    // 使用统一的 showModal 函数（添加 wide 类让弹窗更宽）
    showModal(`${icon} 编辑 ${escapeHtml(label)}`, `
        <div class="form-group">
            <label class="form-label">内容</label>
            <textarea id="edit-item-content" class="form-input" rows="15" style="min-height: 350px; font-size: 14px;" placeholder="输入消息内容...">${escapeHtml(item.content || '')}</textarea>
        </div>
        <div class="form-group">
            <label class="form-label">注入模式</label>
            <select id="edit-item-inject-mode" class="form-select">
                <option value="standalone_user" ${item.inject_mode === 'standalone_user' ? 'selected' : ''}>独立 User 消息</option>
                <option value="standalone_assistant" ${item.inject_mode === 'standalone_assistant' ? 'selected' : ''}>独立 Assistant 消息</option>
                <option value="append_to_system" ${item.inject_mode === 'append_to_system' ? 'selected' : ''}>追加到 System</option>
            </select>
            <div class="form-hint" style="margin-top: 8px;">
                💡 提示：对于 cache_break 组件，建议使用 "独立 Assistant 消息"
            </div>
        </div>
        <div style="margin-top: 15px; text-align: right;">
            <button class="btn" onclick="closeModal()">取消</button>
            <button class="btn btn-success" onclick="saveEditedItem('${escapeAttr(id)}')" style="margin-left: 10px;">💾 保存</button>
        </div>
    `, 'wide');
    
    // 聚焦到内容输入框
    setTimeout(() => {
        const textarea = document.getElementById('edit-item-content');
        if (textarea) textarea.focus();
    }, 100);
}

/**
 * 编辑条件挂载组件
 */
function editConditionalMountItem(id, item) {
    const label = getComponentLabel(item.type);
    const icon = getComponentIcon(item.type);
    
    // 将 model_list 转为换行分隔的文本
    const modelListText = (item.model_list || []).join('\n');
    
    showModal(`${icon} 编辑 ${escapeHtml(label)}`, `
        <div class="alert alert-info" style="margin-bottom: 15px;">
            <span>💡</span>
            <div>
                条件挂载仅对匹配的模型生效。支持两种匹配模式：<br>
                <strong>正则模式</strong>：使用正则表达式或通配符（如 <code>claude-*</code>）<br>
                <strong>列表模式</strong>：直接列出模型名称（每行一个）
            </div>
        </div>
        
        <div class="form-group">
            <label class="form-label">挂载标题（显示在内容前）</label>
            <input type="text" id="edit-mount-title" class="form-input" value="${escapeAttrValue(item.mount_title || '')}" placeholder="例如：Claude 专用提示">
        </div>
        
        <div class="form-group">
            <label class="form-label">匹配模式</label>
            <select id="edit-match-mode" class="form-select" onchange="toggleMatchModeInputs()">
                <option value="regex" ${item.match_mode !== 'list' ? 'selected' : ''}>正则/通配符模式</option>
                <option value="list" ${item.match_mode === 'list' ? 'selected' : ''}>模型列表模式</option>
            </select>
        </div>
        
        <div id="regex-mode-input" class="form-group" style="${item.match_mode === 'list' ? 'display: none;' : ''}">
            <label class="form-label">模型匹配正则/通配符</label>
            <input type="text" id="edit-model-pattern" class="form-input" value="${escapeAttrValue(item.model_pattern || '')}" placeholder="例如：claude-* 或 .*sonnet.*">
            <div class="form-hint">支持 * 通配符（匹配任意字符）或完整正则表达式</div>
        </div>
        
        <div id="list-mode-input" class="form-group" style="${item.match_mode !== 'list' ? 'display: none;' : ''}">
            <label class="form-label">模型列表（每行一个）</label>
            <textarea id="edit-model-list" class="form-input" rows="4" placeholder="claude-sonnet-4&#10;claude-opus-4&#10;gemini-2.0-flash">${escapeHtml(modelListText)}</textarea>
            <div class="form-hint">精确匹配模型名称，忽略大小写</div>
        </div>
        
        <div class="form-group">
            <label class="form-label">挂载内容</label>
            <textarea id="edit-item-content" class="form-input" rows="12" style="min-height: 250px; font-size: 14px;" placeholder="输入要挂载的内容...">${escapeHtml(item.content || '')}</textarea>
        </div>
        
        <div class="form-group">
            <label class="form-label">注入模式</label>
            <select id="edit-item-inject-mode" class="form-select">
                <option value="standalone_user" ${item.inject_mode === 'standalone_user' ? 'selected' : ''}>独立 User 消息</option>
                <option value="standalone_assistant" ${item.inject_mode === 'standalone_assistant' ? 'selected' : ''}>独立 Assistant 消息</option>
            </select>
        </div>
        
        <div style="margin-top: 15px; text-align: right;">
            <button class="btn" onclick="closeModal()">取消</button>
            <button class="btn btn-success" onclick="saveConditionalMountItem('${escapeAttr(id)}')" style="margin-left: 10px;">💾 保存</button>
        </div>
    `, 'wide');
    
    // 聚焦到标题输入框
    setTimeout(() => {
        const input = document.getElementById('edit-mount-title');
        if (input) input.focus();
    }, 100);
}

/**
 * 切换匹配模式输入框显示
 */
function toggleMatchModeInputs() {
    const mode = document.getElementById('edit-match-mode').value;
    const regexInput = document.getElementById('regex-mode-input');
    const listInput = document.getElementById('list-mode-input');
    
    if (mode === 'list') {
        regexInput.style.display = 'none';
        listInput.style.display = 'block';
    } else {
        regexInput.style.display = 'block';
        listInput.style.display = 'none';
    }
}

/**
 * 保存条件挂载组件
 */
function saveConditionalMountItem(id) {
    const item = orchestratorState.sequence.find(s => s.id === id);
    if (!item) return;
    
    const mountTitle = document.getElementById('edit-mount-title').value.trim();
    const matchMode = document.getElementById('edit-match-mode').value;
    const modelPattern = document.getElementById('edit-model-pattern').value.trim();
    const modelListText = document.getElementById('edit-model-list').value;
    const content = document.getElementById('edit-item-content').value;
    const injectMode = document.getElementById('edit-item-inject-mode').value;
    
    // 将换行分隔的文本转为数组
    const modelList = modelListText.split('\n')
        .map(s => s.trim())
        .filter(s => s.length > 0);
    
    // 更新组件
    item.mount_title = mountTitle;
    item.match_mode = matchMode;
    item.model_pattern = modelPattern;
    item.model_list = modelList;
    item.content = content;
    item.inject_mode = injectMode;
    
    closeModal();
    renderSequence();
    initSortable();
    saveSequence(`编辑条件挂载: ${mountTitle || '未命名'}`);
    updatePreview();
}

function saveEditedItem(id) {
    const item = orchestratorState.sequence.find(s => s.id === id);
    if (!item) return;
    
    const content = document.getElementById('edit-item-content').value;
    const injectMode = document.getElementById('edit-item-inject-mode').value;
    
    item.content = content;
    item.inject_mode = injectMode;
    
    closeModal();
    renderSequence();
    initSortable();
    saveSequence(`编辑 ${getComponentLabel(item.type)}`);
    updatePreview();
}

function deleteSequenceItem(id) {
    const item = orchestratorState.sequence.find(s => s.id === id);
    if (!item) return;
    
    if (!confirm(`确定删除 "${getComponentLabel(item.type)}"？`)) return;
    
    orchestratorState.sequence = orchestratorState.sequence.filter(s => s.id !== id);
    renderSequence();
    initSortable();
    saveSequence(`删除 ${getComponentLabel(item.type)}`);
    updatePreview();
}

function toggleItemEnabled(id) {
    const item = orchestratorState.sequence.find(s => s.id === id);
    if (!item) return;
    
    item.enabled = !(item.enabled !== false);
    renderSequence();
    initSortable();
    saveSequence(`${item.enabled ? '启用' : '禁用'} ${getComponentLabel(item.type)}`);
    updatePreview();
}

async function saveSequence(description = '更新序列') {
    try {
        const result = await apiCall('/orchestrator/sequence', 'PUT', {
            sequence: orchestratorState.sequence,
            description: description
        });
        
        if (result.success) {
            showToast('序列已保存', 'success');
            // 刷新历史
            loadOrchestratorHistory();
        } else {
            showToast('保存失败: ' + result.error, 'error');
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

// ==================== 预览 ====================

// 预览用的测试消息（可编辑）
let previewTestMessages = [];

function getPreviewTestMessages() {
    // 从输入框读取，如果有的话
    const systemInput = document.getElementById('preview-system-content');
    const userInput = document.getElementById('preview-user-content');
    
    const messages = [];
    
    if (systemInput && systemInput.value.trim()) {
        messages.push({ role: 'system', content: systemInput.value.trim() });
    }
    
    if (userInput && userInput.value.trim()) {
        messages.push({ role: 'user', content: userInput.value.trim() });
    }
    
    return messages;
}

async function updatePreview(fullPreview = false) {
    const container = document.getElementById('orchestrator-preview');
    if (!container) return;
    
    // 保留测试消息输入区域
    const inputArea = document.getElementById('preview-input-area');
    const inputHtml = inputArea ? inputArea.outerHTML : renderPreviewInputArea();
    
    container.innerHTML = inputHtml + '<div class="loading"><span class="spinner"></span> 生成预览...</div>';
    
    try {
        const testMessages = getPreviewTestMessages();
        
        const result = await apiCall('/orchestrator/preview', 'POST', {
            test_messages: testMessages,
            full_preview: fullPreview
        });
        
        if (result.success) {
            renderPreview(result, fullPreview);
        } else {
            container.innerHTML = inputHtml + `<p class="error">预览失败: ${result.error}</p>`;
        }
    } catch (e) {
        container.innerHTML = inputHtml + `<p class="error">预览失败: ${e.message}</p>`;
    }
}

function renderPreviewInputArea() {
    return `
    <div id="preview-input-area" class="preview-input-area" style="margin-bottom: 15px; padding: 10px; background: var(--bg-secondary); border-radius: 8px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 500;">📝 测试消息（可选，留空则仅显示编排结构）</span>
            <button class="btn btn-sm" onclick="clearPreviewInputs()" title="清空">🗑️ 清空</button>
        </div>
        <div style="display: flex; flex-direction: column; gap: 8px;">
            <div>
                <label style="font-size: 12px; color: var(--text-dim);">System（可选）</label>
                <input type="text" id="preview-system-content" class="form-input" placeholder="留空则不添加 system 消息" style="font-size: 13px;">
            </div>
            <div>
                <label style="font-size: 12px; color: var(--text-dim);">User（可选）</label>
                <input type="text" id="preview-user-content" class="form-input" placeholder="留空则不添加 user 消息" style="font-size: 13px;">
            </div>
        </div>
    </div>`;
}

function clearPreviewInputs() {
    const systemInput = document.getElementById('preview-system-content');
    const userInput = document.getElementById('preview-user-content');
    if (systemInput) systemInput.value = '';
    if (userInput) userInput.value = '';
    updatePreview();
}

function renderPreview(data, fullPreview) {
    const container = document.getElementById('orchestrator-preview');
    if (!container) return;
    
    // 保留输入区域
    let html = renderPreviewInputArea();
    
    html += `
    <div class="preview-stats">
        <span>📊 ${data.orchestrated_count} 条消息</span>
        <span>📝 ${data.total_chars} 字符</span>
        <span>🎯 ~${data.estimated_tokens} tokens</span>
    </div>
    <div class="preview-list">`;
    
    if (data.messages.length === 0) {
        html += '<p style="color: var(--text-dim); padding: 10px;">（无消息，请在上方输入测试内容或启用完整预览）</p>';
    } else {
        data.messages.forEach(msg => {
            const roleClass = msg.role;
            const sourceLabel = getSourceLabel(msg.source);
            const isExpandable = msg.char_count > 200;
            
            html += `
            <div class="preview-msg ${roleClass}">
                <div class="preview-msg-header">
                    <span class="msg-index">[${msg.index}]</span>
                    <span class="msg-role">${msg.role}</span>
                    <span class="msg-source">${sourceLabel}</span>
                    <span class="msg-chars">${msg.char_count} 字符</span>
                </div>
                <div class="preview-msg-content ${isExpandable && !fullPreview ? 'collapsed' : ''}">
                    ${escapeHtml(msg.preview, true)}
                </div>
                ${isExpandable && !fullPreview ? '<button class="btn btn-sm" onclick="this.previousElementSibling.classList.toggle(\'collapsed\')">展开/收起</button>' : ''}
            </div>`;
        });
    }
    
    html += '</div>';
    
    // 添加预览模式切换
    html += `
    <div style="margin-top: 15px; display: flex; gap: 10px;">
        <label style="display: flex; align-items: center; gap: 5px;">
            <input type="radio" name="preview-mode" value="simple" ${!fullPreview ? 'checked' : ''} onchange="updatePreview(false)">
            结构预览
        </label>
        <label style="display: flex; align-items: center; gap: 5px;">
            <input type="radio" name="preview-mode" value="full" ${fullPreview ? 'checked' : ''} onchange="updatePreview(true)">
            完整预览（含实际记忆）
        </label>
        <button class="btn btn-sm" onclick="updatePreview(document.querySelector('input[name=preview-mode]:checked').value === 'full')" style="margin-left: auto;">🔄 刷新预览</button>
    </div>`;
    
    container.innerHTML = html;
}

// ==================== 预设管理 ====================

async function loadOrchestratorPresets() {
    const container = document.getElementById('orchestrator-presets');
    if (!container) return;
    
    try {
        const data = await apiCall('/orchestrator/presets');
        
        if (data.success) {
            orchestratorState.presets = data.presets || [];
            orchestratorState.activePreset = data.active_preset || 'default';
            renderPresets();
        }
    } catch (e) {
        console.error('加载预设失败:', e);
    }
}

function renderPresets() {
    const container = document.getElementById('orchestrator-presets');
    if (!container) return;
    
    const presets = orchestratorState.presets;
    const active = orchestratorState.activePreset;
    
    let html = `
    <div class="preset-selector">
        <select id="preset-select" class="form-select" style="flex: 1;" onchange="onPresetSelect(this.value)">
            ${presets.map(p => `<option value="${escapeAttrValue(p.id)}" ${p.id === active ? 'selected' : ''}>${escapeHtml(p.name)}</option>`).join('')}
        </select>
        <button class="btn btn-sm btn-success" onclick="showSavePresetDialog()">💾 保存为预设</button>
        <button class="btn btn-sm btn-danger" onclick="deleteCurrentPreset()">🗑️ 删除</button>
    </div>
    <div class="preset-list">`;
    
    presets.forEach(p => {
        html += `
        <div class="preset-item ${p.id === active ? 'active' : ''}" onclick="loadPreset('${escapeAttr(p.id)}')">
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
}

async function onPresetSelect(presetId) {
    await loadPreset(presetId);
}

async function loadPreset(presetId) {
    try {
        const result = await apiCall('/orchestrator/preset/load', 'POST', {
            preset_name: presetId
        });
        
        if (result.success) {
            orchestratorState.sequence = result.sequence || [];
            orchestratorState.activePreset = presetId;
            renderSequence();
            initSortable();
            renderPresets();
            updatePreview();
            showToast(result.message, 'success');
        } else {
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast('加载预设失败: ' + e.message, 'error');
    }
}

function showSavePresetDialog() {
    // 使用统一的 showModal 函数
    showModal('💾 保存预设', `
        <div class="form-group">
            <label class="form-label">预设ID（唯一标识）</label>
            <input type="text" id="new-preset-id" class="form-input" placeholder="my_preset" value="${escapeAttrValue(orchestratorState.activePreset)}">
        </div>
        <div class="form-group">
            <label class="form-label">预设名称</label>
            <input type="text" id="new-preset-name" class="form-input" placeholder="我的预设">
        </div>
        <div class="form-group">
            <label class="form-label">描述</label>
            <input type="text" id="new-preset-desc" class="form-input" placeholder="可选描述...">
        </div>
        <div style="margin-top: 15px; text-align: right;">
            <button class="btn" onclick="closeModal()">取消</button>
            <button class="btn btn-success" onclick="saveNewPreset()" style="margin-left: 10px;">💾 保存</button>
        </div>
    `);
    
    // 聚焦到名称输入框
    setTimeout(() => {
        const input = document.getElementById('new-preset-name');
        if (input) input.focus();
    }, 100);
}

async function saveNewPreset() {
    const presetId = document.getElementById('new-preset-id').value.trim();
    const name = document.getElementById('new-preset-name').value.trim();
    const description = document.getElementById('new-preset-desc').value.trim();
    
    if (!presetId || !name) {
        showToast('请填写预设ID和名称', 'error');
        return;
    }
    
    try {
        const result = await apiCall('/orchestrator/preset/save', 'POST', {
            preset_id: presetId,
            name: name,
            description: description
        });
        
        if (result.success) {
            closeModal();
            loadOrchestratorPresets();
            showToast(result.message, 'success');
        } else {
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

async function deleteCurrentPreset() {
    const active = orchestratorState.activePreset;
    
    if (active === 'default') {
        showToast('不能删除默认预设', 'error');
        return;
    }
    
    if (!confirm(`确定删除预设 "${active}"？`)) return;
    
    try {
        const result = await apiCall(`/orchestrator/preset/${active}`, 'DELETE');
        
        if (result.success) {
            loadOrchestratorPresets();
            loadOrchestratorSequence();
            showToast(result.message, 'success');
        } else {
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

// ==================== 模型绑定 ====================

async function loadOrchestratorBindings() {
    try {
        const data = await apiCall('/orchestrator/bindings');
        
        if (data.success) {
            orchestratorState.bindings = data.bindings || {};
            renderBindings(data.available_presets || []);
        }
    } catch (e) {
        console.error('加载模型绑定失败:', e);
    }
}

function renderBindings(availablePresets) {
    const container = document.getElementById('orchestrator-bindings');
    if (!container) return;
    
    const bindings = orchestratorState.bindings;
    
    let html = `
    <div class="bindings-list">
        <div class="bindings-header">
            <span>模型匹配模式</span>
            <span>使用预设</span>
            <span></span>
        </div>`;
    
    Object.entries(bindings).forEach(([pattern, preset]) => {
        html += `
        <div class="binding-row" data-pattern="${escapeAttrValue(pattern)}">
            <input type="text" class="form-input binding-pattern" value="${escapeAttrValue(pattern)}" placeholder="claude-*">
            <select class="form-select binding-preset">
                ${availablePresets.map(p => `<option value="${escapeAttrValue(p)}" ${p === preset ? 'selected' : ''}>${escapeHtml(p)}</option>`).join('')}
            </select>
            <button class="btn btn-sm btn-danger" onclick="removeBinding('${escapeAttr(pattern)}')">🗑️</button>
        </div>`;
    });
    
    html += `
    </div>
    <div style="margin-top: 10px; display: flex; gap: 10px;">
        <button class="btn btn-sm" onclick="addNewBinding()">➕ 添加规则</button>
        <button class="btn btn-sm btn-success" onclick="saveBindings()">💾 保存绑定</button>
    </div>
    <div class="form-hint" style="margin-top: 10px;">
        使用通配符匹配模型名称，如 <code>claude-*</code> 匹配所有 Claude 模型。<br>
        越靠前的规则优先级越高。
    </div>`;
    
    container.innerHTML = html;
}

function addNewBinding() {
    // 添加到本地状态，不重新从后端加载
    orchestratorState.bindings['new-pattern-' + Date.now()] = 'default';
    renderBindingsLocal();
}

function removeBinding(pattern) {
    delete orchestratorState.bindings[pattern];
    renderBindingsLocal();
}

function renderBindingsLocal() {
    // 使用本地状态重新渲染，不从后端加载
    const presets = orchestratorState.presets;
    const availablePresets = presets.map(p => p.id);
    if (!availablePresets.includes('default')) {
        availablePresets.unshift('default');
    }
    renderBindings(availablePresets);
}

async function saveBindings() {
    // 从 DOM 读取最新值
    const rows = document.querySelectorAll('.binding-row');
    const newBindings = {};
    
    rows.forEach(row => {
        const pattern = row.querySelector('.binding-pattern').value.trim();
        const preset = row.querySelector('.binding-preset').value;
        if (pattern) {
            newBindings[pattern] = preset;
        }
    });
    
    try {
        const result = await apiCall('/orchestrator/bindings', 'PUT', {
            bindings: newBindings
        });
        
        if (result.success) {
            orchestratorState.bindings = newBindings;
            showToast('模型绑定已保存', 'success');
        } else {
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

// ==================== 历史回滚 ====================

async function loadOrchestratorHistory() {
    const container = document.getElementById('orchestrator-history');
    if (!container) return;
    
    try {
        const data = await apiCall('/orchestrator/history');
        
        if (data.success) {
            orchestratorState.history = data.history || [];
            renderHistory();
        }
    } catch (e) {
        console.error('加载历史失败:', e);
    }
}

function renderHistory() {
    const container = document.getElementById('orchestrator-history');
    if (!container) return;
    
    const history = orchestratorState.history;
    
    if (history.length === 0) {
        container.innerHTML = '<p style="color: var(--text-dim);">暂无历史记录</p>';
        return;
    }
    
    let html = '<div class="history-list">';
    
    history.forEach((entry, idx) => {
        const time = new Date(entry.timestamp).toLocaleString('zh-CN');
        const actionIcons = {
            'update_sequence': '📝',
            'load_preset': '📂',
            'save_preset': '💾',
            'delete_preset': '🗑️',
            'update_bindings': '🔗',
            'rollback': '⏪',
            'import': '📥'
        };
        const icon = actionIcons[entry.action] || '📋';
        
        html += `
        <div class="history-item">
            <div class="history-info">
                <span class="history-icon">${icon}</span>
                <span class="history-desc">${escapeHtml(entry.description)}</span>
                <span class="history-time">${escapeHtml(time)}</span>
            </div>
            <button class="btn btn-sm" onclick="rollbackTo(${idx})">恢复</button>
        </div>`;
    });
    
    html += '</div>';
    html += '<button class="btn btn-sm btn-danger" onclick="clearHistory()" style="margin-top: 10px;">🗑️ 清空历史</button>';
    
    container.innerHTML = html;
}

async function rollbackTo(index) {
    if (!confirm('确定要恢复到此版本？当前未保存的更改将丢失。')) return;
    
    try {
        const result = await apiCall('/orchestrator/rollback', 'POST', {
            index: index
        });
        
        if (result.success) {
            orchestratorState.sequence = result.sequence || [];
            renderSequence();
            initSortable();
            updatePreview();
            loadOrchestratorHistory();
            showToast(result.message, 'success');
        } else {
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast('回滚失败: ' + e.message, 'error');
    }
}

async function clearHistory() {
    if (!confirm('确定要清空所有历史记录？')) return;
    
    try {
        const result = await apiCall('/orchestrator/history', 'DELETE');
        
        if (result.success) {
            orchestratorState.history = [];
            renderHistory();
            showToast(result.message, 'success');
        } else {
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast('清空失败: ' + e.message, 'error');
    }
}

// ==================== 导入/导出 ====================

async function exportOrchestratorConfig() {
    try {
        const result = await apiCall('/orchestrator/export');
        
        if (result.success) {
            const config = result.config;
            const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `orchestrator_config_${new Date().toISOString().slice(0, 10)}.json`;
            a.click();
            URL.revokeObjectURL(url);
            showToast('配置已导出', 'success');
        } else {
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast('导出失败: ' + e.message, 'error');
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
            
            const result = await apiCall('/orchestrator/import', 'POST', {
                config: config
            });
            
            if (result.success) {
                orchestratorState.sequence = result.sequence || [];
                renderSequence();
                initSortable();
                loadOrchestratorPresets();
                loadOrchestratorBindings();
                loadOrchestratorHistory();
                updatePreview();
                showToast(result.message, 'success');
            } else {
                showToast(result.error, 'error');
            }
        } catch (e) {
            showToast('导入失败: ' + e.message, 'error');
        }
    };
    input.click();
}

// ==================== 测试发送 ====================

async function testSendMessage() {
    const model = document.getElementById('test-model').value;
    const message = document.getElementById('test-message').value;
    const resultContainer = document.getElementById('test-result');
    
    if (!model) {
        showToast('请选择测试模型', 'error');
        return;
    }
    
    if (!message) {
        showToast('请输入测试消息', 'error');
        return;
    }
    
    resultContainer.innerHTML = '<div class="loading"><span class="spinner"></span> 发送中...</div>';
    
    try {
        const result = await apiCall('/orchestrator/test', 'POST', {
            model: model,
            message: message
        });
        
        if (result.success) {
            resultContainer.innerHTML = `
            <div class="test-result-success">
                <h4>🤖 模型回复：</h4>
                <div class="test-response">${escapeHtml(result.response, true)}</div>
                <div class="test-meta">
                    📊 Token: prompt ${escapeHtml(String(result.usage?.prompt_tokens || 0))} + completion ${escapeHtml(String(result.usage?.completion_tokens || 0))} = ${escapeHtml(String(result.usage?.total_tokens || 0))}
                    | ⏱️ ${escapeHtml(String(result.latency_ms || 0))}ms
                    | 📝 ${escapeHtml(String(result.orchestrated_count || 0))} 条编排消息
                </div>
            </div>`;
        } else {
            resultContainer.innerHTML = `<div class="test-result-error">❌ ${escapeHtml(result.error || '未知错误')}</div>`;
        }
    } catch (e) {
        resultContainer.innerHTML = `<div class="test-result-error">❌ ${e.message}</div>`;
    }
}

// ==================== 辅助函数 ====================

function getComponentIcon(type) {
    const icons = {
        'system_prompt': '📋',
        'fake_user': '👤',
        'fake_assistant': '🤖',
        'prefix_mount': '📎',
        'time_context': '📅',
        'memory_range': '📊',
        'layered_memory': '📖',
        'dynamic_search': '🔍',
        'tools_hint': '🔧',
        'suffix_mount': '📎',
        'custom_block': '📝',
        'real_messages': '💬',
        // 新增缓存优化组件
        'cache_break': '✂️',
        'volatile_context': '⏰',
        'pending_memory': '🗒️',
        // 条件挂载
        'conditional_mount': '🎯'
    };
    return icons[type] || '❓';
}

function getComponentLabel(type) {
    const labels = {
        'system_prompt': 'System Prompt',
        'fake_user': '伪造 User 消息',
        'fake_assistant': '伪造 Assistant 消息',
        'prefix_mount': '前置挂载 (prefix.md)',
        'time_context': '时间上下文',
        'memory_range': '记忆库范围',
        'layered_memory': '分层记忆',
        'dynamic_search': '动态检索结果',
        'tools_hint': '工具调用提示',
        'suffix_mount': '后置挂载 (suffix.md)',
        'custom_block': '自定义文本块',
        'real_messages': '真实对话历史',
        // 新增缓存优化组件
        'cache_break': '缓存分隔点',
        'volatile_context': '易变上下文 (时间+pending)',
        'pending_memory': '待归档记忆',
        // 条件挂载
        'conditional_mount': '条件额外挂载'
    };
    return labels[type] || type;
}

function isComponentEditable(type) {
    // 可编辑的组件：伪造消息、自定义块、缓存分隔点、条件挂载
    return ['fake_user', 'fake_assistant', 'custom_block', 'cache_break', 'conditional_mount'].includes(type);
}

function isComponentDeletable(type) {
    // 可删除的组件：非锁定的都可以删除
    // 只有 system_prompt 和 real_messages 不可删
    const nonDeletable = ['system_prompt', 'real_messages'];
    return !nonDeletable.includes(type);
}

function getSourceLabel(source) {
    const labels = {
        'fake': '伪造',
        'layered_memory': '记忆',
        'dynamic_search': '检索',
        'prefix_mount': '前置',
        'suffix_mount': '后置',
        'custom': '自定义',
        'real': '真实',
        'original': '原始',
        // 新增
        'cache_break': '分隔',
        'volatile_context': '易变',
        'pending_memory': 'pending',
        'time_context': '时间',
        'memory_range': '范围',
        'tools_hint': '工具',
        'system': 'system',
        'merged': '合并',
        // 条件挂载
        'conditional_mount': '条件挂载'
    };
    return labels[source] || source;
}

/**
 * 获取组件描述（用于非编辑组件的预览）
 */
function getComponentDescription(type) {
    const descriptions = {
        'system_prompt': '客户端发来的角色设定',
        'prefix_mount': 'prefix.md 文件内容（稳定，可缓存）',
        'memory_range': '记忆库日期范围和统计（相对稳定）',
        'layered_memory': '日记/周总结/月总结/季度总结（稳定，可缓存）',
        'dynamic_search': 'Agent 检索到的相关记忆',
        'tools_hint': '给主模型的工具调用说明',
        'suffix_mount': 'suffix.md 文件内容（稳定，可缓存）',
        'cache_break': '伪造 assistant 确认，打断消息合并',
        'volatile_context': '当前时间 + 今日 pending（每次变化，不缓存）',
        'time_context': '当前日期、时间、周数等（每次变化）',
        'pending_memory': '今日待归档记录（经常变化）',
        'real_messages': '用户实际的对话历史',
        'fake_user': '伪装的用户消息',
        'fake_assistant': '伪装的 AI 回复',
        'custom_block': '自定义文本内容',
        'conditional_mount': '仅对匹配模型生效的额外挂载'
    };
    return descriptions[type] || '';
}

// 注意: escapeHtml 已统一到 admin-core.js
// 本模块中需要换行转换的地方，使用 escapeHtml(text, true)

// ==================== 预填充配置 ====================

async function loadPrefillConfig() {
    try {
        const data = await apiCall('/orchestrator/prefill');
        
        if (data.success) {
            const prefill = data.prefill || {};
            
            // 填充表单
            const contentEl = document.getElementById('prefill-content');
            const thinkTagEl = document.getElementById('prefill-think-tag');
            const bindingsEl = document.getElementById('prefill-model-bindings');
            
            if (contentEl) {
                contentEl.value = prefill.content || '';
            }
            
            if (thinkTagEl) {
                thinkTagEl.value = prefill.think_tag || '</think>';
            }
            
            if (bindingsEl) {
                // 将模型绑定对象转换为文本列表
                const bindings = prefill.model_bindings || {};
                const enabledModels = Object.entries(bindings)
                    .filter(([_, enabled]) => enabled)
                    .map(([model, _]) => model);
                bindingsEl.value = enabledModels.join('\n');
            }
        }
    } catch (e) {
        console.error('加载预填充配置失败:', e);
    }
}

async function savePrefillConfig() {
    const contentEl = document.getElementById('prefill-content');
    const thinkTagEl = document.getElementById('prefill-think-tag');
    const bindingsEl = document.getElementById('prefill-model-bindings');
    
    const content = contentEl ? contentEl.value : '';
    const thinkTag = thinkTagEl ? thinkTagEl.value || '</think>' : '</think>';
    
    // 将文本列表转换为模型绑定对象
    const bindingsText = bindingsEl ? bindingsEl.value : '';
    const modelBindings = {};
    
    bindingsText.split('\n').forEach(line => {
        const model = line.trim();
        if (model) {
            modelBindings[model] = true;
        }
    });
    
    try {
        const result = await apiCall('/orchestrator/prefill', 'PUT', {
            content: content,
            model_bindings: modelBindings,
            think_tag: thinkTag
        });
        
        if (result.success) {
            showToast('预填充配置已保存', 'success');
        } else {
            showToast('保存失败: ' + result.error, 'error');
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}
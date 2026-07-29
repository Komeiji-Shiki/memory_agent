/**
 * 额外挂载页
 * - 启用/禁用（即时生效）
 * - 前置挂载 prefix.md / 后置挂载 suffix.md 编辑与保存
 */

import { apiCall } from '../core/api.js';
import { showToast, escapeHtml, bindActions } from '../core/ui.js';
import { markDirty, clearDirty, isDirty } from '../core/store.js';

let rootEl = null;

export const extraPage = {
    id: 'extra',
    title: '额外挂载',
    icon: '📎',
    group: 'settings',

    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="page-header">
                <h2>📎 额外挂载</h2>
                <p>在记忆上下文前后挂载自定义内容（prefix.md / suffix.md）</p>
            </div>

            <div class="card">
                <div class="card-header"><h3>开关</h3></div>
                <div style="display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
                    <label class="checkbox-label">
                        <input type="checkbox" id="extra-mount-enabled">启用额外挂载
                    </label>
                    <span id="extra-status" class="text-dim"></span>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>⬆️ 前置挂载（prefix.md）</h3>
                    <button class="btn btn-sm btn-success" data-action="save-prefix">💾 保存</button>
                </div>
                <textarea id="extra-prefix-content" class="form-input" rows="10" placeholder="挂载在记忆上下文之前的内容..."></textarea>
                <div id="extra-prefix-status" class="text-dim" style="margin-top: 8px; font-size: 0.85rem;"></div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>⬇️ 后置挂载（suffix.md）</h3>
                    <button class="btn btn-sm btn-success" data-action="save-suffix">💾 保存</button>
                </div>
                <textarea id="extra-suffix-content" class="form-input" rows="10" placeholder="挂载在记忆上下文之后的内容..."></textarea>
                <div id="extra-suffix-status" class="text-dim" style="margin-top: 8px; font-size: 0.85rem;"></div>
            </div>

            <div style="margin-bottom: 20px;">
                <button class="btn btn-primary" data-action="save-all">💾 全部保存</button>
            </div>
        `;

        bindActions(container, {
            'save-prefix': savePrefix,
            'save-suffix': saveSuffix,
            'save-all': saveAll,
        });

        container.querySelector('#extra-mount-enabled').addEventListener('change', toggleMount);
        container.querySelector('#extra-prefix-content').addEventListener('input', () => markDirty('extra-prefix', '前置挂载'));
        container.querySelector('#extra-suffix-content').addEventListener('input', () => markDirty('extra-suffix', '后置挂载'));
    },

    onEnter() {
        if (!isDirty('extra-prefix') && !isDirty('extra-suffix')) {
            loadExtraMount();
        }
    },
};

function fileStatusText(info, defaultPath) {
    if (info?.exists) {
        return `📄 文件: ${info.path} (${info.content?.length || 0} 字符)`;
    }
    return `⚠️ 文件不存在: ${info?.path || defaultPath}（保存时自动创建）`;
}

async function loadExtraMount() {
    const data = await apiCall('/extra');
    if (!data || data.error) {
        showToast('加载额外挂载失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }

    rootEl.querySelector('#extra-mount-enabled').checked = data.enabled;
    updateStatus(data.enabled);

    rootEl.querySelector('#extra-prefix-content').value = data.prefix?.content || '';
    rootEl.querySelector('#extra-prefix-status').textContent = fileStatusText(data.prefix, 'lifebook/extra/prefix.md');

    rootEl.querySelector('#extra-suffix-content').value = data.suffix?.content || '';
    rootEl.querySelector('#extra-suffix-status').textContent = fileStatusText(data.suffix, 'lifebook/extra/suffix.md');
}

function updateStatus(enabled) {
    rootEl.querySelector('#extra-status').innerHTML = enabled
        ? '<span style="color: var(--success);">✅ 额外挂载已启用</span>'
        : '<span class="text-dim">⏸️ 额外挂载已禁用</span>';
}

async function toggleMount() {
    const checkbox = rootEl.querySelector('#extra-mount-enabled');
    const enabled = checkbox.checked;

    const result = await apiCall('/extra/toggle', 'POST', { enabled });
    if (result && result.success) {
        updateStatus(enabled);
        showToast(result.message, 'success');
    } else {
        showToast('切换失败: ' + (result?.error || '未知错误'), 'error');
        checkbox.checked = !enabled; // 回滚
    }
}

async function savePrefix() {
    const content = rootEl.querySelector('#extra-prefix-content').value;
    const result = await apiCall('/extra/prefix', 'PUT', { content });
    if (result && result.success) {
        clearDirty('extra-prefix');
        rootEl.querySelector('#extra-prefix-status').textContent = `📄 已保存 ${result.path || ''} (${result.length} 字符)`;
        showToast('前置挂载已保存', 'success');
        return true;
    }
    showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    return false;
}

async function saveSuffix() {
    const content = rootEl.querySelector('#extra-suffix-content').value;
    const result = await apiCall('/extra/suffix', 'PUT', { content });
    if (result && result.success) {
        clearDirty('extra-suffix');
        rootEl.querySelector('#extra-suffix-status').textContent = `📄 已保存 ${result.path || ''} (${result.length} 字符)`;
        showToast('后置挂载已保存', 'success');
        return true;
    }
    showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    return false;
}

async function saveAll() {
    const ok1 = await savePrefix();
    const ok2 = await saveSuffix();
    if (ok1 && ok2) showToast('所有内容已保存', 'success');
}

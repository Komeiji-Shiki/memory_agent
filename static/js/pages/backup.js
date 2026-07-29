/**
 * 备份恢复页
 * - 创建备份 / 备份列表（下载 / 恢复 / 删除）/ 上传恢复
 */

import { apiCall, apiUpload } from '../core/api.js';
import { showToast, confirmDialog, escapeHtml, escapeAttr, spinnerHtml, emptyHtml, bindActions } from '../core/ui.js';
import { API_BASE } from '../core/api.js';

let rootEl = null;

export const backupPage = {
    id: 'backup',
    title: '备份恢复',
    icon: '💾',
    group: 'ops',

    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="page-header">
                <h2>💾 备份恢复</h2>
                <p>管理记忆库备份</p>
            </div>

            <div class="card">
                <div class="card-header"><h3>创建备份</h3></div>
                <div style="display: flex; gap: 12px; align-items: center;">
                    <button class="btn btn-success" data-action="create-backup">📦 创建备份</button>
                    <span id="backup-status" class="text-dim"></span>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>📤 上传恢复</h3></div>
                <div class="alert alert-warning">
                    <span>⚠️</span>
                    <div>上传备份文件后可选择直接恢复。<strong>恢复操作将覆盖当前所有数据！</strong></div>
                </div>
                <div style="display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
                    <input type="file" id="backup-upload-file" accept=".zip" style="flex: 1; min-width: 200px;">
                    <label class="checkbox-label"><input type="checkbox" id="backup-upload-restore" checked>上传后直接恢复</label>
                    <button class="btn btn-primary" data-action="upload-backup">📤 上传</button>
                </div>
                <div id="upload-status" class="text-dim" style="margin-top: 10px;"></div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>现有备份</h3>
                    <button class="btn btn-sm" data-action="refresh-backups">🔄 刷新</button>
                </div>
                <div id="backups-list">${spinnerHtml()}</div>
            </div>
        `;

        bindActions(container, {
            'create-backup': createBackup,
            'upload-backup': uploadBackup,
            'refresh-backups': loadBackups,
            'download-backup': (t) => downloadBackup(t.dataset.name),
            'restore-backup': (t) => restoreBackup(t.dataset.name),
            'delete-backup': (t) => deleteBackup(t.dataset.name),
        });
    },

    onEnter() {
        loadBackups();
    },
};

async function loadBackups() {
    const container = rootEl.querySelector('#backups-list');
    container.innerHTML = spinnerHtml();
    const data = await apiCall('/backups');
    if (data && data.backups && data.backups.length > 0) {
        let html = '<table class="table"><thead><tr><th>文件名</th><th>大小</th><th>创建时间</th><th>操作</th></tr></thead><tbody>';
        for (const b of data.backups) {
            const sizeDisplay = b.size > 1024 * 1024
                ? `${(b.size / 1024 / 1024).toFixed(2)} MB`
                : `${(b.size / 1024).toFixed(1)} KB`;
            const name = escapeAttr(b.name);
            html += `<tr>
                <td>${escapeHtml(b.name)}</td>
                <td>${sizeDisplay}</td>
                <td>${escapeHtml(b.created_at)}</td>
                <td style="white-space: nowrap;">
                    <button class="btn btn-sm btn-primary" data-action="download-backup" data-name="${name}">📥 下载</button>
                    <button class="btn btn-sm" data-action="restore-backup" data-name="${name}">🔄 恢复</button>
                    <button class="btn btn-sm btn-danger" data-action="delete-backup" data-name="${name}">🗑️ 删除</button>
                </td>
            </tr>`;
        }
        html += '</tbody></table>';
        container.innerHTML = html;
    } else {
        container.innerHTML = emptyHtml('暂无备份');
    }
}

async function createBackup() {
    const statusEl = rootEl.querySelector('#backup-status');
    statusEl.innerHTML = '<span class="spinner"></span> 创建中...';
    const data = await apiCall('/backup', 'POST');
    if (data && data.success) {
        statusEl.innerHTML = `<span style="color: var(--success);">✅ ${escapeHtml(data.backup_file)}</span>`;
        showToast('备份创建成功', 'success');
        loadBackups();
    } else {
        statusEl.innerHTML = '<span style="color: var(--danger);">❌ 创建失败</span>';
        showToast('备份创建失败: ' + (data?.error || '未知错误'), 'error');
    }
}

function downloadBackup(name) {
    const a = document.createElement('a');
    a.href = `${API_BASE}/backup/${encodeURIComponent(name)}/download`;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast('开始下载...', 'info');
}

async function restoreBackup(name) {
    const ok = await confirmDialog(`确定要恢复备份 ${name} 吗？\n\n⚠️ 这将覆盖当前数据！`, { danger: true, okText: '恢复' });
    if (!ok) return;
    const data = await apiCall('/restore', 'POST', { backup_name: name });
    if (data && data.success) {
        showToast('备份恢复成功', 'success');
    } else {
        showToast('恢复失败: ' + (data?.error || '未知错误'), 'error');
    }
}

async function deleteBackup(name) {
    const ok = await confirmDialog(`确定要删除备份 ${name} 吗？\n此操作不可恢复。`, { danger: true, okText: '删除' });
    if (!ok) return;
    const data = await apiCall(`/backup/${encodeURIComponent(name)}`, 'DELETE');
    if (data && data.success) {
        showToast('备份已删除', 'success');
        loadBackups();
    } else {
        showToast('删除失败: ' + (data?.error || '未知错误'), 'error');
    }
}

async function uploadBackup() {
    const fileInput = rootEl.querySelector('#backup-upload-file');
    const statusEl = rootEl.querySelector('#upload-status');

    if (!fileInput.files || fileInput.files.length === 0) {
        showToast('请先选择备份文件', 'error');
        return;
    }
    const file = fileInput.files[0];
    if (!file.name.endsWith('.zip')) {
        showToast('请选择 .zip 格式的备份文件', 'error');
        return;
    }

    const doRestore = rootEl.querySelector('#backup-upload-restore').checked;
    if (doRestore) {
        const ok = await confirmDialog(`确定要上传并恢复备份 ${file.name} 吗？\n\n⚠️ 这将覆盖当前所有数据！`, { danger: true, okText: '上传并恢复' });
        if (!ok) return;
    }

    statusEl.innerHTML = '<span class="spinner"></span> 上传中...';
    const formData = new FormData();
    formData.append('file', file);
    formData.append('restore', doRestore ? 'true' : 'false');

    const data = await apiUpload('/backup/upload', formData);
    if (data && data.success) {
        statusEl.innerHTML = `<span style="color: var(--success);">✅ ${escapeHtml(data.message)}</span>`;
        showToast(data.restored ? '备份恢复成功！' : '备份上传成功', 'success');
        loadBackups();
        fileInput.value = '';
    } else {
        statusEl.innerHTML = `<span style="color: var(--danger);">❌ ${escapeHtml(data?.error || '上传失败')}</span>`;
        showToast('上传失败: ' + (data?.error || '未知错误'), 'error');
    }
}

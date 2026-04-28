/**
 * Admin Memory - 记忆管理和备份
 */

// ===== 日记管理 =====
async function loadRecentDiaries() {
    const container = document.getElementById('recent-diaries');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    const data = await apiCall('/diaries?limit=10');
    if (data && data.diaries) {
        let html = '<table class="table"><thead><tr><th>日期</th><th>标题</th><th>标签</th><th>操作</th></tr></thead><tbody>';
        data.diaries.forEach(d => {
            const tags = (d.tags || []).map(t => `<span class="badge badge-info">#${escapeHtml(t)}</span>`).join(' ');
            html += `<tr>
                <td>${escapeHtml(d.date)}</td>
                <td>${escapeHtml(d.title) || '-'}</td>
                <td>${tags || '-'}</td>
                <td><button class="btn btn-sm btn-primary" onclick="viewDiary('${escapeAttr(d.date)}')">📖 查看</button></td>
            </tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
    } else {
        container.innerHTML = '<p style="color: var(--text-dim);">暂无日记</p>';
    }
}

// ===== 查看日记详情 =====
async function viewDiary(date) {
    const data = await apiCall(`/diary/${date}`);
    if (data && !data.error) {
        const tags = (data.tags || []).map(t => `<span class="badge badge-info">#${t}</span>`).join(' ') || '无';
        const links = (data.links || []).map(l => `<span class="badge">${l}</span>`).join(' ') || '无';
        
        showModal('日记详情', `
            <div style="margin-bottom: 15px;">
                <strong>📅 日期：</strong>${data.date}<br>
                <strong>📝 标题：</strong>${data.title || '无标题'}<br>
                <strong>🏷️ 标签：</strong>${tags}<br>
                <strong>🔗 链接：</strong>${links}
            </div>
            <div style="background: var(--surface-2); padding: 15px; border-radius: 8px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; font-family: monospace; font-size: 0.9rem;">
${escapeHtml(data.content)}
            </div>
        `);
    } else {
        showToast('加载日记失败: ' + (data?.error || '未知错误'), 'error');
    }
}

async function searchMemories() {
    const query = document.getElementById('search-query').value;
    if (!query) return;
    
    const container = document.getElementById('search-results');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 搜索中...</div>';
    
    const data = await apiCall('/search', 'POST', { query });
    if (data && data.results) {
        let html = '<div style="margin-top: 15px;">';
        data.results.forEach(r => {
            html += `<div style="padding: 10px; border-bottom: 1px solid var(--line-weak);">
                <strong>${r.file}</strong> <span class="badge badge-info">${r.type}</span>
                <p style="color: var(--text-dim); margin-top: 5px;">${r.snippet || ''}</p>
            </div>`;
        });
        html += '</div>';
        container.innerHTML = html;
    } else {
        container.innerHTML = '<p style="color: var(--text-dim);">未找到结果</p>';
    }
}

async function rebuildIndex() {
    const container = document.getElementById('index-status');
    container.innerHTML = '<span class="spinner"></span> 重建中...';
    
    const data = await apiCall('/rebuild-index', 'POST');
    if (data && data.success) {
        container.innerHTML = '<span style="color: var(--success);">✅ 索引重建完成</span>';
        showToast('索引重建完成', 'success');
    } else {
        container.innerHTML = '<span style="color: var(--danger);">❌ 重建失败</span>';
    }
}

// ===== 节点管理 =====
// 节点类型图标映射（统一定义）
const NODE_TYPE_ICONS = {
    '人物': '👤',
    '地点': '📍',
    '事物': '📦',
    '概念': '💡',
    '事件': '📅'
};

async function loadNodes(type = '') {
    const container = document.getElementById('nodes-list');
    if (!container) return;
    
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    const url = type ? `/nodes?type=${encodeURIComponent(type)}` : '/nodes';
    const data = await apiCall(url);
    
    if (data && data.nodes && data.nodes.length > 0) {
        let html = '<table class="table"><thead><tr><th>类型</th><th>名称</th><th>标签</th><th>操作</th></tr></thead><tbody>';
        data.nodes.forEach(n => {
            const typeIcon = NODE_TYPE_ICONS[n.type] || '📌';
            const tags = (n.tags || []).slice(0, 3).map(t => `<span class="badge badge-info">#${escapeHtml(t)}</span>`).join(' ');
            html += `<tr>
                <td>${typeIcon} ${escapeHtml(n.type)}</td>
                <td>${escapeHtml(n.name)}</td>
                <td>${tags || '-'}</td>
                <td>
                    <button class="btn btn-sm btn-primary" onclick="viewNode('${escapeAttr(n.name)}')">📖 查看</button>
                    <button class="btn btn-sm" onclick="editNode('${escapeAttr(n.name)}')" style="margin-left: 5px;">✏️ 编辑</button>
                </td>
            </tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
    } else {
        container.innerHTML = '<p style="color: var(--text-dim);">暂无节点</p>';
    }
}

// ===== 查看节点详情 =====
async function viewNode(name) {
    const data = await apiCall(`/node/${encodeURIComponent(name)}`);
    if (data && !data.error) {
        const typeIcon = NODE_TYPE_ICONS[data.type] || '📌';
        const tags = (data.tags || []).map(t => `<span class="badge badge-info">#${t}</span>`).join(' ') || '无';
        const links = (data.links || []).map(l => `<span class="badge">${l}</span>`).join(' ') || '无';
        
        showModal('节点详情', `
            <div style="margin-bottom: 15px;">
                <strong>${typeIcon} 类型：</strong>${data.type}<br>
                <strong>📝 名称：</strong>${escapeHtml(data.name)}<br>
                <strong>🏷️ 标签：</strong>${tags}<br>
                <strong>🔗 链接：</strong>${links}
            </div>
            <div style="background: var(--surface-2); padding: 15px; border-radius: 8px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; font-family: monospace; font-size: 0.9rem;">
${escapeHtml(data.content)}
            </div>
            <div style="margin-top: 15px; text-align: right;">
                <button class="btn btn-primary" onclick="editNode('${escapeAttr(data.name)}'); closeModal();">✏️ 编辑此节点</button>
            </div>
        `);
    } else {
        showToast('加载节点失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 编辑节点 =====
async function editNode(name) {
    const data = await apiCall(`/node/${encodeURIComponent(name)}`);
    if (data && !data.error) {
        const typeIcon = NODE_TYPE_ICONS[data.type] || '📌';
        const tags = (data.tags || []).join(', ');
        
        showModal('编辑节点', `
            <div style="margin-bottom: 15px;">
                <strong>${typeIcon} ${escapeHtml(data.type)} - ${escapeHtml(data.name)}</strong>
            </div>
            <div class="form-group">
                <label class="form-label">标签（逗号分隔）</label>
                <input type="text" id="edit-node-tags" class="form-input" value="${escapeAttrValue(tags)}">
            </div>
            <div class="form-group">
                <label class="form-label">内容</label>
                <textarea id="edit-node-content" class="form-input" style="min-height: 300px; font-family: monospace;">${escapeHtml(data.content)}</textarea>
            </div>
            <div style="margin-top: 15px; text-align: right;">
                <button class="btn" onclick="closeModal()">取消</button>
                <button class="btn btn-success" onclick="saveNode('${escapeAttr(data.name)}')" style="margin-left: 10px;">💾 保存</button>
            </div>
        `, 'large');
    } else {
        showToast('加载节点失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 保存节点 =====
async function saveNode(name) {
    const content = document.getElementById('edit-node-content').value;
    const tagsStr = document.getElementById('edit-node-tags').value;
    const tags = tagsStr.split(',').map(t => t.trim()).filter(t => t);
    
    const data = await apiCall(`/node/${encodeURIComponent(name)}`, 'PUT', {
        content: content,
        tags: tags
    });
    
    if (data && data.success) {
        showToast('节点保存成功', 'success');
        closeModal();
        loadNodes();  // 刷新列表
    } else {
        showToast('保存失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 创建新节点 =====
function showCreateNodeDialog() {
    showModal('创建新节点', `
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
        <div class="form-group">
            <label class="form-label">标签（逗号分隔）</label>
            <input type="text" id="new-node-tags" class="form-input" placeholder="标签1, 标签2">
        </div>
        <div class="form-group">
            <label class="form-label">内容</label>
            <textarea id="new-node-content" class="form-input" style="min-height: 200px; font-family: monospace;" placeholder="节点内容..."></textarea>
        </div>
        <div style="margin-top: 15px; text-align: right;">
            <button class="btn" onclick="closeModal()">取消</button>
            <button class="btn btn-success" onclick="createNode()" style="margin-left: 10px;">✨ 创建</button>
        </div>
    `, 'large');
}

async function createNode() {
    const type = document.getElementById('new-node-type').value;
    const name = document.getElementById('new-node-name').value.trim();
    const content = document.getElementById('new-node-content').value;
    const tagsStr = document.getElementById('new-node-tags').value;
    const tags = tagsStr.split(',').map(t => t.trim()).filter(t => t);
    
    if (!name) {
        showToast('请输入节点名称', 'error');
        return;
    }
    
    const data = await apiCall('/node', 'POST', {
        name: name,
        type: type,
        content: content,
        tags: tags
    });
    
    if (data && data.success) {
        showToast('节点创建成功', 'success');
        closeModal();
        loadNodes();
    } else {
        showToast('创建失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 备份 =====
// 注意: showModal 和 closeModal 已统一到 admin-core.js

async function loadBackups() {
    const container = document.getElementById('backups-list');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    const data = await apiCall('/backups');
    if (data && data.backups && data.backups.length > 0) {
        let html = '<table class="table"><thead><tr><th>文件名</th><th>大小</th><th>创建时间</th><th>操作</th></tr></thead><tbody>';
        data.backups.forEach(b => {
            const sizeKB = (b.size / 1024).toFixed(1);
            const sizeMB = (b.size / 1024 / 1024).toFixed(2);
            const sizeDisplay = b.size > 1024 * 1024 ? `${sizeMB} MB` : `${sizeKB} KB`;
            html += `<tr>
                <td>${escapeHtml(b.name)}</td>
                <td>${sizeDisplay}</td>
                <td>${escapeHtml(b.created_at)}</td>
                <td style="white-space: nowrap;">
                    <button class="btn btn-sm btn-primary" onclick="downloadBackup('${escapeAttr(b.name)}')" title="下载">📥 下载</button>
                    <button class="btn btn-sm" onclick="restoreBackup('${escapeAttr(b.name)}')" style="margin-left: 5px;" title="恢复">🔄 恢复</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteBackup('${escapeAttr(b.name)}')" style="margin-left: 5px;" title="删除">🗑️ 删除</button>
                </td>
            </tr>`;
        });
        html += '</tbody></table>';
        container.innerHTML = html;
    } else {
        container.innerHTML = '<p style="color: var(--text-dim);">暂无备份</p>';
    }
}

async function createBackup() {
    const status = document.getElementById('backup-status');
    status.innerHTML = '<span class="spinner"></span> 创建中...';
    
    const data = await apiCall('/backup', 'POST');
    if (data && data.success) {
        status.innerHTML = `<span style="color: var(--success);">✅ ${data.backup_file}</span>`;
        showToast('备份创建成功', 'success');
        loadBackups();
    } else {
        status.innerHTML = '<span style="color: var(--danger);">❌ 创建失败</span>';
    }
}

async function restoreBackup(name) {
    if (!confirm(`确定要恢复备份 ${name} 吗？这将覆盖当前数据。`)) return;
    
    const data = await apiCall('/restore', 'POST', { backup_name: name });
    if (data && data.success) {
        showToast('备份恢复成功', 'success');
    } else {
        showToast('恢复失败', 'error');
    }
}

async function deleteBackup(name) {
    if (!confirm(`确定要删除备份 ${name} 吗？此操作不可恢复。`)) return;
    
    const data = await apiCall(`/backup/${encodeURIComponent(name)}`, 'DELETE');
    if (data && data.success) {
        showToast('备份已删除', 'success');
        loadBackups();
    } else {
        showToast('删除失败: ' + (data?.error || '未知错误'), 'error');
    }
}

function downloadBackup(name) {
    const url = `/api/memory/backup/${encodeURIComponent(name)}/download`;
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    showToast('开始下载...', 'info');
}

async function uploadBackup() {
    const fileInput = document.getElementById('backup-upload-file');
    const restoreCheckbox = document.getElementById('backup-upload-restore');
    const statusDiv = document.getElementById('upload-status');
    
    if (!fileInput.files || fileInput.files.length === 0) {
        showToast('请先选择备份文件', 'error');
        return;
    }
    
    const file = fileInput.files[0];
    if (!file.name.endsWith('.zip')) {
        showToast('请选择 .zip 格式的备份文件', 'error');
        return;
    }
    
    const doRestore = restoreCheckbox.checked;
    
    if (doRestore) {
        if (!confirm(`确定要上传并恢复备份 ${file.name} 吗？\n\n⚠️ 这将覆盖当前所有数据！`)) {
            return;
        }
    }
    
    statusDiv.innerHTML = '<span class="spinner"></span> 上传中...';
    
    try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('restore', doRestore ? 'true' : 'false');
        
        const res = await fetch('/api/memory/backup/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await res.json();
        
        if (data.success) {
            if (data.restored) {
                statusDiv.innerHTML = `<span style="color: var(--success);">✅ ${data.message}</span>`;
                showToast('备份恢复成功！', 'success');
            } else {
                statusDiv.innerHTML = `<span style="color: var(--success);">✅ ${data.message}</span>`;
                showToast('备份上传成功', 'success');
            }
            loadBackups();
            fileInput.value = '';
        } else {
            statusDiv.innerHTML = `<span style="color: var(--danger);">❌ ${data.error}</span>`;
            showToast('上传失败: ' + data.error, 'error');
        }
    } catch (e) {
        statusDiv.innerHTML = `<span style="color: var(--danger);">❌ 上传失败</span>`;
        showToast('上传失败: ' + e.message, 'error');
    }
}
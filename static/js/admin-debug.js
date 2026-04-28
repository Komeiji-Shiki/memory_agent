/**
 * Admin Debug - 调试日志管理
 */

async function loadDebugLogs() {
    const container = document.getElementById('debug-logs-list');
    const statsContainer = document.getElementById('debug-stats');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    const logType = document.getElementById('debug-log-type').value;
    const limit = document.getElementById('debug-log-limit').value;
    
    try {
        let url = `/api/memory/debug/logs?limit=${limit}`;
        if (logType) url += `&type=${logType}`;
        
        const res = await fetch(url);
        const data = await res.json();
        
        if (data.error) {
            container.innerHTML = `<p style="color: var(--danger);">加载失败: ${data.error}</p>`;
            return;
        }
        
        // 渲染统计
        const stats = data.stats || {};
        let statsHtml = `
        <div class="stats-grid" style="margin-bottom: 0;">
            <div class="stat-card">
                <div class="stat-card-label">📊 总日志数</div>
                <div class="stat-card-value">${stats.total || 0}</div>
                <div class="stat-card-detail">/ ${stats.max_logs || 100} 条上限</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-label">🔍 搜索Agent</div>
                <div class="stat-card-value">${stats.by_type?.search_agent || 0}</div>
                <div class="stat-card-detail">条记录</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-label">📝 总结生成</div>
                <div class="stat-card-value">${stats.by_type?.summary_generate || 0}</div>
                <div class="stat-card-detail">条记录</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-label">📦 待处理汇总</div>
                <div class="stat-card-value">${stats.by_type?.pending_consolidate || 0}</div>
                <div class="stat-card-detail">条记录</div>
            </div>
        </div>`;
        statsContainer.innerHTML = statsHtml;
        
        // 渲染日志列表
        const logs = data.logs || [];
        if (logs.length === 0) {
            container.innerHTML = '<p style="color: var(--text-dim);">暂无日志记录</p>';
            return;
        }
        
        let html = '';
        logs.forEach((log, index) => {
            const ts = new Date(log.timestamp);
            const timeStr = ts.toLocaleString('zh-CN');
            
            const typeLabels = {
                'search_agent': { emoji: '🔍', label: '搜索Agent', color: 'var(--accent)' },
                'post_conversation': { emoji: '💬', label: '对话后总结', color: '#a78bfa' },
                'summary_generate': { emoji: '📝', label: '总结生成', color: 'var(--success)' },
                'pending_consolidate': { emoji: '📦', label: '待处理汇总', color: 'var(--warning)' }
            };
            const typeInfo = typeLabels[log.log_type] || { emoji: '❓', label: log.log_type, color: 'var(--text-dim)' };
            
            let extraInfo = [];
            if (log.extra) {
                if (log.extra.summary_type) extraInfo.push(`类型: ${log.extra.summary_type}`);
                if (log.extra.identifier) extraInfo.push(`标识: ${log.extra.identifier}`);
                if (log.extra.session_id) extraInfo.push(`会话: ${log.extra.session_id}`);
                if (log.extra.query) extraInfo.push(`查询: ${log.extra.query.substring(0, 30)}...`);
            }
            
            html += `
            <div class="debug-log-item" style="border-left: 4px solid ${typeInfo.color};" onclick="showDebugLogDetail(${index})">
                <div class="debug-log-header">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span style="color: ${typeInfo.color}; font-weight: 700; font-size: 1rem;">${typeInfo.emoji} ${typeInfo.label}</span>
                        <span class="badge badge-info">${escapeHtml(log.model) || '-'}</span>
                    </div>
                    <span style="color: var(--text-dim); font-size: 0.8rem;">${escapeHtml(timeStr)}</span>
                </div>
                <div class="debug-log-meta">
                    ${extraInfo.map(info => `<span>${escapeHtml(info)}</span>`).join('<span style="opacity: 0.3;">|</span>')}
                </div>
                <div class="debug-log-preview">${escapeHtml(log.prompt || '', true)}</div>
            </div>`;
        });
        
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<p style="color: var(--danger);">加载失败: ${e.message}</p>`;
    }
}

async function showDebugLogDetail(index) {
    try {
        const res = await fetch(`/api/memory/debug/logs/${index}`);
        const log = await res.json();
        
        if (log.error) {
            showToast('加载失败: ' + log.error, 'error');
            return;
        }
        
        const ts = new Date(log.timestamp);
        const timeStr = ts.toLocaleString('zh-CN');
        
        const typeLabels = {
            'search_agent': '🔍 搜索Agent',
            'post_conversation': '💬 对话后总结',
            'summary_generate': '📝 总结生成',
            'pending_consolidate': '📦 待处理汇总'
        };
        
        let bodyHtml = `
            <div style="display: flex; gap: 20px; margin-bottom: 25px; align-items: center; background: var(--surface-2); padding: 15px; border-radius: 8px;">
                <div><span style="color: var(--text-dim);">时间：</span><strong>${escapeHtml(timeStr)}</strong></div>
                <div><span style="color: var(--text-dim);">模型：</span><span class="badge badge-info">${escapeHtml(log.model) || '-'}</span></div>
            </div>`;
        
        if (log.extra && Object.keys(log.extra).length > 0) {
            bodyHtml += `
                <div class="log-section">
                    <div class="log-section-title">📋 额外信息</div>
                    <pre class="log-code-block">${escapeHtml(JSON.stringify(log.extra, null, 2))}</pre>
                </div>`;
        }
        
        if (log.system_prompt) {
            bodyHtml += `
                <div class="log-section">
                    <div class="log-section-title">🤖 系统提示词 (System Prompt)</div>
                    <div class="log-code-block" style="max-height: 300px; overflow-y: auto;">${escapeHtml(log.system_prompt, true)}</div>
                </div>`;
        }
        
        if (log.prompt) {
            bodyHtml += `
                <div class="log-section">
                    <div class="log-section-title">💬 提示词内容 (Prompt)</div>
                    <div class="log-code-block" style="max-height: 600px; overflow-y: auto;">${escapeHtml(log.prompt, true)}</div>
                </div>`;
        }
        
        if (log.messages && log.messages.length > 0) {
            bodyHtml += `
                <div class="log-section">
                    <div class="log-section-title">📨 完整消息列表 (${log.messages.length} 条)</div>
                    <div class="log-code-block" style="max-height: 400px; overflow-y: auto;">${escapeHtml(JSON.stringify(log.messages, null, 2))}</div>
                </div>`;
        }
        
        if (log.response) {
            bodyHtml += `
                <div class="log-section">
                    <div class="log-section-title">✅ 模型响应</div>
                    <div class="log-code-block" style="max-height: 400px; overflow-y: auto; color: var(--success);">${escapeHtml(log.response, true)}</div>
                </div>`;
        }
        
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
        
        overlay.innerHTML = `
            <div class="modal-container">
                <div class="modal-header">
                    <h2 style="color: var(--accent); margin: 0;">${typeLabels[log.log_type] || log.log_type} 详情</h2>
                    <button class="btn btn-sm" onclick="this.closest('.modal-overlay').remove()">✕</button>
                </div>
                <div class="modal-body">
                    ${bodyHtml}
                </div>
                <div class="modal-footer">
                    <button class="btn" onclick="this.closest('.modal-overlay').remove()">关闭</button>
                    <button class="btn btn-primary" onclick="copyDebugLog(${index})">📋 复制完整 Prompt</button>
                </div>
            </div>`;
        
        document.body.appendChild(overlay);
    } catch (e) {
        showToast('加载失败: ' + e.message, 'error');
    }
}

// 注意: escapeHtml 已统一到 admin-core.js

async function copyDebugLog(index) {
    try {
        const res = await fetch(`/api/memory/debug/logs/${index}`);
        const log = await res.json();
        
        let text = `=== ${log.log_type} ===\n`;
        text += `时间: ${log.timestamp}\n`;
        text += `模型: ${log.model}\n\n`;
        
        if (log.system_prompt) {
            text += `=== System Prompt ===\n${log.system_prompt}\n\n`;
        }
        
        text += `=== Prompt ===\n${log.prompt}\n`;
        
        await navigator.clipboard.writeText(text);
        showToast('提示词已复制到剪贴板', 'success');
    } catch (e) {
        showToast('复制失败', 'error');
    }
}

async function clearDebugLogs() {
    if (!confirm('确定要清空所有调试日志吗？')) return;
    
    try {
        const res = await fetch('/api/memory/debug/logs', { method: 'DELETE' });
        const data = await res.json();
        
        if (data.success) {
            showToast('日志已清空', 'success');
            loadDebugLogs();
        } else {
            showToast('清空失败', 'error');
        }
    } catch (e) {
        showToast('清空失败: ' + e.message, 'error');
    }
}

async function retryLastSummary() {
    if (!confirm('确定要重试最后一次对话的总结吗？\n\n这会把刚刚的对话内容和主模型的思考过程一起发给总结模型。')) return;
    
    showToast('正在重试总结...', 'info');
    try {
        const res = await fetch('/api/memory/summary/retry-last', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        
        if (data.success) {
            showToast(data.message, 'success');
            // 如果在记忆管理页面，刷新待处理列表
            if (document.querySelector('.nav-item[data-page="memory"]').classList.contains('active')) {
                loadPendingStats();
            }
        } else {
            showToast('总结失败: ' + (data.message || data.error || '未知错误'), 'warning');
        }
    } catch (e) {
        showToast('重试失败: ' + e.message, 'error');
    }
}

async function addTestLog() {
    try {
        const res = await fetch('/api/memory/debug/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        
        if (data.success) {
            showToast('测试日志已添加，刷新查看', 'success');
            loadDebugLogs();
        } else {
            showToast('添加失败: ' + (data.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('添加失败: ' + e.message, 'error');
    }
}
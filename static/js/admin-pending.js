/**
 * Admin Pending - 待处理摘要和归档会话管理
 */

// ===== 待处理摘要（智能会话版） =====
async function loadPendingStats() {
    const container = document.getElementById('pending-stats');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    try {
        // 加载配置
        const configData = await apiCall('/pending/config');
        if (configData) {
            if (configData.sleep_gap_hours) {
                document.getElementById('sleep-gap-hours').value = configData.sleep_gap_hours;
            }
            document.getElementById('pending-consolidate-prompt').value = configData.consolidate_prompt || '';
            document.getElementById('pending-merge-prompt').value = configData.merge_prompt || '';
            document.getElementById('pending-consolidate-with-tools-prompt').value = configData.consolidate_with_tools_prompt || '';
        }
        
        // 加载会话列表
        const data = await apiCall('/pending/sessions?ready_only=false');
        
        if (!data.sessions || data.sessions.length === 0) {
            container.innerHTML = '<p style="color: var(--success);">✅ 没有待处理的会话</p>';
            return;
        }
        
        let html = `
        <div style="display: flex; gap: 20px; margin-bottom: 15px;">
            <div style="background: var(--surface-2); padding: 10px 15px; border-radius: 8px;">
                <span style="color: var(--text-dim);">总会话：</span>
                <strong style="color: var(--accent);">${data.total}</strong>
            </div>
            <div style="background: var(--surface-2); padding: 10px 15px; border-radius: 8px;">
                <span style="color: var(--text-dim);">可汇总：</span>
                <strong style="color: var(--success);">${data.ready_count}</strong>
            </div>
        </div>`;
        
        html += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 15px;">';
        
        for (const session of data.sessions) {
            const isReady = session.is_ready;
            const borderColor = isReady ? 'var(--success)' : 'var(--accent)';
            const statusBadge = isReady
                ? '<span class="badge badge-success">可汇总</span>'
                : '<span class="badge badge-info">进行中</span>';
            
            const startTime = new Date(session.start_time);
            const endTime = new Date(session.end_time);
            const dateStr = startTime.toLocaleDateString('zh-CN');
            const startStr = startTime.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'});
            const endStr = endTime.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'});
            
            const topics = (session.topics || []).slice(0, 3).map(t => escapeHtml(t)).join('、');
            const moreTopics = (session.topics || []).length > 3 ? ` +${session.topics.length - 3}` : '';
            
            html += `
            <div style="background: var(--surface-2); padding: 15px; border-radius: 8px; border-left: 3px solid ${borderColor};">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <span style="font-weight: 600; color: var(--accent);">🕐 ${escapeHtml(dateStr)}</span>
                    ${statusBadge}
                </div>
                <div style="font-size: 0.85rem; color: var(--text-dim); margin-bottom: 8px;">
                    ${escapeHtml(startStr)} ~ ${escapeHtml(endStr)} | ${session.duration_minutes} 分钟 | ${session.summary_count} 条摘要
                </div>
                <div style="font-size: 0.8rem; color: var(--text-dim); margin-bottom: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    📝 ${topics}${moreTopics}
                </div>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    ${isReady ? `<button class="btn btn-sm btn-success" onclick="consolidateSession('${escapeAttr(session.session_id)}')" title="使用LLM整理成流畅日记">🤖 汇总</button>` : ''}
                    ${isReady ? `<button class="btn btn-sm" style="background: var(--accent); color: white;" onclick="showConsolidateOptions('${escapeAttr(session.session_id)}')" title="汇总并提取节点">🔧 汇总+节点</button>` : ''}
                    ${isReady ? `<button class="btn btn-sm btn-warning" onclick="directConvertSession('${escapeAttr(session.session_id)}')" title="直接转换摘要，不经过LLM">⚡ 直接转换</button>` : ''}
                    <button class="btn btn-sm" onclick="viewSession('${escapeAttr(session.session_id)}')">查看</button>
                </div>
            </div>`;
        }
        html += '</div>';
        
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<p style="color: var(--danger);">加载失败: ' + e.message + '</p>';
    }
}

async function savePendingConfig() {
    const sleepGap = parseFloat(document.getElementById('sleep-gap-hours').value);
    
    try {
        const result = await apiCall('/pending/config', 'POST', { sleep_gap_hours: sleepGap });
        if (result.success) {
            showToast('睡眠间隔配置已保存', 'success');
            loadPendingStats();
        } else {
            showToast('保存失败', 'error');
        }
    } catch (e) {
        showToast('保存失败', 'error');
    }
}

async function savePendingPromptConfig() {
    const consolidatePrompt = document.getElementById('pending-consolidate-prompt').value;
    const mergePrompt = document.getElementById('pending-merge-prompt').value;
    const consolidateWithToolsPrompt = document.getElementById('pending-consolidate-with-tools-prompt').value;
    
    try {
        const result = await apiCall('/pending/config', 'POST', {
            consolidate_prompt: consolidatePrompt,
            merge_prompt: mergePrompt,
            consolidate_with_tools_prompt: consolidateWithToolsPrompt
        });
        if (result.success) {
            showToast('汇总提示词已保存', 'success');
        } else {
            showToast('保存失败', 'error');
        }
    } catch (e) {
        showToast('保存失败', 'error');
    }
}

async function consolidateSession(sessionId) {
    if (!confirm(`确定要将会话 ${sessionId} 汇总成日记吗？`)) return;
    
    showToast('正在汇总...', 'info');
    
    try {
        const result = await apiCall('/pending/consolidate', 'POST', { session_id: sessionId });
        
        if (result.success) {
            showToast(result.message, 'success');
            loadPendingStats();
            if (typeof loadRecentDiaries === 'function') loadRecentDiaries();
        } else {
            showToast(result.message || '汇总失败', 'error');
        }
    } catch (e) {
        showToast('汇总失败', 'error');
    }
}

function showConsolidateOptions(sessionId) {
    const safeSessionId = escapeAttr(sessionId);
    const html = `
    <h4 style="margin-bottom: 15px;">🔧 选择汇总模式</h4>
    <p style="color: var(--text-dim); margin-bottom: 20px;">会话 ${escapeHtml(sessionId)}</p>
    
    <div style="display: flex; flex-direction: column; gap: 12px;">
        <button class="btn btn-success" onclick="consolidateWithTools('${safeSessionId}', 'both'); closeModal();" style="padding: 15px; text-align: left;">
            <strong>📝 日记 + 🔧 节点</strong><br>
            <span style="font-size: 0.85rem; opacity: 0.8;">生成日记的同时提取/更新知识节点</span>
        </button>
        
        <button class="btn" onclick="consolidateWithTools('${safeSessionId}', 'diary_only'); closeModal();" style="padding: 15px; text-align: left; background: var(--surface-2);">
            <strong>📝 仅日记</strong><br>
            <span style="font-size: 0.85rem; opacity: 0.8;">只生成日记，不处理节点（和普通汇总一样）</span>
        </button>
        
        <button class="btn" onclick="consolidateWithTools('${safeSessionId}', 'nodes_only'); closeModal();" style="padding: 15px; text-align: left; background: var(--surface-2);">
            <strong>🔧 仅节点</strong><br>
            <span style="font-size: 0.85rem; opacity: 0.8;">只提取/更新节点，不生成日记（会话不会归档）</span>
        </button>
    </div>
    
    <button class="btn" style="margin-top: 15px;" onclick="closeModal()">取消</button>
    `;
    showModal(html);  // 使用 admin-core.js 中统一的 showModal（单参数模式）
}

async function consolidateWithTools(sessionId, mode) {
    // 模态框已在按钮点击时关闭
    const modeNames = {
        'both': '日记+节点',
        'diary_only': '仅日记',
        'nodes_only': '仅节点'
    };
    
    showToast(`正在执行${modeNames[mode]}汇总...可能需要较长时间`, 'info');
    
    try {
        const result = await apiCall('/pending/consolidate-with-tools', 'POST', {
            session_id: sessionId,
            mode: mode
        });
        
        if (result.success) {
            let message = result.message;
            if (result.tool_calls && result.tool_calls.length > 0) {
                message += `\n\n工具调用: ${result.tool_calls.map(tc => tc.name).join(', ')}`;
            }
            showToast(message, 'success');
            loadPendingStats();
            if (typeof loadRecentDiaries === 'function') loadRecentDiaries();
        } else {
            showToast(result.message || '汇总失败', 'error');
        }
    } catch (e) {
        showToast('汇总失败: ' + e.message, 'error');
    }
}

async function directConvertSession(sessionId) {
    if (!confirm(`确定要直接转换会话 ${sessionId} 吗？\n\n⚡ 直接转换会保留摘要原文，不经过LLM润色。\n适合你觉得摘要质量已经很好的情况~`)) return;
    
    showToast('正在直接转换...', 'info');
    
    try {
        const result = await apiCall('/pending/direct-convert', 'POST', { session_id: sessionId });
        
        if (result.success) {
            showToast(result.message, 'success');
            loadPendingStats();
            if (typeof loadRecentDiaries === 'function') loadRecentDiaries();
        } else {
            showToast(result.message || '转换失败', 'error');
        }
    } catch (e) {
        showToast('转换失败: ' + e.message, 'error');
    }
}

async function consolidatePending(date) {
    if (!confirm(`确定要将 ${date} 的摘要汇总成日记吗？`)) return;
    
    showToast('正在汇总...', 'info');
    
    try {
        const result = await apiCall('/pending/consolidate', 'POST', { date });
        
        if (result.success) {
            showToast(result.message, 'success');
            loadPendingStats();
            if (typeof loadRecentDiaries === 'function') loadRecentDiaries();
        } else {
            showToast(result.message || '汇总失败', 'error');
        }
    } catch (e) {
        showToast('汇总失败', 'error');
    }
}

async function consolidateAllPending() {
    if (!confirm('确定要智能汇总所有已结束的会话吗？\n\n系统会自动识别"睡眠间隔"，每个清醒周期生成独立日记。')) return;
    
    showToast('正在智能汇总...可能需要一些时间', 'info');
    
    try {
        const result = await apiCall('/pending/consolidate-all', 'POST', {});
        
        if (result.success) {
            showToast(result.message, 'success');
            loadPendingStats();
            if (typeof loadRecentDiaries === 'function') loadRecentDiaries();
        } else {
            showToast(result.message || '汇总失败', 'error');
        }
    } catch (e) {
        showToast('汇总失败', 'error');
    }
}

async function viewSession(sessionId) {
    try {
        const data = await apiCall(`/pending?session_id=${sessionId}`);
        
        const startTime = new Date(data.start_time);
        const endTime = new Date(data.end_time);
        
        let html = `
        <h4 style="margin-bottom: 15px;">
            🕐 会话 ${sessionId}
            <span style="font-size: 0.8rem; color: var(--text-dim); margin-left: 10px;">
                ${startTime.toLocaleString('zh-CN')} ~ ${endTime.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})}
            </span>
        </h4>
        <p style="color: var(--text-dim); margin-bottom: 15px;">共 ${data.count} 条摘要</p>`;
        
        if (data.summaries && data.summaries.length > 0) {
            data.summaries.forEach((s, i) => {
                const time = (s.timestamp || '').substring(11, 16);
                html += `
                <div style="background: var(--surface-2); padding: 12px; margin-bottom: 10px; border-radius: 6px; border-left: 3px solid var(--accent);">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-weight: 600;">${escapeHtml(time)} - ${escapeHtml(s.topic || '')}</span>
                        <span style="color: var(--text-dim); font-size: 0.8rem;">${s.raw_turns || 0} 轮对话</span>
                    </div>
                    <p style="color: var(--text-dim); margin: 0; font-size: 0.9rem;">${escapeHtml(s.summary || '')}</p>
                    ${s.tool_calls && s.tool_calls.length > 0 ? `<div style="margin-top: 8px; font-size: 0.75rem; color: var(--accent);">🔧 ${s.tool_calls.map(t => escapeHtml(t)).join(', ')}</div>` : ''}
                </div>`;
            });
        } else {
            html += '<p style="color: var(--text-dim);">无摘要</p>';
        }
        
        showModal(html);
    } catch (e) {
        showToast('加载失败', 'error');
    }
}

async function viewPending(date) {
    try {
        const data = await apiCall(`/pending?date=${encodeURIComponent(date)}`);
        
        if (data && data.error) {
            showToast('加载失败: ' + data.error, 'error');
            return;
        }
        
        let html = `<h4 style="margin-bottom: 15px;">${escapeHtml(date)} 的待处理摘要 (${data.count || 0} 条)</h4>`;
        
        if (data.summaries && data.summaries.length > 0) {
            data.summaries.forEach((s, i) => {
                const time = (s.timestamp || '').substring(11, 16);
                html += `
                <div style="background: var(--surface-2); padding: 12px; margin-bottom: 10px; border-radius: 6px; border-left: 3px solid var(--accent);">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-weight: 600;">${escapeHtml(time)} - ${escapeHtml(s.topic || '')}</span>
                        <span style="color: var(--text-dim); font-size: 0.8rem;">${s.raw_turns || 0} 轮对话</span>
                    </div>
                    <p style="color: var(--text-dim); margin: 0; font-size: 0.9rem;">${escapeHtml(s.summary || '')}</p>
                </div>`;
            });
        } else {
            html += '<p style="color: var(--text-dim);">无摘要</p>';
        }
        
        showModal(html);
    } catch (e) {
        showToast('加载失败: ' + e.message, 'error');
    }
}

// ===== 归档会话管理 =====
async function loadArchivedSessions() {
    const container = document.getElementById('archived-sessions');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    try {
        const data = await apiCall('/pending/archived');
        
        if (!data.sessions || data.sessions.length === 0) {
            container.innerHTML = '<p style="color: var(--text-dim);">没有已归档的会话</p>';
            return;
        }
        
        let html = `<p style="color: var(--text-dim); margin-bottom: 15px;">共 ${data.total} 个已归档会话</p>`;
        html += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 15px;">';
        
        for (const session of data.sessions) {
            const startTime = new Date(session.start_time);
            const endTime = new Date(session.end_time);
            const dateStr = startTime.toLocaleDateString('zh-CN');
            const startStr = startTime.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'});
            const endStr = endTime.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'});
            
            const topics = (session.topics || []).slice(0, 3).map(t => escapeHtml(t)).join('、');
            const moreTopics = (session.topics || []).length > 3 ? ` +${session.topics.length - 3}` : '';
            
            html += `
            <div style="background: var(--surface-2); padding: 15px; border-radius: 8px; border-left: 3px solid var(--text-dim); opacity: 0.8;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <span style="font-weight: 600; color: var(--text-dim);">📦 ${escapeHtml(dateStr)}</span>
                    <span class="badge" style="background: var(--surface); color: var(--text-dim);">已归档</span>
                </div>
                <div style="font-size: 0.85rem; color: var(--text-dim); margin-bottom: 8px;">
                    ${escapeHtml(startStr)} ~ ${escapeHtml(endStr)} | ${session.duration_minutes} 分钟 | ${session.summary_count} 条摘要
                </div>
                <div style="font-size: 0.8rem; color: var(--text-dim); margin-bottom: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    📝 ${topics}${moreTopics}
                </div>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-sm btn-warning" onclick="restoreSession('${escapeAttr(session.session_id)}')">🔄 恢复</button>
                    <button class="btn btn-sm" onclick="viewArchivedSession('${escapeAttr(session.session_id)}')">查看</button>
                </div>
            </div>`;
        }
        html += '</div>';
        
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<p style="color: var(--danger);">加载失败: ' + e.message + '</p>';
    }
}

async function restoreSession(sessionId) {
    if (!confirm(`确定要将会话 ${sessionId} 恢复到待处理列表吗？\n\n恢复后可以重新汇总。`)) return;
    
    try {
        const result = await apiCall(`/pending/restore/${sessionId}`, 'POST');
        
        if (result.success) {
            showToast(result.message || '会话已恢复', 'success');
            loadArchivedSessions();
            loadPendingStats();
        } else {
            showToast(result.message || '恢复失败', 'error');
        }
    } catch (e) {
        showToast('恢复失败: ' + e.message, 'error');
    }
}

async function viewArchivedSession(sessionId) {
    try {
        const data = await apiCall(`/pending/archived/${sessionId}`);
        
        if (data.error) {
            showToast('加载失败: ' + data.error, 'error');
            return;
        }
        
        const startTime = new Date(data.start_time);
        const endTime = new Date(data.end_time);
        
        let html = `
        <h4 style="margin-bottom: 15px;">
            📦 已归档会话 ${sessionId}
            <span style="font-size: 0.8rem; color: var(--text-dim); margin-left: 10px;">
                ${startTime.toLocaleString('zh-CN')} ~ ${endTime.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})}
            </span>
        </h4>
        <p style="color: var(--text-dim); margin-bottom: 15px;">共 ${data.count} 条摘要</p>`;
        
        if (data.summaries && data.summaries.length > 0) {
            data.summaries.forEach((s, i) => {
                const time = (s.timestamp || '').substring(11, 16);
                html += `
                <div style="background: var(--surface-2); padding: 12px; margin-bottom: 10px; border-radius: 6px; border-left: 3px solid var(--text-dim);">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-weight: 600;">${escapeHtml(time)} - ${escapeHtml(s.topic || '')}</span>
                        <span style="color: var(--text-dim); font-size: 0.8rem;">${s.raw_turns || 0} 轮对话</span>
                    </div>
                    <p style="color: var(--text-dim); margin: 0; font-size: 0.9rem;">${escapeHtml(s.summary || '')}</p>
                    ${s.tool_calls && s.tool_calls.length > 0 ? `<div style="margin-top: 8px; font-size: 0.75rem; color: var(--accent);">🔧 ${s.tool_calls.map(t => escapeHtml(t)).join(', ')}</div>` : ''}
                </div>`;
            });
        } else {
            html += '<p style="color: var(--text-dim);">无摘要</p>';
        }
        
        showModal(html);
    } catch (e) {
        showToast('加载失败', 'error');
    }
}

// ===== Modal 辅助函数 =====
// 注意: showModal 和 closeModal 已统一到 admin-core.js
// 本文件中的调用使用单参数模式 showModal(content)，会自动添加关闭按钮
/**
 * 对话管理模块
 *
 * 功能：
 * - 加载对话列表
 * - 查看对话详情
 * - 删除对话
 * - 总结对话为日记
 */

console.log('[对话管理] 脚本开始加载...');

// 立即定义诊断函数到全局
window.testConvAPI = async function() {
    console.log('[诊断] 开始测试对话 API...');
    try {
        const response = await fetch('/api/memory/conversations?days=30&limit=5');
        console.log('[诊断] 响应状态:', response.status);
        const data = await response.json();
        console.log('[诊断] 获取到数据:', data);
        return data;
    } catch (e) {
        console.error('[诊断] 请求失败:', e);
        return null;
    }
};

// 当前页码
let convCurrentPage = 0;
const convPageSize = 20;

// ==================== 初始化 ====================

/**
 * 初始化对话管理页面
 */
function initConversationsPage() {
    console.log('[对话管理] initConversationsPage 被调用');
    
    // 设置默认日期为今天
    const today = new Date().toISOString().split('T')[0];
    const dateInput = document.getElementById('conv-batch-date');
    if (dateInput) {
        dateInput.value = today;
    }
    
    // 只加载统计和日期，对话列表需要手动点击刷新
    loadConversationStats();
    loadConversationDates();
    loadConvDiaryConfig();
    
    // 显示提示信息而非自动加载
    const container = document.getElementById('conv-list');
    if (container) {
        container.innerHTML = '<p style="color: var(--text-dim); text-align: center; padding: 40px;">👆 点击上方「🔄 刷新」按钮加载对话列表</p>';
    }
    
    // 强制绑定刷新按钮事件（排查 onclick 不工作的问题）
    bindConversationButtons();
}

/**
 * 强制绑定对话管理页面的按钮事件
 */
function bindConversationButtons() {
    console.log('[对话管理] 开始绑定按钮事件...');
    
    // 查找对话列表卡片中的刷新按钮
    const refreshButtons = document.querySelectorAll('#conversations .btn-primary');
    console.log('[对话管理] 找到 btn-primary 按钮数量:', refreshButtons.length);
    
    refreshButtons.forEach((btn, index) => {
        if (btn.textContent.includes('刷新')) {
            console.log('[对话管理] 绑定刷新按钮 #' + index);
            btn.addEventListener('click', function(e) {
                console.log('[对话管理] 刷新按钮被点击 (addEventListener)');
                e.preventDefault();
                loadConversationsList();
            });
        }
    });
    
    // 也绑定 select 的 change 事件
    const daysFilter = document.getElementById('conv-days-filter');
    if (daysFilter) {
        console.log('[对话管理] 绑定天数筛选器');
        daysFilter.addEventListener('change', function() {
            console.log('[对话管理] 天数筛选器变更');
            loadConversationsList();
        });
    }
}

// ==================== 统计信息 ====================

/**
 * 加载对话统计信息
 */
async function loadConversationStats() {
    try {
        const response = await fetch('/api/memory/conversations/stats');
        if (!response.ok) throw new Error('加载失败');
        
        const data = await response.json();
        
        // 更新统计卡片
        document.getElementById('conv-stat-total').textContent = data.total_conversations || 0;
        document.getElementById('conv-stat-total-turns').textContent = data.total_turns || 0;
        
        if (data.today) {
            document.getElementById('conv-stat-today').textContent = data.today.conversations || 0;
            document.getElementById('conv-stat-today-turns').textContent = data.today.turns || 0;
        }
        
    } catch (error) {
        console.error('加载对话统计失败:', error);
    }
}

// ==================== 日期列表 ====================

/**
 * 加载有对话记录的日期列表
 */
async function loadConversationDates() {
    const container = document.getElementById('conv-dates-list');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    try {
        const response = await fetch('/api/memory/conversations/dates');
        if (!response.ok) throw new Error('加载失败');
        
        const data = await response.json();
        
        if (!data.dates || data.dates.length === 0) {
            container.innerHTML = '<p style="color: var(--text-dim);">暂无对话记录</p>';
            return;
        }
        
        // 只显示最近30个日期
        const dates = data.dates.slice(0, 30);
        
        container.innerHTML = dates.map(d => `
            <div style="display: inline-flex; align-items: stretch; gap: 2px;">
                <button class="btn btn-sm" onclick="filterConversationsByDate('${d.date}')"
                        style="display: flex; flex-direction: column; align-items: center; min-width: 70px; border-radius: 6px 0 0 6px;">
                    <span style="font-weight: 600;">${d.date.slice(5)}</span>
                    <span style="font-size: 0.7rem; color: var(--text-dim);">${d.count}个 / ${d.total_turns}轮</span>
                </button>
                <button class="btn btn-sm btn-success" onclick="event.stopPropagation(); quickSummarizeDay('${d.date}')"
                        title="将 ${d.date} 的对话总结为日记"
                        style="padding: 4px 6px; border-radius: 0; font-size: 0.75rem;">
                    📝
                </button>
                <button class="btn btn-sm" onclick="event.stopPropagation(); exportDayTimelineToMarkdown('${d.date}')"
                        title="导出 ${d.date} 的对话为 Markdown"
                        style="padding: 4px 6px; border-radius: 0 6px 6px 0; background: var(--surface-3); font-size: 0.75rem;">
                    📄
                </button>
            </div>
        `).join('');
        
    } catch (error) {
        container.innerHTML = `<div class="alert alert-danger">加载失败: ${error.message}</div>`;
    }
}

/**
 * 按日期过滤对话
 */
function filterConversationsByDate(date) {
    // 设置批量日期
    const dateInput = document.getElementById('conv-batch-date');
    if (dateInput) {
        dateInput.value = date;
    }
    
    // 加载该日期的对话
    loadConversationsList(date);
}

// ==================== 对话列表 ====================

/**
 * 加载对话列表
 * 注意：函数名改为 loadConversationsList 避免与 admin-graphiti.js 冲突
 */
async function loadConversationsList(dateFilter = null) {
    console.log('[对话管理] loadConversationsList 开始执行, dateFilter:', dateFilter);
    const container = document.getElementById('conv-list');
    const timelineEntry = document.getElementById('day-timeline-entry');
    const timelineDateLabel = document.getElementById('day-timeline-date');
    
    if (!container) {
        console.error('[对话管理] 找不到 conv-list 元素');
        return;
    }
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    // 显示/隐藏全天时间线入口（置顶显示）
    if (timelineEntry) {
        timelineEntry.style.display = dateFilter ? 'block' : 'none';
        if (dateFilter) {
            timelineEntry.dataset.date = dateFilter;
            if (timelineDateLabel) {
                timelineDateLabel.textContent = `(${dateFilter})`;
            }
        }
    }

    try {
        const days = document.getElementById('conv-days-filter')?.value || 30;
        let url = `/api/memory/conversations?days=${days}&limit=${convPageSize}&offset=${convCurrentPage * convPageSize}`;
        console.log('[对话管理] 请求URL:', url);
        
        if (dateFilter) {
            url = `/api/memory/conversations?date=${dateFilter}&limit=100`;
        }
        
        const response = await fetch(url);
        console.log('[对话管理] 响应状态:', response.status);
        if (!response.ok) throw new Error('加载失败: ' + response.status);
        
        const data = await response.json();
        console.log('[对话管理] 获取到数据:', data);
        
        if (!data.conversations || data.conversations.length === 0) {
            container.innerHTML = '<p style="color: var(--text-dim);">暂无对话记录</p>';
            updateConversationPagination(0, 0);
            return;
        }
        
        // 渲染对话列表
        console.log('[对话管理] 开始渲染', data.conversations.length, '个对话');
        try {
            const html = data.conversations.map((conv, idx) => {
                console.log('[对话管理] 渲染对话', idx, conv.session_id);
                return renderConversationItem(conv);
            }).join('');
            container.innerHTML = html;
            console.log('[对话管理] 渲染完成');
        } catch (renderErr) {
            console.error('[对话管理] 渲染失败:', renderErr);
            throw renderErr;
        }
        
        // 更新分页
        updateConversationPagination(data.total, data.offset);
        
    } catch (error) {
        container.innerHTML = `<div class="alert alert-danger">加载失败: ${error.message}</div>`;
    }
}

/**
 * 渲染单个对话项
 */
function renderConversationItem(conv) {
    const startTime = conv.start_time ? new Date(conv.start_time).toLocaleString('zh-CN') : '--';
    const firstMsg = conv.first_message?.user || '无内容';
    
    return `
        <div class="debug-log-item" onclick="showConversationDetail('${conv.session_id}')">
            <div class="debug-log-header">
                <div>
                    <span class="badge badge-info">${conv.turn_count}轮</span>
                    <span style="margin-left: 10px; font-weight: 500;">${conv.date || conv.session_id.split('_')[0]}</span>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-sm btn-success" onclick="event.stopPropagation(); summarizeConversation('${conv.session_id}')">📝 总结</button>
                    <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteConversation('${conv.session_id}')">🗑️</button>
                </div>
            </div>
            <div class="debug-log-meta">
                <span>🕐 ${startTime}</span>
                <span>🤖 ${conv.model || '未知'}</span>
                <span>🔑 ${conv.fingerprint || '--'}</span>
            </div>
            <div class="debug-log-preview">${escapeHtml(firstMsg)}</div>
        </div>
    `;
}

/**
 * 更新分页控件
 */
function updateConversationPagination(total, offset) {
    const container = document.getElementById('conv-pagination');
    if (!container) return;
    
    const totalPages = Math.ceil(total / convPageSize);
    const currentPage = Math.floor(offset / convPageSize);
    
    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = '';
    
    // 上一页
    if (currentPage > 0) {
        html += `<button class="btn btn-sm" onclick="convGoToPage(${currentPage - 1})">◀ 上一页</button>`;
    }
    
    // 页码信息
    html += `<span style="color: var(--text-dim);">第 ${currentPage + 1} / ${totalPages} 页</span>`;
    
    // 下一页
    if (currentPage < totalPages - 1) {
        html += `<button class="btn btn-sm" onclick="convGoToPage(${currentPage + 1})">下一页 ▶</button>`;
    }
    
    container.innerHTML = html;
}

/**
 * 跳转到指定页
 */
function convGoToPage(page) {
    convCurrentPage = page;
    loadConversationsList();
}

// ==================== 对话详情 ====================

/**
 * 显示对话详情弹窗
 */
async function showConversationDetail(sessionId) {
    try {
        const response = await fetch(`/api/memory/conversation/${sessionId}`);
        if (!response.ok) throw new Error('加载失败');
        
        const data = await response.json();
        
        // 构建详情内容 - 竖排：用户 → 思考过程 → 助手（符合对话流程）
        const turnsHtml = data.turns.map((turn, idx) => {
            // 渲染图片（如果有）- 使用 Lightbox 页内预览
            let imagesHtml = '';
            if (turn.images && turn.images.length > 0) {
                imagesHtml = `
                <div style="margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px;">
                    ${turn.images.map((imgPath, imgIdx) => `
                        <img src="/api/memory/conversations/image/${imgPath}"
                             alt="对话图片"
                             class="conv-preview-img"
                             style="max-width: 100px; max-height: 70px; border-radius: 6px; border: 1px solid var(--border); cursor: pointer; object-fit: cover;"
                             onclick="openImageLightbox('/api/memory/conversations/image/${imgPath}')"
                             onerror="this.style.display='none';">
                    `).join('')}
                </div>
                `;
            }
            
            // 思考过程 HTML
            const thinkingHtml = turn.metadata && turn.metadata.reasoning_content ? `
                <div style="margin-bottom: 12px; padding: 10px 12px; background: rgba(120, 100, 60, 0.15); border-radius: 8px; border-left: 3px solid #a08050;">
                    <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">
                        <span style="font-size: 0.95rem;">💭</span>
                        <strong style="color: #b89860; font-size: 0.85rem;">思考过程</strong>
                    </div>
                    <div style="padding: 8px 10px; background: rgba(0,0,0,0.2); border-radius: 5px; white-space: pre-wrap; max-height: 180px; overflow-y: auto; font-size: 0.82rem; line-height: 1.55; color: rgba(255,255,255,0.7);">${escapeHtml(turn.metadata.reasoning_content)}</div>
                </div>
            ` : '';
            
            return `
            <div style="margin-bottom: 20px; padding: 12px 14px; background: var(--surface-2); border-radius: 10px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border);">
                    <span class="badge badge-info" style="font-size: 0.75rem;">轮次 ${turn.turn_id}</span>
                    <span style="color: var(--text-dim); font-size: 0.78rem;">🕐 ${new Date(turn.timestamp).toLocaleString('zh-CN')}</span>
                </div>
                
                <!-- 用户消息（先显示用户提问） -->
                <div style="margin-bottom: 10px;">
                    <div style="display: flex; align-items: center; gap: 5px; margin-bottom: 6px;">
                        <span style="font-size: 0.9rem;">👤</span>
                        <strong style="color: #7090a0; font-size: 0.85rem;">用户</strong>
                    </div>
                    <div style="padding: 10px 12px; background: rgba(70, 100, 120, 0.25); border-radius: 8px; border-left: 3px solid #5080a0; white-space: pre-wrap; max-height: 250px; overflow-y: auto; line-height: 1.65; font-size: 0.9rem;">${escapeHtml(turn.user)}</div>
                    ${imagesHtml}
                </div>
                
                ${thinkingHtml}
                
                <!-- 助手回复 -->
                <div>
                    <div style="display: flex; align-items: center; gap: 5px; margin-bottom: 6px; margin-left: 20px;">
                        <span style="font-size: 0.9rem;">🤖</span>
                        <strong style="color: #70a070; font-size: 0.85rem;">助手</strong>
                    </div>
                    <div style="margin-left: 20px; padding: 10px 12px; background: rgba(80, 100, 80, 0.2); border-radius: 8px; border-left: 3px solid #608060; white-space: pre-wrap; max-height: 300px; overflow-y: auto; line-height: 1.65; font-size: 0.9rem;">${escapeHtml(turn.assistant)}</div>
                </div>
            </div>
        `}).join('');
        
        const modalHtml = `
            <div class="modal-overlay" onclick="closeConversationModal(event)">
                <div class="modal-container" style="max-width: 850px;" onclick="event.stopPropagation()">
                    <div class="modal-header">
                        <h3>💬 对话详情</h3>
                        <button class="btn btn-sm" onclick="closeConversationModal()">✕</button>
                    </div>
                    <div class="modal-body" style="max-height: 70vh; overflow-y: auto;">
                        <div style="margin-bottom: 15px; padding: 12px; background: var(--surface-2); border-radius: 8px;">
                            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; font-size: 0.9rem;">
                                <div>
                                    <span style="color: var(--text-dim);">会话ID：</span><br>
                                    <strong style="font-size: 0.8rem;">${data.session_id}</strong>
                                </div>
                                <div>
                                    <span style="color: var(--text-dim);">模型：</span><br>
                                    <strong>${data.header?.model || '未知'}</strong>
                                </div>
                                <div>
                                    <span style="color: var(--text-dim);">轮次：</span><br>
                                    <strong>${data.turns.length} 轮</strong>
                                </div>
                            </div>
                            ${data.header?.system_prompt_preview ? `
                            <div style="margin-top: 12px;">
                                <span style="color: var(--text-dim); font-size: 0.85rem;">系统提示词预览：</span>
                                <div style="margin-top: 4px; padding: 8px; background: var(--surface-3); border-radius: 5px; font-size: 0.8rem; max-height: 80px; overflow-y: auto;">${escapeHtml(data.header.system_prompt_preview)}</div>
                            </div>
                            ` : ''}
                        </div>
                        ${turnsHtml}
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-primary" onclick="exportConversationToMarkdown('${sessionId}')">📄 导出MD</button>
                        <button class="btn" onclick="previewConversationSummary('${sessionId}')">👁️ 预览总结</button>
                        <button class="btn btn-success" onclick="summarizeConversation('${sessionId}'); closeConversationModal();">📝 总结为日记</button>
                        <button class="btn btn-danger" onclick="deleteConversation('${sessionId}'); closeConversationModal();">🗑️ 删除</button>
                        <button class="btn" onclick="closeConversationModal()">关闭</button>
                    </div>
                </div>
            </div>
        `;
        
        // 显示弹窗
        const modalContainer = document.createElement('div');
        modalContainer.id = 'conv-detail-modal';
        modalContainer.innerHTML = modalHtml;
        document.body.appendChild(modalContainer);
        
    } catch (error) {
        showToast('加载对话详情失败: ' + error.message, 'error');
    }
}

/**
 * 关闭对话详情弹窗
 */
function closeConversationModal(event) {
    if (event && event.target !== event.currentTarget) return;
    
    const modal = document.getElementById('conv-detail-modal');
    if (modal) {
        modal.remove();
    }
}

// ==================== 对话操作 ====================

/**
 * 总结对话为日记（弹窗选择模式）
 */
async function summarizeConversation(sessionId) {
    // 弹出选择框：预览 or 直接保存
    const choice = confirm(
        '将此对话通过 LLM 总结为日记。\n\n' +
        '点击「确定」→ 直接总结并保存\n' +
        '点击「取消」→ 取消操作\n\n' +
        '提示：在对话详情弹窗中也可以使用此功能。'
    );
    if (!choice) return;

    try {
        showToast('正在调用 LLM 生成总结...', 'info');
        
        const response = await fetch(`/api/memory/conversation/${sessionId}/summarize`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ append: true })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '总结失败');
        }
        
        const data = await response.json();
        showToast(`✅ 已总结到日记 ${data.target_date}`, 'success');
        
    } catch (error) {
        showToast('总结失败: ' + error.message, 'error');
    }
}

/**
 * 预览单对话总结（不保存）
 */
async function previewConversationSummary(sessionId) {
    try {
        showToast('正在调用 LLM 预览总结...', 'info');
        
        const response = await fetch(`/api/memory/conversation/${sessionId}/summarize`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ preview_only: true })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '预览失败');
        }
        
        const data = await response.json();
        
        // 弹出预览窗口
        const previewHtml = `
            <div class="modal-overlay" onclick="closeConversationModal(event)">
                <div class="modal-container" style="max-width: 700px;" onclick="event.stopPropagation()">
                    <div class="modal-header">
                        <h3>👁️ 总结预览</h3>
                        <button class="btn btn-sm" onclick="closeConversationModal()">✕</button>
                    </div>
                    <div class="modal-body" style="max-height: 60vh; overflow-y: auto;">
                        <div style="padding: 15px; background: var(--surface-2); border-radius: 8px; white-space: pre-wrap; line-height: 1.7; font-size: 0.9rem;">${escapeHtml(data.summary)}</div>
                        <div style="margin-top: 10px; color: var(--text-dim); font-size: 0.8rem;">目标日期: ${data.target_date}</div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-success" onclick="confirmSingleSummary('${sessionId}', '${data.target_date}')">✅ 确认保存</button>
                        <button class="btn" onclick="closeConversationModal()">关闭</button>
                    </div>
                </div>
            </div>`;
        
        // 移除已有弹窗再创建
        const existingModal = document.getElementById('conv-preview-modal');
        if (existingModal) existingModal.remove();
        
        const modal = document.createElement('div');
        modal.id = 'conv-preview-modal';
        modal.innerHTML = previewHtml;
        document.body.appendChild(modal);
        
    } catch (error) {
        showToast('预览失败: ' + error.message, 'error');
    }
}

/**
 * 确认保存单对话总结
 */
async function confirmSingleSummary(sessionId, targetDate) {
    try {
        showToast('正在保存...', 'info');
        
        const response = await fetch(`/api/memory/conversation/${sessionId}/summarize`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ append: true, target_date: targetDate })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '保存失败');
        }
        
        const data = await response.json();
        showToast(`✅ 已保存到日记 ${data.target_date}`, 'success');
        
        // 关闭预览弹窗
        const modal = document.getElementById('conv-preview-modal');
        if (modal) modal.remove();
        
    } catch (error) {
        showToast('保存失败: ' + error.message, 'error');
    }
}

/**
 * 删除对话
 */
async function deleteConversation(sessionId) {
    if (!confirm('确定要删除此对话吗？（会备份到 .deleted 目录）')) return;
    
    try {
        const response = await fetch(`/api/memory/conversation/${sessionId}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '删除失败');
        }
        
        showToast('✅ 对话已删除', 'success');
        loadConversationsList();
        loadConversationStats();
        
    } catch (error) {
        showToast('删除失败: ' + error.message, 'error');
    }
}

/**
 * 预览全天日记总结
 */
async function previewDaySummary() {
    const dateInput = document.getElementById('conv-batch-date');
    const statusEl = document.getElementById('conv-batch-status');
    const date = dateInput?.value;
    
    if (!date) {
        showToast('请选择日期', 'error');
        return;
    }
    
    try {
        statusEl.textContent = '正在调用 LLM 生成预览...';
        statusEl.style.color = 'var(--accent)';
        
        const appendMode = document.getElementById('conv-day-append')?.checked ?? true;
        
        const response = await fetch(`/api/memory/conversations/day/${date}/summarize`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ preview_only: true, append: appendMode })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '预览失败');
        }
        
        const data = await response.json();
        
        // 显示预览区
        const previewEl = document.getElementById('conv-day-preview');
        const contentEl = document.getElementById('conv-day-preview-content');
        const statsEl = document.getElementById('conv-day-preview-stats');
        
        previewEl.style.display = 'block';
        contentEl.textContent = data.diary_content;
        previewEl.dataset.date = date;
        previewEl.dataset.diaryContent = data.diary_content;
        
        const stats = data.stats || {};
        statsEl.textContent = `📊 ${stats.conversations || '?'} 个会话 · ${stats.total_turns || '?'} 轮对话 · 模型: ${stats.model || '?'}`;
        
        statusEl.textContent = '✅ 预览已生成';
        statusEl.style.color = 'var(--success)';
        
    } catch (error) {
        statusEl.textContent = '❌ ' + error.message;
        statusEl.style.color = 'var(--danger)';
        showToast('预览失败: ' + error.message, 'error');
    }
}

/**
 * 确认保存全天日记
 */
async function confirmDaySummary() {
    const previewEl = document.getElementById('conv-day-preview');
    const date = previewEl?.dataset.date;
    const statusEl = document.getElementById('conv-batch-status');
    
    if (!date) {
        showToast('没有预览数据', 'error');
        return;
    }
    
    try {
        statusEl.textContent = '正在保存日记...';
        statusEl.style.color = 'var(--accent)';
        
        const appendMode = document.getElementById('conv-day-append')?.checked ?? true;
        
        const response = await fetch(`/api/memory/conversations/day/${date}/summarize`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ append: appendMode })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '保存失败');
        }
        
        const data = await response.json();
        showToast(`✅ ${data.message}`, 'success');
        statusEl.textContent = `✅ ${data.message}`;
        statusEl.style.color = 'var(--success)';
        closeDayPreview();
        
    } catch (error) {
        statusEl.textContent = '❌ ' + error.message;
        statusEl.style.color = 'var(--danger)';
        showToast('保存失败: ' + error.message, 'error');
    }
}

/**
 * 直接总结并保存（不预览）
 */
async function summarizeDayToDiary() {
    const dateInput = document.getElementById('conv-batch-date');
    const statusEl = document.getElementById('conv-batch-status');
    const date = dateInput?.value;
    
    if (!date) {
        showToast('请选择日期', 'error');
        return;
    }
    
    if (!confirm(`确定要将 ${date} 的所有对话通过 LLM 总结为日记吗？`)) return;
    
    try {
        statusEl.textContent = '正在调用 LLM 总结...';
        statusEl.style.color = 'var(--accent)';
        
        const appendMode = document.getElementById('conv-day-append')?.checked ?? true;
        
        const response = await fetch(`/api/memory/conversations/day/${date}/summarize`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ append: appendMode })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '总结失败');
        }
        
        const data = await response.json();
        statusEl.textContent = `✅ ${data.message}`;
        statusEl.style.color = 'var(--success)';
        showToast(`✅ ${data.message}`, 'success');
        
    } catch (error) {
        statusEl.textContent = '❌ ' + error.message;
        statusEl.style.color = 'var(--danger)';
        showToast('总结失败: ' + error.message, 'error');
    }
}

/**
 * 关闭全天预览
 */
function closeDayPreview() {
    const previewEl = document.getElementById('conv-day-preview');
    if (previewEl) {
        previewEl.style.display = 'none';
    }
}

/**
 * 批量总结对话（旧接口保留兼容）
 */
async function batchSummarizeConversations() {
    const dateInput = document.getElementById('conv-batch-date');
    const statusEl = document.getElementById('conv-batch-status');
    
    const date = dateInput?.value;
    if (!date) {
        showToast('请选择日期', 'error');
        return;
    }
    
    if (!confirm(`确定要将 ${date} 的所有对话逐个总结为日记吗？`)) return;
    
    try {
        statusEl.textContent = '正在处理...';
        statusEl.style.color = 'var(--accent)';
        
        const response = await fetch('/api/memory/conversations/batch-summarize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ date })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '批量总结失败');
        }
        
        const data = await response.json();
        statusEl.textContent = `✅ 已处理 ${data.processed_count} 个对话`;
        statusEl.style.color = 'var(--success)';
        
        showToast(`✅ 已将 ${data.processed_count} 个对话总结到日记 ${data.target_date}`, 'success');
        
    } catch (error) {
        statusEl.textContent = '❌ ' + error.message;
        statusEl.style.color = 'var(--danger)';
        showToast('批量总结失败: ' + error.message, 'error');
    }
}

// ==================== 总结提示词配置 ====================

/**
 * 加载对话→日记总结配置
 */
async function loadConvDiaryConfig() {
    try {
        const response = await fetch('/api/memory/conversations/diary-config');
        if (!response.ok) throw new Error('加载失败');
        
        const data = await response.json();
        
        document.getElementById('cfg-convdiary-model').value = data.using_defaults?.model ? '' : (data.model || '');
        document.getElementById('cfg-convdiary-max-tokens').value = data.max_tokens || 8192;
        document.getElementById('cfg-convdiary-temperature').value = data.temperature ?? 1;
        // 始终显示实际值（含默认值），方便用户基于默认提示词修改
        document.getElementById('cfg-convdiary-single-prompt').value = data.single_prompt || '';
        document.getElementById('cfg-convdiary-day-prompt').value = data.day_prompt || '';
        
        // 标记哪些是默认值
        const singleEl = document.getElementById('cfg-convdiary-single-prompt');
        const dayEl = document.getElementById('cfg-convdiary-day-prompt');
        if (data.using_defaults?.single_prompt) {
            singleEl.style.borderColor = 'var(--text-dim)';
            singleEl.title = '当前显示的是系统默认提示词，修改后保存即可覆盖';
        } else {
            singleEl.style.borderColor = '';
            singleEl.title = '已自定义';
        }
        if (data.using_defaults?.day_prompt) {
            dayEl.style.borderColor = 'var(--text-dim)';
            dayEl.title = '当前显示的是系统默认提示词，修改后保存即可覆盖';
        } else {
            dayEl.style.borderColor = '';
            dayEl.title = '已自定义';
        }
        
        showToast('✅ 配置已加载', 'success');
    } catch (error) {
        showToast('加载配置失败: ' + error.message, 'error');
    }
}

/**
 * 保存对话→日记总结配置
 */
async function saveConvDiaryConfig() {
    try {
        const payload = {
            model: document.getElementById('cfg-convdiary-model').value.trim(),
            max_tokens: parseInt(document.getElementById('cfg-convdiary-max-tokens').value) || 8192,
            temperature: parseFloat(document.getElementById('cfg-convdiary-temperature').value) ?? 1,
            single_prompt: document.getElementById('cfg-convdiary-single-prompt').value,
            day_prompt: document.getElementById('cfg-convdiary-day-prompt').value,
        };
        
        const response = await fetch('/api/memory/conversations/diary-config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) throw new Error('保存失败');
        
        showToast('✅ 配置已保存', 'success');
    } catch (error) {
        showToast('保存配置失败: ' + error.message, 'error');
    }
}

/**
 * 打开图片 Lightbox 预览
 */
function openImageLightbox(imgSrc) {
    // 创建 Lightbox 覆盖层
    const lightbox = document.createElement('div');
    lightbox.id = 'image-lightbox';
    lightbox.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background: rgba(0, 0, 0, 0.9);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
        cursor: zoom-out;
    `;
    lightbox.onclick = () => lightbox.remove();
    
    const img = document.createElement('img');
    img.src = imgSrc;
    img.style.cssText = `
        max-width: 90vw;
        max-height: 90vh;
        border-radius: 8px;
        box-shadow: 0 10px 50px rgba(0,0,0,0.5);
        object-fit: contain;
    `;
    img.onclick = (e) => e.stopPropagation();
    
    // 关闭按钮
    const closeBtn = document.createElement('button');
    closeBtn.innerHTML = '✕';
    closeBtn.style.cssText = `
        position: absolute;
        top: 20px;
        right: 30px;
        background: rgba(255,255,255,0.2);
        border: none;
        color: white;
        font-size: 24px;
        width: 40px;
        height: 40px;
        border-radius: 50%;
        cursor: pointer;
        transition: background 0.2s;
    `;
    closeBtn.onmouseover = () => closeBtn.style.background = 'rgba(255,255,255,0.3)';
    closeBtn.onmouseout = () => closeBtn.style.background = 'rgba(255,255,255,0.2)';
    closeBtn.onclick = () => lightbox.remove();
    
    lightbox.appendChild(img);
    lightbox.appendChild(closeBtn);
    document.body.appendChild(lightbox);
    
    // ESC 关闭
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            lightbox.remove();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
}

/**
 * 显示全天对话时间线
 */
async function showDayTimeline() {
    const timelineEntry = document.getElementById('day-timeline-entry');
    const date = timelineEntry?.dataset.date;
    if (!date) return;

    try {
        showToast(`正在加载 ${date} 的全天时间线...`, 'info');
        const response = await fetch(`/api/memory/conversations/day/${date}`);
        if (!response.ok) throw new Error('加载时间线失败');
        
        const data = await response.json();
        
        if (!data.turns || data.turns.length === 0) {
            showToast('该日无对话记录', 'warning');
            return;
        }

        // 构建时间线内容 - 竖排：用户 → 思考过程 → 助手（符合对话流程）
        const turnsHtml = data.turns.map((turn, idx) => {
            // 图片使用 Lightbox
            let imagesHtml = '';
            if (turn.images && turn.images.length > 0) {
                imagesHtml = `
                <div style="margin-top: 6px; display: flex; flex-wrap: wrap; gap: 6px;">
                    ${turn.images.map(imgPath => `
                        <img src="/api/memory/conversations/image/${imgPath}"
                             style="max-width: 70px; max-height: 50px; border-radius: 4px; border: 1px solid var(--border); cursor: pointer; object-fit: cover;"
                             onclick="event.stopPropagation(); openImageLightbox('/api/memory/conversations/image/${imgPath}')"
                             onerror="this.style.display='none';">
                    `).join('')}
                </div>`;
            }

            // 思考过程
            const thinkingHtml = turn.metadata?.reasoning_content ? `
                <div style="margin-bottom: 10px; padding: 8px 10px; background: rgba(120, 100, 60, 0.15); border-radius: 6px; border-left: 3px solid #a08050;">
                    <div style="display: flex; align-items: center; gap: 5px; margin-bottom: 5px; font-size: 0.78rem;">
                        <span>💭</span>
                        <strong style="color: #b89860;">思考过程</strong>
                    </div>
                    <div style="padding: 6px 8px; background: rgba(0,0,0,0.2); border-radius: 4px; white-space: pre-wrap; max-height: 120px; overflow-y: auto; font-size: 0.78rem; line-height: 1.5; color: rgba(255,255,255,0.65);">${escapeHtml(turn.metadata.reasoning_content)}</div>
                </div>` : '';

            return `
            <div style="margin-bottom: 16px; padding: 12px; background: var(--surface-2); border-radius: 8px; border-left: 3px solid #607080;">
                <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--text-dim); margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px dashed var(--border);">
                    <span>🕒 ${new Date(turn.timestamp).toLocaleTimeString('zh-CN')}</span>
                    <span style="cursor: pointer; text-decoration: underline; color: #7090a0;" onclick="closeConversationModal(); setTimeout(() => showConversationDetail('${turn.session_id}'), 100);">查看完整会话 →</span>
                </div>
                
                <!-- 用户消息（先显示用户提问） -->
                <div style="margin-bottom: 8px;">
                    <div style="display: flex; align-items: center; gap: 4px; margin-bottom: 5px; font-size: 0.8rem;">
                        <span>👤</span>
                        <strong style="color: #7090a0;">用户</strong>
                    </div>
                    <div style="padding: 8px 10px; background: rgba(70, 100, 120, 0.25); border-radius: 6px; border-left: 2px solid #5080a0; white-space: pre-wrap; max-height: 120px; overflow-y: auto; font-size: 0.85rem; line-height: 1.55;">${escapeHtml(turn.user)}</div>
                    ${imagesHtml}
                </div>
                
                ${thinkingHtml}
                
                <!-- 助手回复 -->
                <div>
                    <div style="display: flex; align-items: center; gap: 4px; margin-bottom: 5px; margin-left: 15px; font-size: 0.8rem;">
                        <span>🤖</span>
                        <strong style="color: #70a070;">助手</strong>
                    </div>
                    <div style="margin-left: 15px; padding: 8px 10px; background: rgba(80, 100, 80, 0.2); border-radius: 6px; border-left: 2px solid #608060; white-space: pre-wrap; max-height: 150px; overflow-y: auto; font-size: 0.85rem; line-height: 1.55;">${escapeHtml(turn.assistant)}</div>
                </div>
            </div>`;
        }).join('');

        const modalHtml = `
            <div class="modal-overlay" onclick="closeConversationModal(event)">
                <div class="modal-container" style="max-width: 900px;" onclick="event.stopPropagation()">
                    <div class="modal-header">
                        <h3>📅 全天对话时间线 (${date})</h3>
                        <button class="btn btn-sm" onclick="closeConversationModal()">✕</button>
                    </div>
                    <div class="modal-body" style="max-height: 80vh; overflow-y: auto; padding: 20px;">
                        <!-- 统计信息置顶 -->
                        <div style="margin-bottom: 15px; padding: 12px; background: var(--surface-2); border-radius: 8px; text-align: center;">
                            <div style="display: flex; justify-content: center; gap: 25px; color: var(--text-dim); font-size: 0.9rem;">
                                <span>💬 共 <strong style="color: #70a070;">${data.total_turns}</strong> 轮对话</span>
                                <span>📂 跨越 <strong style="color: #7090a0;">${Object.keys(data.sessions).length}</strong> 个独立会话</span>
                            </div>
                        </div>
                        <div class="timeline-container">
                            ${turnsHtml}
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-primary" onclick="exportDayTimelineToMarkdown('${date}')">📄 导出MD</button>
                        <button class="btn btn-success" onclick="closeConversationModal(); setTimeout(() => { document.getElementById('conv-batch-date').value='${date}'; previewDaySummary(); }, 200);">📝 总结为日记</button>
                        <button class="btn" onclick="closeConversationModal()">关闭</button>
                    </div>
                </div>
            </div>`;

        const modalContainer = document.createElement('div');
        modalContainer.id = 'conv-detail-modal';
        modalContainer.innerHTML = modalHtml;
        document.body.appendChild(modalContainer);

    } catch (error) {
        showToast('加载时间线失败: ' + error.message, 'error');
    }
}

// ==================== 导出 Markdown 功能 ====================

/**
 * 导出单个对话为 Markdown 文档
 */
async function exportConversationToMarkdown(sessionId) {
    try {
        showToast('正在生成 Markdown...', 'info');
        
        const response = await fetch(`/api/memory/conversation/${sessionId}`);
        if (!response.ok) throw new Error('加载对话失败');
        
        const data = await response.json();
        
        // 生成 Markdown 内容
        let md = `# 对话记录\n\n`;
        md += `- **会话ID**: ${data.session_id}\n`;
        md += `- **模型**: ${data.header?.model || '未知'}\n`;
        md += `- **轮次**: ${data.turns.length} 轮\n`;
        md += `- **时间**: ${data.turns[0]?.timestamp ? new Date(data.turns[0].timestamp).toLocaleString('zh-CN') : '--'}\n\n`;
        
        if (data.header?.system_prompt_preview) {
            md += `## 系统提示词\n\n\`\`\`\n${data.header.system_prompt_preview}\n\`\`\`\n\n`;
        }
        
        md += `---\n\n`;
        
        data.turns.forEach((turn, idx) => {
            md += `## 轮次 ${turn.turn_id}\n\n`;
            md += `*${new Date(turn.timestamp).toLocaleString('zh-CN')}*\n\n`;
            
            md += `### 👤 用户\n\n${turn.user}\n\n`;
            
            if (turn.images && turn.images.length > 0) {
                md += `**附图**: ${turn.images.map(p => `\`${p}\``).join(', ')}\n\n`;
            }
            
            if (turn.metadata?.reasoning_content) {
                md += `### 💭 思考过程\n\n`;
                md += `> ${turn.metadata.reasoning_content.split('\n').join('\n> ')}\n\n`;
            }
            
            md += `### 🤖 助手\n\n${turn.assistant}\n\n`;
            
            md += `---\n\n`;
        });
        
        // 下载文件
        downloadMarkdown(md, `conversation_${sessionId}.md`);
        showToast('✅ Markdown 已导出', 'success');
        
    } catch (error) {
        showToast('导出失败: ' + error.message, 'error');
    }
}

/**
 * 导出全天时间线为 Markdown 文档
 */
async function exportDayTimelineToMarkdown(date) {
    try {
        showToast('正在生成 Markdown...', 'info');
        
        const response = await fetch(`/api/memory/conversations/day/${date}`);
        if (!response.ok) throw new Error('加载时间线失败');
        
        const data = await response.json();
        
        // 生成 Markdown 内容
        let md = `# ${date} 对话时间线\n\n`;
        md += `- **总轮次**: ${data.total_turns} 轮\n`;
        md += `- **独立会话**: ${Object.keys(data.sessions).length} 个\n\n`;
        md += `---\n\n`;
        
        data.turns.forEach((turn, idx) => {
            const time = new Date(turn.timestamp).toLocaleTimeString('zh-CN');
            md += `## ${time}\n\n`;
            md += `*会话: ${turn.session_id}*\n\n`;
            
            md += `### 👤 用户\n\n${turn.user}\n\n`;
            
            if (turn.images && turn.images.length > 0) {
                md += `**附图**: ${turn.images.map(p => `\`${p}\``).join(', ')}\n\n`;
            }
            
            if (turn.metadata?.reasoning_content) {
                md += `### 💭 思考过程\n\n`;
                md += `> ${turn.metadata.reasoning_content.split('\n').join('\n> ')}\n\n`;
            }
            
            md += `### 🤖 助手\n\n${turn.assistant}\n\n`;
            
            md += `---\n\n`;
        });
        
        // 下载文件
        downloadMarkdown(md, `timeline_${date}.md`);
        showToast('✅ Markdown 已导出', 'success');
        
    } catch (error) {
        showToast('导出失败: ' + error.message, 'error');
    }
}

/**
 * 下载 Markdown 文件
 */
function downloadMarkdown(content, filename) {
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ==================== 全局函数暴露 ====================
// 确保所有函数都在全局作用域可用（防止某些情况下的作用域问题）
window.initConversationsPage = initConversationsPage;
window.loadConversationStats = loadConversationStats;
window.loadConversationDates = loadConversationDates;
window.filterConversationsByDate = filterConversationsByDate;
window.loadConversationsList = loadConversationsList;
window.convGoToPage = convGoToPage;
window.showConversationDetail = showConversationDetail;
window.showDayTimeline = showDayTimeline;
window.closeConversationModal = closeConversationModal;
window.summarizeConversation = summarizeConversation;
window.previewConversationSummary = previewConversationSummary;
window.confirmSingleSummary = confirmSingleSummary;
window.previewDaySummary = previewDaySummary;
window.confirmDaySummary = confirmDaySummary;
window.summarizeDayToDiary = summarizeDayToDiary;
window.closeDayPreview = closeDayPreview;
window.deleteConversation = deleteConversation;
window.batchSummarizeConversations = batchSummarizeConversations;
window.loadConvDiaryConfig = loadConvDiaryConfig;
window.saveConvDiaryConfig = saveConvDiaryConfig;

/**
 * 快速总结某天对话为日记（从日期列表直接触发）
 */
async function quickSummarizeDay(date) {
    // 先填入日期
    const dateInput = document.getElementById('conv-batch-date');
    if (dateInput) dateInput.value = date;
    
    // 直接预览
    previewDaySummary();
}

window.quickSummarizeDay = quickSummarizeDay;
window.openImageLightbox = openImageLightbox;
window.exportConversationToMarkdown = exportConversationToMarkdown;
window.exportDayTimelineToMarkdown = exportDayTimelineToMarkdown;
window.downloadMarkdown = downloadMarkdown;

// ==================== 模块加载完成 ====================
console.log('[对话管理] admin-conversations.js 模块已加载完成');
console.log('[对话管理] loadConversationsList 函数已注册:', typeof loadConversationsList);
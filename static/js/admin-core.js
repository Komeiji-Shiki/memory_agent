/**
 * Admin Core - 核心函数
 * - 导航
 * - Toast 通知
 * - API 调用
 * - 工具函数
 */

// ===== 导航 =====
window.addEventListener('beforeunload', function(event) {
    if (typeof hasUnsavedModelRoutesChanges === 'function' && hasUnsavedModelRoutesChanges()) {
        event.preventDefault();
        event.returnValue = '';
    }
});

document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', function() {
        const currentPageId = document.querySelector('.page.active')?.id;
        const pageId = this.dataset.page;

        if (currentPageId === 'models' && pageId !== 'models') {
            if (typeof confirmModelRoutesPageLeave === 'function' && !confirmModelRoutesPageLeave('切换到其他页面')) {
                return;
            }
        }

        document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        
        this.classList.add('active');
        document.getElementById(pageId).classList.add('active');
        
        // 页面加载时刷新数据
        if (pageId === 'memory') {
            if (typeof loadPendingStats === 'function') loadPendingStats();
            if (typeof loadArchivedSessions === 'function') loadArchivedSessions();
            if (typeof loadRecentDiaries === 'function') loadRecentDiaries();
        }
        if (pageId === 'backup' && typeof loadBackups === 'function') loadBackups();
        if (pageId === 'models' && typeof loadModelRoutes === 'function') loadModelRoutes();
        if (pageId === 'summary') {
            if (typeof loadSummaryConfig === 'function') loadSummaryConfig();
            if (typeof loadExistingSummaries === 'function') loadExistingSummaries();
            if (typeof updateSummaryIdentifier === 'function') updateSummaryIdentifier();
        }
        if (pageId === 'rag') {
            if (typeof loadRagStats === 'function') loadRagStats();
            if (typeof loadRagConfig === 'function') loadRagConfig();
        }
        if (pageId === 'graph' && typeof initGraph === 'function') {
            initGraph();
        }
        if (pageId === 'graphiti' && typeof initGraphitiPage === 'function') {
            initGraphitiPage();
        }
        if (pageId === 'extra' && typeof loadExtraMount === 'function') {
            loadExtraMount();
        }
        if (pageId === 'debug' && typeof loadDebugLogs === 'function') {
            loadDebugLogs();
        }
        if (pageId === 'orchestrator' && typeof loadOrchestratorPage === 'function') {
            loadOrchestratorPage();
        }
        if (pageId === 'conversations' && typeof initConversationsPage === 'function') {
            initConversationsPage();
        }
    });
});

// ===== Toast 通知 =====
function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.style.borderColor = type === 'success' ? 'var(--success)' : 
                               type === 'error' ? 'var(--danger)' : 'var(--accent)';
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
}

// ===== API 调用 =====
const API_BASE = '/api/memory';

async function apiCall(endpoint, method = 'GET', data = null) {
    try {
        const options = { method, headers: { 'Content-Type': 'application/json' } };
        if (data) options.body = JSON.stringify(data);
        const res = await fetch(API_BASE + endpoint, options);
        return await res.json();
    } catch (e) {
        console.error('API Error:', e);
        return { error: e.message };
    }
}

// ===== 工具函数 =====
async function togglePassword(input) {
    if (typeof input === 'string') {
        input = document.getElementById(input);
    }
    if (!input) return;

    const shouldReveal = input.type === 'password';
    if (shouldReveal) {
        await revealSecretIfMasked(input);
    }
    input.type = input.type === 'password' ? 'text' : 'password';
}

function getObjectPathValue(obj, path) {
    if (!obj || !path) return undefined;
    return path.split('.').reduce((acc, key) => {
        if (acc && Object.prototype.hasOwnProperty.call(acc, key)) {
            return acc[key];
        }
        return undefined;
    }, obj);
}

async function revealSecretIfMasked(input) {
    const currentValue = input.value || '';
    if (!currentValue.includes('****')) return;

    const endpoint = input.dataset.revealEndpoint;
    if (!endpoint) return;

    const queryConnector = endpoint.includes('?') ? '&' : '?';
    const revealEndpoint = `${endpoint}${queryConnector}reveal_secrets=1`;
    const data = await apiCall(revealEndpoint);
    if (!data) return;

    let nextValue;
    const revealPath = input.dataset.revealPath;
    if (revealPath) {
        nextValue = getObjectPathValue(data, revealPath);
    } else {
        const routeName = input.dataset.revealRoute
            || input.closest('.route-card')?.querySelector('[data-field="name"]')?.value?.trim();
        if (routeName) {
            nextValue = data?.value?.[routeName]?.api_key;
        }
    }

    if (typeof nextValue === 'string' && nextValue) {
        input.value = nextValue;
    }
}

function toggleCollapsible(element) {
    element.classList.toggle('open');
}

function escapeHtml(text, convertNewlines = false) {
    if (!text) return '';
    let result = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    
    if (convertNewlines) {
        result = result.replace(/\n/g, '<br>');
    }
    return result;
}

/**
 * 转义用于 HTML 属性（特别是 onclick 等事件处理器）中的字符串
 * 对单引号、双引号、反斜杠进行转义，防止注入攻击
 * @param {string} str - 需要转义的字符串
 * @returns {string} 转义后的字符串
 */
function escapeAttr(str) {
    if (!str) return '';
    return String(str)
        .replace(/\\/g, '\\\\')  // 反斜杠先处理
        .replace(/'/g, "\\'")     // 单引号
        .replace(/"/g, '\\"')     // 双引号
        .replace(/\n/g, '\\n')    // 换行符
        .replace(/\r/g, '\\r');   // 回车符
}

/**
 * 转义用于 HTML 属性值的字符串（用在 value="" 等属性中）
 * @param {string} str - 需要转义的字符串
 * @returns {string} 转义后的字符串
 */
function escapeAttrValue(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// ===== 通用弹窗函数 =====
/**
 * 显示模态弹窗
 * @param {string} titleOrContent - 标题，或者当只有一个参数时作为内容
 * @param {string} [content] - 弹窗内容（HTML）
 * @param {string} [size='normal'] - 尺寸：'normal' 或 'large'
 */
function showModal(titleOrContent, content, size = 'normal') {
    // 关闭已有弹窗
    closeModal();
    
    // 兼容单参数调用（只传内容）
    let title = '';
    let bodyContent = '';
    if (content === undefined) {
        // 单参数模式：titleOrContent 实际是 content
        bodyContent = titleOrContent;
    } else {
        title = titleOrContent;
        bodyContent = content;
    }
    
    const widthStyle = size === 'large' ? 'max-width: 800px; width: 90%;' : 'max-width: 600px;';
    
    const modal = document.createElement('div');
    modal.id = 'memory-modal';
    modal.className = 'modal-overlay';
    
    // 构建 HTML
    let headerHtml = '';
    if (title) {
        headerHtml = `
            <div style="padding: 20px; border-bottom: 1px solid var(--line-weak); display: flex; justify-content: space-between; align-items: center;">
                <h3 style="margin: 0;">${title}</h3>
                <button onclick="closeModal()" style="background: none; border: none; font-size: 1.5rem; cursor: pointer; color: var(--text-dim);">&times;</button>
            </div>`;
    }
    
    modal.innerHTML = `
        <div class="modal-backdrop" style="position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 20px;">
            <div class="modal-content" style="${widthStyle} background: var(--surface-1); border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,0.4); max-height: 90vh; overflow-y: auto;">
                ${headerHtml}
                <div style="padding: 20px;">
                    ${bodyContent}
                    ${!title ? '<button class="btn" style="margin-top: 15px;" onclick="closeModal()">关闭</button>' : ''}
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    
    // 点击背景关闭（只有点击背景层才关闭，点击内容区域不关闭）
    const backdrop = modal.querySelector('.modal-backdrop');
    backdrop.addEventListener('click', (e) => {
        // 只有直接点击背景层时才关闭
        if (e.target === backdrop) {
            closeModal();
        }
    });
}

/**
 * 关闭模态弹窗
 */
function closeModal() {
    // 兼容多种 modal ID
    const modalIds = ['memory-modal'];
    modalIds.forEach(id => {
        const modal = document.getElementById(id);
        if (modal) {
            modal.remove();
        }
    });
    
    // 也处理 class 为 modal-overlay 的元素
    const overlays = document.querySelectorAll('.modal-overlay');
    overlays.forEach(overlay => overlay.remove());
}

// ===== 统计刷新 =====
async function refreshStats(rebuildIndex = true) {
    // 先重建索引确保数据最新
    if (rebuildIndex) {
        try {
            await apiCall('/rebuild-index', 'POST');
        } catch (e) {
            console.warn('索引重建失败:', e);
        }
    }
    
    const stats = await apiCall('/stats');
    if (stats && !stats.error) {
        document.getElementById('stat-diaries').textContent = stats.diary_count || 0;
        document.getElementById('stat-tags').textContent = stats.tag_count || 0;
        // 修复：显示所有节点数量（类型格式为 node_人物, node_地点 等）
        const byType = stats.by_type || {};
        let totalNodes = 0;
        for (const [key, count] of Object.entries(byType)) {
            if (key.startsWith('node_')) {
                totalNodes += count;
            }
        }
        document.getElementById('stat-people').textContent = totalNodes;
        document.getElementById('stat-interactions').textContent = stats.interaction_count || 0;
        document.getElementById('memory-status').textContent = `${stats.diary_count || 0} 条日记`;
        
        if (stats.last_interaction) {
            document.getElementById('last-interaction').textContent = `上次: ${stats.last_interaction}`;
        }
    }
}

// ===== 可用模型 =====
async function refreshModels() {
    const container = document.getElementById('available-models');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    try {
        const res = await fetch('/v1/models');
        const data = await res.json();
        
        if (data.data && data.data.length > 0) {
            let html = '<table class="table"><thead><tr><th>模型ID</th><th>类型</th></tr></thead><tbody>';
            data.data.forEach(m => {
                const modelId = m.id;
                const isManager = ['memory-manager', 'memory-agent', 'lifebook'].includes(modelId);
                let badge = '';
                
                if (modelId.endsWith('-memory')) {
                    badge = '<span class="badge badge-success">记忆增强</span>';
                } else if (modelId.endsWith('-memory-simple')) {
                    badge = '<span class="badge badge-success">记忆增强(简化)</span>';
                } else if (modelId.endsWith('-record')) {
                    badge = '<span class="badge badge-warning">记录+总结</span>';
                } else if (modelId.endsWith('-log')) {
                    badge = '<span class="badge badge-info">仅日志</span>';
                } else if (modelId.endsWith('-log-write')) {
                    badge = '<span class="badge badge-warning">日志+记忆读写</span>';
                } else if (isManager) {
                    badge = '<span class="badge badge-warning">记忆管理</span>';
                } else {
                    badge = '<span class="badge badge-info">透传</span>';
                }
                
                html += `<tr><td><code>${m.id}</code></td><td>${badge}</td></tr>`;
            });
            html += '</tbody></table>';
            container.innerHTML = html;
        } else {
            container.innerHTML = '<p style="color: var(--text-dim);">暂无模型</p>';
        }
    } catch (e) {
        container.innerHTML = '<p style="color: var(--danger);">加载失败</p>';
    }
}

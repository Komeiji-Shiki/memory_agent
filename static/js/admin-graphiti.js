/**
 * Admin Graphiti - Graphiti 时序知识图谱管理模块
 * 
 * 功能：
 * - Graphiti 配置管理
 * - 后端状态监控
 * - Token 使用量追踪
 * - 同步和索引管理
 * - 搜索测试
 * - 对话保留配置
 */

// ========== 配置管理 ==========

/**
 * 加载 Graphiti 配置
 */
async function loadGraphitiConfig() {
    try {
        const res = await fetch('/api/memory/graphiti/config');
        const config = await res.json();
        
        if (config.error) {
            showToast('加载配置失败: ' + config.error, 'error');
            return;
        }
        
        // 基本设置
        document.getElementById('cfg-graphiti-enabled').checked = config.enabled || false;
        document.getElementById('cfg-graphiti-backend').value = config.backend || 'kuzu';
        
        // 根据后端切换显示
        toggleGraphitiBackend(config.backend || 'kuzu');
        
        // Kuzu 设置
        if (config.kuzu) {
            document.getElementById('cfg-kuzu-path').value = config.kuzu.db_path || './lifebook/.graphiti.kuzu';
        }
        
        // Neo4j 设置
        if (config.neo4j) {
            document.getElementById('cfg-neo4j-uri').value = config.neo4j.uri || 'bolt://localhost:7687';
            document.getElementById('cfg-neo4j-user').value = config.neo4j.username || 'neo4j';
            // 密码不回填（安全考虑）
        }
        
        // LLM 配置
        if (config.llm) {
            document.getElementById('cfg-graphiti-llm-url').value = config.llm.base_url || '';
            // 原样回填 API Key
            document.getElementById('cfg-graphiti-llm-key').value = config.llm.api_key || '';
            document.getElementById('cfg-graphiti-model').value = config.llm.model || 'gpt-4o-mini';
        }
        
        // Embedding 配置（独立于 LLM）
        if (config.embedding) {
            document.getElementById('cfg-graphiti-embed-url').value = config.embedding.base_url || '';
            // 原样回填 Embedding API Key
            document.getElementById('cfg-graphiti-embed-key').value = config.embedding.api_key || '';
            document.getElementById('cfg-graphiti-embed-model').value = config.embedding.model || 'text-embedding-3-small';
            document.getElementById('cfg-graphiti-embed-dim').value = config.embedding.dim || 1536;
        } else if (config.llm) {
            // 兼容旧配置：从 llm 节点读取
            document.getElementById('cfg-graphiti-embed-url').value = config.llm.base_url || '';
            document.getElementById('cfg-graphiti-embed-model').value = config.llm.embedding_model || 'text-embedding-3-small';
            document.getElementById('cfg-graphiti-embed-dim').value = config.llm.embedding_dim || 1536;
        }
        
        // Reranker 设置
        if (config.reranker) {
            document.getElementById('cfg-graphiti-reranker').checked = config.reranker.enabled || false;
        }
        
        // 检索策略
        if (config.retrieval) {
            document.getElementById('cfg-graphiti-strategy').value = config.retrieval.strategy || 'auto';
            document.getElementById('cfg-graphiti-max-iter').value = config.retrieval.max_iterations || 3;
            document.getElementById('cfg-graphiti-min-evidence').value = config.retrieval.min_evidence_count || 2;
            document.getElementById('cfg-graphiti-limit').value = config.retrieval.default_limit || 10;
            document.getElementById('cfg-graphiti-include-edges').checked = config.retrieval.include_edges !== false;
        }
        
        // 搜索配置
        if (config.search) {
            document.getElementById('cfg-graphiti-sim-score').value = config.search.sim_min_score || 0.4;
            document.getElementById('cfg-graphiti-mmr').value = config.search.mmr_lambda || 0.5;
        }
        
        // 性能配置
        if (config.performance) {
            document.getElementById('cfg-graphiti-daily-limit').value = config.performance.daily_token_limit || 100000;
            document.getElementById('cfg-graphiti-semaphore').value = config.performance.semaphore_limit || 10;
        }
        
        // 同步设置
        if (config.sync) {
            document.getElementById('cfg-graphiti-sync-conv').checked = config.sync.index_conversations !== false;
        }
        
        showToast('Graphiti 配置加载成功', 'success');
        
        // 同时刷新统计
        await refreshGraphitiStats();
        
    } catch (e) {
        showToast('加载配置失败: ' + e.message, 'error');
        console.error('loadGraphitiConfig error:', e);
    }
}

/**
 * 保存 Graphiti 配置
 */
async function saveGraphitiConfig() {
    try {
        // 收集配置
        const config = {
            enabled: document.getElementById('cfg-graphiti-enabled').checked,
            backend: document.getElementById('cfg-graphiti-backend').value,
            
            kuzu: {
                db_path: document.getElementById('cfg-kuzu-path').value
            },
            
            neo4j: {
                uri: document.getElementById('cfg-neo4j-uri').value,
                username: document.getElementById('cfg-neo4j-user').value
            },
            
            llm: {
                base_url: document.getElementById('cfg-graphiti-llm-url').value || null,
                model: document.getElementById('cfg-graphiti-model').value
            },
            
            embedding: {
                base_url: document.getElementById('cfg-graphiti-embed-url').value || null,
                model: document.getElementById('cfg-graphiti-embed-model').value,
                dim: parseInt(document.getElementById('cfg-graphiti-embed-dim').value) || 1536
            },
            
            reranker: {
                enabled: document.getElementById('cfg-graphiti-reranker').checked,
                model: document.getElementById('cfg-graphiti-model').value  // 复用主模型
            },
            
            retrieval: {
                strategy: document.getElementById('cfg-graphiti-strategy').value,
                max_iterations: parseInt(document.getElementById('cfg-graphiti-max-iter').value) || 3,
                min_evidence_count: parseInt(document.getElementById('cfg-graphiti-min-evidence').value) || 2,
                default_limit: parseInt(document.getElementById('cfg-graphiti-limit').value) || 10,
                include_edges: document.getElementById('cfg-graphiti-include-edges').checked
            },
            
            search: {
                sim_min_score: parseFloat(document.getElementById('cfg-graphiti-sim-score').value) || 0.4,
                mmr_lambda: parseFloat(document.getElementById('cfg-graphiti-mmr').value) || 0.5
            },
            
            performance: {
                daily_token_limit: parseInt(document.getElementById('cfg-graphiti-daily-limit').value) || 100000,
                semaphore_limit: parseInt(document.getElementById('cfg-graphiti-semaphore').value) || 10
            },
            
            sync: {
                index_conversations: document.getElementById('cfg-graphiti-sync-conv').checked
            }
        };
        
        // 处理密码（只有填写了才更新）
        const neo4jPass = document.getElementById('cfg-neo4j-pass').value;
        if (neo4jPass) {
            config.neo4j.password = neo4jPass;
        }
        
        // 处理 LLM API Key（只有填写了才更新）
        const llmApiKey = document.getElementById('cfg-graphiti-llm-key').value;
        if (llmApiKey && !llmApiKey.includes('***')) {
            config.llm.api_key = llmApiKey;
        }
        
        // 处理 Embedding API Key（只有填写了才更新）
        const embedApiKey = document.getElementById('cfg-graphiti-embed-key').value;
        if (embedApiKey && !embedApiKey.includes('***')) {
            config.embedding.api_key = embedApiKey;
        }
        
        const res = await fetch('/api/memory/graphiti/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        const result = await res.json();
        
        if (result.success) {
            showToast('Graphiti 配置已保存', 'success');
            // 刷新统计状态
            await refreshGraphitiStats();
        } else {
            showToast('保存失败: ' + (result.error || '未知错误'), 'error');
        }
        
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
        console.error('saveGraphitiConfig error:', e);
    }
}

/**
 * 切换后端类型显示
 */
function toggleGraphitiBackend(backend) {
    const kuzuSettings = document.getElementById('kuzu-settings');
    const neo4jSettings = document.getElementById('neo4j-settings');
    
    if (kuzuSettings) {
        kuzuSettings.style.display = backend === 'kuzu' ? 'block' : 'none';
    }
    if (neo4jSettings) {
        neo4jSettings.style.display = backend === 'neo4j' ? 'block' : 'none';
    }
}

// ========== 状态监控 ==========

/**
 * 刷新 Graphiti 统计信息
 */
async function refreshGraphitiStats() {
    try {
        const res = await fetch('/api/memory/graphiti/stats');
        const stats = await res.json();
        
        // 更新概览页面的状态卡片
        const statGraphiti = document.getElementById('stat-graphiti');
        const statGraphitiDetail = document.getElementById('stat-graphiti-detail');
        
        if (statGraphiti) {
            if (!stats.enabled) {
                statGraphiti.textContent = '未启用';
                statGraphiti.style.color = 'var(--text-dim)';
            } else if (stats.status === 'running') {
                statGraphiti.textContent = '运行中';
                statGraphiti.style.color = 'var(--success)';
            } else {
                statGraphiti.textContent = stats.status || '未知';
                statGraphiti.style.color = 'var(--warning)';
            }
        }
        
        if (statGraphitiDetail) {
            if (!stats.enabled) {
                statGraphitiDetail.textContent = '点击配置启用';
            } else if (stats.error) {
                statGraphitiDetail.textContent = stats.error;
            } else {
                const backend = stats.backend === 'kuzu' ? 'Kuzu' : 'Neo4j';
                let detail = backend;
                if (stats.kuzu_db_exists !== undefined) {
                    detail += stats.kuzu_db_exists ? ' (已初始化)' : ' (待初始化)';
                }
                statGraphitiDetail.textContent = detail;
            }
        }
        
        // 更新 Graphiti 页面的同步状态
        const syncStatus = document.getElementById('graphiti-sync-status');
        if (syncStatus) {
            if (stats.kuzu_db_exists) {
                const sizeMB = (stats.kuzu_db_size / 1024 / 1024).toFixed(2);
                syncStatus.textContent = `数据库大小: ${sizeMB} MB`;
            } else {
                syncStatus.textContent = '数据库未创建';
            }
        }
        
        // 同时刷新 Token 使用量
        await refreshTokenUsage();
        
    } catch (e) {
        console.error('refreshGraphitiStats error:', e);
    }
}

/**
 * 刷新 Token 使用量
 */
async function refreshTokenUsage() {
    try {
        const res = await fetch('/api/memory/graphiti/token-usage');
        const data = await res.json();
        
        const usedEl = document.getElementById('graphiti-used-tokens');
        const limitEl = document.getElementById('graphiti-limit-tokens');
        const remainEl = document.getElementById('graphiti-remain-tokens');
        const barEl = document.getElementById('graphiti-usage-bar');
        
        if (usedEl) usedEl.textContent = data.used.toLocaleString();
        if (limitEl) limitEl.textContent = data.limit.toLocaleString();
        if (remainEl) remainEl.textContent = data.remaining.toLocaleString();
        
        if (barEl) {
            const percent = data.percent || 0;
            barEl.style.width = percent + '%';
            
            // 颜色根据使用量变化
            if (percent > 80) {
                barEl.style.background = 'var(--danger)';
            } else if (percent > 50) {
                barEl.style.background = 'var(--warning)';
            } else {
                barEl.style.background = 'var(--success)';
            }
        }
        
    } catch (e) {
        console.error('refreshTokenUsage error:', e);
    }
}

// ========== 同步管理 ==========

// 同步状态轮询定时器
let syncStatusPollingTimer = null;

/**
 * 同步 Markdown 到 Graphiti（后台任务）
 */
async function syncMarkdownToGraphiti() {
    if (!confirm('确定要将所有 Markdown 同步到 Graphiti 吗？\n这可能需要几分钟时间并消耗 Token。')) {
        return;
    }
    
    try {
        const res = await fetch('/api/memory/graphiti/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ include_diaries: true, include_nodes: true })
        });
        
        const result = await res.json();
        
        if (result.success) {
            showToast('同步任务已启动', 'success');
            // 开始轮询状态
            startSyncStatusPolling();
        } else if (result.status) {
            // 任务已在运行
            showToast(result.error || '同步任务正在进行中', 'warning');
            startSyncStatusPolling();
        } else {
            showToast('同步失败: ' + (result.error || '未知错误'), 'error');
        }
        
    } catch (e) {
        showToast('同步失败: ' + e.message, 'error');
    }
}

/**
 * 开始轮询同步状态
 */
function startSyncStatusPolling() {
    // 如果已在轮询，不重复启动
    if (syncStatusPollingTimer) return;
    
    // 每秒轮询一次
    syncStatusPollingTimer = setInterval(async () => {
        await refreshSyncStatus();
    }, 1000);
    
    // 立即执行一次
    refreshSyncStatus();
}

/**
 * 停止轮询同步状态
 */
function stopSyncStatusPolling() {
    if (syncStatusPollingTimer) {
        clearInterval(syncStatusPollingTimer);
        syncStatusPollingTimer = null;
    }
}

/**
 * 刷新同步状态
 */
async function refreshSyncStatus() {
    try {
        const res = await fetch('/api/memory/graphiti/sync/status');
        const status = await res.json();
        
        updateSyncControlPanel(status);
        
        // 如果正在运行但没有轮询，自动开始轮询
        if (status.is_running && !syncStatusPollingTimer) {
            console.log('[Graphiti] 检测到同步任务运行中，恢复轮询');
            startSyncStatusPolling();
        }
        
        // 如果完成或失败，停止轮询
        if (!status.is_running && status.status !== 'idle') {
            stopSyncStatusPolling();
            
            if (status.status === 'completed') {
                showToast(`同步完成：${status.synced_diaries} 日记，${status.synced_nodes} 节点`, 'success');
                await refreshGraphitiStats();
            } else if (status.status === 'failed') {
                showToast('同步失败: ' + (status.error || '未知错误'), 'error');
            }
        }
        
    } catch (e) {
        console.error('刷新同步状态失败:', e);
    }
}

/**
 * 更新同步控制面板（面板已在 HTML 中常时显示）
 */
function updateSyncControlPanel(status) {
    const statusText = document.getElementById('sync-status-text');
    const progressBar = document.getElementById('sync-progress-bar');
    const progressText = document.getElementById('sync-progress-text');
    const currentFile = document.getElementById('sync-current-file');
    const diaryCount = document.getElementById('sync-diary-count');
    const nodeCount = document.getElementById('sync-node-count');
    const failedCount = document.getElementById('sync-failed-count');
    const btnPause = document.getElementById('btn-pause-sync');
    const btnResume = document.getElementById('btn-resume-sync');
    const btnStop = document.getElementById('btn-stop-sync');
    
    if (!statusText) return;
    
    // 状态文本
    const statusMap = {
        'idle': '⚪ 空闲',
        'running': '🔄 同步中...',
        'paused': '⏸️ 已暂停',
        'stopping': '⏹️ 正在停止...',
        'completed': '✅ 完成',
        'failed': '❌ 失败'
    };
    statusText.textContent = statusMap[status.status] || status.status;
    
    // 进度条
    const percent = status.total_files > 0
        ? Math.round((status.current_index / status.total_files) * 100)
        : 0;
    if (progressBar) progressBar.style.width = percent + '%';
    if (progressText) progressText.textContent = `${status.current_index} / ${status.total_files}`;
    if (currentFile) currentFile.textContent = status.current_file || '--';
    
    // 统计
    if (diaryCount) diaryCount.textContent = status.synced_diaries || 0;
    if (nodeCount) nodeCount.textContent = status.synced_nodes || 0;
    if (failedCount) failedCount.textContent = status.failed_files?.length || 0;
    
    // 按钮状态
    if (btnPause) btnPause.style.display = status.can_pause ? 'inline-block' : 'none';
    if (btnResume) btnResume.style.display = status.can_resume ? 'inline-block' : 'none';
    if (btnStop) btnStop.style.display = status.can_stop ? 'inline-block' : 'none';
    
    // 进度条颜色
    if (progressBar) {
        if (status.status === 'paused') {
            progressBar.style.background = 'var(--warning)';
        } else if (status.status === 'failed') {
            progressBar.style.background = 'var(--danger)';
        } else if (status.status === 'completed') {
            progressBar.style.background = 'var(--success)';
        } else {
            progressBar.style.background = 'var(--accent)';
        }
    }
}

/**
 * 暂停同步
 */
async function pauseSync() {
    try {
        const res = await fetch('/api/memory/graphiti/sync/pause', { method: 'POST' });
        const result = await res.json();
        
        if (result.success) {
            showToast('同步已暂停', 'success');
        } else {
            showToast(result.error || '暂停失败', 'error');
        }
    } catch (e) {
        showToast('暂停失败: ' + e.message, 'error');
    }
}

/**
 * 继续同步
 */
async function resumeSync() {
    try {
        const res = await fetch('/api/memory/graphiti/sync/resume', { method: 'POST' });
        const result = await res.json();
        
        if (result.success) {
            showToast('同步已继续', 'success');
        } else {
            showToast(result.error || '继续失败', 'error');
        }
    } catch (e) {
        showToast('继续失败: ' + e.message, 'error');
    }
}

/**
 * 停止同步
 */
async function stopSync() {
    if (!confirm('确定要停止同步吗？已同步的内容会保留。')) {
        return;
    }
    
    try {
        const res = await fetch('/api/memory/graphiti/sync/stop', { method: 'POST' });
        const result = await res.json();
        
        if (result.success) {
            showToast('同步正在停止...', 'success');
        } else {
            showToast(result.error || '停止失败', 'error');
        }
    } catch (e) {
        showToast('停止失败: ' + e.message, 'error');
    }
}

/**
 * 一键同步已有节点（不使用 LLM）
 * 直接从 LifeBook nodes/*.md 读取节点并创建到 Graphiti
 */
async function syncNodesWithoutLLM() {
    if (!confirm('确定要将 LifeBook 的已有节点同步到 Graphiti 吗？\n\n这不会使用 LLM，速度快且无 Token 消耗。')) {
        return;
    }
    
    try {
        const res = await fetch('/api/memory/graphiti/sync-nodes-simple', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await res.json();
        
        if (result.success) {
            showToast(`同步完成：${result.synced_count} 个节点`, 'success');
            // 刷新图谱
            await refreshGraphitiGraph();
            await refreshGraphitiStats();
        } else {
            showToast('同步失败: ' + (result.error || '未知错误'), 'error');
        }
        
    } catch (e) {
        showToast('同步失败: ' + e.message, 'error');
    }
}

/**
 * 重建 Graphiti 索引
 */
async function rebuildGraphitiIndex() {
    if (!confirm('⚠️ 确定要重建 Graphiti 索引吗？\n\n这将：\n1. 删除现有图数据库\n2. 重新从 Markdown 构建\n\n此操作不可逆！')) {
        return;
    }
    
    // 二次确认
    if (!confirm('再次确认：重建索引将清空所有 Graphiti 数据。\n\n确定继续？')) {
        return;
    }
    
    const syncStatus = document.getElementById('graphiti-sync-status');
    if (syncStatus) syncStatus.textContent = '重建中...';
    
    try {
        const res = await fetch('/api/memory/graphiti/rebuild', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm: true })
        });
        
        const result = await res.json();
        
        if (result.success) {
            showToast(result.message, 'success');
            if (syncStatus) syncStatus.textContent = '重建完成';
            // 刷新统计
            await refreshGraphitiStats();
        } else {
            showToast('重建失败: ' + (result.error || '未知错误'), 'error');
            if (syncStatus) syncStatus.textContent = '重建失败';
        }
        
    } catch (e) {
        showToast('重建失败: ' + e.message, 'error');
        if (syncStatus) syncStatus.textContent = '重建失败';
    }
}

// ========== 搜索测试 ==========

/**
 * 测试 Graphiti 搜索
 */
async function testGraphitiSearch() {
    const queryEl = document.getElementById('graphiti-test-query');
    const resultEl = document.getElementById('graphiti-test-result');
    
    if (!queryEl || !resultEl) return;
    
    const query = queryEl.value.trim();
    if (!query) {
        showToast('请输入搜索内容', 'error');
        return;
    }
    
    resultEl.innerHTML = '<div class="loading"><span class="spinner"></span> 搜索中...</div>';
    
    try {
        const res = await fetch('/api/memory/graphiti/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, num_results: 10 })
        });
        
        const data = await res.json();
        
        if (data.error) {
            resultEl.innerHTML = `<div class="alert alert-danger">${escapeHtml(data.error)}</div>`;
            return;
        }
        
        if (!data.results || data.results.length === 0) {
            resultEl.innerHTML = '<p style="color: var(--text-dim);">未找到相关结果</p>';
            return;
        }
        
        let html = `<p style="color: var(--text-dim); margin-bottom: 10px;">找到 ${data.count} 条结果：</p>`;
        
        data.results.forEach((r, i) => {
            const score = r.score ? `(${r.score.toFixed(3)})` : '';
            const source = r.source ? `<span style="color: var(--accent);">[${escapeHtml(r.source)}]</span>` : '';
            const type = r.type === 'edge' ? '🔗' : '📦';
            
            html += `
                <div style="padding: 10px; margin-bottom: 8px; background: var(--surface-2); border-radius: 6px;">
                    <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 5px;">
                        <span>${type}</span>
                        ${source}
                        <span style="color: var(--text-dim); font-size: 0.85rem;">${score}</span>
                    </div>
                    <div style="font-size: 0.9rem;">${escapeHtml(r.content || '')}</div>
                </div>
            `;
        });
        
        resultEl.innerHTML = html;
        
    } catch (e) {
        resultEl.innerHTML = `<div class="alert alert-danger">搜索失败: ${escapeHtml(e.message)}</div>`;
    }
}

// ========== 对话保留配置 ==========

/**
 * 加载对话保留配置
 */
async function loadConversationLoggerConfig() {
    try {
        const res = await fetch('/api/memory/graphiti/conversation-logger/config');
        const config = await res.json();
        
        if (config.error) {
            console.error('加载对话保留配置失败:', config.error);
            return;
        }
        
        document.getElementById('cfg-conv-enabled').checked = config.enabled !== false;
        document.getElementById('cfg-conv-timeout').value = config.session_timeout_minutes || 30;
        document.getElementById('cfg-conv-threshold').value = config.prefix_match_threshold || 0.7;
        document.getElementById('cfg-conv-max-turns').value = config.max_turns_per_file || 100;
        
    } catch (e) {
        console.error('loadConversationLoggerConfig error:', e);
    }
}

/**
 * 保存对话保留配置
 */
async function saveConversationLoggerConfig() {
    try {
        const config = {
            enabled: document.getElementById('cfg-conv-enabled').checked,
            session_timeout_minutes: parseInt(document.getElementById('cfg-conv-timeout').value) || 30,
            prefix_match_threshold: parseFloat(document.getElementById('cfg-conv-threshold').value) || 0.7,
            max_turns_per_file: parseInt(document.getElementById('cfg-conv-max-turns').value) || 100
        };
        
        const res = await fetch('/api/memory/graphiti/conversation-logger/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        const result = await res.json();
        
        if (result.success) {
            showToast('对话保留配置已保存', 'success');
        } else {
            showToast('保存失败: ' + (result.error || '未知错误'), 'error');
        }
        
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

/**
 * 加载对话记录列表
 */
async function loadConversations(days = 7) {
    const container = document.getElementById('conversations-list');
    if (!container) return;
    
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    try {
        const res = await fetch(`/api/memory/graphiti/conversations?days=${days}`);
        const data = await res.json();
        
        if (data.error) {
            container.innerHTML = `<div class="alert alert-danger">${escapeHtml(data.error)}</div>`;
            return;
        }
        
        if (!data.conversations || data.conversations.length === 0) {
            container.innerHTML = '<p style="color: var(--text-dim);">暂无对话记录</p>';
            return;
        }
        
        let html = '<table class="table"><thead><tr>';
        html += '<th>会话ID</th><th>开始时间</th><th>轮次</th><th>模型</th><th>大小</th>';
        html += '</tr></thead><tbody>';
        
        data.conversations.forEach(conv => {
            const startTime = conv.start_time ? new Date(conv.start_time).toLocaleString() : '--';
            const sizeMB = (conv.file_size / 1024).toFixed(1);
            
            html += `<tr>
                <td><code style="font-size: 0.85rem;">${escapeHtml(conv.session_id.substring(0, 20))}</code></td>
                <td>${startTime}</td>
                <td>${conv.turn_count}</td>
                <td>${escapeHtml(conv.model || '--')}</td>
                <td>${sizeMB} KB</td>
            </tr>`;
        });
        
        html += '</tbody></table>';
        container.innerHTML = html;
        
    } catch (e) {
        container.innerHTML = `<div class="alert alert-danger">加载失败: ${escapeHtml(e.message)}</div>`;
    }
}

// ========== 图谱可视化 ==========

// 全局变量：vis-network 实例
let graphitiNetwork = null;
let graphitiNodes = null;
let graphitiEdges = null;

/**
 * 刷新 Graphiti 图谱可视化
 */
async function refreshGraphitiGraph() {
    const container = document.getElementById('graphiti-graph-container');
    const statusEl = document.getElementById('graphiti-graph-status');
    
    if (!container) {
        console.warn('图谱容器未找到');
        return;
    }
    
    if (statusEl) statusEl.textContent = '加载中...';
    
    try {
        const res = await fetch('/api/memory/graphiti/graph-data?limit=100');
        const data = await res.json();
        
        if (data.error) {
            if (statusEl) statusEl.textContent = '加载失败: ' + data.error;
            showToast('加载图谱失败: ' + data.error, 'error');
            return;
        }
        
        if (!data.nodes || data.nodes.length === 0) {
            if (statusEl) statusEl.textContent = '暂无图谱数据';
            container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);">暂无图谱数据，请先同步 Markdown</div>';
            return;
        }
        
        // 转换为 vis-network 格式
        const visNodes = data.nodes.map(n => ({
            id: n.uuid || n.id,
            label: truncateLabel(n.name || n.label || n.uuid, 20),
            title: `${n.name || n.label}\n${n.summary || ''}`,
            color: getNodeColor(n.type || n.label_type),
            shape: 'dot',
            size: 15 + (n.importance || 0) * 5
        }));
        
        const visEdges = data.edges.map(e => ({
            id: e.uuid || `${e.source}-${e.target}`,
            from: e.source_uuid || e.source,
            to: e.target_uuid || e.target,
            label: truncateLabel(e.name || e.type || '', 15),
            title: e.fact || e.name || '',
            arrows: 'to',
            font: {
                color: '#8fa0bf',
                size: 11,
                strokeWidth: 0,
                background: 'rgba(14, 26, 45, 0.8)'
            },
            color: { color: '#3d5a80', opacity: 0.7 },
            smooth: { type: 'curvedCW', roundness: 0.2 }
        }));
        
        graphitiNodes = new vis.DataSet(visNodes);
        graphitiEdges = new vis.DataSet(visEdges);
        
        const graphData = {
            nodes: graphitiNodes,
            edges: graphitiEdges
        };
        
        const options = {
            nodes: {
                font: { color: '#d9e5ff', size: 12 },
                borderWidth: 2,
                shadow: true
            },
            edges: {
                font: {
                    color: '#8fa0bf',
                    size: 11,
                    align: 'middle',
                    strokeWidth: 0,
                    background: 'rgba(14, 26, 45, 0.8)'
                },
                smooth: { type: 'curvedCW', roundness: 0.15 },
                width: 1.5
            },
            physics: {
                enabled: true,
                solver: 'forceAtlas2Based',
                forceAtlas2Based: {
                    gravitationalConstant: -50,
                    centralGravity: 0.01,
                    springLength: 100,
                    springConstant: 0.08
                },
                stabilization: { iterations: 100 }
            },
            interaction: {
                hover: true,
                tooltipDelay: 200
            }
        };
        
        // 清空容器并创建新网络
        container.innerHTML = '';
        graphitiNetwork = new vis.Network(container, graphData, options);
        
        // 添加点击事件
        graphitiNetwork.on('click', function(params) {
            if (params.nodes.length > 0) {
                // 点击了节点
                const nodeId = params.nodes[0];
                showNodeDetail(nodeId);
            } else if (params.edges.length > 0) {
                // 点击了边
                const edgeId = params.edges[0];
                showEdgeDetail(edgeId);
            }
        });
        
        // 双击聚焦
        graphitiNetwork.on('doubleClick', function(params) {
            if (params.nodes.length > 0) {
                graphitiNetwork.focus(params.nodes[0], {
                    scale: 1.5,
                    animation: { duration: 500, easingFunction: 'easeInOutQuad' }
                });
            }
        });
        
        if (statusEl) {
            statusEl.textContent = `${visNodes.length} 节点, ${visEdges.length} 边`;
        }
        
        // 更新统计信息
        const statsEl = document.getElementById('graphiti-graph-stats');
        if (statsEl) {
            statsEl.innerHTML = `
                <span>📦 ${visNodes.length} 节点</span> |
                <span>🔗 ${visEdges.length} 边</span> |
                <span style="color: var(--text-dim);">点击节点/边查看详情，双击节点聚焦</span>
            `;
        }
        
        showToast(`加载了 ${visNodes.length} 个节点和 ${visEdges.length} 条边`, 'success');
        
    } catch (e) {
        console.error('refreshGraphitiGraph error:', e);
        if (statusEl) statusEl.textContent = '加载失败';
        showToast('加载图谱失败: ' + e.message, 'error');
    }
}

/**
 * 适应视图
 */
function fitGraphitiView() {
    if (graphitiNetwork) {
        graphitiNetwork.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
    }
}

/**
 * 截断标签
 */
function truncateLabel(text, maxLen) {
    if (!text) return '';
    return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
}

/**
 * 根据节点类型返回颜色
 */
function getNodeColor(type) {
    const colors = {
        'Person': '#e91e63',      // 粉红
        '人物': '#e91e63',
        'Location': '#4caf50',    // 绿色
        '地点': '#4caf50',
        'Organization': '#2196f3', // 蓝色
        '组织': '#2196f3',
        'Event': '#ff9800',       // 橙色
        '事件': '#ff9800',
        'Concept': '#9c27b0',     // 紫色
        '概念': '#9c27b0',
        'Object': '#00bcd4',      // 青色
        '物品': '#00bcd4',
        'default': '#78909c'      // 灰色
    };
    return colors[type] || colors['default'];
}

// ========== 节点/边 CRUD 操作 ==========

/**
 * 显示节点详情
 */
async function showNodeDetail(uuid) {
    try {
        const res = await fetch(`/api/memory/graphiti/nodes/${uuid}`);
        const data = await res.json();
        
        if (!data.success) {
            showToast('获取节点详情失败: ' + (data.error || '未知错误'), 'error');
            return;
        }
        
        const node = data.node;
        const edges = data.edges || [];
        
        // 显示详情模态框
        showNodeDetailModal(node, edges);
        
    } catch (e) {
        showToast('获取节点详情失败: ' + e.message, 'error');
    }
}

/**
 * 显示节点详情模态框
 */
function showNodeDetailModal(node, edges) {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.onclick = (e) => {
        if (e.target === modal) modal.remove();
    };
    
    const labelsHtml = (node.labels || []).map(l =>
        `<span class="badge badge-info">${escapeHtml(l)}</span>`
    ).join(' ');
    
    const edgesHtml = edges.length > 0
        ? edges.map(e => `
            <div class="edge-item" onclick="showEdgeDetail('${e.uuid}')" style="padding: 8px; margin: 5px 0; background: var(--surface-3); border-radius: 6px; cursor: pointer;">
                <div><strong>${escapeHtml(e.name)}</strong></div>
                <div style="font-size: 0.85rem; color: var(--text-dim);">${escapeHtml(e.fact || '').substring(0, 100)}...</div>
            </div>
        `).join('')
        : '<p style="color: var(--text-dim);">暂无关联边</p>';
    
    modal.innerHTML = `
        <div class="modal-container" style="max-width: 700px;">
            <div class="modal-header">
                <h3>📦 节点详情</h3>
                <button class="btn btn-sm" onclick="this.closest('.modal-overlay').remove()">✕</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label class="form-label">名称</label>
                    <input type="text" id="edit-node-name" class="form-input" value="${escapeHtml(node.name)}">
                </div>
                <div class="form-group">
                    <label class="form-label">摘要</label>
                    <textarea id="edit-node-summary" class="form-input" rows="4">${escapeHtml(node.summary || '')}</textarea>
                </div>
                <div class="form-group">
                    <label class="form-label">标签 (逗号分隔)</label>
                    <input type="text" id="edit-node-labels" class="form-input" value="${(node.labels || []).join(', ')}">
                </div>
                <div class="form-group">
                    <label class="form-label">UUID</label>
                    <input type="text" class="form-input" value="${node.uuid}" readonly style="opacity: 0.6;">
                </div>
                <div class="form-group">
                    <label class="form-label">创建时间</label>
                    <input type="text" class="form-input" value="${node.created_at || '--'}" readonly style="opacity: 0.6;">
                </div>
                
                <h4 style="margin-top: 20px; color: var(--accent);">🔗 关联边 (${edges.length})</h4>
                <div style="max-height: 200px; overflow-y: auto;">
                    ${edgesHtml}
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-danger" onclick="deleteNode('${node.uuid}')">🗑️ 删除</button>
                <button class="btn" onclick="this.closest('.modal-overlay').remove()">取消</button>
                <button class="btn btn-success" onclick="saveNodeEdit('${node.uuid}')">💾 保存</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}

/**
 * 保存节点编辑
 */
async function saveNodeEdit(uuid) {
    const name = document.getElementById('edit-node-name').value.trim();
    const summary = document.getElementById('edit-node-summary').value.trim();
    const labelsStr = document.getElementById('edit-node-labels').value.trim();
    const labels = labelsStr ? labelsStr.split(',').map(l => l.trim()).filter(l => l) : [];
    
    if (!name) {
        showToast('节点名称不能为空', 'error');
        return;
    }
    
    try {
        const res = await fetch(`/api/memory/graphiti/nodes/${uuid}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, summary, labels })
        });
        
        const data = await res.json();
        
        if (data.success) {
            showToast('节点更新成功', 'success');
            document.querySelector('.modal-overlay')?.remove();
            refreshGraphitiGraph();
        } else {
            showToast('更新失败: ' + (data.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('更新失败: ' + e.message, 'error');
    }
}

/**
 * 删除节点
 */
async function deleteNode(uuid) {
    if (!confirm('确定要删除这个节点吗？\n相关的边也会被删除，此操作不可逆！')) {
        return;
    }
    
    try {
        const res = await fetch(`/api/memory/graphiti/nodes/${uuid}`, {
            method: 'DELETE'
        });
        
        const data = await res.json();
        
        if (data.success) {
            showToast('节点已删除', 'success');
            document.querySelector('.modal-overlay')?.remove();
            refreshGraphitiGraph();
        } else {
            showToast('删除失败: ' + (data.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

/**
 * 显示边详情
 */
async function showEdgeDetail(uuid) {
    try {
        const res = await fetch(`/api/memory/graphiti/edges/${uuid}`);
        const data = await res.json();
        
        if (!data.success) {
            showToast('获取边详情失败: ' + (data.error || '未知错误'), 'error');
            return;
        }
        
        const edge = data.edge;
        const sourceNode = data.source_node;
        const targetNode = data.target_node;
        
        showEdgeDetailModal(edge, sourceNode, targetNode);
        
    } catch (e) {
        showToast('获取边详情失败: ' + e.message, 'error');
    }
}

/**
 * 显示边详情模态框
 */
function showEdgeDetailModal(edge, sourceNode, targetNode) {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.onclick = (e) => {
        if (e.target === modal) modal.remove();
    };
    
    modal.innerHTML = `
        <div class="modal-container" style="max-width: 700px;">
            <div class="modal-header">
                <h3>🔗 边详情</h3>
                <button class="btn btn-sm" onclick="this.closest('.modal-overlay').remove()">✕</button>
            </div>
            <div class="modal-body">
                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 20px; padding: 15px; background: var(--surface-2); border-radius: 8px;">
                    <span class="badge badge-info" onclick="showNodeDetail('${edge.source_node_uuid}')" style="cursor: pointer;">
                        ${sourceNode ? escapeHtml(sourceNode.name) : edge.source_node_uuid.substring(0, 8)}
                    </span>
                    <span>→</span>
                    <strong style="color: var(--accent);">${escapeHtml(edge.name)}</strong>
                    <span>→</span>
                    <span class="badge badge-info" onclick="showNodeDetail('${edge.target_node_uuid}')" style="cursor: pointer;">
                        ${targetNode ? escapeHtml(targetNode.name) : edge.target_node_uuid.substring(0, 8)}
                    </span>
                </div>
                
                <div class="form-group">
                    <label class="form-label">关系名称</label>
                    <input type="text" id="edit-edge-name" class="form-input" value="${escapeHtml(edge.name)}">
                </div>
                <div class="form-group">
                    <label class="form-label">事实描述</label>
                    <textarea id="edit-edge-fact" class="form-input" rows="4">${escapeHtml(edge.fact || '')}</textarea>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                    <div class="form-group">
                        <label class="form-label">生效时间 (valid_at)</label>
                        <input type="datetime-local" id="edit-edge-valid-at" class="form-input"
                               value="${edge.valid_at ? edge.valid_at.substring(0, 16) : ''}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">失效时间 (invalid_at)</label>
                        <input type="datetime-local" id="edit-edge-invalid-at" class="form-input"
                               value="${edge.invalid_at ? edge.invalid_at.substring(0, 16) : ''}">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">UUID</label>
                    <input type="text" class="form-input" value="${edge.uuid}" readonly style="opacity: 0.6;">
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-danger" onclick="deleteEdge('${edge.uuid}')">🗑️ 删除</button>
                <button class="btn" onclick="this.closest('.modal-overlay').remove()">取消</button>
                <button class="btn btn-success" onclick="saveEdgeEdit('${edge.uuid}')">💾 保存</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}

/**
 * 保存边编辑
 */
async function saveEdgeEdit(uuid) {
    const name = document.getElementById('edit-edge-name').value.trim();
    const fact = document.getElementById('edit-edge-fact').value.trim();
    const validAtStr = document.getElementById('edit-edge-valid-at').value;
    const invalidAtStr = document.getElementById('edit-edge-invalid-at').value;
    
    if (!name || !fact) {
        showToast('关系名称和事实描述不能为空', 'error');
        return;
    }
    
    const payload = { name, fact };
    if (validAtStr) payload.valid_at = new Date(validAtStr).toISOString();
    if (invalidAtStr) payload.invalid_at = new Date(invalidAtStr).toISOString();
    
    try {
        const res = await fetch(`/api/memory/graphiti/edges/${uuid}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const data = await res.json();
        
        if (data.success) {
            showToast('边更新成功', 'success');
            document.querySelector('.modal-overlay')?.remove();
            refreshGraphitiGraph();
        } else {
            showToast('更新失败: ' + (data.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('更新失败: ' + e.message, 'error');
    }
}

/**
 * 删除边
 */
async function deleteEdge(uuid) {
    if (!confirm('确定要删除这条边吗？此操作不可逆！')) {
        return;
    }
    
    try {
        const res = await fetch(`/api/memory/graphiti/edges/${uuid}`, {
            method: 'DELETE'
        });
        
        const data = await res.json();
        
        if (data.success) {
            showToast('边已删除', 'success');
            document.querySelector('.modal-overlay')?.remove();
            refreshGraphitiGraph();
        } else {
            showToast('删除失败: ' + (data.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

/**
 * 显示创建节点对话框
 */
function showCreateGraphitiNodeDialog() {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.onclick = (e) => {
        if (e.target === modal) modal.remove();
    };
    
    modal.innerHTML = `
        <div class="modal-container" style="max-width: 500px;">
            <div class="modal-header">
                <h3>✨ 创建新节点</h3>
                <button class="btn btn-sm" onclick="this.closest('.modal-overlay').remove()">✕</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label class="form-label">节点名称 *</label>
                    <input type="text" id="new-node-name" class="form-input" placeholder="例如：张三、北京、项目A">
                </div>
                <div class="form-group">
                    <label class="form-label">摘要描述</label>
                    <textarea id="new-node-summary" class="form-input" rows="3" placeholder="对节点的描述..."></textarea>
                </div>
                <div class="form-group">
                    <label class="form-label">标签 (逗号分隔)</label>
                    <input type="text" id="new-node-labels" class="form-input" placeholder="Person, Location, Project...">
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="this.closest('.modal-overlay').remove()">取消</button>
                <button class="btn btn-success" onclick="createGraphitiNode()">✨ 创建</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    document.getElementById('new-node-name').focus();
}

/**
 * 创建新节点
 */
async function createGraphitiNode() {
    const name = document.getElementById('new-node-name').value.trim();
    const summary = document.getElementById('new-node-summary').value.trim();
    const labelsStr = document.getElementById('new-node-labels').value.trim();
    const labels = labelsStr ? labelsStr.split(',').map(l => l.trim()).filter(l => l) : [];
    
    if (!name) {
        showToast('节点名称不能为空', 'error');
        return;
    }
    
    try {
        const res = await fetch('/api/memory/graphiti/nodes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, summary, labels })
        });
        
        const data = await res.json();
        
        if (data.success) {
            showToast('节点创建成功', 'success');
            document.querySelector('.modal-overlay')?.remove();
            refreshGraphitiGraph();
        } else {
            showToast('创建失败: ' + (data.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('创建失败: ' + e.message, 'error');
    }
}

/**
 * 显示创建边对话框
 */
async function showCreateEdgeDialog(sourceUuid = null) {
    // 先获取节点列表
    let nodes = [];
    try {
        const res = await fetch('/api/memory/graphiti/nodes?limit=100');
        const data = await res.json();
        if (data.success) {
            nodes = data.nodes || [];
        }
    } catch (e) {
        showToast('获取节点列表失败', 'error');
        return;
    }
    
    if (nodes.length < 2) {
        showToast('至少需要2个节点才能创建边', 'warning');
        return;
    }
    
    const nodeOptions = nodes.map(n =>
        `<option value="${n.uuid}" ${n.uuid === sourceUuid ? 'selected' : ''}>${escapeHtml(n.name)}</option>`
    ).join('');
    
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.onclick = (e) => {
        if (e.target === modal) modal.remove();
    };
    
    modal.innerHTML = `
        <div class="modal-container" style="max-width: 600px;">
            <div class="modal-header">
                <h3>🔗 创建新边</h3>
                <button class="btn btn-sm" onclick="this.closest('.modal-overlay').remove()">✕</button>
            </div>
            <div class="modal-body">
                <div style="display: grid; grid-template-columns: 1fr auto 1fr; gap: 10px; align-items: end; margin-bottom: 20px;">
                    <div class="form-group" style="margin: 0;">
                        <label class="form-label">源节点 *</label>
                        <select id="new-edge-source" class="form-select">${nodeOptions}</select>
                    </div>
                    <div style="padding-bottom: 10px;">→</div>
                    <div class="form-group" style="margin: 0;">
                        <label class="form-label">目标节点 *</label>
                        <select id="new-edge-target" class="form-select">${nodeOptions}</select>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">关系名称 *</label>
                    <input type="text" id="new-edge-name" class="form-input" placeholder="例如：认识、属于、参与">
                </div>
                <div class="form-group">
                    <label class="form-label">事实描述 *</label>
                    <textarea id="new-edge-fact" class="form-input" rows="3" placeholder="描述这个关系的具体事实..."></textarea>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                    <div class="form-group">
                        <label class="form-label">生效时间</label>
                        <input type="datetime-local" id="new-edge-valid-at" class="form-input">
                    </div>
                    <div class="form-group">
                        <label class="form-label">失效时间</label>
                        <input type="datetime-local" id="new-edge-invalid-at" class="form-input">
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="this.closest('.modal-overlay').remove()">取消</button>
                <button class="btn btn-success" onclick="createGraphitiEdge()">🔗 创建</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    document.getElementById('new-edge-name').focus();
}

/**
 * 创建新边
 */
async function createGraphitiEdge() {
    const sourceUuid = document.getElementById('new-edge-source').value;
    const targetUuid = document.getElementById('new-edge-target').value;
    const name = document.getElementById('new-edge-name').value.trim();
    const fact = document.getElementById('new-edge-fact').value.trim();
    const validAtStr = document.getElementById('new-edge-valid-at').value;
    const invalidAtStr = document.getElementById('new-edge-invalid-at').value;
    
    if (!name || !fact) {
        showToast('关系名称和事实描述不能为空', 'error');
        return;
    }
    
    if (sourceUuid === targetUuid) {
        showToast('源节点和目标节点不能相同', 'error');
        return;
    }
    
    const payload = {
        source_node_uuid: sourceUuid,
        target_node_uuid: targetUuid,
        name,
        fact
    };
    if (validAtStr) payload.valid_at = new Date(validAtStr).toISOString();
    if (invalidAtStr) payload.invalid_at = new Date(invalidAtStr).toISOString();
    
    try {
        const res = await fetch('/api/memory/graphiti/edges', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const data = await res.json();
        
        if (data.success) {
            showToast('边创建成功', 'success');
            document.querySelector('.modal-overlay')?.remove();
            refreshGraphitiGraph();
        } else {
            showToast('创建失败: ' + (data.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('创建失败: ' + e.message, 'error');
    }
}

// ========== 页面初始化 ==========

/**
 * 初始化 Graphiti 页面
 */
function initGraphitiPage() {
    // 后端选择变化时切换显示
    const backendSelect = document.getElementById('cfg-graphiti-backend');
    if (backendSelect) {
        backendSelect.addEventListener('change', function() {
            toggleGraphitiBackend(this.value);
        });
    }
    
    // 加载配置
    loadGraphitiConfig();
    
    // 刷新同步状态（显示当前状态）
    refreshSyncStatus();
    
    // 如果有图谱容器，初始化可视化
    const graphContainer = document.getElementById('graphiti-graph-container');
    if (graphContainer) {
        // 延迟加载图谱，等待容器渲染完成
        setTimeout(() => refreshGraphitiGraph(), 500);
    }
}

// 导出函数供全局调用
window.loadGraphitiConfig = loadGraphitiConfig;
window.saveGraphitiConfig = saveGraphitiConfig;
window.toggleGraphitiBackend = toggleGraphitiBackend;
window.refreshGraphitiStats = refreshGraphitiStats;
window.refreshTokenUsage = refreshTokenUsage;
window.syncMarkdownToGraphiti = syncMarkdownToGraphiti;
window.syncNodesWithoutLLM = syncNodesWithoutLLM;
window.rebuildGraphitiIndex = rebuildGraphitiIndex;
window.testGraphitiSearch = testGraphitiSearch;
window.loadConversationLoggerConfig = loadConversationLoggerConfig;
window.saveConversationLoggerConfig = saveConversationLoggerConfig;
window.loadConversations = loadConversations;
window.initGraphitiPage = initGraphitiPage;
window.refreshGraphitiGraph = refreshGraphitiGraph;
window.fitGraphitiView = fitGraphitiView;

// 同步控制
window.pauseSync = pauseSync;
window.resumeSync = resumeSync;
window.stopSync = stopSync;
window.refreshSyncStatus = refreshSyncStatus;
window.startSyncStatusPolling = startSyncStatusPolling;
window.stopSyncStatusPolling = stopSyncStatusPolling;
window.updateSyncControlPanel = updateSyncControlPanel;

// 节点/边 CRUD
window.showNodeDetail = showNodeDetail;
window.saveNodeEdit = saveNodeEdit;
window.deleteNode = deleteNode;
window.showEdgeDetail = showEdgeDetail;
window.saveEdgeEdit = saveEdgeEdit;
window.deleteEdge = deleteEdge;
window.showCreateGraphitiNodeDialog = showCreateGraphitiNodeDialog;
window.createGraphitiNode = createGraphitiNode;
window.showCreateEdgeDialog = showCreateEdgeDialog;
window.createGraphitiEdge = createGraphitiEdge;
/**
 * Graphiti 配置页
 * - 状态监控（数据库/Token 用量）
 * - 配置管理（后端/LLM/Embedding/Reranker/检索策略/搜索/性能/同步，接入脏跟踪）
 * - 同步控制面板（后台任务：启动/暂停/继续/停止/轮询进度）
 * - 无 LLM 节点同步、重建索引（双重确认）
 * - 搜索测试
 * 注：对话保留配置在系统设置页（config.js），此处不重复。
 */

import { apiCall } from '../core/api.js';
import {
    showToast, confirmDialog, escapeHtml, bindActions, spinnerHtml,
} from '../core/ui.js';
import { markDirty, clearDirty, isDirty } from '../core/store.js';

let rootEl = null;
let pollTimer = null;
const DIRTY_KEY = 'graphiti-config';

export const graphitiPage = {
    id: 'graphiti',
    title: 'Graphiti 配置',
    icon: '🔗',
    group: 'settings',

    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="page-header">
                <h2>🔗 Graphiti 配置</h2>
                <p>时序知识图谱的后端、模型与同步管理</p>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>📊 状态与 Token 用量</h3>
                    <button class="btn btn-sm" data-action="refresh-stats">🔄 刷新</button>
                </div>
                <div style="display: flex; gap: 20px; align-items: center; flex-wrap: wrap; margin-bottom: 12px;">
                    <span>状态: <strong id="graphiti-status-text">--</strong></span>
                    <span id="graphiti-sync-status" class="text-dim">--</span>
                </div>
                <div style="display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 8px;">
                    <span>已用: <strong id="graphiti-used-tokens">--</strong></span>
                    <span>限额: <strong id="graphiti-limit-tokens">--</strong></span>
                    <span>剩余: <strong id="graphiti-remain-tokens">--</strong></span>
                </div>
                <div class="progress-track">
                    <div class="progress-bar" id="graphiti-usage-bar" style="width: 0%;"></div>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>⚙️ Graphiti 配置</h3></div>
                <div id="graphiti-config-form">
                    <div class="form-row cols-2">
                        <div class="form-group">
                            <label class="checkbox-label" style="margin-top: 24px;">
                                <input type="checkbox" id="cfg-graphiti-enabled">启用 Graphiti
                            </label>
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-backend">图数据库后端</label>
                            <select id="cfg-graphiti-backend">
                                <option value="kuzu">Kuzu（嵌入式，免部署）</option>
                                <option value="neo4j">Neo4j（独立服务）</option>
                            </select>
                        </div>
                    </div>

                    <div id="kuzu-settings">
                        <div class="form-group">
                            <label for="cfg-kuzu-path">Kuzu 数据库路径</label>
                            <input type="text" id="cfg-kuzu-path" placeholder="./lifebook/.graphiti.kuzu">
                        </div>
                    </div>

                    <div id="neo4j-settings" style="display: none;">
                        <div class="form-row cols-3">
                            <div class="form-group">
                                <label for="cfg-neo4j-uri">Neo4j URI</label>
                                <input type="text" id="cfg-neo4j-uri" placeholder="bolt://localhost:7687">
                            </div>
                            <div class="form-group">
                                <label for="cfg-neo4j-user">用户名</label>
                                <input type="text" id="cfg-neo4j-user" placeholder="neo4j">
                            </div>
                            <div class="form-group">
                                <label for="cfg-neo4j-pass">密码</label>
                                <input type="password" id="cfg-neo4j-pass" placeholder="留空保持不变" autocomplete="off">
                            </div>
                        </div>
                    </div>

                    <h4 style="color: var(--accent); margin: 15px 0 10px;">🤖 LLM（实体抽取）</h4>
                    <div class="form-row cols-3">
                        <div class="form-group">
                            <label for="cfg-graphiti-llm-url">Base URL</label>
                            <input type="text" id="cfg-graphiti-llm-url" placeholder="https://api.openai.com/v1">
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-llm-key">API Key</label>
                            <input type="password" id="cfg-graphiti-llm-key" autocomplete="off">
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-model">模型</label>
                            <input type="text" id="cfg-graphiti-model" placeholder="gpt-4o-mini">
                        </div>
                    </div>

                    <h4 style="color: var(--accent); margin: 15px 0 10px;">🧬 Embedding</h4>
                    <div class="form-row cols-4">
                        <div class="form-group">
                            <label for="cfg-graphiti-embed-url">Base URL</label>
                            <input type="text" id="cfg-graphiti-embed-url" placeholder="留空复用 LLM 地址">
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-embed-key">API Key</label>
                            <input type="password" id="cfg-graphiti-embed-key" autocomplete="off">
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-embed-model">模型</label>
                            <input type="text" id="cfg-graphiti-embed-model" placeholder="text-embedding-3-small">
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-embed-dim">向量维度</label>
                            <input type="number" id="cfg-graphiti-embed-dim" min="1" value="1536">
                        </div>
                    </div>

                    <h4 style="color: var(--accent); margin: 15px 0 10px;">🔍 检索策略</h4>
                    <div class="form-row cols-3">
                        <div class="form-group">
                            <label class="checkbox-label" style="margin-top: 24px;">
                                <input type="checkbox" id="cfg-graphiti-reranker">启用 Reranker（复用主模型）
                            </label>
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-strategy">策略</label>
                            <select id="cfg-graphiti-strategy">
                                <option value="auto">auto（自动判断复杂度）</option>
                                <option value="single">single（单次检索）</option>
                                <option value="iterative">iterative（迭代检索）</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-max-iter">最大迭代次数</label>
                            <input type="number" id="cfg-graphiti-max-iter" min="1" max="10" value="3">
                        </div>
                    </div>
                    <div class="form-row cols-3">
                        <div class="form-group">
                            <label for="cfg-graphiti-min-evidence">最少证据数</label>
                            <input type="number" id="cfg-graphiti-min-evidence" min="1" value="2">
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-limit">默认返回数量</label>
                            <input type="number" id="cfg-graphiti-limit" min="1" value="10">
                        </div>
                        <div class="form-group">
                            <label class="checkbox-label" style="margin-top: 24px;">
                                <input type="checkbox" id="cfg-graphiti-include-edges">检索结果包含边
                            </label>
                        </div>
                    </div>
                    <div class="form-row cols-4">
                        <div class="form-group">
                            <label for="cfg-graphiti-sim-score">相似度最低分</label>
                            <input type="number" id="cfg-graphiti-sim-score" min="0" max="1" step="0.05" value="0.4">
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-mmr">MMR Lambda</label>
                            <input type="number" id="cfg-graphiti-mmr" min="0" max="1" step="0.1" value="0.5">
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-daily-limit">每日 Token 限额</label>
                            <input type="number" id="cfg-graphiti-daily-limit" min="0" step="1000" value="100000">
                        </div>
                        <div class="form-group">
                            <label for="cfg-graphiti-semaphore">并发限制</label>
                            <input type="number" id="cfg-graphiti-semaphore" min="1" value="10">
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="checkbox-label">
                            <input type="checkbox" id="cfg-graphiti-sync-conv">对话入库（索引对话到图谱）
                        </label>
                    </div>
                </div>
                <div style="margin-top: 12px;">
                    <button class="btn btn-success" data-action="save-config">💾 保存配置</button>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>🔄 同步控制面板</h3></div>
                <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 15px;">
                    <button class="btn btn-primary" data-action="sync-markdown">📤 同步 Markdown（LLM 抽取）</button>
                    <button class="btn" data-action="sync-nodes-simple">⚡ 一键同步节点（无 LLM）</button>
                    <button class="btn btn-danger" data-action="rebuild-index">🔨 重建索引</button>
                </div>
                <div style="display: flex; gap: 15px; align-items: center; flex-wrap: wrap; margin-bottom: 8px;">
                    <span id="sync-status-text">⚪ 空闲</span>
                    <span id="sync-progress-text" class="text-dim">0 / 0</span>
                    <span class="text-dim" style="font-size: 0.85rem;">当前: <span id="sync-current-file">--</span></span>
                </div>
                <div class="progress-track" style="margin-bottom: 10px;">
                    <div class="progress-bar" id="sync-progress-bar" style="width: 0%;"></div>
                </div>
                <div style="display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
                    <span class="text-dim">📔 日记: <span id="sync-diary-count">0</span></span>
                    <span class="text-dim">📌 节点: <span id="sync-node-count">0</span></span>
                    <span class="text-dim">❌ 失败: <span id="sync-failed-count">0</span></span>
                    <button class="btn btn-sm btn-warning" data-action="pause-sync" id="btn-pause-sync" style="display: none;">⏸️ 暂停</button>
                    <button class="btn btn-sm btn-success" data-action="resume-sync" id="btn-resume-sync" style="display: none;">▶️ 继续</button>
                    <button class="btn btn-sm btn-danger" data-action="stop-sync" id="btn-stop-sync" style="display: none;">⏹️ 停止</button>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>🔍 搜索测试</h3></div>
                <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                    <input type="text" id="graphiti-test-query" class="form-input" placeholder="输入搜索内容..." style="flex: 1; min-width: 240px;">
                    <button class="btn btn-primary" data-action="test-search">🔍 搜索</button>
                </div>
                <div id="graphiti-test-result" style="margin-top: 15px;"></div>
            </div>
        `;

        bindActions(container, {
            'refresh-stats': refreshStats,
            'save-config': saveConfig,
            'sync-markdown': syncMarkdown,
            'sync-nodes-simple': syncNodesSimple,
            'rebuild-index': rebuildIndex,
            'pause-sync': pauseSync,
            'resume-sync': resumeSync,
            'stop-sync': stopSync,
            'test-search': testSearch,
        });

        container.querySelector('#cfg-graphiti-backend').addEventListener('change', (e) => {
            toggleBackendSettings(e.target.value);
        });
        container.querySelector('#graphiti-test-query').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') testSearch();
        });

        const configForm = container.querySelector('#graphiti-config-form');
        configForm.addEventListener('input', () => markDirty(DIRTY_KEY, 'Graphiti 配置'));
        configForm.addEventListener('change', () => markDirty(DIRTY_KEY, 'Graphiti 配置'));
    },

    onEnter() {
        refreshStats();
        refreshSyncStatus();
        if (!isDirty(DIRTY_KEY)) {
            loadConfig();
        }
    },

    onLeave() {
        stopPolling();
    },
};

function toggleBackendSettings(backend) {
    rootEl.querySelector('#kuzu-settings').style.display = backend === 'kuzu' ? '' : 'none';
    rootEl.querySelector('#neo4j-settings').style.display = backend === 'neo4j' ? '' : 'none';
}

// ===== 配置 =====

async function loadConfig() {
    const config = await apiCall('/graphiti/config');
    if (!config || config.error) {
        showToast('加载 Graphiti 配置失败: ' + (config?.error || '未知错误'), 'error');
        return;
    }

    rootEl.querySelector('#cfg-graphiti-enabled').checked = config.enabled || false;
    rootEl.querySelector('#cfg-graphiti-backend').value = config.backend || 'kuzu';
    toggleBackendSettings(config.backend || 'kuzu');

    if (config.kuzu) {
        rootEl.querySelector('#cfg-kuzu-path').value = config.kuzu.db_path || './lifebook/.graphiti.kuzu';
    }
    if (config.neo4j) {
        rootEl.querySelector('#cfg-neo4j-uri').value = config.neo4j.uri || 'bolt://localhost:7687';
        rootEl.querySelector('#cfg-neo4j-user').value = config.neo4j.username || 'neo4j';
        // 密码不回填
    }
    if (config.llm) {
        rootEl.querySelector('#cfg-graphiti-llm-url').value = config.llm.base_url || '';
        rootEl.querySelector('#cfg-graphiti-llm-key').value = config.llm.api_key || '';
        rootEl.querySelector('#cfg-graphiti-model').value = config.llm.model || 'gpt-4o-mini';
    }
    if (config.embedding) {
        rootEl.querySelector('#cfg-graphiti-embed-url').value = config.embedding.base_url || '';
        rootEl.querySelector('#cfg-graphiti-embed-key').value = config.embedding.api_key || '';
        rootEl.querySelector('#cfg-graphiti-embed-model').value = config.embedding.model || 'text-embedding-3-small';
        rootEl.querySelector('#cfg-graphiti-embed-dim').value = config.embedding.dim || 1536;
    } else if (config.llm) {
        // 兼容旧配置：从 llm 节点读取
        rootEl.querySelector('#cfg-graphiti-embed-url').value = config.llm.base_url || '';
        rootEl.querySelector('#cfg-graphiti-embed-model').value = config.llm.embedding_model || 'text-embedding-3-small';
        rootEl.querySelector('#cfg-graphiti-embed-dim').value = config.llm.embedding_dim || 1536;
    }
    if (config.reranker) {
        rootEl.querySelector('#cfg-graphiti-reranker').checked = config.reranker.enabled || false;
    }
    if (config.retrieval) {
        rootEl.querySelector('#cfg-graphiti-strategy').value = config.retrieval.strategy || 'auto';
        rootEl.querySelector('#cfg-graphiti-max-iter').value = config.retrieval.max_iterations ?? 3;
        rootEl.querySelector('#cfg-graphiti-min-evidence').value = config.retrieval.min_evidence_count ?? 2;
        rootEl.querySelector('#cfg-graphiti-limit').value = config.retrieval.default_limit ?? 10;
        rootEl.querySelector('#cfg-graphiti-include-edges').checked = config.retrieval.include_edges !== false;
    }
    if (config.search) {
        rootEl.querySelector('#cfg-graphiti-sim-score').value = config.search.sim_min_score ?? 0.4;
        rootEl.querySelector('#cfg-graphiti-mmr').value = config.search.mmr_lambda ?? 0.5;
    }
    if (config.performance) {
        rootEl.querySelector('#cfg-graphiti-daily-limit').value = config.performance.daily_token_limit ?? 100000;
        rootEl.querySelector('#cfg-graphiti-semaphore').value = config.performance.semaphore_limit ?? 10;
    }
    if (config.sync) {
        rootEl.querySelector('#cfg-graphiti-sync-conv').checked = config.sync.index_conversations !== false;
    }
}

async function saveConfig() {
    const $ = (sel) => rootEl.querySelector(sel);

    const config = {
        enabled: $('#cfg-graphiti-enabled').checked,
        backend: $('#cfg-graphiti-backend').value,
        kuzu: { db_path: $('#cfg-kuzu-path').value },
        neo4j: {
            uri: $('#cfg-neo4j-uri').value,
            username: $('#cfg-neo4j-user').value,
        },
        llm: {
            base_url: $('#cfg-graphiti-llm-url').value || null,
            model: $('#cfg-graphiti-model').value,
        },
        embedding: {
            base_url: $('#cfg-graphiti-embed-url').value || null,
            model: $('#cfg-graphiti-embed-model').value,
            dim: parseInt($('#cfg-graphiti-embed-dim').value) || 1536,
        },
        reranker: {
            enabled: $('#cfg-graphiti-reranker').checked,
            model: $('#cfg-graphiti-model').value, // 复用主模型
        },
        retrieval: {
            strategy: $('#cfg-graphiti-strategy').value,
            max_iterations: parseInt($('#cfg-graphiti-max-iter').value) || 3,
            min_evidence_count: parseInt($('#cfg-graphiti-min-evidence').value) || 2,
            default_limit: parseInt($('#cfg-graphiti-limit').value) || 10,
            include_edges: $('#cfg-graphiti-include-edges').checked,
        },
        search: {
            sim_min_score: parseFloat($('#cfg-graphiti-sim-score').value) || 0.4,
            mmr_lambda: parseFloat($('#cfg-graphiti-mmr').value) || 0.5,
        },
        performance: {
            daily_token_limit: parseInt($('#cfg-graphiti-daily-limit').value) || 100000,
            semaphore_limit: parseInt($('#cfg-graphiti-semaphore').value) || 10,
        },
        sync: {
            index_conversations: $('#cfg-graphiti-sync-conv').checked,
        },
    };

    // 密码与 API Key：仅在填写且非掩码时提交
    const neo4jPass = $('#cfg-neo4j-pass').value;
    if (neo4jPass) config.neo4j.password = neo4jPass;

    const llmApiKey = $('#cfg-graphiti-llm-key').value;
    if (llmApiKey && !llmApiKey.includes('***')) config.llm.api_key = llmApiKey;

    const embedApiKey = $('#cfg-graphiti-embed-key').value;
    if (embedApiKey && !embedApiKey.includes('***')) config.embedding.api_key = embedApiKey;

    const result = await apiCall('/graphiti/config', 'POST', config);
    if (result && result.success) {
        clearDirty(DIRTY_KEY);
        showToast('Graphiti 配置已保存', 'success');
        refreshStats();
    } else {
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

// ===== 状态监控 =====

async function refreshStats() {
    const stats = await apiCall('/graphiti/stats');
    if (stats && !stats.error) {
        const statusEl = rootEl.querySelector('#graphiti-status-text');
        if (!stats.enabled) {
            statusEl.textContent = '未启用';
            statusEl.style.color = 'var(--text-dim)';
        } else if (stats.status === 'running') {
            statusEl.textContent = '运行中';
            statusEl.style.color = 'var(--success)';
        } else {
            statusEl.textContent = stats.status || '未知';
            statusEl.style.color = 'var(--warning)';
        }

        const dbEl = rootEl.querySelector('#graphiti-sync-status');
        if (stats.kuzu_db_exists) {
            const sizeMB = (stats.kuzu_db_size / 1024 / 1024).toFixed(2);
            dbEl.textContent = `数据库大小: ${sizeMB} MB`;
        } else {
            dbEl.textContent = stats.enabled ? '数据库未创建' : '--';
        }
    }
    await refreshTokenUsage();
}

async function refreshTokenUsage() {
    const data = await apiCall('/graphiti/token-usage');
    if (!data || data.error) return;

    rootEl.querySelector('#graphiti-used-tokens').textContent = (data.used ?? 0).toLocaleString();
    rootEl.querySelector('#graphiti-limit-tokens').textContent = (data.limit ?? 0).toLocaleString();
    rootEl.querySelector('#graphiti-remain-tokens').textContent = (data.remaining ?? 0).toLocaleString();

    const bar = rootEl.querySelector('#graphiti-usage-bar');
    const percent = data.percent || 0;
    bar.style.width = percent + '%';
    bar.style.background = percent > 80 ? 'var(--danger)' : percent > 50 ? 'var(--warning)' : 'var(--success)';
}

// ===== 同步管理 =====

async function syncMarkdown() {
    const ok = await confirmDialog('确定要将所有 Markdown 同步到 Graphiti 吗？\n这可能需要几分钟时间并消耗 Token。', { okText: '开始同步' });
    if (!ok) return;

    const result = await apiCall('/graphiti/sync', 'POST', { include_diaries: true, include_nodes: true });
    if (result && result.success) {
        showToast('同步任务已启动', 'success');
        startPolling();
    } else if (result && result.status) {
        showToast(result.error || '同步任务正在进行中', 'warning');
        startPolling();
    } else {
        showToast('同步失败: ' + (result?.error || '未知错误'), 'error');
    }
}

async function syncNodesSimple() {
    const ok = await confirmDialog('确定要将 LifeBook 的已有节点同步到 Graphiti 吗？\n\n这不会使用 LLM，速度快且无 Token 消耗。', { okText: '同步' });
    if (!ok) return;

    const result = await apiCall('/graphiti/sync-nodes-simple', 'POST');
    if (result && result.success) {
        showToast(`同步完成：${result.synced_count} 个节点`, 'success');
        refreshStats();
    } else {
        showToast('同步失败: ' + (result?.error || '未知错误'), 'error');
    }
}

async function rebuildIndex() {
    const ok1 = await confirmDialog('⚠️ 确定要重建 Graphiti 索引吗？\n\n这将：\n1. 删除现有图数据库\n2. 重新从 Markdown 构建\n\n此操作不可逆！', { danger: true, okText: '继续' });
    if (!ok1) return;
    const ok2 = await confirmDialog('再次确认：重建索引将清空所有 Graphiti 数据。\n\n确定继续？', { danger: true, okText: '重建' });
    if (!ok2) return;

    const dbEl = rootEl.querySelector('#graphiti-sync-status');
    dbEl.textContent = '重建中...';

    const result = await apiCall('/graphiti/rebuild', 'POST', { confirm: true });
    if (result && result.success) {
        showToast(result.message || '重建完成', 'success');
        dbEl.textContent = '重建完成';
        refreshStats();
    } else {
        showToast('重建失败: ' + (result?.error || '未知错误'), 'error');
        dbEl.textContent = '重建失败';
    }
}

function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(refreshSyncStatus, 1000);
    refreshSyncStatus();
}

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

async function refreshSyncStatus() {
    if (document.hidden) return;   // 后台标签页暂停请求，回到前台下个周期自动恢复
    const status = await apiCall('/graphiti/sync/status');
    if (!status || status.error) return;

    updateSyncPanel(status);

    // 检测到任务运行中，自动恢复轮询（如刷新页面后回来）
    if (status.is_running && !pollTimer) {
        startPolling();
    }
    // 完成或失败时停止轮询
    if (!status.is_running && status.status !== 'idle') {
        stopPolling();
        if (status.status === 'completed') {
            showToast(`同步完成：${status.synced_diaries} 日记，${status.synced_nodes} 节点`, 'success');
            refreshStats();
        } else if (status.status === 'failed') {
            showToast('同步失败: ' + (status.error || '未知错误'), 'error');
        }
    }
}

function updateSyncPanel(status) {
    const $ = (sel) => rootEl.querySelector(sel);
    const statusText = $('#sync-status-text');
    if (!statusText) return;

    const statusMap = {
        idle: '⚪ 空闲',
        running: '🔄 同步中...',
        paused: '⏸️ 已暂停',
        stopping: '⏹️ 正在停止...',
        completed: '✅ 完成',
        failed: '❌ 失败',
    };
    statusText.textContent = statusMap[status.status] || status.status;

    const percent = status.total_files > 0
        ? Math.round((status.current_index / status.total_files) * 100)
        : 0;
    const bar = $('#sync-progress-bar');
    bar.style.width = percent + '%';
    bar.style.background =
        status.status === 'paused' ? 'var(--warning)' :
        status.status === 'failed' ? 'var(--danger)' :
        status.status === 'completed' ? 'var(--success)' : 'var(--accent)';

    $('#sync-progress-text').textContent = `${status.current_index} / ${status.total_files}`;
    $('#sync-current-file').textContent = status.current_file || '--';
    $('#sync-diary-count').textContent = status.synced_diaries || 0;
    $('#sync-node-count').textContent = status.synced_nodes || 0;
    $('#sync-failed-count').textContent = status.failed_files?.length || 0;

    $('#btn-pause-sync').style.display = status.can_pause ? '' : 'none';
    $('#btn-resume-sync').style.display = status.can_resume ? '' : 'none';
    $('#btn-stop-sync').style.display = status.can_stop ? '' : 'none';
}

async function pauseSync() {
    const result = await apiCall('/graphiti/sync/pause', 'POST');
    if (result && result.success) {
        showToast('同步已暂停', 'success');
    } else {
        showToast(result?.error || '暂停失败', 'error');
    }
}

async function resumeSync() {
    const result = await apiCall('/graphiti/sync/resume', 'POST');
    if (result && result.success) {
        showToast('同步已继续', 'success');
        startPolling();
    } else {
        showToast(result?.error || '继续失败', 'error');
    }
}

async function stopSync() {
    const ok = await confirmDialog('确定要停止同步吗？已同步的内容会保留。', { okText: '停止' });
    if (!ok) return;

    const result = await apiCall('/graphiti/sync/stop', 'POST');
    if (result && result.success) {
        showToast('同步正在停止...', 'success');
    } else {
        showToast(result?.error || '停止失败', 'error');
    }
}

// ===== 搜索测试 =====

async function testSearch() {
    const query = rootEl.querySelector('#graphiti-test-query').value.trim();
    const resultEl = rootEl.querySelector('#graphiti-test-result');
    if (!query) {
        showToast('请输入搜索内容', 'error');
        return;
    }

    resultEl.innerHTML = spinnerHtml('搜索中...');

    const data = await apiCall('/graphiti/search', 'POST', { query, num_results: 10 });
    if (!data || data.error) {
        resultEl.innerHTML = `<div class="alert alert-danger"><span>❌</span><div>${escapeHtml(data?.error || '搜索失败')}</div></div>`;
        return;
    }
    if (!data.results || data.results.length === 0) {
        resultEl.innerHTML = '<p class="text-dim">未找到相关结果</p>';
        return;
    }

    let html = `<p class="text-dim" style="margin-bottom: 10px;">找到 ${data.count} 条结果：</p>`;
    for (const r of data.results) {
        const score = r.score ? `(${r.score.toFixed(3)})` : '';
        const source = r.source ? `<span style="color: var(--accent);">[${escapeHtml(r.source)}]</span>` : '';
        const type = r.type === 'edge' ? '🔗' : '📦';
        html += `
            <div style="padding: 10px; margin-bottom: 8px; background: var(--surface-2); border-radius: 6px;">
                <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 5px;">
                    <span>${type}</span>
                    ${source}
                    <span class="text-dim" style="font-size: 0.85rem;">${score}</span>
                </div>
                <div style="font-size: 0.9rem;">${escapeHtml(r.content || '')}</div>
            </div>
        `;
    }
    resultEl.innerHTML = html;
}

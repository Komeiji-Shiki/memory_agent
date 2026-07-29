/**
 * 概览页
 * - 统计卡片（日记/标签/节点/交互/Graphiti 状态）
 * - 对话趋势图表（最近 N 天会话数/轮次数）
 * - 快速使用说明
 * - 可用模型列表
 */

import { apiCall, fetchJson } from '../core/api.js';
import { escapeHtml, spinnerHtml, emptyHtml, errorHtml, bindActions } from '../core/ui.js';
import { drawTrendChart } from '../core/chart.js';
import { loadPref, savePref } from '../core/store.js';

let chart = null;
let rootEl = null;

export const overviewPage = {
    id: 'overview',
    title: '概览',
    icon: '📊',
    group: 'top',

    render(container) {
        rootEl = container;
        const trendDays = loadPref('overview.trendDays', 14);
        container.innerHTML = `
            <div class="page-header">
                <h2>系统概览</h2>
                <p>LifeBook Memory Agent 运行状态</p>
            </div>

            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-card-label">📅 日记数量</div>
                    <div class="stat-card-value" id="ov-stat-diaries">--</div>
                    <div class="stat-card-detail">条记录</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label">🏷️ 标签数量</div>
                    <div class="stat-card-value" id="ov-stat-tags">--</div>
                    <div class="stat-card-detail">个标签</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label">📦 节点数量</div>
                    <div class="stat-card-value" id="ov-stat-nodes">--</div>
                    <div class="stat-card-detail">个节点</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label">💬 交互次数</div>
                    <div class="stat-card-value" id="ov-stat-interactions">--</div>
                    <div class="stat-card-detail">次对话</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label">🔗 Graphiti 状态</div>
                    <div class="stat-card-value" id="ov-stat-graphiti">--</div>
                    <div class="stat-card-detail" id="ov-stat-graphiti-detail">未启用</div>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>📈 对话趋势</h3>
                    <div class="card-actions">
                        <select id="ov-trend-days" class="form-select" style="width: 110px;">
                            <option value="7"${trendDays === 7 ? ' selected' : ''}>最近 7 天</option>
                            <option value="14"${trendDays === 14 ? ' selected' : ''}>最近 14 天</option>
                            <option value="30"${trendDays === 30 ? ' selected' : ''}>最近 30 天</option>
                        </select>
                        <button class="btn btn-sm" data-action="refresh-trend">🔄 刷新</button>
                    </div>
                </div>
                <div class="chart-box">
                    <canvas id="ov-trend-canvas"></canvas>
                    <div class="chart-legend" id="ov-trend-legend"></div>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>快速使用</h3>
                </div>
                <div class="alert alert-info">
                    <span>ℹ️</span>
                    <div>
                        <strong>使用方式（模型名后缀决定行为）：</strong>
                        <ul style="margin-top: 10px; padding-left: 20px;">
                            <li><code>模型名-memory</code> - 记忆增强模式</li>
                            <li><code>模型名-record</code> - 记录 + 总结模式</li>
                            <li><code>memory-manager</code> - 记忆管理模式</li>
                            <li><code>模型名</code> - 直接透传</li>
                        </ul>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>可用模型</h3>
                    <button class="btn btn-sm btn-primary" data-action="refresh-models">🔄 刷新</button>
                </div>
                <div id="ov-models">${spinnerHtml()}</div>
            </div>
        `;

        bindActions(container, {
            'refresh-trend': () => loadTrend(),
            'refresh-models': () => loadModels(),
        });
        container.querySelector('#ov-trend-days').addEventListener('change', (e) => {
            savePref('overview.trendDays', parseInt(e.target.value, 10));
            loadTrend();
        });
    },

    onEnter() {
        loadStats();
        loadGraphitiStat();
        loadTrend();
        loadModels();
    },
};

async function loadStats() {
    const stats = await apiCall('/stats');
    if (!stats || stats.error) return;
    setText('ov-stat-diaries', stats.diary_count || 0);
    setText('ov-stat-tags', stats.tag_count || 0);
    // 节点总数 = by_type 中所有 node_ 前缀类型之和
    const byType = stats.by_type || {};
    let totalNodes = 0;
    for (const [key, count] of Object.entries(byType)) {
        if (key.startsWith('node_')) totalNodes += count;
    }
    setText('ov-stat-nodes', totalNodes);
    setText('ov-stat-interactions', stats.interaction_count || 0);
}

async function loadGraphitiStat() {
    const stats = await apiCall('/graphiti/stats');
    const valueEl = rootEl.querySelector('#ov-stat-graphiti');
    const detailEl = rootEl.querySelector('#ov-stat-graphiti-detail');
    if (!stats || stats.error) {
        valueEl.textContent = '错误';
        detailEl.textContent = stats?.error || '获取失败';
        return;
    }
    if (!stats.enabled) {
        valueEl.textContent = '关闭';
        detailEl.textContent = '未启用';
    } else if (stats.status === 'running') {
        valueEl.textContent = '运行中';
        let detail = stats.backend || '';
        if (stats.kuzu_db_size) {
            detail += ` · ${(stats.kuzu_db_size / 1024 / 1024).toFixed(1)} MB`;
        }
        detailEl.textContent = detail;
    } else {
        valueEl.textContent = '不可用';
        detailEl.textContent = stats.error || '适配器初始化失败';
    }
}

async function loadTrend() {
    const days = parseInt(rootEl.querySelector('#ov-trend-days').value, 10) || 14;
    const data = await apiCall(`/conversations/trend?days=${days}`);
    const canvas = rootEl.querySelector('#ov-trend-canvas');
    const legendEl = rootEl.querySelector('#ov-trend-legend');
    if (!data || data.error || !Array.isArray(data.days)) {
        legendEl.innerHTML = `<span class="text-dim">趋势数据加载失败${data?.error ? ': ' + escapeHtml(data.error) : ''}</span>`;
        return;
    }
    const chartData = {
        labels: data.days.map((d) => d.date),
        series: [
            { name: '对话轮次', values: data.days.map((d) => d.turns) },
            { name: '会话数', values: data.days.map((d) => d.sessions) },
        ],
    };
    if (chart) {
        chart.redraw(chartData);
    } else {
        chart = drawTrendChart(canvas, chartData);
    }
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
    const success = getComputedStyle(document.documentElement).getPropertyValue('--success').trim();
    legendEl.innerHTML = `
        <span><span class="dot" style="background:${accent}"></span>对话轮次</span>
        <span><span class="dot" style="background:${success}"></span>会话数</span>`;
}

async function loadModels() {
    const container = rootEl.querySelector('#ov-models');
    container.innerHTML = spinnerHtml();
    const data = await fetchJson('/v1/models');
    if (!data || data.error || !Array.isArray(data.data)) {
        container.innerHTML = errorHtml('模型列表加载失败' + (data?.error ? ': ' + data.error : ''));
        return;
    }
    if (data.data.length === 0) {
        container.innerHTML = emptyHtml('暂无模型');
        return;
    }
    let html = '<table class="table"><thead><tr><th>模型 ID</th><th>类型</th></tr></thead><tbody>';
    for (const m of data.data) {
        html += `<tr><td><code>${escapeHtml(m.id)}</code></td><td>${modelBadge(m.id)}</td></tr>`;
    }
    html += '</tbody></table>';
    container.innerHTML = html;
}

function modelBadge(modelId) {
    const isManager = ['memory-manager', 'memory-agent', 'lifebook'].includes(modelId);
    if (modelId.endsWith('-memory')) return '<span class="badge badge-success">记忆增强</span>';
    if (modelId.endsWith('-memory-simple')) return '<span class="badge badge-success">记忆增强(简化)</span>';
    if (modelId.endsWith('-record')) return '<span class="badge badge-warning">记录+总结</span>';
    if (modelId.endsWith('-log-write')) return '<span class="badge badge-warning">日志+记忆读写</span>';
    if (modelId.endsWith('-log')) return '<span class="badge badge-info">仅日志</span>';
    if (isManager) return '<span class="badge badge-warning">记忆管理</span>';
    return '<span class="badge badge-info">透传</span>';
}

function setText(id, value) {
    const el = rootEl.querySelector('#' + id);
    if (el) el.textContent = value;
}

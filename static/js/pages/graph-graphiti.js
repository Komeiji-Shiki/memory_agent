/**
 * Graphiti 时序知识图谱 tab（vis-network）
 * - GET /graphiti/graph-data 渲染：类型着色、importance 决定节点大小
 * - 节点/边 CRUD：/graphiti/nodes[/<uuid>]、/graphiti/edges[/<uuid>]（边含 valid_at/invalid_at 时序字段）
 * - 主题适配：vis 不识别 CSS 变量，从 computed style 读取 token，themechange 时由壳触发 redraw
 */

import { apiCall } from '../core/api.js';
import {
    showToast, showModal, closeModal, confirmDialog,
    escapeHtml, escapeAttr, spinnerHtml, bindActions,
} from '../core/ui.js';

let rootEl = null;
let network = null;
let lastData = null;

export const graphitiGraphTab = {
    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>⏳ Graphiti 图谱</h3>
                    <span id="graphiti-graph-status" class="text-dim"></span>
                </div>
                <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px;">
                    <button class="btn btn-sm" data-action="refresh-graphiti">🔄 刷新</button>
                    <button class="btn btn-sm" data-action="fit-graphiti">🎯 适应视图</button>
                    <button class="btn btn-sm btn-success" data-action="create-node">➕ 新建节点</button>
                    <button class="btn btn-sm btn-primary" data-action="create-edge">🔗 新建边</button>
                </div>
                <div id="graphiti-graph-container" style="height: 600px; border: 1px solid var(--line-weak); border-radius: 8px;"></div>
                <div id="graphiti-graph-stats" class="text-dim" style="margin-top: 10px; font-size: 0.85rem;"></div>
            </div>
        `;

        bindActions(container, {
            'refresh-graphiti': loadGraph,
            'fit-graphiti': fitView,
            'create-node': showCreateNodeDialog,
            'create-edge': showCreateEdgeDialog,
        });
    },

    load() {
        loadGraph();
    },

    redraw() {
        if (lastData) renderNetwork(lastData);
    },
};

/** 读取 CSS 变量（vis-network 不识别 var()） */
function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
}

async function loadGraph() {
    const container = rootEl.querySelector('#graphiti-graph-container');
    const statusEl = rootEl.querySelector('#graphiti-graph-status');
    statusEl.textContent = '加载中...';
    container.innerHTML = spinnerHtml('加载图谱数据...');

    const data = await apiCall('/graphiti/graph-data?limit=100');
    if (!data || data.error) {
        statusEl.textContent = '加载失败';
        container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--danger);">加载失败: ${escapeHtml(data?.error || '未知错误')}</div>`;
        return;
    }

    if (!data.nodes || data.nodes.length === 0) {
        statusEl.textContent = '暂无图谱数据';
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);">暂无图谱数据，请先在 Graphiti 配置页同步 Markdown</div>';
        return;
    }

    renderNetwork(data);
}

function renderNetwork(data) {
    lastData = data;
    const container = rootEl.querySelector('#graphiti-graph-container');
    const statusEl = rootEl.querySelector('#graphiti-graph-status');
    container.innerHTML = '';

    if (network) {
        network.destroy();
        network = null;
    }

    const textMain = cssVar('--text-main', '#d9e5ff');
    const textDim = cssVar('--text-dim', '#8fa0bf');
    const labelBg = cssVar('--card-bg', 'rgba(14, 26, 45, 0.8)');
    const edgeColor = cssVar('--line-weak', '#3d5a80');

    const visNodes = data.nodes.map((n) => ({
        id: n.uuid || n.id,
        label: truncateLabel(n.name || n.label || n.uuid, 20),
        title: `${n.name || n.label}\n${n.summary || ''}`,
        color: getNodeColor(n.type || n.label_type),
        shape: 'dot',
        size: 15 + (n.importance || 0) * 5,
    }));

    const visEdges = data.edges.map((e) => ({
        id: e.uuid || `${e.source}-${e.target}`,
        from: e.source_uuid || e.source,
        to: e.target_uuid || e.target,
        label: truncateLabel(e.name || e.type || '', 15),
        title: e.fact || e.name || '',
        arrows: 'to',
        color: { color: edgeColor, opacity: 0.7 },
        smooth: { type: 'curvedCW', roundness: 0.2 },
    }));

    const graphData = {
        nodes: new vis.DataSet(visNodes),
        edges: new vis.DataSet(visEdges),
    };

    const options = {
        nodes: {
            font: { color: textMain, size: 12 },
            borderWidth: 2,
            shadow: true,
        },
        edges: {
            font: {
                color: textDim,
                size: 11,
                align: 'middle',
                strokeWidth: 0,
                background: labelBg,
            },
            smooth: { type: 'curvedCW', roundness: 0.15 },
            width: 1.5,
        },
        physics: {
            enabled: true,
            solver: 'forceAtlas2Based',
            forceAtlas2Based: {
                gravitationalConstant: -50,
                centralGravity: 0.01,
                springLength: 100,
                springConstant: 0.08,
            },
            stabilization: { iterations: 100 },
        },
        interaction: {
            hover: true,
            tooltipDelay: 200,
        },
    };

    network = new vis.Network(container, graphData, options);

    network.on('click', (params) => {
        if (params.nodes.length > 0) {
            openNodeDetail(params.nodes[0]);
        } else if (params.edges.length > 0) {
            openEdgeDetail(params.edges[0]);
        }
    });
    network.on('doubleClick', (params) => {
        if (params.nodes.length > 0) {
            network.focus(params.nodes[0], {
                scale: 1.5,
                animation: { duration: 500, easingFunction: 'easeInOutQuad' },
            });
        }
    });

    statusEl.textContent = `${visNodes.length} 节点, ${visEdges.length} 边`;
    rootEl.querySelector('#graphiti-graph-stats').innerHTML = `
        <span>📦 ${visNodes.length} 节点</span> |
        <span>🔗 ${visEdges.length} 边</span> |
        <span class="text-dim">点击节点/边查看详情，双击节点聚焦</span>
    `;
}

function fitView() {
    if (network) {
        network.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
    }
}

function truncateLabel(text, maxLen) {
    if (!text) return '';
    return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
}

function getNodeColor(type) {
    const colors = {
        'Person': '#e91e63', '人物': '#e91e63',
        'Location': '#4caf50', '地点': '#4caf50',
        'Organization': '#2196f3', '组织': '#2196f3',
        'Event': '#ff9800', '事件': '#ff9800',
        'Concept': '#9c27b0', '概念': '#9c27b0',
        'Object': '#00bcd4', '物品': '#00bcd4',
        'default': '#78909c',
    };
    return colors[type] || colors['default'];
}

// ===== 节点详情 / 编辑 =====

async function openNodeDetail(uuid) {
    const data = await apiCall(`/graphiti/nodes/${uuid}`);
    if (!data || !data.success) {
        showToast('获取节点详情失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }
    showNodeDetailModal(data.node, data.edges || []);
}

function showNodeDetailModal(node, edges) {
    const labelsStr = (node.labels || []).join(', ');

    const edgesHtml = edges.length > 0
        ? edges.map((e) => `
            <div data-action="open-edge" data-uuid="${escapeAttr(e.uuid)}" style="padding: 8px; margin: 5px 0; background: var(--surface-2); border-radius: 6px; cursor: pointer;">
                <div><strong>${escapeHtml(e.name)}</strong></div>
                <div style="font-size: 0.85rem;" class="text-dim">${escapeHtml((e.fact || '').substring(0, 100))}...</div>
            </div>
        `).join('')
        : '<p class="text-dim">暂无关联边</p>';

    const modal = showModal('📦 节点详情', `
        <div class="form-group">
            <label>名称</label>
            <input type="text" id="edit-node-name" value="${escapeAttr(node.name)}">
        </div>
        <div class="form-group">
            <label>摘要</label>
            <textarea id="edit-node-summary" rows="4">${escapeHtml(node.summary || '')}</textarea>
        </div>
        <div class="form-group">
            <label>标签 (逗号分隔)</label>
            <input type="text" id="edit-node-labels" value="${escapeAttr(labelsStr)}">
        </div>
        <div class="form-row cols-2">
            <div class="form-group">
                <label>UUID</label>
                <input type="text" value="${escapeAttr(node.uuid)}" readonly style="opacity: 0.6;">
            </div>
            <div class="form-group">
                <label>创建时间</label>
                <input type="text" value="${escapeAttr(node.created_at || '--')}" readonly style="opacity: 0.6;">
            </div>
        </div>
        <h4 style="margin-top: 20px; color: var(--accent);">🔗 关联边 (${edges.length})</h4>
        <div style="max-height: 200px; overflow-y: auto;">${edgesHtml}</div>
    `, {
        size: 'large',
        footer: `
            <button class="btn btn-danger" data-act="del">🗑️ 删除</button>
            <button class="btn" data-modal-close>取消</button>
            <button class="btn btn-success" data-act="save">💾 保存</button>
        `,
    });

    bindActions(modal, {
        'open-edge': (t) => {
            closeModal();
            openEdgeDetail(t.dataset.uuid);
        },
    });
    modal.querySelector('[data-act="save"]').addEventListener('click', () => saveNodeEdit(node.uuid, modal));
    modal.querySelector('[data-act="del"]').addEventListener('click', () => deleteNode(node.uuid));
}

async function saveNodeEdit(uuid, modal) {
    const name = modal.querySelector('#edit-node-name').value.trim();
    const summary = modal.querySelector('#edit-node-summary').value.trim();
    const labelsStr = modal.querySelector('#edit-node-labels').value.trim();
    const labels = labelsStr ? labelsStr.split(',').map((l) => l.trim()).filter((l) => l) : [];

    if (!name) {
        showToast('节点名称不能为空', 'error');
        return;
    }

    const data = await apiCall(`/graphiti/nodes/${uuid}`, 'PUT', { name, summary, labels });
    if (data && data.success) {
        showToast('节点更新成功', 'success');
        closeModal();
        loadGraph();
    } else {
        showToast('更新失败: ' + (data?.error || '未知错误'), 'error');
    }
}

async function deleteNode(uuid) {
    const ok = await confirmDialog('确定要删除这个节点吗？\n相关的边也会被删除，此操作不可逆！', { danger: true, okText: '删除' });
    if (!ok) return;

    const data = await apiCall(`/graphiti/nodes/${uuid}`, 'DELETE');
    if (data && data.success) {
        showToast('节点已删除', 'success');
        closeModal();
        loadGraph();
    } else {
        showToast('删除失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 边详情 / 编辑 =====

async function openEdgeDetail(uuid) {
    const data = await apiCall(`/graphiti/edges/${uuid}`);
    if (!data || !data.success) {
        showToast('获取边详情失败: ' + (data?.error || '未知错误'), 'error');
        return;
    }
    showEdgeDetailModal(data.edge, data.source_node, data.target_node);
}

function showEdgeDetailModal(edge, sourceNode, targetNode) {
    const sourceName = sourceNode ? sourceNode.name : edge.source_node_uuid.substring(0, 8);
    const targetName = targetNode ? targetNode.name : edge.target_node_uuid.substring(0, 8);

    const modal = showModal('🔗 边详情', `
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 20px; padding: 15px; background: var(--surface-2); border-radius: 8px; flex-wrap: wrap;">
            <span class="badge badge-info" data-action="open-node" data-uuid="${escapeAttr(edge.source_node_uuid)}" style="cursor: pointer;">${escapeHtml(sourceName)}</span>
            <span>→</span>
            <strong style="color: var(--accent);">${escapeHtml(edge.name)}</strong>
            <span>→</span>
            <span class="badge badge-info" data-action="open-node" data-uuid="${escapeAttr(edge.target_node_uuid)}" style="cursor: pointer;">${escapeHtml(targetName)}</span>
        </div>
        <div class="form-group">
            <label>关系名称</label>
            <input type="text" id="edit-edge-name" value="${escapeAttr(edge.name)}">
        </div>
        <div class="form-group">
            <label>事实描述</label>
            <textarea id="edit-edge-fact" rows="4">${escapeHtml(edge.fact || '')}</textarea>
        </div>
        <div class="form-row cols-2">
            <div class="form-group">
                <label>生效时间 (valid_at)</label>
                <input type="datetime-local" id="edit-edge-valid-at" value="${edge.valid_at ? escapeAttr(edge.valid_at.substring(0, 16)) : ''}">
            </div>
            <div class="form-group">
                <label>失效时间 (invalid_at)</label>
                <input type="datetime-local" id="edit-edge-invalid-at" value="${edge.invalid_at ? escapeAttr(edge.invalid_at.substring(0, 16)) : ''}">
            </div>
        </div>
        <div class="form-group">
            <label>UUID</label>
            <input type="text" value="${escapeAttr(edge.uuid)}" readonly style="opacity: 0.6;">
        </div>
    `, {
        size: 'large',
        footer: `
            <button class="btn btn-danger" data-act="del">🗑️ 删除</button>
            <button class="btn" data-modal-close>取消</button>
            <button class="btn btn-success" data-act="save">💾 保存</button>
        `,
    });

    bindActions(modal, {
        'open-node': (t) => {
            closeModal();
            openNodeDetail(t.dataset.uuid);
        },
    });
    modal.querySelector('[data-act="save"]').addEventListener('click', () => saveEdgeEdit(edge.uuid, modal));
    modal.querySelector('[data-act="del"]').addEventListener('click', () => deleteEdge(edge.uuid));
}

async function saveEdgeEdit(uuid, modal) {
    const name = modal.querySelector('#edit-edge-name').value.trim();
    const fact = modal.querySelector('#edit-edge-fact').value.trim();
    const validAtStr = modal.querySelector('#edit-edge-valid-at').value;
    const invalidAtStr = modal.querySelector('#edit-edge-invalid-at').value;

    if (!name || !fact) {
        showToast('关系名称和事实描述不能为空', 'error');
        return;
    }

    const payload = { name, fact };
    if (validAtStr) payload.valid_at = new Date(validAtStr).toISOString();
    if (invalidAtStr) payload.invalid_at = new Date(invalidAtStr).toISOString();

    const data = await apiCall(`/graphiti/edges/${uuid}`, 'PUT', payload);
    if (data && data.success) {
        showToast('边更新成功', 'success');
        closeModal();
        loadGraph();
    } else {
        showToast('更新失败: ' + (data?.error || '未知错误'), 'error');
    }
}

async function deleteEdge(uuid) {
    const ok = await confirmDialog('确定要删除这条边吗？此操作不可逆！', { danger: true, okText: '删除' });
    if (!ok) return;

    const data = await apiCall(`/graphiti/edges/${uuid}`, 'DELETE');
    if (data && data.success) {
        showToast('边已删除', 'success');
        closeModal();
        loadGraph();
    } else {
        showToast('删除失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 创建节点 / 边 =====

function showCreateNodeDialog() {
    const modal = showModal('✨ 创建新节点', `
        <div class="form-group">
            <label>节点名称 *</label>
            <input type="text" id="new-node-name" placeholder="例如：张三、北京、项目A">
        </div>
        <div class="form-group">
            <label>摘要描述</label>
            <textarea id="new-node-summary" rows="3" placeholder="对节点的描述..."></textarea>
        </div>
        <div class="form-group">
            <label>标签 (逗号分隔)</label>
            <input type="text" id="new-node-labels" placeholder="Person, Location, Project...">
        </div>
    `, {
        footer: `
            <button class="btn" data-modal-close>取消</button>
            <button class="btn btn-success" data-act="create">✨ 创建</button>
        `,
    });

    modal.querySelector('#new-node-name').focus();
    modal.querySelector('[data-act="create"]').addEventListener('click', async () => {
        const name = modal.querySelector('#new-node-name').value.trim();
        const summary = modal.querySelector('#new-node-summary').value.trim();
        const labelsStr = modal.querySelector('#new-node-labels').value.trim();
        const labels = labelsStr ? labelsStr.split(',').map((l) => l.trim()).filter((l) => l) : [];

        if (!name) {
            showToast('节点名称不能为空', 'error');
            return;
        }

        const data = await apiCall('/graphiti/nodes', 'POST', { name, summary, labels });
        if (data && data.success) {
            showToast('节点创建成功', 'success');
            closeModal();
            loadGraph();
        } else {
            showToast('创建失败: ' + (data?.error || '未知错误'), 'error');
        }
    });
}

async function showCreateEdgeDialog() {
    const listData = await apiCall('/graphiti/nodes?limit=100');
    if (!listData || !listData.success) {
        showToast('获取节点列表失败', 'error');
        return;
    }
    const nodes = listData.nodes || [];
    if (nodes.length < 2) {
        showToast('至少需要2个节点才能创建边', 'warning');
        return;
    }

    const nodeOptions = nodes.map((n) =>
        `<option value="${escapeAttr(n.uuid)}">${escapeHtml(n.name)}</option>`
    ).join('');

    const modal = showModal('🔗 创建新边', `
        <div style="display: grid; grid-template-columns: 1fr auto 1fr; gap: 10px; align-items: end; margin-bottom: 20px;">
            <div class="form-group" style="margin: 0;">
                <label>源节点 *</label>
                <select id="new-edge-source">${nodeOptions}</select>
            </div>
            <div style="padding-bottom: 10px;">→</div>
            <div class="form-group" style="margin: 0;">
                <label>目标节点 *</label>
                <select id="new-edge-target">${nodeOptions}</select>
            </div>
        </div>
        <div class="form-group">
            <label>关系名称 *</label>
            <input type="text" id="new-edge-name" placeholder="例如：认识、属于、参与">
        </div>
        <div class="form-group">
            <label>事实描述 *</label>
            <textarea id="new-edge-fact" rows="3" placeholder="描述这个关系的具体事实..."></textarea>
        </div>
        <div class="form-row cols-2">
            <div class="form-group">
                <label>生效时间</label>
                <input type="datetime-local" id="new-edge-valid-at">
            </div>
            <div class="form-group">
                <label>失效时间</label>
                <input type="datetime-local" id="new-edge-invalid-at">
            </div>
        </div>
    `, {
        size: 'large',
        footer: `
            <button class="btn" data-modal-close>取消</button>
            <button class="btn btn-success" data-act="create">🔗 创建</button>
        `,
    });

    modal.querySelector('#new-edge-name').focus();
    modal.querySelector('[data-act="create"]').addEventListener('click', async () => {
        const sourceUuid = modal.querySelector('#new-edge-source').value;
        const targetUuid = modal.querySelector('#new-edge-target').value;
        const name = modal.querySelector('#new-edge-name').value.trim();
        const fact = modal.querySelector('#new-edge-fact').value.trim();
        const validAtStr = modal.querySelector('#new-edge-valid-at').value;
        const invalidAtStr = modal.querySelector('#new-edge-invalid-at').value;

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
            fact,
        };
        if (validAtStr) payload.valid_at = new Date(validAtStr).toISOString();
        if (invalidAtStr) payload.invalid_at = new Date(invalidAtStr).toISOString();

        const data = await apiCall('/graphiti/edges', 'POST', payload);
        if (data && data.success) {
            showToast('边创建成功', 'success');
            closeModal();
            loadGraph();
        } else {
            showToast('创建失败: ' + (data?.error || '未知错误'), 'error');
        }
    });
}

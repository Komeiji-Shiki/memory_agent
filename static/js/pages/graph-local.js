/**
 * 本地知识图谱 tab（vis-network）
 * - GET /graph 全量渲染：类型着色、双向边弯曲、悬停提示
 * - 节点：点击详情（链出/链入/观察/Markdown 内容）、双击聚焦、高亮邻居、类型过滤
 * - 编辑：节点内容（PUT /node/<name>）、观察追加、关系 CRUD（/graph/relation）、删除节点
 */

import { apiCall } from '../core/api.js';
import {
    showToast, showModal, closeModal, confirmDialog,
    escapeHtml, escapeAttr, spinnerHtml, errorHtml, bindActions,
} from '../core/ui.js';

const NODE_TYPES = ['人物', '地点', '事物', '概念', '事件'];

let rootEl = null;
let network = null;
let dataSet = { nodes: null, edges: null };
let lastData = null;
let detailContent = '';

export const localGraphTab = {
    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>🗂️ 本地图谱</h3>
                    <div id="graph-stats" class="text-dim" style="display: flex; gap: 10px; flex-wrap: wrap;"></div>
                </div>
                <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px;">
                    <select id="graph-filter-type" class="form-select" style="width: auto;">
                        <option value="all">全部类型</option>
                        ${NODE_TYPES.map((t) => `<option value="${t}">${t}</option>`).join('')}
                    </select>
                    <button class="btn btn-sm" data-action="refresh-local">🔄 刷新</button>
                    <button class="btn btn-sm" data-action="fit-local">🎯 适应视图</button>
                    <span class="text-dim" style="font-size: 0.85rem;">点击节点查看详情，点击边编辑关系，双击聚焦</span>
                </div>
                <div id="graph-container" style="height: 600px; border: 1px solid var(--line-weak); border-radius: 8px;"></div>
            </div>
            <div class="card" id="graph-detail-panel" style="display: none;"></div>
        `;

        bindActions(container, {
            'refresh-local': loadGraphData,
            'fit-local': fitView,
            'close-detail': hideNodeDetail,
            'focus-node': (t) => focusNode(t.dataset.node),
            'edit-node-content': (t) => showEditNodeDialog(t.dataset.id),
            'add-relation': (t) => showAddRelationDialog(t.dataset.id),
            'add-observation': (t) => showAddObservationDialog(t.dataset.id),
            'delete-node': (t) => deleteNodeFromGraph(t.dataset.id),
        });

        container.querySelector('#graph-filter-type').addEventListener('change', (e) => {
            filterByType(e.target.value);
        });
    },

    load() {
        loadGraphData();
    },

    redraw() {
        if (lastData) renderGraph(lastData);
    },
};

async function loadGraphData() {
    const container = rootEl.querySelector('#graph-container');
    const statsEl = rootEl.querySelector('#graph-stats');
    container.innerHTML = spinnerHtml('加载图谱数据...');

    const data = await apiCall('/graph');
    if (!data || data.error) {
        container.innerHTML = errorHtml('加载失败: ' + (data?.error || '未知错误'));
        return;
    }

    if (statsEl && data.stats) {
        const s = data.stats;
        statsEl.innerHTML = `
            <span class="badge">📊 ${s.total_nodes} 节点</span>
            <span class="badge">🔗 ${s.total_edges} 关系</span>
            <span class="badge">👤 ${s.by_type?.人物 || 0}</span>
            <span class="badge">📍 ${s.by_type?.地点 || 0}</span>
            <span class="badge">📦 ${s.by_type?.事物 || 0}</span>
            <span class="badge">💡 ${s.by_type?.概念 || 0}</span>
        `;
    }

    if (!data.nodes || data.nodes.length === 0) {
        container.innerHTML = '<p class="text-dim" style="text-align: center; padding: 40px;">暂无节点数据</p>';
        return;
    }

    renderGraph(data);
}

function renderGraph(data) {
    lastData = data;
    const container = rootEl.querySelector('#graph-container');
    container.innerHTML = '';

    if (network) {
        network.destroy();
        network = null;
    }

    const nodes = new vis.DataSet(data.nodes.map((n) => ({
        id: n.id,
        label: `${n.icon} ${n.name}`,
        title: `${n.type}: ${n.name}\n📝 观察: ${n.observations}条\n🔗 链出: ${n.links_count || 0}\n📥 链入: ${n.backlinks_count || 0}\n🏷️ 标签: ${n.tags?.join(', ') || '无'}`,
        color: {
            background: n.color,
            border: n.color,
            highlight: { background: lightenColor(n.color, 20), border: n.color },
            hover: { background: lightenColor(n.color, 10), border: n.color },
        },
        font: { color: '#ffffff', size: 14, face: 'system-ui, -apple-system, sans-serif' },
        shape: 'box',
        borderWidth: 2,
        shadow: true,
        nodeType: n.type,
    })));

    // 双向边检测：存在反向边时两条边分别向两侧弯曲
    const edgePairs = new Map();
    data.edges.forEach((e) => {
        const key1 = `${e.from}->${e.to}`;
        const key2 = `${e.to}->${e.from}`;
        if (edgePairs.has(key2)) {
            edgePairs.get(key2).hasBidirectional = true;
            e.hasBidirectional = true;
            e.isSecond = true;
        }
        edgePairs.set(key1, e);
    });

    const edges = new vis.DataSet(data.edges.map((e, i) => ({
        id: i,
        from: e.from,
        to: e.to,
        label: e.relation !== '关联' ? e.relation : '',
        arrows: 'to',
        color: { color: '#666666', highlight: '#999999', hover: '#888888' },
        width: 1.5,
        smooth: e.hasBidirectional
            ? { enabled: true, type: e.isSecond ? 'curvedCCW' : 'curvedCW', roundness: 0.2 }
            : { enabled: true, type: 'continuous' },
    })));

    dataSet = { nodes, edges };

    const options = {
        nodes: {
            margin: 10,
            widthConstraint: { minimum: 60, maximum: 150 },
        },
        edges: {
            font: { size: 10, color: '#888888' },
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
            stabilization: { enabled: true, iterations: 100, updateInterval: 25 },
        },
        interaction: {
            hover: true,
            tooltipDelay: 200,
            hideEdgesOnDrag: true,
            navigationButtons: true,
            keyboard: true,
        },
        layout: { improvedLayout: true },
    };

    network = new vis.Network(container, dataSet, options);

    network.on('click', onGraphClick);
    network.on('hoverNode', () => { document.body.style.cursor = 'pointer'; });
    network.on('blurNode', () => { document.body.style.cursor = 'default'; });
    network.on('doubleClick', (params) => {
        if (params.nodes.length > 0) focusById(params.nodes[0]);
    });
    // 稳定后关闭物理引擎，提升性能
    network.on('stabilizationIterationsDone', () => {
        network.setOptions({ physics: { enabled: false } });
    });

    // 过滤器复位
    const filterEl = rootEl.querySelector('#graph-filter-type');
    if (filterEl && filterEl.value !== 'all') filterByType(filterEl.value);
}

async function onGraphClick(params) {
    if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        highlightNeighbors(nodeId);
        await showGraphNodeDetail(nodeId);
        return;
    }
    if (params.edges.length > 0) {
        const edge = dataSet.edges.get(params.edges[0]);
        if (edge) showEdgeActions(edge);
        return;
    }
    hideNodeDetail();
    resetHighlight();
}

// ===== 高亮 =====

function highlightNeighbors(nodeId) {
    if (!dataSet.nodes || !dataSet.edges) return;
    const connected = network.getConnectedNodes(nodeId);
    dataSet.nodes.update(dataSet.nodes.getIds().map((id) => ({
        id,
        opacity: id === nodeId || connected.includes(id) ? 1 : 0.3,
    })));
    const edgeUpdates = [];
    dataSet.edges.forEach((edge) => {
        edgeUpdates.push({
            id: edge.id,
            color: { opacity: edge.from === nodeId || edge.to === nodeId ? 1 : 0.2 },
        });
    });
    dataSet.edges.update(edgeUpdates);
}

function resetHighlight() {
    if (!dataSet.nodes || !dataSet.edges) return;
    dataSet.nodes.update(dataSet.nodes.getIds().map((id) => ({ id, opacity: 1 })));
    const edgeUpdates = [];
    dataSet.edges.forEach((edge) => {
        edgeUpdates.push({ id: edge.id, color: { opacity: 1 } });
    });
    dataSet.edges.update(edgeUpdates);
}

// ===== 节点详情面板 =====

async function showGraphNodeDetail(nodeId) {
    const panel = rootEl.querySelector('#graph-detail-panel');
    panel.innerHTML = spinnerHtml();
    panel.style.display = 'block';

    const data = await apiCall(`/graph/node/${encodeURIComponent(nodeId)}`);
    if (!data || data.error) {
        panel.innerHTML = errorHtml(data?.error || '加载失败');
        return;
    }

    const tagsHtml = data.tags?.length
        ? data.tags.map((t) => `<span class="badge badge-info">#${escapeHtml(t)}</span>`).join(' ')
        : '<span class="text-dim">无</span>';

    const linksHtml = data.links?.length
        ? data.links.map((l) => `<a href="#" class="graph-link" data-action="focus-node" data-node="${escapeAttr(l)}">→ ${escapeHtml(l)}</a>`).join(' ')
        : '<span class="text-dim">无</span>';

    const backlinksHtml = data.backlinks?.length
        ? data.backlinks.map((bl) => `<a href="#" class="graph-link graph-backlink" data-action="focus-node" data-node="${escapeAttr(bl.name)}" title="${escapeAttr(bl.relation)}"><span style="color: ${escapeHtml(bl.color)}">${escapeHtml(bl.icon)}</span> ${escapeHtml(bl.name)} <span class="backlink-relation">(${escapeHtml(bl.relation)})</span></a>`).join(' ')
        : '<span class="text-dim">无</span>';

    const obsHtml = data.observations?.length
        ? `<ul style="margin: 0; padding-left: 20px;">${data.observations.map((o) => `<li>${escapeHtml(o)}</li>`).join('')}</ul>`
        : '<span class="text-dim">无观察记录</span>';

    detailContent = data.content || '';
    const contentHtml = renderSimpleMarkdown(data.content || '无内容');
    const idAttr = escapeAttr(nodeId);

    panel.innerHTML = `
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 15px;">
            <span style="font-size: 1.4rem; color: ${escapeHtml(data.color)}">${escapeHtml(data.icon)}</span>
            <h3 style="margin: 0;">${escapeHtml(data.name)}</h3>
            <span class="badge" style="background: ${escapeHtml(data.color)}; color: #fff;">${escapeHtml(data.type)}</span>
            <button class="btn btn-sm" data-action="close-detail" style="margin-left: auto;">✕</button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px;">
            <div><strong>🏷️ 标签</strong><div style="margin-top: 6px;">${tagsHtml}</div></div>
            <div><strong>🔗 链出 (${data.links?.length || 0})</strong><div style="margin-top: 6px;">${linksHtml}</div></div>
            <div><strong>📥 链入 (${data.backlinks?.length || 0})</strong><div style="margin-top: 6px;">${backlinksHtml}</div></div>
            <div><strong>👁️ 观察 (${data.observations?.length || 0})</strong><div style="margin-top: 6px;">${obsHtml}</div></div>
        </div>
        <div style="margin-top: 15px;">
            <strong>📝 完整内容</strong>
            <div style="margin-top: 8px; padding: 12px; background: var(--surface-2); border-radius: 8px; max-height: 300px; overflow-y: auto; font-size: 0.9rem; line-height: 1.6;">${contentHtml}</div>
        </div>
        <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid var(--line-weak); display: flex; gap: 10px; flex-wrap: wrap;">
            <button class="btn btn-sm btn-primary" data-action="edit-node-content" data-id="${idAttr}">✏️ 编辑内容</button>
            <button class="btn btn-sm btn-success" data-action="add-relation" data-id="${idAttr}">➕ 添加关系</button>
            <button class="btn btn-sm" data-action="add-observation" data-id="${idAttr}">👁️ 添加观察</button>
            <button class="btn btn-sm btn-danger" data-action="delete-node" data-id="${idAttr}">🗑️ 删除</button>
        </div>
    `;
}

function hideNodeDetail() {
    const panel = rootEl.querySelector('#graph-detail-panel');
    if (panel) panel.style.display = 'none';
    resetHighlight();
}

/** 简单 Markdown 渲染（标题/双链/列表/粗斜体/行内代码） */
function renderSimpleMarkdown(text) {
    if (!text) return '';
    let html = escapeHtml(text);
    html = html.replace(/^### (.+)$/gm, '<h4 style="color: var(--accent); margin: 15px 0 8px;">$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3 style="color: var(--accent); margin: 15px 0 8px;">$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2 style="color: var(--accent); margin: 15px 0 8px;">$1</h2>');
    html = html.replace(/\[\[([^\]]+)\]\]/g, '<a href="#" class="graph-link" data-action="focus-node" data-node="$1">$1</a>');
    html = html.replace(/^- (.+)$/gm, '<li style="margin-left: 20px;">$1</li>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/`([^`]+)`/g, '<code style="background: var(--surface-2); padding: 2px 6px; border-radius: 3px;">$1</code>');
    html = html.replace(/\n/g, '<br>');
    return html;
}

// ===== 视图操作 =====

function focusById(nodeId) {
    network.focus(nodeId, {
        scale: 1.5,
        animation: { duration: 500, easingFunction: 'easeInOutQuad' },
    });
}

function focusNode(nodeName) {
    if (!network || !dataSet.nodes) return;
    let targetId = null;
    dataSet.nodes.forEach((node) => {
        if (node.label?.includes(nodeName) || String(node.id).includes(nodeName)) {
            targetId = node.id;
        }
    });
    if (targetId) {
        focusById(targetId);
        network.selectNodes([targetId]);
        showGraphNodeDetail(targetId);
    } else {
        showToast(`未在图谱中找到节点: ${nodeName}`, 'warning');
    }
}

function filterByType(type) {
    if (!dataSet.nodes) return;
    if (type === 'all') {
        dataSet.nodes.update(dataSet.nodes.getIds().map((id) => ({ id, hidden: false })));
    } else {
        const updates = [];
        dataSet.nodes.forEach((node) => {
            updates.push({ id: node.id, hidden: node.nodeType !== type });
        });
        dataSet.nodes.update(updates);
    }
}

function fitView() {
    if (network) {
        network.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
    }
}

// ===== 边操作 =====

function showEdgeActions(edge) {
    const fromNode = dataSet.nodes.get(edge.from);
    const toNode = dataSet.nodes.get(edge.to);
    const fromLabel = fromNode ? fromNode.label : edge.from;
    const toLabel = toNode ? toNode.label : edge.to;
    const currentRelation = edge.label || '关联';

    const modal = showModal('🔗 边操作', `
        <div style="margin-bottom: 15px;">
            <strong>关系：</strong>${escapeHtml(fromLabel)} <span style="color: var(--accent);">--${escapeHtml(currentRelation)}--&gt;</span> ${escapeHtml(toLabel)}
        </div>
        <div class="form-group">
            <label>修改关系类型</label>
            <input type="text" id="edit-relation-type" value="${escapeAttr(currentRelation)}" placeholder="开发、创建、使用、属于...">
            <small class="text-dim">常用：开发、创建、使用、属于、包含、朋友、同事、喜欢、服务</small>
        </div>
    `, {
        footer: `
            <button class="btn btn-danger" data-act="del">🗑️ 删除此关系</button>
            <button class="btn" data-modal-close>取消</button>
            <button class="btn btn-success" data-act="save">✓ 保存</button>
        `,
    });

    modal.querySelector('[data-act="save"]').addEventListener('click', () => {
        updateRelation(edge.from, edge.to, currentRelation, modal);
    });
    modal.querySelector('[data-act="del"]').addEventListener('click', async () => {
        closeModal();
        await deleteRelation(edge.from, edge.to, currentRelation);
    });
}

async function updateRelation(fromNodeId, toNodeId, oldRelation, modal) {
    const newRelation = modal.querySelector('#edit-relation-type').value.trim();
    if (!newRelation) {
        showToast('请输入关系类型', 'error');
        return;
    }
    if (newRelation === oldRelation) {
        showToast('关系类型未改变', 'info');
        return;
    }

    const data = await apiCall('/graph/relation', 'PUT', {
        from_node: fromNodeId,
        to_node: toNodeId,
        old_relation: oldRelation,
        new_relation: newRelation,
    });
    if (data && data.success) {
        showToast(`关系已修改: ${oldRelation} → ${newRelation}`, 'success');
        closeModal();
        loadGraphData();
    } else {
        showToast('修改失败: ' + (data?.error || '未知错误'), 'error');
    }
}

async function deleteRelation(fromNodeId, toNodeId, relationType) {
    const ok = await confirmDialog(`确定要删除关系 "${fromNodeId} --${relationType}--> ${toNodeId}" 吗？`, { danger: true, okText: '删除' });
    if (!ok) return;

    const data = await apiCall('/graph/relation', 'DELETE', {
        from_node: fromNodeId,
        to_node: toNodeId,
        relation_type: relationType,
    });
    if (data && data.success) {
        showToast('关系删除成功', 'success');
        loadGraphData();
    } else {
        showToast('删除失败: ' + (data?.error || '未知错误'), 'error');
    }
}

function showAddRelationDialog(fromNodeId) {
    const allNodes = dataSet.nodes ? dataSet.nodes.get() : [];
    const optionsHtml = allNodes
        .filter((n) => n.id !== fromNodeId)
        .map((n) => `<option value="${escapeAttr(n.id)}">${escapeHtml(n.label)}</option>`)
        .join('');

    const modal = showModal('➕ 添加关系', `
        <div class="form-group">
            <label>源节点</label>
            <input type="text" value="${escapeAttr(fromNodeId)}" disabled>
        </div>
        <div class="form-group">
            <label>目标节点</label>
            <select id="relation-to-node">${optionsHtml}</select>
        </div>
        <div class="form-group">
            <label>关系类型</label>
            <input type="text" id="relation-type" placeholder="开发、创建、属于、使用...">
            <small class="text-dim">常用：开发、创建、使用、属于、包含、朋友、同事</small>
        </div>
    `, {
        footer: `
            <button class="btn" data-modal-close>取消</button>
            <button class="btn btn-success" data-act="create">✨ 创建</button>
        `,
    });

    modal.querySelector('[data-act="create"]').addEventListener('click', async () => {
        const toNodeId = modal.querySelector('#relation-to-node').value;
        const relationType = modal.querySelector('#relation-type').value.trim() || '关联';
        if (!toNodeId) {
            showToast('请选择目标节点', 'error');
            return;
        }
        const data = await apiCall('/graph/relation', 'POST', {
            from_node: fromNodeId,
            to_node: toNodeId,
            relation_type: relationType,
        });
        if (data && data.success) {
            showToast('关系创建成功', 'success');
            closeModal();
            loadGraphData();
        } else {
            showToast('创建失败: ' + (data?.error || '未知错误'), 'error');
        }
    });
}

// ===== 节点内容编辑 =====

/** 从节点 ID 解析节点名（去掉类型前缀） */
function parseNodeName(nodeId) {
    for (const t of NODE_TYPES) {
        if (nodeId.startsWith(`${t}-`)) return nodeId.substring(t.length + 1);
    }
    return nodeId;
}

function showEditNodeDialog(nodeId) {
    const modal = showModal('✏️ 编辑节点内容', `
        <div class="form-group">
            <label>节点ID</label>
            <input type="text" value="${escapeAttr(nodeId)}" disabled>
        </div>
        <div class="form-group">
            <label>内容 (Markdown)</label>
            <textarea id="edit-node-content" style="min-height: 300px; font-family: monospace;">${escapeHtml(detailContent)}</textarea>
            <small class="text-dim">支持 Markdown 语法和 [[双链]] 格式</small>
        </div>
    `, {
        size: 'large',
        footer: `
            <button class="btn" data-modal-close>取消</button>
            <button class="btn btn-success" data-act="save">💾 保存</button>
        `,
    });

    modal.querySelector('[data-act="save"]').addEventListener('click', async () => {
        const content = modal.querySelector('#edit-node-content').value;
        const nodeName = parseNodeName(nodeId);
        const data = await apiCall(`/node/${encodeURIComponent(nodeName)}`, 'PUT', {
            content,
            mode: 'replace',
        });
        if (data && (data.success || !data.error)) {
            showToast('节点保存成功', 'success');
            closeModal();
            await showGraphNodeDetail(nodeId);
        } else {
            showToast('保存失败: ' + (data?.error || '未知错误'), 'error');
        }
    });
}

function showAddObservationDialog(nodeId) {
    const modal = showModal('👁️ 添加观察', `
        <div class="form-group">
            <label>节点</label>
            <input type="text" value="${escapeAttr(nodeId)}" disabled>
        </div>
        <div class="form-group">
            <label>观察内容（每行一条）</label>
            <textarea id="add-observation-content" style="min-height: 150px;" placeholder="例如：&#10;喜欢吃草莓蛋糕&#10;经常熬夜写代码"></textarea>
            <small class="text-dim">观察是关于节点的离散事实，每行会成为一个列表项</small>
        </div>
    `, {
        footer: `
            <button class="btn" data-modal-close>取消</button>
            <button class="btn btn-success" data-act="add">✨ 添加</button>
        `,
    });

    modal.querySelector('[data-act="add"]').addEventListener('click', async () => {
        const content = modal.querySelector('#add-observation-content').value.trim();
        if (!content) {
            showToast('请输入观察内容', 'error');
            return;
        }
        const nodeName = parseNodeName(nodeId);
        const lines = content.split('\n').filter((l) => l.trim());
        const obsContent = '\n\n## 观察记录\n\n' + lines.map((l) => `- ${l.trim()}`).join('\n');

        const data = await apiCall(`/node/${encodeURIComponent(nodeName)}`, 'PUT', {
            content: obsContent,
            mode: 'append',
        });
        if (data && (data.success || !data.error)) {
            showToast(`已添加 ${lines.length} 条观察`, 'success');
            closeModal();
            await showGraphNodeDetail(nodeId);
        } else {
            showToast('添加失败: ' + (data?.error || '未知错误'), 'error');
        }
    });
}

async function deleteNodeFromGraph(nodeId) {
    const ok = await confirmDialog(`确定要删除节点 "${nodeId}" 吗？\n\n⚠️ 这将同时删除所有相关的关系引用！`, { danger: true, okText: '删除' });
    if (!ok) return;

    const data = await apiCall(`/graph/node/${encodeURIComponent(nodeId)}`, 'DELETE');
    if (data && data.success) {
        showToast('节点删除成功', 'success');
        hideNodeDetail();
        loadGraphData();
    } else {
        showToast('删除失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 工具 =====

/** 颜色变亮（用于节点 hover/highlight） */
function lightenColor(color, percent) {
    const num = parseInt(color.replace('#', ''), 16);
    const amt = Math.round(2.55 * percent);
    const R = (num >> 16) + amt;
    const G = (num >> 8 & 0x00FF) + amt;
    const B = (num & 0x0000FF) + amt;
    return '#' + (
        0x1000000 +
        (R < 255 ? (R < 1 ? 0 : R) : 255) * 0x10000 +
        (G < 255 ? (G < 1 ? 0 : G) : 255) * 0x100 +
        (B < 255 ? (B < 1 ? 0 : B) : 255)
    ).toString(16).slice(1);
}

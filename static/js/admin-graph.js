/**
 * Admin Graph - 知识图谱可视化
 * 使用 vis-network 库实现交互式图谱展示
 */

// ===== 全局变量 =====
let graphNetwork = null;
let graphData = { nodes: null, edges: null };
let selectedNodeId = null;

// ===== 初始化图谱 =====
async function initGraph() {
    const container = document.getElementById('graph-container');
    if (!container) return;
    
    // 销毁之前的网络实例，防止内存泄漏
    destroyGraph();
    
    // 加载图谱数据
    await loadGraphData();
}

// ===== 销毁图谱实例（防止内存泄漏）=====
function destroyGraph() {
    if (graphNetwork) {
        graphNetwork.destroy();
        graphNetwork = null;
    }
    graphData = { nodes: null, edges: null };
    selectedNodeId = null;
}

// ===== 加载图谱数据 =====
async function loadGraphData() {
    const container = document.getElementById('graph-container');
    const statsContainer = document.getElementById('graph-stats');
    
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载图谱数据...</div>';
    
    try {
        const data = await apiCall('/graph');
        
        if (data.error) {
            container.innerHTML = `<p style="color: var(--danger);">加载失败: ${data.error}</p>`;
            return;
        }
        
        // 更新统计
        if (statsContainer && data.stats) {
            const stats = data.stats;
            statsContainer.innerHTML = `
                <span class="stat-item">📊 ${stats.total_nodes} 节点</span>
                <span class="stat-item">🔗 ${stats.total_edges} 关系</span>
                <span class="stat-item">👤 ${stats.by_type?.人物 || 0}</span>
                <span class="stat-item">📍 ${stats.by_type?.地点 || 0}</span>
                <span class="stat-item">📦 ${stats.by_type?.事物 || 0}</span>
                <span class="stat-item">💡 ${stats.by_type?.概念 || 0}</span>
            `;
        }
        
        if (!data.nodes || data.nodes.length === 0) {
            container.innerHTML = '<p style="color: var(--text-dim); text-align: center; padding: 40px;">暂无节点数据</p>';
            return;
        }
        
        // 渲染图谱
        renderGraph(container, data);
        
    } catch (e) {
        container.innerHTML = `<p style="color: var(--danger);">加载出错: ${e.message}</p>`;
    }
}

// ===== 渲染图谱 =====
function renderGraph(container, data) {
    // 清空容器
    container.innerHTML = '';
    
    // 转换节点数据为 vis-network 格式
    const nodes = new vis.DataSet(data.nodes.map(n => ({
        id: n.id,
        label: `${n.icon} ${n.name}`,
        title: `${n.type}: ${n.name}\n📝 观察: ${n.observations}条\n🔗 链出: ${n.links_count || 0}\n📥 链入: ${n.backlinks_count || 0}\n🏷️ 标签: ${n.tags?.join(', ') || '无'}`,
        color: {
            background: n.color,
            border: n.color,
            highlight: {
                background: lightenColor(n.color, 20),
                border: n.color
            },
            hover: {
                background: lightenColor(n.color, 10),
                border: n.color
            }
        },
        font: {
            color: '#ffffff',
            size: 14,
            face: 'system-ui, -apple-system, sans-serif'
        },
        shape: 'box',
        borderWidth: 2,
        shadow: true,
        // 自定义数据
        nodeType: n.type,
        observations: n.observations,
        tags: n.tags,
        linksCount: n.links_count || 0,
        backlinksCount: n.backlinks_count || 0
    })));
    
    // 转换边数据 - 处理双向边分开显示
    const edgePairs = new Map(); // 用于检测双向边
    data.edges.forEach(e => {
        const key1 = `${e.from}->${e.to}`;
        const key2 = `${e.to}->${e.from}`;
        if (edgePairs.has(key2)) {
            // 存在反向边，标记两条边都需要弯曲
            edgePairs.get(key2).hasBidirectional = true;
            e.hasBidirectional = true;
            e.isSecond = true;
        }
        edgePairs.set(key1, e);
    });
    
    const edges = new vis.DataSet(data.edges.map((e, i) => {
        // 双向边使用弯曲显示，单向边使用直线
        let smoothConfig;
        if (e.hasBidirectional) {
            smoothConfig = {
                enabled: true,
                type: e.isSecond ? 'curvedCCW' : 'curvedCW',  // 双向边分别向两边弯曲
                roundness: 0.2
            };
        } else {
            smoothConfig = {
                enabled: true,
                type: 'continuous'
            };
        }
        
        return {
            id: i,
            from: e.from,
            to: e.to,
            label: e.relation !== '关联' ? e.relation : '',
            arrows: 'to',
            color: {
                color: '#666666',
                highlight: '#999999',
                hover: '#888888'
            },
            width: 1.5,
            smooth: smoothConfig
        };
    }));
    
    graphData = { nodes, edges };
    
    // 配置选项
    const options = {
        nodes: {
            margin: 10,
            widthConstraint: {
                minimum: 60,
                maximum: 150
            }
        },
        edges: {
            font: {
                size: 10,
                color: '#888888'
            }
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
            stabilization: {
                enabled: true,
                iterations: 100,
                updateInterval: 25
            }
        },
        interaction: {
            hover: true,
            tooltipDelay: 200,
            hideEdgesOnDrag: true,
            navigationButtons: true,
            keyboard: true
        },
        layout: {
            improvedLayout: true
        }
    };
    
    // 创建网络图
    graphNetwork = new vis.Network(container, graphData, options);
    
    // 绑定事件
    graphNetwork.on('click', onGraphClick);
    graphNetwork.on('hoverNode', onNodeHover);
    graphNetwork.on('blurNode', onNodeBlur);
    graphNetwork.on('doubleClick', onNodeDoubleClick);
    
    // 稳定后禁用物理引擎（提升性能）
    graphNetwork.on('stabilizationIterationsDone', function() {
        graphNetwork.setOptions({ physics: { enabled: false } });
    });
}

// ===== 图谱点击事件（节点或边） =====
async function onGraphClick(params) {
    // 点击节点
    if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        selectedNodeId = nodeId;
        
        // 高亮相邻节点
        highlightNeighbors(nodeId);
        
        // 显示节点详情
        await showGraphNodeDetail(nodeId);
        return;
    }
    
    // 点击边
    if (params.edges.length > 0) {
        const edgeId = params.edges[0];
        const edge = graphData.edges.get(edgeId);
        
        if (edge) {
            showEdgeActions(edge);
        }
        return;
    }
    
    // 点击空白区域
    hideNodeDetail();
    resetHighlight();
}

// ===== 显示边操作菜单 =====
function showEdgeActions(edge) {
    const fromNode = graphData.nodes.get(edge.from);
    const toNode = graphData.nodes.get(edge.to);
    
    const fromLabel = fromNode ? fromNode.label : edge.from;
    const toLabel = toNode ? toNode.label : edge.to;
    const currentRelation = edge.label || '关联';
    
    showModal('边操作', `
        <div style="margin-bottom: 15px;">
            <strong>关系：</strong>${escapeHtml(fromLabel)} <span style="color: var(--accent);">--${escapeHtml(currentRelation)}--></span> ${escapeHtml(toLabel)}
        </div>
        
        <div class="form-group" style="margin-bottom: 20px;">
            <label class="form-label">修改关系类型</label>
            <div style="display: flex; gap: 10px;">
                <input type="text" id="edit-relation-type" class="form-input" value="${escapeAttrValue(currentRelation)}" placeholder="开发、创建、使用、属于..." style="flex: 1;">
                <button class="btn btn-success" onclick="updateRelation('${escapeAttr(edge.from)}', '${escapeAttr(edge.to)}', '${escapeAttr(currentRelation)}')">✓ 保存</button>
            </div>
            <div class="form-hint">常用：开发、创建、使用、属于、包含、朋友、同事、喜欢、服务</div>
        </div>
        
        <div style="display: flex; gap: 10px; padding-top: 15px; border-top: 1px solid var(--line-weak);">
            <button class="btn btn-danger" onclick="deleteRelation('${escapeAttr(edge.from)}', '${escapeAttr(edge.to)}', '${escapeAttr(currentRelation)}'); closeModal();">🗑️ 删除此关系</button>
            <button class="btn" onclick="closeModal()" style="margin-left: auto;">取消</button>
        </div>
    `);
}

// ===== 更新关系 =====
async function updateRelation(fromNodeId, toNodeId, oldRelation) {
    const newRelation = document.getElementById('edit-relation-type').value.trim();
    
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
        new_relation: newRelation
    });
    
    if (data && data.success) {
        showToast(`关系已修改: ${oldRelation} → ${newRelation}`, 'success');
        closeModal();
        refreshGraph();
    } else {
        showToast('修改失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 节点悬停事件 =====
function onNodeHover(params) {
    document.body.style.cursor = 'pointer';
}

function onNodeBlur(params) {
    document.body.style.cursor = 'default';
}

// ===== 节点双击事件（聚焦） =====
function onNodeDoubleClick(params) {
    if (params.nodes.length > 0) {
        graphNetwork.focus(params.nodes[0], {
            scale: 1.5,
            animation: {
                duration: 500,
                easingFunction: 'easeInOutQuad'
            }
        });
    }
}

// ===== 高亮相邻节点 =====
function highlightNeighbors(nodeId) {
    if (!graphData.nodes || !graphData.edges) return;
    
    // 获取相邻节点
    const connectedNodes = graphNetwork.getConnectedNodes(nodeId);
    const allNodeIds = graphData.nodes.getIds();
    
    // 更新节点透明度
    const updates = [];
    allNodeIds.forEach(id => {
        if (id === nodeId || connectedNodes.includes(id)) {
            updates.push({ id, opacity: 1 });
        } else {
            updates.push({ id, opacity: 0.3 });
        }
    });
    
    graphData.nodes.update(updates);
    
    // 更新边透明度
    const edgeUpdates = [];
    graphData.edges.forEach(edge => {
        if (edge.from === nodeId || edge.to === nodeId) {
            edgeUpdates.push({ id: edge.id, color: { opacity: 1 } });
        } else {
            edgeUpdates.push({ id: edge.id, color: { opacity: 0.2 } });
        }
    });
    graphData.edges.update(edgeUpdates);
}

// ===== 重置高亮 =====
function resetHighlight() {
    if (!graphData.nodes || !graphData.edges) return;
    
    // 重置节点
    const nodeUpdates = graphData.nodes.getIds().map(id => ({ id, opacity: 1 }));
    graphData.nodes.update(nodeUpdates);
    
    // 重置边
    const edgeUpdates = [];
    graphData.edges.forEach(edge => {
        edgeUpdates.push({ id: edge.id, color: { opacity: 1 } });
    });
    graphData.edges.update(edgeUpdates);
}

// ===== 显示节点详情 =====
async function showGraphNodeDetail(nodeId) {
    const panel = document.getElementById('graph-detail-panel');
    if (!panel) return;
    
    panel.innerHTML = '<div class="loading"><span class="spinner"></span></div>';
    panel.style.display = 'block';
    
    try {
        const data = await apiCall(`/graph/node/${encodeURIComponent(nodeId)}`);
        
        if (data.error) {
            panel.innerHTML = `<p style="color: var(--danger);">${data.error}</p>`;
            return;
        }
        
        const tagsHtml = data.tags?.length
            ? data.tags.map(t => `<span class="badge badge-info">#${escapeHtml(t)}</span>`).join(' ')
            : '<span style="color: var(--text-dim);">无</span>';
        
        // 正向链接（链出）
        const linksHtml = data.links?.length
            ? data.links.map(l => `<a href="#" class="graph-link" onclick="focusNode('${escapeAttr(l)}'); return false;">→ ${escapeHtml(l)}</a>`).join(' ')
            : '<span style="color: var(--text-dim);">无</span>';
        
        // 反向链接（链入）
        const backlinksHtml = data.backlinks?.length
            ? data.backlinks.map(bl => `<a href="#" class="graph-link graph-backlink" onclick="focusNode('${escapeAttr(bl.name)}'); return false;" title="${escapeAttrValue(bl.relation)}"><span style="color: ${escapeHtml(bl.color)}">${escapeHtml(bl.icon)}</span> ${escapeHtml(bl.name)} <span class="backlink-relation">(${escapeHtml(bl.relation)})</span></a>`).join(' ')
            : '<span style="color: var(--text-dim);">无</span>';
        
        const obsHtml = data.observations?.length
            ? `<ul style="margin: 0; padding-left: 20px;">${data.observations.map(o => `<li>${escapeHtml(o)}</li>`).join('')}</ul>`
            : '<span style="color: var(--text-dim);">无观察记录</span>';
        
        // 简单的 Markdown 渲染
        const contentHtml = renderSimpleMarkdown(data.content || '无内容');
        
        // 安全地将 content 传递给编辑函数 - 使用全局变量存储
        window._editNodeContent = data.content || '';
        
        panel.innerHTML = `
            <div class="graph-detail-header">
                <span class="graph-detail-icon" style="color: ${escapeHtml(data.color)}">${escapeHtml(data.icon)}</span>
                <h4>${escapeHtml(data.name)}</h4>
                <span class="badge" style="background: ${escapeHtml(data.color)}">${escapeHtml(data.type)}</span>
                <button class="btn btn-sm" onclick="hideNodeDetail()" style="margin-left: auto;">✕</button>
            </div>
            <div class="graph-detail-body">
                <div class="detail-section">
                    <strong>🏷️ 标签</strong>
                    <div>${tagsHtml}</div>
                </div>
                <div class="detail-section">
                    <strong>🔗 链出 (${data.links?.length || 0})</strong>
                    <div>${linksHtml}</div>
                </div>
                <div class="detail-section">
                    <strong>📥 链入 (${data.backlinks?.length || 0})</strong>
                    <div>${backlinksHtml}</div>
                </div>
                <div class="detail-section">
                    <strong>👁️ 观察 (${data.observations?.length || 0})</strong>
                    <div>${obsHtml}</div>
                </div>
                <div class="detail-section detail-section-full">
                    <strong>📝 完整内容</strong>
                    <div class="content-preview content-markdown">${contentHtml}</div>
                </div>
            </div>
            <div class="graph-detail-actions" style="margin-top: 15px; padding-top: 15px; border-top: 1px solid var(--line-weak); display: flex; gap: 10px; flex-wrap: wrap;">
                <button class="btn btn-sm btn-primary" onclick="showEditNodeDialog('${escapeAttr(nodeId)}')">✏️ 编辑内容</button>
                <button class="btn btn-sm btn-success" onclick="showAddRelationDialog('${escapeAttr(nodeId)}')">➕ 添加关系</button>
                <button class="btn btn-sm" onclick="showAddObservationDialog('${escapeAttr(nodeId)}')">👁️ 添加观察</button>
                <button class="btn btn-sm btn-danger" onclick="deleteNodeFromGraph('${escapeAttr(nodeId)}')">🗑️ 删除</button>
            </div>
        `;
        
    } catch (e) {
        panel.innerHTML = `<p style="color: var(--danger);">加载失败: ${e.message}</p>`;
    }
}

// ===== 简单 Markdown 渲染 =====
function renderSimpleMarkdown(text) {
    if (!text) return '';
    
    let html = escapeHtml(text);
    
    // 标题
    html = html.replace(/^### (.+)$/gm, '<h4 style="color: var(--accent); margin: 15px 0 8px;">$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3 style="color: var(--accent); margin: 15px 0 8px;">$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2 style="color: var(--accent); margin: 15px 0 8px;">$1</h2>');
    
    // 双链 [[xxx]]
    html = html.replace(/\[\[([^\]]+)\]\]/g, '<a href="#" class="graph-link" onclick="focusNode(\'$1\'); return false;">$1</a>');
    
    // 列表项
    html = html.replace(/^- (.+)$/gm, '<li style="margin-left: 20px;">$1</li>');
    
    // 粗体
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    
    // 斜体
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    
    // 代码
    html = html.replace(/`([^`]+)`/g, '<code style="background: var(--surface-2); padding: 2px 6px; border-radius: 3px;">$1</code>');
    
    // 换行
    html = html.replace(/\n/g, '<br>');
    
    return html;
}

// ===== 隐藏节点详情 =====
function hideNodeDetail() {
    const panel = document.getElementById('graph-detail-panel');
    if (panel) {
        panel.style.display = 'none';
    }
    selectedNodeId = null;
    resetHighlight();
}

// ===== 聚焦到节点 =====
function focusNode(nodeName) {
    if (!graphNetwork) return;
    
    // 查找节点ID
    let targetId = null;
    graphData.nodes.forEach(node => {
        if (node.label?.includes(nodeName) || node.id?.includes(nodeName)) {
            targetId = node.id;
        }
    });
    
    if (targetId) {
        graphNetwork.focus(targetId, {
            scale: 1.5,
            animation: {
                duration: 500,
                easingFunction: 'easeInOutQuad'
            }
        });
        graphNetwork.selectNodes([targetId]);
        showGraphNodeDetail(targetId);
    }
}

// ===== 按类型过滤 =====
function filterByType(type) {
    if (!graphData.nodes) return;
    
    if (type === 'all') {
        // 显示所有节点
        const updates = graphData.nodes.getIds().map(id => ({ id, hidden: false }));
        graphData.nodes.update(updates);
    } else {
        // 只显示指定类型
        const updates = [];
        graphData.nodes.forEach(node => {
            updates.push({
                id: node.id,
                hidden: node.nodeType !== type
            });
        });
        graphData.nodes.update(updates);
    }
}

// ===== 适应视图 =====
function fitGraphView() {
    if (graphNetwork) {
        graphNetwork.fit({
            animation: {
                duration: 500,
                easingFunction: 'easeInOutQuad'
            }
        });
    }
}

// ===== 刷新图谱 =====
function refreshGraph() {
    loadGraphData();
}

// ===== 工具函数：颜色变亮 =====
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


// ==================== 编辑功能 ====================

// ===== 显示编辑节点对话框 =====
function showEditNodeDialog(nodeId) {
    // 从全局变量获取内容（在 showNodeDetail 中设置）
    const content = window._editNodeContent || '';
    
    showModal('编辑节点内容', `
        <div class="form-group">
            <label class="form-label">节点ID</label>
            <input type="text" class="form-input" value="${escapeAttrValue(nodeId)}" disabled>
        </div>
        <div class="form-group">
            <label class="form-label">内容 (Markdown)</label>
            <textarea id="edit-node-content" class="form-input" style="min-height: 300px; font-family: monospace;">${escapeHtml(content)}</textarea>
            <div class="form-hint">支持 Markdown 语法和 [[双链]] 格式</div>
        </div>
        <div style="margin-top: 15px; text-align: right;">
            <button class="btn" onclick="closeModal()">取消</button>
            <button class="btn btn-success" onclick="saveNodeContent('${escapeAttr(nodeId)}')" style="margin-left: 10px;">💾 保存</button>
        </div>
    `);
}

// ===== 保存节点内容 =====
async function saveNodeContent(nodeId) {
    const content = document.getElementById('edit-node-content').value;
    
    // 解析节点名称
    let nodeName = nodeId;
    for (const t of ["人物", "地点", "事物", "概念", "事件"]) {
        if (nodeId.startsWith(`${t}-`)) {
            nodeName = nodeId.substring(t.length + 1);
            break;
        }
    }
    
    const data = await apiCall(`/node/${encodeURIComponent(nodeName)}`, 'PUT', {
        content: content,
        mode: 'replace'
    });
    
    if (data && (data.success || !data.error)) {
        showToast('节点保存成功', 'success');
        closeModal();
        // 刷新详情
        await showNodeDetail(nodeId);
    } else {
        showToast('保存失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 显示添加观察对话框 =====
function showAddObservationDialog(nodeId) {
    showModal('添加观察', `
        <div class="form-group">
            <label class="form-label">节点</label>
            <input type="text" class="form-input" value="${escapeAttrValue(nodeId)}" disabled>
        </div>
        <div class="form-group">
            <label class="form-label">观察内容（每行一条）</label>
            <textarea id="add-observation-content" class="form-input" style="min-height: 150px;" placeholder="例如：&#10;喜欢吃草莓蛋糕&#10;经常熬夜写代码"></textarea>
            <div class="form-hint">观察是关于节点的离散事实，每行会成为一个列表项</div>
        </div>
        <div style="margin-top: 15px; text-align: right;">
            <button class="btn" onclick="closeModal()">取消</button>
            <button class="btn btn-success" onclick="addObservations('${escapeAttr(nodeId)}')" style="margin-left: 10px;">✨ 添加</button>
        </div>
    `);
}

// ===== 添加观察 =====
async function addObservations(nodeId) {
    const content = document.getElementById('add-observation-content').value.trim();
    if (!content) {
        showToast('请输入观察内容', 'error');
        return;
    }
    
    // 解析节点名称
    let nodeName = nodeId;
    for (const t of ["人物", "地点", "事物", "概念", "事件"]) {
        if (nodeId.startsWith(`${t}-`)) {
            nodeName = nodeId.substring(t.length + 1);
            break;
        }
    }
    
    // 将每行转换为列表项格式
    const lines = content.split('\n').filter(l => l.trim());
    const obsContent = '\n\n## 观察记录\n\n' + lines.map(l => `- ${l.trim()}`).join('\n');
    
    const data = await apiCall(`/node/${encodeURIComponent(nodeName)}`, 'PUT', {
        content: obsContent,
        mode: 'append'
    });
    
    if (data && (data.success || !data.error)) {
        showToast(`已添加 ${lines.length} 条观察`, 'success');
        closeModal();
        refreshGraph();
        await showNodeDetail(nodeId);
    } else {
        showToast('添加失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 从图谱编辑节点（兼容旧版） =====
function editNodeFromGraph(nodeName) {
    // 调用 admin-memory.js 中的编辑函数
    if (typeof editNode === 'function') {
        editNode(nodeName);
    } else {
        showToast('编辑功能不可用', 'error');
    }
}

// ===== 从图谱删除节点 =====
async function deleteNodeFromGraph(nodeId) {
    if (!confirm(`确定要删除节点 "${nodeId}" 吗？\n\n⚠️ 这将同时删除所有相关的关系引用！`)) {
        return;
    }
    
    const data = await apiCall(`/graph/node/${encodeURIComponent(nodeId)}`, 'DELETE');
    
    if (data && data.success) {
        showToast('节点删除成功', 'success');
        hideNodeDetail();
        refreshGraph();
    } else {
        showToast('删除失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 显示添加关系对话框 =====
function showAddRelationDialog(fromNodeId) {
    // 获取所有节点列表
    const allNodes = graphData.nodes ? graphData.nodes.get() : [];
    const optionsHtml = allNodes
        .filter(n => n.id !== fromNodeId)
        .map(n => `<option value="${escapeAttrValue(n.id)}">${escapeHtml(n.label)}</option>`)
        .join('');
    
    showModal('添加关系', `
        <div class="form-group">
            <label class="form-label">源节点</label>
            <input type="text" class="form-input" value="${escapeAttrValue(fromNodeId)}" disabled>
        </div>
        <div class="form-group">
            <label class="form-label">目标节点</label>
            <select id="relation-to-node" class="form-select">
                ${optionsHtml}
            </select>
        </div>
        <div class="form-group">
            <label class="form-label">关系类型</label>
            <input type="text" id="relation-type" class="form-input" placeholder="开发、创建、属于、使用...">
            <div class="form-hint">常用：开发、创建、使用、属于、包含、朋友、同事</div>
        </div>
        <div style="margin-top: 15px; text-align: right;">
            <button class="btn" onclick="closeModal()">取消</button>
            <button class="btn btn-success" onclick="createRelation('${escapeAttr(fromNodeId)}')" style="margin-left: 10px;">✨ 创建</button>
        </div>
    `);
}

// ===== 创建关系 =====
async function createRelation(fromNodeId) {
    const toNodeId = document.getElementById('relation-to-node').value;
    const relationType = document.getElementById('relation-type').value.trim() || '关联';
    
    if (!toNodeId) {
        showToast('请选择目标节点', 'error');
        return;
    }
    
    const data = await apiCall('/graph/relation', 'POST', {
        from_node: fromNodeId,
        to_node: toNodeId,
        relation_type: relationType
    });
    
    if (data && data.success) {
        showToast('关系创建成功', 'success');
        closeModal();
        refreshGraph();
    } else {
        showToast('创建失败: ' + (data?.error || '未知错误'), 'error');
    }
}

// ===== 删除关系（点击边时） =====
async function deleteRelation(fromNodeId, toNodeId, relationType) {
    if (!confirm(`确定要删除关系 "${fromNodeId} --${relationType}--> ${toNodeId}" 吗？`)) {
        return;
    }
    
    const data = await apiCall('/graph/relation', 'DELETE', {
        from_node: fromNodeId,
        to_node: toNodeId,
        relation_type: relationType
    });
    
    if (data && data.success) {
        showToast('关系删除成功', 'success');
        refreshGraph();
    } else {
        showToast('删除失败: ' + (data?.error || '未知错误'), 'error');
    }
}
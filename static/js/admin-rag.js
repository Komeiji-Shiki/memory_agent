/**
 * Admin RAG - RAG 语义搜索
 */

async function loadRagStats() {
    const container = document.getElementById('rag-stats');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    try {
        const data = await apiCall('/rag/stats');
        
        if (!data.enabled) {
            container.innerHTML = `
            <div class="alert alert-warning">
                <span>⚠️</span>
                <div>RAG 未启用或未配置 API Key。请在下方配置后启用。</div>
            </div>`;
            return;
        }
        
        let html = `
        <div class="stats-grid" style="margin-bottom: 0;">
            <div class="stat-card">
                <div class="stat-card-label">📊 向量总数</div>
                <div class="stat-card-value">${data.total_entries || 0}</div>
                <div class="stat-card-detail">条向量</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-label">🤖 嵌入模型</div>
                <div class="stat-card-value" style="font-size: 1rem;">${escapeHtml(data.model) || '-'}</div>
                <div class="stat-card-detail">SiliconFlow</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-label">⏰ 最后更新</div>
                <div class="stat-card-value" style="font-size: 1rem;">${data.last_updated ? escapeHtml(data.last_updated.substring(0, 10)) : '-'}</div>
                <div class="stat-card-detail">${data.last_updated ? escapeHtml(data.last_updated.substring(11, 16)) : ''}</div>
            </div>
        </div>`;
        
        if (data.by_type && Object.keys(data.by_type).length > 0) {
            html += '<div style="margin-top: 15px;"><strong style="color: var(--text-dim);">按类型分布：</strong>';
            html += '<div style="display: flex; gap: 15px; margin-top: 8px; flex-wrap: wrap;">';
            for (const [type, count] of Object.entries(data.by_type)) {
                html += `<span class="badge badge-info">${escapeHtml(type)}: ${count}</span>`;
            }
            html += '</div></div>';
        }
        
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<p style="color: var(--danger);">加载失败: ' + e.message + '</p>';
    }
}

async function loadRagConfig() {
    try {
        const data = await apiCall('/rag/config');
        
        if (data && !data.error) {
            document.getElementById('cfg-rag-enabled').checked = data.enabled === true;
            document.getElementById('cfg-rag-api-key').value = data.has_api_key ? '********' : '';
            document.getElementById('cfg-rag-model').value = data.model || 'Qwen/Qwen3-Embedding-8B';
            document.getElementById('cfg-rag-url').value = data.base_url || 'https://api.siliconflow.cn/v1/embeddings';
            document.getElementById('cfg-rag-chunk-size').value = data.chunk_size || 500;
            document.getElementById('cfg-rag-chunk-overlap').value = data.chunk_overlap || 50;
            document.getElementById('cfg-rag-top-k').value = data.top_k || 5;
            document.getElementById('cfg-rag-threshold').value = data.similarity_threshold || 0.3;
        }
    } catch (e) {
        console.error('加载 RAG 配置失败', e);
    }
}

async function saveRagConfig() {
    const apiKey = document.getElementById('cfg-rag-api-key').value;
    
    const config = {
        enabled: document.getElementById('cfg-rag-enabled').checked,
        model: document.getElementById('cfg-rag-model').value,
        base_url: document.getElementById('cfg-rag-url').value,
        chunk_size: parseInt(document.getElementById('cfg-rag-chunk-size').value) || 500,
        chunk_overlap: parseInt(document.getElementById('cfg-rag-chunk-overlap').value) || 50,
        top_k: parseInt(document.getElementById('cfg-rag-top-k').value) || 5,
        similarity_threshold: parseFloat(document.getElementById('cfg-rag-threshold').value) || 0.3
    };
    
    if (apiKey && apiKey !== '********') {
        config.api_key = apiKey;
    }
    
    try {
        const result = await apiCall('/rag/config', 'POST', config);
        
        if (result && result.success) {
            showToast('RAG 配置已保存（需要重建索引生效）', 'success');
            loadRagStats();
        } else {
            showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

async function rebuildRagIndex() {
    if (!confirm('确定要重建 RAG 向量索引吗？\n\n这将对所有记忆内容进行向量化，可能需要几分钟时间。')) return;
    
    const status = document.getElementById('rag-rebuild-status');
    status.innerHTML = '<span class="spinner"></span> 重建中...请耐心等待';
    
    try {
        const result = await apiCall('/rag/rebuild', 'POST');
        
        if (result && result.success) {
            const stats = result.stats || {};
            status.innerHTML = `<span style="color: var(--success);">✅ 完成！日记 ${stats.diaries || 0} 个，节点 ${stats.nodes || 0} 个，总结 ${stats.summaries || 0} 个，共 ${stats.total_vectors || 0} 个向量</span>`;
            showToast('索引重建完成', 'success');
            loadRagStats();
        } else {
            const errorMsg = result?.message || result?.error || '重建失败';
            status.innerHTML = `<span style="color: var(--danger);">❌ ${escapeHtml(errorMsg)}</span>`;
            showToast(errorMsg, 'error');
        }
    } catch (e) {
        status.innerHTML = '<span style="color: var(--danger);">❌ 重建失败</span>';
        showToast('重建失败', 'error');
    }
}

async function ragSearch() {
    const query = document.getElementById('rag-search-query').value;
    if (!query) {
        showToast('请输入查询内容', 'error');
        return;
    }
    
    const filterType = document.getElementById('rag-search-type').value;
    const container = document.getElementById('rag-search-results');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 搜索中...</div>';
    
    try {
        const payload = { query, top_k: 10 };
        if (filterType) payload.filter_type = filterType;
        
        const data = await apiCall('/rag/search', 'POST', payload);
        
        if (data && data.error) {
            container.innerHTML = `<div class="alert alert-danger"><span>❌</span><div>${escapeHtml(data.error)}</div></div>`;
            return;
        }
        
        if (!data || !data.results || data.results.length === 0) {
            container.innerHTML = '<p style="color: var(--text-dim);">未找到语义相关的内容</p>';
            return;
        }
        
        let html = `<p style="color: var(--text-dim); margin-bottom: 15px;">找到 ${data.total || 0} 条语义相关结果：</p>`;
        
        data.results.forEach((r, i) => {
            const similarity = ((r.similarity || 0) * 100).toFixed(1);
            const typeLabel = r.metadata?.type || 'unknown';
            const date = r.metadata?.date || '';
            
            const simColor = r.similarity > 0.7 ? 'var(--success)' :
                             r.similarity > 0.5 ? 'var(--accent)' : 'var(--text-dim)';
            
            html += `
            <div style="background: var(--surface-2); padding: 15px; margin-bottom: 12px; border-radius: 8px; border-left: 3px solid ${simColor};">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <div>
                        <span class="badge badge-info">${escapeHtml(typeLabel)}</span>
                        ${date ? `<span style="margin-left: 8px; color: var(--text-dim);">${escapeHtml(date)}</span>` : ''}
                    </div>
                    <span style="color: ${simColor}; font-weight: 600;">相似度 ${similarity}%</span>
                </div>
                <p style="color: var(--text-main); margin: 0; line-height: 1.6; font-size: 0.9rem;">${escapeHtml(r.content || '')}</p>
            </div>`;
        });
        
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<p style="color: var(--danger);">搜索失败: ' + e.message + '</p>';
    }
}
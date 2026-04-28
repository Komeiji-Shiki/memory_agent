/**
 * Admin Summary - 总结生成
 */

function updateSummaryIdentifier() {
    const type = document.getElementById('summary-type').value;
    const input = document.getElementById('summary-identifier');
    const hint = document.getElementById('identifier-hint');
    
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth() + 1;
    const quarter = Math.ceil(month / 3);
    
    // 获取 ISO 周数
    const d = new Date(now);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() + 3 - (d.getDay() + 6) % 7);
    const week1 = new Date(d.getFullYear(), 0, 4);
    const weekNum = 1 + Math.round(((d - week1) / 86400000 - 3 + (week1.getDay() + 6) % 7) / 7);
    
    if (type === 'weekly') {
        const lastWeek = weekNum > 1 ? weekNum - 1 : 52;
        const lastWeekYear = weekNum > 1 ? year : year - 1;
        input.value = `${lastWeekYear}-W${String(lastWeek).padStart(2, '0')}`;
        hint.textContent = '格式：2025-W52（年份-W周数）';
    } else if (type === 'monthly') {
        const lastMonth = month > 1 ? month - 1 : 12;
        const lastMonthYear = month > 1 ? year : year - 1;
        input.value = `${lastMonthYear}-${String(lastMonth).padStart(2, '0')}`;
        hint.textContent = '格式：2025-12（年份-月份）';
    } else {
        const lastQ = quarter > 1 ? quarter - 1 : 4;
        const lastQYear = quarter > 1 ? year : year - 1;
        input.value = `${lastQYear}-Q${lastQ}`;
        hint.textContent = '格式：2025-Q4（年份-Q季度）';
    }
}

async function checkMissingSummaries() {
    const container = document.getElementById('missing-summaries');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 检测中...</div>';
    
    try {
        const data = await apiCall('/summary/missing?lookback=6');
        
        let html = '<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px;">';
        
        // 周总结
        html += '<div>';
        html += '<h4 style="color: var(--accent); margin-bottom: 10px;">📅 周总结</h4>';
        if (data.weekly && data.weekly.length > 0) {
            data.weekly.forEach(id => {
                html += `<div style="display: flex; justify-content: space-between; align-items: center; padding: 5px 0; border-bottom: 1px solid var(--line-weak);">
                    <span>${escapeHtml(id)}</span>
                    <button class="btn btn-sm btn-primary" onclick="quickGenerate('weekly', '${escapeAttr(id)}')">生成</button>
                </div>`;
            });
        } else {
            html += '<p style="color: var(--success);">✅ 无缺失</p>';
        }
        html += '</div>';
        
        // 月总结
        html += '<div>';
        html += '<h4 style="color: var(--accent); margin-bottom: 10px;">📆 月总结</h4>';
        if (data.monthly && data.monthly.length > 0) {
            data.monthly.forEach(id => {
                html += `<div style="display: flex; justify-content: space-between; align-items: center; padding: 5px 0; border-bottom: 1px solid var(--line-weak);">
                    <span>${escapeHtml(id)}</span>
                    <button class="btn btn-sm btn-primary" onclick="quickGenerate('monthly', '${escapeAttr(id)}')">生成</button>
                </div>`;
            });
        } else {
            html += '<p style="color: var(--success);">✅ 无缺失</p>';
        }
        html += '</div>';
        
        // 季度总结
        html += '<div>';
        html += '<h4 style="color: var(--accent); margin-bottom: 10px;">🗂️ 季度总结</h4>';
        if (data.quarterly && data.quarterly.length > 0) {
            data.quarterly.forEach(id => {
                html += `<div style="display: flex; justify-content: space-between; align-items: center; padding: 5px 0; border-bottom: 1px solid var(--line-weak);">
                    <span>${escapeHtml(id)}</span>
                    <button class="btn btn-sm btn-primary" onclick="quickGenerate('quarterly', '${escapeAttr(id)}')">生成</button>
                </div>`;
            });
        } else {
            html += '<p style="color: var(--success);">✅ 无缺失</p>';
        }
        html += '</div>';
        
        html += '</div>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<p style="color: var(--danger);">检测失败</p>';
    }
}

async function quickGenerate(type, identifier) {
    document.getElementById('summary-type').value = type;
    document.getElementById('summary-identifier').value = identifier;
    await generateSummary();
}

async function generateSummary() {
    const type = document.getElementById('summary-type').value;
    const identifier = document.getElementById('summary-identifier').value;
    const model = document.getElementById('summary-model').value;
    const prompt = document.getElementById('summary-prompt').value;
    
    if (!identifier) {
        showToast('请输入标识符', 'error');
        return;
    }
    
    const status = document.getElementById('generate-status');
    status.innerHTML = '<span class="spinner"></span> 生成中...（可能需要30秒）';
    
    const payload = { type, identifier };
    if (model) payload.model = model;
    if (prompt) payload.prompt = prompt;
    
    try {
        const result = await apiCall('/summary/generate', 'POST', payload);
        
        if (result && result.success) {
            status.innerHTML = '<span style="color: var(--success);">✅ 生成成功</span>';
            showToast(result.message || '生成成功', 'success');
            
            document.getElementById('summary-result-card').style.display = 'block';
            document.getElementById('summary-result').textContent = result.content || '';
            
            loadExistingSummaries();
            checkMissingSummaries();
        } else {
            const errorMsg = result?.message || result?.error || '未知错误';
            status.innerHTML = `<span style="color: var(--danger);">❌ ${escapeHtml(errorMsg)}</span>`;
            showToast(errorMsg, 'error');
        }
    } catch (e) {
        status.innerHTML = '<span style="color: var(--danger);">❌ 生成失败</span>';
        showToast('生成失败', 'error');
    }
}

async function loadSummaryConfig() {
    try {
        const data = await apiCall('/summary/config');
        if (data && !data.error) {
            document.getElementById('cfg-summary-model').value = data.model || 'deepseek-chat';
            document.getElementById('cfg-weekly-prompt').value = data.weekly_prompt || '';
            document.getElementById('cfg-monthly-prompt').value = data.monthly_prompt || '';
            document.getElementById('cfg-quarterly-prompt').value = data.quarterly_prompt || '';
            
            document.getElementById('cfg-summary-retry').checked = data.enable_retry !== false;
            document.getElementById('cfg-summary-max-retries').value = data.max_retries || 3;
            document.getElementById('cfg-summary-base-delay').value = data.base_delay || 1.0;
            document.getElementById('cfg-summary-max-delay').value = data.max_delay || 30;
        } else if (data && data.error) {
            console.error('加载总结配置失败:', data.error);
        }
    } catch (e) {
        console.error('加载总结配置失败:', e);
    }
}

async function saveSummaryConfig() {
    const config = {
        model: document.getElementById('cfg-summary-model').value,
        weekly_prompt: document.getElementById('cfg-weekly-prompt').value,
        monthly_prompt: document.getElementById('cfg-monthly-prompt').value,
        quarterly_prompt: document.getElementById('cfg-quarterly-prompt').value,
        enable_retry: document.getElementById('cfg-summary-retry').checked,
        max_retries: parseInt(document.getElementById('cfg-summary-max-retries').value) || 3,
        base_delay: parseFloat(document.getElementById('cfg-summary-base-delay').value) || 1.0,
        max_delay: parseFloat(document.getElementById('cfg-summary-max-delay').value) || 30
    };
    
    try {
        const result = await apiCall('/summary/config', 'POST', config);
        if (result && result.success) {
            showToast('总结配置已保存', 'success');
        } else {
            showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

async function loadExistingSummaries() {
    const container = document.getElementById('existing-summaries');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    try {
        const data = await apiCall('/summaries');
        
        let html = '<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;">';
        
        ['weekly', 'monthly', 'quarterly'].forEach(type => {
            const typeNames = { weekly: '周总结', monthly: '月总结', quarterly: '季度总结' };
            const emojis = { weekly: '📅', monthly: '📆', quarterly: '🗂️' };
            
            html += `<div>
                <h4 style="color: var(--accent); margin-bottom: 10px;">${emojis[type]} ${typeNames[type]}</h4>`;
            
            if (data[type] && data[type].length > 0) {
                data[type].forEach(s => {
                    html += `<div style="padding: 8px; margin-bottom: 8px; background: var(--surface-2); border-radius: 6px; border: 1px solid var(--line-weak);">
                        <div style="font-weight: 600; color: var(--accent); margin-bottom: 4px;">${escapeHtml(s.identifier)}</div>
                        <div style="font-size: 0.8rem; color: var(--text-dim);">${escapeHtml(s.preview || '')}</div>
                    </div>`;
                });
            } else {
                html += '<p style="color: var(--text-dim);">暂无</p>';
            }
            html += '</div>';
        });
        
        html += '</div>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<p style="color: var(--danger);">加载失败</p>';
    }
}
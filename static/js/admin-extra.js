/**
 * Admin Extra - 额外挂载管理
 */

// 加载额外挂载配置和内容
async function loadExtraMount() {
    try {
        const data = await apiCall('/extra');
        if (data) {
            // 设置启用状态
            document.getElementById('extra-mount-enabled').checked = data.enabled;
            
            // 设置前置挂载内容
            document.getElementById('extra-prefix-content').value = data.prefix?.content || '';
            const prefixStatus = document.getElementById('extra-prefix-status');
            if (data.prefix?.exists) {
                prefixStatus.textContent = `📄 文件: ${data.prefix.path} (${data.prefix.content?.length || 0} 字符)`;
            } else {
                prefixStatus.textContent = `⚠️ 文件不存在: ${data.prefix?.path || 'lifebook/extra/prefix.md'}`;
            }
            
            // 设置后置挂载内容
            document.getElementById('extra-suffix-content').value = data.suffix?.content || '';
            const suffixStatus = document.getElementById('extra-suffix-status');
            if (data.suffix?.exists) {
                suffixStatus.textContent = `📄 文件: ${data.suffix.path} (${data.suffix.content?.length || 0} 字符)`;
            } else {
                suffixStatus.textContent = `⚠️ 文件不存在: ${data.suffix?.path || 'lifebook/extra/suffix.md'}`;
            }
            
            // 更新状态显示
            updateExtraStatus(data.enabled);
            
            showToast('额外挂载配置已加载', 'success');
        }
    } catch (e) {
        showToast('加载额外挂载失败: ' + e.message, 'error');
    }
}

// 更新状态显示
function updateExtraStatus(enabled) {
    const statusEl = document.getElementById('extra-status');
    if (enabled) {
        statusEl.innerHTML = '<span style="color: var(--success);">✅ 额外挂载已启用</span>';
    } else {
        statusEl.innerHTML = '<span style="color: var(--text-dim);">⏸️ 额外挂载已禁用</span>';
    }
}

// 切换启用状态
async function toggleExtraMount() {
    const enabled = document.getElementById('extra-mount-enabled').checked;
    try {
        const result = await apiCall('/extra/toggle', 'POST', { enabled });
        if (result && result.success) {
            updateExtraStatus(enabled);
            showToast(result.message, 'success');
        } else {
            showToast('切换失败: ' + (result?.error || '未知错误'), 'error');
            // 回滚复选框状态
            document.getElementById('extra-mount-enabled').checked = !enabled;
        }
    } catch (e) {
        showToast('切换失败: ' + e.message, 'error');
        document.getElementById('extra-mount-enabled').checked = !enabled;
    }
}

// 保存前置挂载
async function saveExtraPrefix() {
    const content = document.getElementById('extra-prefix-content').value;
    try {
        const result = await apiCall('/extra/prefix', 'PUT', { content });
        if (result && result.success) {
            document.getElementById('extra-prefix-status').textContent = 
                `📄 已保存 (${result.length} 字符)`;
            showToast('前置挂载已保存', 'success');
        } else {
            showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

// 保存后置挂载
async function saveExtraSuffix() {
    const content = document.getElementById('extra-suffix-content').value;
    try {
        const result = await apiCall('/extra/suffix', 'PUT', { content });
        if (result && result.success) {
            document.getElementById('extra-suffix-status').textContent = 
                `📄 已保存 (${result.length} 字符)`;
            showToast('后置挂载已保存', 'success');
        } else {
            showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

// 全部保存
async function saveAllExtra() {
    // 先保存启用状态
    await toggleExtraMount();
    // 再保存内容
    await saveExtraPrefix();
    await saveExtraSuffix();
    showToast('所有设置已保存', 'success');
}

// 绑定事件
document.addEventListener('DOMContentLoaded', function() {
    // 监听启用复选框变化
    const enabledCheckbox = document.getElementById('extra-mount-enabled');
    if (enabledCheckbox) {
        enabledCheckbox.addEventListener('change', toggleExtraMount);
    }
});
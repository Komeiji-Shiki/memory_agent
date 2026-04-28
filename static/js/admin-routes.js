/**
 * Admin Routes - 模型路由管理
 */

let modelRoutesData = {};
let modelRoutesDirty = false;
let modelRoutesSearchText = '';
let modelRoutesQuickFilter = 'all';
const routeModelsCache = new Map();

function buildRouteModelsCacheKey(baseUrl, apiKey) {
    return JSON.stringify({
        baseUrl: String(baseUrl || '').trim().replace(/\/+$/, ''),
        apiKey: String(apiKey || '').trim()
    });
}

function getCachedRouteModels(baseUrl, apiKey) {
    const key = buildRouteModelsCacheKey(baseUrl, apiKey);
    return routeModelsCache.get(key) || null;
}

function setCachedRouteModels(baseUrl, apiKey, models) {
    const key = buildRouteModelsCacheKey(baseUrl, apiKey);
    routeModelsCache.set(key, {
        models: Array.isArray(models) ? [...models] : [],
        cachedAt: new Date()
    });
}

function hasUnsavedModelRoutesChanges() {
    return modelRoutesDirty;
}

function setModelRoutesDirty(isDirty = true) {
    modelRoutesDirty = !!isDirty;
}

function confirmModelRoutesPageLeave(actionLabel = '离开当前页面') {
    if (!modelRoutesDirty) {
        return true;
    }
    return confirm(`模型路由存在未保存变更，确定要${actionLabel}吗？`);
}

function setupModelRoutesDirtyTracking() {
    const container = document.getElementById('model-routes-container');
    if (!container || container.dataset.dirtyTrackingBound === '1') {
        return;
    }

    const markDirty = (event) => {
        if (event.target?.closest('.route-card')) {
            setModelRoutesDirty(true);
        }
    };

    container.addEventListener('input', markDirty);
    container.addEventListener('change', markDirty);
    container.dataset.dirtyTrackingBound = '1';
}

function isValidHttpUrl(value) {
    try {
        const url = new URL(String(value || '').trim());
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch (_) {
        return false;
    }
}

function focusRouteField(input, message) {
    if (input && typeof input.focus === 'function') {
        input.focus();
        if (typeof input.select === 'function') {
            input.select();
        }
    }
    showToast(message, 'error');
}

function buildRouteModelStatusHtml() {
    return '<div data-role="route-model-status" style="display: none; margin-top: 8px; font-size: 12px; color: var(--text-dim);"></div>';
}

function setModelRoutesSearchText(value) {
    modelRoutesSearchText = String(value || '').trim().toLowerCase();
    renderModelRoutes();
}

function setModelRoutesQuickFilter(value) {
    modelRoutesQuickFilter = String(value || 'all');
    renderModelRoutes();
}

function buildModelRoutesToolbarHtml(totalCount, filteredCount) {
    return `
        <div style="display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-bottom: 18px; padding: 14px; background: var(--surface-2); border-radius: 10px;">
            <input
                type="text"
                class="form-input"
                placeholder="搜索模型名 / 实际模型ID / API 地址"
                value="${escapeAttrValue(modelRoutesSearchText)}"
                oninput="setModelRoutesSearchText(this.value)"
                style="flex: 1; min-width: 260px;"
            >
            <select class="form-select" onchange="setModelRoutesQuickFilter(this.value)" style="width: 220px;">
                <option value="all" ${modelRoutesQuickFilter === 'all' ? 'selected' : ''}>全部路由</option>
                <option value="supports_images" ${modelRoutesQuickFilter === 'supports_images' ? 'selected' : ''}>仅支持图片</option>
                <option value="use_xml_tools" ${modelRoutesQuickFilter === 'use_xml_tools' ? 'selected' : ''}>仅 XML 工具</option>
                <option value="enable_thinking" ${modelRoutesQuickFilter === 'enable_thinking' ? 'selected' : ''}>仅原生 Thinking</option>
            </select>
            <span style="color: var(--text-dim); font-size: 0.85rem;">显示 ${filteredCount} / ${totalCount}</span>
        </div>
    `;
}

function matchesModelRoutesFilter(name, config) {
    const searchText = modelRoutesSearchText;
    const baseUrl = String(config?.base_url || '').toLowerCase();
    const actualModel = String(config?.actual_model || name || '').toLowerCase();
    const routeName = String(name || '').toLowerCase();

    if (searchText) {
        const matchesSearch = routeName.includes(searchText)
            || actualModel.includes(searchText)
            || baseUrl.includes(searchText);

        if (!matchesSearch) {
            return false;
        }
    }

    switch (modelRoutesQuickFilter) {
        case 'supports_images':
            return config?.supports_images === true || config?.vision === true;
        case 'use_xml_tools':
            return config?.use_xml_tools === true;
        case 'enable_thinking':
            return config?.enable_thinking === true;
        default:
            return true;
    }
}

function setRouteModelStatus(card, message = '', type = 'info') {
    const statusEl = card?.querySelector('[data-role="route-model-status"]');
    if (!statusEl) return;

    if (!message) {
        statusEl.style.display = 'none';
        statusEl.textContent = '';
        return;
    }

    statusEl.style.display = 'block';
    statusEl.textContent = message;
    statusEl.style.color = type === 'success'
        ? 'var(--success)'
        : type === 'error'
            ? 'var(--danger)'
            : 'var(--text-dim)';
}

function syncRouteNameFromActualModel(card, nextModel, previousActualModel = '') {
    const nameInput = card?.querySelector('[data-field="name"]');
    if (!nameInput) return;

    const nextValue = String(nextModel || '').trim();
    const previousValue = String(previousActualModel || '').trim();
    const currentName = nameInput.value.trim();

    if (!nextValue) return;

    if (!currentName || currentName === previousValue) {
        nameInput.value = nextValue;
    }
}

function buildActualModelPickerHtml(currentValue = '') {
    const selectedValue = String(currentValue || '').trim();
    const selectedOption = selectedValue
        ? `<option value="${escapeAttrValue(selectedValue)}" selected>${escapeHtml(selectedValue)}</option>`
        : '';

    return `
        <div class="route-model-picker">
            <select class="route-field-input route-model-picker-select" data-role="actual-model-select" onchange="syncRouteModelInputFromSelect(this)">
                <option value="">手动输入或点击获取模型列表</option>
                ${selectedOption}
            </select>
            <button class="btn btn-primary route-model-picker-button" type="button" onclick="fetchRouteModels(this)">📥 获取模型</button>
        </div>
        ${buildRouteModelStatusHtml()}
    `;
}

function syncRouteModelInputFromSelect(select) {
    const card = select?.closest('.route-card');
    const input = card?.querySelector('[data-field="actual_model"]');
    if (!input || !select.value) return;

    const previousActualModel = input.value.trim();
    input.value = select.value;
    syncRouteNameFromActualModel(card, select.value, previousActualModel);
}

function syncRouteModelSelectFromInput(input) {
    const card = input?.closest('.route-card');
    const select = card?.querySelector('[data-role="actual-model-select"]');
    if (!select) return;

    const value = input.value.trim();
    if (!value) {
        select.value = '';
        return;
    }

    const matchedOption = Array.from(select.options).find(option => option.value === value);
    select.value = matchedOption ? value : '';
}

function populateRouteModelOptions(card, models) {
    const select = card?.querySelector('[data-role="actual-model-select"]');
    const input = card?.querySelector('[data-field="actual_model"]');
    if (!select || !input) return;

    const currentValue = input.value.trim();
    const uniqueModels = Array.from(
        new Set((models || []).map(model => String(model).trim()).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));

    let options = '<option value="">手动输入或选择模型</option>';
    if (currentValue && !uniqueModels.includes(currentValue)) {
        options += `<option value="${escapeAttrValue(currentValue)}">${escapeHtml(currentValue)}（当前）</option>`;
    }
    options += uniqueModels.map(model =>
        `<option value="${escapeAttrValue(model)}">${escapeHtml(model)}</option>`
    ).join('');

    select.innerHTML = options;

    if (currentValue) {
        select.value = currentValue;
    } else if (uniqueModels.length > 0) {
        select.value = uniqueModels[0];
        input.value = uniqueModels[0];
    }
}

async function fetchRouteModels(button) {
    const card = button?.closest('.route-card');
    if (!card) return;

    const baseUrlInput = card.querySelector('[data-field="base_url"]');
    const routeNameInput = card.querySelector('[data-field="name"]');
    const apiKeyInput = card.querySelector('[data-field="api_key"]');
    const actualModelInput = card.querySelector('[data-field="actual_model"]');

    const baseUrl = baseUrlInput?.value?.trim() || '';
    const routeName = routeNameInput?.value?.trim() || '';
    const apiKey = apiKeyInput?.value || '';
    const previousActualModel = actualModelInput?.value?.trim() || '';

    if (!baseUrl) {
        setRouteModelStatus(card, '请先填写 API 地址', 'error');
        showToast('请先填写 API 地址', 'error');
        return;
    }

    if (!isValidHttpUrl(baseUrl)) {
        setRouteModelStatus(card, 'API 地址格式无效，请填写 http:// 或 https:// 地址', 'error');
        showToast('API 地址格式无效', 'error');
        return;
    }

    const cachedEntry = getCachedRouteModels(baseUrl, apiKey);
    if (cachedEntry) {
        populateRouteModelOptions(card, cachedEntry.models);
        if ((actualModelInput?.value?.trim() || '') !== previousActualModel) {
            setModelRoutesDirty(true);
        }
        setRouteModelStatus(
            card,
            `已从缓存加载 ${cachedEntry.models.length} 个模型（${cachedEntry.cachedAt.toLocaleTimeString()}）`,
            'success'
        );
        showToast(`已从缓存加载 ${cachedEntry.models.length} 个模型`, 'success');
        return;
    }

    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = '加载中...';
    setRouteModelStatus(card, '正在从远端接口获取模型列表...', 'info');

    try {
        const result = await apiCall('/config/model_routes/models', 'POST', {
            base_url: baseUrl,
            route_name: routeName,
            api_key: apiKey
        });

        if (result && result.success && Array.isArray(result.models)) {
            populateRouteModelOptions(card, result.models);
            setCachedRouteModels(baseUrl, apiKey, result.models);
            if ((actualModelInput?.value?.trim() || '') !== previousActualModel) {
                setModelRoutesDirty(true);
            }
            const successMessage = `已获取 ${result.models.length} 个模型`;
            setRouteModelStatus(card, `${successMessage}（已写入缓存）`, 'success');
            showToast(successMessage, 'success');
        } else {
            const errorMessage = result?.error || '未知错误';
            setRouteModelStatus(card, `获取模型失败：${errorMessage}`, 'error');
            showToast(`获取模型失败: ${errorMessage}`, 'error');
        }
    } catch (error) {
        const errorMessage = error?.message || '未知错误';
        setRouteModelStatus(card, `获取模型失败：${errorMessage}`, 'error');
        showToast(`获取模型失败: ${errorMessage}`, 'error');
    } finally {
        button.disabled = false;
        button.textContent = originalText;
    }
}

async function loadModelRoutes() {
    const container = document.getElementById('model-routes-container');

    if (modelRoutesDirty && !confirmModelRoutesPageLeave('重新加载配置')) {
        return;
    }

    container.innerHTML = '<div class="loading"><span class="spinner"></span> 加载中...</div>';
    
    try {
        const data = await apiCall('/config/model_routes?reveal_secrets=1');
        if (data && data.value) {
            modelRoutesData = data.value;
            renderModelRoutes();
            setupModelRoutesDirtyTracking();
            setModelRoutesDirty(false);
        } else {
            container.innerHTML = '<p style="color: var(--text-dim);">无法加载配置</p>';
        }
    } catch (e) {
        container.innerHTML = '<p style="color: var(--danger);">加载失败</p>';
    }
}

function renderModelRoutes() {
    const container = document.getElementById('model-routes-container');
    const allRoutes = Object.entries(modelRoutesData).filter(([name]) => name !== '_default');
    const visibleRoutes = allRoutes.filter(([name, config]) => matchesModelRoutesFilter(name, config));
    let cardsHtml = '';
    
    visibleRoutes.forEach(([name, config]) => {
        const baseUrl = config.base_url || '';
        const actualModel = config.actual_model || name;
        const apiKey = config.api_key || '';
        const thinkingMode = config.thinking_mode;
        const enableThinking = config.enable_thinking === true;
        const budgetTokens = config.thinking_budget_tokens || '';
        const useXmlTools = config.use_xml_tools === true;
        // 合并 supports_images / vision：任一为 true 即认为支持图片
        const supportsImages = (config.supports_images === true) || (config.vision === true);
        
        const thinkingOptions = [
            { value: 'auto', label: 'Auto', selected: thinkingMode === 'auto' || thinkingMode === undefined },
            { value: 'true', label: 'On', selected: thinkingMode === true },
            { value: 'false', label: 'Off', selected: thinkingMode === false }
        ];
        const thinkingSelect = thinkingOptions.map(opt =>
            `<option value="${opt.value}" ${opt.selected ? 'selected' : ''}>${opt.label}</option>`
        ).join('');
        
        cardsHtml += `
        <div class="route-card" data-model="${escapeAttrValue(name)}">
            <button class="route-card-delete" onclick="removeModelRoute('${escapeAttr(name)}')" title="删除">🗑️</button>
            <div class="route-card-header">
                <div class="route-card-title">
                    🤖 <input type="text" value="${escapeAttrValue(name)}" data-field="name" placeholder="模型名称">
                </div>
            </div>
            <div class="route-card-body">
                <div class="route-field">
                    <span class="route-field-label">API 地址</span>
                    <input type="text" class="route-field-input" value="${escapeAttrValue(baseUrl)}" data-field="base_url" placeholder="http://localhost:8317/v1">
                </div>
                <div class="route-field route-field-wide">
                    <span class="route-field-label">实际模型ID</span>
                    <input type="text" class="route-field-input" value="${escapeAttrValue(actualModel)}" data-field="actual_model" placeholder="同名称" oninput="syncRouteModelSelectFromInput(this)">
                    ${buildActualModelPickerHtml(actualModel)}
                </div>
                <div class="route-field">
                    <span class="route-field-label">API Key</span>
                    <div style="display: flex; gap: 10px;">
                        <input type="password" class="route-field-input" value="${escapeAttrValue(apiKey)}" data-field="api_key" data-reveal-endpoint="/config/model_routes" data-reveal-route="${escapeAttrValue(name)}" placeholder="留空使用用户Key" style="flex: 1;">
                        <button class="btn btn-sm" onclick="togglePassword(this.parentElement.querySelector('input'))">👁️</button>
                    </div>
                </div>
                <div class="route-options">
                    <div class="route-option">
                        <span>兼容模式</span>
                        <select data-field="thinking_mode">${thinkingSelect}</select>
                    </div>
                    <div class="route-option">
                        <input type="checkbox" data-field="enable_thinking" ${enableThinking ? 'checked' : ''}>
                        <span>原生Thinking</span>
                    </div>
                    <div class="route-option">
                        <input type="checkbox" data-field="use_xml_tools" ${useXmlTools ? 'checked' : ''}>
                        <span>XML工具</span>
                    </div>
                    <div class="route-option">
                        <input type="checkbox" data-field="supports_images" ${supportsImages ? 'checked' : ''}>
                        <span>支持图片 (supports_images)</span>
                    </div>
                    <div class="route-option">
                        <span>Budget</span>
                        <input type="number" data-field="thinking_budget_tokens" value="${escapeAttrValue(budgetTokens)}" placeholder="--">
                    </div>
                </div>
            </div>
        </div>`;
    });
    
    if (!cardsHtml) {
        cardsHtml = '<div style="padding: 24px; border: 1px dashed var(--line-weak); border-radius: 10px; color: var(--text-dim); text-align: center;">没有匹配的模型路由</div>';
    }

    cardsHtml += `
    <div class="add-route-card" onclick="addModelRoute()">
        <span>➕</span>
        <div>添加新模型</div>
    </div>`;
    
    container.innerHTML = `
        ${buildModelRoutesToolbarHtml(allRoutes.length, visibleRoutes.length)}
        ${cardsHtml}
    `;
}

function addModelRoute() {
    const container = document.getElementById('model-routes-container');
    const addCard = container.querySelector('.add-route-card');
    
    const newCard = document.createElement('div');
    newCard.className = 'route-card';
    newCard.dataset.model = '_new_' + Date.now();
    newCard.innerHTML = `
        <button class="route-card-delete" onclick="this.parentElement.remove()" title="删除">🗑️</button>
        <div class="route-card-header">
            <div class="route-card-title">
                🤖 <input type="text" data-field="name" placeholder="输入模型名称">
            </div>
        </div>
        <div class="route-card-body">
            <div class="route-field">
                <span class="route-field-label">API 地址</span>
                <input type="text" class="route-field-input" value="http://localhost:8317/v1" data-field="base_url">
            </div>
            <div class="route-field route-field-wide">
                <span class="route-field-label">实际模型ID</span>
                <input type="text" class="route-field-input" data-field="actual_model" placeholder="同名称" oninput="syncRouteModelSelectFromInput(this)">
                ${buildActualModelPickerHtml('')}
            </div>
            <div class="route-field">
                <span class="route-field-label">API Key</span>
                <div style="display: flex; gap: 10px;">
                    <input type="password" class="route-field-input" data-field="api_key" data-reveal-endpoint="/config/model_routes" placeholder="留空" style="flex: 1;">
                    <button class="btn btn-sm" onclick="togglePassword(this.parentElement.querySelector('input'))">👁️</button>
                </div>
            </div>
            <div class="route-options">
                <div class="route-option">
                    <span>兼容模式</span>
                    <select data-field="thinking_mode">
                        <option value="auto" selected>Auto</option>
                        <option value="true">On</option>
                        <option value="false">Off</option>
                    </select>
                </div>
                <div class="route-option">
                    <input type="checkbox" data-field="enable_thinking">
                    <span>原生Thinking</span>
                </div>
                <div class="route-option">
                    <input type="checkbox" data-field="use_xml_tools">
                    <span>XML工具</span>
                </div>
                <div class="route-option">
                    <input type="checkbox" data-field="supports_images">
                    <span>支持图片 (supports_images)</span>
                </div>
                <div class="route-option">
                    <span>Budget</span>
                    <input type="number" data-field="thinking_budget_tokens" placeholder="--">
                </div>
            </div>
        </div>
    `;
    container.insertBefore(newCard, addCard);
    setModelRoutesDirty(true);
    newCard.querySelector('[data-field="name"]').focus();
}

function removeModelRoute(name) {
    if (!confirm(`确定删除模型 ${name} 的路由配置？`)) return;
    delete modelRoutesData[name];
    renderModelRoutes();
}

async function saveModelRoutes() {
    const newRoutes = {};
    const cards = document.querySelectorAll('#model-routes-container .route-card');
    const usedNames = new Set();

    for (const card of cards) {
        const nameInput = card.querySelector('[data-field="name"]');
        const baseUrlInput = card.querySelector('[data-field="base_url"]');
        const actualModelInput = card.querySelector('[data-field="actual_model"]');
        const apiKeyInput = card.querySelector('[data-field="api_key"]');
        const thinkingSelect = card.querySelector('[data-field="thinking_mode"]');
        const enableThinkingInput = card.querySelector('[data-field="enable_thinking"]');
        const budgetTokensInput = card.querySelector('[data-field="thinking_budget_tokens"]');
        const useXmlToolsInput = card.querySelector('[data-field="use_xml_tools"]');
        const supportsImagesInput = card.querySelector('[data-field="supports_images"]');

        const name = nameInput?.value?.trim() || '';
        const baseUrl = baseUrlInput?.value?.trim() || '';

        if (!name) {
            continue;
        }

        if (usedNames.has(name)) {
            return focusRouteField(nameInput, `模型名称重复：${name}`);
        }
        usedNames.add(name);

        if (!baseUrl) {
            return focusRouteField(baseUrlInput, `模型 ${name} 缺少 API 地址`);
        }

        if (!isValidHttpUrl(baseUrl)) {
            return focusRouteField(baseUrlInput, `模型 ${name} 的 API 地址格式无效`);
        }

        let thinkingMode = 'auto';
        if (thinkingSelect) {
            const val = thinkingSelect.value;
            if (val === 'true') thinkingMode = true;
            else if (val === 'false') thinkingMode = false;
        }

        const routeConfig = {
            base_url: baseUrl,
            api_key: apiKeyInput?.value || '',
            actual_model: actualModelInput?.value?.trim() || name,
            thinking_mode: thinkingMode
        };

        if (enableThinkingInput && enableThinkingInput.checked) {
            routeConfig.enable_thinking = true;
        }

        if (budgetTokensInput && budgetTokensInput.value) {
            const budget = parseInt(budgetTokensInput.value);
            if (!isNaN(budget)) {
                routeConfig.thinking_budget_tokens = budget;
            }
        }

        if (useXmlToolsInput && useXmlToolsInput.checked) {
            routeConfig.use_xml_tools = true;
        }

        if (supportsImagesInput && supportsImagesInput.checked) {
            routeConfig.supports_images = true;
        }

        newRoutes[name] = routeConfig;
    }

    if (Object.keys(newRoutes).length === 0) {
        return showToast('没有可保存的模型路由', 'error');
    }

    if (modelRoutesData._default) {
        newRoutes._default = modelRoutesData._default;
    }

    const result = await apiCall('/config/model_routes', 'PUT', { value: newRoutes });
    if (result && result.success) {
        modelRoutesData = newRoutes;
        showToast(result.message || '路由配置已保存并已热更新生效', 'success');
    } else {
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

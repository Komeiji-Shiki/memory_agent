/**
 * 模型路由页
 * - 卡片式编辑：名称 / API 地址 / 实际模型（可拉取远端列表）/ API Key / Thinking / XML 工具 / 图片支持 / Budget
 * - 搜索 + 快速过滤
 * - 模型列表缓存（按 API 地址持久化到 localStorage，长期有效）
 * - 实际模型 ID 输入框 datalist 原生过滤补全（模型多也好找）
 * - 脏跟踪接入全局 store（换页 / 刷新统一拦截）
 * - 改进：删除卡片只移除 DOM，不再全量重渲染导致其他卡片编辑丢失
 */

import { apiCall } from '../core/api.js';
import { showToast, escapeHtml, escapeAttr, spinnerHtml, confirmDialog, bindActions, delegate } from '../core/ui.js';
import { markDirty, clearDirty, loadPref, savePref } from '../core/store.js';

const DIRTY_KEY = 'routes';

let rootEl = null;
let routesData = {};
let searchText = '';
let quickFilter = 'all';
let loaded = false;
let datalistSeq = 0;

// 模型列表缓存：按 API 地址持久化（localStorage），刷新/重开页面不丢
function getModelsCache() {
    return loadPref('routeModelsCache', {});
}

export const routesPage = {
    id: 'routes',
    title: '模型路由',
    icon: '🤖',
    group: 'settings',

    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="page-header">
                <h2>🤖 模型路由</h2>
                <p>配置模型到后端 API 的映射；模型名加 <code>-memory</code> 后缀自动启用记忆增强，API Key 留空则使用用户请求中的 Key</p>
            </div>

            <div class="card" style="padding: 14px;">
                <div style="display: flex; gap: 12px; flex-wrap: wrap; align-items: center;">
                    <input type="text" id="route-search" class="form-input" placeholder="搜索模型名 / 实际模型ID / API 地址" style="flex: 1; min-width: 240px;">
                    <select id="route-filter" class="form-select" style="width: 200px;">
                        <option value="all">全部路由</option>
                        <option value="supports_images">仅支持图片</option>
                        <option value="use_xml_tools">仅 XML 工具</option>
                        <option value="enable_thinking">仅原生 Thinking</option>
                    </select>
                    <span class="text-dim" style="font-size: 0.85rem;" id="route-count"></span>
                </div>
            </div>

            <div class="route-cards" id="route-cards">${spinnerHtml()}</div>

            <div style="margin-top: 24px; display: flex; gap: 12px;">
                <button class="btn btn-success" data-action="save-routes">💾 保存所有配置</button>
                <button class="btn" data-action="reload-routes">🔄 重新加载</button>
            </div>
        `;

        bindActions(container, {
            'save-routes': saveRoutes,
            'reload-routes': () => loadRoutes(true),
            'add-route': addRouteCard,
            'delete-route': async (target) => {
                const card = target.closest('.route-card');
                const name = card.querySelector('[data-field="name"]')?.value?.trim() || '(未命名)';
                const ok = await confirmDialog(`确定删除模型「${name}」的路由配置吗？\n（保存后才会真正生效）`, { danger: true, okText: '删除' });
                if (ok) {
                    card.remove();
                    markDirty(DIRTY_KEY, '模型路由');
                }
            },
            'toggle-pw': (target) => {
                const input = target.parentElement.querySelector('input');
                if (input) input.type = input.type === 'password' ? 'text' : 'password';
            },
            'fetch-models': (target) => fetchModels(target),
        });

        // 搜索 / 过滤
        container.querySelector('#route-search').addEventListener('input', (e) => {
            searchText = e.target.value.trim().toLowerCase();
            renderCards();
        });
        container.querySelector('#route-filter').addEventListener('change', (e) => {
            quickFilter = e.target.value;
            renderCards();
        });

        // 脏跟踪（过滤框只是 UI 操作，不算修改）
        delegate(container, 'input', '.route-card input:not([data-role="model-filter"]), .route-card select', () => {
            markDirty(DIRTY_KEY, '模型路由');
        });

        // 实际模型输入 ↔ 下拉同步
        delegate(container, 'input', '[data-field="actual_model"]', (e, input) => {
            const select = input.closest('.route-card')?.querySelector('[data-role="model-select"]');
            if (!select) return;
            const value = input.value.trim();
            const matched = [...select.options].some((o) => o.value === value);
            select.value = matched ? value : '';
        });
        delegate(container, 'change', '[data-role="model-select"]', (e, select) => {
            const card = select.closest('.route-card');
            const input = card?.querySelector('[data-field="actual_model"]');
            if (!input || !select.value) return;
            const previous = input.value.trim();
            input.value = select.value;
            syncNameFromModel(card, select.value, previous);
            markDirty(DIRTY_KEY, '模型路由');
        });

        // 模型列表过滤（拉取后模型多时快速定位）
        // 注意：Chrome 不支持 option 的 hidden/display:none，必须重建 options
        delegate(container, 'input', '[data-role="model-filter"]', (e, el) => {
            const card = el.closest('.route-card');
            const select = card?.querySelector('[data-role="model-select"]');
            if (!select || !Array.isArray(select._allModels)) return;
            const q = el.value.trim().toLowerCase();
            const matched = q ? select._allModels.filter((m) => m.toLowerCase().includes(q)) : select._allModels;
            const currentValue = card.querySelector('[data-field="actual_model"]')?.value.trim() || '';
            let options = '<option value="">手动输入或选择模型</option>';
            if (currentValue && !matched.includes(currentValue)) {
                options += `<option value="${escapeAttr(currentValue)}">${escapeHtml(currentValue)}（当前）</option>`;
            }
            options += matched.map((m) => `<option value="${escapeAttr(m)}">${escapeHtml(m)}</option>`).join('');
            select.innerHTML = options;
            if (currentValue && matched.includes(currentValue)) select.value = currentValue;
        });
    },

    onEnter() {
        if (!loaded) loadRoutes();
    },
};

// ===== 加载 / 渲染 =====

async function loadRoutes(manual = false) {
    const container = rootEl.querySelector('#route-cards');
    container.innerHTML = spinnerHtml();
    const data = await apiCall('/config/model_routes?reveal_secrets=1');
    if (data && data.value) {
        routesData = data.value;
        loaded = true;
        clearDirty(DIRTY_KEY);
        renderCards();
        if (manual) showToast('模型路由已重新加载', 'success');
    } else {
        container.innerHTML = `<div class="alert alert-danger"><span>❌</span><div>无法加载配置${data?.error ? ': ' + escapeHtml(data.error) : ''}</div></div>`;
    }
}

function matchesFilter(name, config) {
    if (searchText) {
        const haystack = [name, config?.actual_model || name, config?.base_url || ''].join(' ').toLowerCase();
        if (!haystack.includes(searchText)) return false;
    }
    switch (quickFilter) {
        case 'supports_images': return config?.supports_images === true || config?.vision === true;
        case 'use_xml_tools': return config?.use_xml_tools === true;
        case 'enable_thinking': return config?.enable_thinking === true;
        default: return true;
    }
}

function renderCards() {
    const container = rootEl.querySelector('#route-cards');
    const allRoutes = Object.entries(routesData).filter(([name]) => name !== '_default');
    const visible = allRoutes.filter(([name, config]) => matchesFilter(name, config));

    rootEl.querySelector('#route-count').textContent = `显示 ${visible.length} / ${allRoutes.length}`;

    let html = '';
    for (const [name, config] of visible) {
        html += buildCardHtml(name, config);
    }
    if (!html) {
        html = '<div style="padding: 24px; border: 1px dashed var(--line-weak); border-radius: 10px; color: var(--text-dim); text-align: center; grid-column: 1 / -1;">没有匹配的模型路由</div>';
    }
    html += `<div class="route-card add-card" data-action="add-route"><span>➕ 添加新模型</span></div>`;
    container.innerHTML = html;
}

function buildCardHtml(name, config = {}) {
    const baseUrl = config.base_url || '';
    const actualModel = config.actual_model || name;
    const apiKey = config.api_key || '';
    const thinkingMode = config.thinking_mode;
    const supportsImages = config.supports_images === true || config.vision === true;

    const thinkingOptions = [
        { value: 'auto', label: 'Auto', selected: thinkingMode === 'auto' || thinkingMode === undefined },
        { value: 'true', label: 'On', selected: thinkingMode === true },
        { value: 'false', label: 'Off', selected: thinkingMode === false },
    ].map((o) => `<option value="${o.value}"${o.selected ? ' selected' : ''}>${o.label}</option>`).join('');

    const currentModelOption = actualModel
        ? `<option value="${escapeAttr(actualModel)}" selected>${escapeHtml(actualModel)}</option>` : '';

    const datalistId = `models-dl-${++datalistSeq}`;

    return `
    <div class="route-card">
        <div class="route-card-header">
            <div class="route-card-title">🤖 <input type="text" class="form-input" value="${escapeAttr(name)}" data-field="name" placeholder="模型名称"></div>
            <button class="icon-btn" data-action="delete-route" title="删除">🗑️</button>
        </div>
        <div class="route-field">
            <span class="route-field-label">API 地址</span>
            <input type="text" class="form-input" value="${escapeAttr(baseUrl)}" data-field="base_url" placeholder="http://localhost:8317/v1">
        </div>
        <div class="route-field">
            <span class="route-field-label">实际模型 ID</span>
            <input type="text" class="form-input" value="${escapeAttr(actualModel)}" data-field="actual_model" placeholder="同名称" list="${datalistId}">
            <datalist id="${datalistId}"></datalist>
            <div class="input-with-btn" style="margin-top: 6px;">
                <select class="form-select" data-role="model-select">
                    <option value="">手动输入或点击获取模型列表</option>
                    ${currentModelOption}
                </select>
                <button class="btn btn-sm btn-primary" data-action="fetch-models" type="button">📥 获取模型</button>
            </div>
            <input type="text" class="form-input" data-role="model-filter" placeholder="🔍 输入关键词过滤模型列表..." style="margin-top: 6px; display: none;">
            <div class="route-model-status text-dim" data-role="model-status" style="display: none;"></div>
        </div>
        <div class="route-field">
            <span class="route-field-label">API Key</span>
            <div class="input-with-btn">
                <input type="password" class="form-input" value="${escapeAttr(apiKey)}" data-field="api_key" placeholder="留空使用用户 Key">
                <button class="btn btn-sm" data-action="toggle-pw" type="button">👁️</button>
            </div>
        </div>
        <div class="route-options">
            <label class="route-option">兼容模式
                <select class="form-select" data-field="thinking_mode" style="width: auto;">${thinkingOptions}</select>
            </label>
            <label class="route-option"><input type="checkbox" data-field="enable_thinking"${config.enable_thinking === true ? ' checked' : ''}>原生 Thinking</label>
            <label class="route-option"><input type="checkbox" data-field="use_xml_tools"${config.use_xml_tools === true ? ' checked' : ''}>XML 工具</label>
            <label class="route-option"><input type="checkbox" data-field="supports_images"${supportsImages ? ' checked' : ''}>支持图片</label>
            <label class="route-option">Budget
                <input type="number" class="form-input" data-field="thinking_budget_tokens" value="${escapeAttr(config.thinking_budget_tokens ?? '')}" placeholder="--" style="width: 90px;">
            </label>
        </div>
    </div>`;
}

function addRouteCard() {
    const container = rootEl.querySelector('#route-cards');
    const addCard = container.querySelector('.add-card');
    const wrapper = document.createElement('div');
    wrapper.innerHTML = buildCardHtml('', { base_url: 'http://localhost:8317/v1', actual_model: '' });
    const newCard = wrapper.firstElementChild;
    container.insertBefore(newCard, addCard);
    markDirty(DIRTY_KEY, '模型路由');
    newCard.querySelector('[data-field="name"]').focus();
}

// ===== 模型列表拉取 =====

function setModelStatus(card, message = '', type = 'info') {
    const statusEl = card.querySelector('[data-role="model-status"]');
    if (!statusEl) return;
    if (!message) {
        statusEl.style.display = 'none';
        statusEl.textContent = '';
        return;
    }
    statusEl.style.display = 'block';
    statusEl.textContent = message;
    statusEl.style.color = type === 'success' ? 'var(--success)' : type === 'error' ? 'var(--danger)' : 'var(--text-dim)';
}

function syncNameFromModel(card, nextModel, previousModel = '') {
    const nameInput = card.querySelector('[data-field="name"]');
    if (!nameInput || !nextModel) return;
    const currentName = nameInput.value.trim();
    if (!currentName || currentName === previousModel.trim()) {
        nameInput.value = nextModel.trim();
    }
}

function populateModelOptions(card, models) {
    const select = card.querySelector('[data-role="model-select"]');
    const input = card.querySelector('[data-field="actual_model"]');
    if (!select || !input) return;
    const currentValue = input.value.trim();
    const unique = [...new Set((models || []).map((m) => String(m).trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    select._allModels = unique;  // 缓存完整列表，供过滤框重建选项

    // datalist：输入实际模型 ID 时原生过滤补全
    const datalist = card.querySelector('datalist');
    if (datalist) {
        datalist.innerHTML = unique.map((m) => `<option value="${escapeAttr(m)}">`).join('');
    }

    // 模型过滤框：有列表时显示并重置
    const filterInput = card.querySelector('[data-role="model-filter"]');
    if (filterInput) {
        filterInput.value = '';
        filterInput.style.display = unique.length > 0 ? '' : 'none';
    }

    let options = '<option value="">手动输入或选择模型</option>';
    if (currentValue && !unique.includes(currentValue)) {
        options += `<option value="${escapeAttr(currentValue)}">${escapeHtml(currentValue)}（当前）</option>`;
    }
    options += unique.map((m) => `<option value="${escapeAttr(m)}">${escapeHtml(m)}</option>`).join('');
    select.innerHTML = options;

    if (currentValue) {
        select.value = currentValue;
    } else if (unique.length > 0) {
        select.value = unique[0];
        input.value = unique[0];
        syncNameFromModel(card, unique[0]);
        markDirty(DIRTY_KEY, '模型路由');
    }
}

function isValidHttpUrl(value) {
    try {
        const url = new URL(String(value || '').trim());
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch {
        return false;
    }
}

async function fetchModels(button) {
    const card = button.closest('.route-card');
    if (!card) return;

    const baseUrl = card.querySelector('[data-field="base_url"]')?.value?.trim() || '';
    const routeName = card.querySelector('[data-field="name"]')?.value?.trim() || '';
    const apiKey = card.querySelector('[data-field="api_key"]')?.value || '';

    if (!baseUrl) {
        setModelStatus(card, '请先填写 API 地址', 'error');
        return;
    }
    if (!isValidHttpUrl(baseUrl)) {
        setModelStatus(card, 'API 地址格式无效，需为 http:// 或 https:// 地址', 'error');
        return;
    }

    const cacheKey = baseUrl.replace(/\/+$/, '');
    const cache = getModelsCache();
    const cached = cache[cacheKey];
    if (cached && Array.isArray(cached.models)) {
        populateModelOptions(card, cached.models);
        setModelStatus(card, `已从本地缓存加载 ${cached.models.length} 个模型（${new Date(cached.at).toLocaleString()}）`, 'success');
        return;
    }

    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = '加载中...';
    setModelStatus(card, '正在从远端接口获取模型列表...', 'info');

    try {
        const result = await apiCall('/config/model_routes/models', 'POST', {
            base_url: baseUrl,
            route_name: routeName,
            api_key: apiKey,
        });
        if (result && result.success && Array.isArray(result.models)) {
            populateModelOptions(card, result.models);
            cache[cacheKey] = { models: [...result.models], at: new Date().toISOString() };
            savePref('routeModelsCache', cache);
            setModelStatus(card, `已获取 ${result.models.length} 个模型（已缓存到本地）`, 'success');
            showToast(`已获取 ${result.models.length} 个模型`, 'success');
        } else {
            setModelStatus(card, `获取模型失败：${result?.error || '未知错误'}`, 'error');
        }
    } finally {
        button.disabled = false;
        button.textContent = originalText;
    }
}

// ===== 保存 =====

async function saveRoutes() {
    const newRoutes = {};
    const cards = rootEl.querySelectorAll('.route-card:not(.add-card)');
    const usedNames = new Set();

    for (const card of cards) {
        const nameInput = card.querySelector('[data-field="name"]');
        const baseUrlInput = card.querySelector('[data-field="base_url"]');
        const name = nameInput?.value?.trim() || '';
        const baseUrl = baseUrlInput?.value?.trim() || '';

        if (!name) continue;

        if (usedNames.has(name)) {
            nameInput.focus();
            return showToast(`模型名称重复：${name}`, 'error');
        }
        usedNames.add(name);

        if (!baseUrl) {
            baseUrlInput.focus();
            return showToast(`模型 ${name} 缺少 API 地址`, 'error');
        }
        if (!isValidHttpUrl(baseUrl)) {
            baseUrlInput.focus();
            return showToast(`模型 ${name} 的 API 地址格式无效`, 'error');
        }

        const thinkingVal = card.querySelector('[data-field="thinking_mode"]')?.value;
        const routeConfig = {
            base_url: baseUrl,
            api_key: card.querySelector('[data-field="api_key"]')?.value || '',
            actual_model: card.querySelector('[data-field="actual_model"]')?.value?.trim() || name,
            thinking_mode: thinkingVal === 'true' ? true : thinkingVal === 'false' ? false : 'auto',
        };

        if (card.querySelector('[data-field="enable_thinking"]')?.checked) routeConfig.enable_thinking = true;
        if (card.querySelector('[data-field="use_xml_tools"]')?.checked) routeConfig.use_xml_tools = true;
        if (card.querySelector('[data-field="supports_images"]')?.checked) routeConfig.supports_images = true;

        const budgetRaw = card.querySelector('[data-field="thinking_budget_tokens"]')?.value;
        if (budgetRaw) {
            const budget = parseInt(budgetRaw, 10);
            if (Number.isFinite(budget)) routeConfig.thinking_budget_tokens = budget;
        }

        newRoutes[name] = routeConfig;
    }

    if (Object.keys(newRoutes).length === 0) {
        return showToast('没有可保存的模型路由', 'error');
    }

    // 保留 _default 路由
    if (routesData._default) newRoutes._default = routesData._default;

    const result = await apiCall('/config/model_routes', 'PUT', { value: newRoutes });
    if (result && result.success) {
        routesData = newRoutes;
        clearDirty(DIRTY_KEY);
        renderCards();
        showToast(result.message || '路由配置已保存并已热更新生效', 'success');
    } else {
        showToast('保存失败: ' + (result?.error || '未知错误'), 'error');
    }
}

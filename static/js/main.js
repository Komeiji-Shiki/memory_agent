/**
 * 管理面板入口
 * - 渲染侧边栏（分组导航 + 状态小部件 + 底部工具栏）
 * - 初始化主题 / 路由 / 命令面板 / 折叠委托
 */

import { apiCall } from './core/api.js';
import { initTheme, toggleThemeMode, getTheme, setAccent, ACCENT_PRESETS } from './core/theme.js';
import { registerPages, initRouter, navigate } from './core/router.js';
import { initPalette, togglePalette } from './core/palette.js';
import { initCollapsibles, showModal, closeModal, escapeHtml } from './core/ui.js';
import { loadPref, savePref } from './core/store.js';
import { GROUPS, allPages } from './pages/index.js';
import { registerFeatureCommands } from './commands.js';

// ===== 侧边栏导航渲染 =====
function renderNav() {
    const nav = document.getElementById('nav-menu');
    let html = '';
    for (const group of GROUPS) {
        const pagesInGroup = allPages.filter((p) => p.group === group.id);
        if (pagesInGroup.length === 0) continue;
        if (group.label) {
            html += `<li class="nav-group-label">${escapeHtml(group.label)}</li>`;
        }
        for (const page of pagesInGroup) {
            html += `<li class="nav-item" data-page="${page.id}" title="${escapeHtml(page.title)}">
                <i>${page.icon}</i><span class="nav-label">${escapeHtml(page.title)}</span>
            </li>`;
        }
    }
    nav.innerHTML = html;
    nav.addEventListener('click', (e) => {
        const item = e.target.closest('.nav-item');
        if (item) navigate(item.dataset.page);
    });
}

// ===== 侧边栏状态小部件 =====
let lastStatsRefresh = 0;

export async function refreshSidebarStats() {
    lastStatsRefresh = Date.now();
    const statusEl = document.getElementById('memory-status');
    const lastEl = document.getElementById('last-interaction');
    const stats = await apiCall('/stats');
    if (stats && !stats.error) {
        statusEl.textContent = `${stats.diary_count || 0} 条日记`;
        lastEl.textContent = stats.last_interaction ? `上次: ${stats.last_interaction}` : '--';
    } else {
        statusEl.textContent = '连接失败';
    }
}

// ===== 侧边栏折叠 =====
function initSidebarToggle() {
    const collapsed = loadPref('sidebarCollapsed', false);
    if (collapsed) document.body.classList.add('sidebar-collapsed');

    document.getElementById('sidebar-toggle').addEventListener('click', () => {
        const isCollapsed = document.body.classList.toggle('sidebar-collapsed');
        savePref('sidebarCollapsed', isCollapsed);
    });
    // 移动端汉堡按钮
    document.getElementById('mobile-menu-btn').addEventListener('click', () => {
        document.body.classList.toggle('sidebar-open');
    });
    // 点击遮罩收起
    document.getElementById('sidebar-backdrop').addEventListener('click', () => {
        document.body.classList.remove('sidebar-open');
    });
}

// ===== 主题工具栏 =====
function initThemeControls() {
    const modeBtn = document.getElementById('theme-mode-btn');
    const syncModeIcon = () => {
        modeBtn.textContent = getTheme().mode === 'dark' ? '🌙' : '☀️';
        modeBtn.title = getTheme().mode === 'dark' ? '切换到浅色模式' : '切换到深色模式';
    };
    // 图标同步统一走 themechange（按钮、命令面板等任何途径切换都覆盖）
    modeBtn.addEventListener('click', toggleThemeMode);
    document.addEventListener('themechange', syncModeIcon);
    syncModeIcon();

    document.getElementById('accent-btn').addEventListener('click', showAccentPicker);
}

function showAccentPicker() {
    const { accent } = getTheme();
    const presetsHtml = ACCENT_PRESETS.map((p) =>
        `<button class="accent-swatch${p.color === accent ? ' active' : ''}" data-color="${p.color}"
            style="background:${p.color}" title="${escapeHtml(p.name)}"></button>`
    ).join('');
    const modal = showModal('🎨 主题色', `
        <div class="accent-picker">
            <div class="accent-presets">${presetsHtml}</div>
            <div class="accent-custom">
                <label>自定义：</label>
                <input type="color" id="accent-custom-input" value="${accent}">
            </div>
        </div>`);
    modal.querySelectorAll('.accent-swatch').forEach((btn) => {
        btn.addEventListener('click', () => {
            setAccent(btn.dataset.color);
            closeModal();
        });
    });
    modal.querySelector('#accent-custom-input').addEventListener('change', (e) => {
        setAccent(e.target.value);
    });
}

// ===== 启动 =====
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    registerPages(allPages);
    renderNav();
    initSidebarToggle();
    initThemeControls();
    initCollapsibles();
    initPalette();
    registerFeatureCommands({ refreshSidebarStats });
    document.getElementById('palette-btn').addEventListener('click', togglePalette);
    document.getElementById('stats-refresh-btn').addEventListener('click', refreshSidebarStats);

    // 切页时顺带刷新侧边栏统计（15 秒节流，请求很轻）
    document.addEventListener('pagechange', () => {
        if (Date.now() - lastStatsRefresh > 15000) refreshSidebarStats();
    });

    initRouter(document.getElementById('main-content'));
    refreshSidebarStats();
    console.log('[LifeBook] 面板初始化完成');
});

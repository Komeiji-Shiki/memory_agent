/**
 * 命令面板功能命令（集中注册，不侵入各页面文件）
 * - 页面功能命令 = 导航到目标页 + 点击页内 data-action 按钮（按钮是稳定接口）
 * - ⚠️ 页面显隐制、DOM 常驻：选择器必须限定在 #page-<id> 容器内
 *   （memory / rag / graphiti 三页都存在 data-action="rebuild-index"）
 */

import { navigate, getCurrentPageId } from './core/router.js';
import { registerCommands } from './core/palette.js';
import { toggleThemeMode } from './core/theme.js';
import { apiCall } from './core/api.js';
import { showToast, confirmDialog } from './core/ui.js';

/**
 * 导航到目标页后对页内元素执行操作
 * - 已在目标页时立即执行；否则等待 router 的 pagechange 事件（确定性，无定时猜测）
 * - 若导航被脏数据拦截（用户取消离开），pagechange 不会到来，超时后静默放弃，
 *   避免误触当前页的同名按钮
 */
function runOnPage(pageId, fn) {
    const exec = () => {
        const container = document.getElementById('page-' + pageId);
        if (container) fn(container);
    };
    if (getCurrentPageId() === pageId) {
        exec();
        return;
    }
    const onChange = (e) => {
        document.removeEventListener('pagechange', onChange);
        if (e.detail.id === pageId) exec();
        // 导航到了其他页面（如被拦截后用户改去别处）：放弃
    };
    document.addEventListener('pagechange', onChange);
    navigate(pageId);
    setTimeout(() => document.removeEventListener('pagechange', onChange), 5000);
}

/** 点击目标页内的 data-action 按钮 */
function clickPageAction(pageId, action) {
    runOnPage(pageId, (container) => {
        container.querySelector(`[data-action="${action}"]`)?.click();
    });
}

/** 轮询等待服务恢复（重启后） */
async function waitForServer(maxWait = 30000) {
    const start = Date.now();
    while (Date.now() - start < maxWait) {
        await new Promise((r) => setTimeout(r, 1500));
        try {
            const res = await fetch('/api/memory/stats', { cache: 'no-store' });
            if (res.ok) return true;
        } catch (_) { /* 服务尚未恢复，继续等待 */ }
    }
    return false;
}

/** 重启服务：确认 → 调接口 → 等待恢复 → 刷新页面 */
async function restartService() {
    const ok = await confirmDialog(
        '确定要重启代理服务吗？重启期间（约 5 秒）所有请求会中断。',
        { title: '重启服务', danger: true, okText: '重启' }
    );
    if (!ok) return;

    const res = await apiCall('/system/restart', 'POST');
    if (res.error) {
        showToast(`重启请求失败: ${res.error}`, 'error');
        return;
    }
    showToast('服务重启中，等待恢复…', 'info', 8000);
    const recovered = await waitForServer();
    if (recovered) {
        showToast('服务已恢复，即将刷新页面', 'success');
        setTimeout(() => location.reload(), 800);
    } else {
        showToast('等待超时，请手动刷新页面确认服务状态', 'error', 10000);
    }
}

/**
 * 注册全部功能命令
 * @param {{ refreshSidebarStats?: () => void }} deps 由 main.js 注入，避免循环依赖
 */
export function registerFeatureCommands({ refreshSidebarStats } = {}) {
    registerCommands([
        {
            id: 'cmd:global-search',
            title: '🔍 全局搜索',
            group: '功能命令',
            keywords: ['search', '搜索', '全局', 'global', '查找'],
            action: () => runOnPage('search', (c) => c.querySelector('#global-search-input')?.focus()),
        },
        {
            id: 'cmd:create-backup',
            title: '📦 创建新备份',
            group: '功能命令',
            keywords: ['backup', '备份', '创建', 'create'],
            action: () => clickPageAction('backup', 'create-backup'),
        },
        {
            id: 'cmd:rebuild-keyword-index',
            title: '🔄 重建关键词索引（记忆库）',
            group: '功能命令',
            keywords: ['rebuild', 'index', '索引', '关键词', 'keyword', 'memory', '重建'],
            action: () => clickPageAction('memory', 'rebuild-index'),
        },
        {
            id: 'cmd:rebuild-rag-index',
            title: '🔮 RAG：重建语义索引',
            group: '功能命令',
            keywords: ['rag', 'rebuild', 'index', '索引', '语义', '重建'],
            action: () => clickPageAction('rag', 'rebuild-index'),
        },
        {
            id: 'cmd:check-missing-summary',
            title: '📝 检测缺失的总结',
            group: '功能命令',
            keywords: ['summary', '总结', '缺失', 'check', 'missing', '检测'],
            action: () => clickPageAction('summary', 'check-missing'),
        },
        {
            id: 'cmd:graphiti-sync-markdown',
            title: '🔗 Graphiti：同步 Markdown（LLM 抽取）',
            group: '功能命令',
            keywords: ['graphiti', 'sync', '同步', 'markdown', 'llm', '图谱'],
            action: () => clickPageAction('graphiti', 'sync-markdown'),
        },
        {
            id: 'cmd:toggle-theme',
            title: '🌓 切换深色 / 浅色主题',
            group: '功能命令',
            keywords: ['theme', '主题', 'dark', 'light', '深色', '浅色', '明暗', '切换'],
            action: () => toggleThemeMode(),
        },
        {
            id: 'cmd:refresh-sidebar-stats',
            title: '📊 刷新侧边栏统计',
            group: '功能命令',
            keywords: ['refresh', 'stats', '统计', '刷新', '侧边栏', 'sidebar'],
            action: () => { if (refreshSidebarStats) refreshSidebarStats(); },
        },
        {
            id: 'cmd:restart-service',
            title: '♻️ 重启代理服务（加载新后端代码）',
            group: '功能命令',
            keywords: ['restart', '重启', 'reload', '服务', 'server', '后端'],
            action: () => restartService(),
        },
    ]);
}

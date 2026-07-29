/**
 * Hash 路由
 * - #/pageId 形式；刷新后停留当前页；无 hash 时恢复上次访问页
 * - 页面首次进入时渲染到独立容器，之后切换仅显隐（保留页面内状态，如图谱实例）
 * - 切换前检查未保存修改（store 脏数据注册表），异步确认
 * - 生命周期：render(container) 一次性；onEnter() 每次进入；onLeave() 每次离开
 */

import { isDirty, dirtyLabels, clearAllDirty, loadPref, savePref } from './store.js';
import { confirmDialog } from './ui.js';

const pages = new Map();          // id -> page 模块
const containers = new Map();     // id -> 已渲染的容器元素
let mainEl = null;                // 页面容器父元素
let currentId = null;
let suppressHashHandler = false;  // 回退 hash 时避免重入

export function registerPages(pageList) {
    for (const page of pageList) pages.set(page.id, page);
}

export function getPages() {
    return [...pages.values()];
}

export function getCurrentPageId() {
    return currentId;
}

/** 程序化导航 */
export function navigate(id) {
    if (!pages.has(id)) return;
    location.hash = '#/' + id;
}

export function initRouter(mainContainer) {
    mainEl = mainContainer;
    window.addEventListener('hashchange', onHashChange);

    // 初始页：hash > 上次访问 > 第一个注册页
    let initial = parseHash();
    if (!initial || !pages.has(initial)) {
        initial = loadPref('lastPage');
    }
    if (!initial || !pages.has(initial)) {
        initial = pages.keys().next().value;
    }
    suppressHashHandler = true;
    location.hash = '#/' + initial;
    suppressHashHandler = false;
    activate(initial);
}

function parseHash() {
    const m = location.hash.match(/^#\/([\w-]+)/);
    return m ? m[1] : null;
}

async function onHashChange() {
    if (suppressHashHandler) return;
    const targetId = parseHash();
    if (!targetId || !pages.has(targetId) || targetId === currentId) return;

    // 未保存修改拦截
    if (isDirty()) {
        const ok = await confirmDialog(
            `以下修改尚未保存：\n${dirtyLabels().join('、')}\n\n离开将丢弃这些修改，确定吗？`,
            { title: '有未保存的修改', danger: true, okText: '丢弃并离开' }
        );
        if (!ok) {
            suppressHashHandler = true;
            location.hash = '#/' + currentId;
            // hashchange 是异步派发的，下一轮宏任务再解除
            setTimeout(() => { suppressHashHandler = false; }, 0);
            return;
        }
        // 确认离开 = 放弃所有未保存修改，避免之后每次切页重复拦截
        clearAllDirty();
    }
    activate(targetId);
}

function activate(id) {
    const page = pages.get(id);
    if (!page) return;

    // 离开旧页
    if (currentId && currentId !== id) {
        const oldPage = pages.get(currentId);
        const oldEl = containers.get(currentId);
        if (oldEl) oldEl.classList.remove('active');
        if (oldPage && typeof oldPage.onLeave === 'function') {
            try { oldPage.onLeave(); } catch (e) { console.error(`[router] ${currentId}.onLeave`, e); }
        }
    }

    // 首次进入：渲染
    let el = containers.get(id);
    if (!el) {
        el = document.createElement('div');
        el.className = 'page';
        el.id = 'page-' + id;
        mainEl.appendChild(el);
        containers.set(id, el);
        try {
            page.render(el);
        } catch (e) {
            console.error(`[router] ${id}.render`, e);
            el.innerHTML = `<div class="alert alert-danger"><span>❌</span><div>页面渲染失败: ${e.message}</div></div>`;
        }
    }
    el.classList.add('active');
    currentId = id;
    savePref('lastPage', id);

    // 同步侧边栏高亮
    document.querySelectorAll('.nav-item').forEach((item) => {
        item.classList.toggle('active', item.dataset.page === id);
    });
    // 移动端：切换页面后收起侧边栏
    document.body.classList.remove('sidebar-open');

    if (typeof page.onEnter === 'function') {
        try { page.onEnter(); } catch (e) { console.error(`[router] ${id}.onEnter`, e); }
    }

    // 页面激活完成事件（供命令面板等外部逻辑确定性等待，替代定时猜测）
    document.dispatchEvent(new CustomEvent('pagechange', { detail: { id } }));
}

/**
 * 全局状态
 * - 脏数据注册表：任何页面有未保存修改时登记，路由切换/关闭页面前统一提示
 * - 轻量键值状态存取（localStorage 包装）
 */

const dirtyMap = new Map();

/** 登记未保存修改。key 建议用 '页面id:区块'，label 用于提示文案 */
export function markDirty(key, label) {
    dirtyMap.set(key, label || key);
    updateDirtyIndicator();
}

/** 清除某项未保存标记（保存成功或放弃修改后调用） */
export function clearDirty(key) {
    dirtyMap.delete(key);
    updateDirtyIndicator();
}

/** 清除某前缀下所有未保存标记（页面级清理） */
export function clearDirtyByPrefix(prefix) {
    for (const key of [...dirtyMap.keys()]) {
        if (key.startsWith(prefix)) dirtyMap.delete(key);
    }
    updateDirtyIndicator();
}

/** 清除全部未保存标记（用户确认放弃修改后调用） */
export function clearAllDirty() {
    dirtyMap.clear();
    updateDirtyIndicator();
}

export function isDirty() {
    return dirtyMap.size > 0;
}

export function dirtyLabels() {
    return [...dirtyMap.values()];
}

/** 侧边栏"未保存"指示器同步 */
function updateDirtyIndicator() {
    const el = document.getElementById('dirty-indicator');
    if (!el) return;
    if (dirtyMap.size > 0) {
        el.style.display = '';
        el.title = '未保存：' + [...dirtyMap.values()].join('、');
    } else {
        el.style.display = 'none';
    }
}

// 关闭/刷新页面前的原生提示
window.addEventListener('beforeunload', (event) => {
    if (isDirty()) {
        event.preventDefault();
        event.returnValue = '';
    }
});

// ===== localStorage 简单包装 =====
const PREFIX = 'lifebook.';

export function loadPref(key, fallback = null) {
    try {
        const raw = localStorage.getItem(PREFIX + key);
        return raw === null ? fallback : JSON.parse(raw);
    } catch {
        return fallback;
    }
}

export function savePref(key, value) {
    try {
        localStorage.setItem(PREFIX + key, JSON.stringify(value));
    } catch { /* 存储满等异常忽略 */ }
}

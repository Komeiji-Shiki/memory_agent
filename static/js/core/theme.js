/**
 * 主题管理
 * - 深色（默认）/ 浅色模式，通过 <html data-theme="dark|light"> 切换
 * - 主题色（accent）自定义，通过 CSS 变量 --accent 注入，衍生色由 CSS color-mix 计算
 * - localStorage 持久化
 */

import { loadPref, savePref } from './store.js';

export const ACCENT_PRESETS = [
    { name: '科技蓝', color: '#2aa8ff' },
    { name: '翡翠绿', color: '#10b981' },
    { name: '霓虹紫', color: '#a78bfa' },
    { name: '曦光橙', color: '#fb923c' },
    { name: '樱花粉', color: '#f472b6' },
    { name: '暗夜红', color: '#ef4444' },
];

const DEFAULT_THEME = { mode: 'dark', accent: '#2aa8ff' };

let current = { ...DEFAULT_THEME };

export function initTheme() {
    current = { ...DEFAULT_THEME, ...(loadPref('theme', {}) || {}) };
    applyTheme();
}

export function getTheme() {
    return { ...current };
}

export function setThemeMode(mode) {
    current.mode = mode === 'light' ? 'light' : 'dark';
    applyTheme();
    savePref('theme', current);
}

export function toggleThemeMode() {
    setThemeMode(current.mode === 'dark' ? 'light' : 'dark');
    return current.mode;
}

export function setAccent(color) {
    if (!/^#[0-9a-fA-F]{6}$/.test(color)) return;
    current.accent = color;
    applyTheme();
    savePref('theme', current);
}

function applyTheme() {
    const root = document.documentElement;
    root.dataset.theme = current.mode;
    root.style.setProperty('--accent', current.accent);
    // 同步浏览器 UI 色
    let meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) {
        meta = document.createElement('meta');
        meta.name = 'theme-color';
        document.head.appendChild(meta);
    }
    meta.content = current.mode === 'dark' ? '#090e16' : '#f4f7fb';
    // 通知图表等组件重绘
    document.dispatchEvent(new CustomEvent('themechange', { detail: { ...current } }));
}

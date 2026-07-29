/**
 * 命令面板（Ctrl+K / Cmd+K）
 * - 命令来源：页面导航（自动）+ 各页面注册的功能项
 * - 输入过滤（标题 + 关键词模糊匹配），↑↓ 选择，Enter 执行，Esc 关闭
 */

import { escapeHtml } from './ui.js';
import { getPages, navigate } from './router.js';

const extraCommands = [];   // {id, title, group, keywords, action}
let paletteEl = null;
let activeIndex = 0;
let filtered = [];

/** 页面模块可注册额外功能命令 */
export function registerCommands(commands) {
    for (const cmd of commands) extraCommands.push(cmd);
}

export function initPalette() {
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            togglePalette();
        }
        if (e.key === 'Escape' && paletteEl) closePalette();
    });
}

function allCommands() {
    const navCommands = getPages().map((p) => ({
        id: 'nav:' + p.id,
        title: `${p.icon} 前往：${p.title}`,
        group: '页面导航',
        keywords: [p.id, p.title],
        action: () => navigate(p.id),
    }));
    return [...navCommands, ...extraCommands];
}

export function togglePalette() {
    if (paletteEl) { closePalette(); return; }
    openPalette();
}

function openPalette() {
    paletteEl = document.createElement('div');
    paletteEl.className = 'palette-overlay';
    paletteEl.innerHTML = `
        <div class="palette-box">
            <input type="text" class="palette-input" placeholder="输入命令或页面名称... （↑↓ 选择，Enter 执行）">
            <div class="palette-results"></div>
        </div>`;
    document.body.appendChild(paletteEl);

    const input = paletteEl.querySelector('.palette-input');
    const results = paletteEl.querySelector('.palette-results');

    const refresh = () => {
        const q = input.value.trim().toLowerCase();
        filtered = allCommands().filter((cmd) => {
            if (!q) return true;
            const haystack = (cmd.title + ' ' + (cmd.keywords || []).join(' ')).toLowerCase();
            return q.split(/\s+/).every((word) => haystack.includes(word));
        });
        activeIndex = 0;
        renderResults(results);
    };

    input.addEventListener('input', refresh);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            activeIndex = Math.min(activeIndex + 1, filtered.length - 1);
            renderResults(results);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            activeIndex = Math.max(activeIndex - 1, 0);
            renderResults(results);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            runCommand(filtered[activeIndex]);
        }
    });

    paletteEl.addEventListener('click', (e) => {
        if (e.target === paletteEl) closePalette();
        const item = e.target.closest('.palette-item');
        if (item) runCommand(filtered[Number(item.dataset.index)]);
    });

    refresh();
    input.focus();
}

function renderResults(container) {
    if (filtered.length === 0) {
        container.innerHTML = '<div class="palette-empty">没有匹配的命令</div>';
        return;
    }
    let html = '';
    let lastGroup = null;
    filtered.forEach((cmd, i) => {
        if (cmd.group !== lastGroup) {
            html += `<div class="palette-group">${escapeHtml(cmd.group)}</div>`;
            lastGroup = cmd.group;
        }
        html += `<div class="palette-item${i === activeIndex ? ' active' : ''}" data-index="${i}">${escapeHtml(cmd.title)}</div>`;
    });
    container.innerHTML = html;
    const activeEl = container.querySelector('.palette-item.active');
    if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
}

function runCommand(cmd) {
    if (!cmd) return;
    closePalette();
    try { cmd.action(); } catch (e) { console.error('[palette]', cmd.id, e); }
}

function closePalette() {
    if (paletteEl) {
        paletteEl.remove();
        paletteEl = null;
    }
}

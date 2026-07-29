/**
 * 知识图谱页（壳）
 * - tab 切换：本地图谱 / Graphiti 图谱（懒加载）
 * - themechange 时通知已加载的图谱重绘
 * 子模块：graph-local.js（本地）、graph-graphiti.js（Graphiti）
 */

import { bindActions } from '../core/ui.js';
import { localGraphTab } from './graph-local.js';
import { graphitiGraphTab } from './graph-graphiti.js';

let rootEl = null;
let currentTab = 'local';
const loaded = { local: false, graphiti: false };
const tabs = { local: localGraphTab, graphiti: graphitiGraphTab };

export const graphPage = {
    id: 'graph',
    title: '知识图谱',
    icon: '🕸️',
    group: 'memory',

    render(container) {
        rootEl = container;
        container.innerHTML = `
            <div class="page-header">
                <h2>🕸️ 知识图谱</h2>
                <p>本地 Markdown 图谱与 Graphiti 时序知识图谱</p>
            </div>

            <div class="tab-bar" id="graph-tab-bar">
                <button class="tab-item active" data-action="switch-tab" data-tab="local">🗂️ 本地图谱</button>
                <button class="tab-item" data-action="switch-tab" data-tab="graphiti">⏳ Graphiti 图谱</button>
            </div>

            <div class="tab-pane active" id="graph-tab-local"></div>
            <div class="tab-pane" id="graph-tab-graphiti"></div>
        `;

        localGraphTab.render(container.querySelector('#graph-tab-local'));
        graphitiGraphTab.render(container.querySelector('#graph-tab-graphiti'));

        bindActions(container.querySelector('#graph-tab-bar'), {
            'switch-tab': (t) => switchTab(t.dataset.tab),
        });

        // 主题切换时重绘已加载的图谱（vis-network 不识别 CSS 变量）
        document.addEventListener('themechange', () => {
            if (loaded.local) localGraphTab.redraw();
            if (loaded.graphiti) graphitiGraphTab.redraw();
        });
    },

    onEnter() {
        ensureLoaded(currentTab);
    },
};

function switchTab(tab) {
    if (!tabs[tab] || tab === currentTab) return;
    currentTab = tab;

    rootEl.querySelectorAll('#graph-tab-bar .tab-item').forEach((el) => {
        el.classList.toggle('active', el.dataset.tab === tab);
    });
    rootEl.querySelector('#graph-tab-local').classList.toggle('active', tab === 'local');
    rootEl.querySelector('#graph-tab-graphiti').classList.toggle('active', tab === 'graphiti');

    ensureLoaded(tab);
}

function ensureLoaded(tab) {
    if (loaded[tab]) return;
    loaded[tab] = true;
    tabs[tab].load();
}

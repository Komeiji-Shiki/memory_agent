/**
 * UI 组件工厂
 * - Toast 队列通知
 * - Modal 弹窗 / confirm / prompt（替代原生阻塞对话框）
 * - HTML 转义
 * - 常用片段（loading / 空态 / 错误）
 * - 事件委托辅助
 */

// ===== HTML 转义 =====
export function escapeHtml(text, convertNewlines = false) {
    if (text === null || text === undefined || text === '') return '';
    let result = String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    if (convertNewlines) result = result.replace(/\n/g, '<br>');
    return result;
}

/** 转义用于 value="" 等 HTML 属性值 */
export function escapeAttr(str) {
    return escapeHtml(str);
}

// ===== Toast 队列 =====
const TOAST_ICONS = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };

export function showToast(message, type = 'info', duration = 3200) {
    let stack = document.getElementById('toast-stack');
    if (!stack) {
        stack = document.createElement('div');
        stack.id = 'toast-stack';
        document.body.appendChild(stack);
    }
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span class="toast-icon">${TOAST_ICONS[type] || TOAST_ICONS.info}</span>` +
        `<span class="toast-msg">${escapeHtml(message)}</span>` +
        `<button class="toast-close" aria-label="关闭">&times;</button>`;
    toast.querySelector('.toast-close').addEventListener('click', () => dismissToast(toast));
    stack.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    if (duration > 0) setTimeout(() => dismissToast(toast), duration);
    return toast;
}

function dismissToast(toast) {
    if (!toast.isConnected) return;
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 250);
}

// ===== Modal =====

/**
 * 显示弹窗
 * @param {string} title - 标题（可为空字符串）
 * @param {string} content - 主体 HTML
 * @param {object} [opts]
 * @param {'normal'|'large'|'xlarge'} [opts.size]
 * @param {string} [opts.footer] - 底部按钮区 HTML
 * @param {Function} [opts.onClose]
 * @returns {HTMLElement} modal 根元素
 */
export function showModal(title, content, opts = {}) {
    closeModal();
    const size = opts.size || 'normal';
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'app-modal';
    const headerHtml = title
        ? `<div class="modal-header"><h3>${title}</h3><button class="modal-x" data-modal-close aria-label="关闭">&times;</button></div>`
        : '';
    const footerHtml = opts.footer ? `<div class="modal-footer">${opts.footer}</div>` : '';
    modal.innerHTML = `
        <div class="modal-backdrop">
            <div class="modal-content modal-${size}">
                ${headerHtml}
                <div class="modal-body">${content}</div>
                ${footerHtml}
            </div>
        </div>`;
    document.body.appendChild(modal);

    const backdrop = modal.querySelector('.modal-backdrop');
    backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) closeModal();
    });
    modal.addEventListener('click', (e) => {
        if (e.target.closest('[data-modal-close]')) closeModal();
    });
    modal._onClose = opts.onClose || null;

    // Esc 关闭
    const escHandler = (e) => {
        if (e.key === 'Escape') closeModal();
    };
    document.addEventListener('keydown', escHandler);
    modal._escHandler = escHandler;
    return modal;
}

export function closeModal() {
    document.querySelectorAll('.modal-overlay').forEach((modal) => {
        if (modal._escHandler) document.removeEventListener('keydown', modal._escHandler);
        if (typeof modal._onClose === 'function') {
            try { modal._onClose(); } catch { /* 忽略回调异常 */ }
        }
        modal.remove();
    });
}

/**
 * 确认对话框（替代原生 confirm）
 * @returns {Promise<boolean>}
 */
export function confirmDialog(message, opts = {}) {
    return new Promise((resolve) => {
        const okClass = opts.danger ? 'btn-danger' : 'btn-primary';
        const modal = showModal(
            opts.title || '确认操作',
            `<div class="confirm-message">${escapeHtml(message, true)}</div>`,
            {
                footer: `<button class="btn" data-act="cancel">${escapeHtml(opts.cancelText || '取消')}</button>
                         <button class="btn ${okClass}" data-act="ok">${escapeHtml(opts.okText || '确定')}</button>`,
                onClose: () => resolve(false),
            }
        );
        modal.querySelector('[data-act="ok"]').addEventListener('click', () => {
            modal._onClose = null;
            closeModal();
            resolve(true);
        });
        modal.querySelector('[data-act="cancel"]').addEventListener('click', () => closeModal());
    });
}

/**
 * 输入对话框（替代原生 prompt）
 * @returns {Promise<string|null>} 取消返回 null
 */
export function promptDialog(message, opts = {}) {
    return new Promise((resolve) => {
        const inputType = opts.type === 'password' ? 'password' : 'text';
        const inputHtml = opts.multiline
            ? `<textarea id="prompt-input" class="form-input" rows="${opts.rows || 6}" placeholder="${escapeAttr(opts.placeholder || '')}">${escapeHtml(opts.defaultValue || '')}</textarea>`
            : `<input id="prompt-input" class="form-input" type="${inputType}" value="${escapeAttr(opts.defaultValue || '')}" placeholder="${escapeAttr(opts.placeholder || '')}">`;
        const modal = showModal(
            opts.title || '请输入',
            `<div class="confirm-message">${escapeHtml(message, true)}</div><div style="margin-top:12px;">${inputHtml}</div>`,
            {
                footer: `<button class="btn" data-act="cancel">取消</button>
                         <button class="btn btn-primary" data-act="ok">确定</button>`,
                onClose: () => resolve(null),
            }
        );
        const input = modal.querySelector('#prompt-input');
        input.focus();
        const submit = () => {
            const value = input.value;
            modal._onClose = null;
            closeModal();
            resolve(value);
        };
        modal.querySelector('[data-act="ok"]').addEventListener('click', submit);
        modal.querySelector('[data-act="cancel"]').addEventListener('click', () => closeModal());
        if (!opts.multiline) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') submit();
            });
        }
    });
}

// ===== 常用片段 =====
export function spinnerHtml(text = '加载中...') {
    return `<div class="loading"><span class="spinner"></span> ${escapeHtml(text)}</div>`;
}

export function emptyHtml(text = '暂无数据') {
    return `<p class="text-dim">${escapeHtml(text)}</p>`;
}

export function errorHtml(text = '加载失败') {
    return `<div class="alert alert-danger"><span>❌</span><div>${escapeHtml(text)}</div></div>`;
}

// ===== 事件委托 =====

/**
 * 在容器上做事件委托
 * @param {HTMLElement} container
 * @param {string} eventType
 * @param {string} selector
 * @param {(e: Event, target: HTMLElement) => void} handler
 */
export function delegate(container, eventType, selector, handler) {
    container.addEventListener(eventType, (e) => {
        const target = e.target.closest(selector);
        if (target && container.contains(target)) handler(e, target);
    });
}

/**
 * data-action 风格委托：容器内所有 [data-action] 元素点击时按 action 名分发。
 * async handler 执行期间自动禁用触发元素（防双击重复提交，
 * 长耗时 LLM 操作尤其必要），完成后自动恢复，页面代码零改动。
 * @param {HTMLElement} container
 * @param {Record<string, (target: HTMLElement, e: Event) => void>} actions
 */
export function bindActions(container, actions) {
    delegate(container, 'click', '[data-action]', (e, target) => {
        const fn = actions[target.dataset.action];
        if (!fn) return;
        e.preventDefault();
        if (target.dataset.busy) return;   // 执行中，忽略重复点击

        const result = fn(target, e);
        if (result && typeof result.then === 'function') {
            target.dataset.busy = '1';
            const canDisable = 'disabled' in target;
            if (canDisable) target.disabled = true;
            target.classList.add('is-busy');
            const restore = () => {
                delete target.dataset.busy;
                if (canDisable) target.disabled = false;
                target.classList.remove('is-busy');
            };
            result.then(restore, restore);
        }
    });
}

/** 折叠面板全局委托（.collapsible-header 点击切换 open） */
export function initCollapsibles(root = document.body) {
    delegate(root, 'click', '.collapsible-header', (e, header) => {
        header.parentElement.classList.toggle('open');
    });
}

/** 下载文本为文件 */
export function downloadText(filename, text, mime = 'text/plain') {
    const blob = new Blob([text], { type: `${mime};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

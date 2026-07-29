/**
 * API 客户端
 * 统一封装 /api/memory 下的请求，以及任意 URL 的 JSON 请求。
 * 约定：网络层错误不抛出，返回 { error: message }，与页面层的错误展示逻辑配合。
 *
 * 认证：管理 API 可能要求密钥（web_api.require_auth 或非本机访问）。
 * 密钥保存在 localStorage，所有请求自动携带 X-API-Key 头；
 * 收到 401 时提示输入密钥并自动重试一次。
 */

import { promptDialog } from './ui.js';

export const API_BASE = '/api/memory';

const ADMIN_KEY_STORAGE = 'lifebook.adminKey';

function getAdminKey() {
    try { return localStorage.getItem(ADMIN_KEY_STORAGE) || ''; } catch { return ''; }
}

/** 设置管理密钥（传空字符串清除） */
export function setAdminKey(key) {
    try {
        if (key) localStorage.setItem(ADMIN_KEY_STORAGE, key.trim());
        else localStorage.removeItem(ADMIN_KEY_STORAGE);
    } catch { /* localStorage 不可用时静默 */ }
}

function authHeaders() {
    const key = getAdminKey();
    return key ? { 'X-API-Key': key } : {};
}

// 401 密钥弹窗：并发请求共享同一次弹窗（页面 onEnter 常并行发多个请求，避免连环弹窗）
let _keyPromptPromise = null;

/** 401 时提示输入密钥（密码框）；返回 Promise<是否拿到了新密钥> */
function promptForKey() {
    if (!_keyPromptPromise) {
        _keyPromptPromise = promptDialog('管理 API 需要访问密钥（将保存在本浏览器中）', {
            title: '🔑 需要访问密钥',
            type: 'password',
            placeholder: 'X-API-Key',
        }).then((entered) => {
            _keyPromptPromise = null;
            if (entered && entered.trim()) {
                setAdminKey(entered.trim());
                return true;
            }
            return false;
        });
    }
    return _keyPromptPromise;
}

/**
 * 调用记忆系统 API
 * @param {string} endpoint - 以 / 开头的端点，如 '/stats'
 * @param {string} [method='GET']
 * @param {object|null} [data=null] - 请求体（自动 JSON 序列化）
 * @returns {Promise<any>} 响应 JSON；失败时返回 { error }
 */
export async function apiCall(endpoint, method = 'GET', data = null) {
    return fetchJson(API_BASE + endpoint, method, data);
}

/**
 * 通用 JSON 请求（用于 /v1/models 等非 /api/memory 前缀的端点）
 */
export async function fetchJson(url, method = 'GET', data = null) {
    try {
        const options = { method, headers: { 'Content-Type': 'application/json', ...authHeaders() } };
        if (data !== null && data !== undefined) options.body = JSON.stringify(data);
        let res = await fetch(url, options);

        // 管理 API 认证失败：提示输入密钥后重试一次
        if (res.status === 401 && url.startsWith(API_BASE) && await promptForKey()) {
            options.headers['X-API-Key'] = getAdminKey();
            res = await fetch(url, options);
        }

        const json = await res.json().catch(() => null);
        if (json === null) {
            return { error: `响应解析失败 (HTTP ${res.status})` };
        }
        if (!res.ok && json.error === undefined) {
            json.error = `HTTP ${res.status}`;
        }
        return json;
    } catch (e) {
        console.error('[API]', url, e);
        return { error: e.message };
    }
}

/**
 * 上传文件（multipart/form-data）
 * @param {string} endpoint - /api/memory 下的端点
 * @param {FormData} formData
 */
export async function apiUpload(endpoint, formData) {
    try {
        let res = await fetch(API_BASE + endpoint, { method: 'POST', body: formData, headers: authHeaders() });
        if (res.status === 401 && await promptForKey()) {
            res = await fetch(API_BASE + endpoint, { method: 'POST', body: formData, headers: authHeaders() });
        }
        return await res.json();
    } catch (e) {
        console.error('[API upload]', endpoint, e);
        return { error: e.message };
    }
}

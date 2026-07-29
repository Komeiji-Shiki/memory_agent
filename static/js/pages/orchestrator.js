/**
 * 消息编排页（壳）
 * 布局骨架与子模块调度。
 * 子模块：orchestrator-sequence.js（序列/组件/预览）、orchestrator-panels.js（预设/绑定/历史/测试/Prefill）
 */

import { initSequenceModule, loadEnabled, loadSequence } from './orchestrator-sequence.js';
import { initPanelsModule, loadPresets, loadBindings, loadHistory, loadPrefill } from './orchestrator-panels.js';
import { isDirty } from '../core/store.js';

export const orchestratorPage = {
    id: 'orchestrator',
    title: '消息编排',
    icon: '🧩',
    group: 'settings',

    render(container) {
        container.innerHTML = `
            <div class="page-header">
                <h2>🧩 消息编排</h2>
                <p>自由编排发送给模型的消息序列（拖拽排序 / 预设 / 模型绑定）</p>
            </div>

            <div class="card">
                <div style="display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
                    <label class="checkbox-label">
                        <input type="checkbox" id="orchestrator-enabled">启用消息编排器
                    </label>
                    <span id="orchestrator-status" class="text-dim"></span>
                </div>
            </div>

            <div class="orchestrator-layout-v2">
                <div class="panel">
                    <div class="card">
                        <div class="card-header"><h3>📋 消息序列</h3></div>
                        <div id="orchestrator-sequence"></div>
                        <h4 style="margin: 15px 0 8px; color: var(--accent);">➕ 添加组件</h4>
                        <div id="component-palette" class="component-grid"></div>
                    </div>
                </div>
                <div class="panel">
                    <div class="card">
                        <div class="card-header"><h3>👁️ 预览</h3></div>
                        <div id="preview-input-area" style="margin-bottom: 12px; padding: 10px; background: var(--surface-2); border-radius: 8px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                <span style="font-weight: 500;">📝 测试消息（可选，留空则仅显示编排结构）</span>
                                <button class="btn btn-sm" data-action="clear-preview-inputs">🗑️ 清空</button>
                            </div>
                            <div style="display: flex; flex-direction: column; gap: 8px;">
                                <div>
                                    <label style="font-size: 12px;" class="text-dim">System（可选）</label>
                                    <input type="text" id="preview-system-content" class="form-input" placeholder="留空则不添加 system 消息" style="font-size: 13px;">
                                </div>
                                <div>
                                    <label style="font-size: 12px;" class="text-dim">User（可选）</label>
                                    <input type="text" id="preview-user-content" class="form-input" placeholder="留空则不添加 user 消息" style="font-size: 13px;">
                                </div>
                            </div>
                            <div style="margin-top: 10px; display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
                                <label style="display: flex; align-items: center; gap: 5px;">
                                    <input type="radio" name="preview-mode" value="simple" checked>结构预览
                                </label>
                                <label style="display: flex; align-items: center; gap: 5px;">
                                    <input type="radio" name="preview-mode" value="full">完整预览（含实际记忆）
                                </label>
                                <button class="btn btn-sm" data-action="refresh-preview" style="margin-left: auto;">🔄 刷新预览</button>
                            </div>
                        </div>
                        <div id="orchestrator-preview"></div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-header"><h3>📂 预设管理</h3></div>
                <div id="orchestrator-presets"></div>
            </div>

            <div class="card">
                <div class="card-header"><h3>🔀 模型绑定</h3></div>
                <div id="orchestrator-bindings"></div>
            </div>

            <div class="card">
                <div class="card-header"><h3>💉 预填充（Prefill）</h3></div>
                <div class="form-group">
                    <label for="prefill-content">预填充内容（作为 assistant 消息的开头注入）</label>
                    <textarea id="prefill-content" rows="5" placeholder="留空表示不启用预填充..."></textarea>
                </div>
                <div class="form-row cols-2">
                    <div class="form-group">
                        <label for="prefill-think-tag">思考闭合标签</label>
                        <input type="text" id="prefill-think-tag" placeholder="&lt;/think&gt;">
                    </div>
                    <div class="form-group">
                        <label for="prefill-model-bindings">生效模型（每行一个）</label>
                        <textarea id="prefill-model-bindings" rows="3" placeholder="deepseek-reasoner&#10;claude-sonnet-4"></textarea>
                    </div>
                </div>
                <button class="btn btn-success" data-action="save-prefill">💾 保存预填充配置</button>
            </div>

            <div class="card">
                <div class="card-header"><h3>🧪 测试发送</h3></div>
                <div class="form-row cols-2">
                    <div class="form-group">
                        <label for="test-model">测试模型</label>
                        <input type="text" id="test-model" placeholder="如 deepseek-chat">
                    </div>
                    <div class="form-group">
                        <label for="test-message">测试消息</label>
                        <input type="text" id="test-message" placeholder="你好" value="你好">
                    </div>
                </div>
                <button class="btn btn-primary" data-action="test-send">🚀 发送测试</button>
                <div id="test-result" style="margin-top: 15px;"></div>
            </div>

            <div class="card">
                <div class="card-header"><h3>⏪ 历史记录</h3></div>
                <div id="orchestrator-history"></div>
            </div>

            <div class="card">
                <div class="card-header"><h3>📦 导入 / 导出</h3></div>
                <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                    <button class="btn" data-action="export-config">📤 导出配置</button>
                    <button class="btn" data-action="import-config">📥 导入配置</button>
                </div>
            </div>
        `;

        initSequenceModule(container);
        initPanelsModule(container);
    },

    onEnter() {
        loadEnabled();
        loadSequence();
        loadPresets();
        loadBindings();
        loadHistory();
        if (!isDirty('orchestrator-prefill')) {
            loadPrefill();
        }
    },
};

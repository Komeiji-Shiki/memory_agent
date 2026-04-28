/**
 * Admin Init - 初始化入口
 * 页面加载时执行的初始化逻辑
 */

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', async function() {
    console.log('[LifeBook] 页面初始化开始');
    
    // 先重建索引确保数据最新（静默执行，不显示状态）
    try {
        await apiCall('/rebuild-index', 'POST');
        console.log('[LifeBook] 索引重建完成');
    } catch (e) {
        console.warn('[LifeBook] 索引重建失败:', e);
    }
    
    // 刷新首页统计（不再重建索引，因为上面已经重建过了）
    refreshStats(false);
    refreshModels();
    
    // 加载配置
    loadConfig();
    
    // 首次加载时也获取 RAG 数据
    loadRagStats();
    loadRagConfig();
    
    console.log('[LifeBook] 页面初始化完成');
});
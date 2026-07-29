/**
 * 页面模块聚合
 * 注册顺序即侧边栏顺序；group 字段决定分组归属。
 */

import { overviewPage } from './overview.js';
import { conversationsPage } from './conversations.js';
import { memoryPage } from './memory.js';
import { summaryPage } from './summary.js';
import { graphPage } from './graph.js';
import { searchPage } from './search.js';
import { configPage } from './config.js';
import { routesPage } from './routes.js';
import { orchestratorPage } from './orchestrator.js';
import { extraPage } from './extra.js';
import { ragPage } from './rag.js';
import { graphitiPage } from './graphiti.js';
import { backupPage } from './backup.js';
import { debugPage } from './debug.js';

export const GROUPS = [
    { id: 'top', label: '' },
    { id: 'memory', label: '记忆' },
    { id: 'settings', label: '配置' },
    { id: 'ops', label: '运维' },
];

export const allPages = [
    overviewPage,       // top
    conversationsPage,  // memory
    memoryPage,         // memory
    summaryPage,        // memory
    graphPage,          // memory
    searchPage,         // memory
    configPage,         // settings
    routesPage,         // settings
    orchestratorPage,   // settings
    extraPage,          // settings
    ragPage,            // settings
    graphitiPage,       // settings
    backupPage,         // ops
    debugPage,          // ops
];

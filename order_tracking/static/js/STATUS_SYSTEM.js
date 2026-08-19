/**
 * ============================================
 * 订单状态统一管理系统 - Key 版本
 * ============================================
 * 核心原则：
 * 1. 所有状态使用英文 key（如 'NEW_ORDER', 'DRAFT_MAKING'）
 * 2. 数据库存储：key
 * 3. 逻辑判断：只用 key，不依赖中文文字
 * 4. 显示文字：通过 STATUS_LABELS 映射获取
 * 5. 新增流程：只需在 status_definitions.py 添加一个 key + 配置
 * ============================================
 */

// ==================== 状态 Key 定义（英文，用于数据库和逻辑判断）====================
const STATUS = {
    // 新订单/询价阶段
    NEW_ORDER: 'NEW_ORDER',
    QUOTE_CONFIRMING: 'QUOTE_CONFIRMING',
    
    // 图稿阶段
    DRAFT_MAKING: 'DRAFT_MAKING',
    DRAFT_CONFIRMING: 'DRAFT_CONFIRMING',
    DRAFT_REVISING: 'DRAFT_REVISING',
    
    // 打样阶段
    PENDING_SAMPLE: 'PENDING_SAMPLE',
    SAMPLING: 'SAMPLING',
    SAMPLE_CONFIRMING: 'SAMPLE_CONFIRMING',
    SAMPLE_REVISING: 'SAMPLE_REVISING',
    
    // 生产阶段
    PENDING_PRODUCTION: 'PENDING_PRODUCTION',
    PRODUCING: 'PRODUCING',
    
    // 出貨階段
    PRODUCTION_DONE: 'PRODUCTION_DONE',
    PARTIAL_SHIPPED: 'PARTIAL_SHIPPED',
    ALL_SHIPPED: 'ALL_SHIPPED',
    
    // 最终状态
    COMPLETED: 'COMPLETED',
    CANCELLED: 'CANCELLED'
};

// ==================== 状态显示文字映射（key -> 显示文字）====================
const STATUS_LABELS = {
    NEW_ORDER: { zh_cn: '新订单', zh_tw: '新訂單', en: 'New Order', es: 'Pedido nuevo' },
    QUOTE_CONFIRMING: { zh_cn: '报价待确认', zh_tw: '報價待確認', en: 'Quote Pending Confirmation', es: 'Cotización pendiente de confirmación' },
    DRAFT_MAKING: { zh_cn: '图稿制作中', zh_tw: '圖稿製作中', en: 'Artwork in Progress', es: 'Diseño en preparación' },
    DRAFT_CONFIRMING: { zh_cn: '图稿待确认', zh_tw: '圖稿待確認', en: 'Artwork Pending Confirmation', es: 'Diseño pendiente de confirmación' },
    DRAFT_REVISING: { zh_cn: '图稿修改中', zh_tw: '圖稿修改中', en: 'Artwork Revising', es: 'Diseño en revisión' },
    PENDING_SAMPLE: { zh_cn: '待打样', zh_tw: '待打樣', en: 'Pending Sample', es: 'Pendiente de muestra' },
    SAMPLING: { zh_cn: '打样中', zh_tw: '打樣中', en: 'Sampling', es: 'Muestra en preparación' },
    SAMPLE_CONFIRMING: { zh_cn: '打样待确认', zh_tw: '打樣待確認', en: 'Sample Pending Confirmation', es: 'Muestra pendiente de confirmación' },
    SAMPLE_REVISING: { zh_cn: '打样修改中', zh_tw: '打樣修改中', en: 'Sample Revising', es: 'Muestra en revisión' },
    PENDING_PRODUCTION: { zh_cn: '待生产', zh_tw: '待生產', en: 'Pending Production', es: 'Pendiente de producción' },
    PRODUCING: { zh_cn: '生产中', zh_tw: '生產中', en: 'Producing', es: 'En producción' },
    PRODUCTION_DONE: { zh_cn: '生产完成', zh_tw: '生產完成', en: 'Production Done', es: 'Producción terminada' },
    PARTIAL_SHIPPED: { zh_cn: '出货一部份', zh_tw: '出貨一部份', en: 'Partially Shipped', es: 'Envío parcial' },
    ALL_SHIPPED: { zh_cn: '已全部出货', zh_tw: '已全部出貨', en: 'All Shipped', es: 'Envío total' },
    COMPLETED: { zh_cn: '已完成', zh_tw: '已完成', en: 'Completed', es: 'Completado' },
    CANCELLED: { zh_cn: '已取消', zh_tw: '已取消', en: 'Cancelled', es: 'Cancelado' }
};

// ==================== 显示函数 ====================
// 默认使用简体中文，可以通过参数切换语言
function displayStatus(status, lang = null) {
    const activeLang = lang || (typeof window.getTrackingLanguage === 'function' ? window.getTrackingLanguage() : 'zh_cn');
    let key = status;
    // New data stores canonical keys. Older rows may still contain a translated label,
    // so resolve that label back to its key before displaying the selected language.
    if (!(key in STATUS_LABELS)) {
        key = Object.keys(STATUS_LABELS).find(k => Object.values(STATUS_LABELS[k]).includes(status));
    }
    if (key && key in STATUS_LABELS) {
        return STATUS_LABELS[key][activeLang] || STATUS_LABELS[key]['zh_cn'] || status;
    }
    return status;
}

function displayText(text) {
    return text;
}

// ==================== 主要阶段分组（移除 emoji）====================
const PRIMARY_STAGE_GROUPS = {
    new_and_quote: {
        name: '新订单/询价',
        statuses: [STATUS.NEW_ORDER, STATUS.QUOTE_CONFIRMING],
        icon: '', // 移除 emoji，用 CSS
        iconClass: 'stage-icon-new', // 新增：CSS class
        color: '#8b5cf6',
        order: 1,
        isPrimary: true
    },
    draft: {
        name: '图稿阶段',
        statuses: [STATUS.DRAFT_MAKING, STATUS.DRAFT_CONFIRMING, STATUS.DRAFT_REVISING],
        icon: '', // 移除 emoji
        iconClass: 'stage-icon-draft',
        color: '#3b82f6',
        order: 2,
        isPrimary: true
    },
    sampling: {
        name: '打样阶段',
        statuses: [STATUS.PENDING_SAMPLE, STATUS.SAMPLING, STATUS.SAMPLE_CONFIRMING, STATUS.SAMPLE_REVISING],
        icon: '', // 移除 emoji
        iconClass: 'stage-icon-sample',
        color: '#06b6d4',
        order: 3,
        isPrimary: true
    },
    production: {
        name: '生产阶段',
        statuses: [STATUS.PENDING_PRODUCTION, STATUS.PRODUCING, STATUS.PRODUCTION_DONE],
        icon: '',
        iconClass: 'stage-icon-production',
        color: '#10b981',
        order: 4,
        isPrimary: true
    },
    shipping: {
        name: '出货阶段',
        statuses: [STATUS.PARTIAL_SHIPPED, STATUS.ALL_SHIPPED],
        icon: '',
        iconClass: 'stage-icon-shipping',
        color: '#f97316',
        order: 5,
        isPrimary: true
    },
    completed: {
        name: '已完成',
        statuses: [STATUS.COMPLETED],
        icon: '',
        iconClass: 'stage-icon-completed',
        color: '#22c55e',
        order: 6,
        isPrimary: true
    },
    cancelled: {
        name: '已取消',
        statuses: [STATUS.CANCELLED],
        icon: '',
        iconClass: 'stage-icon-cancelled',
        color: '#ef4444',
        order: 7,
        isPrimary: true
    }
};

// ==================== 虚拟筛选器（移除 emoji）====================
const FILTER_GROUPS = {
    waiting_confirm: {
        name: '等国外确认',
        // 仅包含“等待国外回复”的状态；图稿制作中是内部制作，不算“等国外确认”
        statuses: [STATUS.QUOTE_CONFIRMING, STATUS.DRAFT_CONFIRMING, STATUS.SAMPLE_CONFIRMING],
        icon: '', // 移除 emoji
        iconClass: 'stage-icon-waiting',
        color: '#f59e0b',
        order: 0,
        isFilter: true
    }
};

// ==================== 合并的阶段分组 ====================
const STAGE_GROUPS = {
    ...FILTER_GROUPS,
    ...PRIMARY_STAGE_GROUPS
};

// ==================== 工具函数 ====================

function getStageGroup(status) {
    for (const [groupName, group] of Object.entries(PRIMARY_STAGE_GROUPS)) {
        if (group.statuses.includes(status)) {
            return groupName;
        }
    }
    return 'all';
}

function getStageName(status) {
    const group = getStageGroup(status);
    if (group === 'all') return displayStatus('其他');
    
    const stageGroup = STAGE_GROUPS[group];
    // 只返回名稱，不包含 emoji
    return displayStatus(stageGroup.name);
}

// 獲取 CSS class 而不是 emoji
function getStageIconClass(status) {
    const group = getStageGroup(status);
    if (group === 'all') return '';
    
    const stageGroup = STAGE_GROUPS[group];
    return stageGroup.iconClass || '';
}

// ==================== 狀態圖標（時間軸用）- 优化版SVG ====================
function getStatusIcon(status) {
    // 返回优化后的SVG图标 - 使用stroke而不是fill，更清晰
    const iconMap = {
        [STATUS.NEW_ORDER]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`,
        
        [STATUS.QUOTE_CONFIRMING]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`,
        
        [STATUS.DRAFT_MAKING]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"></path></svg>`,
        [STATUS.DRAFT_CONFIRMING]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>`,
        
        [STATUS.DRAFT_REVISING]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>`,
        
        [STATUS.PENDING_SAMPLE]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`,
        
        [STATUS.SAMPLING]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`,
        
        [STATUS.SAMPLE_CONFIRMING]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 11 12 14 22 4"></polyline><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path></svg>`,
        
        [STATUS.SAMPLE_REVISING]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>`,
        
        [STATUS.PENDING_PRODUCTION]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="3" width="15" height="13"></rect><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"></polygon><circle cx="5.5" cy="18.5" r="2.5"></circle><circle cx="18.5" cy="18.5" r="2.5"></circle></svg>`,
        
        [STATUS.PRODUCING]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v4"></path><path d="m16.2 7.8 2.9-2.9"></path><path d="M18 12h4"></path><path d="m16.2 16.2 2.9 2.9"></path><path d="M12 18v4"></path><path d="m4.9 19.1 2.9-2.9"></path><path d="M2 12h4"></path><path d="m4.9 4.9 2.9 2.9"></path></svg>`,
        
        [STATUS.PRODUCTION_DONE]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`,
        
        [STATUS.PARTIAL_SHIPPED]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="3" width="15" height="13"></rect><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"></polygon><circle cx="5.5" cy="18.5" r="2.5"></circle><circle cx="18.5" cy="18.5" r="2.5"></circle></svg>`,
        
        [STATUS.ALL_SHIPPED]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 11 12 14 22 4"></polyline><rect x="1" y="3" width="15" height="13"></rect><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"></polygon><circle cx="5.5" cy="18.5" r="2.5"></circle><circle cx="18.5" cy="18.5" r="2.5"></circle></svg>`,
        
        [STATUS.COMPLETED]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`,
        
        [STATUS.CANCELLED]: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`
    };
    return iconMap[status] || `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`;
}

// 獲取時間軸步驟的 CSS class
function getTimelineIconClass(status) {
    const classMap = {
        [STATUS.NEW_ORDER]: 'timeline-icon-new',
        [STATUS.QUOTE_CONFIRMING]: 'timeline-icon-confirm',
        [STATUS.DRAFT_MAKING]: 'timeline-icon-processing',
        [STATUS.DRAFT_CONFIRMING]: 'timeline-icon-confirm',
        [STATUS.DRAFT_REVISING]: 'timeline-icon-revising',
        [STATUS.PENDING_SAMPLE]: 'timeline-icon-waiting',
        [STATUS.SAMPLING]: 'timeline-icon-processing',
        [STATUS.SAMPLE_CONFIRMING]: 'timeline-icon-confirm',
        [STATUS.SAMPLE_REVISING]: 'timeline-icon-revising',
        [STATUS.PENDING_PRODUCTION]: 'timeline-icon-paused',
        [STATUS.PRODUCING]: 'timeline-icon-processing',
        [STATUS.PRODUCTION_DONE]: 'timeline-icon-done',
        [STATUS.PARTIAL_SHIPPED]: 'timeline-icon-shipping',
        [STATUS.ALL_SHIPPED]: 'timeline-icon-shipped',
        [STATUS.COMPLETED]: 'timeline-icon-completed',
        [STATUS.CANCELLED]: 'timeline-icon-cancelled'
    };
    return classMap[status] || 'timeline-icon-default';
}

function getStatusThresholds(status) {
    const thresholds = {
        [STATUS.NEW_ORDER]: { yellowDays: 5, redDays: 7 },
        [STATUS.QUOTE_CONFIRMING]: { yellowDays: 3, redDays: 5 },
        [STATUS.DRAFT_MAKING]: { yellowDays: 2, redDays: 4 },
        [STATUS.DRAFT_CONFIRMING]: { yellowDays: 3, redDays: 5 },
        [STATUS.DRAFT_REVISING]: { yellowDays: 2, redDays: 4 },
        [STATUS.PENDING_SAMPLE]: { yellowDays: 5, redDays: 7 },
        [STATUS.SAMPLING]: { yellowDays: 10, redDays: null },
        [STATUS.SAMPLE_CONFIRMING]: { yellowDays: 2, redDays: 3 },
        [STATUS.SAMPLE_REVISING]: { yellowDays: 3, redDays: 5 },
        [STATUS.PENDING_PRODUCTION]: { yellowDays: 3, redDays: 5 },
        [STATUS.PRODUCING]: { yellowDays: 14, redDays: 21 },
        [STATUS.PRODUCTION_DONE]: { yellowDays: 2, redDays: 4 },
        [STATUS.PARTIAL_SHIPPED]: { yellowDays: 7, redDays: 14 },
        [STATUS.ALL_SHIPPED]: { yellowDays: 3, redDays: 5 },
        [STATUS.COMPLETED]: { yellowDays: null, redDays: null },
        [STATUS.CANCELLED]: { yellowDays: null, redDays: null }
    };
    return thresholds[status] || { yellowDays: null, redDays: null };
}

// ==================== 快捷操作配置（移除 emoji，保留編輯筆）====================
const QUICK_ACTIONS = {
    [STATUS.NEW_ORDER]: [
        { action: 'to_quote', label: '发报价', next: STATUS.QUOTE_CONFIRMING, color: 'confirm', showInHover: true, iconClass: 'action-icon-quote' }
    ],
    [STATUS.QUOTE_CONFIRMING]: [
        { action: 'quote_confirmed', label: '客户确认', next: STATUS.DRAFT_MAKING, color: 'confirm', showInHover: true, iconClass: 'action-icon-confirm' }
    ],
    [STATUS.DRAFT_MAKING]: [
        { action: 'draft_sent', label: '发图稿', next: STATUS.DRAFT_CONFIRMING, color: 'confirm', showInHover: true, iconClass: 'action-icon-resend' }
    ],
    [STATUS.DRAFT_CONFIRMING]: [
        { action: 'draft_confirm', label: '图稿确认', next: STATUS.PENDING_SAMPLE, color: 'confirm', showInHover: true, iconClass: 'action-icon-confirm' },
        { action: 'draft_modify', label: '需修改', next: STATUS.DRAFT_REVISING, color: 'warning', showInHover: true, iconClass: 'action-icon-modify' }
    ],
    [STATUS.DRAFT_REVISING]: [
        { action: 'draft_resent', label: '重新发图', next: STATUS.DRAFT_CONFIRMING, color: 'confirm', showInHover: true, iconClass: 'action-icon-resend' }
    ],
    [STATUS.PENDING_SAMPLE]: [
        { action: 'sampling_start', label: '开始打样', next: STATUS.SAMPLING, color: 'confirm', showInHover: true, iconClass: 'action-icon-start' }
    ],
    [STATUS.SAMPLING]: [
        { action: 'sampling_sent', label: '打样待确认', next: STATUS.SAMPLE_CONFIRMING, color: 'confirm', showInHover: true, iconClass: 'action-icon-send' }
    ],
    [STATUS.SAMPLE_CONFIRMING]: [
        { action: 'sampling_confirm', label: '样品确认', next: STATUS.PENDING_PRODUCTION, color: 'confirm', showInHover: true, iconClass: 'action-icon-confirm' },
        { action: 'sampling_modify', label: '需修改', next: STATUS.SAMPLE_REVISING, color: 'warning', showInHover: true, iconClass: 'action-icon-modify' }
    ],
    [STATUS.SAMPLE_REVISING]: [
        { action: 'sampling_restart', label: '重新打样', next: STATUS.SAMPLING, color: 'confirm', showInHover: true, iconClass: 'action-icon-restart' }
    ],
    [STATUS.PENDING_PRODUCTION]: [
        { action: 'production_start', label: '开始生产', next: STATUS.PRODUCING, color: 'confirm', showInHover: true, iconClass: 'action-icon-start' }
    ],
    [STATUS.PRODUCING]: [
        { action: 'production_done', label: '生產完成', next: STATUS.PRODUCTION_DONE, color: 'confirm', showInHover: true, iconClass: 'action-icon-complete' }
    ],
    [STATUS.PRODUCTION_DONE]: [
        { action: 'ship_partial', label: '出货一部份', next: STATUS.PARTIAL_SHIPPED, color: 'confirm', showInHover: true, iconClass: 'action-icon-ship' },
        { action: 'ship_all', label: '全部出货', next: STATUS.ALL_SHIPPED, color: 'confirm', showInHover: true, iconClass: 'action-icon-ship-all' }
    ],
    [STATUS.PARTIAL_SHIPPED]: [
        { action: 'ship_partial', label: '出货一部份', next: STATUS.PARTIAL_SHIPPED, color: 'confirm', showInHover: true, iconClass: 'action-icon-ship' },
        { action: 'ship_complete', label: '全部出货完成', next: STATUS.ALL_SHIPPED, color: 'confirm', showInHover: true, iconClass: 'action-icon-ship-all' }
    ],
    [STATUS.ALL_SHIPPED]: [
        { action: 'shipping_complete', label: '确认完成', next: STATUS.COMPLETED, color: 'confirm', showInHover: true, iconClass: 'action-icon-complete' }
    ]
};

function getQuickActions(status) {
    return QUICK_ACTIONS[status] || [];
}

// ==================== 状态流程顺序 ====================
const STATUS_FLOW_ORDER = [
    STATUS.NEW_ORDER,
    STATUS.QUOTE_CONFIRMING,
    STATUS.DRAFT_MAKING,
    STATUS.DRAFT_CONFIRMING,
    STATUS.DRAFT_REVISING,
    STATUS.PENDING_SAMPLE,
    STATUS.SAMPLING,
    STATUS.SAMPLE_CONFIRMING,
    STATUS.SAMPLE_REVISING,
    STATUS.PENDING_PRODUCTION,
    STATUS.PRODUCING,
    STATUS.PRODUCTION_DONE,
    STATUS.PARTIAL_SHIPPED,
    STATUS.ALL_SHIPPED,
    STATUS.COMPLETED,
    STATUS.CANCELLED
];

function getSkippableStatuses(currentStatus) {
    if (currentStatus === STATUS.COMPLETED || currentStatus === STATUS.CANCELLED) {
        return [];
    }
    const currentIndex = STATUS_FLOW_ORDER.indexOf(currentStatus);
    if (currentIndex === -1) return [];
    
    return STATUS_FLOW_ORDER
        .slice(currentIndex + 1)
        .filter(status => 
            status !== STATUS.DRAFT_REVISING && 
            status !== STATUS.SAMPLE_REVISING
        );
}

function getStatusesByStageGroup(stageGroup) {
    if (!STAGE_GROUPS[stageGroup]) {
        return [];
    }
    return STAGE_GROUPS[stageGroup].statuses || [];
}

function getStageMap() {
    const map = {};
    for (const [groupName, group] of Object.entries(STAGE_GROUPS)) {
        map[groupName] = group.statuses;
    }
    return map;
}

function isStatusInFilter(status, filterGroup) {
    if (!STAGE_GROUPS[filterGroup]) {
        return false;
    }
    return STAGE_GROUPS[filterGroup].statuses.includes(status);
}

function getAllMatchingGroups(status) {
    const matches = [];
    for (const [groupName, group] of Object.entries(STAGE_GROUPS)) {
        if (group.statuses.includes(status)) {
            matches.push(groupName);
        }
    }
    return matches;
}

// ==================== 导出 ====================
if (typeof window !== 'undefined') {
    window.STATUS = STATUS;  // Key 定义（如 'NEW_ORDER', 'DRAFT_MAKING'）
    window.STATUS_LABELS = STATUS_LABELS;  // Key -> 显示文字映射
    window.STAGE_GROUPS = STAGE_GROUPS;
    window.PRIMARY_STAGE_GROUPS = PRIMARY_STAGE_GROUPS;
    window.FILTER_GROUPS = FILTER_GROUPS;
    window.displayStatus = displayStatus;  // 显示函数：key -> 中文
    window.displayText = displayText;
    window.getStageGroup = getStageGroup;
    window.getStageName = getStageName;
    window.getStageIconClass = getStageIconClass;
    window.getStatusIcon = getStatusIcon;
    window.getTimelineIconClass = getTimelineIconClass;
    window.getStatusThresholds = getStatusThresholds;
    window.getQuickActions = getQuickActions;
    window.getStatusesByStageGroup = getStatusesByStageGroup;
    window.getStageMap = getStageMap;
    window.isStatusInFilter = isStatusInFilter;
    window.getAllMatchingGroups = getAllMatchingGroups;
    window.STATUS_FLOW_ORDER = STATUS_FLOW_ORDER;
    window.getSkippableStatuses = getSkippableStatuses;
}

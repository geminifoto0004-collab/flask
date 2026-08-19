/**
 * 建立业务流程功能
 */

/**
 * 显示错误 Modal
 */
function showErrorModal(title, message) {
    // 如果有全局的 showToast 函数,用 Toast
    if (typeof showToast === 'function') {
        showToast(title, message, 'error');
        return;
    }
    
    // 否则用简单的 Modal (需要 HTML 配合)
    const modal = document.getElementById('errorModal');
    if (modal) {
        const titleEl = document.getElementById('errorModalTitle');
        const messageEl = document.getElementById('errorModalMessage');
        if (titleEl) titleEl.textContent = title;
        if (messageEl) messageEl.textContent = message;
        modal.classList.add('show');
    } else {
        // 如果连 Modal 都没有,使用 Toast
        if (typeof showToast === 'function') {
            showToast(title, message, 'error');
        }
    }
}

/**
 * 显示成功 Modal
 */
function showSuccessModal(title, message) {
    if (typeof showToast === 'function') {
        showToast(title, message, 'success');
        return;
    }
    
    const modal = document.getElementById('successModal');
    if (modal) {
        const titleEl = document.getElementById('successModalTitle');
        const messageEl = document.getElementById('successModalMessage');
        if (titleEl) titleEl.textContent = title;
        if (messageEl) messageEl.textContent = message;
        modal.classList.add('show');
    } else {
        // 如果连 Modal 都没有,使用 Toast
        if (typeof showToast === 'function') {
            showToast(title, message, 'success');
        }
    }
}

// 统一重置表单状态（用于打开、提交成功、关闭）
function resetNewOrderFormState({ resetForm = true } = {}) {
    if (resetForm) {
        const form = document.getElementById('newOrderForm');
        if (form) {
            form.reset();
        }
        
        // 重置事件绑定标志，确保下次打开时重新绑定
        const orderInput = document.getElementById('newOrderNumber');
        if (orderInput) {
            orderInput.dataset.eventsBound = 'false';
        }
    }

    const orderInfo = document.getElementById('selectedOrderInfo');
    const orderError = document.getElementById('orderNumberError');
    const suggestionsDiv = document.getElementById('orderNumberSuggestions');

    if (orderInfo) orderInfo.style.display = 'none';
    if (orderError) {
        orderError.style.display = 'none';
        orderError.textContent = '';
    }
    if (suggestionsDiv) suggestionsDiv.style.display = 'none';
}

// 绑定订单号输入框事件（每次打开 Modal 时重新绑定，确保在所有页面都能正常工作）
function bindOrderInputEvents() {
    const orderInput = document.getElementById('newOrderNumber');
    const suggestionsDiv = document.getElementById('orderNumberSuggestions');
    
    if (!orderInput) return;
    
    // 如果已经绑定过，先移除旧的事件监听器
    if (window._newOrderModalClickHandler) {
        document.removeEventListener('click', window._newOrderModalClickHandler, true);
        window._newOrderModalClickHandler = null;
    }
    
    // 移除旧的 input 和 blur 事件（通过克隆节点，但保留值）
    const currentValue = orderInput.value;
    const newOrderInput = orderInput.cloneNode(true);
    orderInput.parentNode.replaceChild(newOrderInput, orderInput);
    
    // 重新获取引用并恢复值
    const freshOrderInput = document.getElementById('newOrderNumber');
    if (!freshOrderInput) return;
    freshOrderInput.value = currentValue;
    
    // 标记为已绑定
    freshOrderInput.dataset.eventsBound = 'true';
    
    let searchTimeout;
    
    // 输入时搜索建议
    freshOrderInput.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        const query = this.value;
        searchTimeout = setTimeout(() => {
            searchOrderNumber(query);
        }, 300); // 防抖，300ms后搜索
    });
    
    // 失去焦点时验证
    freshOrderInput.addEventListener('blur', function() {
        // 延迟隐藏建议，让点击建议项有时间执行
        setTimeout(() => {
            if (suggestionsDiv) {
                suggestionsDiv.style.display = 'none';
            }
            if (this.value) {
                validateOrderNumber(this.value);
            }
        }, 200);
    });
    
    // 点击外部关闭建议（但不阻止 Modal 关闭）
    window._newOrderModalClickHandler = function(e) {
        if (suggestionsDiv && suggestionsDiv.style.display !== 'none') {
            const modal = document.getElementById('newOrderModal');
            // 如果点击的是 Modal overlay，先隐藏建议，让 Modal 关闭逻辑处理
            if (modal && e.target === modal) {
                suggestionsDiv.style.display = 'none';
                return; // 让 Modal 的 onclick 处理关闭
            }
            // 如果点击的不是输入框和建议列表，隐藏建议
            if (!freshOrderInput.contains(e.target) && !suggestionsDiv.contains(e.target)) {
                suggestionsDiv.style.display = 'none';
            }
        }
    };
    
    document.addEventListener('click', window._newOrderModalClickHandler, true); // 使用捕获阶段
}

// 打开建立业务流程 Modal（重命名为 openNewWorkflowModal 避免与 tracking.js 冲突）
async function openNewWorkflowModal() {
    console.log('[new_order.js] openNewWorkflowModal called');
    const modal = document.getElementById('newOrderModal');
    if (!modal) {
        console.error('[new_order.js] newOrderModal not found');
        return;
    }

    resetNewOrderFormState({ resetForm: true });

    // Show modal first to avoid blocking on API
    modal.classList.add('show');

    console.log('[new_order.js] rebind input events');
    bindOrderInputEvents();

    const orderInput = document.getElementById('newOrderNumber');
    if (orderInput) {
        setTimeout(() => orderInput.focus(), 100);
    } else {
        console.warn('[new_order.js] newOrderNumber input not found');
    }

    console.log('[new_order.js] loading unlocked orders');
    loadNewOrderUnlockedOrders().then(() => {
        console.log('[new_order.js] unlocked orders loaded:', newOrderUnlockedOrdersCache.length);
        const currentValue = orderInput ? orderInput.value.trim() : '';
        if (currentValue && newOrderUnlockedOrdersCache.length > 0) {
            searchOrderNumber(currentValue);
        }
    });
}


// 载入已解锁的订单列表（用于搜索建议）
// 使用独立的函数名和缓存，避免与其他页面的 loadUnlockedOrders 冲突
let newOrderUnlockedOrdersCache = [];
let newOrderUnlockedOrdersLoading = null;

async function loadNewOrderUnlockedOrders() {
    if (newOrderUnlockedOrdersLoading) {
        return newOrderUnlockedOrdersLoading;
    }

    newOrderUnlockedOrdersLoading = (async () => {
        try {
            console.log('[new_order.js] fetch /tracking/api/orders/unlocked');
            const response = await fetch('/tracking/api/orders/unlocked');

            if (!response.ok) {
                console.error('[new_order.js] API request failed:', response.status, response.statusText);
                newOrderUnlockedOrdersCache = [];
                return;
            }

            const result = await response.json();
            console.log('[new_order.js] unlocked orders response:', result);

            if (result.success) {
                newOrderUnlockedOrdersCache = result.data || [];
                console.log('[new_order.js] unlocked orders count:', newOrderUnlockedOrdersCache.length);
            } else {
                console.error('[new_order.js] unlocked orders error:', result.error);
                newOrderUnlockedOrdersCache = [];
            }
        } catch (error) {
            console.error('[new_order.js] unlocked orders exception:', error);
            newOrderUnlockedOrdersCache = [];
        }
    })();

    return newOrderUnlockedOrdersLoading.finally(() => {
        newOrderUnlockedOrdersLoading = null;
    });
}


// 搜索订单号建议
function searchOrderNumber(query) {
    const suggestionsDiv = document.getElementById('orderNumberSuggestions');
    if (!suggestionsDiv) {
        console.warn('[new_order.js] orderNumberSuggestions 元素未找到');
        return;
    }
    
    if (!query || query.trim().length === 0) {
        suggestionsDiv.style.display = 'none';
        return;
    }
    
    const queryLower = query.toLowerCase().trim();

    if (newOrderUnlockedOrdersCache.length === 0) {
        loadNewOrderUnlockedOrders().then(() => {
            if (newOrderUnlockedOrdersCache.length === 0) return;
            const currentValue = document.getElementById('newOrderNumber')?.value || '';
            if (currentValue.trim().toLowerCase() === queryLower) {
                searchOrderNumber(currentValue);
            }
        });
        return;
    }
    console.log('[new_order.js] 搜索订单号:', query, '缓存数量:', newOrderUnlockedOrdersCache.length);
    
    // 使用独立的缓存变量
    const matches = newOrderUnlockedOrdersCache.filter(order => 
        order.order_number.toLowerCase().includes(queryLower) ||
        (order.customer_name && order.customer_name.toLowerCase().includes(queryLower))
    ).slice(0, 10); // 最多显示10个建议
    
    console.log('[new_order.js] 找到匹配:', matches.length, '个订单');
    
    if (matches.length === 0) {
        suggestionsDiv.style.display = 'none';
        return;
    }
    
    suggestionsDiv.innerHTML = '';
    matches.forEach(order => {
        const item = document.createElement('div');
        item.style.cssText = 'padding: 0.75rem; cursor: pointer; border-bottom: 1px solid #e5e7eb;';
        item.innerHTML = `
            <div style="font-weight: 500; color: #111827;">${order.order_number}</div>
            ${order.customer_name ? `<div style="font-size: 0.75rem; color: #6b7280; margin-top: 0.25rem;">${order.customer_name}</div>` : ''}
        `;
        item.addEventListener('click', () => {
            document.getElementById('newOrderNumber').value = order.order_number;
            suggestionsDiv.style.display = 'none';
            validateOrderNumber(order.order_number);
        });
        item.addEventListener('mouseenter', () => {
            item.style.background = '#f3f4f6';
        });
        item.addEventListener('mouseleave', () => {
            item.style.background = 'white';
        });
        suggestionsDiv.appendChild(item);
    });
    
    suggestionsDiv.style.display = 'block';
}

// 验证订单号
async function validateOrderNumber(orderNumber) {
    const orderInput = document.getElementById('newOrderNumber');
    const orderInfo = document.getElementById('selectedOrderInfo');
    const orderError = document.getElementById('orderNumberError');
    const customerNameSpan = document.getElementById('selectedCustomerName');
    const orderDateSpan = document.getElementById('selectedOrderDate');
    
    if (!orderNumber || orderNumber.trim().length === 0) {
        if (orderInfo) orderInfo.style.display = 'none';
        if (orderError) orderError.style.display = 'none';
        return false;
    }
    
    try {
        const response = await fetch(`/tracking/api/orders/check?order_number=${encodeURIComponent(orderNumber.trim())}`);
        
        // 检查响应状态
        if (!response.ok) {
            // 如果不是 JSON 响应，尝试获取文本
            const text = await response.text();
            console.error('API 响应错误:', response.status, text);
            if (orderError) {
                orderError.textContent = `服务器错误 (${response.status})，请稍后再试`;
                orderError.style.display = 'block';
            }
            if (orderInfo) orderInfo.style.display = 'none';
            return false;
        }
        
        // 尝试解析 JSON
        let result;
        try {
            result = await response.json();
        } catch (jsonError) {
            console.error('JSON 解析失败:', jsonError);
            if (orderError) {
                orderError.textContent = '服务器响应格式错误，请稍后再试';
                orderError.style.display = 'block';
            }
            if (orderInfo) orderInfo.style.display = 'none';
            return false;
        }
        
        if (!result.success) {
            if (orderError) {
                orderError.textContent = result.error || '无法检查订单号状态';
                orderError.style.display = 'block';
            }
            if (orderInfo) orderInfo.style.display = 'none';
            return false;
        }
        
        if (!result.data.exists) {
            if (orderError) {
                orderError.textContent = '订单号不存在，请先由管理员建立';
                orderError.style.display = 'block';
            }
            if (orderInfo) orderInfo.style.display = 'none';
            return false;
        }
        
        if (!result.data.accessible) {
            if (orderError) {
                orderError.textContent = '您无权使用此订单号';
                orderError.style.display = 'block';
            }
            if (orderInfo) orderInfo.style.display = 'none';
            return false;
        }
        
        if (result.data.status !== 'ACTIVE') {
            if (orderError) {
                orderError.textContent = '订单号未解锁，请联系管理员';
                orderError.style.display = 'block';
            }
            if (orderInfo) orderInfo.style.display = 'none';
            return false;
        }
        
        // 验证成功，显示订单信息
        if (orderError) orderError.style.display = 'none';
        if (orderInfo) {
            if (customerNameSpan) {
                customerNameSpan.textContent = result.data.customer_name || '-';
            }
            if (orderDateSpan) {
                orderDateSpan.textContent = result.data.order_date || '-';
            }
            orderInfo.style.display = 'block';
        }
        return true;
    } catch (error) {
        console.error('验证订单号失败:', error);
        if (orderError) {
            orderError.textContent = '网络错误，请稍后再试';
            orderError.style.display = 'block';
        }
        if (orderInfo) orderInfo.style.display = 'none';
        return false;
    }
}

// 当输入订单号时，搜索建议和验证
// 注意：现在事件绑定在 openNewWorkflowModal() 中完成，确保每次打开 Modal 时都能正常工作
// 这里保留 DOMContentLoaded 作为后备，但主要逻辑已移到 bindOrderInputEvents()
document.addEventListener('DOMContentLoaded', function() {
    // 如果 Modal 已经存在，也绑定一次（作为后备）
    const orderInput = document.getElementById('newOrderNumber');
    if (orderInput) {
        bindOrderInputEvents();
    }
});

// 关闭新建业务流程 Modal（重命名为 closeNewWorkflowModal 避免与 tracking.js 冲突）
// forceClose = true 时直接关闭，不弹确认
async function closeNewWorkflowModal(forceClose = false) {
    const modal = document.getElementById('newOrderModal');
    if (!modal) return;
    
    // 检查是否有未保存的数据（简单检查：是否有输入内容）
    const orderInput = document.getElementById('newOrderNumber');
    const hasData = orderInput && orderInput.value.trim().length > 0;
    
    // 如果有数据，显示确认对话框
    if (!forceClose && hasData && typeof showConfirmModal === 'function') {
        try {
            const confirmed = await showConfirmModal('确定要关闭吗？未保存的数据将丢失。', '确认关闭', '确认', '取消', true);
            if (!confirmed) {
                return; // 用户取消关闭
            }
        } catch (e) {
            // 如果 showConfirmModal 不存在或出错，直接关闭
            console.warn('showConfirmModal 不可用，直接关闭:', e);
        }
    }
    
    // 先隐藏所有提示和建议（在关闭 Modal 之前）
    resetNewOrderFormState({ resetForm: true });
    
    // 隐藏建议列表
    const suggestionsDiv = document.getElementById('orderNumberSuggestions');
    if (suggestionsDiv) {
        suggestionsDiv.style.display = 'none';
    }
    
    // 关闭 Modal
    modal.classList.remove('show');
    
    // 表单已重置
}

// 提交建立业务流程表单
async function submitNewOrder() {
    // 1. 收集表单数据（只收集流程相关字段，不包含订单层级字段）
    const productionType = document.getElementById('newProductName')?.value.trim() || '';
    const formData = {
        order_number: document.getElementById('newOrderNumber').value.trim(),
        production_type: productionType,
        product_name: productionType,
        product_code: document.getElementById('newProductCode')?.value.trim() || '',
        quantity: document.getElementById('newQuantity')?.value.trim() || '',
        factory: document.getElementById('newFactory')?.value || '',
        expected_delivery_date: document.getElementById('newDeliveryDate')?.value || '',
        notes: document.getElementById('newOrderNotes')?.value.trim() || ''
    };
    
    // 2. 验证必填项（只需要订单号）
    if (!formData.order_number) {
        showErrorModal('验证错误', '请填写订单号');
        document.getElementById('newOrderNumber').focus();
        return;
    }
    
    // 3. 再次验证订单号（确保最新状态）
    const isValid = await validateOrderNumber(formData.order_number);
    if (!isValid) {
        const orderError = document.getElementById('orderNumberError');
        if (orderError && orderError.style.display === 'none') {
            showErrorModal('验证错误', '订单号验证失败，请检查订单号是否正确');
        }
        document.getElementById('newOrderNumber').focus();
        return;
    }
    
    // 4. 提交建立业务流程
    try {
        const response = await fetch('/tracking/api/workflows', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });
        
        const result = await response.json();
        
        if (result.success) {
            const workflowNumber = result.data?.workflow_number || '';
            const orderNumber = result.data?.order_number || formData.order_number;
            
            showSuccessModal('建立成功', `业务流程 ${workflowNumber} 已建立`);
            
            // 提交成功后清空表单，保持 Modal 打开便于连续录入
            resetNewOrderFormState({ resetForm: true });
            const orderInput = document.getElementById('newOrderNumber');
            if (orderInput) {
                setTimeout(() => orderInput.focus(), 100);
            }
            
            // 动态刷新表格：拉取新流程数据并插入表格（不刷新整个页面）
            if (workflowNumber) {
                try {
                    const wfResp = await fetch(`/tracking/api/workflows/${encodeURIComponent(workflowNumber)}`);
                    const wfResult = await wfResp.json();
                    if (wfResult.success && wfResult.data) {
                        const tbody = document.getElementById('ordersTableBody');
                        if (tbody && typeof createOrderRow === 'function') {
                            const newRow = createOrderRow(wfResult.data);
                            // 插到表格最前面
                            tbody.insertBefore(newRow, tbody.firstChild);
                            
                            // 刷新各组件（applyFilters 内部会更新分页）
                            if (typeof updateFilterCounts === 'function') updateFilterCounts();
                            if (typeof updateOrderAgeColumn === 'function') updateOrderAgeColumn();
                            if (typeof initQuickActionsForAllRows === 'function') {
                                setTimeout(() => initQuickActionsForAllRows(), 50);
                            }
                            if (typeof applyFilters === 'function') applyFilters();
                            
                            // 高亮新行
                            setTimeout(() => {
                                if (typeof highlightOrderRow === 'function') {
                                    highlightOrderRow(workflowNumber);
                                }
                            }, 200);
                        }
                    }
                } catch (e) {
                    console.warn('动态刷新表格失败，可手动刷新:', e);
                }
            }
        } else {
            showErrorModal('建立失败', result.error || '未知错误');
        }
    } catch (error) {
        console.error('Error:', error);
        showErrorModal('错误', '网络错误，请稍后再试');
    }
}

// ==================== 挂载到全局供 HTML onclick 使用 ====================
// 确保函数挂载到 window 对象
// 使用命名空间保护，避免与其他脚本冲突
(function() {
    // 创建命名空间（如果不存在）
    if (!window.NewOrderModule) {
        window.NewOrderModule = {};
    }
    
    // 将函数保存到命名空间
    window.NewOrderModule.openNewWorkflowModal = openNewWorkflowModal;
    window.NewOrderModule.closeNewWorkflowModal = closeNewWorkflowModal;
    window.NewOrderModule.submitNewOrder = submitNewOrder;
    window.NewOrderModule.loadNewOrderUnlockedOrders = loadNewOrderUnlockedOrders;
    window.NewOrderModule.bindOrderInputEvents = bindOrderInputEvents;
    
    // 同时挂载到全局（供 HTML onclick 使用）
    window.openNewWorkflowModal = openNewWorkflowModal;
    window.closeNewWorkflowModal = closeNewWorkflowModal;
    window.submitNewOrder = submitNewOrder;
    
    // 为了向后兼容，也保留旧的函数名（但指向新函数）
    window.openNewOrderModal = openNewWorkflowModal;
    window.closeNewOrderModal = closeNewWorkflowModal;
    
    // 确保在 DOMContentLoaded 后也重新挂载（防止被其他脚本覆盖）
    function reattachFunctions() {
        // 从命名空间恢复函数（如果被覆盖）
        if (window.NewOrderModule) {
            window.openNewWorkflowModal = window.NewOrderModule.openNewWorkflowModal || openNewWorkflowModal;
            window.closeNewWorkflowModal = window.NewOrderModule.closeNewWorkflowModal || closeNewWorkflowModal;
            window.submitNewOrder = window.NewOrderModule.submitNewOrder || submitNewOrder;
        } else {
            // 如果命名空间不存在，重新创建
            window.NewOrderModule = {
                openNewWorkflowModal: openNewWorkflowModal,
                closeNewWorkflowModal: closeNewWorkflowModal,
                submitNewOrder: submitNewOrder,
                loadNewOrderUnlockedOrders: loadNewOrderUnlockedOrders,
                bindOrderInputEvents: bindOrderInputEvents
            };
            window.openNewWorkflowModal = openNewWorkflowModal;
            window.closeNewWorkflowModal = closeNewWorkflowModal;
            window.submitNewOrder = submitNewOrder;
        }
        
        // 向后兼容
        window.openNewOrderModal = window.openNewWorkflowModal;
        window.closeNewOrderModal = window.closeNewWorkflowModal;
    }
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', reattachFunctions);
    } else {
        reattachFunctions();
    }
    
    // 在 window load 事件后再次确保函数存在（防止其他脚本在最后覆盖）
    window.addEventListener('load', reattachFunctions);
})();

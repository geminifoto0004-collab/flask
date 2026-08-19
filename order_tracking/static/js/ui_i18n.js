/**
 * order_tracking UI language switcher.
 * Supported UI languages: Simplified Chinese (zh_cn) and Spanish (es).
 * This is display-only: data, permissions and business logic are unchanged.
 */
(function () {
    'use strict';

    const STORAGE_KEY = 'tracking_ui_language';
    const DEFAULT_LANG = 'zh_cn';
    const SUPPORTED = new Set(['zh_cn', 'es']);

    const TEXT = {
        zh_cn: {
            'company': '杭州可成有限公司',
            'system.name': '订单追踪系统',
            'system.title': '订单流程追踪系统',
            'lang.switch_to': '切换语言',
            'nav.home': '首页',
            'nav.create_workflow': '建立业务流程',
            'nav.order_admin': '订单管理',
            'nav.user_admin': '用户管理',
            'nav.settings': '设置',
            'nav.logout': '登出',
            'mobile.search': '搜索客户名称或订单号',
            'mobile.clear_search': '清除搜索',
            'mobile.browse_mode': '浏览模式',
            'mobile.by_order': '按订单',
            'mobile.by_customer': '按客户',
            'filter.stage': '阶段',
            'filter.all': '全部',
            'filter.draft': '图稿',
            'filter.sample': '打样',
            'filter.production': '生产',
            'filter.shipping': '出货',
            'stage.new_quote': '新订单/询价',
            'stage.draft': '图稿阶段',
            'stage.sample': '打样阶段',
            'stage.production': '生产阶段',
            'stage.shipping': '出货阶段',
            'stage.waiting_confirm': '等国外确认',
            'stage.completed': '已完成',
            'stage.cancelled': '已取消',
            'stage.no_workflow': '无流程',
            'filter.salesperson': '业务员',
            'search.desktop': '搜索订单号、客户名称...',
            'search.salesperson': '搜索',
            'table.order_date': '订单日期',
            'table.elapsed': '历时',
            'table.order_number': '订单号',
            'table.customer': '客户名称',
            'table.product_type': '产品类型',
            'table.product_code': '产品编号',
            'table.quantity': '数量',
            'table.factory': '生产工厂',
            'table.status': '阶段 / 状态',
            'table.delivery': '交期',
            'table.notes': '备注',
            'table.salesperson': '业务员',
            'table.actions': '操作',
            'table.loading': '正在载入订单资料...',
            'filter.all_salespeople': '全部业务员',
            'filter.more': '更多…',
            'filter.light': '灯号',
            'light.normal': '正常',
            'light.warning': '需注意',
            'light.overdue': '逾期',
            'mobile.click_detail': '点击可查看详情',
            'mobile.loading': '正在载入订单资料…',
            'mobile.more': '显示更多',
            'mobile.back_customers': '返回客户列表',
            'mobile.back_orders': '返回订单列表',
            'mobile.order_detail': '订单详情',
            'mobile.order_info': '订单资料',
            'mobile.timeline': '进度时间轴',
            'mobile.timeline_order': '下单',
            'mobile.timeline_draft': '图稿',
            'mobile.timeline_sample': '打样',
            'mobile.timeline_production': '生产',
            'mobile.timeline_shipping': '出货',
            'mobile.product': '产品',
            'mobile.product_code': '编号',
            'mobile.quantity': '数量',
            'mobile.factory': '工厂',
            'mobile.order_date': '订单日期',
            'mobile.delivery_date': '预计交期',
            'mobile.status_days': '当前阶段',
            'mobile.days': '天',
            'mobile.salesperson': '业务员',
            'mobile.current_status': '当前状态',
            'mobile.readonly_hint': '云端只读，只显示已同步资料',
            'mobile.loading_detail': '正在载入订单详情…',
            'mobile.detail_load_failed': '订单详情载入失败',
            'mobile.no_value': '—',
            'mobile.select_salesperson': '选择业务员',
            'mobile.select_salesperson_hint': '选择后立即套用筛选',
            'mobile.close': '关闭',
            'mobile.no_orders': '没有符合条件的订单',
            'mobile.no_cloud_orders': '尚未同步云端订单资料',
            'mobile.no_customers': '没有符合条件的客户',
            'mobile.unassigned_customer': '未指定客户',
            'mobile.latest': '最新',
            'mobile.order_count': '笔订单',
            'mobile.customer_count': '位客户',
            'mobile.order_unit': '笔',
            'mobile.report.request': '申请完整报告',
            'mobile.report.queue_hint': 'TiDB 接通后启用',
            'mobile.report.generate': '生成报告',
            'mobile.report.all_orders': '全部订单报告',
            'mobile.report.all_orders_hint': '按当前查看范围生成',
            'mobile.report.single': '本单 PDF',
            'mobile.report.single_action': '生成 / 分享本单 PDF',
            'mobile.report.single_hint': '只包含当前这张订单',
            'mobile.report.single_title': '单张订单报告',
            'mobile.report.local_hint': '沿用现有 PDF',
            'mobile.customer_link': '查询链接',
            'mobile.customer_token': '客户 Token',
            'mobile.detail_missing_title': '提示',
            'mobile.detail_missing': '此笔订单目前没有可开启的流程详情',
            'mobile.report_cloud_title': '云端报告',
            'mobile.report_cloud_pending': '介面已预留；TiDB report_requests 接通后，这里会加入待处理队列。目前不会假装已送出。',
            'mobile.customer_link_title': '客户查询链接',
            'mobile.customer_link_pending': '的 /c/<token> 将在 TiDB Token 阶段接通，目前尚未建立链接。',
            'mobile.search_customer': '客户',
            'mobile.search_order': '订单',
            'mobile.images': '图片',
            'mobile.image': '图片',
            'mobile.images_loading': '正在载入图片…',
            'mobile.order_image': '订单图片',
            'mobile.workflow_image': '流程图片',
            'mobile.report.title': '客户完整报告',
            'mobile.report.subtitle': 'PDF 会在本地服务器生成',
            'mobile.report.queuing': '正在建立 PDF 任务…',
            'mobile.report.generating': '正在生成 PDF…',
            'mobile.report.keep_open': '可以留在这个页面等待完成',
            'mobile.report.ready': 'PDF 已生成',
            'mobile.report.open_pdf': '打开 PDF',
            'mobile.report.share': '分享 PDF',
            'mobile.report.download': '下载',
            'mobile.report.failed': '报告生成失败',
            'mobile.report.no_file': '报告完成，但没有可用档案',
            'mobile.report.no_orders': '此客户目前没有可生成报告的订单',
            'cloud.title': '云端只读模式',
            'cloud.readonly_desc': '此页只能查看；正式修改请回公司系统操作。',
            'cloud.updated_at': '资料更新于：',
            'cloud.wait_first': '等待首次同步',
            'cloud.no_data': '尚未连接云端订单资料',
            'login.browser_title': '登入 - 订单流程追踪系统',
            'login.welcome': '欢迎登录',
            'login.prompt': '请输入您的账号信息',
            'login.login': '登录',
            'login.register': '注册',
            'login.username': '用户名',
            'login.username_placeholder': '请输入用户名',
            'login.password': '密码',
            'login.password_placeholder': '请输入密码',
            'login.confirm_new_password': '确认新密码',
            'login.confirm_new_password_placeholder': '请再次输入新密码',
            'login.register_title': '用户注册',
            'login.register_prompt': '注册后需等待主管审核',
            'login.real_name': '真实姓名 *',
            'login.real_name_placeholder': '请输入真实姓名',
            'login.register_username': '用户名（登入账号）*',
            'login.register_password': '密码 *',
            'login.register_password_placeholder': '请输入密码（至少6位）',
            'login.confirm_password': '确认密码 *',
            'login.confirm_password_placeholder': '请再次输入密码',
            'login.register_success': '注册成功！请等待主管审核，审核通过后即可登入。',
            'login.cloud_note': '云端版本 · 显示最后同步资料 · 仅供查看',
            'login.brand_title': '品质面料，\n织就美好未来',
            'login.brand_subtitle': '优质面料，匠心传承。每一匹布料都承载着品质与信赖，为您的创作添彩，让美好触手可及。',
            'login.exp_years': '年专业经验',
            'login.realtime': '实时',
            'login.order_monitor': '订单监控',
            'login.efficient': '高效',
            'login.flow_manage': '流程管理',
            'login.password_mismatch': '两次输入的密码不一致',
            'login.password_too_short': '密码至少需要6位',
            'login.register_failed': '注册失败',
            'guest.subtitle': '临时查看 · 仅限本人订单',
            'guest.expiry_label': '此链接将自动失效',
            'guest.expired': '已失效',
            'guest.lang_switch': '切换语言',
            'guest.orders_heading': '订单',
            'guest.status_filter_label': '状态',
            'guest.status_all': '全部',
            'guest.no_image': '暂无图片',
            'guest.empty': '暂无可查看的订单',
            'guest.pdf_zip_title': '下载 PDF 压缩包',
            'guest.pdf_zip_note': '{count} 个文件 · 链接有效期内可下载',
            'guest.report_pdf_title': '生成 PDF 报告',
            'guest.report_pdf_calculating': '正在计算大小与预估时间…',
            'guest.order_subtitle': '临时查看 · 只读',
            'guest.back_orders': '返回订单',
            'guest.order_info': '订单资料',
            'guest.field.order': '订单',
            'guest.field.status': '状态',
            'guest.field.date': '日期',
            'guest.field.delivery': '预计交期',
            'guest.field.product': '产品',
            'guest.field.code': '编号',
            'guest.field.quantity': '数量',
            'guest.progress': '进度',
            'guest.history_detail': '查看详细历史',
            'guest.error.expired.title': '访问已过期',
            'guest.error.expired.subtitle': '此临时链接已过期，请向工作人员索取新的访问链接。',
            'guest.error.revoked.title': '访问已撤销',
            'guest.error.revoked.subtitle': '此临时链接已经失效。',
            'guest.error.network.title': '仅限公司局域网',
            'guest.error.network.subtitle': '此访问只能在授权的公司局域网内使用。',
            'guest.error.cloud.title': '暂不可用',
            'guest.error.cloud.subtitle': 'Cloud 模式不提供本地临时查看。',
            'guest.error.not_found.title': '无法访问',
            'guest.error.not_found.subtitle': '链接不存在，或内容已经不可用。',
            'guest.stage.order': '下单',
            'guest.stage.draft': '图稿',
            'guest.stage.sampling': '打样',
            'guest.stage.production': '生产',
            'guest.stage.shipping': '出货'
        },
        es: {
            'company': 'Hangzhou Kecheng Co., Ltd.',
            'system.name': 'Seguimiento de pedidos',
            'system.title': 'Sistema de seguimiento de pedidos',
            'lang.switch_to': 'Cambiar idioma',
            'nav.home': 'Inicio',
            'nav.create_workflow': 'Crear proceso',
            'nav.order_admin': 'Gestión de pedidos',
            'nav.user_admin': 'Usuarios',
            'nav.settings': 'Configuración',
            'nav.logout': 'Cerrar sesión',
            'mobile.search': 'Buscar cliente o número de pedido',
            'mobile.clear_search': 'Borrar búsqueda',
            'mobile.browse_mode': 'Modo de vista',
            'mobile.by_order': 'Por pedido',
            'mobile.by_customer': 'Por cliente',
            'filter.stage': 'Etapa',
            'filter.all': 'Todos',
            'filter.draft': 'Diseño',
            'filter.sample': 'Muestra',
            'filter.production': 'Producción',
            'filter.shipping': 'Envío',
            'stage.new_quote': 'Pedido / Cotización',
            'stage.draft': 'Diseño',
            'stage.sample': 'Muestra',
            'stage.production': 'Producción',
            'stage.shipping': 'Envío',
            'stage.waiting_confirm': 'Pendiente de confirmación',
            'stage.completed': 'Completado',
            'stage.cancelled': 'Cancelado',
            'stage.no_workflow': 'Sin proceso',
            'filter.salesperson': 'Vendedor',
            'search.desktop': 'Buscar pedido o cliente...',
            'search.salesperson': 'Buscar',
            'table.order_date': 'Fecha',
            'table.elapsed': 'Días',
            'table.order_number': 'N.º pedido',
            'table.customer': 'Cliente',
            'table.product_type': 'Tipo de producto',
            'table.product_code': 'Código',
            'table.quantity': 'Cantidad',
            'table.factory': 'Fábrica',
            'table.status': 'Etapa / Estado',
            'table.delivery': 'Entrega',
            'table.notes': 'Notas',
            'table.salesperson': 'Vendedor',
            'table.actions': 'Acciones',
            'table.loading': 'Cargando pedidos...',
            'filter.all_salespeople': 'Todos los vendedores',
            'filter.more': 'Más…',
            'filter.light': 'Semáforo',
            'light.normal': 'Normal',
            'light.warning': 'Atención',
            'light.overdue': 'Atrasado',
            'mobile.click_detail': 'Toca para ver detalles',
            'mobile.loading': 'Cargando pedidos…',
            'mobile.more': 'Mostrar más',
            'mobile.back_customers': 'Volver a clientes',
            'mobile.back_orders': 'Volver a pedidos',
            'mobile.order_detail': 'Detalle del pedido',
            'mobile.order_info': 'Datos del pedido',
            'mobile.timeline': 'Progreso',
            'mobile.timeline_order': 'Pedido',
            'mobile.timeline_draft': 'Diseño',
            'mobile.timeline_sample': 'Muestra',
            'mobile.timeline_production': 'Producción',
            'mobile.timeline_shipping': 'Envío',
            'mobile.product': 'Producto',
            'mobile.product_code': 'Código',
            'mobile.quantity': 'Cantidad',
            'mobile.factory': 'Fábrica',
            'mobile.order_date': 'Fecha de pedido',
            'mobile.delivery_date': 'Entrega prevista',
            'mobile.status_days': 'Etapa actual',
            'mobile.days': 'días',
            'mobile.salesperson': 'Vendedor',
            'mobile.current_status': 'Estado actual',
            'mobile.readonly_hint': 'Modo nube de solo lectura; muestra datos sincronizados',
            'mobile.loading_detail': 'Cargando detalle del pedido…',
            'mobile.detail_load_failed': 'No se pudo cargar el detalle del pedido',
            'mobile.no_value': '—',
            'mobile.select_salesperson': 'Elegir vendedor',
            'mobile.select_salesperson_hint': 'El filtro se aplica al seleccionar',
            'mobile.close': 'Cerrar',
            'mobile.no_orders': 'No hay pedidos que coincidan',
            'mobile.no_cloud_orders': 'Aún no hay pedidos sincronizados en la nube',
            'mobile.no_customers': 'No hay clientes que coincidan',
            'mobile.unassigned_customer': 'Cliente sin asignar',
            'mobile.latest': 'Último',
            'mobile.order_count': 'pedidos',
            'mobile.customer_count': 'clientes',
            'mobile.order_unit': 'ped.',
            'mobile.report.request': 'Solicitar informe completo',
            'mobile.report.queue_hint': 'Disponible al conectar TiDB',
            'mobile.report.generate': 'Generar informe',
            'mobile.report.all_orders': 'Informe de pedidos',
            'mobile.report.all_orders_hint': 'Usa el rango que estás viendo',
            'mobile.report.single': 'PDF de este pedido',
            'mobile.report.single_action': 'Generar / compartir este PDF',
            'mobile.report.single_hint': 'Solo incluye este pedido',
            'mobile.report.single_title': 'Informe de un solo pedido',
            'mobile.report.local_hint': 'Usa el PDF actual',
            'mobile.customer_link': 'Enlace de consulta',
            'mobile.customer_token': 'Token del cliente',
            'mobile.detail_missing_title': 'Aviso',
            'mobile.detail_missing': 'Este pedido no tiene un proceso disponible para abrir.',
            'mobile.report_cloud_title': 'Informe en la nube',
            'mobile.report_cloud_pending': 'La interfaz está preparada. Cuando se conecte TiDB report_requests, la solicitud se agregará a la cola. Por ahora no se mostrará como enviada.',
            'mobile.customer_link_title': 'Enlace de consulta del cliente',
            'mobile.customer_link_pending': ' tendrá su /c/<token> cuando se conecte la etapa de tokens de TiDB. El enlace todavía no existe.',
            'mobile.search_customer': 'Cliente',
            'mobile.search_order': 'Pedido',
            'mobile.images': 'Imágenes',
            'mobile.image': 'Imagen',
            'mobile.images_loading': 'Cargando imágenes…',
            'mobile.order_image': 'Pedido',
            'mobile.workflow_image': 'Proceso',
            'mobile.report.title': 'Informe completo del cliente',
            'mobile.report.subtitle': 'El PDF se genera en el servidor local',
            'mobile.report.queuing': 'Creando tarea PDF…',
            'mobile.report.generating': 'Generando PDF…',
            'mobile.report.keep_open': 'Puedes dejar esta pantalla abierta mientras termina',
            'mobile.report.ready': 'PDF listo',
            'mobile.report.open_pdf': 'Abrir PDF',
            'mobile.report.share': 'Compartir PDF',
            'mobile.report.download': 'Descargar',
            'mobile.report.failed': 'No se pudo generar el informe',
            'mobile.report.no_file': 'El informe terminó, pero no hay archivos disponibles',
            'mobile.report.no_orders': 'Este cliente no tiene pedidos disponibles para el informe',
            'cloud.title': 'Modo nube · solo lectura',
            'cloud.readonly_desc': 'Solo consulta. Para modificar pedidos, use el sistema local de la empresa.',
            'cloud.updated_at': 'Datos actualizados: ',
            'cloud.wait_first': 'Esperando primera sincronización',
            'cloud.no_data': 'Aún no se han conectado los pedidos de la nube',
            'login.browser_title': 'Ingresar - Seguimiento de pedidos',
            'login.welcome': 'Bienvenido',
            'login.prompt': 'Ingrese sus datos de acceso',
            'login.login': 'Ingresar',
            'login.register': 'Registrarse',
            'login.username': 'Usuario',
            'login.username_placeholder': 'Ingrese su usuario',
            'login.password': 'Contraseña',
            'login.password_placeholder': 'Ingrese su contraseña',
            'login.confirm_new_password': 'Confirmar nueva contraseña',
            'login.confirm_new_password_placeholder': 'Repita la nueva contraseña',
            'login.register_title': 'Registro de usuario',
            'login.register_prompt': 'La cuenta debe ser aprobada por un supervisor',
            'login.real_name': 'Nombre real *',
            'login.real_name_placeholder': 'Ingrese su nombre real',
            'login.register_username': 'Usuario de acceso *',
            'login.register_password': 'Contraseña *',
            'login.register_password_placeholder': 'Mínimo 6 caracteres',
            'login.confirm_password': 'Confirmar contraseña *',
            'login.confirm_password_placeholder': 'Repita la contraseña',
            'login.register_success': 'Registro exitoso. Espere la aprobación del supervisor antes de ingresar.',
            'login.cloud_note': 'Versión nube · datos sincronizados · solo consulta',
            'login.brand_title': 'Textiles de calidad,\nun futuro mejor',
            'login.brand_subtitle': 'Calidad, experiencia y confianza en cada producto, con seguimiento claro de cada pedido.',
            'login.exp_years': 'años de experiencia',
            'login.realtime': 'En vivo',
            'login.order_monitor': 'Seguimiento',
            'login.efficient': 'Eficiente',
            'login.flow_manage': 'Gestión de procesos',
            'login.password_mismatch': 'Las contraseñas no coinciden',
            'login.password_too_short': 'La contraseña debe tener al menos 6 caracteres',
            'login.register_failed': 'Error de registro',
            'guest.subtitle': 'Consulta temporal · solo sus pedidos',
            'guest.expiry_label': 'Este acceso caduca automáticamente',
            'guest.expired': 'Caducado',
            'guest.lang_switch': 'Cambiar idioma',
            'guest.orders_heading': 'Pedidos',
            'guest.status_filter_label': 'Estado',
            'guest.status_all': 'Todos',
            'guest.no_image': 'Sin imagen',
            'guest.empty': 'No hay pedidos disponibles',
            'guest.pdf_zip_title': 'Descargar PDF en ZIP',
            'guest.pdf_zip_note': '{count} archivo{plural} · disponible hasta que caduque este acceso',
            'guest.report_pdf_title': 'Preparar informe PDF',
            'guest.report_pdf_calculating': 'Calculando tamaño y tiempo aproximado…',
            'guest.order_subtitle': 'Consulta temporal · solo lectura',
            'guest.back_orders': 'Volver a pedidos',
            'guest.order_info': 'Información del pedido',
            'guest.field.order': 'Pedido',
            'guest.field.status': 'Estado',
            'guest.field.date': 'Fecha',
            'guest.field.delivery': 'Entrega estimada',
            'guest.field.product': 'Producto',
            'guest.field.code': 'Código',
            'guest.field.quantity': 'Cantidad',
            'guest.progress': 'Progreso',
            'guest.history_detail': 'Ver historial detallado',
            'guest.error.expired.title': 'Acceso caducado',
            'guest.error.expired.subtitle': 'Este enlace temporal ya caducó. Solicite un nuevo acceso.',
            'guest.error.revoked.title': 'Acceso revocado',
            'guest.error.revoked.subtitle': 'Este enlace temporal ya no está disponible.',
            'guest.error.network.title': 'Solo red local',
            'guest.error.network.subtitle': 'Este acceso solo funciona dentro de la red local autorizada.',
            'guest.error.cloud.title': 'No disponible',
            'guest.error.cloud.subtitle': 'Esta vista temporal no está disponible en el modo nube.',
            'guest.error.not_found.title': 'Acceso no disponible',
            'guest.error.not_found.subtitle': 'El enlace no existe o el contenido ya no está disponible.',
            'guest.stage.order': 'Pedido',
            'guest.stage.draft': 'Diseño',
            'guest.stage.sampling': 'Muestra',
            'guest.stage.production': 'Producción',
            'guest.stage.shipping': 'Envío'
        }
    };

    function normalizeLang(lang) {
        const value = String(lang || '').toLowerCase().replace('-', '_');
        if (value === 'es' || value.startsWith('es_')) return 'es';
        return 'zh_cn';
    }

    function getLanguage() {
        try {
            const saved = normalizeLang(localStorage.getItem(STORAGE_KEY));
            return SUPPORTED.has(saved) ? saved : DEFAULT_LANG;
        } catch (e) {
            return DEFAULT_LANG;
        }
    }

    function translate(key, vars) {
        const lang = getLanguage();
        const dict = TEXT[lang] || TEXT[DEFAULT_LANG];
        let value = dict[key] ?? TEXT[DEFAULT_LANG][key] ?? key;
        if (vars && typeof vars === 'object') {
            Object.keys(vars).forEach(name => {
                value = String(value).replaceAll(`{${name}}`, String(vars[name]));
            });
        }
        return value;
    }

    function apply(root) {
        const lang = getLanguage();
        document.documentElement.lang = lang === 'es' ? 'es' : 'zh-CN';

        (root || document).querySelectorAll('[data-i18n]').forEach(el => {
            const text = translate(el.dataset.i18n);
            if (el.dataset.i18nHtml === 'true') el.innerHTML = text;
            else el.textContent = text;
        });
        (root || document).querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            el.setAttribute('placeholder', translate(el.dataset.i18nPlaceholder));
        });
        (root || document).querySelectorAll('[data-i18n-aria]').forEach(el => {
            el.setAttribute('aria-label', translate(el.dataset.i18nAria));
        });
        (root || document).querySelectorAll('[data-status-key]').forEach(el => {
            if (typeof window.displayStatus === 'function') {
                el.textContent = window.displayStatus(el.dataset.statusKey, lang);
            }
        });
        (root || document).querySelectorAll('[data-lang-toggle]').forEach(el => {
            const label = el.querySelector('[data-lang-label]');
            const showCurrent = el.dataset.langDisplay === 'current';
            const buttonText = showCurrent
                ? (lang === 'es' ? 'ES' : '中文')
                : (lang === 'es' ? '中文' : 'ES');
            if (label) label.textContent = buttonText;
            else el.textContent = buttonText;
            el.title = translate('lang.switch_to');
            el.setAttribute('aria-label', translate('lang.switch_to'));
        });

        if (document.title && document.body?.classList.contains('login-body')) {
            document.title = translate('login.browser_title');
        }
    }

    function setLanguage(lang) {
        const next = normalizeLang(lang);
        try { localStorage.setItem(STORAGE_KEY, next); } catch (e) { /* ignore */ }
        apply(document);
        document.dispatchEvent(new CustomEvent('tracking:languagechange', { detail: { language: next } }));
        return next;
    }

    function toggleLanguage() {
        return setLanguage(getLanguage() === 'es' ? 'zh_cn' : 'es');
    }

    window.TRACKING_UI_I18N = TEXT;
    window.getTrackingLanguage = getLanguage;
    window.setTrackingLanguage = setLanguage;
    window.toggleTrackingLanguage = toggleLanguage;
    window.trackingT = translate;
    window.applyTrackingLanguage = apply;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => apply(document));
    } else {
        apply(document);
    }
})();

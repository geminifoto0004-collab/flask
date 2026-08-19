"""
訂單流程追蹤系統 - 配置文件
"""
import os

# 基礎配置
SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-in-production-2026'
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'jwt-secret-key-change-in-production-2026'
JWT_EXPIRATION_DELTA = 7 * 24 * 60 * 60  # 7天

# 數據庫配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {'1', 'true', 'yes', 'on', 'y'}


# ==================== Render / Cloud 模式 ====================
# 本機預設完全不變；Render 由父 Flask 或環境變數開啟。
CLOUD_MODE = _env_bool('TRACKING_CLOUD_MODE', False)
CLOUD_READ_ONLY = _env_bool('TRACKING_CLOUD_READ_ONLY', CLOUD_MODE)
# ============================================================

# ==================== 數據存放路徑 ====================
# DATA_DIR：數據庫和上傳文件的存放位置
# 
# 【默認】留空 = 存在 order_tracking 文件夾內部（適合國內獨立使用）
# 【自定義】填入絕對路徑 = 存在指定位置（適合公司部署，代碼和數據分離）
#
# 範例：
#   DATA_DIR_CUSTOM = ''                          ← 默認，存在代碼內
#   DATA_DIR_CUSTOM = r'D:\KECHEN_DATA'           ← 存在 D 盤
#   DATA_DIR_CUSTOM = r'C:\Users\PC\Documents\tracking_data'
#
# 本機正式資料路徑永遠保留定義；不同電腦不需要手動註解或修改。
# Cloud / Render 模式不會使用這個本機正式路徑。
DATA_DIR_CUSTOM = r'E:\upload_xingwang'
# ==================== 海外模式 ====================
# True  = 國外使用（顯示 WhatsApp 按鈕，從 Flask /contacto API 拿電話）
# False = 國內使用（不顯示，不呼叫任何外部 API）
IS_OVERSEAS = True
# ==================================================

# ==================== 部署 / 雲端資源安全閘門 ====================
# 重要：這些開關控制「這個部署允許使用什麼功能」，但任何 TiDB / B2 / Render
# 的真正憑證都必須只放在環境變數或雲端 Secret 中，絕對不要寫進這個專案。
# 這樣即使完整原始碼被複製，沒有你控制的外部憑證仍然無法使用你的雲端資源。
DEPLOYMENT_PROFILE = (os.environ.get('TRACKING_DEPLOYMENT_PROFILE') or ('OVERSEAS' if IS_OVERSEAS else 'CHINA')).strip().upper()
IS_CHINA_DEPLOYMENT = DEPLOYMENT_PROFILE in {'CHINA', 'CN', 'DOMESTIC'}
IS_OVERSEAS_DEPLOYMENT = not IS_CHINA_DEPLOYMENT

# LAN Guest 可以獨立開關。中國版如不需要，直接在環境變數設 0。
LOCAL_GUEST_SHARING_ENABLED = _env_bool('TRACKING_LOCAL_GUEST_SHARING_ENABLED', True)
LOCAL_GUEST_PERMANENT_ENABLED = _env_bool('TRACKING_LOCAL_GUEST_PERMANENT_ENABLED', IS_OVERSEAS_DEPLOYMENT)

# 雲端總閘門預設關閉；官方海外部署必須在部署環境中明確開啟。
CLOUD_RESOURCE_ACCESS_ENABLED = _env_bool('TRACKING_CLOUD_RESOURCE_ACCESS_ENABLED', False) and IS_OVERSEAS_DEPLOYMENT
TIDB_PROVIDER_ENABLED = _env_bool('TRACKING_TIDB_PROVIDER_ENABLED', False) and CLOUD_RESOURCE_ACCESS_ENABLED
B2_PROVIDER_ENABLED = _env_bool('TRACKING_B2_PROVIDER_ENABLED', False) and CLOUD_RESOURCE_ACCESS_ENABLED
RENDER_PUBLIC_GUEST_ENABLED = _env_bool('TRACKING_RENDER_PUBLIC_GUEST_ENABLED', False) and CLOUD_RESOURCE_ACCESS_ENABLED
PERMANENT_PUBLIC_GUEST_ENABLED = _env_bool('TRACKING_PERMANENT_PUBLIC_GUEST_ENABLED', False) and RENDER_PUBLIC_GUEST_ENABLED

# 公網分享 Provider 的實作尚未放在共用 order_tracking 核心裡。
# 父 Flask / Render 部署完成 Provider 後再設為 1；共用代碼不會假裝已經能發布 B2。
PUBLIC_SHARE_PROVIDER_READY = _env_bool('TRACKING_PUBLIC_SHARE_PROVIDER_READY', False) and RENDER_PUBLIC_GUEST_ENABLED and B2_PROVIDER_ENABLED and TIDB_PROVIDER_ENABLED
PUBLIC_SHARE_BACKGROUND_SYNC_ENABLED = _env_bool('TRACKING_PUBLIC_SHARE_BACKGROUND_SYNC_ENABLED', False) and PUBLIC_SHARE_PROVIDER_READY
PUBLIC_SHARE_SYNC_START_DELAY_SECONDS = max(30, int(os.environ.get('TRACKING_PUBLIC_SHARE_SYNC_START_DELAY_SECONDS', 90)))
PUBLIC_SHARE_SYNC_INTERVAL_SECONDS = max(3600, int(os.environ.get('TRACKING_PUBLIC_SHARE_SYNC_INTERVAL_SECONDS', 6 * 3600)))
# ================================================================
# ==================================================

if CLOUD_MODE:
    DATA_DIR = (
        os.environ.get('TRACKING_DATA_DIR', '').strip()
        or os.path.join(
            os.environ.get('TMPDIR')
            or os.environ.get('TEMP')
            or '/tmp',
            'order_tracking_cloud'
        )
    )
else:
    DATA_DIR = DATA_DIR_CUSTOM if os.path.isdir(DATA_DIR_CUSTOM) else BASE_DIR

DATABASE_PATH = os.path.join(DATA_DIR, 'data', 'tracking.db')

# 藍圖配置
BLUEPRINT_NAME = 'tracking_bp'
URL_PREFIX = '/tracking'

# ==================== 燈號規則配置（天數）====================
# 核心原则：监控每个阶段的停留时间
# 🟢 绿灯 = 正常进行中
# 🟡 黄灯 = 停留时间有点久了，该注意了
# 🔴 红灯 = 停留太久了，必须处理！

LIGHT_RULES = {
    # ===== 等客户回复的状态（比较紧迫）=====
    
    'new_order': {
        # 新订单/询价刚进来
        'yellow_days': 5,      # 5天变黄：该跟进了
        'red_days': 7,         # 7天变红：客户可能不感兴趣了
        'description': '新订单 - 刚收到询价'
    },
    
    'quote_confirming': {
        # 报价已发出，等客户确认
        'yellow_days': 4,      # 4天变黄：该追问客户了
        'red_days': 7,         # 7天变红：很紧迫，必须追！
        'description': '报价待确认 - 等国外客户回复报价'
    },
    
    'draft_confirm': {
        # 图稿已发出，等客户确认
        'yellow_days': 3,      # 3天变黄：该催客户看图了
        'red_days': 5,         # 5天变红：必须催！
        'description': '图稿待确认 - 等国外客户确认图稿'
    },
    
    'draft_revising': {
        # 客户要求修改图稿，我们在改
        'yellow_days': 2,      # 2天变黄：改得有点慢
        'red_days': 4,         # 4天变红：太慢了
        'description': '图稿修改中 - 国内修改图稿'
    },
    
    'sampling_confirm': {
        # 样品已寄出，等客户确认
        'yellow_days': 2,      # 2天变黄：该问问收到没
        'red_days': 4,         # 4天变红：要追问！
        'description': '打样待确认 - 等国外客户确认样品'
    },
    
    'sample_revising': {
        # 客户要求修改样品，我们在改
        'yellow_days': 3,      # 3天变黄
        'red_days': 5,         # 5天变红
        'description': '打样修改中 - 国内修改样品'
    },
    
    # ===== 我们这边处理的状态（相对宽松）=====
    
    'ready_sample': {
        # 图稿确认了，等待开始打样
        'yellow_days': 5,      # 5天变黄：该安排了
        'red_days': 7,         # 7天变红：太慢了
        'description': '待打样 - 国内准备打样'
    },
    
    'sampling_process': {
        # 正在打样中
        'yellow_days': 10,     # 10天变黄：有点久
        'red_days': 15,        # 15天变红：太久了，检查问题
        'description': '打样中 - 国内正在制作样品'
    },
    
    'ready_production': {
        # 样品确认了，等待开始生产
        'yellow_days': 3,      # 3天变黄：该催工厂了
        'red_days': 5,         # 5天变红：必须催！
        'description': '待生产 - 等工厂排产'
    },
    
    'producing': {
        # 正在生产中
        'yellow_days': 14,     # 14天变黄：稍长，关注进度
        'red_days': 21,        # 21天变红：异常，检查问题
        'description': '生产中 - 工厂正在生产'
    },
    
    # ===== 其他 =====
    
    'revision': {
        # 修图需求
        'yellow_days': 3,
        'red_days': 5,
        'description': '修图中'
    },
    
    # 暂时保留（虽然不推荐使用，但 models.py 还在引用）
    'delivery_warning_days': 3  # 距离交货日期3天内警告
}

# 注意：delivery_warning_days 已不推荐使用
# 原因：交货日期往往不准确（询价、图稿阶段客户拖延会导致超期）
# 建议只监控每个阶段的停留时间，这样更准确
# 等 models.py 更新后可以移除

# 上傳配置（預留）
UPLOAD_FOLDER = os.path.join(DATA_DIR, 'uploads')
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB

# 確保目錄存在
os.makedirs(os.path.join(DATA_DIR, 'data'), exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, 'cache', 'media_previews'), exist_ok=True)

# ==================== 客戶訂單報告 ====================
# PDF / Word 單檔超過此大小時會自動拆分；Excel 固定維持單一檔案。
CUSTOMER_REPORT_MAX_BYTES = 50 * 1024 * 1024  # 50 MB; 17 MB 等一般客戶報告不需要拆檔
CUSTOMER_REPORT_IMAGE_MAX_EDGE = 1200
CUSTOMER_REPORT_JPEG_QUALITY = 75
CUSTOMER_REPORT_CACHE_HOURS = 2
CUSTOMER_REPORT_WORKERS = 2  # 同时生成 2 个客户报告，其余自动排队
# 等待中的任务最多 30 个；processing 不计入此数字，因此总 active 上限约为 30 + workers。
CUSTOMER_REPORT_MAX_QUEUED = 30
# 单一登入账号最多同时拥有 5 个 queued/processing 任务，避免一个人塞满全系统。
CUSTOMER_REPORT_MAX_ACTIVE_PER_USER = 5
CUSTOMER_REPORT_CACHE_DIR = os.path.join(DATA_DIR, 'exports', 'customer_reports')

# ==================== 手机 / Guest 媒体预览缓存 ====================
# 只缓存“可重新生成”的缩略图 / PDF 页预览，不缓存订单清单、附件清单或业务数据。
# 每次进入页面仍重新查询 SQLite / 附件列表，因此新增、删除、替换附件会立即被发现。
MEDIA_PREVIEW_CACHE_DIR = os.path.join(DATA_DIR, 'cache', 'media_previews')
MEDIA_PREVIEW_CACHE_MAX_BYTES = int(os.environ.get('TRACKING_MEDIA_CACHE_MAX_BYTES', 3 * 1024 * 1024 * 1024))
MEDIA_PREVIEW_CACHE_RETENTION_DAYS = int(os.environ.get('TRACKING_MEDIA_CACHE_RETENTION_DAYS', 14))
MEDIA_PREVIEW_CACHE_CLEANUP_INTERVAL_SECONDS = int(os.environ.get('TRACKING_MEDIA_CACHE_CLEANUP_INTERVAL_SECONDS', 600))
MEDIA_PREVIEW_WORKERS = max(1, int(os.environ.get('TRACKING_MEDIA_PREVIEW_WORKERS', 2)))
# ================================================================

# ==================== 開發者 / 管理員診斷工具 ====================
# True  = 所有管理員可看到「系統診斷」頁面
# False = 側邊欄不顯示，診斷網址也直接視為不存在
DEVELOPER_TOOLS_ENABLED = False
# ================================================================

# ==================== SQLite 安全快照 ====================
# 使用 SQLite online backup API 產生一致性副本，再經 integrity_check 後原子改名。
# 程式啟動只啟動排程器，不會立刻備份；到以下時間才自動執行。
SNAPSHOT_ENABLED = not CLOUD_MODE
SNAPSHOT_DIR = os.path.join(DATA_DIR, 'sync_snapshot')
SNAPSHOT_SCHEDULE_HOURS = (2, 14)  # 伺服器本機時間：02:00、14:00
SNAPSHOT_RETENTION_DAYS = 14
SNAPSHOT_RETENTION_COUNT = 20
SNAPSHOT_START_DELAY_SECONDS = 5
# ========================================================

# ==================== 通知自動清理 ====================
# notification_visible_days 同時作為「顯示天數」與「資料庫保留天數」。
# 超過該天數的通知會由背景排程真正刪除。
NOTIFICATION_CLEANUP_ENABLED = not CLOUD_MODE
NOTIFICATION_CLEANUP_HOUR = 3
NOTIFICATION_CLEANUP_MINUTE = 15
NOTIFICATION_CLEANUP_BATCH_SIZE = 5000

# 一次性維護：部署此版本後首次啟動，在背景先建立安全快照，
# 再清除過期通知並 VACUUM 一次。成功後會在 system_settings 寫入標記，
# 所以後續重新啟動不會重複 VACUUM。之後可改為正式日期排程。
STARTUP_VACUUM_ONCE_ENABLED = not CLOUD_MODE
STARTUP_VACUUM_ONCE_KEY = 'maintenance_vacuum_once_20260816'
# ======================================================

"""
Flask 授權管理系統 - 配置管理
集中管理環境變數、常量、密碼規則
"""

import os
import hashlib

# 加載 .env 文件（如果存在）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 如果 python-dotenv 未安裝，跳過（不影響生產環境）
    pass


# ========== 基礎配置 ==========
class Config:
    """基礎配置類"""
    
    # Flask 密鑰（必須設置，用於 session 加密）
    # ⚠️ 安全提示：生產環境必須設置環境變數 SECRET_KEY！
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # 如果使用默認值，發出警告
    if SECRET_KEY == 'dev-secret-key-change-in-production':
        import warnings
        warnings.warn("⚠️  使用默認 SECRET_KEY，生產環境請務必設置環境變數！", UserWarning)
    
    # 資料庫配置
    # 資料庫類型：'sqlite'、'postgresql' 或 'mysql'/'tidb'
    # PythonAnywhere 使用 'sqlite'，Render 使用 'postgresql'，TiDB Cloud 使用 'mysql' 或 'tidb'
    # 支持兩種環境變數名稱：DATABASE_TYPE 或 DB_TYPE
    DATABASE_TYPE = os.environ.get('DATABASE_TYPE') or os.environ.get('DB_TYPE', 'sqlite')
    DATABASE_TYPE = DATABASE_TYPE.lower()
    
    # SQLite 資料庫路徑（僅當 DATABASE_TYPE='sqlite' 時使用）
    DATABASE_PATH = os.environ.get(
        'DATABASE_PATH', 
        os.path.join(os.path.dirname(__file__), 'databases', 'app.db')
    )
    
    # PostgreSQL/MySQL/TiDB 連接字符串（當 DATABASE_TYPE='postgresql' 或 'mysql'/'tidb' 時使用）
    # Render PostgreSQL 會自動提供 DATABASE_URL 環境變數
    # TiDB Cloud 連接字符串格式：mysql://user:password@host:port/database
    # 或者分別設置：MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
    # 或者使用簡短名稱：DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
    DATABASE_URL = os.environ.get('DATABASE_URL', '')
    
    # MySQL/TiDB 單獨配置（可選，如果 DATABASE_URL 為空時使用）
    # 支持兩種環境變數名稱：MYSQL_* 或 DB_*
    MYSQL_HOST = os.environ.get('MYSQL_HOST') or os.environ.get('DB_HOST', 'localhost')
    MYSQL_PORT = int(os.environ.get('MYSQL_PORT') or os.environ.get('DB_PORT', '4000'))  # TiDB 默認端口 4000
    MYSQL_USER = os.environ.get('MYSQL_USER') or os.environ.get('DB_USER', '')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD') or os.environ.get('DB_PASSWORD', '')
    MYSQL_DATABASE = os.environ.get('MYSQL_DATABASE') or os.environ.get('DB_NAME', '')
    
    # Session 配置
    PERMANENT_SESSION_LIFETIME = 3600  # 1小時（秒）
    SESSION_COOKIE_SECURE = False  # 開發環境設為 False，生產環境改 True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'


# ========== 管理員配置 ==========
class AdminConfig:
    """管理員相關配置"""
    
    # ========== 超級管理員帳號密碼設定（不可修改、不可刪除）==========
    # 
    # 🔐 安全提示：請務必通過環境變數設置帳號和密碼，不要使用硬編碼！
    # 
    # ⚠️ 必須設置的環境變數：
    #   - SUPER_ADMIN_EMAIL：超級管理員郵箱（帳號）
    #   - SUPER_ADMIN_PASSWORD：超級管理員密碼
    # 
    # 💡 設置方法：
    #   1. 本地開發：創建 .env 文件（見 .env.example）
    #   2. Render：在 Environment 標籤中設置
    #   3. PythonAnywhere：在 Web 設置中設置環境變數
    # 
    # 📖 詳見: HOW_TO_CHANGE_ADMIN_PASSWORD.md
    
    # 從環境變數讀取，如果未設置則拋出錯誤（生產環境必須設置）
    SUPER_ADMIN_EMAIL = os.environ.get('SUPER_ADMIN_EMAIL')
    SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD')
    
    # 開發環境的默認值（僅用於本地開發，生產環境必須設置環境變數）
    if not SUPER_ADMIN_EMAIL:
        import warnings
        warnings.warn("⚠️  SUPER_ADMIN_EMAIL 未設置，使用默認值（僅用於開發）", UserWarning)
        SUPER_ADMIN_EMAIL = 'admin@xingwang.com'  # 僅開發環境默認值
    
    if not SUPER_ADMIN_PASSWORD:
        import warnings
        warnings.warn("⚠️  SUPER_ADMIN_PASSWORD 未設置，使用默認值（僅用於開發）", UserWarning)
        SUPER_ADMIN_PASSWORD = '12345678'  # 僅開發環境默認值
    SUPER_ADMIN_USERNAME = 'super_admin'  # 超級管理員用戶名（固定值，通常不需要修改）
    SUPER_ADMIN_ROLE = 'super_admin'  # 超級管理員角色名稱（固定值，不可修改）
    
    # 超級管理員密碼的 SHA256 hash
    SUPER_ADMIN_PASSWORD_HASH = hashlib.sha256(SUPER_ADMIN_PASSWORD.encode()).hexdigest()
    
    # 向後兼容的別名
    ADMIN_EMAIL = SUPER_ADMIN_EMAIL
    ADMIN_PASSWORD = SUPER_ADMIN_PASSWORD
    ADMIN_PASSWORD_HASH = SUPER_ADMIN_PASSWORD_HASH


# ========== SMTP 郵件配置 ==========
class EmailConfig:
    """郵件服務配置"""
    
    # 郵件服務提供商選擇（可以通過環境變數設置）
    # 選項：
    #   - 'auto'（推薦）：自動檢測，優先使用 SMTP，如果失敗一次後自動切換到 Resend API（並記住，避免重複嘗試）
    #   - 'smtp'：只使用 SMTP（本機開發推薦）
    #   - 'resend'：只使用 Resend API（Render 上推薦）
    # 
    # 💡 提示：如果知道 SMTP 不可用（如 Render），可以在 Render 環境變數中設置：
    #   - EMAIL_PROVIDER=resend（直接使用 Resend API）
    #   或
    #   - SMTP_FAILED=1（在 auto 模式下永久跳過 SMTP）
    # 從環境變數讀取 EMAIL_PROVIDER，如果未設置則默認為 'auto'
    _email_provider_env = os.environ.get('EMAIL_PROVIDER', 'auto')
    EMAIL_PROVIDER = _email_provider_env.lower() if _email_provider_env else 'auto'
    # 調試信息（生產環境可以移除）
    if _email_provider_env and _email_provider_env.lower() != 'auto':
        print(f"[Config] EMAIL_PROVIDER 從環境變數讀取: {EMAIL_PROVIDER}")
    else:
        print(f"[Config] EMAIL_PROVIDER 使用默認值: {EMAIL_PROVIDER} (環境變數: {_email_provider_env})")
    
    # Resend API 配置（不受 Render 網絡限制）
    # 如果設置了 RESEND_API_KEY，可以作為 SMTP 的備選方案
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
    RESEND_FROM_EMAIL = os.environ.get('RESEND_FROM_EMAIL', '')  # 發送郵件的地址（需要在 Resend 驗證）
    
    # 如果環境變數未設置，可以在這裡直接設置（僅用於本地開發）
    if not RESEND_API_KEY:
        RESEND_API_KEY = 're_BMeetzHZ_HMFb9HRSihVcujLrtterRD9x'  # 👈 你的 Resend API Key
    if not RESEND_FROM_EMAIL:
        RESEND_FROM_EMAIL = 'onboarding@resend.dev'  # 👈 改為你在 Resend 驗證的發送地址
    
    # Gmail SMTP 設定（可以通過環境變數覆蓋，作為備選方案）
    # 在 Render 上如果 Gmail 無法訪問，可以嘗試：
    # 1. 使用其他 SMTP 服務（如 SendGrid、Mailgun）
    # 2. 或嘗試不同的端口（465 或 587）
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))  # 支持環境變數，默認 587
    SMTP_USE_TLS = True
    
    # 郵件帳號配置
    # 優先從環境變數讀取，如果未設置則使用下面的硬編碼值
    # ⚠️ 安全提示：生產環境建議使用環境變數，本地開發可以直接在這裡設置
    SMTP_EMAIL = os.environ.get('SMTP_EMAIL', '')  # 如果環境變數未設置，改為你的 Gmail 地址
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')  # 如果環境變數未設置，改為你的 Gmail 應用密碼
    
    # 如果環境變數未設置，可以在這裡直接設置（僅用於本地開發）
    # ⚠️ 注意：如果使用 Gmail，需要使用「應用程式密碼」，不是 Gmail 登入密碼！
    # 獲取方法：https://myaccount.google.com/apppasswords
    if not SMTP_EMAIL:
        SMTP_EMAIL = 'geminifoto0004@gmail.com'  # 👈 改為你的 Gmail 地址
    if not SMTP_PASSWORD:
        SMTP_PASSWORD = 'pczr wlzh uxxl ozot'  # 👈 改為你的 Gmail 應用密碼（16位，原本文檔中的格式）
    
    # Gmail 應用密碼處理：保留原始格式（在發送郵件時會自動嘗試兩種格式：去掉空格和保留空格）
    # 這樣可以兼容兩種情況：
    # 1. 如果密碼是 'pczr wlzh uxxl ozot'（帶空格），會先嘗試 'pczrwlzhuxxlozot'（去掉空格）
    # 2. 如果去掉空格失敗，會再嘗試保留空格的原始格式
    
    # 如果仍未設置，發出警告
    if not SMTP_EMAIL or not SMTP_PASSWORD or SMTP_EMAIL == 'your@gmail.com' or SMTP_PASSWORD == 'your-app-password':
        import warnings
        warnings.warn("⚠️  SMTP_EMAIL 或 SMTP_PASSWORD 未設置，郵件功能可能無法使用", UserWarning)
    
    # 驗證碼配置
    CODE_LENGTH = 6  # 驗證碼長度
    CODE_EXPIRE_MINUTES = 10  # 驗證碼有效期（分鐘）
    
    # 郵件模板
    EMAIL_TEMPLATES = {
        'registration': {
            'subject': '【星旺系統】用戶註冊驗證碼',
            'body': '''
                <h2>歡迎註冊星旺系統</h2>
                <p>您的註冊驗證碼: <strong style="font-size:24px; color:#2196F3;">{code}</strong></p>
                <p>有效期: {expire_minutes} 分鐘</p>
                <p>請在註冊頁面輸入此驗證碼完成註冊。</p>
                <p>如非本人操作，請忽略此郵件。</p>
            '''
        },
        'verification': {
            'subject': '【星旺系統】郵箱驗證碼',
            'body': '''
                <h2>您的驗證碼</h2>
                <p>驗證碼: <strong style="font-size:24px; color:#2196F3;">{code}</strong></p>
                <p>有效期: {expire_minutes} 分鐘</p>
                <p>如非本人操作，請忽略此郵件。</p>
            '''
        },
        'reset_password': {
            'subject': '【星旺系統】密碼重置驗證碼',
            'body': '''
                <h2>密碼重置</h2>
                <p>驗證碼: <strong style="font-size:24px; color:#FF5722;">{code}</strong></p>
                <p>有效期: {expire_minutes} 分鐘</p>
                <p><strong>警告：</strong>如非本人操作，請立即聯繫管理員！</p>
            '''
        }
    }


# ========== 密碼規則配置 ==========
class PasswordConfig:
    """密碼驗證規則"""
    
    MIN_LENGTH = 8  # 最小長度
    MAX_LENGTH = 128  # 最大長度
    
    # 密碼要求
    REQUIRE_UPPERCASE = False  # 不需要大寫字母
    REQUIRE_LOWERCASE = False  # 不需要小寫字母
    REQUIRE_DIGIT = True  # 需要數字
    REQUIRE_SPECIAL = False  # 不強制特殊字符
    
    # 特殊字符列表
    SPECIAL_CHARS = '!@#$%^&*()_+-=[]{}|;:,.<>?'


# ========== 授權狀態配置 ==========
class LicenseConfig:
    """授權相關配置"""
    
    # 授權狀態
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_EXPIRED = 'expired'
    
    VALID_STATUSES = [STATUS_ACTIVE, STATUS_INACTIVE, STATUS_EXPIRED]
    
    # 默認授權期限（天）
    DEFAULT_EXPIRE_DAYS = 365


# ========== 日誌配置 ==========
class LogConfig:
    """日誌配置"""
    
    LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
    LOG_FILE = 'app.log'
    LOG_LEVEL = 'INFO'  # DEBUG, INFO, WARNING, ERROR
    
    # 日誌格式
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'


# ========== 功能開關 ==========
class FeatureFlags:
    """功能開關（控制預留功能）"""
    
    # 用戶自助註冊
    ENABLE_USER_REGISTRATION = True
    
    # 郵件驗證功能
    ENABLE_EMAIL_VERIFICATION = True
    
    # API 速率限制
    ENABLE_RATE_LIMIT = False


# ========== 導出配置實例 ==========
# 創建配置實例供其他模組使用
config = Config()
admin_config = AdminConfig()
email_config = EmailConfig()
password_config = PasswordConfig()
license_config = LicenseConfig()
log_config = LogConfig()
feature_flags = FeatureFlags()


# ========== 驗證配置 ==========
def validate_config():
    """驗證必要的配置是否存在"""
    errors = []
    warnings = []
    
    # 檢查 SMTP 配置（如果啟用郵件功能）
    if feature_flags.ENABLE_EMAIL_VERIFICATION:
        if not email_config.SMTP_EMAIL:
            errors.append("⚠️  未設置 SMTP_EMAIL 環境變數")
        if not email_config.SMTP_PASSWORD:
            errors.append("⚠️  未設置 SMTP_PASSWORD 環境變數")
    
    # 超級管理員配置說明（帳號和密碼都在 config.py 第 44-45 行）
    print(f"✅ 超級管理員配置：郵箱={admin_config.SUPER_ADMIN_EMAIL}，密碼已設置（可在 config.py 第 44-45 行查看/修改）")
    
    # 檢查資料庫路徑
    db_dir = os.path.dirname(config.DATABASE_PATH)
    if not os.path.exists(db_dir):
        errors.append(f"⚠️  資料庫目錄不存在: {db_dir}")
    
    # 檢查日誌目錄
    if not os.path.exists(log_config.LOG_DIR):
        try:
            os.makedirs(log_config.LOG_DIR)
            print(f"✅ 已創建日誌目錄: {log_config.LOG_DIR}")
        except Exception as e:
            errors.append(f"⚠️  無法創建日誌目錄: {e}")
    
    return errors, warnings


# ========== 啟動時驗證 ==========
if __name__ == '__main__':
    print("=" * 50)
    print("配置驗證")
    print("=" * 50)
    
    errors, warnings = validate_config()
    
    if errors:
        print("\n❌ 配置錯誤：")
        for error in errors:
            print(f"  {error}")
    
    if warnings:
        print("\n⚠️  安全提示：")
        for warning in warnings:
            print(f"  {warning}")
    
    if not errors:
        print("\n✅ 配置驗證通過！")
    
    print("\n當前配置：")
    print(f"  資料庫路徑: {config.DATABASE_PATH}")
    print(f"  SMTP 郵箱: {email_config.SMTP_EMAIL or '未設置'}")
    print(f"  超級管理員郵箱: {admin_config.SUPER_ADMIN_EMAIL}")
    print(f"  超級管理員密碼: ***（可在 config.py 第 45 行查看/修改）")
    print(f"  用戶註冊: {'啟用' if feature_flags.ENABLE_USER_REGISTRATION else '關閉'}")
    print(f"  郵件驗證: {'啟用' if feature_flags.ENABLE_EMAIL_VERIFICATION else '關閉'}")
    print("\n💡 修改帳號密碼：")
    print("  直接編輯 config.py 第 44-45 行即可")
    print("  詳見: HOW_TO_CHANGE_ADMIN_PASSWORD.md")
    print("=" * 50)
"""
Flask 授權管理系統 - 配置管理
集中管理環境變數、常量、密碼規則
"""

import os
import hashlib


# ========== 基礎配置 ==========
class Config:
    """基礎配置類"""
    
    # Flask 密鑰
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    
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
    # 🔐 修改帳號和密碼：直接修改下面的值即可
    #   - 修改郵箱（帳號）：修改 SUPER_ADMIN_EMAIL 的值
    #   - 修改密碼：修改 SUPER_ADMIN_PASSWORD 的值
    #   修改後保存文件，重啟應用即可生效
    #   詳見: HOW_TO_CHANGE_ADMIN_PASSWORD.md
    #
    # 💡 提示：這裡設定的值就是登入時使用的帳號和密碼
    # 💡 也可以通過環境變數設置（優先級更高）：
    #   - SUPER_ADMIN_EMAIL 環境變數
    #   - SUPER_ADMIN_PASSWORD 環境變數
    
    SUPER_ADMIN_EMAIL = os.environ.get('SUPER_ADMIN_EMAIL', 'admin@xingwang.com')  # 超級管理員郵箱（帳號）- 可通過環境變數設置
    SUPER_ADMIN_PASSWORD = os.environ.get('SUPER_ADMIN_PASSWORD', '12345678')  # 超級管理員密碼 - 可通過環境變數設置
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
    
    # Gmail SMTP 設定
    SMTP_SERVER = 'smtp.gmail.com'
    SMTP_PORT = 587
    SMTP_USE_TLS = True
    
    # 郵件帳號（從環境變數讀取，或使用預設值）
    SMTP_EMAIL = os.environ.get('SMTP_EMAIL', 'geminifoto0004@gmail.com')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', 'pczr wlzh uxxl ozot')
    
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
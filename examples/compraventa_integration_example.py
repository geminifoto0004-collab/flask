"""
compraventa_MULTICUENTA.py 集成示例
展示如何替換硬編碼參數為動態配置
"""

# 在你的 compraventa_MULTICUENTA.py 文件頂部添加這些導入
from utils.simple_config_manager import (
    simple_config_manager, 
    get_dynamic_config, 
    get_parallel_limits,
    is_batch_enabled,
    is_advanced_processing_enabled
)

# ========== 替換硬編碼參數 ==========

# 原來的硬編碼參數（第33-38行）
# MAX_CONCURRENT_DOWNLOADS = 10
# MAX_CONCURRENT_PROCESAR_VENTA = 10
# MAX_CONCURRENT_PROCESAR_COMPRA = 5
# MAX_CONCURRENT_VENTA = 10
# MAX_CONCURRENT_COMPRA = 50

# 替換為動態配置
def init_dynamic_config():
    """初始化動態配置"""
    global MAX_CONCURRENT_DOWNLOADS
    global MAX_CONCURRENT_PROCESAR_VENTA
    global MAX_CONCURRENT_PROCESAR_COMPRA
    global MAX_CONCURRENT_VENTA
    global MAX_CONCURRENT_COMPRA
    
    # 設置 API Token（從你的登入系統獲取）
    # simple_config_manager.set_api_token("your_jwt_token_here")
    
    # 獲取動態配置
    config = get_dynamic_config()
    
    # 更新全局變量
    MAX_CONCURRENT_DOWNLOADS = config['max_concurrent_downloads']
    MAX_CONCURRENT_PROCESAR_VENTA = config['max_concurrent_procesar_venta']
    MAX_CONCURRENT_PROCESAR_COMPRA = config['max_concurrent_procesar_compra']
    MAX_CONCURRENT_VENTA = config['max_concurrent_venta']
    MAX_CONCURRENT_COMPRA = config['max_concurrent_compra']
    
    print(f"✅ 動態配置已載入:")
    print(f"   最大並行下載: {MAX_CONCURRENT_DOWNLOADS}")
    print(f"   最大並行處理 VENTA: {MAX_CONCURRENT_PROCESAR_VENTA}")
    print(f"   最大並行處理 COMPRA: {MAX_CONCURRENT_PROCESAR_COMPRA}")
    print(f"   最大並行 VENTA 內部: {MAX_CONCURRENT_VENTA}")
    print(f"   最大並行 COMPRA 內部: {MAX_CONCURRENT_COMPRA}")


# ========== 在 BusinessApp 類中使用 ==========

class BusinessAppWithDynamicConfig:
    """帶有動態配置的 BusinessApp 示例"""
    
    def __init__(self, root):
        self.root = root
        
        # 初始化動態配置
        init_dynamic_config()
        
        # 其他初始化代碼...
        self.setup_ui()
    
    def setup_ui(self):
        """設置 UI（示例）"""
        # 檢查功能權限
        if is_batch_enabled():
            print("✅ 批次下載功能已啟用")
        else:
            print("❌ 批次下載功能未啟用")
        
        if is_advanced_processing_enabled():
            print("✅ 高級處理功能已啟用")
        else:
            print("❌ 高級處理功能未啟用")
    
    def update_config_on_demand(self):
        """按需更新配置（可以在應用運行時調用）"""
        print("🔄 更新配置...")
        init_dynamic_config()
        print("✅ 配置已更新")


# ========== 在現有方法中使用動態配置 ==========

def descargar_todos_mes_with_config(self):
    """使用動態配置的批次下載方法示例"""
    
    # 檢查批次功能是否啟用
    if not is_batch_enabled():
        print("❌ 批次下載功能未啟用")
        return
    
    # 獲取當前配置
    config = get_parallel_limits()
    max_downloads = config['max_concurrent_downloads']
    
    print(f"開始批次下載，最大並行數: {max_downloads}")
    
    # 使用動態配置進行下載
    # 原來的代碼邏輯保持不變，只是使用動態參數
    pass


def procesar_todos_with_config(self):
    """使用動態配置的批次處理方法示例"""
    
    # 檢查批次功能是否啟用
    if not is_batch_enabled():
        print("❌ 批次處理功能未啟用")
        return
    
    # 獲取當前配置
    config = get_parallel_limits()
    max_venta = config['max_concurrent_procesar_venta']
    max_compra = config['max_concurrent_procesar_compra']
    
    print(f"開始批次處理，VENTA: {max_venta}, COMPRA: {max_compra}")
    
    # 使用動態配置進行處理
    # 原來的代碼邏輯保持不變，只是使用動態參數
    pass


# ========== 在現有代碼中的具體替換示例 ==========

"""
在你的 compraventa_MULTICUENTA.py 中，找到這些硬編碼參數：

第33-38行：
MAX_CONCURRENT_DOWNLOADS = 10
MAX_CONCURRENT_PROCESAR_VENTA = 10
MAX_CONCURRENT_PROCESAR_COMPRA = 5
MAX_CONCURRENT_VENTA = 10
MAX_CONCURRENT_COMPRA = 50

替換為：

# 在文件頂部添加導入
from utils.simple_config_manager import simple_config_manager, get_dynamic_config

# 在 BusinessApp.__init__ 方法開始處添加：
def __init__(self, root):
    self.root = root
    
    # 初始化動態配置
    self.init_dynamic_config()
    
    # 其他原有代碼...

def init_dynamic_config(self):
    # 設置 API Token（從你的登入系統獲取）
    # simple_config_manager.set_api_token("your_jwt_token_here")
    
    # 獲取動態配置
    config = get_dynamic_config()
    
    # 更新全局變量
    global MAX_CONCURRENT_DOWNLOADS
    global MAX_CONCURRENT_PROCESAR_VENTA
    global MAX_CONCURRENT_PROCESAR_COMPRA
    global MAX_CONCURRENT_VENTA
    global MAX_CONCURRENT_COMPRA
    
    MAX_CONCURRENT_DOWNLOADS = config['max_concurrent_downloads']
    MAX_CONCURRENT_PROCESAR_VENTA = config['max_concurrent_procesar_venta']
    MAX_CONCURRENT_PROCESAR_COMPRA = config['max_concurrent_procesar_compra']
    MAX_CONCURRENT_VENTA = config['max_concurrent_venta']
    MAX_CONCURRENT_COMPRA = config['max_concurrent_compra']
    
    print(f"✅ 動態配置已載入: 下載={MAX_CONCURRENT_DOWNLOADS}, VENTA={MAX_CONCURRENT_PROCESAR_VENTA}")

# 在需要檢查功能權限的地方添加：
from utils.simple_config_manager import is_batch_enabled

def descargar_todos_mes(self):
    if not is_batch_enabled():
        print("❌ 批次下載功能未啟用")
        return
    # 原有代碼...

def procesar_todos(self):
    if not is_batch_enabled():
        print("❌ 批次處理功能未啟用")
        return
    # 原有代碼...
"""


# ========== 測試示例 ==========

def test_dynamic_config():
    """測試動態配置"""
    print("=" * 50)
    print("測試動態配置")
    print("=" * 50)
    
    # 模擬設置 API Token
    # simple_config_manager.set_api_token("test_token")
    
    # 獲取配置
    config = get_dynamic_config()
    print(f"當前配置: {config}")
    
    # 獲取並行限制
    limits = get_parallel_limits()
    print(f"並行限制: {limits}")
    
    # 檢查功能
    print(f"批次下載: {'啟用' if is_batch_enabled() else '禁用'}")
    print(f"高級處理: {'啟用' if is_advanced_processing_enabled() else '禁用'}")


if __name__ == "__main__":
    test_dynamic_config()

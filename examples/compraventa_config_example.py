"""
CompraVenta 應用程式配置示例
展示如何在 Flask 系統中設置參數配置
"""

# 這個文件展示如何在 Flask 系統中為 CompraVenta 應用程式設置參數
# 這些參數會通過 API 動態傳遞給 Python 應用程式

# ============= 參數配置示例 =============

# FREE 版本配置（低性能，適合測試）
FREE_CONFIG = {
    "param_name": "FREE",
    "param_content": """
{
    "max_concurrent_downloads": 1,
    "max_concurrent_procesar_venta": 1,
    "max_concurrent_procesar_compra": 1,
    "max_concurrent_venta": 2,
    "max_concurrent_compra": 5,
    "max_accounts": 2,
    "features": {
        "batch_download": false,
        "batch_process": false,
        "advanced_processing": false,
        "priority_support": false
    }
}
"""
}

# PRO 版本配置（中等性能，適合一般使用）
PRO_CONFIG = {
    "param_name": "PRO",
    "param_content": """
{
    "max_concurrent_downloads": 5,
    "max_concurrent_procesar_venta": 5,
    "max_concurrent_procesar_compra": 3,
    "max_concurrent_venta": 8,
    "max_concurrent_compra": 25,
    "max_accounts": 10,
    "features": {
        "batch_download": true,
        "batch_process": true,
        "advanced_processing": false,
        "priority_support": false
    }
}
"""
}

# ULTRA 版本配置（高性能，適合大量處理）
ULTRA_CONFIG = {
    "param_name": "ULTRA",
    "param_content": """
{
    "max_concurrent_downloads": 15,
    "max_concurrent_procesar_venta": 15,
    "max_concurrent_procesar_compra": 8,
    "max_concurrent_venta": 15,
    "max_concurrent_compra": 75,
    "max_accounts": 50,
    "features": {
        "batch_download": true,
        "batch_process": true,
        "advanced_processing": true,
        "priority_support": true
    }
}
"""
}

# ============= 使用說明 =============

"""
1. 在 Flask 管理界面中：
   - 進入 "服務管理" 頁面
   - 編輯 "Zofri_Compra_Venta" 服務
   - 在 "參數配置" 區域添加這些參數

2. 參數設置步驟：
   - 點擊 "新增參數配置"
   - 參數名稱：FREE/PRO/ULTRA
   - 參數內容：複製上面的 JSON 配置
   - 點擊 "保存參數"

3. 用戶服務配置：
   - 進入 "用戶服務管理" 頁面
   - 編輯用戶服務
   - 選擇對應的參數配置（FREE/PRO/ULTRA）

4. Python 應用程式會：
   - 啟動時嘗試從 API 獲取配置
   - 登入成功後使用 Token 獲取用戶專屬配置
   - 如果 API 不可用，使用硬編碼的備用配置（低性能）

5. 備用配置說明：
   - 硬編碼的備用配置設置為較低的值
   - 確保在網絡問題時應用程式仍能運行
   - 但性能會受到限制
"""

# ============= 測試配置 =============

def test_config_parsing():
    """測試配置解析"""
    import json
    
    configs = [FREE_CONFIG, PRO_CONFIG, ULTRA_CONFIG]
    
    for config in configs:
        print(f"\n=== {config['param_name']} 配置 ===")
        try:
            parsed = json.loads(config['param_content'])
            print("✅ JSON 格式正確")
            print(f"   並行下載: {parsed['max_concurrent_downloads']}")
            print(f"   並行處理 VENTA: {parsed['max_concurrent_procesar_venta']}")
            print(f"   並行處理 COMPRA: {parsed['max_concurrent_procesar_compra']}")
            print(f"   VENTA 內部並行: {parsed['max_concurrent_venta']}")
            print(f"   COMPRA 內部並行: {parsed['max_concurrent_compra']}")
            print(f"   批次下載: {parsed['features']['batch_download']}")
            print(f"   批次處理: {parsed['features']['batch_process']}")
        except json.JSONDecodeError as e:
            print(f"❌ JSON 格式錯誤: {e}")

if __name__ == "__main__":
    test_config_parsing()

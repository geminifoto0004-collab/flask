"""
配置初始化腳本
用於初始化默認的服務配置
"""

from database import init_database, get_db_connection
from services.config_service import config_service
import json


def init_default_configs():
    """初始化默認配置"""
    print("=" * 50)
    print("初始化默認配置")
    print("=" * 50)
    
    # 初始化資料庫
    print("1. 初始化資料庫...")
    init_database()
    print("✅ 資料庫初始化完成")
    
    # 創建默認服務配置
    print("\n2. 創建默認服務配置...")
    config_service.create_default_service_configs()
    print("✅ 默認服務配置創建完成")
    
    # 驗證配置
    print("\n3. 驗證配置...")
    verify_configs()
    
    print("\n" + "=" * 50)
    print("配置初始化完成！")
    print("=" * 50)


def verify_configs():
    """驗證配置是否正確創建"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 檢查服務配置
        cursor.execute("""
            SELECT name, version, config_json 
            FROM services 
            WHERE name = 'Zofri_Compra_Venta' 
            ORDER BY version
        """)
        
        services = cursor.fetchall()
        conn.close()
        
        if not services:
            print("❌ 未找到 Zofri_Compra_Venta 服務配置")
            return False
        
        print("✅ 找到以下服務配置:")
        for name, version, config_json in services:
            try:
                config = json.loads(config_json) if config_json else {}
                max_downloads = config.get('max_concurrent_downloads', 'N/A')
                batch_enabled = config.get('features', {}).get('batch_download', False)
                print(f"   - {name} {version}: 最大並行下載={max_downloads}, 批次下載={'啟用' if batch_enabled else '禁用'}")
            except json.JSONDecodeError:
                print(f"   - {name} {version}: 配置解析錯誤")
        
        return True
        
    except Exception as e:
        print(f"❌ 驗證配置失敗: {e}")
        return False


def test_config_api():
    """測試配置 API"""
    print("\n4. 測試配置 API...")
    
    # 測試獲取 FREE 版本配置
    config = config_service.get_config_for_service("Zofri_Compra_Venta", "FREE")
    if config:
        print("✅ FREE 版本配置獲取成功")
        print(f"   最大並行下載: {config.get('max_concurrent_downloads', 'N/A')}")
    else:
        print("❌ FREE 版本配置獲取失敗")
    
    # 測試獲取 PRO 版本配置
    config = config_service.get_config_for_service("Zofri_Compra_Venta", "PRO")
    if config:
        print("✅ PRO 版本配置獲取成功")
        print(f"   最大並行下載: {config.get('max_concurrent_downloads', 'N/A')}")
        print(f"   批次下載功能: {'啟用' if config.get('features', {}).get('batch_download', False) else '禁用'}")
    else:
        print("❌ PRO 版本配置獲取失敗")
    
    # 測試獲取 ULTRA 版本配置
    config = config_service.get_config_for_service("Zofri_Compra_Venta", "ULTRA")
    if config:
        print("✅ ULTRA 版本配置獲取成功")
        print(f"   最大並行下載: {config.get('max_concurrent_downloads', 'N/A')}")
        print(f"   批次下載功能: {'啟用' if config.get('features', {}).get('batch_download', False) else '禁用'}")
        print(f"   高級處理功能: {'啟用' if config.get('features', {}).get('advanced_processing', False) else '禁用'}")
    else:
        print("❌ ULTRA 版本配置獲取失敗")


if __name__ == "__main__":
    init_default_configs()
    test_config_api()

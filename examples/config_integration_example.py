"""
配置集成示例
展示如何在 Python 應用中集成遠程配置管理
"""

import asyncio
import aiohttp
from utils.remote_config_manager import RemoteConfigManager, with_remote_config


class BusinessAppWithConfig:
    """帶有動態配置的業務應用示例"""
    
    def __init__(self, api_base_url="http://localhost:5000", api_token=None):
        # 初始化遠程配置管理器
        self.remote_config_manager = RemoteConfigManager(api_base_url, api_token)
        
        # 硬編碼默認值（作為備用）
        self.MAX_CONCURRENT_DOWNLOADS = 2
        self.MAX_CONCURRENT_PROCESAR_VENTA = 2
        self.MAX_CONCURRENT_PROCESAR_COMPRA = 1
        self.MAX_CONCURRENT_VENTA = 2
        self.MAX_CONCURRENT_COMPRA = 10
        
        # 動態配置（將從遠程獲取）
        self.config = {}
        self.service_version = "FREE"
    
    def update_config_from_remote(self, service_name="Zofri_Compra_Venta", version=None):
        """從遠程更新配置"""
        try:
            # 獲取遠程配置
            self.config = self.remote_config_manager.get_config(service_name, version)
            self.service_version = version or self.config.get('version', 'FREE')
            
            # 更新並行處理參數
            parallel_config = self.remote_config_manager.get_parallel_config(service_name, version)
            self.MAX_CONCURRENT_DOWNLOADS = parallel_config['max_concurrent_downloads']
            self.MAX_CONCURRENT_PROCESAR_VENTA = parallel_config['max_concurrent_procesar_venta']
            self.MAX_CONCURRENT_PROCESAR_COMPRA = parallel_config['max_concurrent_procesar_compra']
            self.MAX_CONCURRENT_VENTA = parallel_config['max_concurrent_venta']
            self.MAX_CONCURRENT_COMPRA = parallel_config['max_concurrent_compra']
            
            print(f"✅ 配置已更新: {service_name} - {self.service_version}")
            print(f"   並行下載: {self.MAX_CONCURRENT_DOWNLOADS}")
            print(f"   並行處理 VENTA: {self.MAX_CONCURRENT_PROCESAR_VENTA}")
            print(f"   並行處理 COMPRA: {self.MAX_CONCURRENT_PROCESAR_COMPRA}")
            
            return True
            
        except Exception as e:
            print(f"❌ 遠程配置更新失敗: {e}")
            print("使用硬編碼默認配置")
            return False
    
    def check_feature_access(self, feature_name):
        """檢查功能訪問權限"""
        return self.remote_config_manager.is_feature_enabled(feature_name, version=self.service_version)
    
    @with_remote_config("Zofri_Compra_Venta", "PRO")
    def process_with_config(self, config, *args, **kwargs):
        """使用配置參數處理任務的示例"""
        max_downloads = config['max_concurrent_downloads']
        max_venta = config['max_concurrent_venta']
        batch_enabled = config['features']['batch_download']
        
        print(f"使用配置處理任務:")
        print(f"  最大並行下載: {max_downloads}")
        print(f"  最大並行 VENTA: {max_venta}")
        print(f"  批次下載功能: {'啟用' if batch_enabled else '禁用'}")
        
        return True
    
    async def download_with_dynamic_config(self, accounts, mode="venta"):
        """使用動態配置進行下載"""
        # 更新配置
        self.update_config_from_remote()
        
        # 檢查功能權限
        if mode == "batch" and not self.check_feature_access("batch_download"):
            print("❌ 批次下載功能未啟用，請升級到 PRO 或 ULTRA 版本")
            return False
        
        # 使用動態配置進行下載
        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_DOWNLOADS)
        
        async def download_account(account):
            async with semaphore:
                print(f"下載帳號: {account} (限制: {self.MAX_CONCURRENT_DOWNLOADS})")
                # 實際下載邏輯
                await asyncio.sleep(1)  # 模擬下載
                return True
        
        # 並行下載
        tasks = [download_account(account) for account in accounts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is True)
        print(f"下載完成: {success_count}/{len(accounts)} 成功")
        
        return success_count == len(accounts)


# 使用示例
async def main():
    """主函數示例"""
    print("=" * 50)
    print("配置集成示例")
    print("=" * 50)
    
    # 創建應用實例
    app = BusinessAppWithConfig(
        api_base_url="http://localhost:5000",
        api_token="your_jwt_token_here"  # 從登入獲取
    )
    
    # 1. 更新配置
    print("\n1. 更新遠程配置...")
    app.update_config_from_remote("Zofri_Compra_Venta", "PRO")
    
    # 2. 檢查功能權限
    print("\n2. 檢查功能權限...")
    features = ['batch_download', 'batch_process', 'advanced_processing', 'priority_support']
    for feature in features:
        enabled = app.check_feature_access(feature)
        print(f"   {feature}: {'✅' if enabled else '❌'}")
    
    # 3. 使用配置處理任務
    print("\n3. 使用配置處理任務...")
    app.process_with_config()
    
    # 4. 動態下載示例
    print("\n4. 動態下載示例...")
    accounts = ['account1', 'account2', 'account3', 'account4', 'account5']
    await app.download_with_dynamic_config(accounts, mode="batch")
    
    print("\n" + "=" * 50)
    print("示例完成")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())

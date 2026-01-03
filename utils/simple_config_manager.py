"""
簡化配置管理器
專門用於 compraventa_MULTICUENTA.py 應用
隱藏版本概念，用戶無感知
"""

import requests
import json
import time
from typing import Dict, Any, Optional


class SimpleConfigManager:
    """簡化配置管理器 - 隱藏版本概念"""
    
    def __init__(self, api_base_url: str = "http://localhost:5000", api_token: str = None):
        self.api_base_url = api_base_url.rstrip('/')
        self.api_token = api_token
        self.cache = None
        self.cache_time = 0
        self.cache_timeout = 300  # 5分鐘緩存
        
        # 硬編碼備用配置（當無法連接到遠程配置時使用）
        self.default_config = {
            'max_concurrent_downloads': 2,
            'max_concurrent_procesar_venta': 2,
            'max_concurrent_procesar_compra': 1,
            'max_concurrent_venta': 2,
            'max_concurrent_compra': 10,
            'max_accounts': 2,
            'features': {
                'batch_download': False,
                'batch_process': False,
                'advanced_processing': False,
                'priority_support': False
            }
        }
    
    def set_api_token(self, token: str):
        """設置 API Token"""
        self.api_token = token
        self.cache = None  # 清除緩存
    
    def get_config(self) -> Dict[str, Any]:
        """
        獲取配置參數（用戶無感知版本概念）
        優先從遠程 API 獲取，失敗時使用硬編碼默認值
        """
        current_time = time.time()
        
        # 檢查緩存
        if (self.cache and 
            current_time - self.cache_time < self.cache_timeout):
            return self.cache
        
        try:
            # 嘗試從遠程 API 獲取
            config_data = self._fetch_config_from_api()
            if config_data:
                self.cache = config_data
                self.cache_time = current_time
                print("Successfully fetched remote config")
                print(f"   Config content: {config_data}")
                return config_data
        except Exception as e:
            print(f"Warning: Remote config fetch failed: {e}")
        
        # 使用硬編碼默認值
        print("Using hardcoded default config")
        self.cache = self.default_config.copy()
        self.cache_time = current_time
        return self.cache
    
    def _fetch_config_from_api(self) -> Optional[Dict[str, Any]]:
        """從遠程 API 獲取配置"""
        if not self.api_token:
            raise Exception("API Token not set")
        
        url = f"{self.api_base_url}/api/user-config"
        params = {'service_name': 'Zofri_Compra_Venta'}  # 固定服務名
        
        headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json',
            'X-User-ID': '2'  # 使用實際的用戶ID
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=5)
        response.raise_for_status()
        
        data = response.json()
        if data.get('success'):
            # 解析 Python 代碼格式的參數
            config_params = data.get('config_params', '')
            return self._parse_python_config(config_params)
        else:
            raise Exception(f"API returned error: {data.get('error', 'Unknown error')}")
    
    def _parse_python_config(self, config_params: str) -> Dict[str, Any]:
        """解析 Python 代碼格式的配置參數"""
        config = {}
        
        # 解析每一行配置
        for line in config_params.split('\n'):
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                try:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # 轉換為對應的配置鍵名
                    if key == 'MAX_CONCURRENT_DOWNLOADS':
                        config['max_concurrent_downloads'] = int(value)
                    elif key == 'MAX_CONCURRENT_PROCESAR_VENTA':
                        config['max_concurrent_procesar_venta'] = int(value)
                    elif key == 'MAX_CONCURRENT_PROCESAR_COMPRA':
                        config['max_concurrent_procesar_compra'] = int(value)
                    elif key == 'MAX_CONCURRENT_VENTA':
                        config['max_concurrent_venta'] = int(value)
                    elif key == 'MAX_CONCURRENT_COMPRA':
                        config['max_concurrent_compra'] = int(value)
                except (ValueError, IndexError):
                    continue
        
        # 添加默認功能開關
        config['features'] = {
            'batch_download': config.get('max_concurrent_downloads', 1) > 1,
            'batch_process': config.get('max_concurrent_procesar_venta', 1) > 1,
            'advanced_processing': config.get('max_concurrent_compra', 1) > 20,
            'priority_support': config.get('max_concurrent_downloads', 1) > 10
        }
        
        return config
    
    def get_parallel_config(self) -> Dict[str, int]:
        """獲取並行處理配置（只返回數值參數）"""
        config = self.get_config()
        
        return {
            'max_concurrent_downloads': config.get('max_concurrent_downloads', 5),
            'max_concurrent_procesar_venta': config.get('max_concurrent_procesar_venta', 5),
            'max_concurrent_procesar_compra': config.get('max_concurrent_procesar_compra', 3),
            'max_concurrent_venta': config.get('max_concurrent_venta', 5),
            'max_concurrent_compra': config.get('max_concurrent_compra', 25),
            'max_accounts': config.get('max_accounts', 5)
        }
    
    def is_feature_enabled(self, feature_name: str) -> bool:
        """檢查特定功能是否啟用"""
        config = self.get_config()
        features = config.get('features', {})
        return features.get(feature_name, False)
    
    def clear_cache(self):
        """清除配置緩存"""
        self.cache = None
        self.cache_time = 0


# 創建全局配置管理器實例
simple_config_manager = SimpleConfigManager()


def get_dynamic_config():
    """
    獲取動態配置的便捷函數
    用於替換 compraventa_MULTICUENTA.py 中的硬編碼參數
    """
    return simple_config_manager.get_config()


def get_parallel_limits():
    """
    獲取並行限制的便捷函數
    用於替換硬編碼的並行處理參數
    """
    return simple_config_manager.get_parallel_config()


def is_batch_enabled():
    """檢查批次功能是否啟用"""
    return simple_config_manager.is_feature_enabled('batch_download')


def is_advanced_processing_enabled():
    """檢查高級處理功能是否啟用"""
    return simple_config_manager.is_feature_enabled('advanced_processing')

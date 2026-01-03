"""
遠程配置管理器
功能：為前端應用提供動態配置獲取，支持硬編碼備用
"""

import requests
import json
import time
from typing import Dict, Any, Optional
from functools import wraps


class RemoteConfigManager:
    """遠程配置管理器"""
    
    def __init__(self, api_base_url: str = "http://localhost:5000", api_token: str = None):
        self.api_base_url = api_base_url.rstrip('/')
        self.api_token = api_token
        self.cache = {}
        self.cache_timeout = 300  # 5分鐘緩存
        self.last_cache_time = 0
        
        # 硬編碼默認配置（作為備用）
        self.default_configs = {
            'FREE': {
                'max_concurrent_downloads': 2,
                'max_concurrent_procesar_venta': 2,
                'max_concurrent_procesar_compra': 1,
                'max_concurrent_venta': 2,
                'max_concurrent_compra': 10,
                'max_accounts': 1,
                'features': {
                    'batch_download': False,
                    'batch_process': False,
                    'advanced_processing': False,
                    'priority_support': False
                }
            },
            'PRO': {
                'max_concurrent_downloads': 5,
                'max_concurrent_procesar_venta': 5,
                'max_concurrent_procesar_compra': 3,
                'max_concurrent_venta': 5,
                'max_concurrent_compra': 25,
                'max_accounts': 5,
                'features': {
                    'batch_download': True,
                    'batch_process': True,
                    'advanced_processing': False,
                    'priority_support': False
                }
            },
            'ULTRA': {
                'max_concurrent_downloads': 10,
                'max_concurrent_procesar_venta': 10,
                'max_concurrent_procesar_compra': 5,
                'max_concurrent_venta': 10,
                'max_concurrent_compra': 50,
                'max_accounts': -1,  # 無限制
                'features': {
                    'batch_download': True,
                    'batch_process': True,
                    'advanced_processing': True,
                    'priority_support': True
                }
            }
        }
    
    def set_api_token(self, token: str):
        """設置 API Token"""
        self.api_token = token
        # 清除緩存，強制重新獲取
        self.cache.clear()
        self.last_cache_time = 0
    
    def get_config(self, service_name: str = "Zofri_Compra_Venta", version: str = None) -> Dict[str, Any]:
        """
        獲取配置參數
        優先從遠程 API 獲取，失敗時使用硬編碼默認值
        """
        cache_key = f"{service_name}_{version or 'auto'}"
        current_time = time.time()
        
        # 檢查緩存
        if (cache_key in self.cache and 
            current_time - self.last_cache_time < self.cache_timeout):
            return self.cache[cache_key]
        
        try:
            # 嘗試從遠程 API 獲取
            config_data = self._fetch_config_from_api(service_name, version)
            if config_data:
                self.cache[cache_key] = config_data
                self.last_cache_time = current_time
                return config_data
        except Exception as e:
            print(f"從遠程 API 獲取配置失敗: {e}")
        
        # 使用硬編碼默認值
        fallback_version = version or 'FREE'
        config_data = self.default_configs.get(fallback_version, self.default_configs['FREE']).copy()
        self.cache[cache_key] = config_data
        self.last_cache_time = current_time
        
        print(f"使用硬編碼配置: {service_name} - {fallback_version}")
        return config_data
    
    def _fetch_config_from_api(self, service_name: str, version: str = None) -> Optional[Dict[str, Any]]:
        """從遠程 API 獲取配置"""
        if not self.api_token:
            raise Exception("API Token 未設置")
        
        url = f"{self.api_base_url}/api/config"
        params = {'service_name': service_name}
        if version:
            params['version'] = version
        
        headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get('success'):
            return data.get('config')
        else:
            raise Exception(f"API 返回錯誤: {data.get('error', '未知錯誤')}")
    
    def get_parallel_config(self, service_name: str = "Zofri_Compra_Venta", version: str = None) -> Dict[str, int]:
        """獲取並行處理配置（只返回數值參數）"""
        config = self.get_config(service_name, version)
        
        return {
            'max_concurrent_downloads': config.get('max_concurrent_downloads', 2),
            'max_concurrent_procesar_venta': config.get('max_concurrent_procesar_venta', 2),
            'max_concurrent_procesar_compra': config.get('max_concurrent_procesar_compra', 1),
            'max_concurrent_venta': config.get('max_concurrent_venta', 2),
            'max_concurrent_compra': config.get('max_concurrent_compra', 10),
            'max_accounts': config.get('max_accounts', 1)
        }
    
    def get_features(self, service_name: str = "Zofri_Compra_Venta", version: str = None) -> Dict[str, bool]:
        """獲取功能開關配置"""
        config = self.get_config(service_name, version)
        return config.get('features', {})
    
    def clear_cache(self):
        """清除配置緩存"""
        self.cache.clear()
        self.last_cache_time = 0
    
    def is_feature_enabled(self, feature_name: str, service_name: str = "Zofri_Compra_Venta", version: str = None) -> bool:
        """檢查特定功能是否啟用"""
        features = self.get_features(service_name, version)
        return features.get(feature_name, False)


def with_remote_config(service_name: str = "Zofri_Compra_Venta", version: str = None):
    """
    裝飾器：為函數注入遠程配置參數
    使用方式：
    @with_remote_config("Zofri_Compra_Venta", "PRO")
    def my_function(self, config, *args, **kwargs):
        max_downloads = config['max_concurrent_downloads']
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # 假設 self 有 remote_config_manager 屬性
            if hasattr(self, 'remote_config_manager'):
                config = self.remote_config_manager.get_config(service_name, version)
                return func(self, config, *args, **kwargs)
            else:
                # 如果沒有配置管理器，使用默認配置
                from .remote_config_manager import RemoteConfigManager
                temp_manager = RemoteConfigManager()
                config = temp_manager.get_config(service_name, version)
                return func(self, config, *args, **kwargs)
        return wrapper
    return decorator


# 創建全局配置管理器實例
remote_config_manager = RemoteConfigManager()

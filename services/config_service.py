"""
配置管理服務
功能：管理系統配置參數，支持硬編碼默認值 + 遠程動態配置
"""

import json
import sqlite3
from typing import Dict, Any, Optional
from datetime import datetime
from database import get_db_connection


class ConfigService:
    """配置管理服務類"""
    
    # 硬編碼默認配置（作為備用）
    DEFAULT_CONFIGS = {
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
    
    def __init__(self):
        self.cache = {}
        self.cache_timeout = 300  # 5分鐘緩存
        self.last_cache_time = 0
    
    def get_config_for_service(self, service_name: str, version: str = None) -> Dict[str, Any]:
        """
        獲取服務配置
        優先從數據庫獲取，失敗時使用硬編碼默認值
        """
        try:
            # 嘗試從數據庫獲取
            db_config = self._get_config_from_db(service_name, version)
            if db_config:
                return db_config
        except Exception as e:
            print(f"從數據庫獲取配置失敗: {e}")
        
        # 使用硬編碼默認值
        return self._get_default_config(version or 'FREE')
    
    def _get_config_from_db(self, service_name: str, version: str = None) -> Optional[Dict[str, Any]]:
        """從數據庫獲取配置"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # 優先從 service_versions 表獲取配置
            if version:
                cursor.execute("""
                    SELECT param_content 
                    FROM service_versions 
                    WHERE service_name = ? AND param_name = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                """, (service_name, version))
                
                result = cursor.fetchone()
                if result:
                    # 處理返回格式（可能是字典或元組）
                    config_params = result.get('param_content') if isinstance(result, dict) else (result[0] if len(result) > 0 else None)
                    if config_params:
                        # 解析 Python 代碼格式的參數
                        return self._parse_python_config(config_params)
            
            # 如果沒有指定版本，嘗試從 services 表獲取
            query = """
                SELECT version, config_json 
                FROM services 
                WHERE name = ? AND status = 'active'
            """
            params = [service_name]
            
            if version:
                query += " AND version = ?"
                params.append(version)
            
            query += " ORDER BY created_at DESC LIMIT 1"
            
            cursor.execute(query, params)
            result = cursor.fetchone()
            
            if result:
                # 處理返回格式（可能是字典或元組）
                config_json = result.get('config_json') if isinstance(result, dict) else (result[1] if len(result) > 1 else None)
                if config_json:
                    config_data = json.loads(config_json)
                    return config_data
            
            return None
            
        finally:
            conn.close()
    
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
    
    def _get_default_config(self, version: str) -> Dict[str, Any]:
        """獲取硬編碼默認配置"""
        return self.DEFAULT_CONFIGS.get(version, self.DEFAULT_CONFIGS['FREE']).copy()
    
    def update_service_config(self, service_name: str, version: str, config: Dict[str, Any]) -> bool:
        """更新服務配置"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 檢查服務是否存在
            cursor.execute("SELECT id FROM services WHERE name = ? AND version = ?", (service_name, version))
            service = cursor.fetchone()
            
            if service:
                # 更新現有服務
                cursor.execute(
                    "UPDATE services SET config_json = ? WHERE name = ? AND version = ?",
                    (json.dumps(config, ensure_ascii=False), service_name, version)
                )
            else:
                # 創建新服務配置
                cursor.execute("""
                    INSERT INTO services (name, version, config_json, status, description)
                    VALUES (?, ?, ?, 'active', ?)
                """, (service_name, version, json.dumps(config, ensure_ascii=False), 
                     f"{service_name} {version} 版本配置"))
            
            conn.commit()
            conn.close()
            
            # 清除緩存
            self.cache.clear()
            return True
            
        except Exception as e:
            print(f"更新服務配置失敗: {e}")
            return False
    
    def get_all_service_configs(self) -> Dict[str, Dict[str, Any]]:
        """獲取所有服務配置"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT name, version, config_json 
                FROM services 
                WHERE status = 'active' AND config_json IS NOT NULL
                ORDER BY name, version
            """)
            
            results = cursor.fetchall()
            conn.close()
            
            configs = {}
            for name, version, config_json in results:
                if name not in configs:
                    configs[name] = {}
                
                try:
                    configs[name][version] = json.loads(config_json)
                except json.JSONDecodeError:
                    print(f"解析配置 JSON 失敗: {name} - {version}")
                    configs[name][version] = self._get_default_config(version)
            
            return configs
            
        except Exception as e:
            print(f"獲取所有服務配置失敗: {e}")
            return {}
    
    def create_default_service_configs(self):
        """創建默認服務配置"""
        default_services = [
            {
                'name': 'Zofri_Compra_Venta',
                'versions': ['FREE', 'PRO', 'ULTRA'],
                'description': 'Zofri 採購銷售系統'
            }
        ]
        
        for service in default_services:
            for version in service['versions']:
                config = self._get_default_config(version)
                self.update_service_config(service['name'], version, config)
                print(f"已創建 {service['name']} {version} 版本配置")


# 創建全局配置服務實例
config_service = ConfigService()

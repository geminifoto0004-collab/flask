"""
時間工具模組
功能：提供統一的智利時區時間函數
"""

from datetime import datetime
import pytz

# 智利時區設定
CHILE_TZ = pytz.timezone('America/Santiago')

def get_chile_time():
    """獲取智利當前時間（帶時區信息）"""
    return datetime.now(CHILE_TZ)

def get_chile_time_naive():
    """獲取智利當前時間（無時區信息，用於與資料庫記錄比較）"""
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


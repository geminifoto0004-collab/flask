"""
订单状态配置 - Python端
从 status_definitions.py 导入统一的状态定义
用于Python后端的状态管理（保持向后兼容）
"""

from .status_definitions import (
    STATUS_KEYS,
    STATUS_LABELS,
    STAGE_GROUPS,
    STATUS_FLOW_ORDER,
    QUICK_ACTIONS_MAP,
    get_status_label,
    get_stage_group,
    get_statuses_by_stage_group,
    is_status_in_group,
    STATUS  # 向后兼容：旧的 STATUS 字典（key -> 简体中文）
)

# ==================== 向后兼容：生成旧的 STAGE_GROUPS 格式 ====================
# 旧的格式：statuses 是中文文字列表
# 新代码应该直接使用 status_definitions.STAGE_GROUPS（status_keys 是 key 列表）
_STAGE_GROUPS_LEGACY = {}
for group_name, group in STAGE_GROUPS.items():
    _STAGE_GROUPS_LEGACY[group_name] = {
        'name': group['name_zh_cn'],  # 保持简体中文
        'statuses': [get_status_label(key, 'zh_cn') for key in group['status_keys']],
        'icon': group.get('icon', ''),
        'color': group.get('color', '#666666')
    }
    if 'is_filter' in group:
        _STAGE_GROUPS_LEGACY[group_name]['is_filter'] = group['is_filter']

STAGE_GROUPS = _STAGE_GROUPS_LEGACY  # 保持向后兼容

# ==================== 向后兼容：STATUS_MAP（action -> 简体中文）====================
STATUS_MAP = {}
for action, status_key in QUICK_ACTIONS_MAP.items():
    STATUS_MAP[action] = get_status_label(status_key, 'zh_cn')

# ==================== 工具函数（向后兼容）====================

def get_stage_group(status):
    """
    根据状态获取所属阶段（向后兼容）
    
    支持：
    - 新格式：status 是 key（如 'NEW_ORDER'）
    - 旧格式：status 是中文文字（如 '新订单'）
    """
    # 如果是 key，直接用新函数
    if status in STATUS_KEYS.values():
        return get_stage_group(status)
    
    # 如果是中文，先找到对应的 key
    for key, label_zh_cn in STATUS.items():
        if label_zh_cn == status:
            return get_stage_group(key)
    
    return 'all'

def get_statuses_by_stage_group(stage_group):
    """
    获取某个阶段的所有状态（向后兼容）
    返回简体中文列表
    """
    if stage_group not in STAGE_GROUPS:
        return []
    return STAGE_GROUPS[stage_group]['statuses']


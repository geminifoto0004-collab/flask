"""
权限配置（配置驱动）
"""

# 基本权限矩阵：角色 -> 资源 -> 允许的操作
PERMISSION_MATRIX = {
    'admin': {
        'order': ['view', 'edit', 'delete', 'create', 'lock', 'unlock'],
        'workflow': ['view', 'edit', 'delete', 'create'],
        'order_file': ['view', 'upload', 'delete'],
        'workflow_file': ['view', 'upload', 'delete'],
        'user': ['view', 'edit', 'delete', 'create']
    },
    'sales': {
        'order': ['view', 'edit', 'create'],
        'workflow': ['view', 'edit', 'create'],
        'order_file': ['view', 'upload', 'delete'],
        'workflow_file': ['view', 'upload', 'delete'],
        'user': []
    },
    'viewer': {
        'order': ['view'],
        'workflow': ['view'],
        'order_file': ['view'],
        'workflow_file': ['view'],
        'user': []
    }
}

# 所有权规则：角色 -> 资源 -> 规则
OWNERSHIP_RULES = {
    'admin': {
        'order': 'all',
        'workflow': 'all',
        'order_file': 'all',
        'workflow_file': 'all'
    },
    'sales': {
        'order': 'owner_only',
        'workflow': 'owner_only',
        'order_file': 'owner_only',
        'workflow_file': 'owner_only'
    },
    'viewer': {
        'order': 'all',
        'workflow': 'all',
        'order_file': 'all',
        'workflow_file': 'all'
    }
}

# 状态规则：角色 -> 资源 -> 操作 -> 规则
STATUS_RULES = {
    'admin': {
        'order': {
            'edit': 'respect_lock',
            'delete': 'respect_lock'
        },
        'workflow': {
            'edit': 'respect_lock',
            'delete': 'respect_lock'
        },
        'order_file': {
            'upload': 'respect_lock',
            'delete': 'respect_lock'
        },
        'workflow_file': {
            'upload': 'respect_lock',
            'delete': 'respect_lock'
        }
    },
    'sales': {
        'order': {
            'edit': 'respect_lock',
            'delete': 'respect_lock'
        },
        'workflow': {
            'edit': 'respect_lock',
            'delete': 'respect_lock'
        },
        'order_file': {
            'upload': 'respect_lock',
            'delete': 'respect_lock'
        },
        'workflow_file': {
            'upload': 'respect_lock',
            'delete': 'respect_lock'
        }
    },
    'viewer': {}
}


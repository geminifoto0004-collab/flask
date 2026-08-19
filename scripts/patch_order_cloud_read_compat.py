#!/usr/bin/env python3
"""Patch shared ORDER GET routes to use the registered cloud provider on Render.

LAN/local SQLite code paths are preserved byte-for-byte inside each route after the
new cloud-mode guard. This script never opens tracking.db and never changes data.
"""
from pathlib import Path
import py_compile

MARKER = "def _cloud_provider_call(method_name, *args, **kwargs):"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"anchor not found: {label}")
    return text.replace(old, new, 1)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "order_tracking" / "__init__.py"
    text = path.read_text("utf-8")
    original = text

    if MARKER not in text:
        anchor = "\n\n@tracking_bp.route('/api/orders/all-for-filter', methods=['GET'])"
        if anchor not in text:
            raise RuntimeError("all-for-filter anchor not found")
        helper = '''\n\ndef _cloud_provider_call(method_name, *args, **kwargs):\n    """Call one Render/TiDB read method without changing LAN/SQLite behavior."""\n    provider = get_order_data_provider()\n    if provider is None:\n        if cloud_mode_enabled():\n            raise RuntimeError('Render ORDER data provider is not registered')\n        return None\n    method = getattr(provider, method_name, None)\n    if not callable(method):\n        raise RuntimeError(f'OrderDataProvider must implement {method_name}() in cloud mode')\n    return method(*args, **kwargs)\n'''
        text = text.replace(anchor, helper + anchor, 1)

    text = replace_once(
        text,
        """def api_customer_history_orders():\n    if cloud_mode_enabled():\n        return jsonify({'success': False, 'error': '云端客户历史查询尚未接通'}), 400\n    customer_input = ' '.join(str(request.args.get('customer_name') or '').strip().split())\n""",
        """def api_customer_history_orders():\n    customer_input = ' '.join(str(request.args.get('customer_name') or '').strip().split())\n""",
        "customer history hard stop",
    )

    start = text.index("def api_customer_history_orders():")
    local_anchor = """    ctx = get_current_user_context()\n    conn = get_db()\n"""
    cloud_block = """    ctx = get_current_user_context()\n    if cloud_mode_enabled():\n        try:\n            result = _cloud_provider_call(\n                'get_customer_history', customer_input, history_scope, include_cancelled,\n                ctx.get('role', 'viewer'), ctx.get('id')\n            ) or {}\n        except Exception as exc:\n            return jsonify({'success': False, 'error': f'雲端客戶資料載入失敗: {exc}'}), 503\n        rows = list(result.get('data') or [])\n        customer_name = result.get('customer_name') or customer_input\n        response = jsonify({\n            'success': True, 'customer_name': customer_name, 'scope': history_scope,\n            'include_cancelled': bool(include_cancelled), 'total': len(rows), 'data': rows\n        })\n        response.headers['Cache-Control'] = 'no-store, private, max-age=0'\n        return response\n\n    conn = get_db()\n"""
    if cloud_block not in text:
        pos = text.find(local_anchor, start)
        if pos < 0:
            raise RuntimeError("customer history context anchor not found")
        text = text[:pos] + cloud_block + text[pos + len(local_anchor):]

    text = replace_once(
        text,
        """def api_order_detail(order_number):\n    \"\"\"獲取訂單詳情API\"\"\"\n    conn = get_db()\n""",
        """def api_order_detail(order_number):\n    \"\"\"獲取訂單詳情API\"\"\"\n    if cloud_mode_enabled():\n        try:\n            order = _cloud_provider_call('get_order_detail', order_number)\n        except Exception as exc:\n            return jsonify({'success': False, 'error': f'雲端訂單資料載入失敗: {exc}'}), 503\n        if not order:\n            return jsonify({'success': False, 'error': '訂單不存在', 'code': 'NOT_FOUND'}), 404\n        return jsonify({'success': True, 'data': order})\n\n    conn = get_db()\n""",
        "order detail",
    )

    text = replace_once(
        text,
        """def api_workflow_detail(workflow_number):\n    \"\"\"獲取流程詳情API（包含時間軸）\"\"\"\n    conn = get_db()\n""",
        """def api_workflow_detail(workflow_number):\n    \"\"\"獲取流程詳情API（包含時間軸）\"\"\"\n    if cloud_mode_enabled():\n        try:\n            workflow = _cloud_provider_call('get_workflow_detail', workflow_number)\n        except Exception as exc:\n            return jsonify({'success': False, 'error': f'雲端流程資料載入失敗: {exc}'}), 503\n        if not workflow:\n            return jsonify({'success': False, 'error': '流程不存在', 'code': 'NOT_FOUND'}), 404\n        return jsonify({'success': True, 'data': workflow})\n\n    conn = get_db()\n""",
        "workflow detail",
    )

    search_start = text.index("def api_search_customers():")
    search_anchor = """    if not query or len(query) < 1:\n        return jsonify({'success': True, 'data': []})\n    \n    conn = get_db()\n"""
    search_cloud = """    if not query or len(query) < 1:\n        return jsonify({'success': True, 'data': []})\n\n    if cloud_mode_enabled():\n        try:\n            customers = _cloud_provider_call('search_customers', query, 10) or []\n            return jsonify({'success': True, 'data': list(customers)})\n        except Exception as exc:\n            return jsonify({'success': False, 'error': f'雲端客戶搜尋失敗: {exc}'}), 503\n    \n    conn = get_db()\n"""
    if search_cloud not in text:
        pos = text.find(search_anchor, search_start)
        if pos < 0:
            raise RuntimeError("customer search anchor not found")
        text = text[:pos] + search_cloud + text[pos + len(search_anchor):]

    text = replace_once(
        text,
        """def api_get_workflow_files(workflow_number):\n    # visual=1 always re-queries current SQLite rows and current source-file versions.\n    conn = get_db()\n""",
        """def api_get_workflow_files(workflow_number):\n    # Render uses the same UI but has no LAN file system. Published cloud media is\n    # served by the public-share/B2 path, not by this local attachment API.\n    if cloud_mode_enabled():\n        return jsonify({'success': True, 'data': {\n            'workflow_number': workflow_number, 'files': [], 'total': 0\n        }})\n    # visual=1 always re-queries current SQLite rows and current source-file versions.\n    conn = get_db()\n""",
        "workflow files",
    )

    text = replace_once(
        text,
        """def api_get_order_files(order_number):\n    # visual=1 always re-queries current SQLite rows and current source-file versions.\n    conn = get_db()\n""",
        """def api_get_order_files(order_number):\n    if cloud_mode_enabled():\n        return jsonify({'success': True, 'data': {\n            'order_number': order_number, 'files': [], 'total': 0\n        }})\n    # visual=1 always re-queries current SQLite rows and current source-file versions.\n    conn = get_db()\n""",
        "order files",
    )

    text = replace_once(
        text,
        """def api_global_search():\n    \"\"\"全局搜索API - 搜索当前权限范围内的流程，并补充无流程订单\"\"\"\n    keyword = request.args.get('q', '').strip()\n\n    conn = get_db()\n""",
        """def api_global_search():\n    \"\"\"全局搜索API - 搜索当前权限范围内的流程，并补充无流程订单\"\"\"\n    keyword = request.args.get('q', '').strip()\n\n    if cloud_mode_enabled():\n        ctx = get_current_user_context()\n        try:\n            rows = _load_home_orders_from_active_source(ctx.get('role', 'viewer'), ctx.get('id'))\n        except Exception as exc:\n            return jsonify({'success': False, 'error': f'雲端搜尋失敗: {exc}'}), 503\n        needle = keyword.casefold()\n        if needle:\n            rows = [row for row in rows if needle in str(row.get('order_number') or '').casefold()\n                    or needle in str(row.get('workflow_number') or '').casefold()\n                    or needle in str(row.get('customer_name') or '').casefold()]\n        else:\n            rows = [row for row in rows if str(row.get('current_status') or '') not in {STATUS_KEYS['COMPLETED'], STATUS_KEYS['CANCELLED']}]\n        rows = rows[:200]\n        return jsonify({\n            'success': True, 'type': 'search' if keyword else 'recent', 'keyword': keyword,\n            'orders': rows, 'total': len(rows), 'limit_reached': len(rows) >= 200\n        })\n\n    conn = get_db()\n""",
        "global search",
    )

    if text != original:
        path.write_text(text, "utf-8")
    py_compile.compile(str(path), doraise=True)

    required = [
        "def _cloud_provider_call(method_name, *args, **kwargs):",
        "_cloud_provider_call('get_workflow_detail', workflow_number)",
        "_cloud_provider_call('get_order_detail', order_number)",
        "_cloud_provider_call('search_customers', query, 10)",
        "'workflow_number': workflow_number, 'files': [], 'total': 0",
        "'order_number': order_number, 'files': [], 'total': 0",
    ]
    final = path.read_text("utf-8")
    missing = [item for item in required if item not in final]
    if missing:
        raise RuntimeError("post-patch validation failed: " + repr(missing))
    print("ORDER cloud read compatibility", "applied" if text != original else "already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

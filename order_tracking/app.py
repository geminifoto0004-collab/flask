"""
訂單流程追蹤系統 - 獨立運行入口
開發測試用
"""
import sys
import os
import io
from pathlib import Path

# 修复 Windows 控制台编码问题（必须在任何 print 之前执行）
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# 添加項目根目錄到 Python 路徑
current_dir = Path(__file__).parent
parent_dir = current_dir.parent
sys.path.insert(0, str(parent_dir))

from flask import Flask, redirect, url_for, session, request, jsonify
from werkzeug.exceptions import NotFound
from order_tracking import tracking_bp, init_db
from order_tracking.config import SECRET_KEY, CLOUD_MODE

app = Flask(__name__)
app.secret_key = SECRET_KEY

# 本機模式初始化 SQLite；Cloud/Render 模式由外部 Provider 提供資料。
if not CLOUD_MODE:
    init_db()

# 註冊Blueprint
app.register_blueprint(tracking_bp)


# 全局 404 錯誤處理器 - 處理所有未匹配的路由
# 注意：Blueprint 的錯誤處理器會優先處理 /tracking/* 路徑
@app.errorhandler(404)
def handle_global_404(e):
    """處理全局 404 錯誤 - 錯誤的 URL 跳轉到 tracking 登入頁面"""
    # 所有未匹配的路由都重定向到 /tracking（Blueprint 會處理）
    return redirect('/tracking')

if __name__ == '__main__':
    print("=" * 50)
    print("訂單流程追蹤系統")
    print("=" * 50)
    print("訪問地址: http://localhost:5000/tracking")

    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)


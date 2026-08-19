# order_tracking Cloud / Render Mode

此功能是共用 `order_tracking` 的可選模式。**預設本機行為不變**。

## 本機（中國 / 智利）

不設定任何 Cloud 環境變數：

```text
TRACKING_CLOUD_MODE 未設定
TRACKING_CLOUD_READ_ONLY 未設定
```

效果：
- 使用原本 `E:\upload_xingwang\data\tracking.db`
- 原本新增 / 修改 / 上傳 / 刪除功能不變
- SQLite snapshot / notification cleanup / startup VACUUM 不變

## Render

Render 必須設定：

```text
TRACKING_CLOUD_MODE=1
TRACKING_CLOUD_READ_ONLY=1
```

建議另外設定：

```text
TRACKING_DATA_DIR=/tmp/order_tracking_cloud
```

Cloud Mode 效果：
- 不啟動本機 SQLite snapshot / cleanup / VACUUM
- 不把 Render 的空 SQLite 當正式訂單來源
- 未註冊 Provider 時首頁合法回傳空資料，顯示「尚未同步雲端訂單資料」
- 所有正式訂單寫入由 Blueprint `before_request` 後端攔截，回 403 `CLOUD_READ_ONLY`
- admin 仍保留「看全部」角色語意；sales 仍保留「只看自己的」角色語意
- UI 權限矩陣自動移除 create/edit/delete/upload/lock/unlock，避免顯示快捷修改操作
- 手機版首頁會將桌面表格轉為訂單卡片

## 外部資料 Provider

`order_tracking` 本身不 import TiDB / MySQL。

Render 父 Flask 之後實作 Provider：

```python
class TiDBOrderProvider:
    def load_home_orders(self, role, user_id):
        # 讀 TiDB order_summary
        # 必須依 Render 登入帳號做可見範圍過濾
        return rows

    def get_last_synced_at(self):
        return "2026-08-16 18:30:00"
```

註冊方式：

```python
from order_tracking import tracking_bp
from order_tracking.data_provider import register_order_data_provider

provider = TiDBOrderProvider(...)
register_order_data_provider(app, provider)
app.register_blueprint(tracking_bp)
```

或：

```python
from order_tracking import init_app
init_app(app, data_provider=provider)
```

## 安全原則

Cloud Mode 是後端強制唯讀，不只靠隱藏按鈕。

目前允許的非 GET 只保留少數「語意上為查詢」的舊 API，例如 advanced-search。其他未知 POST / PUT / DELETE 預設拒絕。

未來 `report_requests` 應放在 Render / overseas cloud 模組，不屬於訂單資料修改，因此不需要解除 `order_tracking` 的唯讀保護。

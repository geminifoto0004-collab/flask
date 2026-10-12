# XINGWANG ORDER LINK — Telegram 私人群组邀请制

本机 ORDER_HOME_V140 保持原样；查询在 Render 运行，从 TiDB 读取当前有效的
ORDER_SHARES。无须登入网页，也无须公司通行码或逐个登记员工数字 ID。

## 管理员：一次设定

1. 在 Telegram 建立**私人群组**（例如 `XINGWANG ORDER STAFF`），邀请公司员工。
   群组邀请必须由管理员控制，不要把群组邀请链接公开。
2. 将 `@XingwangOrderLinkBot` 加入该群组，并设为**管理员**。
   Telegram Bot API 的 `getChatMember` 对其他用户可靠查询要求 Bot 是群组管理员。
3. 在群组输入 `/groupid@XingwangOrderLinkBot`；Bot 返回负数的群组 ID，
   例如 `-100123456789`（示例，不要照抄）。
4. 打开 Render 的 `flask` Web Service → Environment，新增：
   `ORDER_SHARE_TELEGRAM_GROUP_ID` = 上一步的完整负数 ID，
   然后 **Save, deploy**，等部署完成。
5. Bot 已在 [自动化中心](https://flask-393d.onrender.com/admin/automation)
   绑定为 `客户分享链接 / ORDER_SHARES` 的情况下不用重新填写 Token。
   没有绑定时，需要原管理员登入一次 Automation Hub 绑定 Bot Token。

旧环境变量 `ORDER_SHARE_TELEGRAM_ALLOWED_IDS` 仍可用于**群组未配置时**的旧白名单，
但一旦配置私人群组，授权只看**是否仍在该群组中**，不再看旧白名单。
不需要设置 `ORDER_SHARE_TELEGRAM_ACCESS_CODE`，也不需要发送 `/login`。

## 员工日常使用（无需翻页）

1. 管理员邀请员工加入**唯一指定的私人群组**；Bot 必须是该群组管理员。
2. 群组里第一次发送 `/menu` 或 `/start`，Telegram 会显示常驻的
   **「📋 全部客戶」**键盘按钮。以后点一下就查所有有效分享，不用记住命令。
   也可直接输入 `/all`、`全部`、`todo` 或 `ALL`。
3. **全部清单不再需要手动点下一页**：
   - 一次从 Render/TiDB 只读查询**所有**目前有效的分享；
   - 一条 Telegram 消息最多 20 条客户链接。超出时 Bot
     **自动连续发送后续消息**，无须员工按「下一页」；
   - 为避免 Telegram 消息超过长度上限，客户姓名很长时会提早自动拆分；
   - 已发送过的旧版「下一页」按钮会改为打开**完整清单**。
4. 客户姓名本身是完整可点击的分享 URL，直接点开；下面的📋数字按钮
   按列表编号复制对应 URL。只有一个结果时显示「📋 複製連結」。
5. 输入 `SERGIO`、`CONDO SERGIO` 或 `/links SERGIO`
   可进行客户名称部分匹配、多个关键词任意顺序匹配（暂不容忍错别字）。
   查找结果底下的「📋 全部客戶」也可一键回到所有有效分享。
6. 员工仍可选择私聊 Bot 查资料，但不是必须。
   离开或被移出私人群组后，下一次查询仍会被拒绝。

**关于群组消息量**：如果有效分享很多（例如 85 条），Bot 会自动发出
约 5 则短消息，而不是让员工手动翻 5 页；因此建议仍以输入客户名称
查找单一客户作为日常快速操作。

**权限与数据不变**：只能在指定私人群组或由群组成员私聊 Bot 查询。
群里的客户分享链接对所有当前群成员可见；请限制邀请和外传链接。
Bot 不修改分享、订单或本机 V140，也不下载 B2 图片。

## 重要安全/运维说明

- Telegram Bot 用户名不是私人入口；真正的授权来自私人群组成员身份，
  每一次查询（包括按分页按钮）都向 Telegram 检查是否仍是成员。
- Bot 必须是指定群组的管理员；若 Telegram API 无法确认成员身份，
  采用拒绝访问（fail closed），不会泄露分享。
- 保护 Bot Token、群组邀请链接及分享 URL；分享链接本身仍是可转发的 bearer URL。
- 现有的 Automation Hub 负责 Token 加密、Webhook 验证；
  请不要重新生成 `AUTOMATION_MASTER_KEY`。
- 重用旧 Bot 时需确保它没有被其他 webhook 或轮询程序占用。

## Telegram Mini App（手机一页内完整查询）

在原本 `todo`、`/all`、`SERGIO` 查询之外，新增一页式手机目录：
**完整客户名称（点击打开） + 同一行「📋 複製」**。
可往下滚动，无需翻页；搜索框按客户名称实时筛选，支持无重音大小写、
关键词任意顺序、以及比较接近的单词（小范围拼写错误）。

Render 网址：`https://flask-393d.onrender.com/telegram/order-shares`。
**不能当作普通公开网页登入**：页面本身无客户资料；只有 Telegram
Mini App 提供新鲜且通过服务器 HMAC 验证的 `initData`，并确认用户
仍在公司私人群组时，才会加载现有的有效分享。脱离 Telegram、伪造
Telegram ID、被移出群组的用户都会被拒绝。

### 管理员必须完成一次 BotFather 设置

Telegram 的 **Main Mini App 不能由普通 Bot API 自动创建**，
需由 Bot 所有者在 `@BotFather` 里配置：

1. `/mybots` → 选择 `@XingwangOrderLinkBot`。
2. `Bot Settings` → `Configure Mini App` → `Enable Main Mini App`
   （菜单名称可能随 BotFather 版本略有不同）。
3. 设置 URL：
   `https://flask-393d.onrender.com/telegram/order-shares`
4. 完成后，Bot 在群组可以发送 `/app`，或首次 `/menu`：
   - **📋 全部客戶**：仍然在 Telegram 聊天里显示所有有效分享，
     保留已成功测试的 `todo`。
   - **🔎 客戶清單**：Bot 发送「🔎 開啟客戶清單」Mini App 入口；
     点开就会出现搜索框 + 每行一个复制按钮。
5. 可以把 Bot 发出的「開啟客戶清單」那条消息**置顶在私人群组**，
   员工以后点一下即可进入 Mini App。页面内所有资料即开即查。

Bot Token 与公司私人群组 ID 保持原样，不需要重新输入。
若没有启用 BotFather Main Mini App，`t.me/...?...startapp`
可能只会打开 Bot 聊天，不会打开 Mini App。

## 中國同事專用入口（TiDB 密碼）

中國同事不用 Telegram，也不用 XINGWANG 主系統帳號密碼。
網址：`https://flask-393d.onrender.com/cn/order-links`。

**第一次使用前，必須由現有 XINGWANG 管理員設定密碼**：

1. 以原本管理員帳號登入 Render（`/login`），進入
   `https://flask-393d.onrender.com/admin/automation`。
2. 點「**設定或更換專用密碼**」（也可直接前往
   `/admin/automation/china-links`）。
3. 設定 1–128 字元的獨立專用密碼（可用單一數字，但安全性很弱），按儲存。ADMIN 可隨時修改，修改後舊登入即刻失效。
4. 把 `/cn/order-links` 網址與專用密碼另外傳給中國同事。
   他們可用手機或電腦瀏覽器登入。
5. 登入後同樣有全部有效客戶清單、模糊查找、點名稱開啟、
   一鍵複製連結，不用翻頁。

**儲存位置和權限**：
- 只在 TiDB 的 `order_share_cn_settings` 存帶鹽 PBKDF2 雜湊
  與登入版本號，不記錄明文密碼；不使用 AWS Lambda，也不把密碼放在 HTML 或 JS。
- 中國同事專用 Cookie 有效期 7 天，設定為 Secure / HttpOnly / SameSite；
  管理員更換密碼時，舊 Cookie 即刻失效。
- 未設定密碼前中國入口會停用；所有查詢 API 都再次驗證 Cookie，
  直接打開 API 無法繞過登入。
- 錯誤密碼按來源 15 分鐘內 8 次限制（失敗記錄存 TiDB）；
  管理員改密碼須持有原 Flask 管理員登入與 CSRF 驗證。
- 原本 Telegram Bot（`todo`、`app`、`SERGIO`）完全沿用
  Telegram 身分與公司群組檢查，**不會因為中國入口新增而取消權限驗證**。
- 這是分享清單的存取控制，不會自動禁止已轉傳出去的單條
  `/share/...` 分享網址。

**注意**：如果 Render 沒有使用安全的 `SECRET_KEY` 環境變數，
中國入口會拒絕發出登入票證（fail closed）。首次上線請先確認
原本 Render Flask 有設定安全且長期固定的 `SECRET_KEY`；
**切勿更動已在使用的 SECRET_KEY**，否則會影響原有 Flask 登入。
中國大陸的連線速度與可達性需要當地同事實際測試。

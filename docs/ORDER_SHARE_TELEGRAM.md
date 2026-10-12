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

## 员工日常使用（一键菜单 + 紧凑复制）

1. 管理员将员工加入唯一指定的公司私人群组，Bot 必须是该群组管理员。
2. **第一次在公司群组发送 `/menu`**（也可以发送 `/start`）。
   Bot 会启用 Telegram 的**持续快捷键盘**（ReplyKeyboardMarkup：
   `is_persistent=true`）。键盘中有一个 **「📋 全部客戶」** 按钮，
   员工直接点一下，就会在原群组收到有效客户分享列表；之后无需再记住 `/all`。
   Telegram 客户端仍可自行收起该键盘，需要时可再次输入 `/menu` 展开。
3. 仍可手动发送 `/all`、`全部` 或 `todo`（大小写不敏感）查询，
   最多每页 8 条；底下「上一页 / 全部客戶 / 下一页」用于分页与返回第一页。
4. 搜索时直接输入 `SERGIO`、`CONDO SERGIO` 或 `/links SERGIO`；
   支持名称部分匹配、关键词任意顺序匹配，但不保证拼写错误也能匹配。
5. 每条结果的**完整客户名称**本身就是可点击的分享 URL。
   同时保留 Telegram 原生「复制链接」功能：
   - 搜索只有一条时，下方显示清楚的 **「📋 複製連結」** 按钮。
   - 列表有多条时，用紧凑编号 **📋1、📋2、📋3……** 对应上方编号，
     每排最多 4 个小按钮，避免 8 行长按钮占满手机画面。
   - 搜索结果下还有 **「📋 全部客戶」** 快捷按钮。
   - 如果极少数 URL 超过 Telegram CopyTextButton 的 256 字符限制，
     回覆中会显示可长按复制的文字链接。
6. 群组中的普通闲聊如果未匹配现有客户，不回复，避免刷屏；
   显式使用 `/links 不存在客户` 仍会提示无结果。
7. 群组成员也可选择私聊 Bot 执行相同操作；
   员工被移出群组后，下一次查询与翻页均会失去权限。

**权限与数据不变**：仅指定私人群组及其成员可以查询 Render 中
当前有效的既有分享。群里发的链接对所有当时的群成员可见，
所以群组邀请和分享 URL 不得对外公开。
Bot 不创建或延长任何分享，不修改订单或权限，不读 B2 图片；
本机 ORDER_HOME_V140 不变。

## 重要安全/运维说明

- Telegram Bot 用户名不是私人入口；真正的授权来自私人群组成员身份，
  每一次查询（包括按分页按钮）都向 Telegram 检查是否仍是成员。
- Bot 必须是指定群组的管理员；若 Telegram API 无法确认成员身份，
  采用拒绝访问（fail closed），不会泄露分享。
- 保护 Bot Token、群组邀请链接及分享 URL；分享链接本身仍是可转发的 bearer URL。
- 现有的 Automation Hub 负责 Token 加密、Webhook 验证；
  请不要重新生成 `AUTOMATION_MASTER_KEY`。
- 重用旧 Bot 时需确保它没有被其他 webhook 或轮询程序占用。

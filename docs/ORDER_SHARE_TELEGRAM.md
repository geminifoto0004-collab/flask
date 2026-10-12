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

## 员工日常使用（精简链接界面）

1. 管理员邀请员工加入唯一指定的私人群组，并把 Bot 设置为群组管理员。
2. 在公司群组输入 `/all`、`全部`、`todo`（大小写不敏感）均可查看全部有效分享。
   每页最多 8 条，用「下一页／上一页」翻页；`/all 2` 可直接跳第 2 页。
3. 输入 `SERGIO`、`CONDO SERGIO` 或 `/links SERGIO`：
   按客户名称部分字符串查询，多个关键词不要求顺序一致。
   这是包含匹配，不保证拼写错误也能查到。
4. Bot 在每条结果中直接显示**完整可点击的客户名称**，轻点名称即可打开分享网址。
   不再每条显示「打开 · 截短姓名」及「复制链接」按钮，只有翻页保留按钮。
   结果只显示有效期，省去重复的创建日期；长期有效用「永久」表示。
5. 在群组中输入不匹配客户名称的普通闲聊不会收到「找不到」回复，
   避免 Bot 刷屏；显式使用 `/links 不存在客户` 则仍会提示未找到。
6. 员工也可以私聊 Bot 使用相同命令，但不需要离开公司群组。
   员工被移出群组后，下一次查询（包括翻页按钮）立即失去授权。

**只有配置好的公司群组能在群聊查客户。** 其他群组的客户查询
不会被处理。群组内回复的客户链接对所有当前群成员可见，
因此群组必须保持私人、严格控制邀请，避免把链接外传。
Bot 的权限只允许**读取已经同步到 Render、尚未过期或撤销的分享**；
不会创建新分享或修改订单，不下载 B2 图片，也不影响本机 V140。

## 重要安全/运维说明

- Telegram Bot 用户名不是私人入口；真正的授权来自私人群组成员身份，
  每一次查询（包括按分页按钮）都向 Telegram 检查是否仍是成员。
- Bot 必须是指定群组的管理员；若 Telegram API 无法确认成员身份，
  采用拒绝访问（fail closed），不会泄露分享。
- 保护 Bot Token、群组邀请链接及分享 URL；分享链接本身仍是可转发的 bearer URL。
- 现有的 Automation Hub 负责 Token 加密、Webhook 验证；
  请不要重新生成 `AUTOMATION_MASTER_KEY`。
- 重用旧 Bot 时需确保它没有被其他 webhook 或轮询程序占用。

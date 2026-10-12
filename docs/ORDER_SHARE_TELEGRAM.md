# Render 客户分享链接 Bot

本机 ORDER_HOME_V140 保持原样。功能运行在 Render 已有的 Automation Hub，
读取 TiDB 里目前有效的分享，使用与 Render 分享管理页相同的签名链接。
不会建立新分享、修改权限、上传图片或把整个本机 ORDER 放上 Render。

## 一次性设定

1. 如果没有专用 Bot，在 Telegram 的 `@BotFather` 用 `/newbot` 建立一个。
2. Render 环境变量增加 `ORDER_SHARE_TELEGRAM_ALLOWED_IDS`。
   填入获准查询所有客户分享的 **Telegram 数字用户 ID**，例如 `123456789`；
   多个账号用逗号分隔。不要填电话、用户名或群组 ID。
3. 使用原账号登入一次 [自动化中心](https://flask-393d.onrender.com/admin/automation)。
   Bot key 可填 `order-shares`，名称填 `客户分享链接`，
   Plugin 选 `客户分享链接 / ORDER_SHARES`，粘贴 BotFather 的 Token，保存。
   原中心会加密保存 Token，并自动连接带密钥验证的 Telegram webhook。
4. 如果还不知道数字用户 ID，可先完成第 3 步，在新 Bot 私聊发送 `/id`。
   Bot 只回传发送者自己的 ID；未列入授权名单的账号不能查询客户。
   把这个 ID 填入第 2 步的环境变量并部署后，即可查询。
5. 原自动化中心若尚未配置 `AUTOMATION_MASTER_KEY`，按它既有的流程设置一次。
   已配置时沿用原值；不要更改或重新生成，否则既有 Bot Token 无法解密。
   正常 Render 服务会以 `RENDER_EXTERNAL_URL` 作为服务网址。

不要把 Bot Token 放进 Git 或公开聊天。
若要沿用既有 Bot，先确认它不是正在连接另一套 webhook／轮询程序；
同一 Bot 的 Telegram 更新只能由一个接收入口处理。

## 平常使用

在 Bot **私聊**输入 `OSCAR`、`SERGIO` 或客户名称的一部分。
也可使用 `/links OSCAR`。Bot 回传名称、有效期与「打开／复制链接」按钮。
未开通、已撤销或已过期的分享不会显示。
多个符合的分享会显示最近匹配的最多 5 条；输入更完整名称可缩小范围。
不同有效链接保留原有各自权限，不会自动合并或扩大客户可见范围。

以后查链接不需要再次登入网页；Render 持续运行时，本机关掉也能查询。
Bot 只知道已经同步到 Render 的有效分享，无法查询尚未开通或未同步的本机客户。

## 改动与验证

- Automation Hub 只新增 `ORDER_SHARES` lazy plugin，不改 Aduana 的接收或通知。
- 新模块 `services/order_share_telegram_bot.py`。
- 查询最多一条有限结果 SELECT，不读订单图片、不压缩、不调用 B2。
- Telegram 数字 ID 授权；群组、频道、陌生账号不会取得客户链接。
- 单后台发送线程，最多 16 个待处理查询；Flask webhook 不等待 Telegram 回复网络。
- 现有签名链接仍由原分享状态、有效期、可见权限和资源归属检查决定。
- 使用模拟网络／临时数据库验证，不向真实客户发送测试讯息。

Telegram 官方参考：
[Bot API](https://core.telegram.org/bots/api) 的 webhook、sendMessage 与 CopyTextButton。

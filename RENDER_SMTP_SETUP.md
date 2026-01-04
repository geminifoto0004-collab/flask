# 📧 Render SMTP 配置指南

## ⚠️ 问题说明

如果遇到 `[Errno 101] Network is unreachable` 错误，这通常是因为 **Render 的网络环境无法访问 Gmail SMTP 服务器**。

**注意**：如果本机可以发送邮件，说明代码和密码都是正确的，问题确实是 Render 的网络限制。

## 🔧 解决方案

### 方案 1：尝试不同的端口（推荐先试这个）

在 Render 的 Environment 变量中添加：

```bash
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=465  # 尝试 SSL 端口
```

或者：

```bash
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587  # 使用 STARTTLS 端口（默认）
```

### 方案 2：使用其他 SMTP 服务（如果 Gmail 无法使用）

#### 选项 A：Mailgun（推荐，免费 5000 封/月，最宽松）

1. 注册 Mailgun：https://www.mailgun.com
2. 获取 SMTP 凭证
3. 在 Render 环境变量中设置：

```bash
SMTP_SERVER=smtp.mailgun.org
SMTP_PORT=587
SMTP_EMAIL=你的_Mailgun_SMTP_用户名
SMTP_PASSWORD=你的_Mailgun_SMTP_密码
```

#### 选项 B：Resend（免费 3000 封/月，简单易用）

1. 注册 Resend：https://resend.com
2. 创建 API Key
3. 在 Render 环境变量中设置：

```bash
SMTP_SERVER=smtp.resend.com
SMTP_PORT=587
SMTP_EMAIL=resend  # Resend 使用 'resend' 作为用户名
SMTP_PASSWORD=你的_Resend_API_Key  # 你的 Resend API Key
```

#### 选项 C：Brevo (原 Sendinblue)（免费 300 封/天）

1. 注册 Brevo：https://www.brevo.com
2. 获取 SMTP 凭证
3. 在 Render 环境变量中设置：

```bash
SMTP_SERVER=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_EMAIL=你的_Brevo_邮箱
SMTP_PASSWORD=你的_Brevo_SMTP_密码
```

#### 选项 D：AWS SES（按使用量付费，前 62,000 封免费）

1. 设置 AWS SES
2. 获取 SMTP 凭证
3. 在 Render 环境变量中设置：

```bash
SMTP_SERVER=email-smtp.区域.amazonaws.com  # 例如：email-smtp.us-east-1.amazonaws.com
SMTP_PORT=587
SMTP_EMAIL=你的_AWS_SES_SMTP_用户名
SMTP_PASSWORD=你的_AWS_SES_SMTP_密码
```

### 方案 3：暂时禁用邮件功能

如果暂时不需要邮件功能，可以：

1. 在注册流程中跳过邮件验证（需要修改代码）
2. 或使用其他验证方式

## 📝 在 Render 上设置环境变量

1. 登录 Render Dashboard
2. 选择你的 Web Service
3. 点击左侧 **"Environment"** 标签
4. 点击 **"Add Environment Variable"** 按钮
5. 添加以下变量：

```bash
# Gmail（如果可以使用）
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=geminifoto0004@gmail.com
SMTP_PASSWORD=pczrwlzhuxxlozot  # 16 字符，去掉空格

# 或者使用 Mailgun（推荐）
SMTP_SERVER=smtp.mailgun.org
SMTP_PORT=587
SMTP_EMAIL=你的_Mailgun_SMTP_用户名
SMTP_PASSWORD=你的_Mailgun_SMTP_密码

# 或者使用 Resend
SMTP_SERVER=smtp.resend.com
SMTP_PORT=587
SMTP_EMAIL=resend
SMTP_PASSWORD=你的_Resend_API_Key

# 或者使用 Brevo
SMTP_SERVER=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_EMAIL=你的_Brevo_邮箱
SMTP_PASSWORD=你的_Brevo_SMTP_密码
```

## ✅ 测试

部署后，尝试注册功能，查看是否能够发送邮件。

如果仍然失败，查看 Render 日志中的 `[SMTP]` 相关日志，了解具体在哪一步失败。

## 🔍 调试

代码会自动输出详细的调试信息：

```
[SMTP] 嘗試連接到 smtp.gmail.com:587
[SMTP] 使用 STARTTLS 連接（端口 587）
[SMTP] 連接成功，嘗試登入: geminifoto0004@gmail.com
[SMTP] 嘗試登入 - 去掉空格（長度: 16）
[SMTP] 登入成功 - 去掉空格（長度: 16）
```

如果看到这些日志，说明代码执行正常，问题可能是网络连接。

## 💡 推荐

对于生产环境，建议使用专业的邮件服务（如 SendGrid 或 Mailgun），而不是 Gmail SMTP，因为：

1. 更稳定可靠
2. 更好的送达率
3. 更多的发送配额
4. 更好的网络兼容性


# 📧 Resend API 配置指南

## 🎯 什么是 Resend？

Resend 是一个现代化的邮件发送服务，提供：
- ✅ 免费 3000 封/月
- ✅ 不受 Render 网络限制
- ✅ 简单易用的 API
- ✅ 高送达率

## 📝 注册和获取 API Key

### 步骤 1：注册 Resend 账号

1. 访问：https://resend.com
2. 点击 **"Sign Up"** 注册账号（可以使用 GitHub 账号快速注册）
3. 完成邮箱验证

### 步骤 2：创建 API Key

1. 登录后，进入 **Dashboard**
2. 点击左侧菜单 **"API Keys"**
3. 点击 **"Create API Key"** 按钮
4. 输入名称（例如：`Render Production`）
5. 选择权限（选择 **"Sending access"** 即可）
6. 点击 **"Add"**
7. **复制 API Key**（格式类似：`re_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）
   - ⚠️ **重要**：API Key 只显示一次，请立即复制保存！

### 步骤 3：验证发送域名（可选，但推荐）

#### 选项 A：使用 Resend 提供的测试域名（快速开始）

Resend 提供测试域名：`onboarding@resend.dev`

- ✅ 可以直接使用，无需验证
- ✅ 适合测试和开发
- ⚠️ 限制：只能发送到已验证的邮箱地址（你注册 Resend 时使用的邮箱）

**使用方法**：
- `RESEND_FROM_EMAIL=onboarding@resend.dev`

#### 选项 B：验证自己的域名（生产环境推荐）

1. 在 Resend Dashboard 中，点击 **"Domains"**
2. 点击 **"Add Domain"**
3. 输入你的域名（例如：`example.com`）
4. 按照提示添加 DNS 记录（SPF、DKIM、DMARC）
5. 等待验证完成（通常几分钟）
6. 验证成功后，可以使用：`noreply@example.com` 或 `hello@example.com`

**使用方法**：
- `RESEND_FROM_EMAIL=noreply@yourdomain.com`

## 🔧 在 Render 上配置

### 方法 1：使用环境变量（推荐）

在 Render Dashboard 中：

1. 选择你的 **Web Service**
2. 点击左侧 **"Environment"** 标签
3. 点击 **"Add Environment Variable"**
4. 添加以下变量：

```bash
# 邮件服务提供商（设置为 resend）
EMAIL_PROVIDER=resend

# Resend API Key（从 Resend Dashboard 复制）
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 发送邮件地址（使用测试域名或已验证的域名）
RESEND_FROM_EMAIL=onboarding@resend.dev
```

### 方法 2：使用代码中的默认值（仅本地开发）

如果环境变量未设置，代码会使用 `config.py` 中的默认值：

```python
RESEND_API_KEY = 're_BMeetzHZ_HMFb9HRSihVcujLrtterRD9x'  # 👈 你的 Resend API Key
RESEND_FROM_EMAIL = 'onboarding@resend.dev'  # 👈 改為你在 Resend 驗證的發送地址
```

⚠️ **注意**：这些默认值仅用于本地开发，生产环境请使用环境变量！

## 📋 完整的环境变量清单

在 Render 上，你需要设置以下变量：

### 必须设置的变量：

```bash
# 邮件服务提供商
EMAIL_PROVIDER=resend

# Resend API 配置
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # 👈 从 Resend Dashboard 获取
RESEND_FROM_EMAIL=onboarding@resend.dev  # 👈 使用测试域名或已验证的域名
```

### 可选变量（如果使用 Resend，这些不需要）：

```bash
# 以下 SMTP 变量在 EMAIL_PROVIDER=resend 模式下不会被使用，可以删除
# SMTP_SERVER=smtp.gmail.com
# SMTP_PORT=587
# SMTP_EMAIL=geminifoto0004@gmail.com
# SMTP_PASSWORD=pczr wlzh uxxl ozot
```

### 其他必要的环境变量：

```bash
# 数据库配置（TiDB）
DB_TYPE=tidb
DB_HOST=xxx.tidbcloud.com
DB_PORT=4000
DB_USER=xxx
DB_PASSWORD=xxx
DB_NAME=xxx

# Flask 密钥
SECRET_KEY=your-secret-key-here

# 超级管理员（可选，有默认值）
SUPER_ADMIN_EMAIL=admin@xingwang.com
SUPER_ADMIN_PASSWORD=12345678
```

## ✅ 测试

部署后，尝试注册功能，查看是否能够发送邮件。

### 检查日志

在 Render 日志中，你应该看到：

```
[Email] 郵件服務提供商: resend
[Email] 使用 Resend API 發送郵件
[Resend API] 嘗試發送郵件到: user@example.com
[Resend API] 郵件發送成功: {'id': 'xxx'}
```

### 如果失败

1. **检查 API Key**：确保 `RESEND_API_KEY` 正确（以 `re_` 开头）
2. **检查发送地址**：确保 `RESEND_FROM_EMAIL` 正确
3. **检查权限**：确保 API Key 有 "Sending access" 权限
4. **检查收件人**：如果使用测试域名 `onboarding@resend.dev`，只能发送到已验证的邮箱

## 💡 常见问题

### Q: 可以使用自己的邮箱地址吗？

A: 可以，但需要验证域名。如果使用 `onboarding@resend.dev`，只能发送到已验证的邮箱。

### Q: 免费额度是多少？

A: Resend 免费提供 3000 封/月，对于大多数应用来说足够了。

### Q: 如何升级到付费版？

A: 在 Resend Dashboard 中，点击 **"Billing"** 可以升级到付费计划。

### Q: 可以发送到任何邮箱吗？

A: 如果使用已验证的域名，可以发送到任何邮箱。如果使用测试域名 `onboarding@resend.dev`，只能发送到已验证的邮箱。

## 🔗 相关链接

- Resend 官网：https://resend.com
- Resend 文档：https://resend.com/docs
- Resend Dashboard：https://resend.com/api-keys
- Resend 域名验证：https://resend.com/domains


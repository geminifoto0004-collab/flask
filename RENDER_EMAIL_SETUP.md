# 🔧 Render 邮件发送设置指南

## ✅ 解决方案

您的问题：设置了 `EMAIL_PROVIDER=resend`，但 Resend API 有限制（只能发送测试邮件到自己的邮箱）。

**解决方法**：使用 PythonAnywhere 的 Email API 来发送邮件，而不是 Resend API。

---

## 🚀 设置步骤

### 1. 在 Render 中设置环境变量

在 Render 的 **Environment Variables** 中添加：

```bash
PYANYWHERE_EMAIL_API_URL=http://XINGWANGTEXTIL.pythonanywhere.com/api/email
```

**重要**：
- ✅ **设置** `PYANYWHERE_EMAIL_API_URL`
- ❌ **删除或注释掉** `EMAIL_PROVIDER=resend`（不需要了）

### 2. 可选：设置 API Key（如果 PythonAnywhere 设置了 EMAIL_API_KEY）

如果您的 PythonAnywhere 项目设置了 `EMAIL_API_KEY` 环境变量，在这里也设置相同的值：

```bash
PYANYWHERE_EMAIL_API_KEY=your-api-key-here
```

---

## 📝 工作原理

当设置了 `PYANYWHERE_EMAIL_API_URL` 后：

1. ✅ 代码会**优先**使用 PythonAnywhere 的 Email API
2. ✅ 跳过 Resend API 和 SMTP
3. ✅ 通过 HTTP 请求调用 PythonAnywhere 的 `/api/email/send` 或 `/api/email/send-batch` 端点
4. ✅ PythonAnywhere 使用 SMTP 发送邮件（不受 Render 限制）

---

## ✅ 验证

设置环境变量后，重启 Render 应用，发送邮件时应该看到日志：

```
[Email] 使用 PythonAnywhere Email API 發送郵件
[PythonAnywhere API] 發送請求到: http://XINGWANGTEXTIL.pythonanywhere.com/api/email/send
[PythonAnywhere API] 郵件發送成功
```

而不是：

```
[Email] 郵件服務提供商: resend
[Email] 使用 Resend API 發送郵件
```

---

## 📋 环境变量总结

### 必需的环境变量

```bash
PYANYWHERE_EMAIL_API_URL=http://XINGWANGTEXTIL.pythonanywhere.com/api/email
```

### 可选的环境变量

```bash
# 如果 PythonAnywhere 设置了 EMAIL_API_KEY
PYANYWHERE_EMAIL_API_KEY=your-api-key-here
```

### 不再需要的环境变量

```bash
# ❌ 可以删除或注释掉
# EMAIL_PROVIDER=resend
```

---

## 🎉 完成！

设置完成后，您的 Render 应用就会通过 PythonAnywhere 的 Email API 发送邮件了，不会再使用 Resend API！


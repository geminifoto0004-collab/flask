# 🔐 安全配置說明

## ⚠️ 重要安全提示

**請務必通過環境變數設置敏感信息，不要將密碼硬編碼在代碼中！**

## 🔒 必須設置的環境變數

### 1. Flask 密鑰（SECRET_KEY）
```bash
# 生成方法
python -c "import secrets; print(secrets.token_hex(32))"

# 設置環境變數
SECRET_KEY=生成的隨機字符串
```

### 2. 超級管理員配置
```bash
SUPER_ADMIN_EMAIL=admin@xingwang.com
SUPER_ADMIN_PASSWORD=你的安全密碼
```

### 3. SMTP 郵件配置（如果需要發送郵件）
```bash
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your-app-password
```

### 4. 資料庫配置
根據你使用的資料庫類型設置相應的環境變數。

## 📝 設置方法

### 本地開發
1. 複製 `.env.example` 為 `.env`
2. 填入你的實際值
3. `.env` 文件已被 `.gitignore` 忽略，不會提交到 GitHub

### Render
1. 進入 Render Dashboard
2. 選擇你的 Web Service
3. 點擊 "Environment" 標籤
4. 添加環境變數

### PythonAnywhere
1. 進入 Web 設置頁面
2. 找到 "Environment variables"
3. 添加環境變數

## ✅ 檢查清單

部署前請確認：
- [ ] `SECRET_KEY` 已設置為隨機字符串
- [ ] `SUPER_ADMIN_EMAIL` 已設置
- [ ] `SUPER_ADMIN_PASSWORD` 已設置（不是默認值）
- [ ] `SMTP_EMAIL` 和 `SMTP_PASSWORD` 已設置（如果需要郵件功能）
- [ ] 資料庫配置已正確設置
- [ ] `.env` 文件已添加到 `.gitignore`
- [ ] 沒有將敏感信息提交到 GitHub

## 🚨 如果已經提交了敏感信息

如果已經將敏感信息提交到 GitHub：

1. **立即更改所有密碼和密鑰**
2. **從 Git 歷史中移除敏感信息**（使用 `git filter-branch` 或 BFG Repo-Cleaner）
3. **檢查是否有其他人克隆了倉庫**
4. **考慮重新生成所有密鑰和密碼**

## 📚 更多信息

- 查看 `.env.example` 了解所有可用的環境變數
- 查看 `RENDER_SETUP_GUIDE.md` 了解 Render 部署配置
- 查看 `DATABASE_TYPE_CONFIG.md` 了解資料庫配置


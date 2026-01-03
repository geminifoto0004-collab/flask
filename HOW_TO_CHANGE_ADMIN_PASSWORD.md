# 🔐 如何修改超級管理員帳號和密碼

## 📍 最簡單的方法：直接修改 config.py

**直接修改 `config.py` 文件**即可修改帳號（郵箱）和密碼！

### 步驟：

1. **打開文件**: `config.py`

2. **找到第 44-45 行**，看到這兩行代碼：
   ```python
   SUPER_ADMIN_EMAIL = 'admin@xingwang.com'  # 修改這裡改帳號
   SUPER_ADMIN_PASSWORD = '12345678'  # 修改這裡改密碼
   ```

3. **修改帳號**（第 44 行）：
   ```python
   SUPER_ADMIN_EMAIL = 'your_new_email@example.com'  # 改成你的新郵箱
   ```

4. **修改密碼**（第 45 行）：
   ```python
   SUPER_ADMIN_PASSWORD = 'your_new_password'  # 改成你的新密碼
   ```

5. **保存文件**

6. **重啟應用**（如果正在運行）

### ✅ 完成！

現在你就可以用新的帳號和密碼登入了。

---

## 📝 當前配置方式

系統現在使用**直接配置方式**，帳號和密碼都在 `config.py` 文件中：

- ✅ **簡單直接**：修改一個文件就行
- ✅ **容易找到**：帳號在第 44 行，密碼在第 45 行
- ✅ **不需要環境變數**：不需要記住如何設置環境變數

### ⚠️ 安全提示

- 如果是**公開代碼庫**，建議不要將真實密碼提交到 Git
- 如果是**私有代碼庫**或**本地開發**，這種方式最簡單方便

---

## 🛠️ 如何使用環境變數（可選）

如果你**想要使用環境變數**，下面是設置方法：

### Windows 系統

#### 方法1：臨時設置（關閉命令行後失效）
```cmd
set SUPER_ADMIN_PASSWORD=你的密碼
```

#### 方法2：永久設置
1. 右鍵「此電腦」→「屬性」
2. 點擊「高級系統設置」
3. 點擊「環境變數」按鈕
4. 在「用戶變數」或「系統變數」中點擊「新建」
5. 變數名：`SUPER_ADMIN_PASSWORD`
6. 變數值：你的密碼
7. 點擊「確定」保存

### Linux/Mac 系統

#### 方法1：臨時設置（關閉終端後失效）
```bash
export SUPER_ADMIN_PASSWORD="你的密碼"
```

#### 方法2：永久設置
編輯 `~/.bashrc` 或 `~/.zshrc` 文件，添加：
```bash
export SUPER_ADMIN_PASSWORD="你的密碼"
```
然後運行：
```bash
source ~/.bashrc
```

### PythonAnywhere（生產環境）

1. 登入 PythonAnywhere
2. 點擊頂部的 **Web** 標籤
3. 找到 **Environment variables** 區塊
4. 點擊 **Add a new variable**
5. 變數名：`SUPER_ADMIN_PASSWORD`
6. 變數值：你的密碼
7. 點擊 **Save**
8. 重載 Web 應用（點擊綠色的 **Reload** 按鈕）

---

## 📝 總結

### 🎯 修改帳號和密碼的方法

**直接修改 `config.py` 第 44-45 行**：

```python
# 修改帳號（第 44 行）：
SUPER_ADMIN_EMAIL = 'your_new_email@example.com'

# 修改密碼（第 45 行）：
SUPER_ADMIN_PASSWORD = 'your_new_password'
```

### 🔍 如何確認當前使用的帳號密碼

運行檢查工具：
```bash
python check_admin_credentials.py
```

或者直接查看 `config.py` 第 55-56 行。

---

## ⚠️ 重要提示

1. **修改後需要重啟應用**才能生效
2. **記住新帳號和密碼**，或把它保存在安全的地方
3. **帳號和密碼都在 `config.py` 第 44-45 行**，如果忘記，可以去那裡查看

---

**最後更新**: 2026-01-01  
**帳號位置**: `config.py` 第 44 行  
**密碼位置**: `config.py` 第 45 行


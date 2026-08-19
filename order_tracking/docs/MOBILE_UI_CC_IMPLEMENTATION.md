# order_tracking 手機版 UI 重做說明
日期：2026-08-16

## 基底
本版從：
`order_tracking_Render雲端唯讀與手機版_20260816.zip`

繼續修改，沒有退回舊版。

## 參考來源
手機 UI 依照使用者提供的：
- `手機版UI設計規格.md`
- `mobile_login_page.html`
- `mobile_customer_thread_mode.html`

配色改用 order_tracking 現有品牌色：
- 主色：紅 `#ff2442`
- 正常：綠
- 注意：橙 / 黃
- 逾期：紅
- 雲端唯讀：淡黃提示

## 本版重點
1. 手機版不再把桌面 17 欄 Table 硬轉直排卡片。
2. 桌面 Table 完全保留。
3. <=768px 改為獨立手機渲染。
4. 手機首頁支援：
   - 搜尋客戶 / 訂單號
   - 階段膠囊
   - 業務員膠囊
   - 更多業務員 Bottom Sheet
   - 燈號篩選
   - 按訂單 / 按客戶模式
5. 按訂單：
   - WhatsApp 聯絡人式列表
   - 客戶首字頭像
   - 客戶名稱
   - 狀態 + 訂單號
   - 業務員
   - 右側燈號
6. 按客戶：
   - 依客戶分組
   - 使用該客戶最嚴重燈號
   - 顯示訂單筆數
   - 顯示最近狀態
7. 客戶詳情：
   - 客戶名稱 / 訂單數
   - 主管 / 管理員顯示「生成報告 / 查詢連結」
   - 客戶所有訂單精簡列表
   - 本地「生成報告」沿用現有 customer report PDF
   - Cloud 的 report_requests / Token 尚未接 TiDB，因此目前明確提示尚未啟用，不假裝成功
8. 手機導航：
   - 移除原本把 Sidebar 變成一排小 icon 的做法
   - 改成頂部 Header + 右側抽屜選單
9. Cloud Mode：
   - 淡黃固定提示
   - 顯示最後同步時間
   - 後端唯讀保護仍保留
10. 手機登入：
   - 改成置中單卡
   - 品牌紅 Logo
   - Cloud 登入頁顯示唯讀提示

## 尚未接的功能
以下屬後續 TiDB / Render 階段，本版只預留 UI：
- `/c/<token>`
- customer_tokens
- report_requests Cloud Queue
- Render TiDB 真實 Provider

## 驗證
已做：
- Python compileall
- Jinja template parse
- JavaScript `node --check`
- CSS brace balance
- 390x844 手機 mock render 檢查，無水平溢出

## 2026-08-16：简体中文 / Español 切换
- 新增单键语言切换，登录页、手机 Header、桌面侧栏均可切换。
- 支持语言：`zh_cn` / `es`。
- 选择保存在浏览器 `localStorage`：`tracking_ui_language`，刷新及下次打开仍保留。
- 登录页、Cloud 唯读提示、手机搜索/筛选/按订单/按客户/客户详情等核心界面同步切换。
- 订单状态沿用统一 `STATUS_LABELS`，新增前端 Spanish labels；旧数据库若仍存中文状态，也会先反查 canonical key 再显示 Spanish。
- 语言切换只改变显示，不改数据库、不改筛选逻辑、不改权限、不改订单状态 key。

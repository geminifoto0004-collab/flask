# 手機 / 本地 Guest：PDF 附件逐頁顯示

更新日期：2026-08-17

## 目的
訂單或流程附件若為 PDF，手機客戶 PERFIL、手機單一訂單圖片輪播，以及本地辦公室臨時 Guest 頁，皆可把 PDF 每一頁視為一張圖片直接瀏覽。

## 行為
- JPG/PNG/WebP 等圖片維持原邏輯。
- PDF 不修改原檔，使用 PyMuPDF 按需渲染指定頁為 JPEG。
- 手機內部頁面只在 `?visual=1` 時取得 PDF 頁數，避免桌面一般附件列表額外開啟 PDF。
- 手機圖片名稱顯示 `原檔名 · PDF 1/N`。
- 客戶 PERFIL 的訂單封面/滑動圖也會包含 PDF 頁。
- 本地 Guest 客戶總訂單可用 PDF 第一頁作封面；點進訂單後可逐頁查看完整 PDF。
- Guest PDF 頁仍受短時 Token、單一客戶與 LAN 限制；不能藉由改 URL 讀取其他客戶 PDF。
- Guest PDF 頁使用 no-store；登入內部頁可使用短時間 private browser cache。

## 依賴
`PyMuPDF>=1.24,<2` 與 `Pillow` 已存在於 requirements。

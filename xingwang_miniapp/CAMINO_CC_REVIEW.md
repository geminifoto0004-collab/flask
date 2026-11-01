# XINGWANG SCANNER — CAMINO 客戶訂單 / 公司備貨分類（CC 審查版）

## 狀態
- 此分支是 **審查版**。禁止自動合併或部署 Render。
- 基底：現有 \`xingwang-stock\` 程式，**保留原本 SAMPLE、QR 相機、購物車、TiDB、權限以及原本 DATA API**。
- 前端只針對「待到貨 / Camino」增加：全部／客戶訂單／公司備貨／待確認，並顯示分類、訂單號、客戶、原始描述。
- 原始 \`camino\` 行資料不會被修改，分類只在瀏覽器中計算，沒有寫入 TiDB、Access 或資料回傳結構。
- 要給 CC 審查的完整程式：\`xingwang_miniapp/scanner.html\`、\`scanner_cart.js\`、\`scanner_backend.py\`、\`scanner_cart.py\`、\`scanner_tidb.py\`、\`miniapp_server.py\` 等，請使用此分支的完整 ZIP。

## 重要資料相依（CC 必須核對）
原始 Access 表 \`Camino\` 的 \`Descripcion\` 存在，舊版本機查詢的 SQL 有讀取：
\`SELECT ... c.Descripcion FROM Camino c LEFT JOIN Nave n ...\`。

但是現有 SCANNER 的 \`fullData.camino\` 在畫面程式中只使用：
\`code, container, caja, units, unit_type, eta\`，**尚未確認目前 V33 轉接回覆是否包含描述**。
此版解析支援 \`Descripcion\`、\`descripcion\`、\`description\`、\`observaciones\` 等別名。
如 V33 正規化時把 \`Descripcion\` 丟掉，CC 必須在 **本機 V33 原始程式** 將其安全傳到
\`fullData.camino[].description\`；必要時也可提供 \`glosa\`，但不能把 \`glosa\` 當作訂單描述。
**未取得描述，一律顯示「待確認」，絕不可誤當「公司備貨」。**

參考橋接純函式 \`camino_description_bridge_adapter.py\`；它是供 CC 整合到 V33 的範例，
不是新的服務，也沒有修改現有 V33 程式。

## 判斷規則（保守）
- 有明確訂單標記 + 合法的編號 + 客戶名稱，判斷為「客戶訂單」。
- 例：\`定单号：1008149 WALTER HERRERA 660克/米 公司封条\` → 1008149 / WALTER HERRERA。
- 編號支援 \`KC26001\`、\`G26001\`、\`1008000\`、\`1008149\`，並保留其他字母+數字格式。
- 只有強烈自有備貨詞（\`公司備貨\`、\`補貨\`、\`STOCK PROPIO\` 等）才能標「公司備貨」。
- 只有訂單編號但缺客戶名、沒有描述、描述只是重量、證據互相矛盾 → 「待確認」。
- \`公司封條 / 公司封条\` 不等於公司備貨，**不應被它誤判**。
- 不修改原始描述；沒有匹配到的內容仍可直接查看。

## CC 審查重點
1. 檢查 V33 實際回傳 \`camino\` 的字段（需保留 \`Descripcion\`）。
2. 在 iPhone Chrome 用 320/390/428px 驗證 4 個分類鈕、商品卡、完整客戶姓名、原始描述。
3. 驗證「預訂」/「歷史購買」原頁面未受影響；分類只在 \`fullTab==='camino'\` 啟用。
4. 依真實 Access 資料收集錯誤分類例子，再改善 Regex；**不要自動寫回資料庫**。
5. 連續相機仍是既有 \`fps:10\`、\`qrbox:220x220\`；同頁更新庫存、SAMPLE SAVE 行為不變。
6. \`node xingwang_miniapp/tests/test_camino_classifier.js\` 執行規則測試。

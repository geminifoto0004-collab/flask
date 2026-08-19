# 客户报告：图片顺序按钮 + PDF 附件选择

- Web 的“图片顺序”从下拉选单改成 3 个按钮。
- 新增 PDF 附件选项：
  - `pages`：逐页拆成 JPEG 后加入最终报告。
  - `skip`：报告忽略 PDF 附件。
- Web 只有检测到所选订单/来源存在 PDF 附件时才显示 PDF 选项。
- 手机报告设置也提供相同 PDF 选项，避免手机与 Web 规则不一致。
- 后端 Queue request key 包含 `pdf_attachment_mode`，不同 PDF 规则不会被误判成重复任务。
- 原始 PDF 永远不修改。
- `.bak` / `.api_before` 已从发布包移除，根目录说明文件已归档到 `docs/`。

## Cloud read-only
本次没有把本机 `/api/customer-reports/jobs` 直接加入 Cloud read-only POST 白名单。
当前 Render 设计是由 TiDB `report_requests` 建立请求，再由 Chile/PyQt worker 生成含本机附件的报告；直接放行本机 worker 端点会让 Render 尝试读取不存在的本地 SQLite/附件。等 cloud report-request endpoint 接通时，应白名单那个“建立报告请求”的端点。

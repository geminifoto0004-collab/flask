# 临时客户页：PDF 报告权限 + 横向时间轴（2026-08-17）

## 最终决定
离线互动 HTML 下载/分享功能已移除。客户报告只保留 PDF；本地 Guest 页面继续作为在线互动查看界面。

## QR / 临时链接权限
- `allow_pdf_download`：旧的原始 PDF 附件 ZIP 权限字段保留兼容，但 UI 默认隐藏。
- `allow_report_pdf_download`：允许按需生成、先打开查看、再决定是否下载客户安全 PDF 报告。
- `show_pdf_pages`：决定 Guest 页面与 PDF 报告是否把 PDF 附件逐页转换成预览图片。

权限仅在临时 token 有效期间允许服务器请求。链接过期或被立即撤销后，服务器拒绝新的查看/生成/下载请求。已经下载到客户设备的 PDF 文件快照无法远程收回。

Schema 变更仍通过 `ensure_local_guest_link_tables()` 的安全可重复 migration 完成。旧数据库若已经存在过去版本留下的废弃字段，不做破坏性 DROP；应用代码不再读取或写入互动 HTML 权限。

## Guest 单笔订单时间轴
主进度保持 5 阶段横向时间轴：

`Pedido → Diseño → Muestra → Producción → Envío`

- 已完成阶段：绿色勾选。
- 当前阶段：红色高亮。
- 未来阶段：灰色。
- 每个阶段下方显示可确认的阶段日期。
- 原始状态变更历史保留在详细历史折叠区。

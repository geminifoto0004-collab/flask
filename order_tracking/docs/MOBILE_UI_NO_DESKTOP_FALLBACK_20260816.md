# 手机 UI 第二轮修正（2026-08-16）

本版从 `order_tracking_Render雲端唯讀_CC手機UI_站內返回修正_20260816.zip` 继续修改。

## 修正
- 手机菜单移除会打开桌面 Modal / 桌面管理页的入口。
- 手机客户报告不再打开桌面 customer report Modal，改成手机 Bottom Sheet，仍调用既有 customer report backend。
- 手机模糊搜索复用桌面 `getFrontEndSearchSuggestions()` 排序与匹配逻辑，并显示可点击下拉建议。
- 从客户订单进入订单详情再返回时，恢复滚动位置并高亮刚看过的订单。
- 按订单模式返回列表时同样恢复列表位置与高亮。
- 区域网 / 本地模式的订单详情会读取 order_files + workflow_files 图片，显示手机图片网格与站内全屏预览。
- Render Cloud Mode 不请求本地图片，保持摘要唯读。
- 手机上隐藏桌面 customer report Modal / 桌面 report queue drawer，避免任何“跳回桌面 UI”的感觉。
- 桌面版现有 Workspace / 管理页 / 报告 Modal 均未删除，只是在 <=768px 手机界面不再调用它们。

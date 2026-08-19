# WEB 深浅色切换稳定性 + KPI 卡片修正

本次从上一版完整项目继续修改。

- 修复桌面 WEB 连续切换浅色/深色时，部分区域短暂或缓存后出现混色的问题。
- 主题切换改为原子应用：切换期间短暂关闭 CSS transition，避免多处 `transition: all` 产生不同步。
- `pageshow` / localStorage 跨页面恢复时会重新同步主题。
- `STATIC_VER` cache-busting 纳入 `theme.css` 与 `theme.js`，避免部署后浏览器继续使用旧主题文件。
- 深色模式的正常/需注意/逾期 KPI 卡片与业务员卡片改为深色 surface，不再保留刺眼白卡。
- 增加桌面浅色模式明确覆盖，回到浅色时表头、表格、分页和卡片统一恢复浅色。

不修改订单数据、筛选逻辑、权限、SQLite/TiDB schema。

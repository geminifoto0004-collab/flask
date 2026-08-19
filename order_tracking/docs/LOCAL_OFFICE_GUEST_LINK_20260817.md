# 本地办公室临时客户查看链接（2026-08-17）

## 使用场景
客户人在办公室并已连接公司 Wi-Fi 时，管理员/主管可以在手机版「按客户」页面点击「临时查看」，生成一个无需登录的短时效链接。

## 有效时间
- 30 分钟
- 1 小时
- 4 小时

到期后后端直接拒绝访问；也可以由生成者或管理员「立即失效」。

## 分享方式
生成后同时显示：
- QR Code（方便直接扫码）
- 完整 URL
- 「一键复制」按钮（用于不方便扫码的手机）

## 安全边界
- 仅本地/LAN 模式启用，Render/Cloud Mode 不开放。
- Guest 页面不需要登录，但 token 使用随机值，数据库只保存 SHA-256 hash。
- 后端每次请求都重新验证：token 是否存在、是否过期/撤销、请求是否来自私有/本地 IP。
- 每个 token 固定绑定一个 customer_name。
- Guest 修改 URL / file_id / workflow_number 也不能读取其他客户；订单、详情、图片路由都会再次验证归属。
- 页面没有首页、搜索、菜单、用户管理、编辑、上传等入口；只能在该客户订单列表和该客户订单详情之间浏览。
- Guest 页面不显示内部 notes，不显示电话/财务资料。
- 响应使用 no-store / noindex 等头，避免浏览器缓存和搜索引擎索引。

## 数据库 migration
新增 `local_guest_links`，由 `ensure_local_guest_link_tables()` 安全、可重复创建/升级；`init_db()` 会自动执行，不需要手工修改 production tracking.db。

## PDF 下载权限（2026-08-17 补充）
生成临时链接时新增「允许下载 PDF」开关，默认关闭。

- 关闭：Guest 只能在线查看图片 / PDF 分页预览，不能下载原始 PDF。
- 开启：Guest 客户页显示「Descargar PDF en ZIP」，可把该客户当前可见订单中的原始 PDF 附件一次打包下载。
- ZIP 下载使用同一个短时效 token；30 分钟 / 1 小时 / 4 小时到期或被「立即失效」后，下载接口同时失效。
- 后端重新验证 token、LAN、customer_name 与 `allow_pdf_download`，不能通过改 URL 下载其他客户 PDF。
- ZIP 仅包含该客户当前 Guest 订单范围内的 PDF，不包含其他客户、不包含取消流程的 workflow PDF。
- `local_guest_links.allow_pdf_download` 由重复安全 migration 自动补列，production DB 不需要手工修改。

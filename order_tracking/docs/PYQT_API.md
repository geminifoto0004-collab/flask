# PyQt 对接 API

Base URL 示例：`http://SERVER:5000/tracking`

所有下列 API 都支持两种认证：

1. 现有 PyQt 可继续使用 `requests.Session()` 对 `/tracking/login` 做 form-data 登录，后续自动携带 session cookie。
2. 新客户端可向 `/tracking/login` 发送 JSON `{username, password}`，取得 JWT，后续使用 `Authorization: Bearer <token>`。

## 推荐的批量发送流程

PyQt 已经拥有「客户名称 -> 电话」。order_tracking 只负责「客户名称 -> 当前订单 -> 客户报告」。

### 1. 一次为多个客户建立报告

`POST /tracking/api/customer-reports/by-customers`

```json
{
  "customers": ["WILLIAM TACO", "WALDO MAGI"],
  "format": "pdf",
  "language": "es",
  "image_source": "both",
  "image_count": "all",
  "image_order": "order_first",
  "pdf_attachment_mode": "pages",
  "include_completed": false
}
```

默认值就是：PDF、西班牙文、主管图+业务图、全部图片、主管图优先、只发当前未完成订单。

后端会「每个客户建立一个独立 job」，不会把不同客户混在同一个 PDF。

响应中的 `job.id` 请由 PyQt 保存。

### 2. 查询单一 job


`pdf_attachment_mode` 可选：
- `pages`（默认）：PDF 附件逐页转成图片加入报告。
- `skip`：忽略 PDF 附件。

旧版 PyQt 不传此字段时维持 `pages`，不会破坏既有调用。

`GET /tracking/api/customer-reports/jobs/<job_id>`

状态：

- `queued`：排队中
- `processing`：生成中
- `completed`：已完成
- `failed`：失败

完成后 `job.files[]` 会包含下载 `url`。

### 3. 下载报告

直接 GET `job.files[].url`，继续携带同一个 Session cookie 或 Bearer Token。

PyQt 下载 PDF 后，再依据自己电话簿里的客户电话发送即可。

---

## 精确查询一个客户的订单

`GET /tracking/api/customers/orders?name=WILLIAM%20TACO`

这是「精确客户」查询，不是模糊搜索。会自动忽略首尾空白、连续空白与英文大小写差异，避免 WILLIAM 查到另一个 WILLIAM 客户。

默认只回当前未完成订单；需要包含已完成流程时加：

`include_completed=1`

响应同时提供：

- `orders`：给 PyQt 预览
- `report_items`：若要走旧的 `/customer-reports/jobs` API，可直接使用
- 中文 / 西班牙文状态文字

不会返回 `workflows.notes` 内部便利贴内容。

## 批量查询多个客户

`POST /tracking/api/customers/orders/batch`

```json
{
  "customers": ["WILLIAM TACO", "WALDO MAGI"],
  "include_completed": false
}
```

响应会按客户分组，并额外回：

- `not_found`：找不到或当前账号无权访问的客户
- 每个客户的 `order_count`
- 每个客户自己的 `orders` / `report_items`

---

## 登录 / 连线检查

### Session（兼容现有 PyQt）

`POST /tracking/login`，form-data：`username`, `password`。

### JWT

`POST /tracking/login`，JSON：

```json
{"username":"xxx","password":"xxx"}
```

成功会返回 `token` 与 `expires_in`。

### 验证当前登录

`GET /tracking/api/auth/me`

---

## 设计约束

- 客户电话不放进 order_tracking；电话继续由 PyQt / FlaskApp 管理。
- 客户名称采用精确逻辑匹配，防止自动发送给错误客户。
- 不同客户永远建立独立报告 job / 独立文件。
- API 沿用 order_tracking 原有权限规则，PyQt 不会因为走 API 而绕过权限。
- 报告生成使用既有后台队列，PyQt 不需要等待一个客户完成后才能提交下一个。

---

## PDF 队列保护（2026-08-16）

报告 API 现在有统一的容量保护：

- 同时生成：2 个
- 全系统等待：最多 30 个
- 单一登入账号 active（queued + processing）：最多 5 个
- 完全相同的 active 报告请求不会重复建立，回应 `deduplicated: true`

当队列满时，单笔 `/api/customer-reports/jobs` 会回 HTTP 429：

- `USER_REPORT_QUEUE_LIMIT`
- `REPORT_QUEUE_FULL`

批量 `/api/customer-reports/by-customers` 会把当下无法加入的客户放进 `queue_rejected`。PyQt 后续应在已有任务完成后再补送这些客户，避免一次塞满服务器。

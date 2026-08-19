# 手机订单页 / 客户页返回栏统一

问题：
- 订单详情：返回是灰色圆形按钮并与客户名字在同一行。
- 客户详情：返回仍然是单独的红色箭头，视觉框架不一致。

修正：
- 删除两个页面原本独立的 `mobile-back-btn`。
- 订单详情和客户详情现在都使用完全相同的：
  - `mobile-profile-nav-shell`
  - `mobile-profile-nav-back`
  - `mobile-profile-nav-main`
- 左边统一灰色圆形返回按钮。
- 中间统一头像 + 客户名。
- 右边统一红色 chevron。
- 客户页保留订单数量作为第二行小字。
- 手机 History 返回逻辑不变。
- 桌面 Web 不修改。

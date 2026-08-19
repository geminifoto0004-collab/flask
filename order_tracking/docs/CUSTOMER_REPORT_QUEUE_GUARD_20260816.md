# 客户 PDF 队列保护（2026-08-16）

本版在现有 `ThreadPoolExecutor` 报告队列上增加容量与重复任务保护，供 Web、手机与 PyQt 共用。

## 当前限制

- `CUSTOMER_REPORT_WORKERS = 2`
  - 最多同时真正生成 2 个报告。
- `CUSTOMER_REPORT_MAX_QUEUED = 30`
  - 最多允许 30 个等待中的任务；processing 不计入此数，因此总 active 约为 30 + workers。
- `CUSTOMER_REPORT_MAX_ACTIVE_PER_USER = 5`
  - 单一登入账号最多同时拥有 5 个 `queued / processing` 任务。

## 重复任务

同一登入账号，如果在前一个任务仍为 `queued / processing` 时再次提交完全相同的：

- 订单集合
- 输出格式
- 报告语言
- 图片来源
- 图片数量
- 图片顺序

不会建立第二个任务，而是返回原来的 job，并在 API 回应中带：

```json
{"deduplicated": true}
```

已完成 / failed 的任务不阻止以后重新生成。

## 队列满时

单一用户达到上限：

- HTTP 429
- code: `USER_REPORT_QUEUE_LIMIT`

全系统等待队列达到上限：

- HTTP 429
- code: `REPORT_QUEUE_FULL`

## PyQt 批量接口

`POST /tracking/api/customer-reports/by-customers`

现在同样经过这套保护。若一个批次超过当下可接受数量：

- 已成功加入的放在 `jobs`
- 未加入的放在 `queue_rejected`
- 不会继续无上限塞进 ThreadPoolExecutor

后续 PyQt 应采用「完成一个，再补一个」的方式持续喂队列，而不是一次提交几十 / 上百个任务。

## 备注

当前 queue/job 状态仍是 Flask process 内存级；本地公司 Flask 单 process 使用时可避免多人同时生成造成资源爆量。若未来 Flask 改成多 worker / 多进程部署，需再升级成 SQLite/Redis 等跨进程共享队列。

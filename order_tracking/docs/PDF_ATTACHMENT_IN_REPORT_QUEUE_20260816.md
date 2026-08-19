# 客户报告队列：PDF 附件按页作为图片加入最终报告

本次修改的是既有 customer report 后台队列与报告生成器，不改桌面 / 手机 UI。

## 行为

当订单附件或业务员 workflow 附件是 PDF 时：

- `图片来源 = 主管参考图 + 业务员附件图`：两边的 PDF 都会纳入。
- `只要主管参考图`：只处理 order_files 中的图片 / PDF。
- `只要业务员附件图`：只处理 workflow_files 中的图片 / PDF。
- `不要图片`：图片和 PDF 页面都不纳入。
- `全部图片`：PDF 每一页都转成 JPEG 预览页，按原顺序放进最终报告。
- `每笔 1 张代表图`：如果被选中的代表附件是 PDF，只取 PDF 第 1 页。
- PDF 页面继续遵守原有图片排序、每行最多两张、订单分页和约 50MB 拆分逻辑。

例如业务附件 `drawing.pdf` 有 3 页，最终报告中的图片序列会出现：

- `drawing.pdf [PDF 1/3]`
- `drawing.pdf [PDF 2/3]`
- `drawing.pdf [PDF 3/3]`

原始 PDF 不修改、不覆盖；这里只是在背景 Worker 生成报告时逐页渲染。

## 依赖

运行 Flask 的 Python 环境需要 PyMuPDF：

```bash
python -m pip install PyMuPDF
```

如果检测到 PDF 附件但没有安装 PyMuPDF，该报告 Job 会明确失败并提示安装命令，不会悄悄漏掉 PDF 附件。

## 性能

- PDF 转页发生在现有后台报告 Worker 内，不阻塞手机 / Web 请求页面。
- 仍受现有全局 `CUSTOMER_REPORT_WORKERS = 2`、等待队列与单用户限制保护。
- 同一个报告 Job 内，相同 PDF 会缓存已经渲染的页，避免重复转换。
- 每个 PDF 页面转成 JPEG 后继续沿用现有 `CUSTOMER_REPORT_IMAGE_MAX_EDGE` 与 JPEG quality 压缩。

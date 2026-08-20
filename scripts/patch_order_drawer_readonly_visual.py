#!/usr/bin/env python3
"""Keep the Render drawer visually aligned with LAN while cloud writes stay disabled."""
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "order_tracking" / "static" / "js" / "WORKSPACE_drawer.js"
text = path.read_text("utf-8")
original = text

if "const isCloudReadOnly" not in text:
    anchor = "    const canEditWorkflow = () => (typeof appPerm.can === 'function' ? appPerm.can('edit', 'workflow') : false);\n"
    if anchor not in text:
        raise RuntimeError("permission helper anchor not found")
    text = text.replace(anchor, anchor + "    const isCloudReadOnly = () => document.body?.dataset.cloudReadOnly === 'true';\n", 1)

if "this.applyCloudReadonlyVisual();" not in text:
    old = """            this.renderQuickActions();\n            this.renderFooterActions();\n\n            this._syncPreviewAfterRender();\n"""
    new = """            this.renderQuickActions();\n            this.renderFooterActions();\n            this.applyCloudReadonlyVisual();\n\n            this._syncPreviewAfterRender();\n"""
    if old not in text:
        raise RuntimeError("renderAll footer anchor not found")
    text = text.replace(old, new, 1)

    old_order_only = """            if (this.state.orderOnly) {\n                this.renderAdminRef();\n                this._syncPreviewAfterRender();\n                return;\n            }\n"""
    new_order_only = """            if (this.state.orderOnly) {\n                this.renderAdminRef();\n                this.applyCloudReadonlyVisual();\n                this._syncPreviewAfterRender();\n                return;\n            }\n"""
    if old_order_only not in text:
        raise RuntimeError("orderOnly render anchor not found")
    text = text.replace(old_order_only, new_order_only, 1)

marker = "        applyCloudReadonlyVisual() {"
if marker not in text:
    anchor = """        /**\n         * 订单-only 视图布局（隐藏流程相关区域）\n         */\n        applyOrderOnlyLayout() {\n"""
    if anchor not in text:
        raise RuntimeError("applyOrderOnlyLayout anchor not found")
    method = '''        /**\n         * Render 仍使用 LAN 的完整抽屜版面；寫入控制保持唯讀。\n         * 這裡只把 LAN 原本存在的操作區顯示成 disabled，不會繞過後端唯讀保護。\n         */\n        applyCloudReadonlyVisual() {\n            if (!isCloudReadOnly()) return;\n\n            const disable = (el, show = true) => {\n                if (!el) return;\n                if (show) el.classList.remove('hidden');\n                el.disabled = true;\n                el.classList.add('is-disabled');\n                el.setAttribute('aria-disabled', 'true');\n                el.title = 'Render 云端唯读';\n            };\n\n            if (this.isAdmin()) {\n                disable(this.elements.adminRemarkEditBtn);\n                disable(this.elements.adminUploadBtn);\n                disable(this.elements.adminSelectBtn);\n                disable(this.elements.adminDeleteBtn);\n                disable(this.elements.transferBtn);\n            }\n            if (this.isSales()) {\n                disable(this.elements.salesRemarkEditBtn);\n            }\n            if (this.isAdmin() || this.isSales()) {\n                disable(this.elements.salesUploadBtn);\n                disable(this.elements.salesSelectBtn);\n                disable(this.elements.salesDeleteBtn);\n            }\n\n            if (!this.state.orderOnly && (this.isAdmin() || this.isSales())) {\n                if (this.elements.footer) this.elements.footer.style.display = '';\n                if (this.elements.quickActionsGrid) this.elements.quickActionsGrid.style.display = '';\n                if (this.elements.orderManagementGrid) this.elements.orderManagementGrid.style.display = '';\n                disable(this.elements.quickActionBtn);\n                disable(this.elements.skipBtn);\n            }\n        },\n\n'''
    text = text.replace(anchor, method + anchor, 1)

if text != original:
    path.write_text(text, "utf-8")

final = path.read_text("utf-8")
for needle in ("const isCloudReadOnly", "applyCloudReadonlyVisual()", "Render 云端唯读"):
    if needle not in final:
        raise RuntimeError(f"validation failed: {needle}")
print("ORDER drawer readonly visual compatibility applied")

# Mobile Order Detail + PDF Inline Preview

Updated: 2026-08-16

## Mobile order detail

Tapping an order opens a native mobile detail page with:
- customer + order number + current status
- compact stage timeline
- product / code / quantity / factory
- order date / delivery date / stage days / salesperson

The old `打开完整工作区 / Abrir espacio de trabajo` mobile button was removed. The desktop workspace drawer remains unchanged for desktop use.

## In-page back navigation

Mobile customer detail and order detail now push History API states. Therefore:
- browser/system back gesture from order detail returns to the customer detail or order list
- browser/system back gesture from customer detail returns to the customer list
- the first back gesture no longer jumps out of order_tracking
- the visible back buttons use the same browser-history path, so gesture and button behavior are consistent

## PDF

PDF report download supports inline preview via `?inline=1`. The UI exposes separate open/preview and download actions.

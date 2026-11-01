# SCANNER UI FOR CC

Production source branch: `xingwang-stock`; snapshot for UI redesign, not deployed.
Production URL: https://xingwang-stock.onrender.com/scanner

`SCANNER_FULL.html`: merged full current scanner page and cart controller JS for one-file reading/design.
`scanner.html`: original production HTML/CSS, keeping external `/scanner/cart.js` reference.
`scanner_cart.js`: original production cart controller code.
`CC_DESIGN_BRIEF.md`: full mobile UI requirements.

Note: back-end endpoints, TiDB, cookies, stock data and camera permission are live server features.
Opening the HTML locally will not connect to these server APIs. CC should not replace real business logic with mock behavior.
The exact screenshot issues are numeric SKU order, SCAN MORE not directly opening the camera, and native customer-name prompt.

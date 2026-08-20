#!/usr/bin/env python3
from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'services' / 'order_full_mirror_service.py'
text = path.read_text('utf-8')
original = text

old = '''    m = re.search(r'(?:VAR)?CHAR\\s*\\(\\s*(\\d+)\\s*\\)', declared)\n    if m:\n        n = max(1, int(m.group(1)))\n        if indexed:\n            # Four utf8mb4 VARCHAR(191) columns still fit a normal 3072-byte\n            # composite index. ORDER's indexed identifiers/names are below this.\n            n = min(n, 191)\n        return f'VARCHAR({min(n, 4096)})'\n\n    # SQLite TEXT is unbounded. Only indexed/PK text needs a finite MySQL type.\n    return 'VARCHAR(191)' if indexed else 'LONGTEXT'\n'''
new = '''    m = re.search(r'(?:VAR)?CHAR\\s*\\(\\s*(\\d+)\\s*\\)', declared)\n    if m:\n        n = max(1, int(m.group(1)))\n        if indexed:\n            # Indexed identifiers keep a bounded VARCHAR so TiDB can build the\n            # mirrored indexes. ORDER's indexed keys are short identifiers.\n            return f'VARCHAR({min(n, 191)})'\n\n        # SQLite treats VARCHAR(n) as TEXT affinity and DOES NOT enforce n. The\n        # live ORDER database already contains values longer than declarations\n        # such as workflows.product_code VARCHAR(50). Mirroring that declaration\n        # literally to TiDB causes error 1406 (Data too long). Non-indexed text\n        # must therefore stay unbounded on the read-only WAN mirror.\n        return 'LONGTEXT'\n\n    # SQLite TEXT is unbounded. Only indexed/PK text needs a finite MySQL type.\n    return 'VARCHAR(191)' if indexed else 'LONGTEXT'\n'''

if new not in text:
    if old not in text:
        raise RuntimeError('VARCHAR mapping anchor not found')
    text = text.replace(old, new, 1)
    path.write_text(text, 'utf-8')

py_compile.compile(str(path), doraise=True)
print('sqlite varchar mirror compatibility', 'applied' if text != original else 'already present')

#!/usr/bin/env python3
"""Mirror ORDER-owned public visitor templates into Render's startup-safe template path.

The source of truth lives under order_tracking/templates/tracking. Render keeps a
small generated mirror under the app-level templates directory because the B2 share
blueprint pre-renders HTML before the ORDER blueprint is registered. This script is
run after vendoring ORDER and before git commit/push.

Render-only speed/cache modules are deliberately not touched here.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from jinja2 import Environment


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    source_dir = repo / "order_tracking" / "templates" / "tracking"
    page_source = source_dir / "customer_share_public.html"
    macro_source = source_dir / "_guest_share_common.html"
    if not page_source.is_file() or not macro_source.is_file():
        missing = [str(p) for p in (page_source, macro_source) if not p.is_file()]
        raise SystemExit(
            "ORDER shared visitor UI is missing. Update the local order_tracking source first:\n  - "
            + "\n  - ".join(missing)
        )

    page_bytes = page_source.read_bytes()
    macro_bytes = macro_source.read_bytes()
    page_text = page_bytes.decode("utf-8")
    macro_text = macro_bytes.decode("utf-8")

    # Syntax-only guard before replacing Render's known-good page.
    env = Environment()
    env.parse(page_text)
    env.parse(macro_text)

    render_tracking = repo / "templates" / "tracking"
    render_tracking.mkdir(parents=True, exist_ok=True)
    (render_tracking / "customer_share_public.html").write_text(page_text, "utf-8")
    (render_tracking / "_guest_share_common.html").write_text(macro_text, "utf-8")

    page_sha = _digest(page_bytes)
    macro_sha = _digest(macro_bytes)
    shim = (
        "{# GENERATED FROM ORDER SHARED UI. "
        f"page={page_sha} macro={macro_sha} #}}\n"
        "{% include 'tracking/customer_share_public.html' %}\n"
    )
    (repo / "templates" / "customer_share_live_fast.html").write_text(shim, "utf-8")

    print("ORDER shared visitor UI mirrored for Render")
    print(f"  page  {page_sha}")
    print(f"  macro {macro_sha}")
    print("Render speed/cache services: unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

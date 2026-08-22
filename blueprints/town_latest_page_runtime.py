"""Exact current CUSTOMS AGENT TOWN browser snapshot.

The App Block changes quickly during visual development. To keep Render serving
that exact build without a fragile chain of HTML string replacements, the
compressed HTML payload is stored in small repository chunks and reconstructed
at request time.
"""

import base64
import gzip
from pathlib import Path


_CHUNK_DIR = Path(__file__).with_name("town_latest_chunks")
_CHUNK_COUNT = 9


def latest_town_html():
    payload = "".join(
        (_CHUNK_DIR / f"{index:02d}.txt").read_text(encoding="utf-8").strip()
        for index in range(1, _CHUNK_COUNT + 1)
    )
    return gzip.decompress(base64.b64decode(payload)).decode("utf-8")

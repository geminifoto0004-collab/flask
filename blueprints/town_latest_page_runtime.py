"""Exact current CUSTOMS AGENT TOWN browser snapshot.

The App Block changes quickly during visual development. To keep Render serving
that exact build without a fragile chain of legacy HTML patches, the compressed
HTML payload is stored in small repository chunks and reconstructed at request
time. Tiny current-version hotfixes can be applied after reconstruction.
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
    html = gzip.decompress(base64.b64decode(payload)).decode("utf-8")
    # v119: execute the returned ephemeral actions (movement/chat/dogs/etc.) even
    # when the server-authoritative world endpoint is available, then reconcile
    # persistent state from /api/town/world.
    html = html.replace(
        "      const synced=await pullTownWorld();\n      if(!synced)applyAiTownActions(data?.actions||[]);",
        "      applyAiTownActions(data?.actions||[]);\n      await pullTownWorld();",
    )
    return html

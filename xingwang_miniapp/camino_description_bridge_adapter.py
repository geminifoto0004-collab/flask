"""V33 local bridge adapter reference, NOT used by Render unless CC integrates.

Ensure original Camino.Descripcion and Glosa survive the existing local
Flask -> V33 -> Render bridge. This does not access Access by itself.
Preserves all existing original row keys for any existing caller.
"""
from __future__ import annotations
from typing import Mapping, Any

def retain_camino_description(normalized: Mapping[str, Any],
                              raw_access_row: Mapping[str, Any]) -> dict[str, Any]:
    """Return augmented (copy of) already-authorized Camino row.

    No extra SQL, HTTP or database writes. Invoke when normalizing the
    Camino result that came from the original /search data_camino / Access row.
    """
    out = dict(normalized)
    def value(*aliases: str) -> str:
        keys = {name.lower().replace("_", "") for name in aliases}
        for key, val in raw_access_row.items():
            if key.lower().replace("_", "") in keys and val is not None:
                return str(val).strip()
        return ""
    if not out.get("description"):
        out["description"] = value("Descripcion", "Description", "Observaciones")
    if not out.get("glosa"):
        out["glosa"] = value("Glosa")
    return out

if __name__ == "__main__":
    row = retain_camino_description(
        {"code": "12-225D-53", "caja": 14},
        {"Codigo": "12-225D-53", "Descripcion": "定单号：1008149 WALTER HERRERA 660克/米",
         "Glosa": "2026年9月"},
    )
    assert row["description"].startswith("定单号")
    assert row["code"] == "12-225D-53"
    print("V33 BRIDGE ADAPTER SELF TEST PASS")

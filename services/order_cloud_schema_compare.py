"""Read-only parity inspection of *schema*, never customer/order rows.

Intentionally query each configured TiDB separately, so one RU-exhausted
target can't be mistaken for the other through the normal failover connector.
"""
from __future__ import annotations

import hmac
import os

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _order_cloud_auth_source
from services.order_desktop_grant import authorized


def _authorized():
    secret = (os.environ.get("ORDER_SYNC_CHECKPOINT_KEY") or "").strip()
    received = request.headers.get("X-Order-Checkpoint-Key") or ""
    return authorized("replicas:verify-repair") or (
        len(secret) >= 24 and hmac.compare_digest(secret, received)
    )


def _read_schema(target):
    import pymysql
    from tidb_targets import pymysql_kwargs, target_settings
    dbname = target_settings(target)["database"]
    if not dbname:
        raise RuntimeError("target is not configured")
    conn = pymysql.connect(**pymysql_kwargs(target, connect_timeout=5, read_timeout=15))
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION
                   FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME""",
                (dbname,),
            )
            tables = {r[0]: list(r[1:]) for r in cur.fetchall()}
            cur.execute(
                """SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE,
                          COLUMN_DEFAULT, EXTRA, ORDINAL_POSITION
                   FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME, ORDINAL_POSITION""",
                (dbname,),
            )
            columns = {}
            for table, name, coltype, nullable, default, extra, position in cur.fetchall():
                columns.setdefault(table, {})[name] = [
                    str(coltype or ""), str(nullable or ""),
                    default if default is None else str(default),
                    str(extra or ""), int(position),
                ]
            cur.execute(
                """SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX,
                          COLUMN_NAME, SUB_PART, INDEX_TYPE
                   FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA=%s
                   ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX""",
                (dbname,),
            )
            indexes = {}
            for table, idx, nonunique, sequence, col, prefix, kind in cur.fetchall():
                indexes.setdefault(table, {}).setdefault(idx, []).append([
                    int(nonunique), int(sequence), str(col or ""),
                    prefix, str(kind or "")
                ])
        return {"tables": tables, "columns": columns, "indexes": indexes}
    finally:
        conn.close()


def _compare(a, b):
    missing_1 = sorted(set(b["tables"]) - set(a["tables"]))
    missing_2 = sorted(set(a["tables"]) - set(b["tables"]))
    table_defs = []
    columns_1, columns_2, column_defs = [], [], []
    indexes_1, indexes_2, index_defs = [], [], []
    for table in sorted(set(a["tables"]) & set(b["tables"])):
        if a["tables"][table] != b["tables"][table]:
            table_defs.append(table)
        c1 = a["columns"].get(table, {})
        c2 = b["columns"].get(table, {})
        columns_1 += [f"{table}.{name}" for name in sorted(set(c2) - set(c1))]
        columns_2 += [f"{table}.{name}" for name in sorted(set(c1) - set(c2))]
        column_defs += [f"{table}.{name}" for name in sorted(set(c1) & set(c2))
                        if c1[name] != c2[name]]
        i1 = a["indexes"].get(table, {})
        i2 = b["indexes"].get(table, {})
        indexes_1 += [f"{table}.{name}" for name in sorted(set(i2) - set(i1))]
        indexes_2 += [f"{table}.{name}" for name in sorted(set(i1) - set(i2))]
        index_defs += [f"{table}.{name}" for name in sorted(set(i1) & set(i2))
                       if i1[name] != i2[name]]
    differences = {
        "missing_tables_in_tidb1": missing_1,
        "missing_tables_in_tidb2": missing_2,
        "table_definition_mismatches": table_defs,
        "missing_columns_in_tidb1": columns_1,
        "missing_columns_in_tidb2": columns_2,
        "column_definition_mismatches": column_defs,
        "missing_indexes_in_tidb1": indexes_1,
        "missing_indexes_in_tidb2": indexes_2,
        "index_definition_mismatches": index_defs,
    }
    return {"same_schema": not any(differences.values()), "differences": differences,
            "table_counts": {"TIDB1": len(a["tables"]), "TIDB2": len(b["tables"])}}


@b2_test_bp.route("/api/order-cloud/diagnostics/schema-compare", methods=["GET"])
def order_cloud_schema_compare():
    _, error = _order_cloud_auth_source()
    if error:
        return error
    if not _authorized():
        return jsonify({"ok": False, "error": "checkpoint authorization required"}), 401
    outputs = {}
    errors = {}
    for target in ("TIDB1", "TIDB2"):
        try:
            outputs[target] = _read_schema(target)
        except Exception as exc:
            errors[target] = type(exc).__name__  # no connection strings or passwords
    if errors:
        return jsonify({"ok": False, "schema_verified": False, "target_errors": errors,
                        "reachable_targets": list(outputs)}), 503
    return jsonify({"ok": True, "schema_verified": True, "result": _compare(outputs["TIDB1"], outputs["TIDB2"])})

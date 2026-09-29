"""TiDB1/TiDB2 target selection shared by Flask cloud metadata and ORDER mirror.

Goals:
- TIDB1 keeps backward compatibility with the existing DATABASE_URL / DB_* / MYSQL_* vars.
- TIDB2 uses its own TIDB2_* (or TIDB2_URL) credentials.
- DB_TARGET selects the preferred database; AUTO tries TIDB1 then TIDB2.
- Mirroring is best-effort: a broken standby never blocks the selected database.
"""
from __future__ import annotations

import os
import urllib.parse

_TARGETS = ("TIDB1", "TIDB2")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return bool(default)
    return str(raw).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def selected_target() -> str:
    value = str(os.environ.get("DB_TARGET") or "TIDB1").strip().upper()
    if value not in {"TIDB1", "TIDB2", "AUTO"}:
        raise ValueError("DB_TARGET must be TIDB1, TIDB2 or AUTO")
    return value


def preferred_target() -> str:
    value = selected_target()
    if value == "TIDB2":
        return "TIDB2"
    return "TIDB1"


def other_target(target: str) -> str:
    target = str(target or "").strip().upper()
    if target not in _TARGETS:
        raise ValueError("target must be TIDB1 or TIDB2")
    return "TIDB2" if target == "TIDB1" else "TIDB1"


def failover_enabled() -> bool:
    return _env_bool("TIDB_FAILOVER_ENABLED", True)


def mirror_enabled() -> bool:
    default = bool(
        (os.environ.get("TIDB2_URL") or "").strip()
        or (
            (os.environ.get("TIDB2_HOST") or "").strip()
            and (os.environ.get("TIDB2_USER") or "").strip()
        )
    )
    return _env_bool("TIDB_MIRROR_ENABLED", default)


def _target_url(target: str) -> str:
    target = str(target or "").strip().upper()
    if target == "TIDB1":
        return (os.environ.get("TIDB1_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if target == "TIDB2":
        return (os.environ.get("TIDB2_URL") or "").strip()
    raise ValueError("target must be TIDB1 or TIDB2")


def target_settings(target: str, *, database_override=None, require_database=True) -> dict:
    target = str(target or "").strip().upper()
    if target not in _TARGETS:
        raise ValueError("target must be TIDB1 or TIDB2")

    url = _target_url(target)
    parsed = urllib.parse.urlparse(url) if url else None

    if target == "TIDB1":
        host = (
            (parsed.hostname if parsed else None)
            or os.environ.get("TIDB1_HOST")
            or os.environ.get("MYSQL_HOST")
            or os.environ.get("DB_HOST")
            or ""
        )
        port = (
            (parsed.port if parsed else None)
            or os.environ.get("TIDB1_PORT")
            or os.environ.get("MYSQL_PORT")
            or os.environ.get("DB_PORT")
            or 4000
        )
        user = (
            (parsed.username if parsed else None)
            or os.environ.get("TIDB1_USER")
            or os.environ.get("MYSQL_USER")
            or os.environ.get("DB_USER")
            or ""
        )
        password = (
            (parsed.password if parsed else None)
            or os.environ.get("TIDB1_PASSWORD")
            or os.environ.get("MYSQL_PASSWORD")
            or os.environ.get("DB_PASSWORD")
            or ""
        )
        database = (
            database_override
            if database_override is not None
            else ((parsed.path.lstrip("/") if parsed and parsed.path else None)
                  or os.environ.get("TIDB1_NAME")
                  or os.environ.get("MYSQL_DATABASE")
                  or os.environ.get("DB_NAME")
                  or "")
        )
    else:
        host = (parsed.hostname if parsed else None) or os.environ.get("TIDB2_HOST") or ""
        port = (parsed.port if parsed else None) or os.environ.get("TIDB2_PORT") or 4000
        user = (parsed.username if parsed else None) or os.environ.get("TIDB2_USER") or ""
        password = (parsed.password if parsed else None) or os.environ.get("TIDB2_PASSWORD") or ""
        database = (
            database_override
            if database_override is not None
            else ((parsed.path.lstrip("/") if parsed and parsed.path else None)
                  or os.environ.get("TIDB2_NAME")
                  or "")
        )

    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 4000

    result = {
        "target": target,
        "host": str(host or "").strip(),
        "port": port,
        "user": str(user or "").strip(),
        "password": str(password or ""),
        "database": str(database or "").strip(),
        "url": url,
    }
    result["configured"] = bool(
        result["host"] and result["user"] and (result["database"] or not require_database)
    )
    return result


def target_configured(target: str, *, require_database=True) -> bool:
    return bool(target_settings(target, require_database=require_database).get("configured"))


def target_candidates(preferred=None, *, allow_failover=None) -> list[str]:
    selected = selected_target()
    first = str(preferred or ("TIDB2" if selected == "TIDB2" else "TIDB1")).strip().upper()
    if first not in _TARGETS:
        first = "TIDB1"
    if allow_failover is None:
        allow_failover = failover_enabled() or selected == "AUTO"
    result = [first]
    second = other_target(first)
    if allow_failover and second not in result and target_configured(second):
        result.append(second)
    return result


def pymysql_kwargs(target: str, *, database_override=None, require_database=True,
                    connect_timeout=10, read_timeout=10, write_timeout=10) -> dict:
    cfg = target_settings(
        target,
        database_override=database_override,
        require_database=require_database,
    )
    if not cfg["configured"]:
        missing = []
        if not cfg["host"]:
            missing.append("host")
        if not cfg["user"]:
            missing.append("user")
        if require_database and not cfg["database"]:
            missing.append("database")
        raise RuntimeError(f"{cfg['target']} is not configured: missing {', '.join(missing)}")

    result = {
        "host": cfg["host"],
        "port": cfg["port"],
        "user": cfg["user"],
        "password": cfg["password"],
        "charset": "utf8mb4",
        "autocommit": False,
        "connect_timeout": int(connect_timeout),
        "read_timeout": int(read_timeout),
        "write_timeout": int(write_timeout),
    }
    if require_database or cfg["database"]:
        result["database"] = cfg["database"]
    if "tidbcloud.com" in cfg["host"].lower():
        result["ssl"] = {"check_hostname": False}
    return result

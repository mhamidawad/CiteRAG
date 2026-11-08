"""Single-workspace boundary and durable admission budgets, without storing credentials.

One process deployment owns one index and workspace. Separate tenants MUST use separate
deployments and data volumes. Budgets are admission attempts, not billing measurements.
"""
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qs


class PolicyConfigurationError(ValueError):
    pass


def configuration():
    production = os.getenv("CITERAG_PRODUCTION") == "1"
    workspace = os.getenv("CITERAG_WORKSPACE_ID", "")
    if workspace and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", workspace):
        raise PolicyConfigurationError("Invalid workspace ID")
    limits = {}
    for name in ("CITERAG_RATE_LIMIT_PER_MINUTE", "CITERAG_GENERATION_LIMIT_PER_DAY"):
        raw = os.getenv(name, "")
        if raw:
            if not raw.isdecimal() or not 1 <= int(raw) <= 1000000:
                raise PolicyConfigurationError("Invalid admission budget")
            limits[name] = int(raw)
    database = os.getenv("CITERAG_POLICY_DB", "")
    if limits and (not database or not Path(database).is_absolute()):
        raise PolicyConfigurationError("Budgets require an absolute persistent policy database")
    if production and (not workspace or len(limits) != 2 or not database):
        raise PolicyConfigurationError("Production requires workspace and explicit persistent budgets")
    return workspace, limits, database


def check_workspace(scope, workspace, data=None):
    """Reject a requested alternate workspace; absence means this deployment's workspace."""
    if not workspace:
        return True
    values = [v.decode("utf-8", "replace") for k, v in scope.get("headers", [])
              if k.lower() == b"x-citerag-workspace"]
    query = parse_qs(scope.get("query_string", b"").decode("utf-8", "replace"),
                     keep_blank_values=True)
    for key in ("workspace", "workspace_id"):
        values += query.get(key, [])
    if isinstance(data, dict):
        candidates = [data]
        params = data.get("params")
        if isinstance(params, dict) and isinstance(params.get("arguments"), dict):
            candidates.append(params["arguments"])
        for candidate in candidates:
            for key in ("workspace", "workspace_id"):
                if key in candidate:
                    values.append(candidate[key])
    return len(values) == 0 or all(isinstance(v, str) and v == workspace for v in values)


def admit(database, workspace, limits, generating=False, now=None):
    """Atomic cross-process budgets. Charge generation admissions, never polling/retrieval."""
    if not limits:
        return True
    now = int(time.time() if now is None else now)
    buckets = []
    if "CITERAG_RATE_LIMIT_PER_MINUTE" in limits:
        buckets.append(("minute", now // 60, limits["CITERAG_RATE_LIMIT_PER_MINUTE"]))
    if generating and "CITERAG_GENERATION_LIMIT_PER_DAY" in limits:
        buckets.append(("generation_day", now // 86400, limits["CITERAG_GENERATION_LIMIT_PER_DAY"]))
    con = sqlite3.connect(database, timeout=3)
    try:
        con.execute("PRAGMA busy_timeout=3000")
        con.execute("BEGIN IMMEDIATE")
        con.execute("CREATE TABLE IF NOT EXISTS admission (workspace TEXT, kind TEXT, bucket INTEGER, used INTEGER NOT NULL, PRIMARY KEY(workspace,kind,bucket))")
        for kind, bucket, limit in buckets:
            row = con.execute("SELECT used FROM admission WHERE workspace=? AND kind=? AND bucket=?",
                              (workspace, kind, bucket)).fetchone()
            if row and row[0] >= limit:
                con.rollback()
                return False
        for kind, bucket, _ in buckets:
            con.execute("INSERT INTO admission VALUES(?,?,?,1) ON CONFLICT(workspace,kind,bucket) DO UPDATE SET used=used+1",
                        (workspace, kind, bucket))
        con.execute("DELETE FROM admission WHERE (kind='minute' AND bucket<?) OR (kind='generation_day' AND bucket<?)",
                    (now // 60 - 2, now // 86400 - 2))
        con.commit()
        return True
    finally:
        con.close()


async def enforce(scope, receive):
    """Return (status, receive) before any application side effect."""
    workspace, limits, database = configuration()
    if not check_workspace(scope, workspace):
        return 403, receive
    path = scope.get("path", "")
    active = scope.get("method") == "POST" and path in {"/api/ask", "/api/reindex", "/mcp", "/mcp/"}
    if not active or not (workspace or limits):
        return None, receive
    chunks = []
    size = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return 400, receive
        size += len(message.get("body", b""))
        if size > 65536:
            return 413, receive
        chunks.append(message)
        if not message.get("more_body", False):
            break
    raw = b"".join(message.get("body", b"") for message in chunks)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        data = None
    if not check_workspace(scope, workspace, data):
        return 403, receive
    generating = False
    charge = path in {"/api/ask", "/api/reindex"}
    if path == "/api/ask" and isinstance(data, dict):
        adapter = data.get("adapter")
        generating = (isinstance(adapter, str) and adapter in {"opencode", "omniroute"}) or (
            adapter is None and data.get("retrieval_only") is not True)
    elif path in {"/mcp", "/mcp/"} and isinstance(data, dict):
        # MCP initialization and notifications do not consume search budget.
        charge = data.get("method") == "tools/call"
    if charge and not admit(database, workspace, limits, generating):
        return 429, receive
    iterator = iter(chunks)
    async def replay():
        try:
            return next(iterator)
        except StopIteration:
            return await receive()
    return None, replay

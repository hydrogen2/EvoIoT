"""File-source watcher: catalogs files from source_type='file' data sources.

A Restate virtual object keyed by data_sources.id. `start` kicks off a
durable self-scheduling loop: scan → delayed self-send → scan ... The loop
survives crashes/restarts because the pending delayed send lives in Restate,
not in this process.

The catalog records only what is invariant for any file: bytes at a path.
A changed file becomes a NEW immutable version row (is_current flips);
interpretation of contents is extraction's job, not the watcher's.
"""

import hashlib
import os
import shutil
from datetime import timedelta

import psycopg2
from restate import VirtualObject, ObjectContext

from shared.config import POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

FILE_STORE = os.environ.get("FILE_STORE", "/data/file_store")
DEFAULT_SCAN_INTERVAL_S = 60

file_watcher = VirtualObject("file_watcher")


def _connect():
    conn = psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT, database=POSTGRES_DB,
        user=POSTGRES_USER, password=POSTGRES_PASSWORD,
    )
    conn.autocommit = True
    return conn


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_source(source_id: str) -> dict:
    """One catalog pass over a file source. Returns scan stats + next interval."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT tenant_id, config, enabled FROM evoiot.data_sources
                   WHERE id = %s AND source_type = 'file'""",
                (source_id,),
            )
            row = cur.fetchone()
        if row is None:
            return {"status": "unknown_source", "stop": True}
        tenant_id, config, enabled = row[0], row[1] or {}, row[2]
        interval = int(config.get("scan_interval_s", DEFAULT_SCAN_INTERVAL_S))
        if not enabled:
            # keep the loop alive but idle — re-enabling needs no restart
            return {"status": "disabled", "interval": interval,
                    "seen": 0, "new": 0}

        root = config.get("path")
        if not root or not os.path.isdir(root):
            return {"status": "path_missing", "path": root, "interval": interval,
                    "seen": 0, "new": 0}

        seen = new = 0
        with conn.cursor() as cur:
            for dirpath, _dirnames, filenames in os.walk(root):
                for name in filenames:
                    full = os.path.join(dirpath, name)
                    relpath = os.path.relpath(full, root)
                    try:
                        digest = _sha256(full)
                        stat = os.stat(full)
                    except OSError:
                        continue  # vanished/unreadable mid-scan — next pass gets it
                    seen += 1

                    cur.execute(
                        """UPDATE evoiot.files SET last_seen = NOW()
                           WHERE source_id = %s AND relpath = %s AND sha256 = %s
                           RETURNING id""",
                        (source_id, relpath, digest),
                    )
                    if cur.fetchone() is not None:
                        continue  # known version

                    # new version: snapshot bytes first, then catalog
                    os.makedirs(FILE_STORE, exist_ok=True)
                    snapshot = os.path.join(FILE_STORE, digest)
                    if not os.path.exists(snapshot):
                        shutil.copyfile(full, snapshot)

                    cur.execute(
                        """UPDATE evoiot.files SET is_current = FALSE
                           WHERE source_id = %s AND relpath = %s AND is_current""",
                        (source_id, relpath),
                    )
                    cur.execute(
                        """INSERT INTO evoiot.files
                               (source_id, tenant_id, relpath, sha256,
                                size_bytes, file_mtime)
                           VALUES (%s, %s, %s, %s, %s, to_timestamp(%s))""",
                        (source_id, tenant_id, relpath, digest,
                         stat.st_size, stat.st_mtime),
                    )
                    new += 1

        return {"status": "ok", "interval": interval, "seen": seen, "new": new}
    finally:
        conn.close()


@file_watcher.handler()
async def start(ctx: ObjectContext, req: dict) -> dict:
    """Begin the watch loop for this source (idempotent)."""
    if await ctx.get("active"):
        return {"status": "already_running", "source_id": ctx.key()}
    ctx.set("active", True)
    ctx.object_send(scan, key=ctx.key(), arg={}, send_delay=timedelta(seconds=1))
    return {"status": "started", "source_id": ctx.key()}


@file_watcher.handler()
async def stop(ctx: ObjectContext, req: dict) -> dict:
    """Stop the watch loop (takes effect at the next tick)."""
    ctx.set("active", False)
    return {"status": "stopping", "source_id": ctx.key()}


@file_watcher.handler()
async def scan(ctx: ObjectContext, req: dict) -> dict:
    """One tick: catalog pass, then durably schedule the next tick.

    Invoke with {"oneshot": true} for a manual scan that neither requires
    the loop to be active nor schedules a next tick (which would fork a
    second timer chain).
    """
    oneshot = bool(req and req.get("oneshot"))
    if not oneshot and not await ctx.get("active"):
        return {"status": "stopped"}

    result = await ctx.run("scan", lambda: scan_source(ctx.key()))

    if result.get("stop"):
        ctx.set("active", False)
        return result

    if result.get("new", 0) > 0:
        print(f"[watcher] {ctx.key()}: cataloged {result['new']} new file version(s)",
              flush=True)

    if not oneshot:
        interval = int(result.get("interval", DEFAULT_SCAN_INTERVAL_S))
        ctx.object_send(scan, key=ctx.key(), arg={}, send_delay=timedelta(seconds=interval))
    return result


@file_watcher.handler()
async def status(ctx: ObjectContext, req: dict) -> dict:
    """Whether the loop is active for this source."""
    return {"source_id": ctx.key(), "active": bool(await ctx.get("active"))}

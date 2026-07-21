"""File extraction workflow: catalog row → point claims → RawTags.

Keyed by evoiot.files.id (one extraction per immutable file version).
The LLM interprets the file's schema (summary + column mapping spec);
code applies the spec mechanically to every row. Claims land as RawTags
with origin='file' and per-row provenance fragments — wire discovery
later corroborates them (origin upgrades to 'wire').
"""

import json
import os

import psycopg2
from restate import Workflow, WorkflowContext

from shared import tabular
from shared.config import POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
from shared.llm import summarize_file, propose_table_mapping
from shared.traced import traced_run

FILE_STORE = os.environ.get("FILE_STORE", "/data/file_store")
SOURCE_LABEL = "bms-export"   # rawtag source segment for file-derived claims

file_extraction_workflow = Workflow("file_extraction")


def _connect():
    conn = psycopg2.connect(host=POSTGRES_HOST, port=POSTGRES_PORT,
                            database=POSTGRES_DB, user=POSTGRES_USER,
                            password=POSTGRES_PASSWORD)
    conn.autocommit = True
    return conn


def _fetch_file(file_id: str) -> dict:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT tenant_id, relpath, sha256, status FROM evoiot.files
                   WHERE id = %s""", (file_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"unknown file id {file_id}")
    tenant_id, relpath, sha256, status = row
    snapshot = os.path.join(FILE_STORE, sha256)
    if not os.path.exists(snapshot):
        raise ValueError(f"snapshot missing for {relpath} ({sha256[:12]})")
    # folder position is evidence: first path segment hints the building
    building = relpath.split("/")[0] if "/" in relpath else None
    return {"tenant_id": tenant_id, "relpath": relpath, "sha256": sha256,
            "status": status, "snapshot": snapshot, "building": building}


def _summarize(file: dict) -> str:
    sheets = tabular.render_xlsx(file["snapshot"])
    summary = summarize_file(os.path.basename(file["relpath"]),
                             tabular.sample_text(sheets))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE evoiot.files SET summary = %s,
                       status = CASE WHEN status = 'cataloged' THEN 'summarized' ELSE status END
                   WHERE sha256 = %s""",
                (summary, file["sha256"]))
    finally:
        conn.close()
    return summary


def _propose_mapping(file: dict) -> dict:
    """LLM proposes the spec; validation happens HERE so a bad spec makes
    this step fail and retry (a fresh LLM call), not the apply step."""
    sheets = tabular.render_xlsx(file["snapshot"])
    spec = propose_table_mapping(os.path.basename(file["relpath"]),
                                 tabular.sample_text(sheets))
    tabular.apply_mapping(sheets, spec)  # validates roles/columns; raises if bad
    return spec


def _extract(file: dict, spec: dict) -> dict:
    sheets = tabular.render_xlsx(file["snapshot"])
    result = tabular.apply_mapping(sheets, spec)
    claims = result["claims"]
    evidence_base = f"file:{file['sha256'][:12]}#{result['sheet']}"

    conn = _connect()
    try:
        with conn.cursor() as cur:
            devices = {}
            for c in claims:
                devices[c["device_id"]] = c["device_name"]
            for device_id, device_name in devices.items():
                cur.execute(
                    "SELECT evoiot.upsert_rawtag(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (file["tenant_id"], SOURCE_LABEL, device_id, None, None,
                     "bacnet", "device", json.dumps({"name": device_name}, ensure_ascii=False),
                     None, f"file:{file['sha256'][:12]}",
                     "file", evidence_base, file["building"]))
            for c in claims:
                raw_data = {k: v for k, v in {
                    "object_name": c["object_name"], "unit": c["unit"],
                    "value_sample": c["value_sample"], "writable": c["writable"],
                    "path": c["path"],
                }.items() if v is not None}
                cur.execute(
                    "SELECT evoiot.upsert_rawtag(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (file["tenant_id"], SOURCE_LABEL, c["device_id"],
                     c["object_type"], c["object_instance"], "bacnet", "object",
                     json.dumps(raw_data, ensure_ascii=False), None, f"file:{file['sha256'][:12]}",
                     "file", f"{evidence_base}!r{c['row']}", file["building"]))
            cur.execute("UPDATE evoiot.files SET status = 'extracted' WHERE sha256 = %s",
                        (file["sha256"],))
    finally:
        conn.close()

    return {"devices": len(devices), "points": len(claims),
            "skipped": result["skipped"]}


@file_extraction_workflow.main()
async def run(ctx: WorkflowContext, req: dict) -> dict:
    file_id = ctx.key()

    file = await traced_run(ctx, "fetch_file", lambda: _fetch_file(file_id),
                            data_id=file_id)

    summary = await traced_run(ctx, "summarize", lambda: _summarize(file),
                               data_id=file_id)

    mapping = await traced_run(ctx, "propose_mapping", lambda: _propose_mapping(file),
                               data_id=file_id)

    stats = await traced_run(ctx, "extract", lambda: _extract(file, mapping),
                             data_id=file_id)

    return {"status": "completed", "file": file["relpath"],
            "summary": summary, **stats}

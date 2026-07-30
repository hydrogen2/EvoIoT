#!/usr/bin/env python3
"""Building chat — the minimal chat-root, seeded with the building.

A single-file service (runs on the docker host): each turn it snapshots the
building's current live state from the graph + readings, injects it into
Claude, and answers. No artifacts spawned yet — just a chat that can answer
questions about current conditions, grounded in real data.

    RP_CHAT_MODEL=claude-sonnet python3 server.py   # default port 8899
"""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg2

import agent as agent_mod
import appdev
import functions

PORT = int(os.environ.get("RP_CHAT_PORT", "8899"))
MODEL = os.environ.get("RP_CHAT_MODEL", "sonnet")
TENANT = os.environ.get("RP_CHAT_TENANT", "HDB")
BUILDING = os.environ.get("RP_CHAT_BUILDING", "RP")
DSN = os.environ.get("RP_CHAT_DSN", "host=postgres port=5432 dbname=postgres user=postgres password=postgres")
# LLM via the claude-shim (the shared host LLM gateway), same as the workflows
# service — a container can't run the claude CLI directly.
LLM_API_BASE = os.environ.get("LLM_API_BASE", "http://host.docker.internal:8787/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
STATIC_DIR = Path(__file__).parent / "static"

functions.init(DSN)
STORE = appdev.ViewStore(DSN, TENANT)
AGENT = agent_mod.Agent(LLM_API_BASE, LLM_API_KEY, MODEL, STORE, TENANT, BUILDING,
                        lambda: appdev.building_context(TENANT, BUILDING))


def _conn():
    c = psycopg2.connect(DSN)
    c.autocommit = True
    return c


def snapshot():
    """Current live state: every point with a reading in the last 2h, its
    equipment, name, latest value + unit + age. This is what the chat 'sees'."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = ag_catalog, evoiot, public")
            cur.execute(f"""
                SELECT rid, nm, otype, eq FROM (SELECT * FROM cypher('platform', $$
                    MATCH (r:RawTag {{tenant_id:'{TENANT}', building:'{BUILDING}', tag_type:'object'}})
                    OPTIONAL MATCH (r)-[:BELONGS_TO]->(e:Equipment)
                    RETURN r.id, r.object_name, r.object_type, e.name
                $$) AS (rid agtype, nm agtype, otype agtype, eq agtype)) s
            """)
            meta = {}
            for rid, nm, otype, eq in cur.fetchall():
                meta[str(rid).strip('"')] = (
                    str(nm).strip('"') if nm and str(nm) != "null" else "",
                    str(eq).strip('"') if eq and str(eq) != "null" else "(unassigned)",
                    str(otype).strip('"') if otype else "",
                )
            cur.execute(f"""
                SELECT DISTINCT ON (rawtag_id) rawtag_id, value, unit, observed_at
                FROM evoiot.readings
                WHERE tenant_id = '{TENANT}' AND observed_at > now() - interval '2 hours'
                ORDER BY rawtag_id, observed_at DESC
            """)
            rows = []
            for rid, val, unit, ts in cur.fetchall():
                nm, eq, otype = meta.get(rid, ("", "(unassigned)", ""))
                if not nm:
                    continue
                rows.append({"equipment": eq, "point": nm, "value": val,
                             "unit": unit or "", "type": otype})
    finally:
        conn.close()
    return rows


def equipment_summary():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = ag_catalog, evoiot, public")
            cur.execute(f"""
                SELECT dtype, n FROM (SELECT * FROM cypher('platform', $$
                    MATCH (e:Equipment {{tenant_id:'{TENANT}', building:'{BUILDING}'}})-[:IS_TYPE_OF]->(d:DeviceType)
                    RETURN d.label, count(e)
                $$) AS (dtype agtype, n agtype)) s
            """)
            return [(str(d).strip('"'), int(str(n))) for d, n in cur.fetchall()]
    finally:
        conn.close()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass

    def _static(self, fname, ctype):
        f = (STATIC_DIR / fname).resolve()
        if not f.is_file() or STATIC_DIR.resolve() not in f.parents:
            return self._send(404, "{}")
        self._send(200, f.read_bytes(), ctype)

    def do_GET(self):
        if self.path == "/":
            self._static("app.html", "text/html; charset=utf-8")
        elif self.path == "/views":  # legacy apps page — unified into /
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/building":
            eq = equipment_summary()
            live = len(snapshot())
            self._send(200, json.dumps({"building": BUILDING, "equipment": eq, "live_points": live}))
        elif self.path.startswith("/view/"):
            self._static("view.html", "text/html; charset=utf-8")
        elif self.path.startswith("/static/"):
            ctype = ("application/javascript" if self.path.endswith(".js")
                     else "text/html; charset=utf-8")
            self._static(self.path[len("/static/"):], ctype)
        elif self.path == "/api/views":
            self._send(200, json.dumps({"views": STORE.list_views()}))
        elif self.path == "/api/components":
            self._send(200, json.dumps({"components": STORE.list_components()}))
        elif self.path.startswith("/api/component/"):
            comp = STORE.get_component(self.path[len("/api/component/"):])
            if comp is None:
                return self._send(404, json.dumps({"error": "no such component"}))
            self._send(200, json.dumps(comp))
        elif self.path.startswith("/api/view/"):
            spec = STORE.get_view(self.path[len("/api/view/"):])
            if spec is None:
                return self._send(404, json.dumps({"error": "no such view"}))
            self._send(200, json.dumps(spec))
        else:
            self._send(404, "{}")

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n)) if n else {}
            if self.path == "/chat":
                t0 = time.time()
                out = AGENT.run(req.get("message", ""), req.get("history"),
                                current_view=req.get("view"))
                self._send(200, json.dumps({
                    "answer": out["answer"], "tools": out["tools"],
                    "published": out["published"],
                    "elapsed": round(time.time() - t0, 1)}))
            elif self.path == "/api/data":
                result = functions.call(req.get("fn", ""), req.get("args") or {},
                                        TENANT, req.get("building") or BUILDING)
                self._send(200, json.dumps(result, default=str))
            elif self.path == "/api/action":
                result = functions.call_action(req.get("fn", ""), req.get("args") or {},
                                               TENANT, req.get("building") or BUILDING)
                self._send(200, json.dumps(result, default=str))
            elif self.path == "/api/appdev":
                try:
                    result = AGENT.build_view(req.get("request", ""))
                    self._send(200, json.dumps(result))
                except ValueError as e:
                    self._send(422, json.dumps({
                        "error": str(e),
                        "validation_errors": getattr(e, "validation_errors", [])}))
            else:
                self._send(404, "{}")
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)[:500]}))




if __name__ == "__main__":
    print(f"[chat] building={BUILDING} model={MODEL} on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()

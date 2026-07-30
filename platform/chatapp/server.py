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
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg2

import appdev as appdev_mod
import functions
import viewspec

PORT = int(os.environ.get("RP_CHAT_PORT", "8899"))
MODEL = os.environ.get("RP_CHAT_MODEL", "sonnet")
TENANT = os.environ.get("RP_CHAT_TENANT", "HDB")
BUILDING = os.environ.get("RP_CHAT_BUILDING", "RP")
DSN = os.environ.get("RP_CHAT_DSN", "host=postgres port=5432 dbname=postgres user=postgres password=postgres")
# LLM via the claude-shim (the shared host LLM gateway), same as the workflows
# service — a container can't run the claude CLI directly.
LLM_API_BASE = os.environ.get("LLM_API_BASE", "http://host.docker.internal:8787/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
APPDEV_MODEL = os.environ.get("APPDEV_MODEL", MODEL)

STATIC_DIR = Path(__file__).parent / "static"

functions.init(DSN)
APPDEV = appdev_mod.AppDev(LLM_API_BASE, LLM_API_KEY, APPDEV_MODEL,
                           DSN, TENANT, BUILDING)


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


def render_snapshot(rows):
    by_eq = {}
    for r in rows:
        by_eq.setdefault(r["equipment"], []).append(r)
    lines = []
    for eq in sorted(by_eq):
        lines.append(f"## {eq}")
        for r in sorted(by_eq[eq], key=lambda x: x["point"]):
            v = r["value"]
            v = round(v, 2) if isinstance(v, float) else v
            lines.append(f"  {r['point']} = {v} {r['unit']}".rstrip())
    return "\n".join(lines)


SYSTEM = """You are the live assistant for the {building} building — a chiller plant plus fan-coil units, monitored in real time via BACnet.

Below is a snapshot of EVERY monitored point's current value (grouped by equipment). Point names follow BAS conventions: temp_chws = chilled-water supply temp, temp_chwr = chilled-water return, temp_cws/cwr = condenser-water supply/return, kw = power, kwh = energy, status/trip = on/alarm, etc. Values are the latest reading (within the last 2 hours).

Answer the user's question using ONLY this snapshot. Be concise and concrete — give numbers and units, group sensibly, and name the equipment. If something isn't in the snapshot, say so plainly. Don't invent points or values.

=== LIVE BUILDING SNAPSHOT ===
{snapshot}
=== END SNAPSHOT ==="""


def ask(question, history):
    rows = snapshot()
    messages = [{"role": "system",
                 "content": SYSTEM.format(building=BUILDING, snapshot=render_snapshot(rows))}]
    for turn in (history or [])[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})

    body = json.dumps({"model": MODEL, "messages": messages}).encode()
    req = urllib.request.Request(
        f"{LLM_API_BASE}/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {LLM_API_KEY}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.load(r)
    return resp["choices"][0]["message"]["content"], len(rows)


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
            self._send(200, HTML, "text/html; charset=utf-8")
        elif self.path == "/building":
            eq = equipment_summary()
            live = len(snapshot())
            self._send(200, json.dumps({"building": BUILDING, "equipment": eq, "live_points": live}))
        elif self.path == "/views":
            self._static("views.html", "text/html; charset=utf-8")
        elif self.path.startswith("/view/"):
            self._static("view.html", "text/html; charset=utf-8")
        elif self.path.startswith("/static/"):
            ctype = ("application/javascript" if self.path.endswith(".js")
                     else "text/html; charset=utf-8")
            self._static(self.path[len("/static/"):], ctype)
        elif self.path == "/api/views":
            self._send(200, json.dumps({"views": APPDEV.list_views()}))
        elif self.path.startswith("/api/view/"):
            spec = APPDEV.get_view(self.path[len("/api/view/"):])
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
                answer, npts = ask(req.get("message", ""), req.get("history"))
                self._send(200, json.dumps({"answer": answer, "points_seen": npts,
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
                    result = APPDEV.generate(req.get("request", ""))
                    self._send(200, json.dumps(result))
                except ValueError as e:
                    self._send(422, json.dumps({
                        "error": str(e),
                        "validation_errors": getattr(e, "validation_errors", [])}))
            else:
                self._send(404, "{}")
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)[:500]}))


HTML = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>RP Building — Chat</title>
<style>
:root{--bg:#0f1216;--panel:#171b21;--edge:#252b34;--tx:#e6e9ef;--dim:#8b95a3;--acc:#4a9eff;--user:#1f6feb22}
*{box-sizing:border-box}body{margin:0;font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--tx);height:100vh;display:flex;flex-direction:column}
header{padding:14px 20px;border-bottom:1px solid var(--edge);background:var(--panel)}
header h1{margin:0;font-size:15px;font-weight:600}header .sub{color:var(--dim);font-size:13px;margin-top:2px}
#log{flex:1;overflow-y:auto;padding:22px 16px;display:flex;flex-direction:column;gap:16px;max-width:820px;width:100%;margin:0 auto}
.msg{display:flex;gap:11px;align-items:flex-start}.msg .who{width:26px;height:26px;border-radius:6px;flex:none;display:grid;place-items:center;font-size:12px;font-weight:700}
.user .who{background:#1f6feb;color:#fff}.bot .who{background:#2b333d;color:var(--acc)}
.msg .body{padding-top:2px;white-space:pre-wrap}.user .body{color:var(--tx)}.bot .body{color:var(--tx)}
.meta{color:var(--dim);font-size:12px;margin-top:5px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
.chip{border:1px solid var(--edge);background:var(--panel);color:var(--dim);padding:5px 10px;border-radius:14px;font-size:13px;cursor:pointer}
.chip:hover{border-color:var(--acc);color:var(--tx)}
footer{border-top:1px solid var(--edge);background:var(--panel);padding:12px 16px}
.inwrap{max-width:820px;margin:0 auto;display:flex;gap:9px}
textarea{flex:1;resize:none;background:var(--bg);border:1px solid var(--edge);color:var(--tx);border-radius:9px;padding:11px 13px;font:inherit;max-height:140px}
textarea:focus{outline:none;border-color:var(--acc)}
button{background:var(--acc);border:0;color:#fff;border-radius:9px;padding:0 18px;font-weight:600;cursor:pointer}
button:disabled{opacity:.5}
.dots{color:var(--dim)}
</style></head><body>
<header style="display:flex;align-items:baseline;gap:14px"><h1>RP Building</h1><div class=sub id=sub style="flex:1;margin-top:0">connecting…</div><a href=/views style="color:var(--acc);text-decoration:none;font-size:13px">apps</a></header>
<div id=log></div>
<footer><div class=inwrap>
<textarea id=in rows=1 placeholder="Ask about current conditions… e.g. what are the chiller temperatures?"></textarea>
<button id=send>Send</button></div></footer>
<script>
const log=document.getElementById('log'),input=document.getElementById('in'),send=document.getElementById('send'),sub=document.getElementById('sub');
let history=[];
function bubble(role,txt){const m=document.createElement('div');m.className='msg '+(role==='user'?'user':'bot');
 m.innerHTML='<div class=who>'+(role==='user'?'you':'RP')+'</div><div class=body></div>';m.querySelector('.body').textContent=txt;log.appendChild(m);log.scrollTop=log.scrollHeight;return m.querySelector('.body');}
function meta(el,t){const d=document.createElement('div');d.className='meta';d.textContent=t;el.parentNode.appendChild(d);}
async function greet(){try{const b=await(await fetch('/building')).json();
 sub.textContent=b.live_points+' live points · '+b.equipment.map(e=>e[1]+' '+e[0]).join(', ');
 const el=bubble('bot',"I'm monitoring the "+b.building+" building in real time — "+b.equipment.map(e=>e[1]+' '+e[0]+(e[1]>1?'s':'')).join(', ')+", "+b.live_points+" points reporting now. Ask me anything about current conditions.");
 const c=document.createElement('div');c.className='chips';['What are the chiller temperatures?','Which chillers are running?','What is CH_1 drawing (kW)?','Any alarms or trips?'].forEach(q=>{const s=document.createElement('div');s.className='chip';s.textContent=q;s.onclick=()=>{input.value=q;go();};c.appendChild(s);});el.parentNode.appendChild(c);
}catch(e){sub.textContent='offline';}}
async function go(){const q=input.value.trim();if(!q)return;input.value='';send.disabled=true;
 bubble('user',q);history.push({role:'user',content:q});
 const el=bubble('bot','');el.innerHTML='<span class=dots>thinking…</span>';
 try{const r=await(await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:q,history})})).json();
 if(r.error){el.textContent='⚠ '+r.error;}else{el.textContent=r.answer;history.push({role:'assistant',content:r.answer});meta(el,r.points_seen+' points · '+r.elapsed+'s');}}
 catch(e){el.textContent='⚠ '+e;}send.disabled=false;input.focus();}
send.onclick=go;input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();go();}});
input.addEventListener('input',()=>{input.style.height='auto';input.style.height=input.scrollHeight+'px';});
greet();
</script></body></html>"""


if __name__ == "__main__":
    print(f"[chat] building={BUILDING} model={MODEL} on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()

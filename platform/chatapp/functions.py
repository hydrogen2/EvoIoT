"""The data-function registry — the verbs of the app layer.

Named, parameterized, read-only queries over the graph (equipment/point
metadata) and the readings hypertable. These are the ONLY things a view spec
can call; the LLM composes them, it never writes SQL or Cypher. The same
functions serve components and (later) agents — one capability surface.

Write-actions (commanding points, ratifying proposals) belong here too but the
platform paths for them don't exist yet — see ACTIONS at the bottom for the
placeholders.
"""

import re
import threading
import time

import psycopg2

# match the point-name suffixes that mean "this binary is an abnormal state"
ALARM_DEFAULT = r"(trip|alarm|fault|fail_to_)"

_DSN = None


def init(dsn: str):
    global _DSN
    _DSN = dsn


def _conn():
    c = psycopg2.connect(_DSN)
    c.autocommit = True
    return c


# ── Cached building metadata + latest values ────────────────────────
# One graph walk + one DISTINCT ON gives everything the point-level functions
# need; at RP scale (~1k points) filtering in Python is trivial and keeps a
# dashboard render (N blocks = N calls) cheap.

class _Cache:
    def __init__(self, ttl, load):
        self.ttl, self.load = ttl, load
        self.at, self.val = 0.0, None
        self.lock = threading.Lock()

    def get(self, *args):
        with self.lock:
            if self.val is None or time.time() - self.at > self.ttl:
                self.val = self.load(*args)
                self.at = time.time()
            return self.val


def _load_meta(tenant):
    """Point metadata from the graph: rawtag id -> (point, equipment, device
    type, building, object type)."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = ag_catalog, evoiot, public")
            cur.execute(f"""
                SELECT rid, nm, otype, eq, dt, bld, un FROM (SELECT * FROM cypher('platform', $$
                    MATCH (r:RawTag {{tenant_id:'{tenant}', tag_type:'object'}})
                    OPTIONAL MATCH (r)-[:BELONGS_TO]->(e:Equipment)
                    OPTIONAL MATCH (e)-[:IS_TYPE_OF]->(d:DeviceType)
                    RETURN r.id, r.object_name, r.object_type, e.name, d.label, r.building, r.unit
                $$) AS (rid agtype, nm agtype, otype agtype, eq agtype, dt agtype, bld agtype, un agtype)) s
            """)
            meta = {}
            for rid, nm, otype, eq, dt, bld, un in cur.fetchall():
                s = lambda v, d="": (str(v).strip('"') if v is not None and str(v) != "null" else d)
                if not s(nm):
                    continue
                meta[s(rid)] = {"point": s(nm), "equipment": s(eq, "(unassigned)"),
                                "device_type": s(dt), "building": s(bld),
                                "object_type": s(otype), "unit": s(un)}
            return meta
    finally:
        conn.close()


def _load_latest(tenant):
    """Latest reading per point within the live window (2h)."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (rawtag_id) rawtag_id, value, unit,
                       extract(epoch FROM now() - observed_at)::int AS age_s
                FROM evoiot.readings
                WHERE tenant_id = %s AND rawtag_id IS NOT NULL
                  AND observed_at > now() - interval '2 hours'
                ORDER BY rawtag_id, observed_at DESC
            """, (tenant,))
            return {rid: {"value": v, "unit": u or "", "age_s": age}
                    for rid, v, u, age in cur.fetchall()}
    finally:
        conn.close()


_meta_cache = _Cache(60, _load_meta)
_latest_cache = _Cache(10, _load_latest)


def _points(tenant, building, match=None, equipment=None, device_type=None,
            live_only=True):
    """Matched (rid, meta, latest|None) rows — the shared point selector."""
    meta = _meta_cache.get(tenant)
    latest = _latest_cache.get(tenant)
    rx = re.compile(match, re.I) if match else None
    out = []
    for rid, m in meta.items():
        if building and m["building"] and m["building"] != building:
            continue
        if equipment and m["equipment"] != equipment:
            continue
        if device_type and m["device_type"] != device_type:
            continue
        if rx and not rx.search(m["point"]):
            continue
        lv = latest.get(rid)
        if live_only and lv is None:
            continue
        out.append((rid, m, lv))
    return out


# ── The read functions ──────────────────────────────────────────────

def latest(ctx, match=None, equipment=None, device_type=None, limit=200):
    rows = []
    for rid, m, lv in _points(ctx["tenant"], ctx["building"], match, equipment, device_type):
        v = lv["value"]
        rows.append({"equipment": m["equipment"], "point": m["point"],
                     "value": round(v, 2) if isinstance(v, float) else v,
                     "unit": lv["unit"] or m["unit"], "age_s": lv["age_s"]})
    rows.sort(key=lambda r: (r["equipment"], r["point"]))
    return {"rows": rows[:limit]}


_OPS = {"sum": sum, "avg": lambda vs: sum(vs) / len(vs), "min": min, "max": max,
        "count": len, "latest": lambda vs: vs[-1]}


def agg_latest(ctx, op, match, equipment=None, device_type=None):
    pts = _points(ctx["tenant"], ctx["building"], match, equipment, device_type)
    vals = [lv["value"] for _, _, lv in pts if lv["value"] is not None]
    unit = next((lv["unit"] or m["unit"] for _, m, lv in pts if lv["unit"] or m["unit"]), "")
    if not vals:
        return {"value": None, "unit": unit, "n": 0}
    return {"value": round(_OPS[op](vals), 3),
            "unit": "" if op == "count" else unit, "n": len(vals)}


def agg_latest_by(ctx, op, match, by="equipment", device_type=None, limit=20):
    groups, unit = {}, ""
    for _, m, lv in _points(ctx["tenant"], ctx["building"], match, None, device_type):
        if lv["value"] is None:
            continue
        groups.setdefault(m[by] if by == "device_type" else m["equipment"], []).append(lv["value"])
        unit = unit or lv["unit"] or m["unit"]
    rows = [{"label": k, "value": round(_OPS[op](vs), 2),
             "unit": "" if op == "count" else unit}
            for k, vs in groups.items()]
    rows.sort(key=lambda r: r["value"], reverse=True)
    return {"rows": rows[:limit], "unit": "" if op == "count" else unit}


def series(ctx, match, equipment=None, device_type=None, hours=24,
           group="point", agg="avg", max_series=6):
    hours = min(int(hours), 168)
    max_series = min(int(max_series), 8)
    pts = _points(ctx["tenant"], ctx["building"], match, equipment, device_type,
                  live_only=False)
    if not pts:
        return {"series": []}
    bucket = 5 if hours <= 6 else 15 if hours <= 24 else 60 if hours <= 72 else 240
    rid_map = {rid: m for rid, m, _ in pts}
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT rawtag_id,
                       time_bucket(interval '{bucket} minutes', observed_at) AS tb,
                       avg(value), max(unit)
                FROM evoiot.readings
                WHERE tenant_id = %s AND rawtag_id = ANY(%s)
                  AND observed_at > now() - interval '{hours} hours'
                  AND value IS NOT NULL
                GROUP BY rawtag_id, tb ORDER BY tb
            """, (ctx["tenant"], list(rid_map)))
            raw = cur.fetchall()
    finally:
        conn.close()

    # fold buckets into the requested grouping
    def key_of(rid):
        m = rid_map[rid]
        if group == "total":
            return "total"
        if group == "equipment":
            return m["equipment"]
        return (f"{m['equipment']} " if m["equipment"] != "(unassigned)" else "") + m["point"]

    folded, units = {}, {}
    for rid, tb, v, u in raw:
        k = key_of(rid)
        folded.setdefault(k, {}).setdefault(tb, []).append(v)
        units.setdefault(k, u or rid_map[rid]["unit"])
    aggf = _OPS[agg]
    out = []
    for k, buckets in folded.items():
        pts_out = [[int(tb.timestamp() * 1000), round(aggf(vs), 3)]
                   for tb, vs in sorted(buckets.items())]
        out.append({"name": k, "unit": units[k], "points": pts_out})
    # keep the biggest movers if over the cap; report the fold, never silent
    dropped = 0
    if len(out) > max_series:
        out.sort(key=lambda s: -(max(p[1] for p in s["points"]) -
                                 min(p[1] for p in s["points"])) if s["points"] else 0)
        dropped = len(out) - max_series
        out = out[:max_series]
    out.sort(key=lambda s: s["name"])
    return {"series": out, "bucket_min": bucket, "dropped_series": dropped}


def equipment_list(ctx, device_type=None, limit=100):
    counts, live = {}, {}
    for rid, m, lv in _points(ctx["tenant"], ctx["building"], None, None,
                              device_type, live_only=False):
        if m["equipment"] == "(unassigned)":
            continue
        k = (m["equipment"], m["device_type"])
        counts[k] = counts.get(k, 0) + 1
        if lv is not None:
            live[k] = live.get(k, 0) + 1
    rows = [{"equipment": eq, "device_type": dt, "points": n,
             "live_points": live.get((eq, dt), 0)}
            for (eq, dt), n in sorted(counts.items())]
    return {"rows": rows[:limit]}


def equipment_summary(ctx):
    agg = {}
    for _, m, lv in _points(ctx["tenant"], ctx["building"], None, None, None,
                            live_only=False):
        if m["equipment"] == "(unassigned)":
            continue
        a = agg.setdefault(m["device_type"] or "(untyped)",
                           {"equipment": set(), "points": 0, "live_points": 0})
        a["equipment"].add(m["equipment"])
        a["points"] += 1
        a["live_points"] += 1 if lv else 0
    rows = [{"device_type": dt, "count": len(a["equipment"]),
             "points": a["points"], "live_points": a["live_points"]}
            for dt, a in sorted(agg.items(), key=lambda kv: -len(kv[1]["equipment"]))]
    return {"rows": rows}


def alarms(ctx, match=None, device_type=None):
    """Binary abnormal-state points currently active (value != 0)."""
    rows, monitored = [], 0
    for _, m, lv in _points(ctx["tenant"], ctx["building"],
                            match or ALARM_DEFAULT, None, device_type):
        monitored += 1
        if lv["value"]:
            rows.append({"equipment": m["equipment"], "point": m["point"],
                         "value": lv["value"], "age_s": lv["age_s"]})
    rows.sort(key=lambda r: (r["equipment"], r["point"]))
    return {"rows": rows, "monitored": monitored}


FUNCTIONS = {
    "latest": latest,
    "agg_latest": agg_latest,
    "agg_latest_by": agg_latest_by,
    "series": series,
    "equipment_list": equipment_list,
    "equipment_summary": equipment_summary,
    "alarms": alarms,
}


def call(name: str, args: dict, tenant: str, building: str):
    if name not in FUNCTIONS:
        raise ValueError(f"unknown function '{name}'")
    return FUNCTIONS[name]({"tenant": tenant, "building": building}, **(args or {}))


# ── Actions (the write verbs) — PLACEHOLDERS ────────────────────────
# The edge command path (platform -> edge ops proxy -> BACnet write) is not
# built yet, and view-level ratification hooks aren't wired to the Restate
# workflows. Registered here so the vocabulary has a place for them; each
# returns not_implemented rather than pretending.

def _not_implemented(what, needs):
    def action(ctx, **kwargs):
        return {"status": "not_implemented", "action": what, "args": kwargs,
                "needs": needs}
    return action


ACTIONS = {
    # needs: edge ops proxy write primitive (arch.md two-primitive surface)
    "write_point": _not_implemented(
        "write_point", "edge ops proxy command path (not yet built)"),
    # needs: route to classifier/discovery review handlers with auth identity
    "ratify": _not_implemented(
        "ratify", "wiring to Restate review handlers + user identity"),
}


def call_action(name: str, args: dict, tenant: str, building: str):
    if name not in ACTIONS:
        raise ValueError(f"unknown action '{name}'")
    return ACTIONS[name]({"tenant": tenant, "building": building}, **(args or {}))

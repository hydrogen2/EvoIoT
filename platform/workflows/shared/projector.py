"""Stage 2 — the projector: derive the AGE graph from the claims log.

Belief lives in the claims log (the belief-bearing subset of evoiot.events).
The graph is a rebuildable *cache*: the current fold of the claims log
materialized as Equipment nodes, their type/membership edges, and RawTag
classifications. This module folds claims → belief, backfills the pre-Stage-1
graph state into the log so the log is complete, and rebuilds the graph.

Fold rules (latest claim wins, by event id):
  is_type_of     (equip → DeviceType) : by subject      → current type
  ratified       (equip → status)     : by subject      → current status
  belongs_to     (rawtag → equip)     : by subject      → current parent
  classified_as  (rawtag → PropertyDef): by (subject, object) → per-classification
Only 'proposed'/'approved' materialize; 'rejected'/'retracted' are dropped.
"""

from . import graph

MATERIALIZE = ("proposed", "approved")


# ── Fold: claims log → current belief ───────────────────────────────

def current_belief() -> dict:
    """Fold the claims log into current belief (does not touch the graph)."""
    conn = graph.get_connection()
    try:
        with conn.cursor() as cur:
            # equipment: type = latest is_type_of; status = latest of
            # (is_type_of | ratified). Retracted/rejected fall out.
            cur.execute("""
                WITH type_latest AS (
                    SELECT DISTINCT ON (data_id) data_id AS equip, claim_object AS dtype
                    FROM evoiot.events WHERE claim_predicate = 'is_type_of'
                    ORDER BY data_id, id DESC),
                status_latest AS (
                    SELECT DISTINCT ON (data_id) data_id AS equip, claim_status AS status
                    FROM evoiot.events WHERE claim_predicate IN ('is_type_of', 'ratified')
                    ORDER BY data_id, id DESC)
                SELECT t.equip, t.dtype, s.status
                FROM type_latest t JOIN status_latest s ON s.equip = t.equip
                WHERE s.status = ANY(%s)
            """, (list(MATERIALIZE),))
            equipment = [{"id": r[0], "type": r[1], "status": r[2]} for r in cur.fetchall()]
            live = {e["id"] for e in equipment}

            cur.execute("""
                SELECT DISTINCT ON (data_id) data_id, claim_object, claim_status
                FROM evoiot.events WHERE claim_predicate = 'belongs_to'
                ORDER BY data_id, id DESC
            """)
            belongs = [{"rawtag": r[0], "equip": r[1]} for r in cur.fetchall()
                       if r[2] in MATERIALIZE and r[1] in live]

            cur.execute("""
                SELECT DISTINCT ON (data_id, claim_object) data_id, claim_object, claim_status, payload
                FROM evoiot.events WHERE claim_predicate = 'classified_as'
                ORDER BY data_id, claim_object, id DESC
            """)
            classes = [{"rawtag": r[0], "property": r[1], "status": r[2],
                        "confidence": (r[3] or {}).get("confidence"),
                        "reason": (r[3] or {}).get("reason")}
                       for r in cur.fetchall() if r[2] in MATERIALIZE]
    finally:
        conn.close()
    return {"equipment": equipment, "belongs_to": belongs, "classifications": classes}


# ── Snapshot: current graph → belief (for verification) ─────────────

def snapshot_graph() -> dict:
    """Read current belief directly from the graph, same shape as current_belief."""
    conn = graph.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT * FROM cypher('platform', $$
                MATCH (e:Equipment)-[:IS_TYPE_OF]->(d:DeviceType)
                RETURN e.id, d.name, e.status $$) AS (eid agtype, dtype agtype, status agtype)""")
            equipment = [{"id": _s(a), "type": _s(b), "status": _s(c)} for a, b, c in cur.fetchall()]
            cur.execute("""SELECT * FROM cypher('platform', $$
                MATCH (r:RawTag)-[:BELONGS_TO]->(e:Equipment)
                RETURN r.id, e.id $$) AS (rid agtype, eid agtype)""")
            belongs = [{"rawtag": _s(a), "equip": _s(b)} for a, b in cur.fetchall()]
            cur.execute("""SELECT * FROM cypher('platform', $$
                MATCH (r:RawTag)-[c:IS_TYPE_OF]->(p:PropertyDef)
                RETURN r.id, p.name, c.status, c.confidence, c.reason $$)
                AS (rid agtype, prop agtype, status agtype, conf agtype, reason agtype)""")
            classes = [{"rawtag": _s(a), "property": _s(b), "status": _s(c) or "proposed",
                        "confidence": float(cf) if cf is not None and str(cf) != 'null' else None,
                        "reason": _s(rs)}
                       for a, b, c, cf, rs in cur.fetchall()]
    finally:
        conn.close()
    return {"equipment": equipment, "belongs_to": belongs, "classifications": classes}


def _s(v) -> str | None:
    return str(v).strip('"') if v is not None and str(v) != 'null' else None


# ── Backfill: current graph → claims log (one-time completeness) ─────

def backfill_claims_from_graph() -> dict:
    """Emit a claim for every current graph fact so the log is complete —
    the standard 'snapshot current state as the initial event set' migration."""
    snap = snapshot_graph()
    for e in snap["equipment"]:
        graph.append_claim(e["id"], "is_type_of", e["type"], e["status"] or "approved",
                           actor="backfill", payload={"backfill": True})
    for m in snap["belongs_to"]:
        graph.append_claim(m["rawtag"], "belongs_to", m["equip"], "approved",
                           actor="backfill", payload={"backfill": True})
    for c in snap["classifications"]:
        graph.append_claim(c["rawtag"], "classified_as", c["property"], c["status"],
                           actor="backfill",
                           payload={"confidence": c.get("confidence"), "reason": c.get("reason")})
    return {k: len(v) for k, v in snap.items()}


# ── Rebuild: wipe projected subgraph, re-materialize from belief ────

def rebuild_graph_from_claims() -> dict:
    """Destructive: DETACH DELETE all Equipment + drop RawTag classifications,
    then re-project from the folded claims log. RawTag/DeviceType/PropertyDef
    (substrate + TBox) are untouched. Writes cypher directly — does NOT go
    through the dual-write path, so it emits no new claims."""
    b = current_belief()
    graph.execute_cypher("MATCH (e:Equipment) DETACH DELETE e")
    graph.execute_cypher("MATCH (:RawTag)-[c:IS_TYPE_OF]->(:PropertyDef) DELETE c")

    for e in b["equipment"]:
        eid = e["id"]
        tenant, name = eid.split(":", 1)
        nm = graph._sanitize_cypher_string(name)
        et = graph._sanitize_cypher_string(e["type"])
        st = graph._sanitize_cypher_string(e["status"])
        graph.execute_cypher(f"MERGE (x:Equipment {{id: '{eid}'}}) RETURN x")
        graph.execute_cypher(
            f"MATCH (x:Equipment {{id: '{eid}'}}) "
            f"SET x.name = '{nm}', x.tenant_id = '{tenant}', x.status = '{st}' RETURN x")
        graph.execute_cypher(
            f"MATCH (x:Equipment {{id: '{eid}'}}) MATCH (d:DeviceType {{name: '{et}'}}) "
            f"MERGE (x)-[:IS_TYPE_OF]->(d) RETURN x")
    for m in b["belongs_to"]:
        graph.execute_cypher(
            f"MATCH (r:RawTag {{id: '{m['rawtag']}'}}) MATCH (x:Equipment {{id: '{m['equip']}'}}) "
            f"MERGE (r)-[:BELONGS_TO]->(x) RETURN r")
    for c in b["classifications"]:
        p = graph._sanitize_cypher_string(c["property"])
        st = graph._sanitize_cypher_string(c["status"])
        conf = c.get("confidence") if c.get("confidence") is not None else 0.0
        reason = graph._sanitize_cypher_string(c.get("reason") or "")
        # AGE does not persist SET on an edge in the same query as its MERGE
        # (works in psql, not via psycopg2) — split, as create_is_type_of_edge does.
        graph.execute_cypher(
            f"MATCH (r:RawTag {{id: '{c['rawtag']}'}}) MATCH (p:PropertyDef {{name: '{p}'}}) "
            f"MERGE (r)-[e:IS_TYPE_OF]->(p) RETURN r")
        graph.execute_cypher(
            f"MATCH (r:RawTag {{id: '{c['rawtag']}'}})-[e:IS_TYPE_OF]->(p:PropertyDef {{name: '{p}'}}) "
            f"SET e.status = '{st}', e.confidence = {conf}, e.reason = '{reason}' RETURN e")
    return {k: len(v) for k, v in b.items()}


# ── Diff helper ─────────────────────────────────────────────────────

def diff_belief(a: dict, b: dict) -> dict:
    """Set-difference two belief dicts; empty everywhere == identical."""
    def keyset(d, kind):
        if kind == "equipment":
            return {(x["id"], x["type"], x["status"]) for x in d[kind]}
        if kind == "belongs_to":
            return {(x["rawtag"], x["equip"]) for x in d[kind]}
        return {(x["rawtag"], x["property"], x["status"]) for x in d[kind]}
    out = {}
    for kind in ("equipment", "belongs_to", "classifications"):
        A, B = keyset(a, kind), keyset(b, kind)
        out[kind] = {"only_in_a": sorted(A - B)[:5], "only_in_b": sorted(B - A)[:5],
                     "n_only_a": len(A - B), "n_only_b": len(B - A)}
    return out

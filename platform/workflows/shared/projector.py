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

    # Reuse the SAME _project_* helpers the incremental belief-writes use, so a
    # full replay and a single claim produce identical graph state.
    for e in b["equipment"]:
        parts = e["id"].split(":")
        if len(parts) >= 3:            # tenant:building:name (current scheme)
            tenant, building, name = parts[0], parts[1], ":".join(parts[2:])
        else:                          # tenant:name (legacy, pre-Stage-4)
            tenant, building, name = parts[0], "", (parts[1] if len(parts) > 1 else "")
        graph._project_equipment(tenant, building, name, e["type"], e["status"])
    for m in b["belongs_to"]:
        graph._project_belongs_to(m["rawtag"], m["equip"])
    for c in b["classifications"]:
        graph._project_classification(c["rawtag"], c["property"], c["status"],
                                      confidence=c.get("confidence") if c.get("confidence") is not None else 0.0,
                                      reason=c.get("reason") or "")
    return {k: len(v) for k, v in b.items()}


# ── Stage 4 migration: de-conflate equipment (building-scope the id) ─

def migrate_building_scope() -> dict:
    """One-time re-key of equipment from legacy tenant:name to building-scoped
    tenant:building:name, SPLITTING cross-building conflations (RP+LP CH_1 into
    HDB:RP:CH_1 and HDB:LP:CH_1). Emits new claims + retracts the legacy ids,
    then reprojects. Idempotent: already-3-part ids are skipped. Classifications
    are keyed by RawTag, so they are unaffected."""
    from collections import defaultdict
    b = current_belief()
    eq = {e["id"]: e for e in b["equipment"]}

    # group each legacy equipment's members by their building
    members: dict = defaultdict(list)
    for m in b["belongs_to"]:
        members[(m["equip"], graph.building_of(m["rawtag"]))].append(m["rawtag"])

    migrated, retracted = 0, 0
    for (old_id, bld), rawtags in members.items():
        if len(old_id.split(":")) != 2:      # already building-scoped
            continue
        e = eq.get(old_id)
        if not e or not bld:
            continue
        tenant, name = old_id.split(":", 1)
        new_id = graph.equipment_id(tenant, bld, name)
        pl = {"tenant_id": tenant, "building": bld, "equipment_name": name}
        graph.append_claim(new_id, "is_type_of", e["type"], e["status"], actor="migrate", payload=pl)
        for rt in rawtags:
            graph.append_claim(rt, "belongs_to", new_id, e["status"], actor="migrate", payload=pl)
        migrated += 1

    for old_id in eq:
        if len(old_id.split(":")) == 2:       # legacy tenant:name — retract it
            graph.append_claim(old_id, "ratified", "retracted", "retracted", actor="migrate")
            retracted += 1

    stats = rebuild_graph_from_claims()
    return {"new_building_scoped": migrated, "legacy_retracted": retracted, **stats}


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

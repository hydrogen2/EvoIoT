"""Graph queries for AGE (Apache Graph Extension)."""

import psycopg2
import json
import logging
import re
import time
import uuid
from .config import (
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB,
    POSTGRES_USER, POSTGRES_PASSWORD
)

logger = logging.getLogger(__name__)


def get_connection():
    """Get a database connection with AGE search path."""
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("LOAD 'age'")
        cur.execute("SET search_path = ag_catalog, evoiot, public")
    return conn


def parse_agtype(value: str) -> dict | None:
    """Parse an AGE agtype value (strips ::vertex, ::edge suffixes)."""
    if not value:
        return None
    # AGE returns strings like '{"id": ..., "properties": {...}}::vertex'
    # Strip the ::type suffix
    if '::' in value:
        value = value.rsplit('::', 1)[0]
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _classify_cypher_op(query: str) -> str:
    """Classify a Cypher query as a read or write operation."""
    q = query.strip().upper()
    if q.startswith("CREATE") or "CREATE " in q:
        return "CREATE"
    if "MERGE " in q:
        return "MERGE"
    if "SET " in q:
        return "SET"
    if "DELETE " in q:
        return "DELETE"
    return "MATCH"


def _extract_cypher_id(query: str) -> str | None:
    """Extract the primary ID from a Cypher query (best-effort)."""
    # Match patterns like {id: 'some-id'} or {name: 'some-name'}
    m = re.search(r"\{(?:id|name):\s*'([^']+)'", query)
    return m.group(1) if m else None


def _emit_graph_event(operation: str, data_id: str | None, query: str):
    """Emit an event for a graph mutation to evoiot.events."""
    # Only emit for write operations
    if operation == "MATCH":
        return
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO evoiot.events (component, operation, data_id, actor, payload)
                       VALUES ('graph', %s, %s, 'restate', %s)""",
                    (operation, data_id,
                     json.dumps({"cypher": query[:500]}, default=str))
                )
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to emit graph event: %s", e)


def append_claim(subject: str, predicate: str, obj: str | None, status: str,
                 actor: str = "restate", component: str = "graph",
                 supersedes_id: int | None = None,
                 payload: dict | None = None) -> int | None:
    """Append a belief-bearing event — a CLAIM — to the authoritative claims log
    (the belief-bearing subset of evoiot.events).

    Stage 1 is DUAL-WRITE: this is called alongside the graph mutation. The
    graph stays the primary read model until the Stage-2 projector can rebuild
    it from these claims, so a claims-log failure must never break the graph
    write — hence swallow-and-warn.

    Belief is recorded append-only: a change is a new claim
    (proposed → approved → retracted), never an in-place edit. The projector
    folds the latest claim per (subject, predicate) into the graph.
    """
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO evoiot.events
                         (component, operation, data_id, actor, payload,
                          claim_predicate, claim_object, claim_status, supersedes_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (component, f"claim_{predicate}", subject, actor,
                     json.dumps(payload or {}, default=str),
                     predicate, obj, status, supersedes_id))
                return cur.fetchone()[0]
        finally:
            conn.close()
    except Exception as e:  # never let the claims log break the primary write
        logger.warning("append_claim failed (%s %s -> %s @ %s): %s",
                       subject, predicate, obj, status, e)
        return None


def _sanitize_cypher_string(value: str) -> str:
    """Sanitize a string value for use inside Cypher single-quoted literals.

    AGE's Cypher parser inside $$...$$ blocks cannot handle backslash escapes
    or embedded quotes. Strip all single quotes, double quotes, backslashes,
    and dollar signs (which could break the $$ delimiter).
    """
    return value.translate(str.maketrans('', '', "\\'\"\n\r$"))


def execute_cypher(query: str) -> list[dict]:
    """Execute a Cypher query, emit event for mutations, return results as dicts."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            sql = f"SELECT * FROM cypher('platform', $${query}$$) AS (result agtype)"
            cur.execute(sql)
            rows = cur.fetchall()
            results = []
            for row in rows:
                result = row[0]
                if result:
                    if isinstance(result, str):
                        parsed = parse_agtype(result)
                        if parsed:
                            results.append(parsed)
                    else:
                        results.append(result)
            return results
    except Exception as e:
        print(f"[graph] ERROR Cypher query failed: {e}\nQuery: {query[:500]}", flush=True)
        return []
    finally:
        conn.close()
        # Emit event after connection is closed (non-blocking)
        op = _classify_cypher_op(query)
        _emit_graph_event(op, _extract_cypher_id(query), query)


def get_rawtags_for_context(tenant_id: str, building: str | None = None) -> list[dict]:
    """Get all RawTags for a tenant, optionally scoped to one building."""
    if building:
        query = f"""
            MATCH (t:RawTag)
            WHERE t.tenant_id = '{tenant_id}' AND t.building = '{building}'
            RETURN t
        """
    else:
        query = f"""
            MATCH (t:RawTag)
            WHERE t.tenant_id = '{tenant_id}'
            RETURN t
        """
    results = execute_cypher(query)
    # Extract node properties from agtype result
    parsed = []
    for r in results:
        if isinstance(r, dict) and 'properties' in r:
            parsed.append(r['properties'])
        elif isinstance(r, dict):
            parsed.append(r)
    return parsed


def get_property_defs(names: list[str]) -> list[dict]:
    """Get multiple PropertyDefs by names."""
    if not names:
        return []
    names_str = ', '.join(f"'{n}'" for n in names)
    query = f"""
        MATCH (p:PropertyDef)
        WHERE p.name IN [{names_str}]
        RETURN p
    """
    results = execute_cypher(query)
    parsed = []
    for r in results:
        if isinstance(r, dict) and 'properties' in r:
            parsed.append(r['properties'])
        elif isinstance(r, dict):
            parsed.append(r)
    return parsed


def get_device_types() -> list[dict]:
    """Get all DeviceType nodes."""
    query = "MATCH (d:DeviceType) RETURN d"
    results = execute_cypher(query)
    parsed = []
    for r in results:
        if isinstance(r, dict) and 'properties' in r:
            parsed.append(r['properties'])
        elif isinstance(r, dict):
            parsed.append(r)
    return parsed


# ── Graph projection (Stage 3) ──────────────────────────────────────
# The graph is a derived cache. These _project_* helpers are the ONLY writers
# of the projected subgraph (Equipment + edges, RawTag classifications), driven
# by claims. Both the incremental path (belief-writes, below) and the batch
# path (projector.rebuild_graph_from_claims) go through them, so a single claim
# and a full replay produce identical graph state.

def _mint_bms_id() -> str:
    """A fresh opaque BMS surrogate. The BMS is the physical observation channel
    (one BACnet internetwork); a device:object address is unique only within it,
    so the BMS — not the organizational 'building' — is what scopes a rawtag."""
    return "bms_" + uuid.uuid4().hex[:12]


def resolve_bms(tenant_id: str, building: str, edge: str | None = None) -> str:
    """Resolve (or mint) the BMS surrogate for a (tenant, building). building is
    an attribute of the BMS, not part of any identity."""
    b = _sanitize_cypher_string(building)
    rows = execute_cypher(
        f"MATCH (m:BMS {{tenant_id: '{tenant_id}', building: '{b}'}}) RETURN m.id")
    if rows:
        v = rows[0]
        return v if isinstance(v, str) else str(v).strip('"')
    bms_id = _mint_bms_id()
    append_claim(bms_id, "bms_exists", building, "approved",
                 payload={"tenant_id": tenant_id, "building": building, "edge": edge})
    _project_bms(bms_id, tenant_id, building, edge)
    return bms_id


def _project_bms(bms_id: str, tenant_id: str, building: str, edge: str | None = None) -> None:
    b = _sanitize_cypher_string(building)
    e = _sanitize_cypher_string(edge or "")
    execute_cypher(f"MERGE (m:BMS {{id: '{bms_id}'}}) RETURN m")
    execute_cypher(f"MATCH (m:BMS {{id: '{bms_id}'}}) "
                   f"SET m.tenant_id = '{tenant_id}', m.building = '{b}', m.edge = '{e}' RETURN m")


def assert_file_export_of_bms(sha256: str, bms_id: str, actor: str = "extraction") -> None:
    """Explicit claim that a catalogued file IS the export of a BMS — replacing
    the folder-convention *implication*. Both the file's points and the wire's
    resolve to the same bms:device:object coordinate and merge."""
    append_claim(sha256, "is_export_of", bms_id, "approved", actor=actor)


def ensure_observes(datasource_id: str, bms_id: str, actor: str = "collector") -> None:
    """Record (once) that a datasource observes a BMS — the collector-side twin
    of is_export_of. Guarded so the pull loop doesn't re-assert every cycle."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM evoiot.events
                   WHERE claim_predicate = 'observes' AND data_id = %s AND claim_object = %s
                   LIMIT 1""", (str(datasource_id), bms_id))
            if cur.fetchone() is None:
                append_claim(str(datasource_id), "observes", bms_id, "approved", actor=actor)
    finally:
        conn.close()


def rawtag_coordinate(bms_id: str, device_id: str, object_type: str, object_instance: str) -> str:
    """BMS-scoped rawtag coordinate: bms:device:object_type:object_instance.
    All datasources of one BMS report the same coordinate for the same point,
    so multi-source observations merge with no per-reading resolution."""
    return f"{bms_id}:{device_id}:{object_type}:{object_instance}"


def building_of(rawtag_id: str) -> str:
    """Building of a rawtag, via its BMS. The coordinate is bms:device:object;
    building is an attribute of the BMS, looked up (not parsed from the id)."""
    bms_id = (rawtag_id or "").split(":")[0]
    if not bms_id.startswith("bms_"):
        # legacy tenant:building:device:... coordinate
        parts = (rawtag_id or "").split(":")
        return parts[1] if len(parts) > 2 else ""
    rows = execute_cypher(f"MATCH (m:BMS {{id: '{bms_id}'}}) RETURN m.building")
    if rows:
        v = rows[0]
        return v if isinstance(v, str) else str(v).strip('"')
    return ""


def _mint_equipment_id() -> str:
    """A fresh opaque equipment surrogate. Identity is decoupled from the
    (mutable) name so a review correction — rename, re-type, merge — updates a
    property instead of orphaning every BELONGS_TO edge."""
    return "eq_" + uuid.uuid4().hex[:12]


def resolve_equipment(tenant_id: str, building: str, name: str) -> str | None:
    """Resolve an equipment's surrogate by its natural key (tenant, building,
    name). Used to keep discovery idempotent (a re-run with the same name maps
    to the same surrogate) and to let callers reference equipment by name."""
    b = _sanitize_cypher_string(building)
    n = _sanitize_cypher_string(name)
    rows = execute_cypher(
        f"MATCH (e:Equipment {{tenant_id: '{tenant_id}', building: '{b}', name: '{n}'}}) "
        f"RETURN e.id")
    if rows:
        v = rows[0]
        return v if isinstance(v, str) else str(v).strip('"')
    return None


def _project_equipment(equip_id: str, tenant_id: str, building: str,
                       equipment_name: str, equipment_type: str, status: str) -> None:
    """Materialize an equipment (by surrogate id) — its natural key, type, and
    status — from a claim."""
    name = _sanitize_cypher_string(equipment_name)
    bld = _sanitize_cypher_string(building)
    etype = _sanitize_cypher_string(equipment_type)
    st = _sanitize_cypher_string(status)
    execute_cypher(f"MERGE (e:Equipment {{id: '{equip_id}'}}) RETURN e")
    # SET props separately (AGE MERGE+SET quirk)
    execute_cypher(f"MATCH (e:Equipment {{id: '{equip_id}'}}) "
                   f"SET e.name = '{name}', e.tenant_id = '{tenant_id}', "
                   f"e.building = '{bld}', e.status = '{st}' RETURN e")
    # Replace the type edge (re-typing must not leave a second IS_TYPE_OF)
    execute_cypher(f"MATCH (e:Equipment {{id: '{equip_id}'}})-[t:IS_TYPE_OF]->(:DeviceType) "
                   f"DELETE t RETURN e")
    execute_cypher(f"MATCH (e:Equipment {{id: '{equip_id}'}}) MATCH (d:DeviceType {{name: '{etype}'}}) "
                   f"MERGE (e)-[:IS_TYPE_OF]->(d) RETURN e")


def _project_belongs_to(rawtag_id: str, equip_id: str) -> None:
    execute_cypher(f"MATCH (r:RawTag {{id: '{rawtag_id}'}}) MATCH (e:Equipment {{id: '{equip_id}'}}) "
                   f"MERGE (r)-[:BELONGS_TO]->(e) RETURN r")


def _project_equipment_status(equip_id: str, status: str) -> None:
    st = _sanitize_cypher_string(status)
    execute_cypher(f"MATCH (e:Equipment {{id: '{equip_id}'}}) SET e.status = '{st}' RETURN e")


def _retract_equipment(equip_id: str) -> None:
    execute_cypher(f"MATCH (e:Equipment {{id: '{equip_id}'}}) "
                   f"OPTIONAL MATCH ()-[b:BELONGS_TO]->(e) OPTIONAL MATCH (e)-[t:IS_TYPE_OF]->() "
                   f"DELETE b, t, e RETURN count(*)")


def _project_classification(rawtag_id: str, property_name: str, status: str,
                            confidence: float | None = None, reason: str | None = None,
                            approved_by: str | None = None, feedback: str | None = None) -> None:
    """Materialize a RawTag classification from a claim. confidence/reason are
    only written when provided, so a status-only ratification preserves them."""
    prop = _sanitize_cypher_string(property_name)
    execute_cypher(f"MATCH (r:RawTag {{id: '{rawtag_id}'}}) MATCH (p:PropertyDef {{name: '{prop}'}}) "
                   f"MERGE (r)-[e:IS_TYPE_OF]->(p) RETURN r")
    sets = [f"e.status = '{_sanitize_cypher_string(status)}'"]
    if confidence is not None:
        sets.append(f"e.confidence = {confidence}")
    if reason is not None:
        sets.append(f"e.reason = '{_sanitize_cypher_string(reason)}'")
    if status == "approved" and approved_by:
        sets.append(f"e.approved_at = {int(time.time() * 1000)}")
        sets.append(f"e.approved_by = '{_sanitize_cypher_string(approved_by)}'")
    if feedback:
        sets.append(f"e.feedback = '{_sanitize_cypher_string(feedback)}'")
    execute_cypher(f"MATCH (r:RawTag {{id: '{rawtag_id}'}})-[e:IS_TYPE_OF]->(p:PropertyDef {{name: '{prop}'}}) "
                   f"SET {', '.join(sets)} RETURN e")


def _require_claim(cid: int | None, what: str) -> None:
    """The claims log is the source of truth (Stage 3): if it can't record the
    belief, the operation fails rather than mutating a derived cache silently."""
    if cid is None:
        raise RuntimeError(f"claims log write failed: {what}")


# ── Belief-writes: append the claim (source of truth), then project ─

def create_equipment_and_link(
    tenant_id: str,
    equipment_name: str,
    equipment_type: str,
    rawtag_id: str,
    status: str = "approved",
) -> str | None:
    """Assert equipment type + membership. Resolves the equipment's surrogate by
    natural key (or mints one), so re-runs are idempotent and the id survives a
    later rename. The claim is authoritative; the graph is its projection."""
    if not equipment_name or not equipment_type:
        return None
    building = building_of(rawtag_id)
    equip_id = resolve_equipment(tenant_id, building, equipment_name) or _mint_equipment_id()
    payload = {"tenant_id": tenant_id, "building": building, "equipment_name": equipment_name}
    _require_claim(append_claim(equip_id, "is_type_of", equipment_type, status, payload=payload),
                   f"{equip_id} is_type_of {equipment_type}")
    _require_claim(append_claim(rawtag_id, "belongs_to", equip_id, status, payload=payload),
                   f"{rawtag_id} belongs_to {equip_id}")
    _project_equipment(equip_id, tenant_id, building, equipment_name, equipment_type, status)
    _project_belongs_to(rawtag_id, equip_id)
    print(f"[graph] Linked RawTag {rawtag_id} -> Equipment {equip_id} "
          f"({equipment_name}) -> {equipment_type}", flush=True)
    return equip_id


def update_equipment_status(tenant_id: str, building: str, equipment_name: str, status: str) -> None:
    """Ratify an equipment (status transition). Claim first, then project."""
    equip_id = resolve_equipment(tenant_id, building, equipment_name)
    if not equip_id:
        return
    payload = {"tenant_id": tenant_id, "building": building, "equipment_name": equipment_name}
    _require_claim(append_claim(equip_id, "ratified", status, status, payload=payload),
                   f"{equip_id} ratified {status}")
    if status == "retracted":
        _retract_equipment(equip_id)
    else:
        _project_equipment_status(equip_id, status)
    print(f"[graph] Equipment {equip_id} ({equipment_name}) status -> {status}", flush=True)


def delete_equipment(tenant_id: str, building: str, equipment_name: str) -> None:
    """Retract an equipment. Recorded as a retraction claim, not an erasure."""
    equip_id = resolve_equipment(tenant_id, building, equipment_name)
    if not equip_id:
        return
    payload = {"tenant_id": tenant_id, "building": building, "equipment_name": equipment_name}
    _require_claim(append_claim(equip_id, "ratified", "retracted", "retracted", payload=payload),
                   f"{equip_id} retracted")
    _retract_equipment(equip_id)
    print(f"[graph] Deleted Equipment {equip_id} ({equipment_name})", flush=True)


def get_pending_equipment() -> list[dict]:
    """Get all Equipment nodes with status='proposed'."""
    query = """
        MATCH (e:Equipment)-[:IS_TYPE_OF]->(d:DeviceType)
        WHERE e.status = 'proposed'
        RETURN e.id AS id, e.name AS name, d.name AS device_type,
               e.tenant_id AS tenant_id, e.building AS building
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            sql = f"SELECT * FROM cypher('platform', $${query}$$) AS (id agtype, name agtype, device_type agtype, tenant_id agtype, building agtype)"
            cur.execute(sql)
            rows = cur.fetchall()
            return [
                {
                    "id": str(row[0]).strip('"') if row[0] else None,
                    "equipment_name": str(row[1]).strip('"') if row[1] else None,
                    "device_type": str(row[2]).strip('"') if row[2] else None,
                    "tenant_id": str(row[3]).strip('"') if row[3] else None,
                    "building": str(row[4]).strip('"') if row[4] and str(row[4]) != 'null' else None,
                }
                for row in rows
            ]
    finally:
        conn.close()


def get_equipment_rawtags(equip_id: str) -> list[dict]:
    """Get all RawTags belonging to an equipment (by building-scoped id)."""
    query = f"""
        MATCH (r:RawTag)-[:BELONGS_TO]->(e:Equipment {{id: '{equip_id}'}})
        RETURN r
    """
    results = execute_cypher(query)
    parsed = []
    for r in results:
        if isinstance(r, dict) and 'properties' in r:
            parsed.append(r['properties'])
        elif isinstance(r, dict):
            parsed.append(r)
    return parsed


def create_is_type_of_edge(
    rawtag_id: str,
    property_name: str,
    status: str = "proposed",
    confidence: float = 0.0,
    reason: str = ""
) -> dict:
    """Classify a RawTag. The claim is authoritative; the edge is its projection."""
    print(f"[graph] Classifying: {rawtag_id} -> {property_name} (confidence={confidence})", flush=True)
    _require_claim(
        append_claim(rawtag_id, "classified_as", property_name, status,
                     payload={"confidence": confidence, "reason": reason}),
        f"{rawtag_id} classified_as {property_name}")
    _project_classification(rawtag_id, property_name, status,
                            confidence=confidence, reason=reason)
    return {}


def get_pending_proposals() -> list[dict]:
    """Get all IS_TYPE_OF edges that are not yet approved."""
    query = """
        MATCH (r:RawTag)-[e:IS_TYPE_OF]->(p:PropertyDef)
        WHERE e.status IS NULL OR e.status = 'proposed'
        RETURN r.id AS rawtag_id, p.name AS tbox_type, e.confidence AS confidence, e.reason AS reason, e.status AS status
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            sql = f"SELECT * FROM cypher('platform', $${query}$$) AS (rawtag_id agtype, tbox_type agtype, confidence agtype, reason agtype, status agtype)"
            cur.execute(sql)
            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append({
                    "rawtag_id": str(row[0]).strip('"') if row[0] else None,
                    "tbox_type": str(row[1]).strip('"') if row[1] else None,
                    "confidence": float(row[2]) if row[2] else 0.0,
                    "reason": str(row[3]).strip('"') if row[3] else "",
                    "status": str(row[4]).strip('"') if row[4] else "proposed"
                })
            return results
    finally:
        conn.close()


def update_is_type_of_status(
    rawtag_id: str,
    property_name: str,
    status: str,
    approved_by: str | None = None,
    feedback: str | None = None
) -> dict:
    """Ratify a classification (status transition). Claim first, then project."""
    _require_claim(
        append_claim(rawtag_id, "classified_as", property_name, status,
                     payload={"approved_by": approved_by, "feedback": feedback}),
        f"{rawtag_id} classified_as {property_name} ({status})")
    # Re-project at the new status; confidence/reason omitted so they're preserved.
    _project_classification(rawtag_id, property_name, status,
                            approved_by=approved_by, feedback=feedback)
    return {}

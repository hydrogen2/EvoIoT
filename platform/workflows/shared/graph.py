"""Graph queries for AGE (Apache Graph Extension)."""

import psycopg2
import json
import logging
import re
import time
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


def create_equipment_and_link(
    tenant_id: str,
    equipment_name: str,
    equipment_type: str,
    rawtag_id: str,
    status: str = "approved",
) -> None:
    """Create Equipment node, link it to DeviceType, and link RawTag to it.

    Equipment ID = {tenant_id}:{equipment_name}
    Creates:
      Equipment --IS_TYPE_OF--> DeviceType
      RawTag --BELONGS_TO--> Equipment
    """
    if not equipment_name or not equipment_type:
        return

    equip_id = f"{tenant_id}:{equipment_name}"
    equip_name_safe = _sanitize_cypher_string(equipment_name)
    equip_type_safe = _sanitize_cypher_string(equipment_type)

    print(f"[graph] Creating Equipment: {equip_id} (type={equipment_type}, status={status})", flush=True)

    # MERGE Equipment node
    execute_cypher(f"""
        MERGE (e:Equipment {{id: '{equip_id}'}})
        RETURN e
    """)
    # SET properties separately (AGE MERGE+SET bug)
    execute_cypher(f"""
        MATCH (e:Equipment {{id: '{equip_id}'}})
        SET e.name = '{equip_name_safe}',
            e.tenant_id = '{tenant_id}',
            e.status = '{status}'
        RETURN e
    """)

    # Equipment --IS_TYPE_OF--> DeviceType. Drop any existing type edge first:
    # a re-run that re-types the equipment must REPLACE the type, not add a
    # second one (observed: PAHUs ending up typed both MAU and PAU).
    execute_cypher(f"""
        MATCH (e:Equipment {{id: '{equip_id}'}})-[t:IS_TYPE_OF]->(:DeviceType)
        DELETE t
        RETURN e
    """)
    execute_cypher(f"""
        MATCH (e:Equipment {{id: '{equip_id}'}})
        MATCH (d:DeviceType {{name: '{equip_type_safe}'}})
        MERGE (e)-[:IS_TYPE_OF]->(d)
        RETURN e
    """)

    # MERGE RawTag --BELONGS_TO--> Equipment
    execute_cypher(f"""
        MATCH (r:RawTag {{id: '{rawtag_id}'}})
        MATCH (e:Equipment {{id: '{equip_id}'}})
        MERGE (r)-[:BELONGS_TO]->(e)
        RETURN r
    """)

    print(f"[graph] Linked RawTag {rawtag_id} -> Equipment {equip_id} -> DeviceType {equipment_type}", flush=True)

    # Dual-write claims (Stage 1). The type claim repeats per rawtag (this fn is
    # called once per member); that's idempotent — the projector folds by
    # (subject, predicate) to the latest. belongs_to is genuinely per-rawtag.
    append_claim(equip_id, "is_type_of", equipment_type, status,
                 payload={"tenant_id": tenant_id, "equipment_name": equipment_name})
    append_claim(rawtag_id, "belongs_to", equip_id, status,
                 payload={"tenant_id": tenant_id, "equipment_name": equipment_name})


def update_equipment_status(tenant_id: str, equipment_name: str, status: str) -> None:
    """Update the status of an Equipment node."""
    equip_id = f"{tenant_id}:{equipment_name}"
    execute_cypher(f"""
        MATCH (e:Equipment {{id: '{equip_id}'}})
        SET e.status = '{status}'
        RETURN e
    """)
    print(f"[graph] Equipment {equip_id} status -> {status}", flush=True)
    # Dual-write: a ratification is a new claim that supersedes the proposal.
    append_claim(equip_id, "ratified", status, status,
                 payload={"tenant_id": tenant_id, "equipment_name": equipment_name})


def delete_equipment(tenant_id: str, equipment_name: str) -> None:
    """Delete an Equipment node and its BELONGS_TO edges."""
    equip_id = f"{tenant_id}:{equipment_name}"
    execute_cypher(f"""
        MATCH (e:Equipment {{id: '{equip_id}'}})
        OPTIONAL MATCH ()-[b:BELONGS_TO]->(e)
        OPTIONAL MATCH (e)-[t:IS_TYPE_OF]->()
        DELETE b, t, e
        RETURN count(*)
    """)
    print(f"[graph] Deleted Equipment {equip_id}", flush=True)
    # Dual-write: deletion is a retraction claim, not an erasure of history.
    append_claim(equip_id, "ratified", "retracted", "retracted",
                 payload={"tenant_id": tenant_id, "equipment_name": equipment_name})


def get_pending_equipment() -> list[dict]:
    """Get all Equipment nodes with status='proposed'."""
    query = """
        MATCH (e:Equipment)-[:IS_TYPE_OF]->(d:DeviceType)
        WHERE e.status = 'proposed'
        RETURN e.id AS id, e.name AS name, d.name AS device_type, e.tenant_id AS tenant_id
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            sql = f"SELECT * FROM cypher('platform', $${query}$$) AS (id agtype, name agtype, device_type agtype, tenant_id agtype)"
            cur.execute(sql)
            rows = cur.fetchall()
            return [
                {
                    "id": str(row[0]).strip('"') if row[0] else None,
                    "equipment_name": str(row[1]).strip('"') if row[1] else None,
                    "device_type": str(row[2]).strip('"') if row[2] else None,
                    "tenant_id": str(row[3]).strip('"') if row[3] else None,
                }
                for row in rows
            ]
    finally:
        conn.close()


def get_equipment_rawtags(tenant_id: str, equipment_name: str) -> list[dict]:
    """Get all RawTags belonging to a specific equipment."""
    equip_id = f"{tenant_id}:{equipment_name}"
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
    """Create an IS_TYPE_OF edge between RawTag and PropertyDef."""
    timestamp = int(time.time() * 1000)
    reason_safe = _sanitize_cypher_string(reason)

    # MERGE to ensure the edge exists
    merge_query = f"""
        MATCH (r:RawTag {{id: '{rawtag_id}'}})
        MATCH (p:PropertyDef {{name: '{property_name}'}})
        MERGE (r)-[e:IS_TYPE_OF]->(p)
        RETURN e
    """
    print(f"[graph] Creating IS_TYPE_OF: {rawtag_id} -> {property_name} (confidence={confidence})", flush=True)
    execute_cypher(merge_query)

    # SET properties separately — AGE doesn't persist SET on edges when
    # combined with MERGE in the same query via psycopg2 (works in psql).
    set_query = f"""
        MATCH (r:RawTag {{id: '{rawtag_id}'}})-[e:IS_TYPE_OF]->(p:PropertyDef {{name: '{property_name}'}})
        SET e.status = '{status}',
            e.confidence = {confidence},
            e.reason = '{reason_safe}',
            e.proposed_at = {timestamp},
            e.approved_at = null,
            e.approved_by = null,
            e.feedback = null
        RETURN e
    """
    results = execute_cypher(set_query)
    if results:
        print(f"[graph] IS_TYPE_OF edge properties set: {results[0]}", flush=True)
    else:
        print(f"[graph] WARNING: IS_TYPE_OF SET returned empty for {rawtag_id} -> {property_name}", flush=True)
    # Dual-write: the classification is a claim about this rawtag.
    append_claim(rawtag_id, "classified_as", property_name, status,
                 payload={"confidence": confidence, "reason": reason})
    return results[0] if results else {}


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
    """Update the status of an IS_TYPE_OF edge."""
    set_clauses = [f"e.status = '{status}'"]
    if status == "approved" and approved_by:
        timestamp = int(time.time() * 1000)
        set_clauses.append(f"e.approved_at = {timestamp}")
        set_clauses.append(f"e.approved_by = '{approved_by}'")
    if feedback:
        set_clauses.append(f"e.feedback = '{_sanitize_cypher_string(feedback)}'")

    set_clause = ", ".join(set_clauses)

    query = f"""
        MATCH (r:RawTag {{id: '{rawtag_id}'}})-[e:IS_TYPE_OF]->(p:PropertyDef {{name: '{property_name}'}})
        SET {set_clause}
        RETURN e
    """
    results = execute_cypher(query)
    # Dual-write: re-assert the classification claim at the new status
    # (supersedes the proposal); single predicate carries the lifecycle.
    append_claim(rawtag_id, "classified_as", property_name, status,
                 payload={"approved_by": approved_by, "feedback": feedback})
    return results[0] if results else {}

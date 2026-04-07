"""Graph queries for AGE (Apache Graph Extension)."""

import psycopg2
import json
import time
from .config import (
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB,
    POSTGRES_USER, POSTGRES_PASSWORD
)


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


def execute_cypher(query: str) -> list[dict]:
    """Execute a Cypher query and return results as dicts."""
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
    finally:
        conn.close()


def get_rawtags_for_context(building_id: str, source_id: str | None = None) -> list[dict]:
    """Get all RawTags for a building, optionally filtered by source."""
    if source_id:
        query = f"""
            MATCH (t:RawTag)
            WHERE t.building_id = '{building_id}' AND t.source_id = '{source_id}'
            RETURN t
        """
    else:
        query = f"""
            MATCH (t:RawTag)
            WHERE t.building_id = '{building_id}'
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


def create_is_type_of_edge(
    rawtag_id: str,
    property_name: str,
    status: str = "proposed",
    confidence: float = 0.0,
    reason: str = ""
) -> dict:
    """Create an IS_TYPE_OF edge between RawTag and PropertyDef."""
    timestamp = int(time.time() * 1000)
    # Escape for Cypher: backslash-escape quotes and backslashes
    reason_escaped = reason.replace("\\", "\\\\").replace("'", "\\'")

    query = f"""
        MATCH (r:RawTag {{id: '{rawtag_id}'}})
        MATCH (p:PropertyDef {{name: '{property_name}'}})
        MERGE (r)-[e:IS_TYPE_OF]->(p)
        SET e.status = '{status}',
            e.confidence = {confidence},
            e.reason = '{reason_escaped}',
            e.proposed_at = {timestamp},
            e.approved_at = null,
            e.approved_by = null,
            e.feedback = null
        RETURN e
    """
    results = execute_cypher(query)
    return results[0] if results else {}


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
        feedback_escaped = feedback.replace("\\", "\\\\").replace("'", "\\'")
        set_clauses.append(f"e.feedback = '{feedback_escaped}'")

    set_clause = ", ".join(set_clauses)

    query = f"""
        MATCH (r:RawTag {{id: '{rawtag_id}'}})-[e:IS_TYPE_OF]->(p:PropertyDef {{name: '{property_name}'}})
        SET {set_clause}
        RETURN e
    """
    results = execute_cypher(query)
    return results[0] if results else {}

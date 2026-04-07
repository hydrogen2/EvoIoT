"""Graph queries for AGE (Apache Graph Extension)."""

import asyncpg
import json
from typing import Any
from .config import POSTGRES_URL


async def get_connection() -> asyncpg.Connection:
    """Get a database connection with AGE search path."""
    conn = await asyncpg.connect(POSTGRES_URL)
    await conn.execute("LOAD 'age'")
    await conn.execute("SET search_path = ag_catalog, evoiot, public")
    return conn


async def execute_cypher(query: str, params: dict | None = None) -> list[dict]:
    """Execute a Cypher query and return results as dicts."""
    conn = await get_connection()
    try:
        # AGE requires parameters as a JSON string
        if params:
            params_json = json.dumps(params)
            sql = f"SELECT * FROM cypher('platform', $${query}$$, '{params_json}') AS (result agtype)"
        else:
            sql = f"SELECT * FROM cypher('platform', $${query}$$) AS (result agtype)"

        rows = await conn.fetch(sql)
        results = []
        for row in rows:
            # AGE returns agtype which needs parsing
            result = row['result']
            if result:
                # agtype is returned as string, parse it
                if isinstance(result, str):
                    results.append(json.loads(result))
                else:
                    results.append(result)
        return results
    finally:
        await conn.close()


async def get_rawtags_for_context(building_id: str, source_id: str | None = None) -> list[dict]:
    """Get all RawTags for a building, optionally filtered by source."""
    query = """
        MATCH (t:RawTag {building_id: $building_id})
        WHERE $source_id IS NULL OR t.source_id = $source_id
        RETURN t
    """
    # Simple query without params for now (AGE param handling is complex)
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
    return await execute_cypher(query)


async def get_property_def(name: str) -> dict | None:
    """Get a PropertyDef by name."""
    query = f"""
        MATCH (p:PropertyDef {{name: '{name}'}})
        RETURN p
    """
    results = await execute_cypher(query)
    return results[0] if results else None


async def get_property_defs(names: list[str]) -> list[dict]:
    """Get multiple PropertyDefs by names."""
    names_str = ', '.join(f"'{n}'" for n in names)
    query = f"""
        MATCH (p:PropertyDef)
        WHERE p.name IN [{names_str}]
        RETURN p
    """
    return await execute_cypher(query)


async def create_is_type_of_edge(
    rawtag_id: str,
    property_name: str,
    status: str = "proposed",
    confidence: float = 0.0,
    reason: str = ""
) -> dict:
    """Create an IS_TYPE_OF edge between RawTag and PropertyDef."""
    import time
    timestamp = int(time.time() * 1000)

    query = f"""
        MATCH (r:RawTag {{id: '{rawtag_id}'}})
        MATCH (p:PropertyDef {{name: '{property_name}'}})
        MERGE (r)-[e:IS_TYPE_OF]->(p)
        SET e.status = '{status}',
            e.confidence = {confidence},
            e.reason = '{reason}',
            e.proposed_at = {timestamp},
            e.approved_at = null,
            e.approved_by = null,
            e.feedback = null
        RETURN e
    """
    results = await execute_cypher(query)
    return results[0] if results else {}


async def update_is_type_of_status(
    rawtag_id: str,
    property_name: str,
    status: str,
    approved_by: str | None = None,
    feedback: str | None = None
) -> dict:
    """Update the status of an IS_TYPE_OF edge."""
    import time

    set_clauses = [f"e.status = '{status}'"]
    if status == "approved" and approved_by:
        timestamp = int(time.time() * 1000)
        set_clauses.append(f"e.approved_at = {timestamp}")
        set_clauses.append(f"e.approved_by = '{approved_by}'")
    if feedback:
        set_clauses.append(f"e.feedback = '{feedback}'")

    set_clause = ", ".join(set_clauses)

    query = f"""
        MATCH (r:RawTag {{id: '{rawtag_id}'}})-[e:IS_TYPE_OF]->(p:PropertyDef {{name: '{property_name}'}})
        SET {set_clause}
        RETURN e
    """
    results = await execute_cypher(query)
    return results[0] if results else {}


async def get_existing_classifications(rawtag_ids: list[str]) -> dict[str, list[dict]]:
    """Get existing IS_TYPE_OF edges for a list of RawTags."""
    ids_str = ', '.join(f"'{id}'" for id in rawtag_ids)
    query = f"""
        MATCH (r:RawTag)-[e:IS_TYPE_OF]->(p:PropertyDef)
        WHERE r.id IN [{ids_str}]
        RETURN r.id AS rawtag_id, e AS edge, p.name AS property_name
    """
    results = await execute_cypher(query)

    # Group by rawtag_id
    classifications: dict[str, list[dict]] = {}
    for r in results:
        rawtag_id = r.get('rawtag_id')
        if rawtag_id not in classifications:
            classifications[rawtag_id] = []
        classifications[rawtag_id].append({
            'property_name': r.get('property_name'),
            'edge': r.get('edge')
        })
    return classifications

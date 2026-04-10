"""Traced wrapper for Restate ctx.run() — the workflow chokepoint for event emission."""

import json
import logging
import psycopg2
from .config import POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

logger = logging.getLogger(__name__)


def _get_events_connection():
    """Get a connection for writing events."""
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    conn.autocommit = True
    return conn


def _summarize(result, max_len=500):
    """Truncate result to avoid bloating events table."""
    if result is None:
        return None
    try:
        s = json.dumps(result, default=str)
    except (TypeError, ValueError):
        s = str(result)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _emit_event(component, operation, data_id=None, trace_id=None, actor=None, payload=None):
    """Write a single event to evoiot.events."""
    try:
        conn = _get_events_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO evoiot.events (component, operation, data_id, trace_id, actor, payload)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (component, operation, data_id, trace_id, actor,
                     json.dumps(payload, default=str) if payload else None)
                )
        finally:
            conn.close()
    except Exception as e:
        # Event emission must never break the workflow
        logger.warning("Failed to emit event: %s", e)


async def traced_run(ctx, name, fn, data_id=None):
    """Wrapper around ctx.run() that emits a provenance event for every step.

    Args:
        ctx: Restate WorkflowContext
        name: Step name (e.g., "fetch_rawtags", "classify")
        fn: The function to execute
        data_id: Optional data correlation key (defaults to workflow key)
    """
    result = await ctx.run(name, fn)

    _emit_event(
        component="restate.classifier",
        operation=name,
        data_id=data_id or ctx.key(),
        trace_id=ctx.key(),
        actor="restate",
        payload={"result_summary": _summarize(result)},
    )

    return result

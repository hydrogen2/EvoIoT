"""Collector framework — the durable, platform-side control plane.

One Restate virtual object (`collector`) serves every source_type='collector'
data source, keyed by its data_sources.id (like file_watcher). It owns the
smart parts that are identical across all collectors:

  - a durable self-scheduling scan loop (survives restarts via Restate)
  - the incremental watermark, held in Restate object state (not a file)
  - retry/backoff (Restate handles it), interval, enable/disable
  - publishing readings through the normal MQTT → Bento → readings path
    (so provenance/tracing chokepoints still fire)

Everything source- and transport-specific is delegated (sources.build_source,
transport.build_transport). Adding a new collector kind = a new Source; the
control plane here does not change.
"""

import json
import os
from datetime import timedelta

import paho.mqtt.client as mqtt
import psycopg2
from restate import VirtualObject, ObjectContext

from shared.config import (POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB,
                           POSTGRES_USER, POSTGRES_PASSWORD)
from .transport import build_transport
from .sources import build_source

MQTT_HOST = os.environ.get("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
DEFAULT_INTERVAL_S = 60

collector = VirtualObject("collector")


def _connect():
    conn = psycopg2.connect(host=POSTGRES_HOST, port=POSTGRES_PORT, database=POSTGRES_DB,
                            user=POSTGRES_USER, password=POSTGRES_PASSWORD)
    conn.autocommit = True
    return conn


def _load_config(source_id: str):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT config, enabled FROM evoiot.data_sources
                           WHERE id = %s AND source_type = 'collector'""", (source_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    return row  # (config, enabled) or None


def _load_config_map(tenant: str, name: str) -> dict:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT config FROM evoiot.config_maps
                           WHERE name = %s AND tenant_id IN (%s, '*')
                           ORDER BY tenant_id = %s DESC LIMIT 1""",
                        (name, tenant, tenant))
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"config map '{name}' not found for tenant {tenant}")
    return row[0] or {}


def _resolve_transport(config: dict) -> dict:
    """Resolve a transport spec, expanding a {"ref": "<config-map>"} into the
    concrete connection from the seed config map (declared once, not embedded)."""
    spec = dict(config.get("transport") or {})
    ref = spec.pop("ref", None)
    if ref:
        ssh = _load_config_map(config["tenant"], ref).get("ssh", {})
        spec.setdefault("type", "ssh")
        host, user = ssh["host"], ssh.get("user")
        spec["target"] = f"{user}@{host}" if user else host
    return spec


def resolve_namespace(config: dict) -> str:
    """The rawtag_id namespace is the BUILDING (physical-network scope), NOT the
    evidence source — source is recorded per-tag as origin. Single-building edge
    sources take it from their seed config map; it can also be set explicitly."""
    ref = (config.get("transport") or {}).get("ref")
    if ref:
        building = _load_config_map(config["tenant"], ref).get("building")
        if building:
            return building
    return config.get("building") or config["tenant"]


def run_cycle(source_id: str, watermark):
    """One pull cycle for a collector. Returns (published, new_watermark,
    interval, status)."""
    row = _load_config(source_id)
    if row is None:
        return 0, watermark, DEFAULT_INTERVAL_S, "unknown_source"
    config, enabled = row[0] or {}, row[1]
    interval = int(config.get("scan_interval_s", DEFAULT_INTERVAL_S))
    if not enabled:
        return 0, watermark, interval, "disabled"

    transport = build_transport(_resolve_transport(config))
    source = build_source(config, transport)
    readings, new_watermark = source.pull(watermark)

    if readings:
        _publish(config, readings)
    return len(readings), new_watermark, interval, "ok"


def _publish(config: dict, readings: list):
    """Publish readings as telemetry (MQTT → Bento → readings), keyed by raw
    BACnet identity. rawtag_id is stated explicitly so it joins existing
    RawTags regardless of which evidence source reported the point."""
    tenant = config["tenant"]
    agent = config.get("agent_id", "collector")
    ns = resolve_namespace(config)   # building name, not the source
    topic = f"buildings/{tenant}/agents/{agent}/telemetry"

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"collector-{agent}")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    try:
        for r in readings:
            rawtag_id = f"{tenant}:{ns}:{r['device_id']}:{r['object_type']}:{r['object_instance']}"
            payload = {
                "building_id": tenant, "source_id": agent,
                "rawtag_id": rawtag_id, "device_id": r["device_id"],
                "object_type": r["object_type"], "object_instance": r["object_instance"],
                "point_type": "unclassified", "value": r["value"],
                "unit": r.get("unit", ""), "agent_read_at": r["observed_at"],
                **(r.get("provenance") or {}),
            }
            client.publish(topic, json.dumps(payload), qos=1)
    finally:
        client.loop_stop()
        client.disconnect()


@collector.handler()
async def start(ctx: ObjectContext, req: dict) -> dict:
    if await ctx.get("active"):
        return {"status": "already_running", "source_id": ctx.key()}
    ctx.set("active", True)
    ctx.object_send(scan, key=ctx.key(), arg={}, send_delay=timedelta(seconds=1))
    return {"status": "started", "source_id": ctx.key()}


@collector.handler()
async def stop(ctx: ObjectContext, req: dict) -> dict:
    ctx.set("active", False)
    return {"status": "stopping", "source_id": ctx.key()}


@collector.handler()
async def scan(ctx: ObjectContext, req: dict) -> dict:
    """One tick: pull since the durable watermark, publish, advance watermark,
    reschedule. `{"oneshot": true}` runs one cycle without (re)scheduling."""
    oneshot = bool(req and req.get("oneshot"))
    if not oneshot and not await ctx.get("active"):
        return {"status": "stopped"}

    watermark = await ctx.get("watermark")
    published, new_watermark, interval, status = await ctx.run(
        "cycle", lambda: run_cycle(ctx.key(), watermark))

    if new_watermark and new_watermark != watermark:
        ctx.set("watermark", new_watermark)
    if published:
        print(f"[collector] {ctx.key()}: published {published} "
              f"(watermark → {new_watermark})", flush=True)

    if not oneshot and status != "unknown_source":
        ctx.object_send(scan, key=ctx.key(), arg={}, send_delay=timedelta(seconds=interval))
    return {"status": status, "published": published, "watermark": new_watermark}


@collector.handler()
async def status(ctx: ObjectContext, req: dict) -> dict:
    return {"source_id": ctx.key(), "active": bool(await ctx.get("active")),
            "watermark": await ctx.get("watermark")}
